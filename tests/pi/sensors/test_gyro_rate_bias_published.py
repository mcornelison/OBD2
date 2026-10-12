################################################################################
# File Name: test_gyro_rate_bias_published.py
# Purpose/Description: US-810 -- PitchFusion's learned gyro RATE bias reaches
#                      edr_imu_derived: the boot schema step is replay-safe on a
#                      POPULATED database (asserted on executed statements), the
#                      rate columns carry gyroBiasRadS after an accepted stop and
#                      are NULL -- never 0.0 -- when none was accepted, and the
#                      rejected-stop count tells the two NULL cases apart.
# Author: Rex (US-810)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-810) | Initial.
# ================================================================================
################################################################################
"""US-810: the gyro RATE bias that corrects the integration is published.

Two quantities share the word "bias" here. ``biasRad`` is the mount-tilt ANGLE
(already in ``bias_rad``); ``gyroBiasRadS`` is the gyro RATE bias in rad/s, the
value these tests follow into the five new ``gyro_bias_*`` columns.
"""

from __future__ import annotations

import math
import re
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from common.edr.sensor_schema import (
    EDR_IMU_DERIVED_GYRO_RATE_BIAS_COLUMNS,
    SCHEMA_EDR_IMU_DERIVED,
    SCHEMA_EDR_IMU_SAMPLE,
    ensureEdrImuDerivedGyroRateBiasColumns,
)
from pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber
from pi.bus.sample import Sample
from pi.obdii.database import ObdDatabase
from pi.sensors.imu_state_bridge import ImuStateBridge
from pi.sensors.pitch_fusion import (
    FUSION_VERSION,
    STANDARD_GRAVITY_MS2,
    ZUPT_MIN_STOP_S,
    PitchFusion,
)

G = STANDARD_GRAVITY_MS2
RATE_COLUMNS = ("gyro_bias_roll_rad_s", "gyro_bias_pitch_rad_s", "gyro_bias_yaw_rad_s")
NEW_COLUMNS = tuple(name for name, _ in EDR_IMU_DERIVED_GYRO_RATE_BIAS_COLUMNS)

#: edr_imu_derived exactly as US-805 shipped it (V0.29.6x, on the car today) --
#: the shape the boot step must upgrade in place.
PRE_US810_DDL = """
CREATE TABLE IF NOT EXISTS edr_imu_derived (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc        TEXT    NOT NULL,
    ts_capture    REAL    NOT NULL,
    seq           INTEGER NOT NULL,
    pitch_deg     REAL,
    stop_count    INTEGER,
    bias_rad      REAL,
    fusion_version INTEGER NOT NULL,
    drive_id      INTEGER,
    data_source   TEXT    NOT NULL DEFAULT 'real'
                  CHECK (data_source IN ('real','replay','physics_sim','fixture')),
    schema_version INTEGER NOT NULL DEFAULT 1
);
"""

SEEDED_ROWS = 40


def _seedPreUs810(conn: sqlite3.Connection) -> None:
    conn.executescript(PRE_US810_DDL)
    conn.executemany(
        "INSERT INTO edr_imu_derived (ts_utc, ts_capture, seq, pitch_deg, stop_count, "
        "bias_rad, fusion_version) VALUES (?, ?, ?, ?, 5, 0.013, 1)",
        [(f"2026-09-23T12:00:{i % 60:02d}Z", float(i), i, -3.9) for i in range(SEEDED_ROWS)],
    )
    conn.commit()


def _columns(conn: sqlite3.Connection) -> list[str]:
    return [row[1] for row in conn.execute("PRAGMA table_info(edr_imu_derived)")]


def _traced(conn: sqlite3.Connection, fn: Any) -> list[str]:
    executed: list[str] = []
    conn.set_trace_callback(executed.append)
    try:
        fn()
    finally:
        conn.set_trace_callback(None)
    return executed


def _schemaChanges(executed: list[str]) -> list[str]:
    return [
        sql for sql in executed
        if re.search(r"\b(ADD\s+COLUMN|DROP\s+TABLE|DROP\s+COLUMN|RENAME\s+TO)\b",
                     sql, re.IGNORECASE)
    ]


# ------------------------------------------------ acceptance 3: replay-safe step


class TestSchemaStepIsReplaySafeOnAPopulatedDatabase:
    """specs/design-patterns.md section 10: run TWICE against the SAME populated DB."""

    def test_firstRunAddsExactlyTheFiveColumns_secondRunIssuesNoSchemaChange(self) -> None:
        """
        Given: a populated edr_imu_derived in the pre-US-810 shape
        When:  the step runs twice, tracing executed statements
        Then:  run 1 issues five ADD COLUMNs and nothing destructive; run 2 issues
               no ADD COLUMN and no DROP; the row count never moves
        """
        conn = sqlite3.connect(":memory:")
        _seedPreUs810(conn)

        first = _traced(conn, lambda: ensureEdrImuDerivedGyroRateBiasColumns(conn))
        firstChanges = _schemaChanges(first)
        assert len(firstChanges) == 5, firstChanges
        assert all(re.search(r"ADD\s+COLUMN", s, re.IGNORECASE) for s in firstChanges)
        assert conn.execute("SELECT COUNT(*) FROM edr_imu_derived").fetchone()[0] == SEEDED_ROWS

        second = _traced(conn, lambda: ensureEdrImuDerivedGyroRateBiasColumns(conn))
        assert _schemaChanges(second) == [], f"second run changed the schema: {second}"
        assert conn.execute("SELECT COUNT(*) FROM edr_imu_derived").fetchone()[0] == SEEDED_ROWS

    def test_theReturnValueNamesWhatThisCallAdded(self) -> None:
        conn = sqlite3.connect(":memory:")
        _seedPreUs810(conn)

        assert ensureEdrImuDerivedGyroRateBiasColumns(conn) == list(NEW_COLUMNS)
        assert ensureEdrImuDerivedGyroRateBiasColumns(conn) == []

    def test_existingRowsReadNULL_neverZero(self) -> None:
        """A row written before the columns existed has no recorded bias -- NULL."""
        conn = sqlite3.connect(":memory:")
        _seedPreUs810(conn)
        ensureEdrImuDerivedGyroRateBiasColumns(conn)

        rows = conn.execute(f"SELECT {', '.join(NEW_COLUMNS)} FROM edr_imu_derived").fetchall()
        assert len(rows) == SEEDED_ROWS
        assert all(value is None for row in rows for value in row)

    def test_upgradedTable_hasTheSameColumnsInTheSameOrderAsAFreshOne(self) -> None:
        """ADD COLUMN appends; the DDL appends too, so the two shapes cannot diverge."""
        upgraded = sqlite3.connect(":memory:")
        _seedPreUs810(upgraded)
        ensureEdrImuDerivedGyroRateBiasColumns(upgraded)

        fresh = sqlite3.connect(":memory:")
        fresh.executescript(SCHEMA_EDR_IMU_DERIVED)

        assert _columns(upgraded) == _columns(fresh)

    def test_freshTable_isANoOp(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_EDR_IMU_DERIVED)

        executed = _traced(conn, lambda: ensureEdrImuDerivedGyroRateBiasColumns(conn))

        assert _schemaChanges(executed) == []

    def test_aMissingTable_failsLoud_ratherThanReportingNothingToDo(self) -> None:
        conn = sqlite3.connect(":memory:")

        with pytest.raises(sqlite3.OperationalError, match="edr_imu_derived"):
            ensureEdrImuDerivedGyroRateBiasColumns(conn)


class TestTheBootPathRunsTheStep:
    """The step is CALLED at boot -- the V0.29.66 shape was a step nothing ran."""

    def _tracedInitialize(
        self, db: ObdDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> list[str]:
        executed: list[str] = []
        original = db._getConnection  # noqa: SLF001 -- wrap the real connection

        def traced() -> sqlite3.Connection:
            conn = original()
            conn.set_trace_callback(executed.append)
            return conn

        monkeypatch.setattr(db, "_getConnection", traced)
        db.initialize()
        monkeypatch.undo()
        return executed

    def test_initializeTwice_onAPopulatedPreUs810Database(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: an on-disk Pi database whose edr_imu_derived is populated, pre-US-810
        When:  ObdDatabase.initialize() runs, then runs again (two boots)
        Then:  boot 1 adds the five columns; boot 2 issues no gyro_bias ADD COLUMN
               and no DROP on edr_imu_derived; rows are unchanged
        """
        path = str(tmp_path / "obd.db")
        seed = sqlite3.connect(path)
        _seedPreUs810(seed)
        seed.close()
        db = ObdDatabase(path, walMode=False)

        first = self._tracedInitialize(db, monkeypatch)
        added = [s for s in first if "gyro_bias" in s and re.search(r"ADD\s+COLUMN", s, re.I)]
        assert len(added) == 5, added

        second = self._tracedInitialize(db, monkeypatch)
        touched = [
            s for s in second
            if "edr_imu_derived" in s
            and re.search(r"\b(ADD\s+COLUMN|DROP|RENAME\s+TO)\b", s, re.IGNORECASE)
        ]
        assert touched == [], f"second boot changed edr_imu_derived: {touched}"

        check = sqlite3.connect(path)
        try:
            assert set(NEW_COLUMNS) <= set(_columns(check))
            count = check.execute("SELECT COUNT(*) FROM edr_imu_derived").fetchone()[0]
            assert count == SEEDED_ROWS
        finally:
            check.close()


# ------------------------------------------- validation 2 + 3: what the row says


class _Db:
    """The ObdDatabase handle surface the EDR subscriber writes through."""

    def __init__(self, path: str) -> None:
        self.dbPath = path
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA_EDR_IMU_SAMPLE)
        # The car's path: the pre-US-810 table, upgraded by the boot step.
        _seedPreUs810(self._conn)
        ensureEdrImuDerivedGyroRateBiasColumns(self._conn)
        self._conn.execute("DELETE FROM edr_imu_derived")
        self._conn.commit()

    def connect(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()


@pytest.fixture()
def db(tmp_path: Any) -> Any:
    handle = _Db(str(tmp_path / "obd.db"))
    yield handle
    handle.close()


def _feed(fusion: PitchFusion, gyro: tuple[float, float, float], *, seconds: float,
          speed: float, startAt: float = 0.0, hz: float = 50.0) -> float:
    step = 1.0 / hz
    capture = startAt
    nextSpeedAt = startAt
    for i in range(int(round(seconds * hz))):
        capture = startAt + i * step
        if capture >= nextSpeedAt:
            fusion.observeSpeed(speed, capture)
            nextSpeedAt = capture + 1.0
        fusion.update((0.0, 0.0, G), gyro, capture)
    return capture + step


def _oneStopThenDrive(fusion: PitchFusion, gyro: tuple[float, float, float]) -> float:
    stopS = ZUPT_MIN_STOP_S + 8.0
    t = _feed(fusion, gyro, seconds=stopS, speed=0.0)
    fusion.observeSpeed(20.0, t)
    return _feed(fusion, gyro, seconds=1.0, speed=20.0, startAt=t)


def _persistedRow(db: _Db, tmp_path: Any, fusion: PitchFusion, capture: float) -> dict[str, Any]:
    """Bridge snapshot of ``fusion`` -> EDR writer -> the stored derived row."""
    bridge = ImuStateBridge(None, str(tmp_path))
    bridge._pitchFusion = fusion  # noqa: SLF001 -- the estimator under test
    bridge._recordDerived(  # noqa: SLF001 -- the snapshot the writer persists
        SimpleNamespace(tsUtc="2026-09-24T12:00:00Z", seq=9), capture,
    )
    sub = EdrPersistenceSubscriber(
        None, db, imuSampleHz=4, imuPersistHz=4, derivedSnapshotFn=bridge.derivedSnapshot,
    )
    for field, value in (("accel", (0.0, 0.0, G)), ("gyro", (0.0, 0.0, 0.0)),
                         ("mag", (1.0, 2.0, 3.0)), ("temp", None)):
        sub.handleSample(Sample(
            topic=f"raw.imu.{field}", source="imu", value=value, unit=None,
            tsUtc="2026-09-24T12:00:00Z", tsCapture=capture, driveId=None,
            dataSource="real", seq=0,
        ))
    cur = db.connect().execute("SELECT * FROM edr_imu_derived")
    rows = cur.fetchall()
    assert len(rows) == 1, "the derived row was not written"
    return dict(zip([d[0] for d in cur.description], rows[0], strict=True))


class TestTheRowCarriesTheRateBias:
    """Validation 2 -- after an accepted stop, the row IS gyroBiasRadS."""

    def test_acceptedStop_rateColumnsEqualGyroBiasRadS_andStopsMatch(
        self, db: _Db, tmp_path: Any
    ) -> None:
        bias = (0.004, -0.003, 0.002)
        fusion = PitchFusion()
        capture = _oneStopThenDrive(fusion, bias)
        learned = fusion.gyroBiasRadS
        assert learned is not None and fusion.gyroBiasStopCount == 1

        row = _persistedRow(db, tmp_path, fusion, capture)

        for column, want in zip(RATE_COLUMNS, learned, strict=True):
            assert math.isclose(row[column], want, abs_tol=1e-12), (column, row[column], want)
        assert row["gyro_bias_stops"] == fusion.gyroBiasStopCount == 1
        assert row["gyro_bias_rejected_stops"] == 0

    def test_theRateBiasIsNotTheTiltBias(self, db: _Db, tmp_path: Any) -> None:
        """bias_rad (ANGLE, 0.0 below minStops) and the RATE columns stay separate."""
        fusion = PitchFusion()
        capture = _oneStopThenDrive(fusion, (0.004, -0.003, 0.002))

        row = _persistedRow(db, tmp_path, fusion, capture)

        assert row["bias_rad"] == fusion.biasRad == 0.0
        assert row["gyro_bias_pitch_rad_s"] is not None
        assert row["gyro_bias_pitch_rad_s"] != row["bias_rad"]


class TestAnUnlearnedBiasIsNULL:
    """Validation 3 -- no accepted stop: NULL rates, and WHY is on the row."""

    def test_noStopAtAll_ratesNULL_rejectedZero(self, db: _Db, tmp_path: Any) -> None:
        fusion = PitchFusion()
        capture = _feed(fusion, (0.004, -0.003, 0.002), seconds=5.0, speed=20.0)
        assert fusion.gyroBiasRadS is None

        row = _persistedRow(db, tmp_path, fusion, capture)

        assert [row[c] for c in RATE_COLUMNS] == [None, None, None]
        assert all(row[c] != 0.0 for c in RATE_COLUMNS)
        assert row["gyro_bias_stops"] == 0
        assert row["gyro_bias_rejected_stops"] == 0

    def test_everyStopRejectedAsALatch_ratesNULL_rejectedCounted(
        self, db: _Db, tmp_path: Any
    ) -> None:
        """Same NULL rates as 'never learned' -- the rejected count tells them apart."""
        latch = (0.0, -math.radians(20.0), 0.0)
        fusion = PitchFusion()
        capture = _oneStopThenDrive(fusion, latch)
        assert fusion.gyroBiasRadS is None and fusion.gyroBiasRejectedStops == 1

        row = _persistedRow(db, tmp_path, fusion, capture)

        assert [row[c] for c in RATE_COLUMNS] == [None, None, None]
        assert row["gyro_bias_stops"] == 0
        assert row["gyro_bias_rejected_stops"] == 1


class TestPublishOnly:
    """Acceptance 5 -- publishing a computed value does not change the algorithm."""

    def test_fusionVersionIsUnchanged(self, db: _Db, tmp_path: Any) -> None:
        fusion = PitchFusion()
        capture = _oneStopThenDrive(fusion, (0.004, -0.003, 0.002))

        row = _persistedRow(db, tmp_path, fusion, capture)

        assert FUSION_VERSION == 1
        assert row["fusion_version"] == 1
