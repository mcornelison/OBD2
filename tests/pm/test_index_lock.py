################################################################################
# File Name: test_index_lock.py
# Purpose/Description: Tests for offices.pm.scripts.index_lock -- the guarded
#                      stale .git/index.lock clearer (TD-057 / US-467 / F-118).
#                      Proves the discipline invariant: NEVER delete a lock a
#                      live git process may own; only clear a verified-orphaned
#                      (no-git-process AND aged-past-threshold AND empty) lock.
# Author: Rex (Ralph / windows-dev)
# Creation Date: 2026-07-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-13    | Rex (Ralph)  | Initial implementation -- US-467 TDD
# 2026-08-11    | Rex (Ralph)  | US-554: two-sample stability probe (BL-032) --
#               |              | a STABLE non-empty orphan is now clearable; a
#               |              | lock still changing between samples is not.
# ================================================================================
################################################################################

"""Tests for offices.pm.scripts.index_lock (TD-057 stale index.lock guard)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from offices.pm.scripts import index_lock
from offices.pm.scripts.index_lock import (
    DEFAULT_SETTLE_INTERVAL_SECONDS,
    DEFAULT_STALE_AGE_SECONDS,
    LockDecision,
    clearStaleIndexLock,
    clearStaleIndexLockWithBackoff,
    lockPath,
    main,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _makeGitDir(repoRoot: Path) -> Path:
    """Create a bare .git dir under repoRoot and return the lock path."""
    (repoRoot / ".git").mkdir(parents=True, exist_ok=True)
    return lockPath(repoRoot)


def _plantLock(repoRoot: Path, *, contents: bytes = b"", ageSeconds: float = 9999.0) -> Path:
    """Plant a .git/index.lock with the given size and mtime-age (seconds ago)."""
    lockFile = _makeGitDir(repoRoot)
    lockFile.write_bytes(contents)
    past = os.stat(lockFile).st_mtime - ageSeconds
    os.utime(lockFile, (past, past))
    return lockFile


def _growDuringSettle(lockFile: Path, extra: bytes = b" ...more index bytes"):
    """Return a settleSleep callable that APPENDS to the lock while we wait.

    This is what a genuinely live mid-write looks like from the guard's side:
    between the two stability samples the file changes. Driving it through the
    real filesystem (rather than a stubbed stat) keeps the test honest about
    what the probe actually compares.
    """
    def settleSleep(_delaySeconds: float) -> None:
        with lockFile.open("ab") as handle:
            handle.write(extra)

    return settleSleep


# ---------------------------------------------------------------------------
# single-shot guarded clear -- the core decision matrix
# ---------------------------------------------------------------------------

def test_clearStaleIndexLock_noLock_returnsAbsent(tmp_path):
    """
    Given: a repo with no .git/index.lock
    When: the guard runs
    Then: decision is ABSENT (nothing to clear, safe to proceed)
    """
    _makeGitDir(tmp_path)
    result = clearStaleIndexLock(tmp_path, gitProcessRunning=lambda: False)
    assert result.decision is LockDecision.ABSENT


def test_clearStaleIndexLock_staleEmptyNoGit_clearsIt(tmp_path):
    """
    Given: a 0-byte lock aged past threshold, no live git process
    When: the guard runs
    Then: decision is CLEARED and the lock file is removed (validationCriterion #1)
    """
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=DEFAULT_STALE_AGE_SECONDS + 60)
    result = clearStaleIndexLock(tmp_path, gitProcessRunning=lambda: False)
    assert result.decision is LockDecision.CLEARED
    assert not lockFile.exists()


def test_clearStaleIndexLock_liveGitProcess_refusesAndKeepsLock(tmp_path):
    """
    Given: a lock that LOOKS stale (empty + old) BUT a live git process is present
    When: the guard runs
    Then: it REFUSES and never deletes -- the load-bearing discipline invariant
    """
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=DEFAULT_STALE_AGE_SECONDS + 60)
    result = clearStaleIndexLock(tmp_path, gitProcessRunning=lambda: True)
    assert result.decision is LockDecision.REFUSED_GIT_LIVE
    assert lockFile.exists()  # NEVER deleted under a live process


def test_clearStaleIndexLock_tooFresh_refusesAndKeepsLock(tmp_path):
    """
    Given: an empty lock younger than the age threshold, no git process
    When: the guard runs
    Then: it REFUSES (a fresh lock may belong to a commit finishing on slow SMB)
    """
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=1.0)
    result = clearStaleIndexLock(
        tmp_path, ageThresholdSeconds=120.0, gitProcessRunning=lambda: False
    )
    assert result.decision is LockDecision.REFUSED_TOO_FRESH
    assert lockFile.exists()


def test_clearStaleIndexLock_nonEmptyMidWriteLock_refusesAndKeepsLock(tmp_path):
    """
    Given: a NON-empty aged lock that is STILL GROWING (a live mid-write index)
    When: the guard runs
    Then: it REFUSES (the two samples differ -> something is writing; fail safe)

    US-554 narrowed this refusal: it used to fire on ANY non-empty lock, which is
    what made BL-032 (a 376467-byte crashed-mid-write ORPHAN) unhealable. The
    refusal now keys on CHANGE between samples, not on size.
    """
    lockFile = _plantLock(tmp_path, contents=b"partial index bytes", ageSeconds=9999.0)
    result = clearStaleIndexLock(
        tmp_path,
        gitProcessRunning=lambda: False,
        settleSleep=_growDuringSettle(lockFile),
        settleIntervalSeconds=0.0,
    )
    assert result.decision is LockDecision.REFUSED_NONEMPTY
    assert lockFile.exists()


def test_clearStaleIndexLock_removeFalse_isDryRun(tmp_path):
    """
    Given: a verified-stale lock and remove=False (a --check dry run)
    When: the guard runs
    Then: it reports CLEARED-would but leaves the file in place
    """
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=9999.0)
    result = clearStaleIndexLock(tmp_path, gitProcessRunning=lambda: False, remove=False)
    assert result.decision is LockDecision.CLEARED
    assert lockFile.exists()  # dry-run does not delete


def test_clearStaleIndexLock_checkOrder_gitLiveBeatsEverything(tmp_path):
    """
    Given: a lock that is ALSO too-fresh AND non-empty, with a live git process
    When: the guard runs
    Then: the git-live refusal wins -- the invariant is checked first
    """
    _plantLock(tmp_path, contents=b"bytes", ageSeconds=0.0)
    result = clearStaleIndexLock(tmp_path, gitProcessRunning=lambda: True)
    assert result.decision is LockDecision.REFUSED_GIT_LIVE


# ---------------------------------------------------------------------------
# retry-with-backoff -- wait out a live/fresh lock, only clear when confirmed
# ---------------------------------------------------------------------------

def test_backoff_liveThenClears_waitsThenClears(tmp_path):
    """
    Given: a git process live on the first probe but gone afterward
    When: the backoff clearer runs
    Then: it sleeps (backoff) then clears once the process is gone (never deletes early)
    """
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=9999.0)
    calls = {"n": 0}

    def gitRunning() -> bool:
        calls["n"] += 1
        return calls["n"] == 1  # live only on the first probe

    slept: list[float] = []
    result = clearStaleIndexLockWithBackoff(
        tmp_path,
        gitProcessRunning=gitRunning,
        sleep=slept.append,
        retrySchedule=(1, 2, 4),
    )
    assert result.decision is LockDecision.CLEARED
    assert not lockFile.exists()
    assert slept == [1]  # waited exactly one backoff step before the lock went stale


def test_backoff_persistentlyLive_neverDeletes(tmp_path):
    """
    Given: a git process live on EVERY probe (a long commit on slow SMB)
    When: the backoff clearer exhausts its schedule
    Then: it refuses and the lock is NEVER deleted (invariant holds across retries)
    """
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=9999.0)
    slept: list[float] = []
    result = clearStaleIndexLockWithBackoff(
        tmp_path,
        gitProcessRunning=lambda: True,
        sleep=slept.append,
        retrySchedule=(1, 2, 4),
    )
    assert result.decision is LockDecision.REFUSED_GIT_LIVE
    assert lockFile.exists()
    assert slept == [1, 2, 4]  # exhausted the full backoff schedule, still refused


def test_backoff_nonEmptyMidWrite_isTerminalNoSpin(tmp_path):
    """
    Given: an aged NON-empty lock that changes between samples, no git process
    When: the backoff clearer runs
    Then: it returns immediately without spinning the BACKOFF schedule

    Note the two sleeps are distinct: `sleep` is the backoff ladder (asserted
    unused here), `settleSleep` is the in-probe stability interval.
    """
    lockFile = _plantLock(tmp_path, contents=b"bytes", ageSeconds=9999.0)
    slept: list[float] = []
    result = clearStaleIndexLockWithBackoff(
        tmp_path,
        gitProcessRunning=lambda: False,
        sleep=slept.append,
        settleSleep=_growDuringSettle(lockFile),
        settleIntervalSeconds=0.0,
    )
    assert result.decision is LockDecision.REFUSED_NONEMPTY
    assert slept == []  # did not spin the backoff ladder


def test_backoff_absent_returnsImmediately(tmp_path):
    """
    Given: no lock at all
    When: the backoff clearer runs
    Then: ABSENT, no sleeps
    """
    _makeGitDir(tmp_path)
    slept: list[float] = []
    result = clearStaleIndexLockWithBackoff(
        tmp_path, gitProcessRunning=lambda: False, sleep=slept.append
    )
    assert result.decision is LockDecision.ABSENT
    assert slept == []


# ---------------------------------------------------------------------------
# US-554 / BL-032 -- the two-sample stability probe
#
# BL-032's lock was 376467 bytes: a crashed `git` wrote the WHOLE index into
# index.lock and died before the atomic rename. Size alone cannot tell that
# orphan apart from a live mid-write, so the guard now asks a question size
# cannot answer -- "is it still CHANGING?" -- by sampling (st_size, st_mtime_ns)
# twice across a settle interval.
# ---------------------------------------------------------------------------

# The exact BL-032 forensics, so the headline test IS the validationCriterion.
BL032_LOCK_SIZE_BYTES = 376467
BL032_LOCK_AGE_SECONDS = 80 * 60.0


def test_clearStaleIndexLock_stableNonEmptyAgedNoGit_clearsIt(tmp_path):
    """
    Given: BL-032 exactly -- a 376467-byte lock, 80 min old, no git process,
           byte-identical across both stability samples
    When: the guard runs
    Then: it CLEARS it via the stable-non-empty path (validationCriterion #1)
    """
    lockFile = _plantLock(
        tmp_path,
        contents=b"x" * BL032_LOCK_SIZE_BYTES,
        ageSeconds=BL032_LOCK_AGE_SECONDS,
    )
    result = clearStaleIndexLock(
        tmp_path,
        gitProcessRunning=lambda: False,
        settleSleep=lambda _delay: None,
    )
    assert result.decision is LockDecision.CLEARED_STABLE_NONEMPTY
    assert result.safeToProceed
    assert not lockFile.exists()
    assert result.sizeBytes == BL032_LOCK_SIZE_BYTES


def test_clearStaleIndexLock_sizeChangesBetweenSamples_refusesNonempty(tmp_path):
    """
    Given: an aged non-empty lock that GROWS during the settle interval
    When: the guard runs
    Then: REFUSED_NONEMPTY -- a changing size means a live writer owns it
    """
    lockFile = _plantLock(tmp_path, contents=b"y" * 4096, ageSeconds=9999.0)
    result = clearStaleIndexLock(
        tmp_path,
        gitProcessRunning=lambda: False,
        settleSleep=_growDuringSettle(lockFile),
        settleIntervalSeconds=0.0,
    )
    assert result.decision is LockDecision.REFUSED_NONEMPTY
    assert lockFile.exists()


def test_clearStaleIndexLock_mtimeChangesBetweenSamples_refusesNonempty(tmp_path):
    """
    Given: an aged non-empty lock whose SIZE is identical across both samples
           but whose mtime moves (a rewrite in place)
    When: the guard runs
    Then: REFUSED_NONEMPTY

    Size alone is not the signal. A writer that rewrites the same number of
    bytes would slip past a size-only comparison, so the probe compares the
    (size, mtime_ns) PAIR. mtime is set explicitly rather than by touching the
    file, so the test does not depend on filesystem clock granularity.
    """
    lockFile = _plantLock(tmp_path, contents=b"z" * 4096, ageSeconds=9999.0)
    sizeBefore = lockFile.stat().st_size

    def rewriteInPlace(_delaySeconds: float) -> None:
        lockFile.write_bytes(b"q" * sizeBefore)  # same size, different content
        moved = os.stat(lockFile).st_mtime + 5.0
        os.utime(lockFile, (moved, moved))

    result = clearStaleIndexLock(
        tmp_path,
        gitProcessRunning=lambda: False,
        settleSleep=rewriteInPlace,
        settleIntervalSeconds=0.0,
    )
    assert lockFile.stat().st_size == sizeBefore  # the size really did not move
    assert result.decision is LockDecision.REFUSED_NONEMPTY
    assert lockFile.exists()


def test_clearStaleIndexLock_stableNonEmptyButGitLive_refusesGitLive(tmp_path):
    """
    Given: a perfectly STABLE aged non-empty lock, but a live git process
    When: the guard runs
    Then: REFUSED_GIT_LIVE and the lock survives -- the invariant still wins

    Stability is a NEW licence to clear, not a bypass of the old gates.
    """
    lockFile = _plantLock(tmp_path, contents=b"stable bytes", ageSeconds=9999.0)
    result = clearStaleIndexLock(
        tmp_path,
        gitProcessRunning=lambda: True,
        settleSleep=lambda _delay: None,
    )
    assert result.decision is LockDecision.REFUSED_GIT_LIVE
    assert lockFile.exists()


def test_clearStaleIndexLock_gitAppearsDuringSettle_refusesGitLive(tmp_path):
    """
    Given: no git process at the first probe, but one running by the second
    When: the guard runs
    Then: REFUSED_GIT_LIVE and the lock survives

    The settle interval OPENS A WINDOW that did not exist before this story: a
    git process can start inside it. Probing only at entry would delete a lock
    under a process that is live at the moment of the unlink.
    """
    lockFile = _plantLock(tmp_path, contents=b"stable bytes", ageSeconds=9999.0)
    probes = {"n": 0}

    def gitRunning() -> bool:
        probes["n"] += 1
        return probes["n"] > 1  # absent at entry, live after the settle

    result = clearStaleIndexLock(
        tmp_path,
        gitProcessRunning=gitRunning,
        settleSleep=lambda _delay: None,
    )
    assert probes["n"] == 2  # non-vacuous: the SECOND probe really happened
    assert result.decision is LockDecision.REFUSED_GIT_LIVE
    assert lockFile.exists()


def test_clearStaleIndexLock_nonEmptyTooFresh_refusesWithoutSettling(tmp_path):
    """
    Given: a non-empty lock YOUNGER than the age threshold, no git process
    When: the guard runs
    Then: REFUSED_TOO_FRESH, and no settle interval is spent at all

    Order matters twice over: the cheap gates stay ahead of the expensive one,
    and a fresh lock must never reach a path that could clear it.
    """
    lockFile = _plantLock(tmp_path, contents=b"fresh bytes", ageSeconds=1.0)
    settled: list[float] = []
    result = clearStaleIndexLock(
        tmp_path,
        ageThresholdSeconds=120.0,
        gitProcessRunning=lambda: False,
        settleSleep=settled.append,
    )
    assert result.decision is LockDecision.REFUSED_TOO_FRESH
    assert lockFile.exists()
    assert settled == []  # never paid the settle cost


def test_clearStaleIndexLock_emptyAgedNoGit_clearsWithoutSettling(tmp_path):
    """
    Given: the original US-467 case -- a 0-byte aged lock, no git process
    When: the guard runs
    Then: plain CLEARED (regression, unchanged) and no settle interval spent

    The empty lock is self-evidently not mid-write, so it must not start
    costing the preflight ~1.5s on the common path.
    """
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=9999.0)
    settled: list[float] = []
    result = clearStaleIndexLock(
        tmp_path, gitProcessRunning=lambda: False, settleSleep=settled.append
    )
    assert result.decision is LockDecision.CLEARED
    assert not lockFile.exists()
    assert settled == []


def test_clearStaleIndexLock_stableNonEmpty_dryRunReportsButKeepsLock(tmp_path):
    """
    Given: a stable non-empty orphan and remove=False (a --check dry run)
    When: the guard runs
    Then: it reports the SAME stable-non-empty verdict but deletes nothing
    """
    lockFile = _plantLock(tmp_path, contents=b"stable bytes", ageSeconds=9999.0)
    result = clearStaleIndexLock(
        tmp_path,
        gitProcessRunning=lambda: False,
        settleSleep=lambda _delay: None,
        remove=False,
    )
    assert result.decision is LockDecision.CLEARED_STABLE_NONEMPTY
    assert lockFile.exists()


def test_clearStaleIndexLock_messagesDistinguishTheTwoClearedPaths(tmp_path):
    """
    Given: an empty orphan and a stable non-empty orphan
    When: each is cleared
    Then: the messages name WHICH evidence authorized the delete

    A PM reading the preflight line needs to know whether the guard removed a
    0-byte nothing or a 376kB index copy -- those warrant different follow-up.
    """
    emptyRepo = tmp_path / "empty"
    stableRepo = tmp_path / "stable"
    _plantLock(emptyRepo, contents=b"", ageSeconds=9999.0)
    _plantLock(stableRepo, contents=b"s" * 2048, ageSeconds=9999.0)

    emptyResult = clearStaleIndexLock(emptyRepo, gitProcessRunning=lambda: False)
    stableResult = clearStaleIndexLock(
        stableRepo, gitProcessRunning=lambda: False, settleSleep=lambda _delay: None
    )

    assert "empty" in emptyResult.message.lower()
    assert "stable" in stableResult.message.lower()
    assert "2 samples" in stableResult.message
    assert "2048" in stableResult.message  # the size it actually removed
    assert "no git" in stableResult.message.lower()


def test_clearStaleIndexLock_allowStableNonEmptyFalse_keepsTheOldRefusal(tmp_path):
    """
    Given: a stable non-empty orphan and allowStableNonEmpty=False
    When: the guard runs
    Then: REFUSED_NONEMPTY -- the pre-US-554 conservative behaviour is still
          reachable for a caller that wants it (the CLI --no-stable-nonempty)
    """
    lockFile = _plantLock(tmp_path, contents=b"stable bytes", ageSeconds=9999.0)
    settled: list[float] = []
    result = clearStaleIndexLock(
        tmp_path,
        gitProcessRunning=lambda: False,
        allowStableNonEmpty=False,
        settleSleep=settled.append,
    )
    assert result.decision is LockDecision.REFUSED_NONEMPTY
    assert lockFile.exists()
    assert settled == []  # opted out -> does not even probe


def test_clearStaleIndexLock_settleIntervalIsHonoured(tmp_path):
    """
    Given: an explicit settleIntervalSeconds
    When: the stability probe runs
    Then: exactly one wait of THAT duration separates the two samples

    A probe that samples twice with no gap between them proves nothing; the
    interval is the whole mechanism, so it is asserted rather than assumed.
    """
    _plantLock(tmp_path, contents=b"stable bytes", ageSeconds=9999.0)
    settled: list[float] = []
    clearStaleIndexLock(
        tmp_path,
        gitProcessRunning=lambda: False,
        settleIntervalSeconds=0.25,
        settleSleep=settled.append,
    )
    assert settled == [0.25]


def test_defaultSettleInterval_isInTheSpecifiedBand():
    """
    Given: the module default settle interval
    When: it is read
    Then: it sits in the [EXACT: ~1.5-2s] band the story specifies

    Grounded in US-554 AC-4. The floor matters: a sub-second interval on the
    slow SMB share could sample twice inside one write's stat granularity.
    """
    assert 1.5 <= DEFAULT_SETTLE_INTERVAL_SECONDS <= 2.0


def test_clearStaleIndexLock_lockVanishesDuringSettle_reportsAbsent(tmp_path):
    """
    Given: a lock that a finishing git renames away during the settle interval
    When: the guard runs
    Then: ABSENT (safe to proceed) -- and no exception escapes the probe

    This is the HAPPY version of the mid-write case: waiting cured it. The
    guard must not crash on the file disappearing between two stats.
    """
    lockFile = _plantLock(tmp_path, contents=b"vanishing bytes", ageSeconds=9999.0)

    def unlinkDuringSettle(_delaySeconds: float) -> None:
        lockFile.unlink()

    result = clearStaleIndexLock(
        tmp_path, gitProcessRunning=lambda: False, settleSleep=unlinkDuringSettle
    )
    assert result.decision is LockDecision.ABSENT
    assert result.safeToProceed


# ---------------------------------------------------------------------------
# default git-process detector -- exact-name match + fail-safe uncertainty
# ---------------------------------------------------------------------------

def test_defaultGitProcessRunning_matchFound_returnsTrue(monkeypatch):
    """
    Given: the process lister reports a git process
    When: the default detector runs
    Then: it returns True
    """
    monkeypatch.setattr(index_lock, "_listGitProcessNames", lambda: ["git.exe"])
    assert index_lock._defaultGitProcessRunning() is True


def test_defaultGitProcessRunning_noMatch_returnsFalse(monkeypatch):
    """
    Given: the process lister reports NO git process
    When: the default detector runs
    Then: it returns False
    """
    monkeypatch.setattr(index_lock, "_listGitProcessNames", lambda: [])
    assert index_lock._defaultGitProcessRunning() is False


def test_defaultGitProcessRunning_probeFails_failsSafeAsLive(monkeypatch):
    """
    Given: the process probe raises (cannot determine process state)
    When: the default detector runs
    Then: it returns True (assume-live) -- uncertainty must NEVER authorize a delete
    """
    def boom() -> list[str]:
        raise OSError("tasklist unavailable")

    monkeypatch.setattr(index_lock, "_listGitProcessNames", boom)
    assert index_lock._defaultGitProcessRunning() is True


# ---------------------------------------------------------------------------
# CLI main -- exit codes + monkeypatched detector
# ---------------------------------------------------------------------------

def test_main_staleLock_clearsAndExitsZero(tmp_path, monkeypatch, capsys):
    """
    Given: a verified-stale lock and no git process
    When: main runs against the repo
    Then: it clears the lock and exits 0 (safe to proceed with the commit)
    """
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=9999.0)
    monkeypatch.setattr(index_lock, "_defaultGitProcessRunning", lambda: False)
    code = main(["--repo", str(tmp_path), "--retries", "0"])
    assert code == 0
    assert not lockFile.exists()
    assert "clear" in capsys.readouterr().out.lower()


def test_main_liveLock_refusesAndExitsNonZero(tmp_path, monkeypatch):
    """
    Given: a lock and a live git process
    When: main runs
    Then: it refuses, keeps the lock, and exits non-zero (escalate)
    """
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=9999.0)
    monkeypatch.setattr(index_lock, "_defaultGitProcessRunning", lambda: True)
    code = main(["--repo", str(tmp_path), "--retries", "0"])
    assert code != 0
    assert lockFile.exists()


def test_main_bl032StableNonEmptyLock_healsAndExitsZero(tmp_path, monkeypatch, capsys):
    """
    Given: BL-032's lock (376467 bytes, 80 min old, stable) and no git process
    When: the PREFLIGHT invocation runs -- `--repo <root>`, no new flags
    Then: it clears the lock, exits 0, and names the stable path

    This is AC-4 itself. ralph.sh:237 calls the module with `--repo` alone, so
    a fix that needs an extra flag to fire is a fix the loop never gets. The
    flag list here is deliberately the ralph.sh line, plus the two knobs that
    keep the test fast and hermetic.
    """
    lockFile = _plantLock(
        tmp_path,
        contents=b"x" * BL032_LOCK_SIZE_BYTES,
        ageSeconds=BL032_LOCK_AGE_SECONDS,
    )
    monkeypatch.setattr(index_lock, "_defaultGitProcessRunning", lambda: False)
    code = main(["--repo", str(tmp_path), "--retries", "0", "--settle-interval", "0"])
    assert code == 0
    assert not lockFile.exists()
    assert "stable" in capsys.readouterr().out.lower()


def test_main_noStableNonEmptyFlag_refusesAndExitsNonZero(tmp_path, monkeypatch):
    """
    Given: the same stable non-empty lock, run with --no-stable-nonempty
    When: main runs
    Then: it refuses and exits non-zero (the conservative pre-US-554 posture)
    """
    lockFile = _plantLock(tmp_path, contents=b"stable bytes", ageSeconds=9999.0)
    monkeypatch.setattr(index_lock, "_defaultGitProcessRunning", lambda: False)
    code = main(["--repo", str(tmp_path), "--retries", "0", "--no-stable-nonempty"])
    assert code != 0
    assert lockFile.exists()


def test_main_checkOnStableNonEmpty_reportsSameVerdictWithoutDeleting(tmp_path, monkeypatch):
    """
    Given: a stable non-empty orphan
    When: main runs with --check
    Then: it reports safe-to-proceed (exit 0) but leaves the lock in place (AC-3)
    """
    lockFile = _plantLock(tmp_path, contents=b"stable bytes", ageSeconds=9999.0)
    monkeypatch.setattr(index_lock, "_defaultGitProcessRunning", lambda: False)
    code = main(
        ["--repo", str(tmp_path), "--retries", "0", "--settle-interval", "0", "--check"]
    )
    assert code == 0
    assert lockFile.exists()  # dry run never deletes


# ---------------------------------------------------------------------------
# AC-4 wiring -- the preflight in ralph.sh must actually reach this module
# ---------------------------------------------------------------------------

def test_ralphShPreflight_invokesTheGuardWithStabilityClearingEnabled():
    """
    Given: ralph.sh's per-iteration preflight
    When:  its executable lines are scanned for the index_lock invocation
    Then:  the guard is invoked, and NOT with --no-stable-nonempty

    Without this the unit tests above are a fix the loop never receives: delete
    the preflight line and every other test in this file still passes. Comments
    are stripped first -- the preflight is documented at length in a comment
    block that also names the module, so an unstripped scan would find the
    module name in prose and call the wiring present when it is not.
    """
    ralphSh = Path(__file__).resolve().parents[2] / "offices" / "ralph" / "ralph.sh"
    executable = [
        line for line in ralphSh.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    invocations = [line for line in executable if "offices.pm.scripts.index_lock" in line]

    # Non-vacuity: the scan must have FOUND the wiring before its shape is judged.
    assert invocations, (
        "ralph.sh no longer invokes the index_lock preflight. US-554's self-heal "
        "only ever runs from that line -- without it a stale lock halts the sprint again."
    )
    for line in invocations:
        assert "--repo" in line
        assert "--no-stable-nonempty" not in line, (
            "the preflight opts OUT of stability-clearing, which re-breaks BL-032."
        )


# ---------------------------------------------------------------------------
# real-git integration -- the end-to-end validationCriterion #1
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_realGit_staleLockClearedThenCommitSucceeds(tmp_path, monkeypatch):
    """
    Given: a real git repo blocked by a stale (empty, aged) .git/index.lock
    When: the backoff clearer runs, then a commit is attempted
    Then: the lock clears and `git commit` succeeds (validationCriterion #1 end-to-end)
    """
    # Arrange -- a real repo with a staged change
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

    def git(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *argv], cwd=tmp_path, env=env, capture_output=True, text=True
        )

    git("init")
    git("config", "user.email", "rex@example.com")
    git("config", "user.name", "Rex")
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    git("add", "file.txt")

    # Plant a stale lock -- a real commit is now blocked
    lockFile = _plantLock(tmp_path, contents=b"", ageSeconds=9999.0)
    assert lockFile.exists()
    blocked = git("commit", "-m", "should be blocked")
    assert blocked.returncode != 0  # the lock genuinely blocks the commit

    # Act -- the guard clears the verified-stale lock (no git process is mid-commit)
    result = clearStaleIndexLockWithBackoff(tmp_path, gitProcessRunning=lambda: False)

    # Assert -- lock gone, and the commit now succeeds
    assert result.decision is LockDecision.CLEARED
    assert not lockFile.exists()
    committed = git("commit", "-m", "unblocked commit")
    assert committed.returncode == 0, committed.stderr
