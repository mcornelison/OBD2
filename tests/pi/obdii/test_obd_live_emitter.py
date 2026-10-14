################################################################################
# File Name: test_obd_live_emitter.py
# Purpose/Description: US-874 -- states/obd-live: every live PID with its value,
#   unit, own event time and a band (null until US-875). Pins the pure builder's
#   three per-PID shapes (fresh / stale / never read = absent), the conversion of
#   the reading's NAIVE LOCAL timestamp to canonical UTC, the file-level
#   dataSource taken from the logger's own resolved tag, the path from the real
#   _handleReading seam to the file, and the contract fixture.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-13    | Rex (US-874) | Initial -- obd-live producer and fixture.
# ================================================================================
################################################################################

"""US-874: the states/obd-live producer, from the reading seam to tmpfs."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from pi.obdii import obd_live_emitter as ole
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.event_router import EventRouterMixin

_ZONE_CONFIG = {"pi": {"time": {"localZone": "America/Chicago"}}}
_PID_KEYS = {"value", "unit", "ts", "stale", "band", "last"}
_TOP_LEVEL_KEYS = {"params", "dataSource", "ts"}

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "ui" / "fixtures" / "states" / "obd-live.json"
)


def _obs(value: Any, unit: str | None, ts: str) -> ole.ObdLiveObservation:
    return ole.ObdLiveObservation(value=value, unit=unit, ts=ts)


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class _Reading:
    """The shape RealtimeDataLogger hands the reading callback (LoggedReading)."""

    def __init__(
        self, parameterName: str, value: Any, timestamp: Any, unit: str | None = None
    ) -> None:
        self.parameterName = parameterName
        self.value = value
        self.unit = unit
        self.timestamp = timestamp


class _UtcClock:
    """A wall clock the test advances by hand (aware UTC)."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


# ================================================================ pure builder


class TestBuildObdLiveState:
    """The three per-PID shapes, decided at emit time against the stale window."""

    def test_freshReading_publishesValueUnitTsAndNullBand(self) -> None:
        """
        Given: RPM 812 read at 12:05:01Z
        When: the state is built at 12:05:03Z with a 5 s window
        Then: the fresh shape -- value 812, stale false, band null, last null
        """
        state = ole.buildObdLiveState(
            {"RPM": _obs(812, "rpm", "2026-10-13T12:05:01Z")},
            nowUtc=_utc("2026-10-13T12:05:03Z"),
            staleSec=5.0,
            dataSource="real",
        )

        assert state == {
            "params": {
                "RPM": {
                    "value": 812, "unit": "rpm", "ts": "2026-10-13T12:05:01Z",
                    "stale": False, "band": None, "last": None,
                }
            },
            "dataSource": "real",
            "ts": "2026-10-13T12:05:03Z",
        }

    def test_staleReading_neverPublishesTheOldValueAsCurrent(self) -> None:
        """
        Given: COOLANT_TEMP 88 read at 12:04:55Z
        When: built at 12:05:03Z (8 s later, window 5 s)
        Then: value null, ts of the last reading, stale true, band null,
              last {value: 88, band: null}
        """
        state = ole.buildObdLiveState(
            {"COOLANT_TEMP": _obs(88, "C", "2026-10-13T12:04:55Z")},
            nowUtc=_utc("2026-10-13T12:05:03Z"),
            staleSec=5.0,
            dataSource="real",
        )

        assert state["params"]["COOLANT_TEMP"] == {
            "value": None, "unit": "C", "ts": "2026-10-13T12:04:55Z",
            "stale": True, "band": None, "last": {"value": 88, "band": None},
        }

    def test_ageExactlyAtTheWindow_isStillFresh(self) -> None:
        """
        Given: a reading exactly staleSec old
        When: built
        Then: fresh -- the rule is age > window, not >=
        """
        state = ole.buildObdLiveState(
            {"SPEED": _obs(40, "km/h", "2026-10-13T12:00:00Z")},
            nowUtc=_utc("2026-10-13T12:00:05Z"),
            staleSec=5.0,
            dataSource="real",
        )

        assert state["params"]["SPEED"]["stale"] is False
        assert state["params"]["SPEED"]["value"] == 40

    def test_staleWindow_isTheArgumentNotALiteral(self) -> None:
        """
        Given: a reading 3 s old
        When: built with a 2 s window
        Then: stale -- the window comes from the caller (config), not the module
        """
        state = ole.buildObdLiveState(
            {"SPEED": _obs(40, "km/h", "2026-10-13T12:00:00Z")},
            nowUtc=_utc("2026-10-13T12:00:03Z"),
            staleSec=2.0,
            dataSource="real",
        )

        assert state["params"]["SPEED"]["stale"] is True

    def test_noObservations_publishesEmptyParams(self) -> None:
        """
        Given: nothing read this process
        When: built
        Then: params is empty -- a PID never read is ABSENT, not 0 or null
        """
        state = ole.buildObdLiveState(
            {}, nowUtc=_utc("2026-10-13T12:00:00Z"), staleSec=5.0, dataSource=None
        )

        assert state == {"params": {}, "dataSource": None, "ts": "2026-10-13T12:00:00Z"}

    def test_bandIsNullForEveryPid(self) -> None:
        """
        Given: several PIDs, fresh and stale
        When: built
        Then: band is null on every one (US-875 fills it)
        """
        state = ole.buildObdLiveState(
            {
                "RPM": _obs(812, "rpm", "2026-10-13T12:00:09Z"),
                "SPEED": _obs(0, "km/h", "2026-10-13T12:00:00Z"),
            },
            nowUtc=_utc("2026-10-13T12:00:10Z"),
            staleSec=5.0,
            dataSource="real",
        )

        for pid in state["params"].values():
            assert pid["band"] is None
            assert set(pid) == _PID_KEYS


# ===================================================================== tracker


class TestObdLiveTracker:
    """Every PID observed this process, stamped with its own event time."""

    def test_observeReading_convertsNaiveLocalTimestampToCanonicalUtc(self) -> None:
        """
        Given: America/Chicago declared, an RPM reading stamped 12:00:00 local (CDT)
        When: observed
        Then: its ts is 17:00:00Z -- not the local wall time
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        tracker.observeReading(_Reading("RPM", 812.0, datetime(2026, 10, 13, 12, 0, 0), "rpm"))

        assert tracker.snapshot()["RPM"] == _obs(812.0, "rpm", "2026-10-13T17:00:00Z")

    def test_observeReading_keepsOnlyTheLatestPerPid(self) -> None:
        """
        Given: two RPM readings and one SPEED reading
        When: observed
        Then: one entry per PID, holding the newest reading
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)
        t = datetime(2026, 10, 13, 12, 0, 0)

        tracker.observeReading(_Reading("RPM", 800.0, t, "rpm"))
        tracker.observeReading(_Reading("SPEED", 0.0, t, "km/h"))
        tracker.observeReading(_Reading("RPM", 900.0, t + timedelta(seconds=2), "rpm"))

        snap = tracker.snapshot()
        assert set(snap) == {"RPM", "SPEED"}
        assert snap["RPM"] == _obs(900.0, "rpm", "2026-10-13T17:00:02Z")

    def test_readingWithoutTimestamp_isNotObserved(self) -> None:
        """
        Given: a reading with no capture timestamp
        When: observed
        Then: nothing is recorded -- the write time is never substituted
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        tracker.observeReading(_Reading("RPM", 812.0, None, "rpm"))

        assert tracker.snapshot() == {}

    def test_readingWithNoValue_isNotObserved(self) -> None:
        """
        Given: a reading whose value is None
        When: observed
        Then: nothing is recorded -- null means not read, so it cannot be a reading
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        tracker.observeReading(_Reading("RPM", None, datetime(2026, 10, 13, 12), "rpm"))

        assert tracker.snapshot() == {}

    def test_snapshot_isACopy(self) -> None:
        """
        Given: a snapshot taken
        When: a later reading arrives
        Then: the earlier snapshot is unchanged (the emit tick reads a stable view)
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)
        tracker.observeReading(_Reading("RPM", 800.0, datetime(2026, 10, 13, 12), "rpm"))
        snap = tracker.snapshot()

        tracker.observeReading(_Reading("SPEED", 5.0, datetime(2026, 10, 13, 12), "km/h"))

        assert set(snap) == {"RPM"}


# ================================================================= the emitter


def test_makeObdLiveEmitter_writesTheStateFileAtomically(tmp_path) -> None:
    """
    Given: an emitter over a tmp states dir
    When: it emits one observation
    Then: states/obd-live holds the built payload
    """
    statesDir = str(tmp_path / "states")
    emit = ole.makeObdLiveEmitter(statesDir)

    emit(
        {"RPM": _obs(812, "rpm", "2026-10-13T12:05:01Z")},
        nowUtc=_utc("2026-10-13T12:05:03Z"),
        staleSec=5.0,
        dataSource="real",
    )

    with open(os.path.join(statesDir, ole.OBD_LIVE_STATE_FILENAME), encoding="utf-8") as fh:
        written = json.load(fh)
    assert written["params"]["RPM"]["value"] == 812
    assert set(written) == _TOP_LEVEL_KEYS


def test_makeObdLiveEmitter_neverRaisesOnAWriteFailure(tmp_path, monkeypatch) -> None:
    """
    Given: the atomic writer raises
    When: the emitter is called
    Then: it logs and returns -- the orchestrator loop is never crashed
    """
    import pi.splash.boot_state_emitter as bse

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("tmpfs full")

    monkeypatch.setattr(bse, "writeStateAtomic", boom)
    emit = ole.makeObdLiveEmitter(str(tmp_path / "states"))

    emit({}, nowUtc=_utc("2026-10-13T12:00:00Z"), staleSec=5.0, dataSource="real")


# ======================================================= through the real seam


class _DataLogger:
    """ObdDataLogger stand-in: only the resolved tag the emitter reads."""

    def __init__(self, dataSource: str) -> None:
        self.dataSource = dataSource


class _RealtimeLogger:
    """RealtimeDataLogger stand-in: exposes the inner writer as ``dataLogger``."""

    def __init__(self, dataSource: str) -> None:
        self.dataLogger = _DataLogger(dataSource)


class _Orch(EventRouterMixin, CardStateEmitterMixin):
    """The two REAL mixins; the reading arrives at the production callback."""

    def __init__(
        self, statesDir: str, clock: _UtcClock, *, staleSec: float | None = None,
        dataSource: str | None = "real",
    ) -> None:
        display: dict[str, Any] = {}
        if staleSec is not None:
            display = {"stale": {"obdLiveSec": staleSec}}
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
                "display": display,
                "time": {"localZone": "America/Chicago"},
                "gear": {"enabled": False},
                "captureHealth": {"enabled": False},
            }
        }
        self._obdLiveClock = clock
        self._dataLogger = None if dataSource is None else _RealtimeLogger(dataSource)
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        self._displayManager = None
        self._alertManager = None
        self._milEdgeDetector = None
        self._dtcLogger = None
        self._alertsPausedForReconnect = False
        self._dashboardParameters = []
        self._healthCheckStats = type("S", (), {"totalReadings": 0, "totalErrors": 0})()
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


def _readObdLive(statesDir: str) -> dict:
    with open(os.path.join(statesDir, ole.OBD_LIVE_STATE_FILENAME), encoding="utf-8") as fh:
        return json.load(fh)


# 12:00:00 America/Chicago in October is CDT (UTC-5) -> 17:00:00Z.
_T_LOCAL = datetime(2026, 10, 13, 12, 0, 0)
_T_UTC = datetime(2026, 10, 13, 17, 0, 0, tzinfo=UTC)


class TestThroughTheReadingSeam:
    """Readings arriving at _handleReading reach states/obd-live."""

    def test_eachPidCarriesItsOwnEventTime(self, tmp_path) -> None:
        """
        Given: RPM read at t and SPEED at t+1 through _handleReading
        When: the card tick emits
        Then: params.RPM.ts = t, params.SPEED.ts = t+1, band null
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC + timedelta(seconds=2)))

        orch._handleReading(_Reading("RPM", 812.0, _T_LOCAL, "rpm"))
        orch._handleReading(_Reading("SPEED", 40.0, _T_LOCAL + timedelta(seconds=1), "km/h"))
        orch._maybeEmitCardStates()

        params = _readObdLive(statesDir)["params"]
        assert params["RPM"]["ts"] == "2026-10-13T17:00:00Z"
        assert params["SPEED"]["ts"] == "2026-10-13T17:00:01Z"
        assert params["RPM"]["band"] is None
        assert params["SPEED"]["band"] is None

    def test_aReadingSixSecondsOld_isPublishedStale(self, tmp_path) -> None:
        """
        Given: COOLANT_TEMP 85 at t, default window
        When: emitted at t+6 s with no further reading
        Then: {value: null, ts: t, stale: true, band: null, last: {value: 85, band: null}}
        """
        statesDir = str(tmp_path / "states")
        clock = _UtcClock(_T_UTC)
        orch = _Orch(statesDir, clock)

        orch._handleReading(_Reading("COOLANT_TEMP", 85.0, _T_LOCAL, "C"))
        clock.now = _T_UTC + timedelta(seconds=6)
        orch._maybeEmitCardStates()

        assert _readObdLive(statesDir)["params"]["COOLANT_TEMP"] == {
            "value": None, "unit": "C", "ts": "2026-10-13T17:00:00Z",
            "stale": True, "band": None, "last": {"value": 85.0, "band": None},
        }

    def test_staleWindow_isReadFromConfig(self, tmp_path) -> None:
        """
        Given: pi.display.stale.obdLiveSec = 10
        When: a reading is emitted 6 s old
        Then: still fresh -- the window is the config key
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC + timedelta(seconds=6)), staleSec=10.0)

        orch._handleReading(_Reading("COOLANT_TEMP", 85.0, _T_LOCAL, "C"))
        orch._maybeEmitCardStates()

        assert _readObdLive(statesDir)["params"]["COOLANT_TEMP"]["value"] == 85.0

    def test_aPidNeverReadIsAbsent(self, tmp_path) -> None:
        """
        Given: only RPM has been read
        When: emitted
        Then: params holds RPM alone
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC))

        orch._handleReading(_Reading("RPM", 812.0, _T_LOCAL, "rpm"))
        orch._maybeEmitCardStates()

        assert set(_readObdLive(statesDir)["params"]) == {"RPM"}

    @pytest.mark.parametrize("tag", ["real", "replay", "physics_sim"])
    def test_dataSource_isTheLoggersResolvedTag(self, tmp_path, tag: str) -> None:
        """
        Given: the data logger resolved its rows' data_source as <tag>
        When: emitted
        Then: obd-live.dataSource is that same tag, once, at file level
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC), dataSource=tag)

        orch._handleReading(_Reading("RPM", 812.0, _T_LOCAL, "rpm"))
        orch._maybeEmitCardStates()

        state = _readObdLive(statesDir)
        assert state["dataSource"] == tag
        assert "dataSource" not in state["params"]["RPM"]

    def test_noDataLogger_publishesNullDataSource(self, tmp_path) -> None:
        """
        Given: no data logger exists
        When: emitted
        Then: dataSource null -- never a guessed 'real'
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC), dataSource=None)

        orch._maybeEmitCardStates()

        assert _readObdLive(statesDir)["dataSource"] is None

    def test_cardsDisabled_writesNoFile(self, tmp_path) -> None:
        """
        Given: pi.dashboard.stateEmitEnabled false (no producer built)
        When: a reading arrives
        Then: no obd-live file and no error on the poll path
        """
        statesDir = str(tmp_path / "states")

        class _Off(_Orch):
            _cardStateEmitEnabled = False

            def _initializeCardStateEmitters(self) -> None:
                self._cardStateEmitEnabled = False
                super()._initializeCardStateEmitters()

        orch = _Off(statesDir, _UtcClock(_T_UTC))
        orch._handleReading(_Reading("RPM", 812.0, _T_LOCAL, "rpm"))
        orch._maybeEmitCardStates()

        assert not os.path.exists(os.path.join(statesDir, ole.OBD_LIVE_STATE_FILENAME))


# ================================================================ the fixture


class TestTheContractFixture:
    """tests/ui/fixtures/states/obd-live.json: named, complete payloads (Iris S-7)."""

    _CASES = ("fresh", "stale", "pid-absent", "replay")

    @staticmethod
    def _load() -> dict[str, Any]:
        with open(_FIXTURE_PATH, encoding="utf-8") as fh:
            return json.load(fh)

    def test_fixture_holdsTheNamedCases(self) -> None:
        """
        Given: the fixture file
        When: loaded
        Then: it is an object holding at least this story's four cases
        """
        assert set(self._CASES) <= set(self._load())

    def test_replayCase_carriesReplayDataSource(self) -> None:
        """
        Given: the replay case
        When: read
        Then: its file-level dataSource is 'replay'
        """
        assert self._load()["replay"]["dataSource"] == "replay"

    @pytest.mark.parametrize("case", _CASES)
    def test_fixture_everyCaseIsWhatTheBuilderEmits(self, case: str) -> None:
        """
        Given: one named case, a complete obd-live payload
        When: its readings (fresh value or last.value, unit, ts) are rebuilt
              at the case's ts with the default window
        Then: the builder's output equals the case exactly
        """
        payload = self._load()[case]
        assert set(payload) == _TOP_LEVEL_KEYS

        observations = {}
        for name, pid in payload["params"].items():
            assert set(pid) == _PID_KEYS
            value = pid["last"]["value"] if pid["stale"] else pid["value"]
            observations[name] = _obs(value, pid["unit"], pid["ts"])

        built = ole.buildObdLiveState(
            observations,
            nowUtc=_utc(payload["ts"]),
            staleSec=ole.DEFAULT_OBD_LIVE_STALE_S,
            dataSource=payload["dataSource"],
        )

        assert built == payload
