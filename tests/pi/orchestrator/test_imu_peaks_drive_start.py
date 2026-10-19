################################################################################
# File Name: test_imu_peaks_drive_start.py
# Purpose/Description: US-892-a -- the states/imu g peaks mean THIS DRIVE (Atlas
#                      ruling 4, 2026-10-14). The orchestrator's REAL drive-start
#                      callback clears the IMU bridge's peaks and labels them with
#                      the drive start's event ts, built by the same conversion
#                      as the trip distance, so peaks.sinceTs equals
#                      system-status drive.distanceSinceTs byte-for-byte.
# Author: Rex (US-892-a)
# Creation Date: 2026-10-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-18    | Rex (US-892-a) | Initial.
# ================================================================================
################################################################################

"""US-892-a: drive start resets the states/imu peaks."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import pytest

from pi.bus.sample import Sample
from pi.obdii.drive.types import DriveSession
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.event_router import EventRouterMixin
from pi.sensors.imu_state_bridge import IMU_STATE_FILENAME, ImuStateBridge
from pi.splash.system_status_emitter import SYSTEM_STATUS_FILENAME

# America/Chicago is UTC-5 in October (CDT): a naive local 10:00:00 is 15:00:00Z.
_ZONE = "America/Chicago"
_DRIVE_START_LOCAL = datetime(2026, 10, 20, 10, 0, 0)
_DRIVE_START_TS = "2026-10-20T15:00:00Z"

_PEAK_FIELDS = ("accelG", "brakeG", "leftG", "rightG")


class _Clock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.t = 5000.0

    def __call__(self) -> float:
        return self.t


class _DriveDetector:
    """The recording/idle source _gatherDriveState reads (isDriving)."""

    def __init__(self) -> None:
        self.driving = False

    def isDriving(self) -> bool:
        return self.driving

    def processValue(self, name: str, value: Any) -> None:
        pass


class _Orch(EventRouterMixin, CardStateEmitterMixin):
    """The two REAL mixins with the trip and IMU-bridge facts attached."""

    def __init__(self, statesDir: str, imuBridge: Any | None) -> None:
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
                "time": {"localZone": _ZONE},
                "trip": {"gapSec": 300},
            }
        }
        self._connection = None
        self._driveDetector = _DriveDetector()
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
        self._tripClock = _Clock()
        self._imuStateBridge = imuBridge
        self.statesDir = statesDir

    def startDrive(self, startLocal: Any = _DRIVE_START_LOCAL) -> None:
        self._driveDetector.driving = True
        self._handleDriveStart(DriveSession(startTime=startLocal))

    def drive(self) -> dict:
        self._emitSystemStatusState()
        with open(
            os.path.join(self.statesDir, SYSTEM_STATUS_FILENAME), encoding="utf-8"
        ) as fh:
            return json.load(fh)["drive"]


def _presenceAbsent() -> Sample:
    """The retained presence STATE saying absent: forces a states/imu write."""
    return Sample(
        topic="state.sensor.imu",
        source="imu",
        value=0.0,
        unit="absent",
        tsUtc="2026-10-20T15:00:01Z",
        tsCapture=10.0,
        driveId=None,
        dataSource="real",
        seq=0,
    )


def _bridgeWithPeaks(statesDir: str) -> ImuStateBridge:
    """A real bridge holding {accelG 0.31, brakeG 0.38, leftG 0.27, rightG 0.31}."""
    bridge = ImuStateBridge(None, statesDir, stateHz=1, peaksSmoothingSec=0.5)
    legs = [(0.31, 0.0), (-0.38, 0.0), (0.0, -0.27), (0.0, 0.31)]
    i = 0
    for gLon, gLat in legs:
        for _ in range(50):
            bridge._peaks.fold(gLon, gLat, i / 50.0, "2026-10-20T08:01:00Z")  # noqa: SLF001
            i += 1
    return bridge


def _readImu(statesDir: str) -> dict:
    with open(os.path.join(statesDir, IMU_STATE_FILENAME), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def statesDir(tmp_path) -> str:
    path = tmp_path / "states"
    path.mkdir()
    return str(path)


def test_driveStart_clearsThePeaks_andLabelsThemWithTheDriveStart(statesDir):
    """
    Given: peaks {accelG 0.31, brakeG 0.38, leftG 0.27, rightG 0.31}
    When: a drive starts at T
    Then: peaks all null, sinceTs T
    """
    bridge = _bridgeWithPeaks(statesDir)
    assert bridge._peaks.snapshot() == {  # noqa: SLF001
        "accelG": 0.31, "brakeG": 0.38, "leftG": 0.27, "rightG": 0.31,
        "sinceTs": "2026-10-20T08:01:00Z",
    }
    orch = _Orch(statesDir, bridge)

    orch.startDrive()

    assert bridge._peaks.snapshot() == {  # noqa: SLF001
        "accelG": None, "brakeG": None, "leftG": None, "rightG": None,
        "sinceTs": _DRIVE_START_TS,
    }


def test_driveStart_peaksSinceTsEqualsTheTripDistanceSinceTs_stringEqual(statesDir):
    """
    Given: a drive start
    When: states/imu and system-status are read
    Then: peaks.sinceTs == drive.distanceSinceTs (one string compare)
    """
    bridge = _bridgeWithPeaks(statesDir)
    orch = _Orch(statesDir, bridge)

    orch.startDrive()
    bridge.handleSample(_presenceAbsent())
    peaks = _readImu(statesDir)["peaks"]
    drive = orch.drive()

    assert all(peaks[f] is None for f in _PEAK_FIELDS)
    assert drive["distanceSinceTs"] is not None
    assert peaks["sinceTs"] == drive["distanceSinceTs"]


def test_driveStart_noImuBridge_noException_andTheTripResetStillRuns(statesDir):
    """IMU disabled: no bridge, no call, no error -- the trip distance resets."""
    orch = _Orch(statesDir, None)

    orch.startDrive()

    assert orch.drive()["distanceSinceTs"] == _DRIVE_START_TS


def test_driveStart_bridgeResetRaises_isIsolated_andLaterResetsStillRun(
    statesDir, caplog
):
    """A failing peaks reset never blocks the drive-start chain behind it."""

    class _Broken:
        def resetPeaks(self, startTs: Any) -> None:
            raise RuntimeError("boom")

    orch = _Orch(statesDir, _Broken())
    resetHistory: list[Any] = []
    orch._resetEngineHistory = resetHistory.append  # type: ignore[method-assign]

    with caplog.at_level(logging.DEBUG, logger="pi.obdii.orchestrator"):
        orch.startDrive()

    assert orch.drive()["distanceSinceTs"] == _DRIVE_START_TS
    assert resetHistory == [_DRIVE_START_LOCAL]
    assert "IMU peaks reset failed" in caplog.text


def test_driveStart_unusableStartTime_clearsThePeaks_sinceTsNull(statesDir):
    """No usable drive-start ts (None, the trip reset's own rule): the peaks
    clear and sinceTs is null -- never a guessed time."""
    bridge = _bridgeWithPeaks(statesDir)
    orch = _Orch(statesDir, bridge)

    orch.startDrive(None)

    assert bridge._peaks.snapshot() == {  # noqa: SLF001
        "accelG": None, "brakeG": None, "leftG": None, "rightG": None, "sinceTs": None,
    }
