################################################################################
# File Name: test_o2_state.py
# Purpose/Description: US-891-a -- states/o2: the last windowSec of front
#   (O2_B1S1) and rear (O2_B1S2) O2 samples at their own event times, per-sensor
#   staleness by obd-live's contract, the measured samplePeriodSec, and the
#   re-emit on every card tick so `stale` can flip.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-26    | Rex (US-891-a) | Initial -- O2 tracker, builder, seam and tick.
# 2026-10-26    | Rex (US-891-b) | The front verdict: per-sample gate, the 60
#                                minimum, Spool's distribution rule, reasons.
# ================================================================================
################################################################################

"""US-891-a: the states/o2 producer, from the reading seam to tmpfs."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pi.obdii import o2_state
from pi.obdii.o2_state import (
    MIDLINE_V,
    O2_STATE_FILENAME,
    O2History,
    O2Settings,
    buildO2State,
    makeO2Emitter,
)
from pi.obdii.obd_live_emitter import ObdLiveTracker
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.event_router import EventRouterMixin

# America/Chicago is UTC-5 in October (CDT): naive local 10:00:00 = 15:00:00Z.
_ZONE = "America/Chicago"
_T0_LOCAL = datetime(2026, 10, 20, 10, 0, 0)
_T0_UTC = datetime(2026, 10, 20, 15, 0, 0, tzinfo=UTC)
_STALE_S = 5.0
_WINDOW_S = 300.0


def _at(seconds: float) -> datetime:
    return _T0_UTC + timedelta(seconds=seconds)


def _iso(seconds: float) -> str:
    return _at(seconds).strftime("%Y-%m-%dT%H:%M:%SZ")


def _history(windowSec: float = _WINDOW_S) -> O2History:
    return O2History(O2Settings(windowSec=windowSec))


def _build(history: O2History, nowS: float, staleSec: float = _STALE_S) -> dict[str, Any]:
    return buildO2State(history.snapshot(), nowUtc=_at(nowS), staleSec=staleSec)


class _Reading:
    """The shape RealtimeDataLogger hands the reading callback (LoggedReading)."""

    def __init__(self, parameterName: str, value: Any, timestamp: datetime) -> None:
        self.parameterName = parameterName
        self.value = value
        self.unit = "volt"
        self.timestamp = timestamp


def _reading(name: str, value: Any, seconds: float) -> _Reading:
    return _Reading(name, value, _T0_LOCAL + timedelta(seconds=seconds))


# ================================================================ the builder


class TestTheShape:
    """A1 RULED (Atlas 2026-10-26): the agreed states/o2 shape."""

    def test_freshFrontAndUnreadRear_isTheAgreedShape(self) -> None:
        """
        Given: front 0.78 V at t=0 and 0.12 V at t=2.2; no rear reading
        When: built at t=3
        Then: front current, rear not_read, held verdicts, write-time ts
        """
        history = _history()
        history.observe("O2_B1S1", 0.78, _at(0))
        history.observe("O2_B1S1", 0.12, _at(2.2))

        state = _build(history, 3)

        assert state == {
            "front": {
                "value": 0.12,
                "ts": _iso(2.2),
                "stale": False,
                "reason": None,
                "last": None,
                "samples": [{"v": 0.78, "ts": _iso(0)}, {"v": 0.12, "ts": _iso(2.2)}],
            },
            "rear": {
                "value": None,
                "ts": None,
                "stale": False,
                "reason": "not_read",
                "last": None,
                "samples": [],
            },
            "samplePeriodSec": 2.2,
            "windowSec": 300.0,
            "midlineV": 0.45,
            "frontVerdict": "no_data",
            "frontReason": "no_data",
            "rearVerdict": "not_rated",
            "catalystVerdict": "not_rated",
            "ts": _iso(3),
        }

    def test_midlineV_isTheOneNamedConstant(self) -> None:
        """Spec s4.2: 0.45 V has one home, published as midlineV."""
        assert MIDLINE_V == 0.45
        assert _build(_history(), 0)["midlineV"] is MIDLINE_V

    def test_rearReadings_landInRear_notFront(self) -> None:
        history = _history()
        history.observe("O2_B1S2", 0.21, _at(1))

        state = _build(history, 2)

        assert state["rear"]["value"] == 0.21
        assert state["rear"]["samples"] == [{"v": 0.21, "ts": _iso(1)}]
        assert state["front"]["reason"] == "not_read"

    def test_anotherPid_isIgnored(self) -> None:
        history = _history()
        history.observe("RPM", 900.0, _at(0))
        history.observe("O2_B1S3", 0.5, _at(0))

        state = _build(history, 1)

        assert state["front"]["samples"] == [] and state["rear"]["samples"] == []


class TestNegativeCases:
    """US-891-a negative cases, one test each."""

    def test_noO2ReadingYet_valueNull_reasonNotRead_noSamples(self) -> None:
        state = _build(_history(), 10)

        for sensor in ("front", "rear"):
            assert state[sensor]["value"] is None
            assert state[sensor]["reason"] == "not_read"
            assert state[sensor]["samples"] == []
        assert state["samplePeriodSec"] is None

    @pytest.mark.parametrize("bad", ["0.5", None, True, False, float("nan"), float("inf")])
    def test_aNonNumericValue_isDropped_neverStoredAsZero(self, bad: Any) -> None:
        history = _history()
        history.observe("O2_B1S1", 0.6, _at(0))
        history.observe("O2_B1S1", bad, _at(2))

        front = _build(history, 3)["front"]

        assert front["samples"] == [{"v": 0.6, "ts": _iso(0)}]
        assert front["value"] == 0.6 and front["ts"] == _iso(0)

    def test_aNonNumericFirstValue_leavesTheSensorNotRead(self) -> None:
        history = _history()
        history.observe("O2_B1S1", "n/a", _at(0))

        front = _build(history, 1)["front"]

        assert front["reason"] == "not_read" and front["samples"] == []

    def test_samplesOlderThanTheWindow_areGoneOnTheNextBuild(self) -> None:
        """
        Given: front samples at t=0, 100 and 299 in a 300 s window
        When: built at t=300, then again at t=301
        Then: t=0 sits exactly on the window edge and stays, then is gone
        """
        history = _history()
        for t in (0, 100, 299):
            history.observe("O2_B1S1", 0.5, _at(t))

        atEdge = _build(history, 300)["front"]["samples"]
        past = _build(history, 301)["front"]["samples"]

        assert [s["ts"] for s in atEdge] == [_iso(0), _iso(100), _iso(299)]
        assert [s["ts"] for s in past] == [_iso(100), _iso(299)]

    def test_theWindowIsTheSettingsWindow(self) -> None:
        history = _history(windowSec=60)
        for t in (0, 30, 61):
            history.observe("O2_B1S1", 0.5, _at(t))

        state = _build(history, 62)

        assert [s["ts"] for s in state["front"]["samples"]] == [_iso(30), _iso(61)]
        assert state["windowSec"] == 60

    def test_aStaleFront_stillListsItsSamples(self) -> None:
        """
        Given: front read at t=0 and t=2; nothing since
        When: built at t=8 (6 s after the last reading, obdLiveSec 5)
        Then: value null, stale, reason 'stale', last value + ts kept, samples kept
        """
        history = _history()
        history.observe("O2_B1S1", 0.70, _at(0))
        history.observe("O2_B1S1", 0.20, _at(2))

        front = _build(history, 8)["front"]

        assert front == {
            "value": None,
            "ts": _iso(2),
            "stale": True,
            "reason": "stale",
            "last": {"value": 0.20},
            "samples": [{"v": 0.70, "ts": _iso(0)}, {"v": 0.20, "ts": _iso(2)}],
        }

    def test_staleness_isObdLiveRule_ageOverStaleSec(self) -> None:
        """Exactly staleSec old is still current, as obd-live's _isStale."""
        history = _history()
        history.observe("O2_B1S1", 0.5, _at(0))

        assert _build(history, 5)["front"]["stale"] is False
        assert _build(history, 5.01)["front"]["stale"] is True
        assert _build(history, 5, staleSec=4)["front"]["reason"] == "stale"

    def test_aStaleValueOutsideTheWindow_staysAsLast(self) -> None:
        """The latest reading is not history: it outlives the window as `last`."""
        history = _history(windowSec=60)
        history.observe("O2_B1S1", 0.33, _at(0))

        front = _build(history, 100)["front"]

        assert front["samples"] == []
        assert front["last"] == {"value": 0.33} and front["ts"] == _iso(0)

    def test_oneSample_samplePeriodNull(self) -> None:
        history = _history()
        history.observe("O2_B1S1", 0.5, _at(0))

        assert _build(history, 1)["samplePeriodSec"] is None


class TestSamplePeriod:
    """A1 RULED (c): the median of consecutive FRONT deltas, rounded to 0.1 s."""

    def test_oneDroppedPoll_doesNotMoveIt(self) -> None:
        """Story example: deltas 2.2, 2.3, 2.2, 6.6 s -> 2.2."""
        history = _history()
        t = 0.0
        history.observe("O2_B1S1", 0.5, _at(t))
        for delta in (2.2, 2.3, 2.2, 6.6):
            t += delta
            history.observe("O2_B1S1", 0.5, _at(t))

        assert _build(history, t)["samplePeriodSec"] == 2.2

    def test_rearSamples_doNotMeasureIt(self) -> None:
        history = _history()
        history.observe("O2_B1S1", 0.5, _at(0))
        for t in (0, 1, 2, 3):
            history.observe("O2_B1S2", 0.2, _at(t))

        assert _build(history, 4)["samplePeriodSec"] is None

    def test_onlySamplesInsideTheWindowCount(self) -> None:
        history = _history(windowSec=60)
        for t in (0, 10, 70, 72.2, 74.4):
            history.observe("O2_B1S1", 0.5, _at(t))

        assert _build(history, 75)["samplePeriodSec"] == 2.2

    def test_measuredFromFullPrecisionEventTimes(self) -> None:
        """Second-resolution ts strings would read 2 s and 3 s; the event times say 2.5."""
        history = _history()
        for t in (0.4, 2.9, 5.4):
            history.observe("O2_B1S1", 0.5, _at(t))

        assert _build(history, 6)["samplePeriodSec"] == 2.5


class TestSettings:
    def test_windowSec_defaultsToTheValidatorDefault(self) -> None:
        assert O2Settings.fromConfig({}).windowSec == 300.0

    def test_windowSec_isReadFromConfig(self) -> None:
        config = {"pi": {"display": {"o2": {"windowSec": 120}}}}
        assert O2Settings.fromConfig(config).windowSec == 120.0


# ================================================================ the emitter


class TestTheEmitter:
    def test_writesStatesO2Atomically(self, tmp_path) -> None:
        history = _history()
        history.observe("O2_B1S1", 0.78, _at(0))
        statesDir = str(tmp_path / "states")

        makeO2Emitter(statesDir)(history.snapshot(), nowUtc=_at(1), staleSec=_STALE_S)

        with open(os.path.join(statesDir, "o2"), encoding="utf-8") as fh:
            assert json.load(fh)["front"]["value"] == 0.78
        assert O2_STATE_FILENAME == "o2"

    def test_aWriteFailure_logs_neverRaises(self, tmp_path, monkeypatch, caplog) -> None:
        from pi.splash import boot_state_emitter

        def _boom(*_: Any, **__: Any) -> None:
            raise OSError("disk gone")

        monkeypatch.setattr(boot_state_emitter, "writeStateAtomic", _boom)
        emit = makeO2Emitter(str(tmp_path))

        with caplog.at_level(logging.ERROR, logger=o2_state.logger.name):
            emit(_history().snapshot(), nowUtc=_at(0), staleSec=_STALE_S)

        assert "states/o2 write failed" in caplog.text


# ======================================================= the obd-live tracker


def _tracker(**o2: Any) -> ObdLiveTracker:
    config: dict[str, Any] = {"pi": {"time": {"localZone": _ZONE}}}
    if o2:
        config["pi"]["display"] = {"o2": o2}
    return ObdLiveTracker(config)


class TestTheReadingSeam:
    """The O2 history is owned and fed inside ObdLiveTracker.observeReading."""

    def test_theFrontSampleTs_isTheReadingsEventTs_notTheWriteTime(self) -> None:
        """
        Given: an O2_B1S1 reading captured at naive local 10:00:02 (CDT)
        When: built 40 s later
        Then: its sample and sensor ts are 15:00:02Z -- the event time
        """
        tracker = _tracker()
        tracker.observeReading(_reading("O2_B1S1", 0.78, 2))

        state = buildO2State(tracker.o2Snapshot(), nowUtc=_at(42), staleSec=_STALE_S)

        assert state["front"]["samples"] == [{"v": 0.78, "ts": _iso(2)}]
        assert state["front"]["ts"] == _iso(2)
        assert state["ts"] == _iso(42)

    def test_theWindowKey_isReadFromConfig(self) -> None:
        tracker = _tracker(windowSec=60)
        assert tracker.o2Snapshot().windowSec == 60.0

    def test_aReadingWithNoTimestamp_isNotASample(self) -> None:
        tracker = _tracker()
        reading = _reading("O2_B1S1", 0.5, 0)
        reading.timestamp = None  # type: ignore[assignment]
        tracker.observeReading(reading)

        assert tracker.o2Snapshot().front.samples == ()


# ======================================================= through the real seam


class _DriveDetector:
    def isDriving(self) -> bool:
        return True

    def processValue(self, name: str, value: Any) -> None:
        pass


class _Orch(EventRouterMixin, CardStateEmitterMixin):
    """The two REAL mixins; readings arrive at the production callback."""

    def __init__(self, statesDir: str) -> None:
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "time": {"localZone": _ZONE},
                "gear": {"enabled": False},
                "captureHealth": {"enabled": False},
            }
        }
        self.nowS = 0.0
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
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0
        self._initializeCardStateEmitters()
        self._obdLiveClock = lambda: _at(self.nowS)
        self.statesDir = statesDir

    def read(self, name: str, value: Any, seconds: float) -> None:
        self.nowS = seconds
        self._handleReading(_reading(name, value, seconds))

    def tick(self, atS: float) -> None:
        self.nowS = atS
        self._lastCardStateEmitTime = None
        assert self._maybeEmitCardStates()

    def path(self) -> str:
        return os.path.join(self.statesDir, O2_STATE_FILENAME)

    def state(self) -> dict:
        with open(self.path(), encoding="utf-8") as fh:
            return json.load(fh)


class TestThroughTheCardTick:
    """Readings at _handleReading reach states/o2 at EVERY card tick."""

    def test_aReadingReachesStatesO2_atTheTick(self, tmp_path) -> None:
        orch = _Orch(str(tmp_path / "states"))
        orch.read("O2_B1S1", 0.78, 0)
        orch.read("O2_B1S2", 0.21, 0.1)
        orch.tick(1)

        state = orch.state()
        assert state["front"]["samples"] == [{"v": 0.78, "ts": _iso(0)}]
        assert state["rear"]["value"] == 0.21

    def test_theTickReEmits_withNoNewReading_soStaleFlips(self, tmp_path) -> None:
        """
        Given: one front reading at t=0, written fresh at the t=1 tick
        When: the file is removed and the tick runs at t=8 with no new reading
        Then: states/o2 is written again, now stale, samples kept
        """
        orch = _Orch(str(tmp_path / "states"))
        orch.read("O2_B1S1", 0.78, 0)
        orch.tick(1)
        assert orch.state()["front"]["stale"] is False
        os.remove(orch.path())

        orch.tick(8)

        front = orch.state()["front"]
        assert front["stale"] is True and front["reason"] == "stale"
        assert front["samples"] == [{"v": 0.78, "ts": _iso(0)}]

    def test_theFirstTick_writesTheNotReadState(self, tmp_path) -> None:
        orch = _Orch(str(tmp_path / "states"))
        orch.tick(0)

        assert orch.state()["front"]["reason"] == "not_read"

    def test_staleSec_isPiDisplayStaleObdLiveSec(self, tmp_path) -> None:
        orch = _Orch(str(tmp_path / "states"))
        orch._obdLiveStaleSec = 2.0
        orch.read("O2_B1S1", 0.5, 0)
        orch.tick(3)

        assert orch.state()["front"]["stale"] is True


# ================================================== US-891-b: the front verdict

_PERIOD_S = 2.2
_STATUS_LEAD_S = 0.14
_COOLANT_LEAD_S = 0.07


def _cycles(
    history: O2History,
    volts: list[float],
    *,
    status: Any = 2,
    coolantC: Any = 90.0,
    startS: float = 0.0,
    statusLeadS: float = _STATUS_LEAD_S,
    coolantLeadS: float = _COOLANT_LEAD_S,
) -> float:
    """One poll cycle per volt: status, coolant, then the front O2 sample.

    Returns the event time (s) of the last front sample.
    """
    t = startS
    for i, v in enumerate(volts):
        t = startS + i * _PERIOD_S
        if status is not None:
            history.observe("FUEL_SYSTEM_STATUS", status, _at(t - statusLeadS))
        if coolantC is not None:
            history.observe("COOLANT_TEMP", coolantC, _at(t - coolantLeadS))
        history.observe("O2_B1S1", v, _at(t))
    return t


def _verdict(history: O2History, nowS: float) -> tuple[str, str | None]:
    state = _build(history, nowS)
    return state["frontVerdict"], state["frontReason"]


class TestTheDistributionRule:
    """Spec s4.2 (Spool 2026-10-13): fractions of the gated front samples."""

    def test_storyExample_70gated_30pcLow_35pcHigh_isSwitching(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 21 + [0.8] * 25 + [0.45] * 24)

        assert _verdict(history, last) == ("switching", None)

    def test_switching_atExactlyTwentyPercentEachSide(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 12 + [0.8] * 12 + [0.45] * 36)

        assert _verdict(history, last) == ("switching", None)

    def test_justUnderTwentyPercentLow_isNotSwitching(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 11 + [0.8] * 12 + [0.45] * 37)

        assert _verdict(history, last) == ("unclear", "unclear")

    def test_theSwitchingBands_areStrict(self) -> None:
        """0.30 V is not below 0.30 and 0.60 V is not above 0.60."""
        history = _history()
        last = _cycles(history, [0.30] * 30 + [0.60] * 30)

        assert _verdict(history, last) == ("unclear", "unclear")

    def test_stuckLean_atExactlyNinetyPercent(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 54 + [0.5] * 6)

        assert _verdict(history, last) == ("stuck_lean", None)

    def test_justUnderNinetyPercentLean_isUnclear(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 53 + [0.5] * 7)

        assert _verdict(history, last) == ("unclear", "unclear")

    def test_stuckRich_atExactlyNinetyPercent(self) -> None:
        history = _history()
        last = _cycles(history, [0.8] * 54 + [0.4] * 6)

        assert _verdict(history, last) == ("stuck_rich", None)

    def test_justUnderNinetyPercentRich_isUnclear(self) -> None:
        history = _history()
        last = _cycles(history, [0.8] * 53 + [0.4] * 7)

        assert _verdict(history, last) == ("unclear", "unclear")

    def test_aSampleOnTheMidline_isNeitherLeanNorRich(self) -> None:
        history = _history()
        last = _cycles(history, [0.45] * 60)

        assert _verdict(history, last) == ("unclear", "unclear")

    def test_theRuleConstants_areNamedInO2State(self) -> None:
        assert o2_state.SWITCH_LOW_V == 0.30
        assert o2_state.SWITCH_HIGH_V == 0.60
        assert o2_state.SWITCH_MIN_FRACTION == 0.20
        assert o2_state.STUCK_MIN_FRACTION == 0.90
        assert o2_state.VERDICT_MIN_GATED_SAMPLES == 60
        assert o2_state.GATE_COOLANT_MIN_C == 85.0
        assert o2_state.GATE_PAIR_MAX_SEC == 1.1


class TestNotEnoughData:
    def test_59gatedSamples_isNotEnoughData(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 30 + [0.8] * 29)

        assert _verdict(history, last) == ("not_enough_data", "not_enough_data")

    def test_60gatedSamples_isEnough(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 30 + [0.8] * 30)

        assert _verdict(history, last)[0] == "switching"

    def test_onlySamplesInsideTheWindowCount(self) -> None:
        """70 gated samples, but only ~55 fit in a 120 s window."""
        history = _history(windowSec=120)
        last = _cycles(history, [0.1] * 35 + [0.8] * 35)

        assert _verdict(history, last) == ("not_enough_data", "not_enough_data")

    def test_rearSamples_neverCount(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 30 + [0.8] * 29)
        for i in range(10):
            history.observe("O2_B1S2", 0.1, _at(last + 0.01 * i))

        assert _verdict(history, last)[0] == "not_enough_data"


class TestThePerSampleGate:
    """A sample counts only with paired status 2 AND paired coolant >= 85 C."""

    def test_status5Samples_doNotCount(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 35 + [0.8] * 35, status=5)

        assert _verdict(history, last) == ("not_enough_data", "not_enough_data")

    def test_aLatestStatusOf5_neverReadsOpenLoop(self) -> None:
        """Story example: latest status 5 with 10 code-2 samples -> not_enough_data."""
        history = _history()
        last = _cycles(history, [0.1] * 5 + [0.8] * 5)
        last = _cycles(history, [0.45] * 5, status=5, startS=last + _PERIOD_S)

        assert _verdict(history, last) == ("not_enough_data", "not_enough_data")

    def test_coolant84_samplesDoNotCount(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 35 + [0.8] * 35, coolantC=84.0)

        assert _verdict(history, last)[0] == "warming_up"

    def test_coolantExactly85_counts(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 30 + [0.8] * 30, coolantC=85.0)

        assert _verdict(history, last)[0] == "switching"

    def test_aStatusReading1point5sBeforeTheSample_isNotPaired(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 35 + [0.8] * 35, statusLeadS=1.5)

        assert _verdict(history, last)[0] == "not_enough_data"

    def test_aCoolantReading1point5sBeforeTheSample_isNotPaired(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 35 + [0.8] * 35, coolantLeadS=1.5)

        assert _verdict(history, last)[0] == "not_enough_data"

    def test_aStatusReadingExactly1point1sBefore_isPaired(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 30 + [0.8] * 30, statusLeadS=1.1)

        assert _verdict(history, last)[0] == "switching"

    def test_aStatusReadingAfterTheSample_isNotPaired(self) -> None:
        """At or before: a gate read 0.1 s AFTER the sample does not gate it."""
        history = _history()
        last = _cycles(history, [0.1] * 35 + [0.8] * 35, statusLeadS=-0.1)

        assert _verdict(history, last)[0] == "not_enough_data"

    def test_theLatestGateAtOrBefore_decides_notAnEarlierGoodOne(self) -> None:
        """Status 2 at t-0.5 then status 1 at t-0.1: the sample is open loop."""
        history = _history()
        last = 0.0
        for i in range(70):
            last = i * _PERIOD_S
            history.observe("FUEL_SYSTEM_STATUS", 2, _at(last - 0.5))
            history.observe("FUEL_SYSTEM_STATUS", 1, _at(last - 0.1))
            history.observe("COOLANT_TEMP", 90.0, _at(last - 0.07))
            history.observe("O2_B1S1", 0.1 if i % 2 else 0.8, _at(last))

        assert _verdict(history, last) == ("open_loop", "open_loop")

    def test_closedLoopIsTheImportedLtftConstant(self) -> None:
        """Spool S3: the EXISTING code-2-only constant, not a new literal."""
        from pi.splash import ltft_trend_emitter

        assert o2_state.FUEL_SYSTEM_CLOSED_LOOP is ltft_trend_emitter.FUEL_SYSTEM_CLOSED_LOOP

    def test_aFloatStatus2point0_isClosedLoop(self) -> None:
        """realtime_data carries the code as a float (decoders: float(code))."""
        history = _history()
        last = _cycles(history, [0.1] * 30 + [0.8] * 30, status=2.0)

        assert _verdict(history, last)[0] == "switching"


class TestTheWithheldReason:
    """Fewer than 60 gated samples: the reason by the latest paired readings."""

    def test_status2_coolant84_isWarmingUp(self) -> None:
        history = _history()
        last = _cycles(history, [0.5] * 10, coolantC=84.0)

        assert _verdict(history, last) == ("warming_up", "warming_up")

    def test_storyExample_coolant80_closedLoop_isWarmingUp(self) -> None:
        history = _history()
        last = _cycles(history, [0.5] * 3, coolantC=80.0)

        assert _verdict(history, last) == ("warming_up", "warming_up")

    @pytest.mark.parametrize("status", [1, 3, 4, 1.0, 3.0])
    def test_openLoopCodes_readOpenLoop(self, status: Any) -> None:
        history = _history()
        last = _cycles(history, [0.5] * 10, status=status)

        assert _verdict(history, last) == ("open_loop", "open_loop")

    def test_status5_isNotOpenLoop(self) -> None:
        history = _history()
        last = _cycles(history, [0.5] * 10, status=5)

        assert _verdict(history, last) == ("not_enough_data", "not_enough_data")

    def test_status2_warmCoolant_isNotEnoughData(self) -> None:
        history = _history()
        last = _cycles(history, [0.5] * 10)

        assert _verdict(history, last) == ("not_enough_data", "not_enough_data")

    def test_noStatusReading_isNoData(self) -> None:
        history = _history()
        last = _cycles(history, [0.1] * 35 + [0.8] * 35, status=None)

        assert _verdict(history, last) == ("no_data", "no_data")

    def test_nothingReadAtAll_isNoData(self) -> None:
        assert _verdict(_history(), 0) == ("no_data", "no_data")

    @pytest.mark.parametrize("bad", [None, "CL", True, float("nan")])
    def test_aNonNumericStatus_isNotAStatus(self, bad: Any) -> None:
        history = _history()
        last = _cycles(history, [0.5] * 10, status=bad)

        assert _verdict(history, last) == ("no_data", "no_data")

    def test_aStaleStatus_isNoData(self) -> None:
        """obd-live's value-means-CURRENT: a status older than obdLiveSec is absent."""
        history = _history()
        last = _cycles(history, [0.5] * 10, status=1)

        # The last status was read at last - 0.14 s: 4.94 s old, then 5.06 s old.
        assert _verdict(history, last + 4.8) == ("open_loop", "open_loop")
        assert _verdict(history, last + 4.92) == ("no_data", "no_data")

    def test_status2_unpairedCoolant_isNotWarmingUp(self) -> None:
        """A cold coolant 2 s from the latest status is another cycle's."""
        history = _history()
        history.observe("COOLANT_TEMP", 60.0, _at(0))
        history.observe("FUEL_SYSTEM_STATUS", 2, _at(2))

        assert _verdict(history, 2) == ("not_enough_data", "not_enough_data")

    def test_status2_coolantJustAfterIt_isPaired(self) -> None:
        """Status and coolant of one cycle, coolant polled 0.1 s after status."""
        history = _history()
        history.observe("FUEL_SYSTEM_STATUS", 2, _at(0))
        history.observe("COOLANT_TEMP", 60.0, _at(0.1))

        assert _verdict(history, 0.1) == ("warming_up", "warming_up")

    def test_enoughGatedSamples_winsOverTheLatestStatus(self) -> None:
        """A switching window stays SWITCHING when the latest status is open loop."""
        history = _history()
        last = _cycles(history, [0.1] * 30 + [0.8] * 30)
        history.observe("FUEL_SYSTEM_STATUS", 3, _at(last + 1))

        assert _verdict(history, last + 1)[0] == "switching"


class TestTheVerdictThroughTheSeam:
    def test_trackerFeedsTheGateReadings(self) -> None:
        tracker = _tracker()
        for i in range(60):
            t = 10 + i * _PERIOD_S
            tracker.observeReading(_reading("FUEL_SYSTEM_STATUS", 2.0, t - 0.14))
            tracker.observeReading(_reading("COOLANT_TEMP", 90.0, t - 0.07))
            tracker.observeReading(_reading("O2_B1S1", 0.1 if i % 2 else 0.8, t))

        state = buildO2State(
            tracker.o2Snapshot(), nowUtc=_at(10 + 59 * _PERIOD_S), staleSec=_STALE_S
        )

        assert state["frontVerdict"] == "switching"
        assert state["frontReason"] is None

    def test_importingO2State_hasNoCycle(self) -> None:
        import subprocess
        import sys

        # As the tests run: the repo root is the cwd and src is on the path.
        repoRoot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        env = dict(os.environ, PYTHONPATH=os.path.join(repoRoot, "src") + os.pathsep + repoRoot)
        result = subprocess.run(
            [sys.executable, "-c", "import pi.obdii.o2_state"],
            cwd=repoRoot,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        assert result.returncode == 0, result.stderr
