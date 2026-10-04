################################################################################
# File Name: test_stop_capture_error_drive_end.py
# Purpose/Description: US-674 -- a capture error during stop must not
#     force-exit before the drive closes.  Mechanism A (Atlas, drive 96): at
#     key-off the ECU goes silent mid-stop, the capture loop raises 'Not
#     connected to OBD-II', that routed as FATAL, stop() flipped to force-exit
#     and skipped driveDetector, so no drive_end was written and the process
#     exited 1.  Also pins the stop order (capture loop first, then the drive
#     close) and the stop-path drive-end DTC skip (Atlas 5th ruling).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-674: capture error during stop -> drive_end written, exit 0."""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.data.exceptions import DataLoggerError
from pi.obdii.database import ObdDatabase
from pi.obdii.drive.detector import DriveDetector
from pi.obdii.drive.types import DriveState
from pi.obdii.drive_id import getRawCurrentDriveId, setCurrentDriveId
from pi.obdii.orchestrator import (
    EXIT_CODE_CLEAN,
    EXIT_CODE_FORCED,
    ApplicationOrchestrator,
    ShutdownState,
)

_SKIP_LINE = 'drive-end DTC skipped: ecu_unpowered_at_stop'


@pytest.fixture
def freshDb(tmp_path: Path) -> Generator[ObdDatabase, None, None]:
    db = ObdDatabase(str(tmp_path / "us674_stop.db"), walMode=False)
    db.initialize()
    setCurrentDriveId(None)
    yield db
    setCurrentDriveId(None)


def _detectorConfig() -> dict[str, Any]:
    """Fast-debounce thresholds so processValue ticks drive the state machine."""
    return {
        'pi': {
            'analysis': {
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 0.01,
                'driveEndRpmThreshold': 200,
                'driveEndDurationSeconds': 0.01,
                'triggerAfterDrive': False,
            },
            'profiles': {'activeProfile': 'daily'},
        },
    }


class _CaptureLoopRaisingMidStop:
    """A capture loop whose ECU goes silent while it is being stopped.

    Mirrors ``RealtimeDataLogger._routeCaptureError``: the exception goes
    through the orchestrator's classifier, and a FATAL re-raise is handed to
    the orchestrator's ``onFatalError`` hook.
    """

    def __init__(self, orchestrator: ApplicationOrchestrator) -> None:
        self._orchestrator = orchestrator

    def stop(self) -> None:
        exc = DataLoggerError("Not connected to OBD-II")
        try:
            self._orchestrator.handleCaptureError(exc)
        except BaseException as fatal:  # noqa: BLE001 -- mirrors the capture loop
            self._orchestrator._onCaptureFatalError(fatal)


def _orchestratorWithDrive(
    db: ObdDatabase, driveUp: bool = True,
) -> tuple[ApplicationOrchestrator, DriveDetector, MagicMock]:
    """A running orchestrator with a real detector, optionally mid-drive."""
    orchestrator = ApplicationOrchestrator(config={}, simulate=True)
    orchestrator._database = db
    dtcLogger = MagicMock()
    orchestrator._dtcLogger = dtcLogger
    orchestrator._connection = MagicMock()
    orchestrator._syncClient = MagicMock()
    orchestrator._syncClient.pushAllDeltas.return_value = []
    orchestrator._syncTriggerOn = ['drive_end']

    detector = DriveDetector(_detectorConfig(), statisticsEngine=None, database=db)
    detector.registerCallbacks(onDriveEnd=orchestrator._handleDriveEnd)
    detector.start()
    if driveUp:
        detector.processValue('RPM', 1000)
        time.sleep(0.05)
        detector.processValue('RPM', 1200)
        assert detector.getDriveState() == DriveState.RUNNING
    orchestrator._driveDetector = detector
    orchestrator._running = True
    return orchestrator, detector, dtcLogger


def _driveEndRows(db: ObdDatabase, driveId: int | None) -> list[sqlite3.Row]:
    with db.connect() as conn:
        return conn.execute(
            "SELECT drive_id FROM connection_log "
            "WHERE event_type = 'drive_end' AND drive_id IS ?",
            (driveId,),
        ).fetchall()


def _allDriveEndRows(db: ObdDatabase) -> list[sqlite3.Row]:
    with db.connect() as conn:
        return conn.execute(
            "SELECT drive_id FROM connection_log WHERE event_type = 'drive_end'"
        ).fetchall()


def test_stop_captureErrorRaisedDuringStop_writesDriveEndAndExitsClean(
    freshDb: ObdDatabase,
) -> None:
    """
    Given: a running orchestrator mid-drive whose capture loop raises
           'Not connected to OBD-II' while stop() is stopping it (mechanism A)
    When: stop() runs
    Then: drive_end is written for that drive_id and the exit code is 0
    """
    # Arrange
    orchestrator, _detector, _dtc = _orchestratorWithDrive(freshDb)
    driveId = getRawCurrentDriveId()
    assert driveId is not None
    orchestrator._dataLogger = _CaptureLoopRaisingMidStop(orchestrator)

    # Act
    exitCode = orchestrator.stop()

    # Assert
    assert exitCode == EXIT_CODE_CLEAN
    assert orchestrator._shutdownState != ShutdownState.FORCE_EXIT
    assert len(_driveEndRows(freshDb, driveId)) == 1


def test_stop_orderlyStopMidDrive_skipsMode07AndLogsTypedLine(
    freshDb: ObdDatabase, caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: a running orchestrator mid-drive, ECU unpowered at key-off
    When: an orderly stop() runs
    Then: drive_end is written, no Mode 07 call is made, exactly one
          'drive-end DTC skipped: ecu_unpowered_at_stop' line is logged, and
          no drive-end sync push waits on the network before poweroff
    """
    # Arrange
    orchestrator, _detector, dtcLogger = _orchestratorWithDrive(freshDb)
    syncClient = orchestrator._syncClient
    driveId = getRawCurrentDriveId()

    # Act
    with caplog.at_level(logging.INFO):
        exitCode = orchestrator.stop()

    # Assert
    assert exitCode == EXIT_CODE_CLEAN
    assert len(_driveEndRows(freshDb, driveId)) == 1
    dtcLogger.logDriveEndDtcs.assert_not_called()
    skipLines = [r for r in caplog.records if r.getMessage() == _SKIP_LINE]
    assert len(skipLines) == 1
    syncClient.pushAllDeltas.assert_not_called()


def test_stop_noActiveDrive_writesNoDriveEndAndExitsClean(
    freshDb: ObdDatabase, caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: a running orchestrator with no active drive
    When: an orderly stop() runs
    Then: no drive_end is written, no skip line is logged, and the stop
          completes with exit 0
    """
    # Arrange
    orchestrator, _detector, dtcLogger = _orchestratorWithDrive(freshDb, driveUp=False)

    # Act
    with caplog.at_level(logging.INFO):
        exitCode = orchestrator.stop()

    # Assert
    assert exitCode == EXIT_CODE_CLEAN
    assert _allDriveEndRows(freshDb) == []
    dtcLogger.logDriveEndDtcs.assert_not_called()
    assert not [r for r in caplog.records if r.getMessage() == _SKIP_LINE]
    assert orchestrator._running is False


def test_ignitionOnDriveEnd_beforeStop_stillQueriesMode07(
    freshDb: ObdDatabase, caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: a running orchestrator mid-drive, no stop in progress
    When: the drive ends on RPM -> 0 with the ignition on
    Then: the drive-end Mode 07 read and the drive-end sync push are
          dispatched exactly as before, and no skip line is logged
    """
    # Arrange
    orchestrator, detector, dtcLogger = _orchestratorWithDrive(freshDb)

    # Act
    with caplog.at_level(logging.INFO):
        detector.processValue('RPM', 0)
        time.sleep(0.05)
        detector.processValue('RPM', 0)

    # Assert
    assert detector.getDriveState() != DriveState.RUNNING
    dtcLogger.logDriveEndDtcs.assert_called_once()
    orchestrator._syncClient.pushAllDeltas.assert_called_once()
    assert not [r for r in caplog.records if r.getMessage() == _SKIP_LINE]


def test_captureFatalBeforeStop_stillEscalatesToForceExit() -> None:
    """
    Given: a running orchestrator with no stop in progress
    When: the capture loop reports a FATAL capture-boundary error
    Then: it escalates exactly as today -- FORCE_EXIT, exit code forced,
          the main loop told to stop
    """
    # Arrange
    orchestrator = ApplicationOrchestrator(config={}, simulate=True)
    orchestrator._running = True

    # Act
    orchestrator._onCaptureFatalError(DataLoggerError("Not connected to OBD-II"))

    # Assert
    assert orchestrator._shutdownState == ShutdownState.FORCE_EXIT
    assert orchestrator._exitCode == EXIT_CODE_FORCED
    assert orchestrator._running is False


def test_captureFatalAfterShutdownSignal_doesNotEscalate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: the orchestrator received its stop signal (SIGTERM from the
           confirmed power-loss poweroff) but stop() has not been entered yet
    When: the capture loop reports a FATAL capture-boundary error
    Then: it does not escalate: the shutdown state, exit code and running
          flag are left for the orderly stop, and a WARNING says why
    """
    # Arrange
    orchestrator = ApplicationOrchestrator(config={}, simulate=True)
    orchestrator._running = True
    orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

    # Act
    with caplog.at_level(logging.WARNING):
        orchestrator._onCaptureFatalError(DataLoggerError("Not connected to OBD-II"))

    # Assert
    assert orchestrator._shutdownState == ShutdownState.SHUTDOWN_REQUESTED
    assert orchestrator._exitCode == EXIT_CODE_CLEAN
    assert orchestrator._running is True
    assert any(
        r.levelno == logging.WARNING and 'during stop' in r.getMessage()
        for r in caplog.records
    )


def test_stop_stopsCaptureLoopFirstThenDriveDetector() -> None:
    """
    Given: a running orchestrator with its components in place
    When: stop() runs
    Then: the capture loop (dataLogger) is stopped first, the drive detector
          second, and the remaining components after them
    """
    # Arrange
    orchestrator = ApplicationOrchestrator(config={}, simulate=True)
    order: list[str] = []

    def _component(name: str, method: str = 'stop') -> MagicMock:
        component = MagicMock()
        getattr(component, method).side_effect = lambda: order.append(name)
        return component

    orchestrator._profileSwitcher = _component('profileSwitcher')
    orchestrator._dataLogger = _component('dataLogger')
    orchestrator._alertManager = _component('alertManager')
    orchestrator._driveDetector = _component('driveDetector')
    orchestrator._statisticsEngine = _component('statisticsEngine')
    orchestrator._vinDecoder = _component('vinDecoder')
    orchestrator._connection = _component('connection', method='disconnect')
    orchestrator._running = True

    # Act
    exitCode = orchestrator.stop()

    # Assert
    assert exitCode == EXIT_CODE_CLEAN
    assert order[:2] == ['dataLogger', 'driveDetector'], order
    assert set(order[2:]) == {
        'profileSwitcher', 'alertManager', 'statisticsEngine', 'vinDecoder',
        'connection',
    }
