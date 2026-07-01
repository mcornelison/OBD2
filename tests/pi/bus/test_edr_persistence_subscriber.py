################################################################################
# File Name: test_edr_persistence_subscriber.py
# Purpose/Description: Unit tests for the EDR sibling persistence subscriber
#     (US-410, F-114). Drains raw.imu.*/raw.light.* off the F-110 SampleBus and
#     writes edr_imu_sample / edr_light_sample -- one IMU row per seq (burst
#     assembly), decimated persist cadence, drive_id NULL-latch (never inherit a
#     stale _currentDriveId), rolling-window retention purge, and additive
#     isolation from raw.obd.* (the golden master is a separate write path).
# Author: Rex (US-410)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Unit tests for EdrPersistenceSubscriber (burst assembly, latch, retention)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from common.edr.sensor_schema import SCHEMA_VERSION
from common.time.helper import utcIsoNow
from pi.bus.bus import SampleBus
from pi.bus.edr_persistence_subscriber import (
    EdrPersistenceSubscriber,
    createEdrPersistenceSubscriberFromConfig,
)
from pi.bus.sample import QoS, Sample
from pi.obdii.database import ObdDatabase


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """An initialized, empty ObdDatabase (creates the EDR tables at startup)."""
    db = ObdDatabase(str(tmp_path / "test_edr_persist.db"), walMode=False)
    db.initialize()
    return db


def _imu(field: str, value, seq: int, *, ts: str = "2026-06-30T00:00:00Z",
         dataSource: str = "real") -> Sample:
    """Build one raw.imu.<field> sample (field in accel/gyro/mag/temp)."""
    return Sample(
        topic=f"raw.imu.{field}",
        source="imu",
        value=value,
        unit="x",
        tsUtc=ts,
        tsCapture=float(seq),
        driveId=None,  # subscriber ignores this; it applies the RUNNING latch
        dataSource=dataSource,
        seq=seq,
    )


def _light(field: str, value, seq: int, *, ts: str = "2026-06-30T00:00:00Z") -> Sample:
    """Build one raw.light.<field> sample (field in lux/raw)."""
    return Sample(
        topic=f"raw.light.{field}",
        source="light",
        value=value,
        unit="x",
        tsUtc=ts,
        tsCapture=float(seq),
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _feedImuBurst(sub: EdrPersistenceSubscriber, seq: int, *,
                  accel=(1.0, 2.0, 3.0), gyro=(4.0, 5.0, 6.0),
                  mag=(7.0, 8.0, 9.0), temp=25.0, ts="2026-06-30T00:00:00Z") -> None:
    """Feed a full IMU burst (accel+gyro+mag+temp) under one shared seq."""
    sub.handleSample(_imu("accel", accel, seq, ts=ts))
    sub.handleSample(_imu("gyro", gyro, seq, ts=ts))
    sub.handleSample(_imu("mag", mag, seq, ts=ts))
    sub.handleSample(_imu("temp", temp, seq, ts=ts))


def _imuRows(db: ObdDatabase) -> list:
    with db.connect() as conn:
        conn.row_factory = None
        return conn.execute(
            "SELECT ts_utc, ts_capture, seq, accel_x, accel_y, accel_z, "
            "gyro_x, gyro_y, gyro_z, mag_x, mag_y, mag_z, temp_c, drive_id, "
            "data_source, schema_version FROM edr_imu_sample ORDER BY seq"
        ).fetchall()


def _lightRows(db: ObdDatabase) -> list:
    with db.connect() as conn:
        return conn.execute(
            "SELECT ts_utc, seq, lux, visible, infrared, full_spectrum, "
            "drive_id, data_source, schema_version "
            "FROM edr_light_sample ORDER BY seq"
        ).fetchall()


def _noDecimation(db: ObdDatabase, **kw) -> EdrPersistenceSubscriber:
    """A subscriber that persists every IMU burst (persistHz == sampleHz)."""
    return EdrPersistenceSubscriber(
        None, db, imuSampleHz=50, imuPersistHz=50, **kw
    )


# ---------------------------------------------------------------------------
# Burst assembly: one edr_imu_sample row per seq
# ---------------------------------------------------------------------------

class TestImuBurstAssembly:
    def test_fullBurstWritesExactlyOneRow(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(freshDb)
        _feedImuBurst(sub, seq=1)
        rows = _imuRows(freshDb)
        assert len(rows) == 1
        assert rows[0][2] == 1  # seq

    def test_burstValuesAndVectorsMapped(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(freshDb)
        _feedImuBurst(
            sub, seq=1,
            accel=(1.0, 2.0, 3.0), gyro=(4.0, 5.0, 6.0),
            mag=(7.0, 8.0, 9.0), temp=25.5,
        )
        (row,) = _imuRows(freshDb)
        # accel_x/y/z, gyro_x/y/z, mag_x/y/z, temp_c
        assert row[3:6] == (1.0, 2.0, 3.0)
        assert row[6:9] == (4.0, 5.0, 6.0)
        assert row[9:12] == (7.0, 8.0, 9.0)
        assert row[12] == 25.5

    def test_twoSeqsWriteTwoRows(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(freshDb)
        _feedImuBurst(sub, seq=1)
        _feedImuBurst(sub, seq=2)
        rows = _imuRows(freshDb)
        assert [r[2] for r in rows] == [1, 2]

    def test_partialBurstFlushedOnSeqBoundary(self, freshDb: ObdDatabase) -> None:
        """A dropped field still writes a row (NULLs) when the next seq opens."""
        sub = _noDecimation(freshDb)
        sub.handleSample(_imu("accel", (1.0, 2.0, 3.0), 1))
        sub.handleSample(_imu("gyro", (4.0, 5.0, 6.0), 1))
        # mag + temp dropped for seq 1; seq 2 opening flushes the partial seq 1
        sub.handleSample(_imu("accel", (9.0, 9.0, 9.0), 2))
        rows = _imuRows(freshDb)
        assert rows[0][2] == 1
        assert rows[0][3:6] == (1.0, 2.0, 3.0)   # accel present
        assert rows[0][9:12] == (None, None, None)  # mag NULL
        assert rows[0][12] is None                  # temp NULL

    def test_schemaVersionStampedExplicitly(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(freshDb)
        _feedImuBurst(sub, seq=1)
        (row,) = _imuRows(freshDb)
        assert row[15] == SCHEMA_VERSION

    def test_dataSourceStampedFromSample(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(freshDb)
        for f, v in (("accel", (1.0, 2.0, 3.0)), ("gyro", (0.0, 0.0, 0.0)),
                     ("mag", (0.0, 0.0, 0.0)), ("temp", 1.0)):
            sub.handleSample(_imu(f, v, 1, dataSource="fixture"))
        (row,) = _imuRows(freshDb)
        assert row[14] == "fixture"


# ---------------------------------------------------------------------------
# Decimation: persist a decimated baseline (persistHz < sampleHz)
# ---------------------------------------------------------------------------

class TestDecimation:
    def test_keepsEveryNthBurst(self, freshDb: ObdDatabase) -> None:
        # 50 Hz bus -> 25 Hz persist == keep every 2nd burst.
        sub = EdrPersistenceSubscriber(None, freshDb, imuSampleHz=50, imuPersistHz=25)
        for seq in (1, 2, 3, 4):
            _feedImuBurst(sub, seq=seq)
        rows = _imuRows(freshDb)
        assert [r[2] for r in rows] == [2, 4]

    def test_persistHzAtOrAboveSampleHzKeepsAll(self, freshDb: ObdDatabase) -> None:
        sub = EdrPersistenceSubscriber(None, freshDb, imuSampleHz=50, imuPersistHz=100)
        for seq in (1, 2, 3):
            _feedImuBurst(sub, seq=seq)
        assert [r[2] for r in _imuRows(freshDb)] == [1, 2, 3]


# ---------------------------------------------------------------------------
# drive_id NULL-latch (ADR 2.4) -- never inherit a stale _currentDriveId
# ---------------------------------------------------------------------------

class TestDriveIdLatch:
    def test_nullWhenNoRunningDrive_evenIfContextHasStaleId(
        self, freshDb: ObdDatabase
    ) -> None:
        # getCurrentDriveId would return 7, but no drive is RUNNING -> NULL.
        sub = _noDecimation(
            freshDb, driveIdFn=lambda: 7, isDrivingFn=lambda: False
        )
        _feedImuBurst(sub, seq=1)
        (row,) = _imuRows(freshDb)
        assert row[13] is None

    def test_stampedWhenDriveRunning(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(
            freshDb, driveIdFn=lambda: 7, isDrivingFn=lambda: True
        )
        _feedImuBurst(sub, seq=1)
        (row,) = _imuRows(freshDb)
        assert row[13] == 7

    def test_defaultIsNull(self, freshDb: ObdDatabase) -> None:
        # No latch injected -> safe default is NULL (never fabricate attribution).
        sub = _noDecimation(freshDb)
        _feedImuBurst(sub, seq=1)
        (row,) = _imuRows(freshDb)
        assert row[13] is None


# ---------------------------------------------------------------------------
# Light: lux + raw counts, saturation -> NULL lux
# ---------------------------------------------------------------------------

class TestLightPersistence:
    def test_writesLuxAndRawCounts(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(freshDb)
        sub.handleSample(_light("lux", 123.4, 1))
        sub.handleSample(_light("raw", (10, 20, 30), 1))
        (row,) = _lightRows(freshDb)
        assert row[1] == 1            # seq
        assert row[2] == 123.4        # lux
        assert row[3:6] == (10, 20, 30)  # visible, infrared, full_spectrum

    def test_saturationPersistsNullLuxWithRawCounts(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(freshDb)
        sub.handleSample(_light("lux", None, 1))  # saturated
        sub.handleSample(_light("raw", (65535, 65535, 65535), 1))
        (row,) = _lightRows(freshDb)
        assert row[2] is None                        # lux NULL, never inf
        assert row[3:6] == (65535, 65535, 65535)     # raw counts still recorded

    def test_lightNotDecimated(self, freshDb: ObdDatabase) -> None:
        sub = EdrPersistenceSubscriber(None, freshDb, imuSampleHz=50, imuPersistHz=25)
        for seq in (1, 2, 3):
            sub.handleSample(_light("lux", float(seq), seq))
            sub.handleSample(_light("raw", (seq, seq, seq), seq))
        assert [r[1] for r in _lightRows(freshDb)] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Additive isolation: never touch raw.obd.* (golden master is a separate path)
# ---------------------------------------------------------------------------

class TestAdditiveIsolation:
    def test_ignoresRawObdSamples(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(freshDb)
        handled = sub.handleSample(
            Sample("raw.obd.RPM", "obd", 3500.0, "rpm",
                   "2026-06-30T00:00:00Z", 1.0, 27, "real", 1)
        )
        assert handled is False
        assert _imuRows(freshDb) == []
        assert _lightRows(freshDb) == []


# ---------------------------------------------------------------------------
# Rolling-window retention purge (ADR 2.6)
# ---------------------------------------------------------------------------

class TestRetentionPurge:
    def _insertRow(self, db: ObdDatabase, table: str, ts: str) -> None:
        with db.connect() as conn:
            conn.execute(
                f"INSERT INTO {table} (ts_utc, ts_capture, seq) VALUES (?, 0.0, 1)",
                (ts,),
            )

    def test_purgeDeletesRowsOlderThanRetentionFromBothTables(
        self, freshDb: ObdDatabase
    ) -> None:
        old = "2020-01-01T00:00:00Z"
        fresh = utcIsoNow()
        for table in ("edr_imu_sample", "edr_light_sample"):
            self._insertRow(freshDb, table, old)
            self._insertRow(freshDb, table, fresh)

        sub = EdrPersistenceSubscriber(None, freshDb, retentionDays=7)
        imuDeleted, lightDeleted = sub.purgeExpired()

        assert imuDeleted == 1
        assert lightDeleted == 1
        with freshDb.connect() as conn:
            imuLeft = conn.execute("SELECT ts_utc FROM edr_imu_sample").fetchall()
            lightLeft = conn.execute("SELECT ts_utc FROM edr_light_sample").fetchall()
        assert [r[0] for r in imuLeft] == [fresh]
        assert [r[0] for r in lightLeft] == [fresh]

    def test_purgeRespectsInjectedClock(self, freshDb: ObdDatabase) -> None:
        # A row timestamped "now" is purged once the clock advances past the window.
        ts = utcIsoNow()
        self._insertRow(freshDb, "edr_imu_sample", ts)
        future = datetime.now(UTC) + timedelta(days=10)
        sub = EdrPersistenceSubscriber(
            None, freshDb, retentionDays=7, nowUtcFn=lambda: future
        )
        imuDeleted, _ = sub.purgeExpired()
        assert imuDeleted == 1

    def test_maybePurgeGatedByInterval(self, freshDb: ObdDatabase) -> None:
        clock = {"t": 0.0}
        old = "2020-01-01T00:00:00Z"
        self._insertRow(freshDb, "edr_imu_sample", old)
        sub = EdrPersistenceSubscriber(
            None, freshDb, retentionDays=7,
            monotonicFn=lambda: clock["t"], retentionCheckIntervalS=1000.0,
        )
        # Not yet due (constructed at t=0, interval 1000).
        assert sub.maybePurge() is False
        with freshDb.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM edr_imu_sample").fetchone()[0] == 1
        # Advance past the interval -> purge runs.
        clock["t"] = 1001.0
        assert sub.maybePurge() is True
        with freshDb.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM edr_imu_sample").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# End-to-end over a real bus + drain thread
# ---------------------------------------------------------------------------

class TestEndToEndOverBus:
    def test_drainThreadPersistsPublishedBurst(self, freshDb: ObdDatabase) -> None:
        bus = SampleBus()
        subscription = bus.subscribe(
            ["raw.imu.*", "raw.light.*"], QoS.LOSSY, "edr-persistence"
        )
        sub = EdrPersistenceSubscriber(
            subscription, freshDb, imuSampleHz=50, imuPersistHz=50
        )
        sub.start()
        try:
            for f, v in (("accel", (1.0, 2.0, 3.0)), ("gyro", (0.0, 0.0, 0.0)),
                         ("mag", (0.0, 0.0, 0.0)), ("temp", 20.0)):
                bus.publish(_imu(f, v, 1))
            # give the drain thread a moment
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and not _imuRows(freshDb):
                time.sleep(0.02)
        finally:
            sub.stop()
        assert len(_imuRows(freshDb)) == 1

    def test_stopFlushesPendingPartialBurst(self, freshDb: ObdDatabase) -> None:
        sub = _noDecimation(freshDb)
        sub.handleSample(_imu("accel", (1.0, 2.0, 3.0), 1))
        # never completes the burst; stop() must flush the partial row
        sub.stop()
        rows = _imuRows(freshDb)
        assert len(rows) == 1
        assert rows[0][3:6] == (1.0, 2.0, 3.0)


# ---------------------------------------------------------------------------
# Factory gating (ships dark behind the per-sensor flags under pi.bus.enabled)
# ---------------------------------------------------------------------------

class TestFactory:
    def _config(self, *, bus: bool, imu: bool = False, light: bool = False) -> dict:
        return {
            "pi": {
                "bus": {"enabled": bus},
                "sensors": {
                    "imu": {"enabled": imu, "sampleHz": 50, "persistHz": 25},
                    "light": {"enabled": light, "sampleHz": 1},
                    "retentionDays": 7,
                },
            }
        }

    def test_noneWhenBusOff(self, freshDb: ObdDatabase) -> None:
        sub = createEdrPersistenceSubscriberFromConfig(
            self._config(bus=False, imu=True), SampleBus(), freshDb
        )
        assert sub is None

    def test_noneWhenNoSensorEnabled(self, freshDb: ObdDatabase) -> None:
        sub = createEdrPersistenceSubscriberFromConfig(
            self._config(bus=True, imu=False, light=False), SampleBus(), freshDb
        )
        assert sub is None

    def test_builtWhenSensorEnabled(self, freshDb: ObdDatabase) -> None:
        sub = createEdrPersistenceSubscriberFromConfig(
            self._config(bus=True, imu=True), SampleBus(), freshDb
        )
        assert isinstance(sub, EdrPersistenceSubscriber)
        sub.stop()
