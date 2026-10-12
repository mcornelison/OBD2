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
# 2026-10-08    | Atlas (US-418)| ACTIVE now demotes to IDLE after 12
#                               consecutive EMPTY pushes (CIO 2026-10-08).
#                               MEASURED 10-07: the startup backlog drain
#                               promoted a parked Pi 1 s after start and
#                               nothing demoted it for 15.8 h -- 330/362
#                               pushes at 5 s. "drive_end is the ONLY way
#                               out of ACTIVE" was the defect, not a rule.
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
    DEFAULT_ACTIVE_DEMOTE_EMPTY_PUSHES,
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
        # While in ACTIVE, ONE empty sync does NOT demote back to IDLE.
        # (US-418: a RUN of empty pushes does -- see TestEmptyPushDemotion.
        # This used to say "drive_end is the ONLY way out of ACTIVE", which
        # is exactly what pinned a parked Pi at 5 s for its whole uptime.)
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


class TestEmptyPushDemotion:
    """
    US-418 (CIO 2026-10-08): ACTIVE demotes to IDLE after
    ``DEFAULT_ACTIVE_DEMOTE_EMPTY_PUSHES`` (12) CONSECUTIVE empty pushes.

    Threshold + consecutive dwell (specs/design-patterns.md section 1): one
    empty push is noise; a run of them means nothing is being produced. In a
    real drive every 5 s push carries realtime_data, so only a capture stall
    of ~60 s demotes, and the next non-empty push re-promotes via the
    missed-drive_start fallback.
    """

    def _emptyPushes(self, controller: SyncCadenceController, n: int) -> None:
        for _ in range(n):
            controller.markSynced(hadRows=False)

    def test_demoteThreshold_default_is12(self) -> None:
        assert DEFAULT_ACTIVE_DEMOTE_EMPTY_PUSHES == 12

    def test_fallbackActive_demotesAfter12ConsecutiveEmptyPushes(
        self, controller: SyncCadenceController
    ) -> None:
        # The MEASURED 10-07 case: the startup backlog drain is the one
        # non-empty push, then the parked Pi has nothing to send.
        controller.markSynced(hadRows=True)
        assert controller.state == SyncCadenceState.ACTIVE
        self._emptyPushes(controller, 11)
        assert controller.state == SyncCadenceState.ACTIVE
        controller.markSynced(hadRows=False)
        assert controller.state == SyncCadenceState.IDLE

    def test_driveStartActive_alsoDemotesAfter12EmptyPushes(
        self, controller: SyncCadenceController
    ) -> None:
        # One rule for every ACTIVE (CIO ruling as stated): a drive whose
        # pushes are empty for ~60 s is a capture stall, not a live stream.
        controller.onDriveStart()
        self._emptyPushes(controller, 12)
        assert controller.state == SyncCadenceState.IDLE

    def test_nonEmptyPush_resetsTheRun(
        self, controller: SyncCadenceController
    ) -> None:
        # CONSECUTIVE, not k-of-n: a single row restarts the count.
        controller.onDriveStart()
        self._emptyPushes(controller, 11)
        controller.markSynced(hadRows=True)
        self._emptyPushes(controller, 11)
        assert controller.state == SyncCadenceState.ACTIVE

    def test_reEnteringActive_startsAFreshRun(
        self, controller: SyncCadenceController
    ) -> None:
        # Empties counted in a previous ACTIVE stint must not carry over.
        controller.onDriveStart()
        self._emptyPushes(controller, 12)
        assert controller.state == SyncCadenceState.IDLE
        controller.markSynced(hadRows=True)  # fallback re-promotes
        self._emptyPushes(controller, 11)
        assert controller.state == SyncCadenceState.ACTIVE

    def test_afterDemotion_cadenceIsTheIdleHeartbeat(
        self, controller: SyncCadenceController, clock: FakeClock
    ) -> None:
        controller.markSynced(hadRows=True)
        self._emptyPushes(controller, 12)
        clock.advance(DEFAULT_ACTIVE_CADENCE_SECONDS)
        assert controller.shouldSyncNow() is False
        clock.advance(DEFAULT_IDLE_CADENCE_SECONDS - DEFAULT_ACTIVE_CADENCE_SECONDS)
        assert controller.shouldSyncNow() is True

    def test_demotion_isLogged(
        self, controller: SyncCadenceController, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The exit test reads this line in the journal: promotions and
        # demotions must balance over a parked window.
        controller.markSynced(hadRows=True)
        with caplog.at_level("INFO", logger=SyncCadenceController.__module__):
            self._emptyPushes(controller, 12)
        assert any(
            "ACTIVE -> IDLE" in r.getMessage() and "12 consecutive empty" in r.getMessage()
            for r in caplog.records
        )

    def test_constructor_acceptsDemoteOverride(self, clock: FakeClock) -> None:
        controller = SyncCadenceController(now=clock, demoteAfterEmptyPushes=3)
        controller.onDriveStart()
        self._emptyPushes(controller, 3)
        assert controller.state == SyncCadenceState.IDLE

    def test_draining_isUnaffected(
        self, controller: SyncCadenceController
    ) -> None:
        # DRAINING still resolves to IDLE on its one flush, empty or not.
        controller.onDriveStart()
        self._emptyPushes(controller, 5)
        controller.onDriveEnd()
        controller.markSynced(hadRows=False)
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
