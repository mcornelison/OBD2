"""Guarded stale `.git/index.lock` clearer for the shared chi-nas-01 checkout.

Pays down TD-057 (US-467 / F-118). On the slow SMB share a crashed or orphaned
`git` process leaves a 0-byte `.git/index.lock` that blocks every write git op
(`add`/`commit`/`stash`) for all agents while reads keep working. It has recurred
across multiple sprints and each occurrence escalated to a manual PM clear.

This module encodes the heuristic the PM validated by hand (TD-057): a lock is
safe to remove ONLY when it is definitively orphaned, i.e. ALL of --

1. **No live `git` process** owns it (the load-bearing discipline invariant --
   handbook §13 Rule-4: never force a lock while a git process is running).
2. **Aged past a threshold** -- a fresh lock may belong to a commit still
   finishing on the slow share.
3. **Empty (0 bytes)** -- a live commit writes the new index *into* index.lock
   before the atomic rename, so 0 bytes means nothing was pending; a non-empty
   lock is treated as a possible mid-write and refused (fail safe).

`clearStaleIndexLock` is the single-shot decision; `clearStaleIndexLockWithBackoff`
retries with the project backoff schedule so a genuinely-live commit is waited
out (the lock disappears on its own when the commit finishes) rather than
force-cleared. Every destructive branch fails safe: if the guard cannot *prove*
the lock is orphaned, it refuses and the caller escalates.

Usage (CLI -- a safe one-command clear that replaces a manual forensic + `rm`):

    python -m offices.pm.scripts.index_lock --repo .        # clear if verified-stale
    python -m offices.pm.scripts.index_lock --repo . --check # dry-run, decide only

Exit code 0 = safe to proceed (no lock, or the lock was cleared); non-zero = the
guard refused (a live process, a too-fresh lock, or a non-empty lock) and the
situation needs a human. Intended to be wired ahead of PM commit rituals and
Ralph's lock-blocked commit retry (see the TD-057 pay-down note to PM).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# The canonical write-lock git plants under the repo's git dir.
INDEX_LOCK_RELPATH = ".git/index.lock"

# A fresh lock younger than this may belong to a commit still finishing on the
# slow SMB share; refuse to clear it. 120s is deliberately conservative -- a
# healthy commit releases the lock in well under a second even on the share.
DEFAULT_STALE_AGE_SECONDS = 120.0

# Only an empty lock is treated as orphaned (see module docstring, condition 3).
DEFAULT_MAX_STALE_SIZE_BYTES = 0

# Backoff schedule (seconds) for waiting out a live/fresh lock -- the project
# standard [1, 2, 4, 8, 16] retry ladder.
RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)

# Exact process names that count as a live git (exact-match only -- a substring
# match would false-trip on names like "Logitech", per TD-057).
_GIT_PROCESS_NAMES = frozenset({"git", "git.exe"})


class LockDecision(Enum):
    """The outcome of a guarded stale-lock evaluation."""

    ABSENT = "absent"  # no lock present -- safe to proceed
    CLEARED = "cleared"  # verified-stale lock removed (or would-remove on dry-run)
    REFUSED_GIT_LIVE = "refused_git_live"  # a live git process may own it
    REFUSED_TOO_FRESH = "refused_too_fresh"  # younger than the age threshold
    REFUSED_NONEMPTY = "refused_nonempty"  # non-zero -- possible mid-write


# Decisions on which retrying (waiting) could plausibly change the outcome: a
# live commit finishes (-> ABSENT) or a borderline-fresh lock ages out.
_WAITABLE = frozenset({LockDecision.REFUSED_GIT_LIVE, LockDecision.REFUSED_TOO_FRESH})


@dataclass(frozen=True)
class LockCheckResult:
    """The verdict of a stale-lock evaluation.

    Attributes:
        decision: The `LockDecision` reached.
        path: The `.git/index.lock` path evaluated.
        sizeBytes: Lock size in bytes, or None when no lock was present.
        ageSeconds: Lock mtime age in seconds, or None when no lock was present.
        message: A human-readable one-line summary.
    """

    decision: LockDecision
    path: Path
    sizeBytes: int | None
    ageSeconds: float | None
    message: str

    @property
    def safeToProceed(self) -> bool:
        """True when there is no blocking lock (absent or successfully cleared)."""
        return self.decision in (LockDecision.ABSENT, LockDecision.CLEARED)


def lockPath(repoRoot: Path | str) -> Path:
    """Return the `.git/index.lock` path for the given repo root.

    Args:
        repoRoot: Path to the working-tree root (the dir containing `.git`).

    Returns:
        The `Path` to `<repoRoot>/.git/index.lock` (whether or not it exists).
    """
    return Path(repoRoot) / INDEX_LOCK_RELPATH


def _listGitProcessNames() -> list[str]:
    """List running process image names that exactly equal a git executable.

    Uses `tasklist` on Windows and `ps` elsewhere. Exact-name filtering avoids
    the substring false-match TD-057 warns about (e.g. "Logitech").

    Returns:
        A list containing one entry per matching live git process (empty if none).

    Raises:
        OSError / subprocess.SubprocessError: if the probe cannot be run. Callers
            treat that as "cannot determine" and fail safe.
    """
    if sys.platform.startswith("win"):
        # /FI exact IMAGENAME filter, /NH no header, /FO CSV stable output.
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq git.exe", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            check=False,
        )
        return [
            line for line in completed.stdout.splitlines() if '"git.exe"' in line.lower()
        ]
    # POSIX: -e all processes, -o comm= just the executable name (no header).
    completed = subprocess.run(
        ["ps", "-e", "-o", "comm="], capture_output=True, text=True, check=False
    )
    return [
        line.strip()
        for line in completed.stdout.splitlines()
        if Path(line.strip()).name in _GIT_PROCESS_NAMES
    ]


def _defaultGitProcessRunning() -> bool:
    """Return whether a live `git` process is present (fail-safe on uncertainty).

    Returns:
        True if a git process is detected OR the probe fails. A probe failure
        MUST read as "assume live": uncertainty can never authorize a delete
        (the discipline invariant).
    """
    try:
        return bool(_listGitProcessNames())
    except (OSError, subprocess.SubprocessError):
        return True  # cannot determine -> assume live -> refuse to delete


def clearStaleIndexLock(
    repoRoot: Path | str,
    *,
    ageThresholdSeconds: float = DEFAULT_STALE_AGE_SECONDS,
    maxStaleSizeBytes: int = DEFAULT_MAX_STALE_SIZE_BYTES,
    now: float | None = None,
    gitProcessRunning=None,
    remove: bool = True,
) -> LockCheckResult:
    """Evaluate and (if verified-orphaned) clear the repo's `.git/index.lock`.

    The three orphaned-lock conditions are checked in a fixed order so the
    discipline invariant can never be bypassed: the live-git-process gate is
    evaluated FIRST, before any condition that could authorize a delete.

    Args:
        repoRoot: Working-tree root containing `.git`.
        ageThresholdSeconds: Minimum lock mtime age to consider it stale.
        maxStaleSizeBytes: Maximum lock size (bytes) to consider it orphaned;
            defaults to 0 (only an empty lock qualifies).
        now: Current epoch seconds (injectable for tests); defaults to `time.time()`.
        gitProcessRunning: Zero-arg callable returning whether a live git process
            is present; defaults to the platform detector (fail-safe on error).
        remove: When False, decide only and never delete (a `--check` dry run).

    Returns:
        A `LockCheckResult`. `CLEARED` means verified-stale (and removed unless
        `remove=False`); any `REFUSED_*` means the lock was left untouched.
    """
    lockFile = lockPath(repoRoot)
    if not lockFile.exists():
        return LockCheckResult(
            LockDecision.ABSENT, lockFile, None, None, "no index.lock present"
        )

    stat = lockFile.stat()
    sizeBytes = stat.st_size
    nowTs = time.time() if now is None else now
    ageSeconds = nowTs - stat.st_mtime
    isGitLive = (gitProcessRunning or _defaultGitProcessRunning)()

    # 1) INVARIANT FIRST: never touch a lock a live git process may own.
    if isGitLive:
        return LockCheckResult(
            LockDecision.REFUSED_GIT_LIVE,
            lockFile,
            sizeBytes,
            ageSeconds,
            "refused: a live git process is present (never delete under a live process)",
        )
    # 2) A fresh lock may belong to a commit still finishing on the slow share.
    if ageSeconds < ageThresholdSeconds:
        return LockCheckResult(
            LockDecision.REFUSED_TOO_FRESH,
            lockFile,
            sizeBytes,
            ageSeconds,
            f"refused: lock age {ageSeconds:.0f}s < threshold {ageThresholdSeconds:.0f}s",
        )
    # 3) A non-empty lock may be a mid-write index -- fail safe.
    if sizeBytes > maxStaleSizeBytes:
        return LockCheckResult(
            LockDecision.REFUSED_NONEMPTY,
            lockFile,
            sizeBytes,
            ageSeconds,
            f"refused: lock is {sizeBytes} bytes (> {maxStaleSizeBytes}); possible mid-write",
        )

    # Verified orphaned: empty, aged, no live git process.
    verb = "would clear (dry-run)" if not remove else "cleared"
    if remove:
        lockFile.unlink()
    return LockCheckResult(
        LockDecision.CLEARED,
        lockFile,
        sizeBytes,
        ageSeconds,
        f"{verb} verified-stale index.lock (empty, age {ageSeconds:.0f}s, no git process)",
    )


def clearStaleIndexLockWithBackoff(
    repoRoot: Path | str,
    *,
    retrySchedule: tuple[float, ...] = RETRY_BACKOFF_SECONDS,
    sleep=time.sleep,
    **kwargs,
) -> LockCheckResult:
    """Clear a stale lock, waiting out a live/fresh lock with backoff first.

    Retries only on outcomes that waiting could change (a live commit finishing,
    or a borderline-fresh lock aging out). A non-empty lock is terminal -- it
    won't cure by waiting -- so it returns immediately for escalation. The
    discipline invariant holds across every retry: a persistently-live lock is
    refused (never deleted) after the schedule is exhausted.

    Args:
        repoRoot: Working-tree root containing `.git`.
        retrySchedule: Backoff delays (seconds) between re-probes.
        sleep: Sleep callable (injectable for tests); defaults to `time.sleep`.
        **kwargs: Forwarded to `clearStaleIndexLock` (thresholds, injectors).

    Returns:
        The final `LockCheckResult` after the last probe.
    """
    result = clearStaleIndexLock(repoRoot, **kwargs)
    for delay in retrySchedule:
        if result.decision not in _WAITABLE:
            return result  # terminal: absent, cleared, or non-empty (escalate)
        sleep(delay)
        result = clearStaleIndexLock(repoRoot, **kwargs)
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: clear a verified-stale `.git/index.lock` or refuse safely.

    Args:
        argv: Argument vector (defaults to `sys.argv[1:]`).

    Returns:
        0 when safe to proceed (no lock or it was cleared); 2 when the guard
        refused (a live process, a too-fresh lock, or a non-empty lock).
    """
    parser = argparse.ArgumentParser(
        prog="index_lock",
        description="Guarded clear of a verified-stale .git/index.lock (TD-057).",
    )
    parser.add_argument("--repo", default=".", help="repo root containing .git (default: .)")
    parser.add_argument(
        "--age-threshold",
        type=float,
        default=DEFAULT_STALE_AGE_SECONDS,
        help=f"min lock age in seconds to treat as stale (default: {DEFAULT_STALE_AGE_SECONDS:.0f})",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=len(RETRY_BACKOFF_SECONDS),
        help="number of backoff retries to wait out a live/fresh lock (default: full schedule)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="dry-run: decide only, never delete",
    )
    args = parser.parse_args(argv)

    schedule = RETRY_BACKOFF_SECONDS[: max(args.retries, 0)]
    result = clearStaleIndexLockWithBackoff(
        args.repo,
        retrySchedule=schedule,
        ageThresholdSeconds=args.age_threshold,
        remove=not args.check,
    )
    print(f"[index_lock] {result.decision.value}: {result.message}")
    return 0 if result.safeToProceed else 2


if __name__ == "__main__":
    raise SystemExit(main())
