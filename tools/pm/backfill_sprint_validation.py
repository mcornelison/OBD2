#!/usr/bin/env python3
# ==============================================================================
# File:        tools/pm/backfill_sprint_validation.py
# Purpose:     Stamp validation (validatedAt / validatedBy / validatedEvidence)
#              onto an ARCHIVED sprint snapshot, refusing any stamp that
#              outruns its evidence.
# Author:      Rex (Ralph agent) -- US-569
# Created:     2026-08-28
# ==============================================================================
"""Backfill validation onto an archived sprint snapshot (US-569).

Why this tool exists
--------------------
``/sprint-validated`` reads and writes ``$FLEET_SHARE/ralph/sprint.json`` ONLY
-- the CURRENT sprint.  The 26 archived sprints live in
``ralph/archive/sprint.archive.*.json``; ``chain_validate_aggregate`` READS
those archives and nothing WRITES them.  There was no auditable way to record,
after the fact, that an archived sprint was validated.

What this tool is NOT
---------------------
It is **not a merge prerequisite**.  ``chain_validate_aggregate.py:238`` gates
``chainStatus`` on the CHAIN TIP ALONE, and ``:188`` documents
``unvalidatedSprints`` as "informational; does NOT gate chainStatus" under the
CIO 2026-05-23 chain-end-merge rule.  An earlier patch's ``validatedAt = null``
is the EXPECTED state, not a debt.  This tool exists so the 26-sprint record can
be kept honestly, not to unblock anything.

It also does **not** decide whether evidence is sufficient.  It only refuses to
record a stamp that has none.  Judgement stays with the PM and the CIO.

Two traps this tool is built around (Atlas F-8)
-----------------------------------------------
(a) **The inert write.**  52 archive snapshots exist for 27 sprints.  The
    aggregator collapses duplicates via ``_snapshotAuthorityKey``, so stamping a
    non-authoritative snapshot succeeds, reports success, and changes nothing
    the gate reads.  This tool therefore never picks its own target file: it
    asks ``aggregateChain`` which snapshot the READER selects, stamps that one,
    and then RE-RUNS the aggregator to confirm the stamp is visible.  It never
    proves the write by reading the file back.

(b) **No revert.**  The share is not version controlled, and this is a scripted
    rewrite.  ``--dry-run`` and ``--force`` are good and insufficient, so every
    real write additionally requires ``--snapshot-confirmed YYYY-MM-DD`` naming
    a recent, already-verified Synology snapshot (share ``CLAUDE.md``).

Usage
-----
    # Preview -- writes nothing, needs no snapshot confirmation.
    python -m tools.pm.backfill_sprint_validation \\
        --version V0.29.7 --evidence "Drive 112 log; CIO confirmed" --dry-run

    # Real stamp.
    python -m tools.pm.backfill_sprint_validation \\
        --version V0.29.7 \\
        --evidence "Drive 112 log; CIO confirmed 2026-08-28" \\
        --by "Mike (CIO confirmed)" \\
        --snapshot-confirmed 2026-08-28

    # Target a specific archive file instead of a version.
    python -m tools.pm.backfill_sprint_validation \\
        --archive sprint.archive.2026-05-22_015122Z.json --evidence "..." \\
        --snapshot-confirmed 2026-08-28

Exit codes (project convention):
  0  stamped, or a clean --dry-run
  1  refused -- bad/absent arguments, unresolvable target, double stamp
  2  runtime -- unreadable/unparseable snapshot, or a write the reader did not
     pick up (the inert-write guard firing)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from tools.pm import chain_validate_aggregate as aggregate
from tools.pm._encoding import forceUtf8Stdio
from tools.pm._paths import resolveShareRoot

forceUtf8Stdio()

# How recent a Synology snapshot has to be before it counts as a rollback path.
# Anything older describes a tree that no longer resembles the one being
# rewritten, which is not a backup of this change.
SNAPSHOT_MAX_AGE_DAYS = 7

# The three fields this tool owns. Nothing else in the snapshot is touched.
_STAMP_FIELDS = ("validatedAt", "validatedBy", "validatedEvidence")


# ==============================================================================
# Share-relative path construction
# ==============================================================================
# These re-derive what chain_validate_aggregate holds in DEFAULT_ARCHIVE_GLOB /
# DEFAULT_CURRENT_SPRINT.  Reusing those constants directly is not possible:
# they are built from SHARE_ROOT at IMPORT time and so cannot follow a caller's
# $FLEET_SHARE, whereas resolveShareRoot() reads the environment at CALL time.
# The duplicated layout fact is pinned by
# tests/pm/test_backfill_sprint_validation.py::test_pathBuilders_matchTheAggregatorsOwnConstants.
def archiveGlobFor(shareRoot: Path) -> Path:
    """Return the archived-snapshot glob under ``shareRoot``."""
    return shareRoot / "ralph" / "archive" / "sprint.archive.*.json"


def currentSprintFor(shareRoot: Path) -> Path:
    """Return the live sprint.json under ``shareRoot``."""
    return shareRoot / "ralph" / "sprint.json"


def discoverSnapshotPaths() -> list[Path]:
    """Enumerate every sprint snapshot the aggregator would consider.

    Mirrors ``chain_validate_aggregate.discoverChainPaths``: all archived
    snapshots plus the live sprint.json when it exists.  The live file is
    included deliberately -- the current sprint is a legitimate stamp target for
    ``--version``, and leaving it out would let the aggregator select a snapshot
    this tool cannot see.

    Returns:
        Archived snapshot paths, plus the live sprint.json if present.

    Raises:
        RuntimeError: If ``$FLEET_SHARE`` is unset (via ``resolveShareRoot``).
            There is no fallback, on purpose -- see ``tools/pm/_paths.py``.
    """
    shareRoot = resolveShareRoot()
    paths = [Path(p) for p in glob.glob(str(archiveGlobFor(shareRoot)))]
    liveSprint = currentSprintFor(shareRoot)
    if liveSprint.exists():
        paths.append(liveSprint)
    return paths


# ==============================================================================
# Small helpers
# ==============================================================================
def todayIso() -> str:
    """Today's date as ``YYYY-MM-DD``, per the clock this tool validates against."""
    return date.today().isoformat()


def nowIsoUtc() -> str:
    """Current UTC instant as an ISO-8601 ``Z`` timestamp (sprint.json convention)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def defaultValidatedBy() -> str:
    """Who to credit when ``--by`` is not given.

    Suffixed ``(backfill)`` on purpose: the stamp was applied after the fact by
    a script, and the record should say so rather than impersonate a live
    ``/sprint-validated`` run.
    """
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    return f"{user} (backfill)"


def _loadSnapshot(path: Path) -> dict:
    """Read and parse a sprint snapshot.

    Raises:
        OSError, json.JSONDecodeError: Propagated to ``main``, which maps them
            to exit code 2 -- an unreadable snapshot is a runtime fault, not a
            usage error.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def _refuse(message: str) -> int:
    """Print a refusal to stderr and return the refusal exit code."""
    print(f"REFUSED: {message}", file=sys.stderr)
    return 1


# ==============================================================================
# Target resolution -- the aggregator picks, this tool does not
# ==============================================================================
def resolveAuthoritativeSnapshot(version: str) -> Path | None:
    """Return the snapshot ``chain_validate_aggregate`` actually READS for ``version``.

    Delegates to ``aggregateChain`` so the choice is made by the same
    ``_snapshotAuthorityKey`` ranking the gate uses.  Any independent
    file-picking heuristic here would be a second, drifting source of truth --
    and would land the stamp on a snapshot the reader discards (trap a).

    Args:
        version: An exact ``validation.currentVersion``, e.g. ``V0.29.7``.

    Returns:
        The authoritative snapshot path, or None if no snapshot carries that
        version.
    """
    result = aggregate.aggregateChain(discoverSnapshotPaths(), version)
    for record in result["sprintsInChain"]:
        if record["currentVersion"] == version:
            return Path(record["path"])
    return None


def _resolveArchiveArgument(archiveArg: str) -> Path:
    """Resolve ``--archive`` to a concrete path (bare filename or explicit path)."""
    candidate = Path(archiveArg)
    if candidate.parent != Path("."):
        return candidate
    return archiveGlobFor(resolveShareRoot()).parent / archiveArg


# ==============================================================================
# Preconditions
# ==============================================================================
def checkSnapshotConfirmation(value: str | None) -> str | None:
    """Validate ``--snapshot-confirmed``; return a refusal message or None.

    The share has no git history: an unwanted rewrite here is recovered from a
    Synology snapshot or not at all.  So a write asserts that such a snapshot
    exists AND is recent enough to describe the tree being rewritten.  A date
    that is unparseable, in the future, or older than
    ``SNAPSHOT_MAX_AGE_DAYS`` fails -- a precondition nobody can fail is not a
    precondition.
    """
    if not value:
        return (
            "--snapshot-confirmed YYYY-MM-DD is required for a real write. The "
            "fleet share is NOT version controlled -- there is no git revert for "
            "this file. Confirm a recent Synology snapshot first (share "
            "CLAUDE.md), then name its date. Use --dry-run to preview instead."
        )

    try:
        confirmed = date.fromisoformat(value)
    except ValueError:
        return f"--snapshot-confirmed must be an ISO date (YYYY-MM-DD); got {value!r}."

    today = date.today()
    if confirmed > today:
        return (
            f"--snapshot-confirmed {value} is in the future. A snapshot that has "
            "not happened yet is a typo or a fabrication, never a rollback path."
        )
    if confirmed < today - timedelta(days=SNAPSHOT_MAX_AGE_DAYS):
        return (
            f"--snapshot-confirmed {value} is stale (older than "
            f"{SNAPSHOT_MAX_AGE_DAYS} days). Take a fresh Synology snapshot "
            "before rewriting share data."
        )
    return None


# ==============================================================================
# Diff rendering
# ==============================================================================
def renderDiff(path: Path, before: dict, after: dict) -> str:
    """Render the field-level diff this run would apply (or did apply)."""
    lines = [f"{path}"]
    for field in _STAMP_FIELDS:
        old = before.get(field)
        new = after.get(field)
        marker = " " if old == new else "*"
        lines.append(f"  {marker} validation.{field}: {old!r} -> {new!r}")
    return "\n".join(lines)


# ==============================================================================
# CLI
# ==============================================================================
def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.pm.backfill_sprint_validation",
        description=(
            "Stamp validation onto an archived sprint snapshot. Refuses any "
            "stamp with no evidence behind it."
        ),
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--version",
        help="Exact validation.currentVersion to stamp, e.g. V0.29.7",
    )
    selector.add_argument(
        "--archive",
        help=(
            "Archive filename (or path) to stamp. Refused if it is not the "
            "snapshot the aggregator reads for that version."
        ),
    )
    parser.add_argument(
        "--evidence",
        help=(
            "MANDATORY. What the validation actually rests on (drive number, "
            "log, CIO confirmation). Recorded into validation.validatedEvidence."
        ),
    )
    parser.add_argument(
        "--by",
        default=None,
        help=f"validatedBy attribution. Default: {defaultValidatedBy()!r}",
    )
    parser.add_argument(
        "--at",
        default=None,
        help="validatedAt timestamp. Default: now, as ISO-8601 UTC.",
    )
    parser.add_argument(
        "--snapshot-confirmed",
        dest="snapshotConfirmed",
        default=None,
        help=(
            "ISO date of a verified, recent Synology snapshot of the share. "
            "Required for a real write; the share has no git revert."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-stamp a snapshot that already carries a validatedAt.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dryRun",
        action="store_true",
        help="Print the diff and write nothing.",
    )
    return parser


def main(argv: list[str]) -> int:
    args = buildParser().parse_args(argv)

    # --- Evidence first. It is the reason this tool exists, and the refusal
    # must be identical under --dry-run: a preview that skips it is not a
    # preview of the real run.
    evidence = (args.evidence or "").strip()
    if not evidence:
        return _refuse(
            "--evidence is mandatory and must be non-empty. A stamp that "
            "outruns its evidence is the same defect class as a fixture "
            "asserting an unmeasured fact. This tool does not judge whether "
            "the evidence is sufficient -- only that it exists."
        )

    # --- No-revert precondition. Skipped for --dry-run, which cannot destroy
    # anything; gating a preview would only train operators to pass the flag
    # reflexively.
    if not args.dryRun:
        problem = checkSnapshotConfirmation(args.snapshotConfirmed)
        if problem:
            return _refuse(problem)

    # --- Resolve the target via the READER, never by picking a file here.
    try:
        if args.version:
            version = args.version
            target = resolveAuthoritativeSnapshot(version)
            if target is None:
                return _refuse(
                    f"no sprint snapshot carries validation.currentVersion "
                    f"{version!r} under {resolveShareRoot()}."
                )
        else:
            target = _resolveArchiveArgument(args.archive)
            if not target.exists():
                return _refuse(f"no such archive: {target}")
            version = (_loadSnapshot(target).get("validation") or {}).get("currentVersion")
            if not version:
                return _refuse(
                    f"{target} has no validation.currentVersion, so there is "
                    "nothing to stamp and no way to tell whether the "
                    "aggregator reads it."
                )
            authoritative = resolveAuthoritativeSnapshot(version)
            if authoritative is not None and authoritative != target:
                return _refuse(
                    f"{target.name} is NOT the snapshot the aggregator reads for "
                    f"{version}; it reads {authoritative.name}. Stamping "
                    f"{target.name} would succeed and change nothing the gate "
                    f"sees. Re-run with --version {version}, or target "
                    f"{authoritative.name} explicitly."
                )

        original = _loadSnapshot(target)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read {args.archive or args.version}: {exc}", file=sys.stderr)
        return 2

    validation = original.get("validation")
    if not isinstance(validation, dict):
        return _refuse(f"{target} has no validation block to stamp.")

    # --- Double-stamp detection, matching /sprint-validated Phase 0.
    if validation.get("validatedAt") and not args.force:
        return _refuse(
            f"{version} is already stamped: validatedAt="
            f"{validation['validatedAt']!r}, validatedBy="
            f"{validation.get('validatedBy')!r}. Re-run with --force to "
            "overwrite it."
        )

    stamped = {
        "validatedAt": args.at or nowIsoUtc(),
        "validatedBy": args.by or defaultValidatedBy(),
        "validatedEvidence": evidence,
    }

    if args.dryRun:
        print("DRY RUN -- nothing written.")
        print(renderDiff(target, validation, {**validation, **stamped}))
        return 0

    validation.update(stamped)
    target.write_text(
        json.dumps(original, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # --- Prove it by RE-RUNNING the reader, never by reading the file back.
    # A write the aggregator discards is the inert-guard defect, and it is
    # indistinguishable from success at the filesystem level.
    reRead = resolveAuthoritativeSnapshot(version)
    result = aggregate.aggregateChain(discoverSnapshotPaths(), version)
    seen = next(
        (r for r in result["sprintsInChain"] if r["currentVersion"] == version),
        None,
    )
    if reRead != target or seen is None or not seen["validatedAt"]:
        print(
            f"ERROR: wrote {target}, but re-running chain_validate_aggregate "
            f"still does not read {version} as validated (it now reads "
            f"{reRead}). The write was inert -- treat this as a failure, not a "
            f"stamp.",
            file=sys.stderr,
        )
        return 2

    print(f"Stamped {version}.")
    print(renderDiff(target, {}, stamped))
    print(f"Verified by re-running chain_validate_aggregate: {version} reads as validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
