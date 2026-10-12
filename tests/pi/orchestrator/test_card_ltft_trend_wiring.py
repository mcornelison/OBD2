################################################################################
# File Name: test_card_ltft_trend_wiring.py
# Purpose/Description: US-661 -- THE JOIN. The `ltft-trend` emitter module has
#   existed since US-420 and every one of its unit tests passed, but NOTHING IN
#   src/ EVER CALLED IT, so the Fuel Trim card has never had data. That is the
#   fifth instance of this shape in the project (US-494/495/498/US-630): two
#   correct halves, no wire between them, and a green suite either side.
#
#   A UNIT TEST OF THE BUILDER CANNOT CATCH THIS, WHICH IS WHY THIS FILE EXISTS
#   SEPARATELY. Every assertion here drives the REAL orchestrator mixin against
#   a REAL SQLite database shaped like the Pi's and reads the REAL state file
#   off disk -- never `buildLtftTrendState` directly.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-04    | Ralph (Rex)  | Initial -- US-661 ltft-trend producer wiring.
# ================================================================================
################################################################################

"""US-661: the `ltft-trend` producer is wired into the card emit tick."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.splash.ltft_trend_emitter import (
    COOLANT_PID,
    FUEL_SYSTEM_CLOSED_LOOP,
    FUEL_SYSTEM_PID,
    LTFT_PID,
    LTFT_TREND_FILENAME,
    REASON_WARMING,
)

_T0 = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)


def _iso(offsetSeconds: float) -> str:
    return (_T0 + timedelta(seconds=offsetSeconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _FakeDatabase:
    """An in-memory realtime_data + drive_summary shaped like the Pi's."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE realtime_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                parameter_name TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                profile_id TEXT,
                data_source TEXT NOT NULL DEFAULT 'real',
                drive_id INTEGER
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE drive_summary (
                drive_id INTEGER PRIMARY KEY,
                drive_start_timestamp TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def seedDrive(
        self,
        driveId: int,
        ltftMean: float,
        *,
        samples: int = 25,
        coolant: float = 90.0,
        fuelStatus: float = FUEL_SYSTEM_CLOSED_LOOP,
        dataSource: str = "real",
        cycleBase: int = 0,
    ) -> None:
        """One drive of round-robin poll cycles, each parameter on its OWN stamp."""
        self._conn.execute(
            "INSERT OR REPLACE INTO drive_summary "
            "(drive_id, drive_start_timestamp) VALUES (?, ?)",
            (driveId, _iso(cycleBase * 5)),
        )
        for i in range(samples):
            base = (cycleBase + i) * 5
            for offset, name, value in (
                (0, COOLANT_PID, coolant),
                (1, FUEL_SYSTEM_PID, fuelStatus),
                (2, LTFT_PID, ltftMean),
            ):
                self._conn.execute(
                    "INSERT INTO realtime_data (timestamp, parameter_name, value, "
                    "unit, data_source, drive_id) VALUES (?, ?, ?, '%', ?, ?)",
                    (_iso(base + offset), name, value, dataSource, driveId),
                )
        self._conn.commit()

    @contextmanager
    def connect(self):
        yield self._conn


class _FakeOrch(CardStateEmitterMixin):
    """Minimal composing object exposing the attrs the mixin reads."""

    def __init__(self, config, *, database=None):
        self._config = config
        self._connection = None
        self._driveDetector = None
        self._powerSourceProvider = None
        self._hardwareManager = None
        if database is not None:
            self._database = database
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


def _config(tmp_path, **dashboard):
    dash = {"stateEmitIntervalSeconds": 0.0, "ltftTrendIntervalSeconds": 0.0}
    dash.update(dashboard)
    return {
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": dash,
        }
    }


def _trendPath(tmp_path) -> str:
    return os.path.join(str(tmp_path / "states"), LTFT_TREND_FILENAME)


def _emitAndRead(tmp_path, orch) -> dict | None:
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()
    path = _trendPath(tmp_path)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ===========================================================================


def test_theCardTickWritesTheLtftTrendFile(tmp_path):
    """
    Given: an orchestrator with a database holding six qualifying real drives
    When: the card-state emit tick runs
    Then: `states/ltft-trend` EXISTS and carries a real median.

    THE WHOLE STORY IN ONE ASSERTION. Before US-661 this file was never written
    by anything, at any time, on any machine.
    """
    db = _FakeDatabase()
    for index, driveId in enumerate(range(41, 47)):
        db.seedDrive(driveId, -1.0, cycleBase=index * 100)
    orch = _FakeOrch(_config(tmp_path), database=db)

    payload = _emitAndRead(tmp_path, orch)

    assert payload is not None, "the card tick still writes no ltft-trend file"
    assert payload["sufficient"] is True
    assert payload["median"] == -1.0


def test_theProducerGatesOnCoolant_endToEndThroughTheTick(tmp_path):
    """
    Given: six real drives that never reach 85 C coolant
    When: the tick runs
    Then: the file says WARMING and publishes no number.

    Driven through the REAL SQL rather than a hand-built row list, because the
    gate's whole difficulty is the as-of alignment across separately-timestamped
    rows -- which only the query can get wrong.
    """
    db = _FakeDatabase()
    for index, driveId in enumerate(range(41, 47)):
        db.seedDrive(driveId, 6.5, coolant=45.0, fuelStatus=1.0, cycleBase=index * 100)
    orch = _FakeOrch(_config(tmp_path), database=db)

    payload = _emitAndRead(tmp_path, orch)

    assert payload["reason"] == REASON_WARMING
    assert payload["median"] is None
    assert "6.5" not in json.dumps(payload)


def test_simulatorDrivesNeverReachTheCard(tmp_path):
    """
    Given: six physics_sim drives and nothing real
    When: the tick runs
    Then: no trend is published -- a bench run cannot pollute the tune signal.
    """
    db = _FakeDatabase()
    for index, driveId in enumerate(range(41, 47)):
        db.seedDrive(
            driveId, -9.0, dataSource="physics_sim", cycleBase=index * 100
        )
    orch = _FakeOrch(_config(tmp_path), database=db)

    payload = _emitAndRead(tmp_path, orch)

    assert payload["sufficient"] is False
    assert payload["median"] is None
    assert "-9" not in json.dumps(payload)


def test_noDatabaseWritesNoFileAtAll(tmp_path):
    """
    Given: an orchestrator with NO database handle (bench, or pre-boot order)
    When: the tick runs
    Then: NOTHING is written.

    Deliberate, and it is the US-672 lesson one card over: a file reading "no
    real drives recorded" when we could not even OPEN the log would be a claim
    about the CAR drawn from an absence of evidence about US. An absent state
    file already renders the honest "no data -- trend not computed".
    """
    orch = _FakeOrch(_config(tmp_path))

    assert _emitAndRead(tmp_path, orch) is None


def test_anUnreadableDatabaseNeverCrashesTheRunLoop(tmp_path):
    """
    Given: a database whose connect() raises
    When: the tick runs
    Then: the tick still returns -- the dashboard hook never blocks its owner.
    """
    class _Exploding:
        def connect(self):
            raise sqlite3.OperationalError("database is locked")

    orch = _FakeOrch(_config(tmp_path), database=_Exploding())

    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True


def test_theTrendIsThrottledOffTheTwoSecondCardCadence(tmp_path):
    """
    Given: a long ltft-trend interval and a tick that has already published
    When: the tick runs again immediately
    Then: the producer does NOT re-query.

    The trend cannot change until a drive ENDS, so re-aggregating it on the 2 s
    card cadence would put a multi-drive scan of the Pi's hottest write table
    into the run loop 30 times a minute for an identical answer.

    COUNTED AT THE PRODUCER, NOT AT `database.connect()`. The first draft of this
    test counted connects and read THREE on the opening tick -- the battery-
    health verdict and the last-drive summary each open the same handle every
    tick, so a connect count answers a question about the whole emit block
    rather than about this throttle. Counting invocations of the ltft emitter
    itself is the fact the cadence actually governs.
    """
    db = _FakeDatabase()
    for index, driveId in enumerate(range(41, 47)):
        db.seedDrive(driveId, -1.0, cycleBase=index * 100)
    orch = _FakeOrch(_config(tmp_path, ltftTrendIntervalSeconds=3600.0), database=db)

    orch._initializeCardStateEmitters()
    realEmit = orch._ltftTrendEmitter
    emits = {"n": 0}

    def countingEmit() -> None:
        emits["n"] += 1
        realEmit()

    orch._ltftTrendEmitter = countingEmit

    orch._maybeEmitCardStates()
    assert emits["n"] == 1, "the first tick must publish"

    for _ in range(5):
        orch._maybeEmitCardStates()

    assert emits["n"] == 1, "the trend re-aggregated inside its own interval"


def test_theDatabaseIsResolvedAtUseTime_notCapturedAtConstruction(tmp_path):
    """
    Given: an orchestrator built BEFORE its database exists (the real boot order)
    When: the database is attached and the tick runs
    Then: the trend publishes.

    THE BOOT-ORDER TRAP, hit three times in this file's history (US-501/502/
    504b): the emitters are constructed in _initializeAllComponents while their
    dependencies land later, so a reference captured at construction stays None
    for the life of the process -- a permanently empty tile with a fully green
    unit-test suite, which is indistinguishable from the defect US-661 just
    fixed.
    """
    orch = _FakeOrch(_config(tmp_path))
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True
    assert not os.path.exists(_trendPath(tmp_path))

    db = _FakeDatabase()
    for index, driveId in enumerate(range(41, 47)):
        db.seedDrive(driveId, -1.0, cycleBase=index * 100)
    orch._database = db
    orch._maybeEmitCardStates()

    with open(_trendPath(tmp_path), encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["median"] == -1.0
