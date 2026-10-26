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
