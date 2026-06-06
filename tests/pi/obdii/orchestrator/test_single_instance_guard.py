################################################################################
# File Name: test_single_instance_guard.py
# Purpose/Description: US-361 (F-107) -- unit tests for the orchestrator
#                      single-instance guard.  The Drive 23/24 production
#                      dual-attribution (Mechanism B in the US-360 RCA) is two
#                      concurrent eclipse-obd orchestrator processes, each with
#                      its own DriveDetector + process-global drive_id, both
#                      minting from the shared drive_counter.  This guard makes a
#                      second concurrent orchestrator REFUSE to start while the
#                      first is alive, so one physical leg cannot be split across
#                      two minting processes.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-361) | Initial -- pidfile single-instance guard with an
#                               injectable process-liveness seam (no real process
#                               spawning required for determinism).
# ================================================================================
################################################################################

"""US-361 -- SingleInstanceGuard unit tests (Feature F-107, Mechanism B).

The guard is a pidfile lock with an injectable ``isAliveFn`` liveness seam so
the four cases below are exercised deterministically without spawning real
processes (mirrors the project's ``_eventWaitForTesting`` injection pattern):

* fresh acquire on a clean path succeeds;
* a second guard whose pidfile holds a *live* foreign PID is REFUSED
  (``SingleInstanceError``) -- the Mechanism-B prevention contract;
* a *stale* pidfile (foreign PID no longer alive) is reclaimed;
* release removes the owned pidfile so a later start re-acquires cleanly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.pi.obdii.orchestrator.single_instance import (
    SingleInstanceError,
    SingleInstanceGuard,
)


@pytest.fixture()
def lockPath(tmp_path: Path) -> Path:
    """A per-test lockfile path inside the pytest tmp dir."""
    return tmp_path / "orchestrator.lock"


class TestSingleInstanceGuard:
    """Acquire / refuse / reclaim / release behavior of the pidfile guard."""

    def test_acquire_cleanPath_writesOwnPidAndSucceeds(self, lockPath: Path) -> None:
        """
        Given: a lock path with no existing pidfile.
        When: a guard acquires it.
        Then: acquisition succeeds and the pidfile holds our PID.
        """
        guard = SingleInstanceGuard(lockPath, pid=4321, isAliveFn=lambda _pid: True)

        guard.acquire()

        assert lockPath.exists()
        assert lockPath.read_text(encoding="utf-8").strip() == "4321"

    def test_acquire_liveForeignHolder_refusesWithSingleInstanceError(
        self, lockPath: Path
    ) -> None:
        """
        Given: a pidfile already held by a DIFFERENT, still-alive PID.
        When: a second guard tries to acquire the same path.
        Then: SingleInstanceError is raised (Mechanism-B prevention) and the
            foreign holder's PID is left untouched.
        """
        lockPath.write_text("9999", encoding="utf-8")

        guard = SingleInstanceGuard(
            lockPath, pid=1234, isAliveFn=lambda pid: pid == 9999
        )

        with pytest.raises(SingleInstanceError) as excinfo:
            guard.acquire()

        assert "9999" in str(excinfo.value)
        # Foreign holder untouched -- we must not steal a live lock.
        assert lockPath.read_text(encoding="utf-8").strip() == "9999"

    def test_acquire_stalePidfile_reclaimsLock(self, lockPath: Path) -> None:
        """
        Given: a pidfile holding a foreign PID that is no longer alive.
        When: a guard acquires the path.
        Then: the stale lock is reclaimed and now holds our PID.
        """
        lockPath.write_text("9999", encoding="utf-8")

        guard = SingleInstanceGuard(
            lockPath, pid=1234, isAliveFn=lambda _pid: False
        )

        guard.acquire()

        assert lockPath.read_text(encoding="utf-8").strip() == "1234"

    def test_acquire_ownStalePid_isReclaimedNotRefused(self, lockPath: Path) -> None:
        """A pidfile holding OUR OWN pid must never refuse us (restart safety)."""
        lockPath.write_text("1234", encoding="utf-8")

        guard = SingleInstanceGuard(
            lockPath, pid=1234, isAliveFn=lambda _pid: True
        )

        guard.acquire()  # must not raise

        assert lockPath.read_text(encoding="utf-8").strip() == "1234"

    def test_release_removesOwnedPidfile(self, lockPath: Path) -> None:
        """
        Given: a guard that acquired a lock.
        When: it releases.
        Then: the pidfile is removed so a later start re-acquires cleanly.
        """
        guard = SingleInstanceGuard(lockPath, pid=1234, isAliveFn=lambda _pid: True)
        guard.acquire()
        assert lockPath.exists()

        guard.release()

        assert not lockPath.exists()

    def test_release_doesNotRemoveForeignHeldPidfile(self, lockPath: Path) -> None:
        """Release after a refused acquire must not delete the live holder's lock."""
        lockPath.write_text("9999", encoding="utf-8")
        guard = SingleInstanceGuard(
            lockPath, pid=1234, isAliveFn=lambda pid: pid == 9999
        )
        with pytest.raises(SingleInstanceError):
            guard.acquire()

        guard.release()  # we never owned it -> no-op

        assert lockPath.exists()
        assert lockPath.read_text(encoding="utf-8").strip() == "9999"

    def test_defaultPid_isCurrentProcess(self, lockPath: Path) -> None:
        """When pid is omitted, the guard stamps the current process id."""
        guard = SingleInstanceGuard(lockPath, isAliveFn=lambda _pid: True)

        guard.acquire()

        assert lockPath.read_text(encoding="utf-8").strip() == str(os.getpid())
