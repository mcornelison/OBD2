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


def test_clearStaleIndexLock_nonEmptyLock_refusesAndKeepsLock(tmp_path):
    """
    Given: a NON-empty aged lock, no git process
    When: the guard runs
    Then: it REFUSES (non-zero = a commit may have been mid-write; fail safe)
    """
    lockFile = _plantLock(tmp_path, contents=b"partial index bytes", ageSeconds=9999.0)
    result = clearStaleIndexLock(tmp_path, gitProcessRunning=lambda: False)
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


def test_backoff_nonEmpty_isTerminalNoSpin(tmp_path):
    """
    Given: an aged NON-empty lock with no git process
    When: the backoff clearer runs
    Then: it returns immediately without sleeping (non-empty won't cure by waiting)
    """
    _plantLock(tmp_path, contents=b"bytes", ageSeconds=9999.0)
    slept: list[float] = []
    result = clearStaleIndexLockWithBackoff(
        tmp_path, gitProcessRunning=lambda: False, sleep=slept.append
    )
    assert result.decision is LockDecision.REFUSED_NONEMPTY
    assert slept == []  # did not spin


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
