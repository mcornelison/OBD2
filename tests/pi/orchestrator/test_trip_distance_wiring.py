################################################################################
# File Name: test_trip_distance_wiring.py
# Purpose/Description: US-880-a -- SPEED readings arriving at the orchestrator's
#                      REAL reading callback, while a drive is recording, reach
#                      system-status drive.distanceKm / distanceSinceTs through
#                      the one speed integrator. Drive start resets it; drive
#                      end keeps it; idle readings are ignored; a mid-drive
#                      process start labels its partial distance honestly.
# Author: Rex (US-880-a)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-880-a) | Initial.
# ================================================================================
################################################################################

"""US-880-a: the trip distance, from the reading seam to system-status."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import pytest

from pi.obdii.drive.types import DriveSession
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.event_router import EventRouterMixin
from pi.splash.system_status_emitter import SYSTEM_STATUS_FILENAME

# America/Chicago is UTC-5 in October (CDT): a naive local 09:58:02 is 14:58:02Z.
_ZONE = "America/Chicago"
_DRIVE_START_LOCAL = datetime(2026, 10, 20, 9, 58, 2)
_DRIVE_START_TS = "2026-10-20T14:58:02Z"


class _Reading:
    """The shape RealtimeDataLogger hands the reading callback."""

    def __init__(self, parameterName: str, value: Any, timestamp: datetime | None) -> None:
        self.parameterName = parameterName
        self.value = value
        self.unit = None
        self.timestamp = timestamp


class _Clock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.t = 5000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _DriveDetector:
    """The recording/idle source _gatherDriveState reads (isDriving)."""

    def __init__(self, driving: bool) -> None:
        self.driving = driving

    def isDriving(self) -> bool:
        return self.driving

    def processValue(self, name: str, value: Any) -> None:
        pass


class _Orch(EventRouterMixin, CardStateEmitterMixin):
    """The two REAL mixins with only the trip-distance facts attached."""

    def __init__(self, statesDir: str, *, driving: bool = False) -> None:
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
                "time": {"localZone": _ZONE},
                "trip": {"gapSec": 300},
            }
        }
        self.clock = _Clock()
        self._connection = None
        self._driveDetector = _DriveDetector(driving)
        self._hardwareManager = None
        self._displayManager = None
        self._alertManager = None
        self._milEdgeDetector = None
        self._dtcLogger = None
        self._freezeFrameCapture = None
        self._onDriveStart = None
        self._onDriveEnd = None
        self._alertsPausedForReconnect = False
        self._dashboardParameters = []
        self._healthCheckStats = type(
            "S", (), {"totalReadings": 0, "totalErrors": 0, "drivesDetected": 0}
        )()
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0
        self._initializeCardStateEmitters()
        self._tripClock = self.clock
        self.statesDir = statesDir

    def speed(self, kmh: float | None, local: datetime | None = None) -> None:
        self._handleReading(_Reading("SPEED", kmh, local))

    def startDrive(self, startLocal: datetime = _DRIVE_START_LOCAL) -> None:
        self._driveDetector.driving = True
        self._handleDriveStart(DriveSession(startTime=startLocal))

    def endDrive(self) -> None:
        self._driveDetector.driving = False
        self._handleDriveEnd(DriveSession(startTime=_DRIVE_START_LOCAL))

    def drive(self) -> dict:
        self._emitSystemStatusState()
        with open(
            os.path.join(self.statesDir, SYSTEM_STATUS_FILENAME), encoding="utf-8"
        ) as fh:
            return json.load(fh)["drive"]


@pytest.fixture
def orch(tmp_path) -> _Orch:
    return _Orch(str(tmp_path / "states"))


def test_freshProcess_noDrive_publishesNullDistanceKeys(orch):
    drive = orch.drive()

    assert drive["state"] == "idle"
    assert drive["distanceKm"] is None
    assert drive["distanceSinceTs"] is None


def test_driveStart_zeroThenSixtyOverSixtySeconds_publishesHalfAKilometre(orch):
    orch.startDrive()
    orch.speed(0.0, datetime(2026, 10, 20, 9, 58, 3))
    orch.clock.advance(60.0)
    orch.speed(60.0, datetime(2026, 10, 20, 9, 59, 3))

    drive = orch.drive()

    assert drive["state"] == "recording"
    assert drive["distanceKm"] == pytest.approx(0.5)
    assert drive["distanceSinceTs"] == _DRIVE_START_TS


def test_dtComesFromTheMonotonicSeam_notTheReadingWallTime(orch):
    """The readings' wall times are 1 h apart, the monotonic seam 60 s:
    the distance follows the seam."""
    orch.startDrive()
    orch.speed(60.0, datetime(2026, 10, 20, 10, 0, 0))
    orch.clock.advance(60.0)
    orch.speed(60.0, datetime(2026, 10, 20, 11, 0, 0))

    assert orch.drive()["distanceKm"] == pytest.approx(1.0)


def test_speedWhileIdle_isIgnored(orch):
    orch.speed(60.0, datetime(2026, 10, 20, 9, 0, 0))
    orch.clock.advance(60.0)
    orch.speed(60.0, datetime(2026, 10, 20, 9, 1, 0))

    drive = orch.drive()

    assert drive["distanceKm"] is None
    assert drive["distanceSinceTs"] is None


def test_driveEnd_keepsTheDistance_andIdleReadingsDoNotMoveIt(orch):
    orch.startDrive()
    orch.speed(36.0, datetime(2026, 10, 20, 9, 58, 3))
    orch.clock.advance(100.0)
    orch.speed(36.0, datetime(2026, 10, 20, 9, 59, 43))

    orch.endDrive()
    orch.clock.advance(10.0)
    orch.speed(36.0, datetime(2026, 10, 20, 10, 0, 0))
    orch.clock.advance(100.0)
    orch.speed(36.0, datetime(2026, 10, 20, 10, 1, 40))
    drive = orch.drive()

    assert drive["state"] == "idle"
    assert drive["distanceKm"] == pytest.approx(1.0)
    assert drive["distanceSinceTs"] == _DRIVE_START_TS


def test_nextDriveStart_resetsTheDistance(orch):
    orch.startDrive()
    orch.speed(36.0, datetime(2026, 10, 20, 9, 58, 3))
    orch.clock.advance(100.0)
    orch.speed(36.0, datetime(2026, 10, 20, 9, 59, 43))
    orch.endDrive()

    orch.clock.advance(600.0)
    orch.startDrive(datetime(2026, 10, 20, 11, 0, 0))
    drive = orch.drive()

    assert drive["distanceSinceTs"] == "2026-10-20T16:00:00Z"
    assert drive["distanceKm"] is None

    orch.speed(36.0, datetime(2026, 10, 20, 11, 0, 1))
    assert orch.drive()["distanceKm"] == 0.0


def test_firstReadingAfterDriveStart_onlySetsTheStart(orch):
    """The interval does not reach back across the reset to a prior drive."""
    orch.startDrive()
    orch.speed(50.0, datetime(2026, 10, 20, 9, 58, 3))
    orch.clock.advance(30.0)
    orch.startDrive(datetime(2026, 10, 20, 9, 58, 33))
    orch.speed(50.0, datetime(2026, 10, 20, 9, 58, 34))

    assert orch.drive()["distanceKm"] == 0.0


def test_midDriveProcessStart_labelsFromTheFirstIntegratedReading(tmp_path):
    """No drive start seen this process: the distance counts from 0 and
    distanceSinceTs is the first integrated SPEED reading's event ts."""
    orch = _Orch(str(tmp_path / "states"), driving=True)

    orch.speed(None, datetime(2026, 10, 20, 10, 0, 0))
    orch.speed(72.0, datetime(2026, 10, 20, 10, 0, 5))
    orch.clock.advance(50.0)
    orch.speed(72.0, datetime(2026, 10, 20, 10, 0, 55))
    drive = orch.drive()

    assert drive["distanceSinceTs"] == "2026-10-20T15:00:05Z"
    assert drive["distanceKm"] == pytest.approx(1.0)


def test_nonSpeedParameters_areIgnored(orch):
    orch.startDrive()
    orch._handleReading(_Reading("RPM", 3000.0, datetime(2026, 10, 20, 9, 58, 3)))
    orch.clock.advance(60.0)
    orch._handleReading(_Reading("RPM", 3000.0, datetime(2026, 10, 20, 9, 59, 3)))

    assert orch.drive()["distanceKm"] is None


def test_gapWiderThanGapSec_addsNoDistance(orch):
    orch.startDrive()
    orch.speed(50.0, datetime(2026, 10, 20, 9, 58, 3))
    orch.clock.advance(301.0)
    orch.speed(50.0, datetime(2026, 10, 20, 10, 3, 4))
    orch.clock.advance(10.0)
    orch.speed(50.0, datetime(2026, 10, 20, 10, 3, 14))

    assert orch.drive()["distanceKm"] == pytest.approx(50.0 * 10.0 / 3600.0)


def test_cardStatesDisabled_observeTripSpeedIsInert(tmp_path):
    """No integrator is built when the card emitters are disabled; a SPEED
    reading must still pass through the callback without error."""

    class _Dark(_Orch):
        def _initializeCardStateEmitters(self) -> None:  # type: ignore[override]
            self._cardStateEmitEnabled = False
            CardStateEmitterMixin._initializeCardStateEmitters(self)

    orch = _Dark(str(tmp_path / "states"), driving=True)
    orch.speed(50.0, datetime(2026, 10, 20, 9, 58, 3))

    assert orch._gatherTripDistance() == (None, None)
