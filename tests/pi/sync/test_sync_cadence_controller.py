################################################################################
# File Name: test_sync_cadence_controller.py
# Purpose/Description: Tests for SyncCadenceController state machine
#                      (IDLE/ACTIVE/DRAINING) per B-053 Story 1 / US-298.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex (US-298) | Initial implementation: parametrized state-
#                               transition fixture + missed-drive-start
#                               fallback + cadence-by-state shouldSyncNow
#                               contract.
# ================================================================================
################################################################################

"""
Tests for the engine-aware sync cadence controller.

The controller drives a 3-state machine (IDLE / ACTIVE / DRAINING) so the
sync loop polls 60s in idle, 5s during a drive, and fires one final flush
on drive_end before returning to idle.  Per B-053 Option 2 (CIO 2026-05-05)
this replaces the constant 5/sec polling that produced 100k+ sync_log rows.

These tests would FAIL pre-fix because the module does not exist (per
runtime-validation rule -- Sprint 21 retro feedback_runtime_validation_required.md).
"""

from __future__ import annotations

import pytest

from pi.sync.sync_cadence_controller import (
    DEFAULT_ACTIVE_CADENCE_SECONDS,
    DEFAULT_IDLE_CADENCE_SECONDS,
    SyncCadenceController,
    SyncCadenceState,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class FakeClock:
    """Injectable monotonic clock for deterministic cadence tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def controller(clock: FakeClock) -> SyncCadenceController:
    return SyncCadenceController(now=clock)


# ---------------------------------------------------------------------------
# State transitions (drive lifecycle)
# ---------------------------------------------------------------------------


class TestStateTransitions:
    """B-053 Story 1 acceptance: IDLE / ACTIVE / DRAINING transitions."""

    def test_initialState_isIdle(
        self, controller: SyncCadenceController
    ) -> None:
        assert controller.state == SyncCadenceState.IDLE

    def test_onDriveStart_idle_transitionsToActive(
        self, controller: SyncCadenceController
    ) -> None:
        controller.onDriveStart()
        assert controller.state == SyncCadenceState.ACTIVE

    def test_onDriveEnd_active_transitionsToDraining(
        self, controller: SyncCadenceController
    ) -> None:
        controller.onDriveStart()
        controller.onDriveEnd()
        assert controller.state == SyncCadenceState.DRAINING

    def test_markSynced_draining_transitionsToIdle(
        self, controller: SyncCadenceController, clock: FakeClock
    ) -> None:
        # Walk the full lifecycle then prove DRAINING resolves to IDLE
        # after the single final flush
        controller.onDriveStart()
        controller.onDriveEnd()
        assert controller.state == SyncCadenceState.DRAINING
        controller.markSynced(hadRows=True)
        assert controller.state == SyncCadenceState.IDLE

    def test_markSynced_draining_emptyFlush_transitionsToIdle(
        self, controller: SyncCadenceController
    ) -> None:
        # The flush is "single", not "successful w/ rows" -- DRAINING
        # must clear even if there happened to be nothing left to push
        # (e.g. delta already drained mid-drive)
        controller.onDriveStart()
        controller.onDriveEnd()
        controller.markSynced(hadRows=False)
        assert controller.state == SyncCadenceState.IDLE


# ---------------------------------------------------------------------------
# Cadence by state (shouldSyncNow contract)
# ---------------------------------------------------------------------------


class TestShouldSyncNowCadence:
    """B-053 Story 1: IDLE=60s heartbeat, ACTIVE=5s, DRAINING=immediate."""

    def test_idle_firstTick_isDue(
        self, controller: SyncCadenceController
    ) -> None:
        # Fresh controller -- never synced -- first decision is "yes"
        # so the sync loop establishes a baseline cursor.
        assert controller.shouldSyncNow() is True

    def test_idle_underHeartbeat_isNotDue(
        self, controller: SyncCadenceController, clock: FakeClock
    ) -> None:
        controller.markSynced()
        clock.advance(DEFAULT_IDLE_CADENCE_SECONDS - 1.0)
        assert controller.shouldSyncNow() is False

    def test_idle_atHeartbeat_isDue(
        self, controller: SyncCadenceController, clock: FakeClock
    ) -> None:
        controller.markSynced()
        clock.advance(DEFAULT_IDLE_CADENCE_SECONDS)
        assert controller.shouldSyncNow() is True

    def test_active_underActiveCadence_isNotDue(
        self, controller: SyncCadenceController, clock: FakeClock
    ) -> None:
        controller.onDriveStart()
        controller.markSynced()
        clock.advance(DEFAULT_ACTIVE_CADENCE_SECONDS - 0.1)
        assert controller.shouldSyncNow() is False

    def test_active_atActiveCadence_isDue(
        self, controller: SyncCadenceController, clock: FakeClock
    ) -> None:
        controller.onDriveStart()
        controller.markSynced()
        clock.advance(DEFAULT_ACTIVE_CADENCE_SECONDS)
        assert controller.shouldSyncNow() is True

    def test_draining_isAlwaysDue(
        self, controller: SyncCadenceController
    ) -> None:
        # Single final flush invariant: DRAINING means "fire NOW regardless
        # of cooldown" -- the flush IS the only sync that should happen
        # in this state.
        controller.onDriveStart()
        controller.markSynced()  # Establish a recent sync timestamp
        controller.onDriveEnd()
        # No clock advance -- but DRAINING ignores cadence and fires
        assert controller.shouldSyncNow() is True

    def test_idle_dropsBackToHeartbeat_afterDraining(
        self, controller: SyncCadenceController, clock: FakeClock
    ) -> None:
        # Full lifecycle: drive ends, flush completes, controller back
        # to 60s heartbeat (NOT 5s ACTIVE leftover).
        controller.onDriveStart()
        controller.onDriveEnd()
        controller.markSynced(hadRows=True)
        clock.advance(DEFAULT_ACTIVE_CADENCE_SECONDS + 1.0)
        # If the controller forgot to drop back to IDLE cadence, this
        # would be True after only ACTIVE+1 seconds.
        assert controller.shouldSyncNow() is False
        clock.advance(DEFAULT_IDLE_CADENCE_SECONDS - DEFAULT_ACTIVE_CADENCE_SECONDS)
        assert controller.shouldSyncNow() is True


# ---------------------------------------------------------------------------
# Missed drive_start fallback (B-053 Story 1 invariant)
# ---------------------------------------------------------------------------


class TestMissedDriveStartFallback:
    """
    Invariant: any non-empty heartbeat sync in IDLE auto-switches to ACTIVE.

    Why: drive_start is delivered by the OBD layer's onDriveStart callback;
    if Bluetooth flakes at engine startup the callback may never fire.  We
    must NOT spend a whole drive at 60s cadence because of one missed
    event.  An IDLE-state heartbeat that comes back with rows is a strong
    signal that the engine actually started.
    """

    def test_idle_heartbeat_withRows_promotesToActive(
        self, controller: SyncCadenceController
    ) -> None:
        # Pre-fix: in IDLE, markSynced(hadRows=True) leaves state in IDLE
        # (because no drive_start was observed).  The fallback fixes this.
        controller.markSynced(hadRows=True)
        assert controller.state == SyncCadenceState.ACTIVE

    def test_idle_heartbeat_withoutRows_staysIdle(
        self, controller: SyncCadenceController
    ) -> None:
        # Empty heartbeats are the normal idle case -- DO NOT escalate
        # cadence on every empty poll.
        controller.markSynced(hadRows=False)
        assert controller.state == SyncCadenceState.IDLE

    def test_active_heartbeat_withoutRows_staysActive(
        self, controller: SyncCadenceController
    ) -> None:
        # While in ACTIVE, an empty sync does NOT demote back to IDLE.
        # drive_end is the ONLY way out of ACTIVE.
        controller.onDriveStart()
        controller.markSynced(hadRows=False)
        assert controller.state == SyncCadenceState.ACTIVE

    def test_draining_heartbeat_withRows_doesNotStayActive(
        self, controller: SyncCadenceController
    ) -> None:
        # The fallback is for missed drive_start; DRAINING must always
        # resolve to IDLE (one final flush, no matter the rowcount).
        controller.onDriveStart()
        controller.onDriveEnd()
        controller.markSynced(hadRows=True)
        assert controller.state == SyncCadenceState.IDLE


# ---------------------------------------------------------------------------
# Cadence values come from constants (no magic numbers invariant)
# ---------------------------------------------------------------------------


class TestCadenceConstants:
    """Invariant: cadence values come from named module constants."""

    def test_idleCadence_default_is60Seconds(self) -> None:
        # B-053 Option 2 + CIO 2026-05-07: IDLE = 60s heartbeat
        assert DEFAULT_IDLE_CADENCE_SECONDS == 60.0

    def test_activeCadence_default_is5Seconds(self) -> None:
        # B-053 Option 2 + CIO 2026-05-07: ACTIVE = 5s
        assert DEFAULT_ACTIVE_CADENCE_SECONDS == 5.0

    def test_constructor_acceptsCadenceOverrides(
        self, clock: FakeClock
    ) -> None:
        # Sprint 27+ will config-wire these; the constructor surface
        # has to exist now so Sprint 27 is a config-touch only.
        controller = SyncCadenceController(
            now=clock, idleSeconds=120.0, activeSeconds=2.0
        )
        controller.markSynced()
        clock.advance(119.5)
        assert controller.shouldSyncNow() is False
        clock.advance(0.5)
        assert controller.shouldSyncNow() is True


# ---------------------------------------------------------------------------
# Event-listener pattern (non-blocking invariant)
# ---------------------------------------------------------------------------


class TestEventHandlersNonBlocking:
    """
    Invariant: drive_start / drive_end event handlers do NOT perform I/O
    or block.  They mutate state only -- the cadence loop polls
    shouldSyncNow() to decide whether to actually fire a sync.
    """

    def test_onDriveStart_doesNotCallSyncClient(
        self, controller: SyncCadenceController
    ) -> None:
        # The controller must not depend on a SyncClient at all.
        # Importing/constructing it without one is the contract.
        controller.onDriveStart()  # No exception means no I/O attempted

    def test_onDriveEnd_doesNotCallSyncClient(
        self, controller: SyncCadenceController
    ) -> None:
        controller.onDriveStart()
        controller.onDriveEnd()  # Same -- pure state mutation
