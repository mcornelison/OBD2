################################################################################
# File Name: test_fuel_economy_emitter.py
# Purpose/Description: US-881-b -- states/fuel-economy: fuel integrated from MAF
#                      at the fuel's stoich (no trims), MPG against the ONE
#                      speed integrator's distance, one mpgNullReason by fixed
#                      precedence, the engine gate read under the tracker's
#                      lock, the reading-seam wiring, and the contract fixture.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-881-b) | Initial.
# ================================================================================
################################################################################

"""US-881-b: this drive's fuel and MPG, from the reading seam to the file."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from pi.obdii import fuel_economy_emitter as fee
from pi.obdii.band_producer import BandProducer, BandSettings
from pi.obdii.drive.types import DriveSession
from pi.obdii.obd_live_emitter import ObdLiveTracker
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.event_router import EventRouterMixin

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "ui" / "fixtures" / "states" / "fuel-economy.json"
)

# America/Chicago is UTC-5 in October (CDT): naive local 09:58:02 = 14:58:02Z.
_ZONE = "America/Chicago"
_T0_LOCAL = datetime(2026, 10, 20, 9, 58, 2)
_T0_TS = "2026-10-20T14:58:02Z"
_STEP_S = 2.0


def _toUtc(local: datetime) -> datetime:
    return local.replace(tzinfo=ZoneInfo(_ZONE)).astimezone(UTC)


class _Reading:
    """The shape RealtimeDataLogger hands the reading callback."""

    def __init__(self, parameterName: str, value: Any, timestamp: datetime | None) -> None:
        self.parameterName = parameterName
        self.value = value
        self.unit = None
        self.timestamp = timestamp


class _DriveDetector:
    def __init__(self, driving: bool) -> None:
        self.driving = driving

    def isDriving(self) -> bool:
        return self.driving

    def processValue(self, name: str, value: Any) -> None:
        pass


class _Orch(EventRouterMixin, CardStateEmitterMixin):
    """The two REAL mixins; one fake monotonic clock drives both integrators."""

    def __init__(self, statesDir: str, *, fuel: dict | None = None,
                 driving: bool = False) -> None:
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "time": {"localZone": _ZONE},
                "trip": {"gapSec": 300},
                "fuel": dict(fuel or {}),
            }
        }
        self.t = 1000.0
        self.local = _T0_LOCAL
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
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0
        self._initializeCardStateEmitters()
        self._tripClock = lambda: self.t
        # "now" for staleness: one second after the newest reading.
        self._obdLiveClock = lambda: _toUtc(self.local) + timedelta(seconds=1)
        self.statesDir = statesDir

    def read(self, name: str, value: Any) -> None:
        self._handleReading(_Reading(name, value, self.local))

    def advance(self, seconds: float) -> None:
        self.t += seconds
        self.local += timedelta(seconds=seconds)

    def startDrive(self) -> None:
        self._driveDetector.driving = True
        self._handleDriveStart(DriveSession(startTime=self.local))

    def run(self, seconds: float, *, maf: float | None, speed: float | None,
            status: int | None = None, rpm: float | None = None) -> None:
        """Readings every _STEP_S for ``seconds`` (the first at the current t)."""
        steps = round(seconds / _STEP_S)
        for i in range(steps + 1):
            if i:
                self.advance(_STEP_S)
            if rpm is not None:
                self.read("RPM", rpm)
            if status is not None:
                self.read("FUEL_SYSTEM_STATUS", float(status))
            if speed is not None:
                self.read("SPEED", speed)
            if maf is not None:
                self.read("MAF", maf)

    def state(self) -> dict:
        self._lastCardStateEmitTime = None
        assert self._maybeEmitCardStates()
        with open(
            os.path.join(self.statesDir, fee.FUEL_ECONOMY_STATE_FILENAME), encoding="utf-8"
        ) as fh:
            return json.load(fh)


def _orch(tmp_path, **kw) -> _Orch:
    return _Orch(str(tmp_path / "states"), **kw)


# ======================================================= validation criteria


def test_steadyDrive_fuelAndMpgAreSpoolsArithmetic(tmp_path):
    """MAF 10 g/s and SPEED 60 km/h for 360 s at stoich 14.7, density 740:
    fuelL = 10*360/14.7/740, distance 6 km, mpg 42.65."""
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=2)

    state = orch.state()
    drive = state["thisDrive"]

    assert drive["fuelL"] == pytest.approx(10 * 360 / 14.7 / 740)
    assert drive["fuelL"] == pytest.approx(0.3309, abs=1e-4)
    assert orch._gatherTripDistance()[0] == pytest.approx(6.0)
    assert drive["mpg"] == pytest.approx(
        (6 / 1.609344) / (10 * 360 / 14.7 / 740 / 3.785411784)
    )
    assert drive["mpg"] == pytest.approx(42.65, abs=0.01)
    assert "mpgNullReason" not in drive
    assert drive["sinceTs"] == _T0_TS
    assert drive["approximate"] is False
    assert drive["openLoopAirPct"] == 0.0
    assert state["sinceReset"] is None
    assert state["ts"] == _toUtc(orch.local).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_thisDrive_carriesNoDistance(tmp_path):
    """Distance lives in system-status (US-880-a, Atlas gap 1)."""
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=2)

    assert set(orch.state()["thisDrive"]) == {
        "fuelL", "mpg", "sinceTs", "approximate", "openLoopAirPct",
    }


def test_shortDrive_mpgNullTooShort(tmp_path):
    """0.8 km (48 s at 60 km/h) is under 1.0 mile."""
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(48, maf=10.0, speed=60.0, status=2)

    drive = orch.state()["thisDrive"]

    assert orch._gatherTripDistance()[0] == pytest.approx(0.8)
    assert drive["mpg"] is None
    assert drive["mpgNullReason"] == "too_short"


def test_mafUntrusted_mpgNull_fuelStillIntegrated(tmp_path):
    orch = _orch(tmp_path, fuel={"mafTrusted": False})
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=2)

    drive = orch.state()["thisDrive"]

    assert drive["mpg"] is None
    assert drive["mpgNullReason"] == "maf_untrusted"
    assert drive["fuelL"] == pytest.approx(10 * 360 / 14.7 / 740)


def test_twentyPercentOfAirAtStatus3_openLoopAirPct20_approximate(tmp_path):
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(288, maf=10.0, speed=60.0, status=2)
    # The next 72 s of air (20 % of 360) is seen at status 3 (OL-drive).
    orch.read("FUEL_SYSTEM_STATUS", 3.0)
    orch.advance(_STEP_S)
    orch.run(70, maf=10.0, speed=60.0, status=3)

    drive = orch.state()["thisDrive"]

    assert drive["openLoopAirPct"] == pytest.approx(20.0)
    assert drive["approximate"] is True
    assert drive["mpg"] is not None


@pytest.mark.parametrize("code", [0, 1, 3, 4])
def test_openLoopCodes_countAsOpenLoopAir(tmp_path, code):
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=code)

    assert orch.state()["thisDrive"]["openLoopAirPct"] == pytest.approx(100.0)


@pytest.mark.parametrize("code", [2, 5])
def test_closedLoopCodes_countAsClosedLoopAir(tmp_path, code):
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=code)

    assert orch.state()["thisDrive"]["openLoopAirPct"] == 0.0


def test_fourHundredSecondGapInAThousandSecondDrive_excludedAndNullGaps(tmp_path):
    """A 400 s MAF gap (> gapSec 300) adds no fuel; 40 % excluded > 10 %."""
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(300, maf=10.0, speed=60.0, status=2)
    orch.advance(400.0)
    orch.run(300, maf=10.0, speed=60.0, status=2)

    drive = orch.state()["thisDrive"]

    assert drive["fuelL"] == pytest.approx(10 * 600 / 14.7 / 740)
    assert drive["mpg"] is None
    assert drive["mpgNullReason"] == "gaps"


def test_mafUntrustedAndHalfMileDrive_precedencePicksMafUntrusted(tmp_path):
    orch = _orch(tmp_path, fuel={"mafTrusted": False})
    orch.startDrive()
    orch.run(48, maf=10.0, speed=60.0, status=2)  # 0.8 km = 0.497 mi

    drive = orch.state()["thisDrive"]

    assert drive["mpgNullReason"] == "maf_untrusted"


def test_zeroFuelOverAMile_mpgNullNoFuel_noException(tmp_path):
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(360, maf=0.0, speed=60.0, status=2)

    drive = orch.state()["thisDrive"]

    assert drive["fuelL"] == 0.0
    assert drive["mpg"] is None
    assert drive["mpgNullReason"] == "no_fuel"
    assert drive["openLoopAirPct"] is None
    assert drive["approximate"] is False


def test_zeroMafWhileEngineRunning_mpgNullMafZeroRunning(tmp_path):
    """RPM 800 for the whole drive (past the crank guard), then MAF 0."""
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=2, rpm=800.0)
    orch.advance(_STEP_S)
    orch.read("RPM", 800.0)
    orch.read("MAF", 0.0)

    assert orch.state()["thisDrive"]["mpgNullReason"] == "maf_zero_running"


def test_zeroMafWithTrackerNone_mafZeroRunningNeverChosen(tmp_path):
    """No obd-live tracker -> the gate is unknown, and unknown is not running."""
    orch = _orch(tmp_path)
    orch._obdLiveTracker = None
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=2, rpm=800.0)
    orch.advance(_STEP_S)
    orch.read("MAF", 0.0)

    drive = orch.state()["thisDrive"]

    assert drive["mpg"] is not None
    assert "mpgNullReason" not in drive


def test_noMafWithinObdLiveSec_mpgNullMafStale(tmp_path):
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=2)
    orch._obdLiveClock = lambda: _toUtc(orch.local) + timedelta(seconds=6)

    assert orch.state()["thisDrive"]["mpgNullReason"] == "maf_stale"


# ================================================================ the window


def test_freshProcess_noDrive_thisDriveNull(tmp_path):
    state = _orch(tmp_path).state()

    assert state == {"thisDrive": None, "sinceReset": None, "ts": None}


def test_driveStartWithNoMafYet_zeroFuel_mpgNullMafStale(tmp_path):
    orch = _orch(tmp_path)
    orch.startDrive()

    state = orch.state()

    assert state["ts"] is None
    assert state["thisDrive"]["fuelL"] == 0.0
    assert state["thisDrive"]["mpgNullReason"] == "maf_stale"
    assert state["thisDrive"]["sinceTs"] == _T0_TS


def test_mafWhileIdle_isIgnored(tmp_path):
    orch = _orch(tmp_path)
    orch.run(60, maf=10.0, speed=None)

    assert orch.state()["thisDrive"] is None


def test_driveEnd_keepsTheFuel(tmp_path):
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=2)
    orch._driveDetector.driving = False
    orch._handleDriveEnd(DriveSession(startTime=_T0_LOCAL))
    orch.advance(_STEP_S)
    orch.run(60, maf=10.0, speed=60.0)

    assert orch.state()["thisDrive"]["fuelL"] == pytest.approx(10 * 360 / 14.7 / 740)


def test_nextDriveStart_resetsTheFuel(tmp_path):
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.run(360, maf=10.0, speed=60.0, status=2)
    orch.advance(600.0)
    orch.startDrive()
    orch.read("MAF", 10.0)

    assert orch.state()["thisDrive"]["fuelL"] == 0.0


def test_midDriveProcessStart_windowOpensAtTheFirstMafReading(tmp_path):
    orch = _orch(tmp_path, driving=True)
    orch.run(360, maf=10.0, speed=60.0, status=2)

    drive = orch.state()["thisDrive"]

    assert drive["fuelL"] == pytest.approx(10 * 360 / 14.7 / 740)
    assert drive["sinceTs"] == _T0_TS
    assert drive["mpg"] == pytest.approx(42.65, abs=0.01)


def test_dtComesFromTheMonotonicSeam_notTheReadingWallTime(tmp_path):
    """Wall times an hour apart, the seam 10 s: 10 s of air."""
    orch = _orch(tmp_path)
    orch.startDrive()
    orch.read("MAF", 10.0)
    orch.t += 10.0
    orch.local += timedelta(hours=1)
    orch.read("MAF", 10.0)

    assert orch.state()["thisDrive"]["fuelL"] == pytest.approx(100 / 14.7 / 740)


def test_atomicWrite_sameStatesWriterAsObdLive(tmp_path, monkeypatch):
    from pi.splash import boot_state_emitter

    calls: list[str] = []
    real = boot_state_emitter.writeStateAtomic

    def spy(target: str, payload: dict) -> None:
        calls.append(os.path.basename(target))
        real(target, payload)

    monkeypatch.setattr(boot_state_emitter, "writeStateAtomic", spy)
    orch = _orch(tmp_path)
    orch.state()

    assert fee.FUEL_ECONOMY_STATE_FILENAME in calls
    assert "obd-live" in calls


def test_fuelReadingAndPublish_shareOneLock(tmp_path):
    """observeFuelReading and the publish both take the one _fuelLock."""
    orch = _orch(tmp_path)
    orch.startDrive()
    entered: list[str] = []

    class _Lock:
        def __init__(self) -> None:
            self._lock = threading.Lock()

        def __enter__(self) -> None:
            entered.append("in")
            self._lock.acquire()

        def __exit__(self, *exc: Any) -> None:
            self._lock.release()

    orch._fuelLock = _Lock()
    orch.read("MAF", 10.0)
    orch.read("FUEL_SYSTEM_STATUS", 2.0)
    orch.state()

    assert len(entered) == 3


# ============================================================== engine gate


def _rpmReadings(start: datetime, count: int) -> list[_Reading]:
    return [
        _Reading("RPM", 800.0, start + timedelta(seconds=_STEP_S * i)) for i in range(count)
    ]


def test_trackerEngineRunningAt_naiveLocal_sameAnswerAsTheBandProducer():
    """A naive-local MAF time resolves to the band producer's answer at the
    same instant (the time domain observeReading uses)."""
    config = {"pi": {"time": {"localZone": _ZONE}}}
    tracker = ObdLiveTracker(config)
    producer = BandProducer(BandSettings.fromConfig(config))
    for r in _rpmReadings(_T0_LOCAL, 10):
        tracker.observeReading(r)
        producer.observe("RPM", r.value, _toUtc(r.timestamp))

    for offsetS in (0.0, 1.0, 5.0, 19.0, 21.0, 30.0):
        mafTime = _T0_LOCAL + timedelta(seconds=offsetS)
        assert tracker.engineRunningAt(_Reading("MAF", 0.0, mafTime)) == (
            producer.engineRunningAt(_toUtc(mafTime))
        )
    assert tracker.engineRunningAt(
        _Reading("MAF", 0.0, _T0_LOCAL + timedelta(seconds=18))
    ) is True


def test_trackerEngineRunningAt_noTimestamp_none():
    tracker = ObdLiveTracker({"pi": {"time": {"localZone": _ZONE}}})

    assert tracker.engineRunningAt(_Reading("MAF", 0.0, None)) is None


def test_trackerEngineRunningAt_takesTheTrackersLock():
    tracker = ObdLiveTracker({"pi": {"time": {"localZone": _ZONE}}})
    taken: list[bool] = []

    class _Lock:
        def __enter__(self) -> None:
            taken.append(True)

        def __exit__(self, *exc: Any) -> None:
            pass

    tracker._lock = _Lock()
    tracker.engineRunningAt(_Reading("MAF", 0.0, _T0_LOCAL))

    assert taken == [True]


def test_bandProducerEngineRunningAt_isThePrivateGate():
    producer = BandProducer(BandSettings.fromConfig({}))
    for r in _rpmReadings(_T0_LOCAL, 10):
        producer.observe("RPM", r.value, _toUtc(r.timestamp))
    ts = _toUtc(_T0_LOCAL + timedelta(seconds=18))

    assert producer.engineRunningAt(ts) is producer._engineRunningAt(ts) is True


# ================================================================ pure layer


def _settings(**over: Any) -> fee.FuelSettings:
    return fee.FuelSettings(**{**vars(fee.FuelSettings.fromConfig({})), **over})


def _snap(**over: Any) -> fee.FuelSnapshot:
    base = {
        "started": True, "airG": 3600.0, "openLoopAirG": 0.0, "excludedS": 0.0,
        "windowS": 360.0, "lastMafGPerS": 10.0,
        "lastMafEventUtc": datetime(2026, 10, 20, 15, 4, 2, tzinfo=UTC),
        "lastMafEngineRunning": True,
    }
    return fee.FuelSnapshot(**{**base, **over})


_NOW = datetime(2026, 10, 20, 15, 4, 3, tzinfo=UTC)


def test_fromConfig_defaultsAreTheValidatorDefaults():
    s = fee.FuelSettings.fromConfig({})

    assert (s.stoichAfr, s.densityGPerL, s.mafTrusted, s.minMiles,
            s.maxExcludedPct, s.approximateOpenLoopPct, s.gapSec) == (
        14.7, 740.0, True, 1.0, 10.0, 10.0, 300.0)


def test_unitConstants_areNistExact():
    assert fee.LITERS_PER_US_GALLON == 3.785411784
    assert fee.KM_PER_MILE == 1.609344


@pytest.mark.parametrize(
    "snapOver, settingsOver, km, expected",
    [
        # every condition at once -> the first in precedence
        ({"lastMafEventUtc": None, "lastMafGPerS": 0.0, "excludedS": 300.0},
         {"mafTrusted": False}, 0.1, "maf_untrusted"),
        ({"lastMafEventUtc": datetime(2026, 10, 20, 15, 3, 0, tzinfo=UTC),
          "lastMafGPerS": 0.0, "excludedS": 300.0}, {}, 0.1, "maf_stale"),
        ({"lastMafGPerS": 0.0, "excludedS": 300.0, "airG": 0.0}, {}, 0.1,
         "maf_zero_running"),
        ({"excludedS": 300.0, "airG": 0.0}, {}, 0.1, "gaps"),
        ({"airG": 0.0}, {}, 0.1, "too_short"),
        ({"airG": 0.0}, {}, 6.0, "no_fuel"),
        ({}, {}, None, "too_short"),
    ],
)
def test_mpgNullReason_precedence(snapOver, settingsOver, km, expected):
    state = fee.buildFuelEconomyState(
        _snap(**snapOver), _settings(**settingsOver),
        distanceKm=km, distanceSinceTs=_T0_TS, nowUtc=_NOW, staleSec=5.0,
    )

    assert state["thisDrive"]["mpg"] is None
    assert state["thisDrive"]["mpgNullReason"] == expected
    assert expected in fee.MPG_NULL_REASONS


def test_zeroMafWithEngineGateUnknownOrOff_isNotZeroRunning():
    for gate in (None, False):
        state = fee.buildFuelEconomyState(
            _snap(lastMafGPerS=0.0, lastMafEngineRunning=gate), _settings(),
            distanceKm=6.0, distanceSinceTs=_T0_TS, nowUtc=_NOW, staleSec=5.0,
        )
        assert "mpgNullReason" not in state["thisDrive"]


def test_excludedExactlyAtTheThreshold_isNotGaps():
    state = fee.buildFuelEconomyState(
        _snap(excludedS=36.0), _settings(),
        distanceKm=6.0, distanceSinceTs=_T0_TS, nowUtc=_NOW, staleSec=5.0,
    )

    assert state["thisDrive"]["mpg"] is not None


def test_integrator_dtNonPositive_excludedAndAddsNothing():
    integ = fee.FuelIntegrator(300.0)
    integ.reset(0.0)
    t = datetime(2026, 10, 20, 15, 0, 0, tzinfo=UTC)
    integ.observeMaf(10.0, 10.0, t, None)
    integ.observeMaf(10.0, 10.0, t, None)
    integ.observeMaf(10.0, 5.0, t, None)

    snap = integ.snapshot()

    assert snap.airG == 0.0
    assert snap.excludedS == 0.0


def test_integrator_resetForgetsTheFuelStatus():
    integ = fee.FuelIntegrator(300.0)
    integ.observeFuelStatus(2.0)
    integ.reset(0.0)
    t = datetime(2026, 10, 20, 15, 0, 0, tzinfo=UTC)
    integ.observeMaf(10.0, 0.0, t, None)
    integ.observeMaf(10.0, 2.0, t, None)

    assert integ.snapshot().openLoopAirG == pytest.approx(20.0)


def test_emitter_writeFailure_isSwallowed(tmp_path, monkeypatch):
    from pi.splash import boot_state_emitter

    def boom(*a: Any, **k: Any) -> None:
        raise OSError("tmpfs full")

    monkeypatch.setattr(boot_state_emitter, "writeStateAtomic", boom)
    emit = fee.makeFuelEconomyEmitter(str(tmp_path))

    emit(_snap(), _settings(), distanceKm=6.0, distanceSinceTs=_T0_TS,
         nowUtc=_NOW, staleSec=5.0)


# ================================================================ the fixture

# Each named case's scenario: (settings overrides, seconds at 60 km/h).
_CASES: dict[str, tuple[dict[str, Any], float]] = {
    "driving": ({}, 360.0),
    "too-short": ({}, 48.0),
    "maf-untrusted": ({"mafTrusted": False}, 360.0),
}


def _buildCase(name: str) -> dict[str, Any]:
    """The case's scenario through the real integrator and builder."""
    settingsOver, seconds = _CASES[name]
    settings = _settings(**settingsOver)
    integ = fee.FuelIntegrator(settings.gapSec)
    integ.reset(0.0)
    start = _toUtc(_T0_LOCAL)
    integ.observeFuelStatus(2.0)
    steps = round(seconds / _STEP_S)
    for i in range(steps + 1):
        tS = i * _STEP_S
        integ.observeMaf(10.0, tS, start + timedelta(seconds=tS), True)
    distanceKm = 60.0 * seconds / 3600.0
    return fee.buildFuelEconomyState(
        integ.snapshot(), settings,
        distanceKm=distanceKm, distanceSinceTs=_T0_TS,
        nowUtc=start + timedelta(seconds=seconds + 1), staleSec=5.0,
    )


def _loadFixture() -> dict[str, Any]:
    with open(_FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def test_fixture_holdsTheNamedCases():
    assert set(_CASES) <= set(_loadFixture())


@pytest.mark.parametrize("case", sorted(_CASES))
def test_fixture_everyCaseIsWhatTheProducerEmits(case):
    """R29: the producer's output for each named scenario equals the fixture."""
    assert _buildCase(case) == _loadFixture()[case]


def test_fixture_cases_carryTheirReasons():
    fixture = _loadFixture()

    assert fixture["driving"]["thisDrive"]["mpg"] == pytest.approx(42.65, abs=0.01)
    assert fixture["too-short"]["thisDrive"]["mpgNullReason"] == "too_short"
    assert fixture["maf-untrusted"]["thisDrive"]["mpgNullReason"] == "maf_untrusted"
