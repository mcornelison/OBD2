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
# 2026-10-14    | Rex (US-881-c) | sinceReset payload rules, open-loop seconds,
#                                the after-reset fixture case.
# 2026-10-15    | Rex (US-890-e) | recent (MPG over the last 30 s): RecentWindow,
#                                null precedence, lock-apart feeding, the
#                                recent-crawl fixture case.
# 2026-10-22    | Rex (US-923)   | resetAllowed: published each card tick from the
#                                cached gear reading + the deriver's SPEED.
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
from pi.obdii.speed_integrator import SpeedIntegrator

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

    # US-890-e named pin change: the empty state gains 'recent': None.
    # MOVED PIN (US-923): and the gate verdict -- no gear, no SPEED: fail closed.
    assert state == {"thisDrive": None, "sinceReset": None, "ts": None, "recent": None,
                     "resetAllowed": {"value": False, "reason": "speed_unknown"}}


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
            s.maxExcludedPct, s.approximateOpenLoopPct, s.gapSec, s.persistSec) == (
        14.7, 740.0, True, 1.0, 10.0, 10.0, 300.0, 60.0)


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


def test_integrator_openLoopSeconds_countIncludedOpenLoopIntervalsOnly():
    """US-881-c: open_loop_s is the included interval time outside closed loop."""
    integ = fee.FuelIntegrator(300.0)
    integ.reset(0.0)
    t = datetime(2026, 10, 20, 15, 0, 0, tzinfo=UTC)
    integ.observeFuelStatus(3.0)
    integ.observeMaf(10.0, 0.0, t, None)
    integ.observeMaf(10.0, 4.0, t, None)
    integ.observeFuelStatus(2.0)
    integ.observeMaf(10.0, 6.0, t, None)
    integ.observeFuelStatus(1.0)
    integ.observeMaf(10.0, 506.0, t, None)  # a gap: excluded, not open loop

    assert integ.snapshot().openLoopS == pytest.approx(4.0)


def _row(**over: Any) -> dict[str, Any]:
    base = {
        "id": 1, "fuel_l": 0.6618863761720906, "distance_km": 12.0,
        "open_loop_s": 0.0, "reset_at_ts": "2026-10-01T09:00:00Z",
        "updated_at": "2026-10-20T15:02:11Z",
    }
    return {**base, **over}


def test_sinceReset_fromTheRow_mpgOverTheTotals():
    since = fee.buildFuelEconomyState(
        _snap(), _settings(), distanceKm=6.0, distanceSinceTs=_T0_TS,
        nowUtc=_NOW, staleSec=5.0, sinceReset=_row(),
    )["sinceReset"]

    assert set(since) == {"fuelL", "distanceKm", "mpg", "resetAtTs"}
    assert (since["fuelL"], since["distanceKm"]) == (0.6618863761720906, 12.0)
    assert since["mpg"] == pytest.approx((12 / 1.609344) / (0.6618863761720906 / 3.785411784))
    assert since["resetAtTs"] == "2026-10-01T09:00:00Z"


@pytest.mark.parametrize(
    "rowOver, settingsOver",
    [
        ({}, {"mafTrusted": False}),                       # maf_untrusted
        ({"distance_km": 1.0}, {}),                        # too_short (< 1 mile)
        ({"fuel_l": 0.0}, {}),                             # no fuel: undefined
        ({"fuel_l": 0.0, "distance_km": 0.0}, {}),         # straight after a reset
    ],
)
def test_sinceReset_mpgNull_underTheRules(rowOver, settingsOver):
    since = fee.buildFuelEconomyState(
        _snap(), _settings(**settingsOver), distanceKm=6.0, distanceSinceTs=_T0_TS,
        nowUtc=_NOW, staleSec=5.0, sinceReset=_row(**rowOver),
    )["sinceReset"]

    assert since["mpg"] is None


def test_sinceReset_publishedWithNoDriveWindow():
    """A parked, fresh process still publishes the persisted totals."""
    state = fee.buildFuelEconomyState(
        _snap(started=False), _settings(), distanceKm=None, distanceSinceTs=None,
        nowUtc=_NOW, staleSec=5.0, sinceReset=_row(),
    )

    assert state["thisDrive"] is None
    assert state["sinceReset"]["distanceKm"] == 12.0


def test_sinceReset_noRow_null():
    assert fee.buildFuelEconomyState(
        _snap(), _settings(), distanceKm=6.0, distanceSinceTs=_T0_TS,
        nowUtc=_NOW, staleSec=5.0,
    )["sinceReset"] is None


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
    "after-reset": ({}, 360.0),
    "recent-crawl": ({}, 360.0),
}

# US-890-e: a case's speed when it is not 60 km/h. recent-crawl: 10 km/h covers
# 0.083 km (0.05 mi) in the 30 s window, under pi.fuel.recentMinMiles 0.1.
_CASE_SPEED_KMH: dict[str, float] = {"recent-crawl": 10.0}

# US-881-c: the fuel_since_reset row each case publishes as sinceReset (absent =
# no row yet). after-reset: parked after a drive, the totals just zeroed.
_SINCE_RESET_ROWS: dict[str, dict[str, Any]] = {
    "after-reset": {
        "id": 1, "fuel_l": 0.0, "distance_km": 0.0, "open_loop_s": 0.0,
        "reset_at_ts": "2026-10-20T15:10:00Z", "updated_at": "2026-10-20T15:10:00Z",
    },
}


def _buildCase(name: str) -> dict[str, Any]:
    """The case's scenario through the real integrator and builder."""
    settingsOver, seconds = _CASES[name]
    speedKmh = _CASE_SPEED_KMH.get(name, 60.0)
    settings = _settings(**settingsOver)
    integ = fee.FuelIntegrator(settings.gapSec)
    integ.reset(0.0)
    # US-890-e: the window is fed as the card emitter feeds it -- the air the
    # integrator just added, and the speed integrator's km delta.
    window = fee.RecentWindow(settings.recentWindowSec)
    speed = SpeedIntegrator(settings.gapSec)
    lastKm = 0.0
    start = _toUtc(_T0_LOCAL)
    integ.observeFuelStatus(2.0)
    steps = round(seconds / _STEP_S)
    for i in range(steps + 1):
        tS = i * _STEP_S
        km = speed.update(speedKmh, tS)
        window.add(tS, km=km - lastKm)
        lastKm = km
        airG = integ.observeMaf(10.0, tS, start + timedelta(seconds=tS), True)
        window.add(tS, airG=airG, isMafSample=True)
    distanceKm = speedKmh * seconds / 3600.0
    return fee.buildFuelEconomyState(
        integ.snapshot(), settings,
        distanceKm=distanceKm, distanceSinceTs=_T0_TS,
        nowUtc=start + timedelta(seconds=seconds + 1), staleSec=5.0,
        sinceReset=_SINCE_RESET_ROWS.get(name), recent=window.snapshot(),
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
    assert fixture["after-reset"]["sinceReset"] == {
        "fuelL": 0.0, "distanceKm": 0.0, "mpg": None, "resetAtTs": "2026-10-20T15:10:00Z",
    }
    # US-890-e: 30 s of steady 60 km/h / 10 g/s is the drive's own ratio.
    assert fixture["driving"]["recent"]["mpg"] == pytest.approx(42.65, abs=0.01)
    assert fixture["driving"]["recent"]["windowSec"] == 30
    assert fixture["maf-untrusted"]["recent"]["mpgNullReason"] == "maf_untrusted"
    assert fixture["recent-crawl"]["recent"]["mpg"] is None
    assert fixture["recent-crawl"]["recent"]["mpgNullReason"] == "too_short"


# ======================================================= US-890-e: recent


def _recentOrch(tmp_path, **kw) -> _Orch:
    orch = _orch(tmp_path, **kw)
    orch.startDrive()
    return orch


def _runEvery(orch: _Orch, stepS: float, seconds: float, *, maf: float | None,
              speed: float | None) -> None:
    """SPEED then MAF every ``stepS`` for ``seconds`` (the first at the current t)."""
    steps = round(seconds / stepS)
    for i in range(steps + 1):
        if i:
            orch.advance(stepS)
        if speed is not None:
            orch.read("SPEED", speed)
        if maf is not None:
            orch.read("MAF", maf)


# Hand arithmetic: miles over gallons for SPEED v km/h and MAF m g/s held over
# the same seconds -- the seconds cancel.
def _steadyMpg(speedKmh: float, mafGPerS: float) -> float:
    milesPerS = speedKmh / 3600.0 / 1.609344
    gallonsPerS = mafGPerS / 14.7 / 740.0 / 3.785411784
    return milesPerS / gallonsPerS


def test_recent_thirtySecondsAt60KmhMafEvery2p2s_isTheHandRatio(tmp_path):
    """Validation 1: 30 s at 60 km/h, MAF 10 g/s every 2.2 s."""
    orch = _recentOrch(tmp_path)
    _runEvery(orch, 2.2, 30.8, maf=10.0, speed=60.0)

    recent = orch.state()["recent"]

    assert recent["mpg"] == pytest.approx(_steadyMpg(60.0, 10.0))
    assert recent["mpg"] == pytest.approx(42.64, abs=0.01)
    # readings at 0 .. 28.6 s back from the newest: 14 inside (newest - 30, newest]
    assert recent["mafSamples"] == 14
    assert recent["windowSec"] == 30
    assert "mpgNullReason" not in recent


def test_recent_isTheRatioOfSums_notTheMeanOfSampleRatios():
    """Two 15 s halves: 90 km/h at 20 g/s, then 30 km/h at 5 g/s. The mean of
    the two halves' MPGs is not the window's MPG; the ratio of the sums is."""
    window = fee.RecentWindow(30.0)
    for i in range(1, 16):
        window.add(float(i), airG=20.0, km=90.0 / 3600.0, isMafSample=True)
    for i in range(16, 31):
        window.add(float(i), airG=5.0, km=30.0 / 3600.0, isMafSample=True)

    recent = fee.buildFuelEconomyState(
        _snap(), _settings(), distanceKm=6.0, distanceSinceTs=_T0_TS,
        nowUtc=_NOW, staleSec=5.0, recent=window.snapshot(),
    )["recent"]

    miles = (15 * 90.0 / 3600.0 + 15 * 30.0 / 3600.0) / 1.609344
    gallons = (15 * 20.0 + 15 * 5.0) / 14.7 / 740.0 / 3.785411784
    assert recent["mpg"] == pytest.approx(miles / gallons)
    meanOfRatios = (_steadyMpg(90.0, 20.0) + _steadyMpg(30.0, 5.0)) / 2
    assert recent["mpg"] != pytest.approx(meanOfRatios, rel=1e-3)


def test_recent_thirtySecondsIdle_tooShort(tmp_path):
    """Validation 2: 30 s at speed 0 (idle MAF) -> too_short."""
    orch = _recentOrch(tmp_path)
    _runEvery(orch, 2.2, 30.8, maf=3.2, speed=0.0)

    recent = orch.state()["recent"]

    assert recent["mpg"] is None
    assert recent["mpgNullReason"] == "too_short"
    assert recent["mafSamples"] == 14


def test_recent_eightMafSamplesInTheWindow_tooFewSamples(tmp_path):
    """Validation 3: MAF every 4 s puts 8 readings in the window (< 10)."""
    orch = _recentOrch(tmp_path)
    _runEvery(orch, 4.0, 60.0, maf=10.0, speed=60.0)

    recent = orch.state()["recent"]

    assert recent["mafSamples"] == 8
    assert recent["mpg"] is None
    assert recent["mpgNullReason"] == "too_few_samples"


def test_recent_noDriveWindow_null(tmp_path):
    assert _orch(tmp_path).state()["recent"] is None


def test_recent_driveStartWithNoReadings_isAnEmptyWindowWithAReason(tmp_path):
    recent = _recentOrch(tmp_path).state()["recent"]

    assert recent == {"mpg": None, "windowSec": 30, "mafSamples": 0,
                      "mpgNullReason": "maf_stale"}


def test_recent_dropsIncrementsOlderThanTheWindow(tmp_path):
    """60 s of idle then 31 s of cruise: only the cruise is in the window."""
    orch = _recentOrch(tmp_path)
    _runEvery(orch, 2.0, 60.0, maf=3.0, speed=0.0)
    orch.advance(2.0)
    _runEvery(orch, 2.0, 30.0, maf=10.0, speed=60.0)

    recent = orch.state()["recent"]

    assert recent["mafSamples"] == 15
    assert recent["mpg"] == pytest.approx(_steadyMpg(60.0, 10.0))


def test_recent_resetsAtDriveStart(tmp_path):
    orch = _recentOrch(tmp_path)
    _runEvery(orch, 2.0, 30.0, maf=10.0, speed=60.0)
    orch.advance(2.0)
    orch.startDrive()
    orch.read("MAF", 10.0)

    assert orch.state()["recent"]["mafSamples"] == 1


def test_recent_mafUntrusted_nullWithTheDriveLevelReason(tmp_path):
    orch = _recentOrch(tmp_path, fuel={"mafTrusted": False})
    _runEvery(orch, 2.0, 30.0, maf=10.0, speed=60.0)

    assert orch.state()["recent"]["mpgNullReason"] == "maf_untrusted"


def test_recent_windowAndThresholds_comeFromConfig(tmp_path):
    orch = _recentOrch(
        tmp_path, fuel={"recentWindowSec": 10, "recentMinMafSamples": 3, "recentMinMiles": 0.01}
    )
    _runEvery(orch, 2.0, 30.0, maf=10.0, speed=60.0)

    recent = orch.state()["recent"]

    assert recent["windowSec"] == 10
    assert recent["mafSamples"] == 5
    assert recent["mpg"] == pytest.approx(_steadyMpg(60.0, 10.0))


@pytest.mark.parametrize(
    "snapOver, settingsOver, recentIn, expected",
    [
        # every condition at once -> the first in precedence
        ({"lastMafEventUtc": None, "lastMafGPerS": 0.0}, {"mafTrusted": False},
         (0.0, 0.0, 0), "maf_untrusted"),
        ({"lastMafEventUtc": datetime(2026, 10, 20, 15, 3, 0, tzinfo=UTC),
          "lastMafGPerS": 0.0}, {}, (0.0, 0.0, 0), "maf_stale"),
        ({"lastMafGPerS": 0.0}, {}, (0.0, 0.0, 0), "maf_zero_running"),
        ({}, {}, (0.0, 0.0, 9), "too_few_samples"),
        ({}, {}, (0.0, 0.16, 10), "too_short"),
        ({}, {}, (0.0, 0.17, 10), "no_fuel"),
    ],
)
def test_recentNullReason_precedence(snapOver, settingsOver, recentIn, expected):
    airG, km, samples = recentIn
    recent = fee.buildFuelEconomyState(
        _snap(**snapOver), _settings(**settingsOver),
        distanceKm=6.0, distanceSinceTs=_T0_TS, nowUtc=_NOW, staleSec=5.0,
        recent=fee.RecentSnapshot(airG=airG, km=km, mafSamples=samples),
    )["recent"]

    assert recent["mpg"] is None
    assert recent["mpgNullReason"] == expected
    assert expected in fee.RECENT_NULL_REASONS


def test_recent_minimumsAreInclusive():
    """Exactly recentMinMafSamples readings and exactly recentMinMiles is a figure."""
    recent = fee.buildFuelEconomyState(
        _snap(), _settings(), distanceKm=6.0, distanceSinceTs=_T0_TS,
        nowUtc=_NOW, staleSec=5.0,
        recent=fee.RecentSnapshot(airG=100.0, km=0.1 * 1.609344, mafSamples=10),
    )["recent"]

    assert recent["mpg"] is not None
    assert set(recent) == {"mpg", "windowSec", "mafSamples"}


def test_recent_withoutAWindowSnapshot_isAnEmptyWindow():
    """A caller that passes no window gets an honest empty one, never a figure."""
    recent = fee.buildFuelEconomyState(
        _snap(), _settings(), distanceKm=6.0, distanceSinceTs=_T0_TS,
        nowUtc=_NOW, staleSec=5.0,
    )["recent"]

    assert recent["mafSamples"] == 0
    assert recent["mpgNullReason"] == "too_few_samples"


def test_recentWindow_holdsOnlyTheNewestWindowSec():
    window = fee.RecentWindow(30.0)
    window.add(0.0, airG=99.0, km=9.0, isMafSample=True)
    window.add(30.0, airG=1.0, km=0.5, isMafSample=True)
    window.add(31.0, km=0.25)

    snap = window.snapshot()

    assert (snap.airG, snap.km, snap.mafSamples) == (1.0, 0.75, 1)


def test_recentWindow_resetEmptiesIt():
    window = fee.RecentWindow(30.0)
    window.add(1.0, airG=5.0, km=0.1, isMafSample=True)
    window.reset()

    assert window.snapshot() == fee.RecentSnapshot(airG=0.0, km=0.0, mafSamples=0)


def test_integrator_observeMaf_returnsTheAirItAdded():
    integ = fee.FuelIntegrator(300.0)
    integ.reset(0.0)
    t = datetime(2026, 10, 20, 15, 0, 0, tzinfo=UTC)

    assert integ.observeMaf(10.0, 0.0, t, None) == 0.0
    assert integ.observeMaf(20.0, 2.0, t, None) == pytest.approx(30.0)
    assert integ.observeMaf(20.0, 500.0, t, None) == 0.0  # a gap adds nothing


def test_fromConfig_recentDefaultsAreTheValidatorDefaults():
    s = fee.FuelSettings.fromConfig({})

    assert (s.recentWindowSec, s.recentMinMiles, s.recentMinMafSamples) == (30.0, 0.1, 10.0)


def test_speedKmDelta_feedsTheWindow_withTheTwoLocksNeverHeldTogether(tmp_path):
    """Atlas G2: observeTripSpeed takes the fuel lock only AFTER the trip lock."""
    orch = _recentOrch(tmp_path)
    held: set[str] = set()
    overlaps: list[str] = []

    class _Lock:
        def __init__(self, name: str) -> None:
            self.name = name
            self._lock = threading.Lock()

        def __enter__(self) -> None:
            if held:
                overlaps.append(f"{self.name} inside {sorted(held)}")
            self._lock.acquire()
            held.add(self.name)

        def __exit__(self, *exc: Any) -> None:
            held.discard(self.name)
            self._lock.release()

    orch._tripLock = _Lock("trip")
    orch._fuelLock = _Lock("fuel")
    _runEvery(orch, 2.0, 30.0, maf=10.0, speed=60.0)
    recent = orch.state()["recent"]

    assert overlaps == []
    assert recent["mpg"] == pytest.approx(_steadyMpg(60.0, 10.0))


# ============================================ US-923 resetAllowed published


def test_builder_withoutAGateVerdict_omitsTheKey_withOne_carriesIt():
    """None is the shape a provider from before the gate published."""
    snap = fee.FuelIntegrator(300.0).snapshot()
    settings = fee.FuelSettings.fromConfig({})
    kw = {"distanceKm": None, "distanceSinceTs": None,
          "nowUtc": datetime(2026, 10, 22, tzinfo=UTC), "staleSec": 5.0}

    assert "resetAllowed" not in fee.buildFuelEconomyState(snap, settings, **kw)
    payload = fee.buildFuelEconomyState(
        snap, settings, resetAllowed={"value": False, "reason": "driving"}, **kw)
    assert payload["resetAllowed"] == {"value": False, "reason": "driving"}


class _Deriver:
    """Counts update calls; answers a fixed reading."""

    def __init__(self, reading: Any) -> None:
        self.reading = reading
        self.calls = 0

    def update(self, **kw: Any) -> Any:
        self.calls += 1
        return self.reading


def _gearOrch(tmp_path, reading: Any) -> tuple[_Orch, _Deriver, list[Any]]:
    orch = _orch(tmp_path)
    deriver = _Deriver(reading)
    published: list[Any] = []
    orch._gearDeriver = deriver
    orch._gearStateEmitter = published.append
    orch._gearClock = lambda: orch.t
    orch._gatherObdLinkState = lambda: ("linked", 0, True, None)
    return orch, deriver, published


def test_emitGearState_cachesTheReadingItPublished_withItsDerivationTime(tmp_path):
    from pi.obdii.gear_derivation import GearReading

    park = GearReading(available=True, gear="P", reason="park")
    orch, deriver, published = _gearOrch(tmp_path, park)

    orch._emitGearState()

    assert published == [park]
    assert (orch._lastGearReading, orch._lastGearAtS) == (park, orch.t)
    assert deriver.calls == 1


def test_publishedResetAllowed_readsTheCache_neverASecondDerivation(tmp_path):
    from pi.obdii.gear_derivation import GearReading, Reading

    orch, deriver, _ = _gearOrch(tmp_path, GearReading(True, "N", "neutral"))
    orch._emitGearState()
    calls = deriver.calls

    assert orch.state()["resetAllowed"] == {"value": True, "reason": None}
    assert deriver.calls - calls <= 1  # the tick's own gear emit, not the gate
    # Past maxAgeS the cached N ages out; a fresh 40 km/h refuses.
    orch._gearDeriver = None
    orch.advance(3.5)
    orch._lastSpeedReading = Reading(value=40.0, tsS=orch.t)
    assert orch.state()["resetAllowed"] == {"value": False, "reason": "driving"}


def test_publishedResetAllowed_noGearNoSpeed_isSpeedUnknown(tmp_path):
    """pi.gear.enabled false caches nothing: the gate fails closed."""
    assert _orch(tmp_path).state()["resetAllowed"] == {
        "value": False, "reason": "speed_unknown"}


def test_publishedResetAllowed_followsTheConfiguredLimit(tmp_path):
    from pi.obdii.gear_derivation import Reading

    orch = _orch(tmp_path, fuel={"resetMaxSpeedKph": 12})
    orch._gearClock = lambda: orch.t
    orch._lastSpeedReading = Reading(value=12.0, tsS=orch.t)
    assert orch.state()["resetAllowed"]["value"] is True
    orch._lastSpeedReading = Reading(value=13.0, tsS=orch.t)
    assert orch.state()["resetAllowed"] == {"value": False, "reason": "driving"}
