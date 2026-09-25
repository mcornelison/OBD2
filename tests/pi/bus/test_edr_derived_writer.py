################################################################################
# File Name: test_edr_derived_writer.py
# Purpose/Description: US-805 / ARCH-045 -- the edr_imu_derived writer. The
#                      PitchFusion snapshot is persisted ATOMICALLY beside its
#                      raw sibling, from the same sample, through the same log
#                      gate, carrying the FUSION's own ts_capture.
# Author: Atlas (ARCH-045, under the CIO build override -- board/wip/ARCH-045.md)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-805: the derived-row writer on the EDR persistence subscriber."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from src.common.edr.sensor_schema import EDR_INDEXES, EDR_SCHEMAS
from src.pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber
from src.pi.bus.sample import Sample

_IMU_FIELDS = ("accel", "gyro", "mag", "temp")


class _Db:
    """Minimal stand-in for the ObdDatabase handle the subscriber writes through."""

    def __init__(self, path: str) -> None:
        self.dbPath = path
        self._conn = sqlite3.connect(path)
        for _name, ddl in EDR_SCHEMAS:
            self._conn.executescript(ddl)
        for _name, ddl in EDR_INDEXES:
            self._conn.executescript(ddl)
        # purgeExpired reads the per-table sync high-water mark and deletes
        # NOTHING if it cannot (US-768). A fixture without it silently makes
        # every retention test vacuous.
        self._conn.executescript(
            "CREATE TABLE IF NOT EXISTS sync_log ("
            "  table_name TEXT PRIMARY KEY,"
            "  last_synced_id INTEGER NOT NULL DEFAULT 0,"
            "  last_synced_at TEXT, last_batch_id TEXT,"
            "  status TEXT NOT NULL DEFAULT 'ok');"
        )
        for table in ("edr_imu_sample", "edr_light_sample", "edr_imu_derived"):
            self._conn.execute(
                "INSERT OR REPLACE INTO sync_log (table_name, last_synced_id) "
                "VALUES (?, 1000000)", (table,),
            )
        self._conn.commit()

    def connect(self) -> Any:
        return self._conn

    def close(self) -> None:
        self._conn.close()


@pytest.fixture()
def db(tmp_path: Any) -> Any:
    handle = _Db(str(tmp_path / "obd.db"))
    yield handle
    handle.close()


def _burst(seq: int, tsCapture: float, tsUtc: str = "2026-09-22T12:00:00Z") -> list[Sample]:
    """One complete IMU burst: all four fields sharing a seq."""
    values = {
        "accel": (0.0, 0.0, 9.81),
        "gyro": (0.0, 0.0, 0.0),
        "mag": (1.0, 2.0, 3.0),
        "temp": None,
    }
    return [
        Sample(
            topic=f"raw.imu.{field}",
            source="imu",
            value=values[field],
            unit=None,
            tsUtc=tsUtc,
            tsCapture=tsCapture,
            driveId=None,
            dataSource="real",
            seq=seq,
        )
        for field in _IMU_FIELDS
    ]


def _snapshot(
    tsUtc: str = "2026-09-22T12:00:00Z",
    tsCapture: float = 100.0,
    seq: int = 0,
    pitchDeg: float | None = 3.74,
    stopCount: int = 5,
    biasRad: float = 0.0131,
    fusionVersion: int = 1,
    gyroBiasRadS: tuple[float, float, float] | None = None,
    gyroBiasStops: int = 0,
    gyroBiasRejectedStops: int = 0,
) -> dict[str, Any]:
    roll, pitch, yaw = gyroBiasRadS if gyroBiasRadS is not None else (None, None, None)
    return {
        "tsUtc": tsUtc,
        "tsCapture": tsCapture,
        "seq": seq,
        "pitchDeg": pitchDeg,
        "stopCount": stopCount,
        "biasRad": biasRad,
        "fusionVersion": fusionVersion,
        "gyroBiasRollRadS": roll,
        "gyroBiasPitchRadS": pitch,
        "gyroBiasYawRadS": yaw,
        "gyroBiasStops": gyroBiasStops,
        "gyroBiasRejectedStops": gyroBiasRejectedStops,
    }


def _rows(db: _Db, table: str) -> list[Any]:
    cur = db.connect().execute(f"SELECT * FROM {table} ORDER BY id")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


class TestDerivedRowWriter:
    """US-805: the derived row rides with its raw sibling, or not at all."""

    def _feed(self, sub: EdrPersistenceSubscriber, seq: int, tsCapture: float) -> None:
        for sample in _burst(seq, tsCapture):
            sub.handleSample(sample)

    def test_derivedRowIsWritten_besideTheRawRow(self, db: _Db) -> None:
        sub = EdrPersistenceSubscriber(
            None, db, imuSampleHz=4, imuPersistHz=4,
            derivedSnapshotFn=lambda: _snapshot(),
        )
        self._feed(sub, seq=0, tsCapture=100.0)
        assert len(_rows(db, "edr_imu_sample")) == 1
        assert len(_rows(db, "edr_imu_derived")) == 1

    def test_derivedRow_carriesTheFUSIONS_tsCapture_notTheRawSamples(self, db: _Db) -> None:
        """The stamp names the sample the value was COMPUTED FROM (A-double-prime).

        If the fusion has not yet seen the sample the raw row is being written
        from, stamping the derived row with the RAW sample's ts_capture would be
        a lie -- it would claim a belief the estimator did not hold yet.
        """
        sub = EdrPersistenceSubscriber(
            None, db, imuSampleHz=4, imuPersistHz=4,
            derivedSnapshotFn=lambda: _snapshot(tsCapture=99.5, seq=-1),
        )
        self._feed(sub, seq=0, tsCapture=100.0)
        raw = _rows(db, "edr_imu_sample")[0]
        derived = _rows(db, "edr_imu_derived")[0]
        assert raw["ts_capture"] == 100.0
        assert derived["ts_capture"] == 99.5
        assert derived["seq"] == -1

    def test_nullPitch_isPreservedAsNull_neverCoercedToZero(self, db: _Db) -> None:
        """pitchRad is None under gyro_implausible -- that null is the FINDING."""
        sub = EdrPersistenceSubscriber(
            None, db, imuSampleHz=4, imuPersistHz=4,
            derivedSnapshotFn=lambda: _snapshot(pitchDeg=None),
        )
        self._feed(sub, seq=0, tsCapture=100.0)
        assert _rows(db, "edr_imu_derived")[0]["pitch_deg"] is None

    def test_noSnapshotYet_writesTheRawRowAndNoDerivedRow(self, db: _Db) -> None:
        """Before the fusion has an estimate there is no belief to record.

        The raw reading must still land: a missing derived value may never cost
        us the measurement.
        """
        sub = EdrPersistenceSubscriber(
            None, db, imuSampleHz=4, imuPersistHz=4,
            derivedSnapshotFn=lambda: None,
        )
        self._feed(sub, seq=0, tsCapture=100.0)
        assert len(_rows(db, "edr_imu_sample")) == 1
        assert _rows(db, "edr_imu_derived") == []

    def test_noSnapshotFnWired_behavesExactlyAsBefore(self, db: _Db) -> None:
        """The parameter is optional -- an unwired deployment is unchanged."""
        sub = EdrPersistenceSubscriber(None, db, imuSampleHz=4, imuPersistHz=4)
        self._feed(sub, seq=0, tsCapture=100.0)
        assert len(_rows(db, "edr_imu_sample")) == 1
        assert _rows(db, "edr_imu_derived") == []

    def test_aFailingSnapshotFn_neverCostsTheRawRow(self, db: _Db) -> None:
        """A derived-value failure must not lose the measurement it accompanies."""
        def boom() -> dict[str, Any]:
            raise RuntimeError("fusion exploded")

        sub = EdrPersistenceSubscriber(
            None, db, imuSampleHz=4, imuPersistHz=4, derivedSnapshotFn=boom,
        )
        self._feed(sub, seq=0, tsCapture=100.0)
        assert len(_rows(db, "edr_imu_sample")) == 1
        assert _rows(db, "edr_imu_derived") == []

    def test_derivedRow_sharesTheRawRowsDriveIdAndDataSource(self, db: _Db) -> None:
        sub = EdrPersistenceSubscriber(
            None, db, imuSampleHz=4, imuPersistHz=4,
            derivedSnapshotFn=lambda: _snapshot(),
        )
        self._feed(sub, seq=0, tsCapture=100.0)
        raw = _rows(db, "edr_imu_sample")[0]
        derived = _rows(db, "edr_imu_derived")[0]
        assert derived["drive_id"] == raw["drive_id"]
        assert derived["data_source"] == raw["data_source"]

    def test_decimationIsSHARED_derivedFollowsTheRawKeepSet(self, db: _Db) -> None:
        """Both rows come from the SAME decimation decision, so they cannot diverge.

        Decimation is `seq % N`, a function of the SAMPLE -- not of arrival
        order -- so a dropped burst costs BOTH rows or neither. That is what
        makes the raw<->derived join structural rather than probabilistic.
        """
        sub = EdrPersistenceSubscriber(
            None, db, imuSampleHz=4, imuPersistHz=2,   # keep 1 of 2
            derivedSnapshotFn=lambda: _snapshot(),
        )
        for seq in range(4):
            self._feed(sub, seq=seq, tsCapture=100.0 + seq)
        rawSeqs = [r["seq"] for r in _rows(db, "edr_imu_sample")]
        assert rawSeqs == [0, 2]
        assert len(_rows(db, "edr_imu_derived")) == len(rawSeqs)


class TestRetentionPairing:
    """US-805: the purge may never leave a belief whose raw evidence is gone."""

    def _sub(self, db: _Db, **kw: Any) -> EdrPersistenceSubscriber:
        return EdrPersistenceSubscriber(
            None, db, imuSampleHz=4, imuPersistHz=4,
            derivedSnapshotFn=lambda: _snapshot(tsCapture=100.0, seq=0),
            **kw,
        )

    def test_purge_deletesTheDerivedRowWithItsRawSibling(self, db: _Db) -> None:
        """Both tables are purged under ONE cutoff and ONE high-water gate."""
        conn = db.connect()
        conn.execute(
            "INSERT INTO edr_imu_sample (ts_utc, ts_capture, seq, data_source, "
            "schema_version) VALUES ('2020-01-01T00:00:00Z', 1.0, 0, 'real', 1)"
        )
        conn.execute(
            "INSERT INTO edr_imu_derived (ts_utc, ts_capture, seq, fusion_version, "
            "data_source, schema_version) "
            "VALUES ('2020-01-01T00:00:00Z', 1.0, 0, 1, 'real', 1)"
        )
        conn.commit()
        sub = self._sub(db)
        sub.purgeExpired()
        assert _rows(db, "edr_imu_sample") == []
        assert _rows(db, "edr_imu_derived") == [], (
            "ORPHANED BELIEF: the derived row outlived the raw evidence it was "
            "computed from -- the exact un-re-derivable value the separate table "
            "exists to prevent."
        )

    def test_noOrphanSurvivesAPurge_theInvariantStated(self, db: _Db) -> None:
        """The property, not the mechanism: no derived row without a raw sibling."""
        conn = db.connect()
        for seq, ts in ((0, "2020-01-01T00:00:00Z"), (1, "2099-01-01T00:00:00Z")):
            conn.execute(
                "INSERT INTO edr_imu_sample (ts_utc, ts_capture, seq, data_source, "
                "schema_version) VALUES (?, ?, ?, 'real', 1)", (ts, float(seq), seq),
            )
            conn.execute(
                "INSERT INTO edr_imu_derived (ts_utc, ts_capture, seq, fusion_version, "
                "data_source, schema_version) VALUES (?, ?, ?, 1, 'real', 1)",
                (ts, float(seq), seq),
            )
        conn.commit()
        self._sub(db).purgeExpired()
        rawCaptures = {r["ts_capture"] for r in _rows(db, "edr_imu_sample")}
        derivedCaptures = {r["ts_capture"] for r in _rows(db, "edr_imu_derived")}
        assert derivedCaptures - rawCaptures == set(), "orphaned derived rows"
