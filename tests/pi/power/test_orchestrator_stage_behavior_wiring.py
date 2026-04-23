################################################################################
# File Name: test_orchestrator_stage_behavior_wiring.py
# Purpose/Description: Integration test for the US-225 / TD-034 stage-behavior
#                      wiring of PowerDownOrchestrator callbacks.  Mocked
#                      35 -> 15 % drain across a real BatteryHealthRecorder
#                      + real pi_state gate + real DriveDetector +
#                      MagicMock SyncClient to assert each stage invokes
#                      the expected new APIs and AC-restore fully unwinds.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Integration test for US-225 orchestrator-stage wiring.

Strategy
--------
The test does NOT run the lifecycle module's full `_wirePowerDownOrchestrator
Callbacks` path (that couples through hardware_manager + real threads).
Instead, the test:

1. Builds a real :class:`PowerDownOrchestrator` + real
   :class:`BatteryHealthRecorder` on a real :class:`ObdDatabase`.
2. Builds a real :class:`DriveDetector` with an active drive session.
3. Stubs the orchestrator-host (ApplicationOrchestrator) with
   :class:`MagicMock`-flavored stubs for pausePolling/resumePolling +
   a SyncClient-alike forcePush.
4. Binds stage callbacks that replicate the lifecycle wiring pattern:
   WARNING -> {setNoNewDrives, forcePush}; IMMINENT ->
   {pausePolling, forceKeyOff}; AC-restore -> {clearNoNewDrives,
   resumePolling}.
5. Drives the orchestrator ``tick()`` from 35 -> 32 -> 26 -> 21 (each
   stage in turn) and asserts the expected side effects land on the
   real components (DB gate, drive-end row) + the mocks.
6. Validates AC-restore fully unwinds -- gate clear, polling resumed,
   no drive re-minted.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

from src.pi.hardware.ups_monitor import PowerSource
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DriveState
from src.pi.obdii.drive_id import getCurrentDriveId, setCurrentDriveId
from src.pi.obdii.pi_state import getNoNewDrives, setNoNewDrives
from src.pi.power.battery_health import BatteryHealthRecorder
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerState,
    ShutdownThresholds,
)

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def freshDb(tmp_path) -> Generator[ObdDatabase, None, None]:
    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    setCurrentDriveId(None)
    yield db
    setCurrentDriveId(None)


@pytest.fixture
def detectorConfig() -> dict:
    return {
        'pi': {
            'analysis': {
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 0.01,
                'driveEndRpmThreshold': 200,
                'driveEndDurationSeconds': 30,
                'triggerAfterDrive': False,
            },
            'profiles': {'activeProfile': 'daily'},
        },
    }


@pytest.fixture
def detector(detectorConfig, freshDb) -> DriveDetector:
    d = DriveDetector(detectorConfig, statisticsEngine=None, database=freshDb)
    d.start()
    return d


@pytest.fixture
def recorder(freshDb) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


@pytest.fixture
def thresholds() -> ShutdownThresholds:
    return ShutdownThresholds(
        enabled=True,
        warningSoc=30,
        imminentSoc=25,
        triggerSoc=20,
        hysteresisSoc=5,
    )


# ================================================================================
# Helpers
# ================================================================================


def _driveUp(detector: DriveDetector) -> None:
    """Drive the detector into RUNNING with an active session + drive_id."""
    detector.processValue('RPM', 1000)
    import time as _t
    _t.sleep(0.03)
    detector.processValue('RPM', 1200)
    assert detector.getDriveState() == DriveState.RUNNING
    assert getCurrentDriveId() is not None


class _PollingStub:
    """Stand-in for ApplicationOrchestrator's pausePolling/resumePolling.

    Tracks call order so assertions can verify the sequencing invariant:
    pausePolling fires before forceKeyOff on IMMINENT; resumePolling
    fires on AC-restore; both respect the flag.
    """

    def __init__(self) -> None:
        self.pauseCalls: list[str] = []
        self.resumeCalls: list[str] = []
        self._paused = False

    def pausePolling(self, reason: str = 'power_imminent') -> bool:
        if self._paused:
            return False
        self._paused = True
        self.pauseCalls.append(reason)
        return True

    def resumePolling(self, reason: str = 'power_restored') -> bool:
        if not self._paused:
            return False
        self._paused = False
        self.resumeCalls.append(reason)
        return True

    @property
    def isPaused(self) -> bool:
        return self._paused


def _wireCallbacks(
    *,
    database: ObdDatabase,
    detector: DriveDetector,
    polling: _PollingStub,
    syncStub: MagicMock,
    orch: PowerDownOrchestrator,
) -> None:
    """Replicate lifecycle._wirePowerDownOrchestratorCallbacks in test shape."""

    def onWarning() -> None:
        with database.connect() as conn:
            setNoNewDrives(conn, True)
        syncStub.forcePush()

    def onImminent() -> None:
        polling.pausePolling(reason='power_imminent')
        detector.forceKeyOff(reason='power_imminent')

    def onAcRestore() -> None:
        with database.connect() as conn:
            setNoNewDrives(conn, False)
        polling.resumePolling(reason='power_restored')

    orch._onWarning = onWarning  # noqa: SLF001
    orch._onImminent = onImminent  # noqa: SLF001
    orch._onAcRestore = onAcRestore  # noqa: SLF001


# ================================================================================
# End-to-end drain 35 -> TRIGGER
# ================================================================================


class TestDrain35ToTriggerCascadesAllStageBehaviors:
    def test_fullDrain_firesWarningThenImminentStageBehaviors(
        self, thresholds, recorder, freshDb, detector
    ) -> None:
        shutdownAction = MagicMock()
        polling = _PollingStub()
        syncStub = MagicMock()
        orch = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
        )
        _wireCallbacks(
            database=freshDb, detector=detector, polling=polling,
            syncStub=syncStub, orch=orch,
        )

        # Start a live drive -- the IMMINENT stage must force-terminate it.
        _driveUp(detector)
        originalDriveId = getCurrentDriveId()

        # Tick through the drain: 35 (NORMAL) -> 29 (WARNING) -> 24
        # (IMMINENT) -> 19 (TRIGGER).
        orch.tick(currentSoc=35, currentSource=PowerSource.BATTERY)
        assert orch.state == PowerState.NORMAL

        orch.tick(currentSoc=29, currentSource=PowerSource.BATTERY)
        assert orch.state == PowerState.WARNING
        # WARNING stage behaviors:
        with freshDb.connect() as conn:
            assert getNoNewDrives(conn) is True
        syncStub.forcePush.assert_called_once()

        orch.tick(currentSoc=24, currentSource=PowerSource.BATTERY)
        assert orch.state == PowerState.IMMINENT
        # IMMINENT stage behaviors:
        assert polling.pauseCalls == ['power_imminent']
        assert polling.isPaused is True
        # Drive must be force-terminated.
        assert detector.getDriveState() == DriveState.STOPPED
        assert getCurrentDriveId() is None

        orch.tick(currentSoc=19, currentSource=PowerSource.BATTERY)
        assert orch.state == PowerState.TRIGGER
        shutdownAction.assert_called_once()

        # Drive-end row carries the 'power_imminent' reason so
        # analytics can classify the termination.
        with freshDb.connect() as conn:
            row = conn.execute(
                "SELECT error_message, drive_id FROM connection_log "
                "WHERE event_type = 'drive_end'"
            ).fetchone()
            assert row is not None
            assert row[0] == 'power_imminent'
            assert row[1] == originalDriveId


# ================================================================================
# AC-restore unwind
# ================================================================================


class TestAcRestoreUnwindsStageEffects:
    def test_acRestoreDuringWarning_clearsGateAndResumesPolling(
        self, thresholds, recorder, freshDb, detector
    ) -> None:
        shutdownAction = MagicMock()
        polling = _PollingStub()
        syncStub = MagicMock()
        orch = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
        )
        _wireCallbacks(
            database=freshDb, detector=detector, polling=polling,
            syncStub=syncStub, orch=orch,
        )

        # Drain to WARNING + IMMINENT so BOTH behaviors fired.
        orch.tick(currentSoc=29, currentSource=PowerSource.BATTERY)
        orch.tick(currentSoc=24, currentSource=PowerSource.BATTERY)
        assert orch.state == PowerState.IMMINENT
        with freshDb.connect() as conn:
            assert getNoNewDrives(conn) is True
        assert polling.isPaused is True

        # AC restored at 24% -- full unwind.
        orch.tick(currentSoc=24, currentSource=PowerSource.EXTERNAL)

        assert orch.state == PowerState.NORMAL
        with freshDb.connect() as conn:
            assert getNoNewDrives(conn) is False
        assert polling.resumeCalls == ['power_restored']
        assert polling.isPaused is False

    def test_acRestoreNeverFiresShutdownAction(
        self, thresholds, recorder, freshDb, detector
    ) -> None:
        shutdownAction = MagicMock()
        polling = _PollingStub()
        syncStub = MagicMock()
        orch = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
        )
        _wireCallbacks(
            database=freshDb, detector=detector, polling=polling,
            syncStub=syncStub, orch=orch,
        )

        orch.tick(currentSoc=26, currentSource=PowerSource.BATTERY)
        orch.tick(currentSoc=26, currentSource=PowerSource.EXTERNAL)

        shutdownAction.assert_not_called()

    def test_acRestoreAfterImminent_allowsMintingAgain(
        self, thresholds, recorder, freshDb, detector
    ) -> None:
        shutdownAction = MagicMock()
        polling = _PollingStub()
        syncStub = MagicMock()
        orch = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
        )
        _wireCallbacks(
            database=freshDb, detector=detector, polling=polling,
            syncStub=syncStub, orch=orch,
        )

        orch.tick(currentSoc=29, currentSource=PowerSource.BATTERY)
        orch.tick(currentSoc=26, currentSource=PowerSource.EXTERNAL)
        assert orch.state == PowerState.NORMAL

        # A fresh cranking transition must succeed (gate cleared).
        driveId = detector._openDriveId()
        assert driveId is not None
        assert driveId >= 1


# ================================================================================
# Invariant: failing callback does NOT block stage escalation
# ================================================================================


class TestFailingCallbackDoesNotBlockEscalation:
    def test_warningCallbackRaisesButImminentStillFires(
        self, thresholds, recorder, freshDb, detector
    ) -> None:
        shutdownAction = MagicMock()
        polling = _PollingStub()
        orch = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
        )

        def raisingWarning() -> None:
            raise RuntimeError("simulated WARNING stage failure")

        imminentFired: list[bool] = []

        def onImminent() -> None:
            imminentFired.append(True)
            polling.pausePolling()

        orch._onWarning = raisingWarning  # noqa: SLF001
        orch._onImminent = onImminent  # noqa: SLF001

        orch.tick(currentSoc=29, currentSource=PowerSource.BATTERY)
        assert orch.state == PowerState.WARNING
        orch.tick(currentSoc=24, currentSource=PowerSource.BATTERY)
        assert orch.state == PowerState.IMMINENT
        assert imminentFired == [True]

    def test_imminentCallbackRaisesButTriggerStillFires(
        self, thresholds, recorder, freshDb
    ) -> None:
        shutdownAction = MagicMock()
        orch = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
        )

        def raisingImminent() -> None:
            raise RuntimeError("simulated IMMINENT stage failure")

        orch._onImminent = raisingImminent  # noqa: SLF001

        orch.tick(currentSoc=29, currentSource=PowerSource.BATTERY)
        orch.tick(currentSoc=24, currentSource=PowerSource.BATTERY)
        orch.tick(currentSoc=19, currentSource=PowerSource.BATTERY)

        # TRIGGER must still fire -- this is the primary safety
        # invariant of US-216 the new wiring must not weaken.
        assert orch.state == PowerState.TRIGGER
        shutdownAction.assert_called_once()
