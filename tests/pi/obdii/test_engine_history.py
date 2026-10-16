################################################################################
# File Name: test_engine_history.py
# Purpose/Description: US-889-a -- states/engine-history: this drive's
#   COOLANT_TEMP, INTAKE_TEMP and BATTERY_V as worst-band buckets on the epoch
#   grid. Pins the bucket rules (last value, worst band, omitted gaps, trim),
#   the reading seam (band copied at each reading, not at the tick), the drive
#   start reset and the restart-mid-drive partial window through the real
#   mixins, and the R29 contract fixture.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-889-a) | Initial -- engine-history producer and fixture.
# ================================================================================
################################################################################

"""US-889-a: the states/engine-history producer, from the reading seam to tmpfs."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from pi.obdii import engine_history as eh
from pi.obdii.drive.types import DriveSession
from pi.obdii.obd_live_emitter import ObdLiveTracker
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.event_router import EventRouterMixin

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "ui" / "fixtures" / "states" / "engine-history.json"
)

# America/Chicago is UTC-5 in October (CDT): naive local 10:00:00 = 15:00:00Z,
# which is on the 30 s epoch grid.
_ZONE = "America/Chicago"
_T0_LOCAL = datetime(2026, 10, 20, 10, 0, 0)
_T0_UTC = datetime(2026, 10, 20, 15, 0, 0, tzinfo=UTC)
_DRIVE_ID = 118


def _toUtc(local: datetime) -> datetime:
    return local.replace(tzinfo=ZoneInfo(_ZONE)).astimezone(UTC)


def _at(seconds: float) -> datetime:
    return _T0_UTC + timedelta(seconds=seconds)


def _iso(seconds: float) -> str:
    return _at(seconds).strftime("%Y-%m-%dT%H:%M:%SZ")


def _history(intervalSec: float = 30, maxPoints: int = 240) -> eh.EngineHistory:
    return eh.EngineHistory(eh.EngineHistorySettings(intervalSec, maxPoints))


class _Reading:
    """The shape RealtimeDataLogger hands the reading callback (LoggedReading)."""

    def __init__(
        self, parameterName: str, value: Any, timestamp: datetime, unit: str | None
    ) -> None:
        self.parameterName = parameterName
        self.value = value
        self.unit = unit
        self.timestamp = timestamp


# The MEASURED python-obd unit names (US-888-b); the tracker canonicalises them.
_PY_OBD_UNIT = {
    "COOLANT_TEMP": "degree_Celsius",
    "INTAKE_TEMP": "degree_Celsius",
    "BATTERY_V": "volt",
    "RPM": "revolutions_per_minute",
}


def _reading(name: str, value: Any, seconds: float) -> _Reading:
    return _Reading(name, value, _T0_LOCAL + timedelta(seconds=seconds), _PY_OBD_UNIT[name])


# ================================================================ the buckets


class TestBuckets:
    """EngineHistory alone: the per-bucket rules (Atlas S104 ruling 1)."""

    def test_aBucketKeepsItsLastValueAndItsWorstBand(self) -> None:
        """
        Given: COOLANT 103.0 green at t=0, 105.5 amber at t=10, 101.0 green at
               t=29, intervalSec 30
        When: the bucket closes
        Then: one point -- value 101.0 (last), band amber (worst held)
        """
        history = _history()
        history.observe("COOLANT_TEMP", 103.0, _at(0), "green", "C")
        history.observe("COOLANT_TEMP", 105.5, _at(10), "amber", "C")
        history.observe("COOLANT_TEMP", 101.0, _at(29), "green", "C")
        history.observe("COOLANT_TEMP", 100.0, _at(30), "green", "C")

        assert history.snapshot()["series"]["COOLANT_TEMP"] == [
            {"ts": _iso(30), "value": 101.0, "band": "amber"},
        ]

    @pytest.mark.parametrize(
        ("bands", "worst"),
        [
            (["green", "red", "amber"], "red"),
            (["amber", "green"], "amber"),
            ([None, "green"], "green"),
            ([None, None], None),
        ],
    )
    def test_worstBand_orderIsRedAmberGreenNull(self, bands, worst) -> None:
        history = _history()
        for i, band in enumerate(bands):
            history.observe("BATTERY_V", 14.0, _at(i), band, "V")
        history.observe("BATTERY_V", 14.0, _at(30), None, "V")

        assert history.snapshot()["series"]["BATTERY_V"][0]["band"] == worst

    def test_theOpenBucketIsNotPublished(self) -> None:
        """A point is published only when its bucket has closed."""
        history = _history()
        history.observe("COOLANT_TEMP", 88.0, _at(0), "green", "C")
        history.observe("COOLANT_TEMP", 88.5, _at(20), "green", "C")

        assert history.snapshot()["series"]["COOLANT_TEMP"] == []

    def test_aGap_omitsItsBuckets_noNullPoint(self) -> None:
        """
        Given: COOLANT every 10 s for t=0..50, none for t=60..110, again t=120..150
        When: t=180 closes the last bucket
        Then: points end at 01:00 and resume at 02:30 -- nothing between
        """
        history = _history()
        for t in (0, 10, 20, 30, 40, 50, 120, 130, 140, 150, 160, 170, 180):
            history.observe("COOLANT_TEMP", 90.0, _at(t), "green", "C")

        assert [p["ts"] for p in history.snapshot()["series"]["COOLANT_TEMP"]] == [
            _iso(30), _iso(60), _iso(150), _iso(180),
        ]

    @pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True, "88"])
    def test_aReadingWithNoFreshValue_isNotASample(self, value) -> None:
        """A null (or non-finite) reading opens no bucket and changes none."""
        history = _history()
        history.observe("COOLANT_TEMP", 88.0, _at(0), "green", "C")
        history.observe("COOLANT_TEMP", value, _at(10), "red", "C")
        history.observe("COOLANT_TEMP", 89.0, _at(30), "green", "C")

        assert history.snapshot()["series"]["COOLANT_TEMP"] == [
            {"ts": _iso(30), "value": 88.0, "band": "green"},
        ]

    def test_aPidOutsideTheThree_isIgnored(self) -> None:
        history = _history()
        history.observe("RPM", 900.0, _at(0), "green", "rpm")
        history.observe("RPM", 900.0, _at(30), "green", "rpm")

        snap = history.snapshot()
        assert set(snap["series"]) == {"COOLANT_TEMP", "INTAKE_TEMP", "BATTERY_V"}
        assert "RPM" not in snap["unit"]

    def test_unit_isTheCanonicalUnitAsGiven_neverConverted(self) -> None:
        history = _history()
        history.observe("COOLANT_TEMP", 88.0, _at(0), "green", "C")
        history.observe("BATTERY_V", 14.1, _at(0), "green", "V")

        assert history.snapshot()["unit"] == {"COOLANT_TEMP": "C", "BATTERY_V": "V"}

    def test_241Buckets_maxPoints240_keeps240_sinceTsMoves_partial(self) -> None:
        """
        Given: a drive started at t=0, one sample per bucket, 241 buckets closed
        When: maxPoints is 240
        Then: 240 points; sinceTs = the oldest kept bucket's START; partial true
        """
        history = _history()
        history.reset(_DRIVE_ID, _at(0))
        for idx in range(241):
            history.observe("COOLANT_TEMP", 90.0, _at(idx * 30), "green", "C")
        assert history.snapshot()["partial"] is False  # 240 closed: not trimmed yet

        history.observe("COOLANT_TEMP", 90.0, _at(241 * 30), "green", "C")

        snap = history.snapshot()
        assert len(snap["series"]["COOLANT_TEMP"]) == 240
        assert snap["series"]["COOLANT_TEMP"][0]["ts"] == _iso(60)
        assert snap["sinceTs"] == _iso(30)
        assert snap["partial"] is True

    def test_aNewInstance_isEmptyAndPartial(self) -> None:
        """An orchestrator restart mid-drive: no drive start seen."""
        snap = _history().snapshot()

        assert snap == {
            "driveId": None, "sinceTs": None, "partial": True, "intervalSec": 30,
            "series": {"COOLANT_TEMP": [], "INTAKE_TEMP": [], "BATTERY_V": []},
            "unit": {},
        }

    def test_restartMidDrive_sinceTsIsTheFirstFoldedBucketsStart(self) -> None:
        history = _history()
        history.observe("COOLANT_TEMP", 90.0, _at(47), "green", "C")

        snap = history.snapshot()
        assert snap["sinceTs"] == _iso(30)
        assert snap["partial"] is True

    def test_reset_clearsEverySeries_setsTheNewDrive_partialFalse(self) -> None:
        history = _history()
        for t in (0, 30, 60):
            history.observe("COOLANT_TEMP", 90.0, _at(t), "green", "C")
            history.observe("BATTERY_V", 14.0, _at(t), "green", "V")

        history.reset(_DRIVE_ID, _at(75))
        history.observe("COOLANT_TEMP", 91.0, _at(80), "green", "C")
        history.observe("COOLANT_TEMP", 91.0, _at(90), "green", "C")

        snap = history.snapshot()
        assert snap["driveId"] == _DRIVE_ID
        assert snap["sinceTs"] == _iso(75)
        assert snap["partial"] is False
        # The bucket open before the reset does not survive it.
        assert snap["series"] == {
            "COOLANT_TEMP": [{"ts": _iso(90), "value": 91.0, "band": "green"}],
            "INTAKE_TEMP": [],
            "BATTERY_V": [],
        }

    def test_clockSteppedBack_restartsTheHistory_partial(self) -> None:
        history = _history()
        history.reset(_DRIVE_ID, _at(0))
        for t in (0, 30, 60):
            history.observe("COOLANT_TEMP", 90.0, _at(t), "green", "C")

        history.observe("COOLANT_TEMP", 90.0, _at(-600), "green", "C")

        snap = history.snapshot()
        assert snap["series"]["COOLANT_TEMP"] == []
        assert snap["sinceTs"] == _iso(-600)
        assert snap["partial"] is True

    def test_snapshotIfChanged_onlyWhenABucketClosedOrAReset(self) -> None:
        history = _history()
        assert history.snapshotIfChanged() is not None  # first call: the honest empty
        history.observe("COOLANT_TEMP", 90.0, _at(0), "green", "C")
        history.observe("COOLANT_TEMP", 90.0, _at(10), "green", "C")
        assert history.snapshotIfChanged() is None
        history.observe("COOLANT_TEMP", 90.0, _at(30), "green", "C")
        assert history.snapshotIfChanged() is not None
        assert history.snapshotIfChanged() is None
        history.reset(_DRIVE_ID, _at(40))
        assert history.snapshotIfChanged() is not None


# ======================================================= the obd-live tracker


def _tracker(**engineHistory: Any) -> ObdLiveTracker:
    config: dict[str, Any] = {"pi": {"time": {"localZone": _ZONE}}}
    if engineHistory:
        config["pi"]["display"] = {"engineHistory": engineHistory}
    return ObdLiveTracker(config)


class TestTheReadingSeam:
    """The tracker feeds the history with the band producer's band AT the reading."""

    def test_coolantDwell_bucketIsAmberAt101(self) -> None:
        """
        Given: amber dwell 5 s; COOLANT 103.0 at t=0, 105.5 at t=5 and t=10
               (amber after the dwell), 101.0 at t=29
        When: t=30 closes the bucket
        Then: value 101.0, band amber -- the producer's verdict, copied
        """
        tracker = ObdLiveTracker({"pi": {
            "time": {"localZone": _ZONE},
            "bands": {"coolant": {"amberDwellSec": 5}},
        }})
        for value, t in ((103.0, 0), (105.5, 5), (105.5, 10), (101.0, 29), (101.0, 30)):
            tracker.observeReading(_reading("COOLANT_TEMP", value, t))

        history = tracker.engineHistoryIfChanged()
        assert history is not None
        assert history["series"]["COOLANT_TEMP"] == [
            {"ts": _iso(30), "value": 101.0, "band": "amber"},
        ]
        assert history["unit"] == {"COOLANT_TEMP": "C"}

    def test_intakeTemp_bandIsAlwaysNull(self) -> None:
        tracker = _tracker()
        for t in (0, 30):
            tracker.observeReading(_reading("INTAKE_TEMP", 31.0, t))

        history = tracker.engineHistoryIfChanged()
        assert history is not None
        assert history["series"]["INTAKE_TEMP"] == [
            {"ts": _iso(30), "value": 31.0, "band": None},
        ]

    def test_engineHistoryKeys_areReadFromConfig(self) -> None:
        tracker = _tracker(intervalSec=10, maxPoints=2)
        for t in (0, 10, 20, 30):
            tracker.observeReading(_reading("COOLANT_TEMP", 90.0, t))

        history = tracker.engineHistoryIfChanged()
        assert history is not None
        assert history["intervalSec"] == 10
        assert [p["ts"] for p in history["series"]["COOLANT_TEMP"]] == [_iso(20), _iso(30)]


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
        self.seconds = 0.0
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
        self._obdLiveClock = lambda: _at(self.seconds + 1)
        self.statesDir = statesDir

    def read(self, name: str, value: Any, seconds: float) -> None:
        self.seconds = seconds
        self._handleReading(_reading(name, value, seconds))

    def tick(self) -> None:
        self._lastCardStateEmitTime = None
        assert self._maybeEmitCardStates()

    def path(self) -> str:
        return os.path.join(self.statesDir, eh.ENGINE_HISTORY_STATE_FILENAME)

    def state(self) -> dict:
        with open(self.path(), encoding="utf-8") as fh:
            return json.load(fh)


@pytest.fixture
def driveId118(monkeypatch):
    """The detector has published drive 118 on the process context."""
    monkeypatch.setattr("pi.obdii.drive_id.getCurrentDriveId", lambda: _DRIVE_ID)


class TestThroughTheCardTick:
    """Readings at _handleReading reach states/engine-history at the card tick."""

    def test_twoBatteryReadingsInOneTick_redThenGreen_bucketIsRed(self, tmp_path) -> None:
        """
        Given: the engine running; BATTERY_V 11.5 (red) then 14.0 (green) with
               no card tick between them
        When: the bucket closes and the tick writes
        Then: that bucket's band is red -- fed at the reading seam, not the tick
        """
        orch = _Orch(str(tmp_path / "states"))
        for t in (0, 2, 4, 6, 8):
            orch.read("RPM", 900.0, t)
        orch.read("BATTERY_V", 11.5, 5)
        orch.read("BATTERY_V", 14.0, 6)
        orch.tick()
        orch.read("RPM", 900.0, 30)
        orch.read("BATTERY_V", 14.0, 30)
        orch.tick()

        assert orch.state()["series"]["BATTERY_V"] == [
            {"ts": _iso(30), "value": 14.0, "band": "red"},
        ]

    def test_theTickWritesOnlyWhenABucketClosed(self, tmp_path) -> None:
        orch = _Orch(str(tmp_path / "states"))
        orch.tick()  # the first tick replaces any previous process's file
        first = orch.state()
        os.remove(orch.path())

        orch.read("COOLANT_TEMP", 90.0, 0)
        orch.read("COOLANT_TEMP", 90.0, 10)
        orch.tick()
        assert not os.path.exists(orch.path())

        orch.read("COOLANT_TEMP", 90.0, 30)
        orch.tick()
        assert orch.state()["series"]["COOLANT_TEMP"] == [
            {"ts": _iso(30), "value": 90.0, "band": "green"},
        ]
        assert first["series"] == {"COOLANT_TEMP": [], "INTAKE_TEMP": [], "BATTERY_V": []}

    def test_restartMidDrive_noDriveStartSeen_emptyAndPartial(self, tmp_path) -> None:
        """
        Given: a new orchestrator (no drive-start event seen)
        When: the first card tick runs
        Then: series empty, partial true, driveId null
        """
        orch = _Orch(str(tmp_path / "states"))
        orch.tick()

        state = orch.state()
        assert state["series"] == {"COOLANT_TEMP": [], "INTAKE_TEMP": [], "BATTERY_V": []}
        assert state["partial"] is True
        assert state["driveId"] is None

    def test_driveStart_emptiesTheSeries_newDrive_partialFalse(
        self, tmp_path, driveId118
    ) -> None:
        """
        Given: history from before a drive start
        When: _handleDriveStart runs for a drive that started at t=75
        Then: series empty; driveId 118 and sinceTs of the new drive; partial false
        """
        orch = _Orch(str(tmp_path / "states"))
        for t in (0, 30, 60):
            orch.read("COOLANT_TEMP", 90.0, t)
        orch.tick()
        assert orch.state()["series"]["COOLANT_TEMP"] != []

        orch._handleDriveStart(DriveSession(startTime=_T0_LOCAL + timedelta(seconds=75)))
        orch.tick()

        state = orch.state()
        assert state["series"] == {"COOLANT_TEMP": [], "INTAKE_TEMP": [], "BATTERY_V": []}
        assert state["driveId"] == _DRIVE_ID
        assert state["sinceTs"] == _iso(75)
        assert state["partial"] is False

    def test_aFailingHistoryReset_doesNotBlockTheDriveStart(self, tmp_path) -> None:
        orch = _Orch(str(tmp_path / "states"))

        def _boom(_start: Any) -> None:
            raise RuntimeError("boom")

        orch._resetEngineHistory = _boom  # type: ignore[method-assign]
        orch._handleDriveStart(DriveSession(startTime=_T0_LOCAL))

        assert orch._healthCheckStats.drivesDetected == 1


# ================================================================ the fixture

# Readings every 2 s, RPM 900 alongside (the ~2.2 s measured poll spacing,
# validator note on pi.bands.battery.rpmMaxAgeSec). A spacing past the 5 s
# stale window would reset every coolant dwell, and past rpmMaxAgeSec would
# make each RPM a fresh crank, so nothing would ever be banded. Each scenario:
# drive start seen?, seconds, step, the three value curves (a curve returning
# None skips that PID at that t).
_Curve = Callable[[float], float | None]


def _fanCycle(t: float) -> float:
    """92 -> 101 -> 92 C every 120 s: the fan cycling, peaks below amber.

    Shifted 2 s so each peak is its bucket's LAST sample and so its value.
    """
    phase = ((t + 2) % 120) / 60.0
    return round(92.0 + 9.0 * (1.0 - abs(phase - 1.0)), 1)


def _inGap(t: float) -> bool:
    return 60 <= t < 120


_CASES: dict[str, dict[str, Any]] = {
    "cold-start-history": {
        "driveStart": True, "seconds": 600, "step": 2,
        "coolant": lambda t: round(20.0 + t / 10.0, 1),
        "intake": lambda t: round(15.0 + t / 60.0, 1),
        "battery": lambda t: 14.1,
    },
    "fan-cycle-history": {
        "driveStart": True, "seconds": 600, "step": 2,
        "coolant": _fanCycle,
        "intake": lambda t: 30.0,
        "battery": lambda t: 14.2,
    },
    "coolant-dwell-fired": {
        "driveStart": True, "seconds": 360, "step": 2,
        # 110 s at 106 C: amber fires at the 30 s dwell, red's 120 s never does.
        "coolant": lambda t: 106.0 if 60 <= t < 170 else 98.0,
        "intake": lambda t: 35.0,
        "battery": lambda t: 14.0,
    },
    "bucket-worst-band": {
        "driveStart": True, "seconds": 120, "step": 2,
        "coolant": lambda t: 106.0 if t < 80 else 101.0,
        "intake": lambda t: 35.0,
        "battery": lambda t: 14.0,
    },
    "history-gap": {
        "driveStart": True, "seconds": 180, "step": 2,
        "coolant": lambda t: None if _inGap(t) else 90.0,
        "intake": lambda t: None if _inGap(t) else 30.0,
        "battery": lambda t: None if _inGap(t) else 14.1,
    },
    "history-trimmed-2h": {
        "driveStart": True, "seconds": 244 * 30, "step": 30,
        "coolant": lambda t: 90.0,
        "intake": lambda t: None,
        "battery": lambda t: None,
    },
    "history-restart-mid-drive": {
        "driveStart": False, "seconds": 180, "step": 2, "offset": 737,
        "coolant": lambda t: 89.0,
        "intake": lambda t: 28.0,
        "battery": lambda t: 14.1,
    },
    "history-empty-after-restart": {
        "driveStart": False, "seconds": None, "step": 2,
        "coolant": lambda t: None,
        "intake": lambda t: None,
        "battery": lambda t: None,
    },
}


def _buildCase(name: str) -> dict[str, Any]:
    """The case's reading sequence through the real tracker and builder.

    The payload is the one the card tick would have written last: the
    newest ``engineHistoryIfChanged`` after each reading.
    """
    case = _CASES[name]
    tracker = ObdLiveTracker({"pi": {"time": {"localZone": _ZONE}}})
    offset = case.get("offset", 0)
    if case["driveStart"]:
        tracker.resetEngineHistory(_DRIVE_ID, _T0_LOCAL + timedelta(seconds=offset))
    written = tracker.engineHistoryIfChanged()
    lastS = float(offset)
    if case["seconds"] is not None:
        for i in range(case["seconds"] // case["step"] + 1):
            t = i * case["step"]
            lastS = offset + t
            readings = [
                ("RPM", 900.0),
                ("COOLANT_TEMP", case["coolant"](t)),
                ("INTAKE_TEMP", case["intake"](t)),
                ("BATTERY_V", case["battery"](t)),
            ]
            for pid, value in readings:
                if value is None:
                    continue
                tracker.observeReading(_reading(pid, value, lastS))
                changed = tracker.engineHistoryIfChanged()
                if changed is not None:
                    written = changed
    assert written is not None
    return eh.buildEngineHistoryState(written, nowUtc=_at(lastS + 2))


def _loadFixture() -> dict[str, Any]:
    with open(_FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


class TestTheContractFixture:
    """tests/ui/fixtures/states/engine-history.json (R29): builder output, named."""

    def test_fixture_holdsTheNamedCases(self) -> None:
        assert set(_loadFixture()) == set(_CASES)

    @pytest.mark.parametrize("case", sorted(_CASES))
    def test_fixture_everyCaseIsWhatTheProducerEmits(self, case: str) -> None:
        assert _buildCase(case) == _loadFixture()[case]

    def test_fixture_unitsAreCanonical(self) -> None:
        for case in _loadFixture().values():
            assert set(case["unit"].values()) <= {"C", "V"}

    def test_fixture_casesCarryTheirFacts(self) -> None:
        fixture = _loadFixture()

        def bands(case: str) -> set[str | None]:
            return {p["band"] for p in fixture[case]["series"]["COOLANT_TEMP"]}

        assert bands("fan-cycle-history") == {"green"}
        assert max(
            p["value"] for p in fixture["fan-cycle-history"]["series"]["COOLANT_TEMP"]
        ) == 101.0
        assert bands("coolant-dwell-fired") == {"green", "amber"}
        worst = fixture["bucket-worst-band"]["series"]["COOLANT_TEMP"]
        assert {"ts": _iso(90), "value": 101.0, "band": "amber"} in worst
        gapTs = [p["ts"] for p in fixture["history-gap"]["series"]["COOLANT_TEMP"]]
        assert _iso(90) not in gapTs and _iso(120) not in gapTs
        trimmed = fixture["history-trimmed-2h"]
        assert len(trimmed["series"]["COOLANT_TEMP"]) == 240
        assert trimmed["partial"] is True
        assert trimmed["sinceTs"] == _iso(4 * 30)
        restart = fixture["history-restart-mid-drive"]
        assert restart["partial"] is True and restart["driveId"] is None
        assert restart["sinceTs"] == _iso(720)
        empty = fixture["history-empty-after-restart"]
        assert empty["partial"] is True
        assert all(points == [] for points in empty["series"].values())
        for case in ("cold-start-history", "fan-cycle-history", "coolant-dwell-fired"):
            assert fixture[case]["partial"] is False
            assert fixture[case]["driveId"] == _DRIVE_ID
            assert fixture[case]["sinceTs"] == _iso(0)
            assert fixture[case]["series"]["INTAKE_TEMP"]
            assert {p["band"] for p in fixture[case]["series"]["INTAKE_TEMP"]} == {None}
