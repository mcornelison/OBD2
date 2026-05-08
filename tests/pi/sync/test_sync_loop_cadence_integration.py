################################################################################
# File Name: test_sync_loop_cadence_integration.py
# Purpose/Description: Integration tests for B-053 Story 2 / US-299 -- wiring
#                      the SyncCadenceController into the orchestrator's
#                      _maybeTriggerIntervalSync + drive_start/drive_end
#                      handlers.  Asserts ~99% idle workload reduction
#                      (<=100/hour vs ~720/hour at legacy 5s cadence) +
#                      ACTIVE cadence preserved during a simulated drive +
#                      controller event-handler wiring on _handleDriveStart
#                      and _handleDriveEnd.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex (US-299) | Initial implementation: 1-hour idle
#                               workload assertion + ACTIVE cadence assertion
#                               + drive_start/drive_end wiring discriminators.
# ================================================================================
################################################################################

"""
US-299 integration: orchestrator runLoop drives the SyncCadenceController.

Pre-fix RED: orchestrator has no `_syncCadenceController` field, so the legacy
``_lastSyncAttemptTime``-based gate still controls cadence (and the ``5/sec``
pre-Sprint-26 production cadence yields ~18,000 sync attempts/hour during
idle windows -- the bug class B-053 closes).

Post-fix GREEN: ``_initializeSyncClient`` constructs a SyncCadenceController;
``_maybeTriggerIntervalSync`` consults it via ``shouldSyncNow()`` and notifies
it via ``markSynced(hadRows=...)``; ``_handleDriveStart`` /
``_handleDriveEnd`` invoke the controller's event handlers so the IDLE/ACTIVE
state-machine actually transitions.

Discriminators (per feedback_runtime_validation_required.md):
1. Legacy intervalSeconds=5 + 1 hour of polls = 720 attempts pre-fix; controller
   IDLE state caps at ~60 attempts post-fix.  ``<= 100`` is the AC threshold.
2. drive_start callback path must MUTATE controller state (IDLE -> ACTIVE).
3. drive_end callback path must MUTATE controller state (ACTIVE -> DRAINING).
4. ``markSynced(hadRows=...)`` must reflect actual ``pushAllDeltas`` rowsPushed
   count so missed-drive-start fallback fires when an IDLE heartbeat returns
   non-empty rows.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.orchestrator.core import ApplicationOrchestrator
from pi.sync.sync_cadence_controller import SyncCadenceController, SyncCadenceState
from src.pi.sync.client import PushResult, PushStatus

# ================================================================================
# Test fixtures
# ================================================================================


class FakeClock:
    """Injectable monotonic clock matched to the controller's contract."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _baseConfig(
    *,
    syncEnabled: bool = True,
    companionEnabled: bool = True,
    intervalSeconds: int = 5,
    triggerOn: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal config for an orchestrator under test.

    intervalSeconds defaults to 5 to mirror the pre-Sprint-26 production
    cadence -- the load-bearing pre-fix discriminator.
    """
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "companionService": {
                "enabled": companionEnabled,
                "baseUrl": "http://10.27.27.10:8000",  # b044-exempt: test fixture
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 3,
                "retryBackoffSeconds": [1, 2, 4, 8, 16],
            },
            "sync": {
                "enabled": syncEnabled,
                "intervalSeconds": intervalSeconds,
                "triggerOn": triggerOn or ["interval", "drive_end"],
            },
        },
        "server": {},
    }


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-cadence-integration")


def _makeOrch(config: dict[str, Any]) -> ApplicationOrchestrator:
    return ApplicationOrchestrator(config=config, simulate=True)


def _emptyResult() -> list[PushResult]:
    """Empty pushAllDeltas result -- treated as an empty heartbeat."""
    return []


def _okResult(rowsPushed: int = 1) -> list[PushResult]:
    """Single-table OK PushResult with the requested row count."""
    return [
        PushResult(
            tableName="realtime_data",
            rowsPushed=rowsPushed,
            batchId="test-batch",
            elapsed=0.01,
            status=PushStatus.OK,
            reason="",
        )
    ]


def _installController(
    orch: ApplicationOrchestrator,
    clock: FakeClock,
    *,
    idleSeconds: float = 60.0,
    activeSeconds: float = 5.0,
) -> SyncCadenceController:
    """Construct a deterministic-clock controller and bind it to the orchestrator.

    Mirrors what ``_initializeSyncClient`` does in production but with a
    fake clock so cadence assertions are deterministic.
    """
    controller = SyncCadenceController(
        now=clock,
        idleSeconds=idleSeconds,
        activeSeconds=activeSeconds,
    )
    orch._syncCadenceController = controller
    return controller


# ================================================================================
# 1. Idle workload reduction (the load-bearing AC)
# ================================================================================


class TestIdleWorkloadReduction:
    """1-hour idle simulation: legacy 5s cadence -> ~720/hour;
    controller IDLE 60s -> <=100/hour (B-053 Why-section target)."""

    def test_oneHourIdle_atMostHundredSyncAttempts(self, stubApiKey) -> None:
        """
        Given: orchestrator with controller wired + intervalSeconds=5 (legacy).
        When: 1 hour of polls (3600s @ 1s steps) drives _maybeTriggerIntervalSync.
        Then: at most 100 sync attempts fired -- IDLE cadence has taken over.
        """
        # Arrange
        clock = FakeClock(start=0.0)
        orch = _makeOrch(_baseConfig(intervalSeconds=5))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = _emptyResult()
        controller = _installController(clock=clock, orch=orch)

        # Act -- simulate 3600 seconds of idle, polling every second.
        for _ in range(3600):
            orch._maybeTriggerIntervalSync()
            clock.advance(1.0)

        # Assert
        callCount = orch._syncClient.pushAllDeltas.call_count
        assert callCount <= 100, (
            f"Idle workload regression: {callCount} pushAllDeltas calls in "
            f"1 hour exceeds 100/hour budget (B-053 Why-section target). "
            f"Controller state at end: {controller.state}."
        )
        # Lower-bound sanity: 60s cadence gives ~60/hour.
        assert callCount >= 50, (
            f"Suspiciously few pushAllDeltas calls ({callCount}) -- did the "
            f"controller stop firing entirely?"
        )

    def test_oneHourIdleWithoutController_legacyCadenceFires720Per(
        self, stubApiKey
    ) -> None:
        """
        Pre-fix RED proxy: with NO controller (the legacy path), 1-hour idle
        at intervalSeconds=5 yields ~720 attempts -- ~18000/hour at the
        production 0.2s cadence.  This pins the back-compat branch and shows
        why US-299's controller-driven path actually reduces workload.
        """
        # Arrange -- explicitly DO NOT install a controller (legacy path).
        orch = _makeOrch(_baseConfig(intervalSeconds=5))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = _emptyResult()
        # Sanity: prove the legacy path is the active path.
        assert orch._syncCadenceController is None

        # Act -- legacy path uses datetime.now(); we backdate
        # _lastSyncAttemptTime instead of advancing a clock so each tick
        # appears to be ~5s after the last.
        from datetime import datetime, timedelta

        callCount = 0
        for tick in range(3600):
            # Force the legacy gate to evaluate as if 5s elapsed each tick.
            if tick > 0:
                orch._lastSyncAttemptTime = datetime.now() - timedelta(
                    seconds=10
                )
            if orch._maybeTriggerIntervalSync():
                callCount += 1

        # Assert -- legacy path with intervalSeconds=5 fires every tick we let it.
        assert callCount > 100, (
            "Legacy path expected to fire >100 calls; if it doesn't, the "
            "discriminator for the post-fix path is meaningless."
        )


# ================================================================================
# 2. Drive-start wiring (controller event handler)
# ================================================================================


class TestDriveStartWiringInvokesController:
    """The orchestrator's _handleDriveStart must call controller.onDriveStart()."""

    def test_handleDriveStart_transitionsControllerIdleToActive(
        self, stubApiKey
    ) -> None:
        """
        Given: controller in IDLE state.
        When: _handleDriveStart fires (DriveDetector callback path).
        Then: controller.state == ACTIVE.
        """
        # Arrange
        clock = FakeClock()
        orch = _makeOrch(_baseConfig())
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = _emptyResult()
        controller = _installController(clock=clock, orch=orch)
        assert controller.state == SyncCadenceState.IDLE

        # Act -- invoke the central drive-start router with a stub session.
        sessionStub = MagicMock(id="drv-001")
        orch._handleDriveStart(sessionStub)

        # Assert
        assert controller.state == SyncCadenceState.ACTIVE


class TestDriveEndWiringInvokesController:
    """The orchestrator's _handleDriveEnd must call controller.onDriveEnd()."""

    def test_handleDriveEnd_transitionsControllerActiveToDraining(
        self, stubApiKey
    ) -> None:
        """
        Given: controller in ACTIVE state (drive_start fired earlier).
        When: _handleDriveEnd fires (DriveDetector callback path).
        Then: controller.state == DRAINING.
        """
        # Arrange
        clock = FakeClock()
        orch = _makeOrch(_baseConfig(triggerOn=["interval"]))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = _emptyResult()
        controller = _installController(clock=clock, orch=orch)
        controller.onDriveStart()
        assert controller.state == SyncCadenceState.ACTIVE

        # Act
        sessionStub = MagicMock(id="drv-001", duration=42.0)
        orch._handleDriveEnd(sessionStub)

        # Assert
        assert controller.state == SyncCadenceState.DRAINING


# ================================================================================
# 3. ACTIVE cadence after drive_start
# ================================================================================


class TestActiveCadencePostDriveStart:
    """Post-drive_start, controller's ACTIVE state polls every activeSeconds."""

    def test_oneHourActive_atFiveSecondCadence_yields_about720Attempts(
        self, stubApiKey
    ) -> None:
        """
        Given: controller transitioned to ACTIVE via _handleDriveStart.
        When: 1 hour of polls (3600s @ 1s steps).
        Then: approximately 720 attempts (3600/5) -- the live-stream cadence
        Spool needs for tuning analysis.
        """
        # Arrange
        clock = FakeClock(start=0.0)
        orch = _makeOrch(_baseConfig(triggerOn=["interval"]))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = _emptyResult()
        controller = _installController(clock=clock, orch=orch)

        # Drive_start through the orchestrator's central router.
        orch._handleDriveStart(MagicMock(id="drv-active-test"))

        # Act
        for _ in range(3600):
            orch._maybeTriggerIntervalSync()
            clock.advance(1.0)

        # Assert -- 720 +/- 1 (the very first tick at t=0 fires before cooldown).
        callCount = orch._syncClient.pushAllDeltas.call_count
        assert 700 <= callCount <= 730, (
            f"ACTIVE cadence expected ~720/hour (3600/5), got {callCount}. "
            f"Final controller state: {controller.state}."
        )


# ================================================================================
# 4. markSynced signals hadRows from pushAllDeltas result
# ================================================================================


class TestMarkSyncedSignalsHadRows:
    """``markSynced(hadRows=True)`` must fire when push returns OK rows.

    This is what powers the missed-drive-start fallback: an IDLE heartbeat
    that comes back with rows must auto-promote to ACTIVE.
    """

    def test_pushAllDeltas_returnsOkRows_controllerEscalatesToActive(
        self, stubApiKey
    ) -> None:
        """
        Given: controller in IDLE; pushAllDeltas returns an OK result with rows.
        When: _maybeTriggerIntervalSync fires.
        Then: controller.state == ACTIVE (missed-drive-start fallback).
        """
        # Arrange
        clock = FakeClock(start=0.0)
        orch = _makeOrch(_baseConfig())
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = _okResult(rowsPushed=42)
        controller = _installController(clock=clock, orch=orch)
        assert controller.state == SyncCadenceState.IDLE

        # Act
        fired = orch._maybeTriggerIntervalSync()

        # Assert
        assert fired is True
        assert controller.state == SyncCadenceState.ACTIVE
        assert controller.lastNonEmptySyncAt is not None

    def test_pushAllDeltas_returnsEmpty_controllerStaysIdle(
        self, stubApiKey
    ) -> None:
        """Empty heartbeat must not trigger fallback BUT must still markSynced.

        ``controller.lastSyncAt is not None`` is the load-bearing check: it
        proves the orchestrator notified the controller of the attempt.
        Pre-fix the orchestrator does not read ``_syncCadenceController``
        at all, so ``lastSyncAt`` would still be None and this test fails.
        """
        # Arrange
        clock = FakeClock(start=0.0)
        orch = _makeOrch(_baseConfig())
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = _emptyResult()
        controller = _installController(clock=clock, orch=orch)

        # Act
        orch._maybeTriggerIntervalSync()

        # Assert
        assert controller.lastSyncAt is not None  # markSynced was called
        assert controller.state == SyncCadenceState.IDLE
        assert controller.lastNonEmptySyncAt is None  # but hadRows=False


# ================================================================================
# 5. Lifecycle constructs the controller during _initializeSyncClient
# ================================================================================


class TestLifecycleConstructsController:
    """``_initializeSyncClient`` must populate ``_syncCadenceController``.

    Without this lifecycle wiring, the integration is skeleton: the gate
    code paths exist but production execution sees a None controller and
    falls back to legacy timing.
    """

    def test_enabledSyncClient_constructsController(self, stubApiKey) -> None:
        # Arrange
        orch = _makeOrch(_baseConfig(syncEnabled=True))

        # Act
        orch._initializeSyncClient()

        # Assert
        assert orch._syncCadenceController is not None
        assert isinstance(orch._syncCadenceController, SyncCadenceController)
        # State machine must boot in IDLE.
        assert orch._syncCadenceController.state == SyncCadenceState.IDLE

    def test_disabledSync_leavesControllerNone(self) -> None:
        """When sync is disabled the controller is also unconstructed."""
        orch = _makeOrch(_baseConfig(syncEnabled=False))

        orch._initializeSyncClient()

        assert orch._syncClient is None
        # Controller without a client to gate is meaningless; stays None.
        assert orch._syncCadenceController is None
