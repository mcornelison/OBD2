################################################################################
# File Name: test_edr_end_to_end.py
# Purpose/Description: EDR bench harness + golden-master regression (US-411,
#     F-114). Wires the REAL production classes end-to-end with only the I2C
#     device handles mocked: ImuReader + LightReader (US-409) -> SampleBus
#     (F-110) -> EdrPersistenceSubscriber (US-410) -> edr_imu_sample /
#     edr_light_sample. Proves (1) synthetic samples land in both tables with
#     the right shape + one row per IMU seq, (2) the absent path publishes
#     state.sensor.*=absent with ZERO rows and no fabricated samples, (3) the
#     F-110 realtime_data byte-identical golden master is preserved with the EDR
#     flags OFF and with them ON (OBD-only) -- the EDR path is a separate
#     subscriber writing separate tables, so it cannot perturb raw.obd.*, and
#     (4) a saturating TSL2591 read persists lux=NULL + raw counts, never inf.
#     No hardware required -- this is the CIO connect-when-wired bench acceptance
#     (companion doc: docs/edr-connect-when-wired-drill.md).
#     ADR: docs/superpowers/specs/
#     2026-06-30-edr-sensor-reader-schema-bus-adr.md sections 1/2/3.
# Author: Rex (US-411)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""End-to-end EDR bench harness + F-110 golden-master regression (US-411)."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from pi.bus.bus import SampleBus
from pi.bus.edr_persistence_subscriber import (
    EdrPersistenceSubscriber,
    createEdrPersistenceSubscriberFromConfig,
)
from pi.bus.persistence_subscriber import PersistenceSubscriber
from pi.bus.sample import QoS, Sample
from pi.obdii.data.logger import ObdDataLogger
from pi.obdii.data.types import LoggedReading
from pi.obdii.database import ObdDatabase
from pi.sensors.sensor_reader import (
    ABSENT,
    STATE_IMU,
    STATE_LIGHT,
    ImuReader,
    LightReader,
)

# The synthetic bench uses the honest 'fixture' data_source tag (the CHECK enum
# accepts it) so no bench row is ever mistaken for a real ('real') capture.
_FIXTURE = "fixture"


# ---------------------------------------------------------------------------
# Mock I2C device handles (the ONLY thing faked -- every other class is prod)
# ---------------------------------------------------------------------------
class _MockImu:
    """Synthetic ICM-20948: fixed, per-axis-distinguishable burst readings."""

    def __init__(self) -> None:
        self.acceleration = (0.10, 0.20, 9.81)  # z ~ gravity
        self.gyro = (1.10, 1.20, 1.30)
        self.magnetic = (10.0, 20.0, 30.0)
        self.temperature = 26.5


class _MockLight:
    """Synthetic TSL2591: a clean daylight reading + raw channel counts."""

    def __init__(self) -> None:
        self.lux = 123.4
        self.visible = 100
        self.infrared = 40
        self.full_spectrum = 140


class _SaturatingLight:
    """Synthetic TSL2591 pinned in full sun: .lux raises overflow, counts max."""

    visible = 65535
    infrared = 65535
    full_spectrum = 65535

    @property
    def lux(self) -> float:
        # The real adafruit_tsl2591 driver raises on a saturated read; the
        # LightReader translates this to lux=None (persist NULL, never inf).
        raise OverflowError("TSL2591 saturated (overflow)")


def _absentFactory() -> Any:
    """A device factory that fails the I2C probe (sensor not wired / off-Pi)."""
    raise OSError("[Errno 121] Remote I/O error")  # what an absent I2C addr gives


# ---------------------------------------------------------------------------
# Harness: wire the real reader -> bus -> subscriber pipeline
# ---------------------------------------------------------------------------
@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """An initialized, empty ObdDatabase (creates the EDR tables at startup)."""
    db = ObdDatabase(str(tmp_path / "test_edr_e2e.db"), walMode=False)
    db.initialize()
    return db


def _buildPipeline(
    db: ObdDatabase,
    *,
    imuFactory: Any = None,
    lightFactory: Any = None,
) -> tuple[SampleBus, Any, EdrPersistenceSubscriber, list[Any]]:
    """Wire SampleBus + EDR subscriber (no decimation) + the requested readers.

    imuSampleHz == imuPersistHz (50/50) so persistence is 1:1 -- deterministic
    one-row-per-seq for the harness assertions.
    """
    bus = SampleBus()
    subscription = bus.subscribe(
        ["raw.imu.*", "raw.light.*"], QoS.LOSSY, "edr-persistence"
    )
    subscriber = EdrPersistenceSubscriber(
        subscription, db, imuSampleHz=50, imuPersistHz=50
    )
    readers: list[Any] = []
    if imuFactory is not None:
        readers.append(
            ImuReader(bus, sampleHz=50, deviceFactory=imuFactory, dataSource=_FIXTURE)
        )
    if lightFactory is not None:
        readers.append(
            LightReader(bus, sampleHz=1, deviceFactory=lightFactory, dataSource=_FIXTURE)
        )
    return bus, subscription, subscriber, readers


def _pump(
    readers: list[Any],
    subscription: Any,
    subscriber: EdrPersistenceSubscriber,
    *,
    polls: int = 1,
) -> None:
    """Probe each reader, drive ``polls`` deterministic poll cycles, then drain.

    Deterministic (no poll thread) so the row count equals ``polls`` exactly --
    the threaded lifecycle is exercised separately in US-410's tests.
    """
    for reader in readers:
        reader.probe()
    for _ in range(polls):
        for reader in readers:
            reader.pollOnce()
    while True:
        sample = subscription.poll()
        if sample is None:
            break
        subscriber.handleSample(sample)
    subscriber.flushPending()


def _imuRows(db: ObdDatabase) -> list[tuple]:
    with db.connect() as conn:
        conn.row_factory = None
        return conn.execute(
            "SELECT seq, accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z, "
            "mag_x, mag_y, mag_z, temp_c, data_source, schema_version "
            "FROM edr_imu_sample ORDER BY seq"
        ).fetchall()


def _lightRows(db: ObdDatabase) -> list[tuple]:
    with db.connect() as conn:
        conn.row_factory = None
        return conn.execute(
            "SELECT seq, lux, visible, infrared, full_spectrum, data_source "
            "FROM edr_light_sample ORDER BY seq"
        ).fetchall()


# ---------------------------------------------------------------------------
# (1) Mock-sensor harness: rows land in both tables, one row per IMU seq
# ---------------------------------------------------------------------------
class TestMockSensorHarness:
    def test_synthetic_bothSensors_rowsLandWithOneRowPerImuSeq(
        self, freshDb: ObdDatabase
    ) -> None:
        bus, sub, subscriber, readers = _buildPipeline(
            freshDb, imuFactory=_MockImu, lightFactory=_MockLight
        )
        _pump(readers, sub, subscriber, polls=3)

        imu = _imuRows(freshDb)
        light = _lightRows(freshDb)
        # One edr_imu_sample row per IMU burst seq (1, 2, 3) -- burst assembled.
        assert [r[0] for r in imu] == [1, 2, 3]
        assert [r[0] for r in light] == [1, 2, 3]

    def test_imuBurstValuesAndTagsMapped(self, freshDb: ObdDatabase) -> None:
        bus, sub, subscriber, readers = _buildPipeline(freshDb, imuFactory=_MockImu)
        _pump(readers, sub, subscriber, polls=1)

        (row,) = _imuRows(freshDb)
        assert row[1:4] == (0.10, 0.20, 9.81)   # accel x/y/z
        assert row[4:7] == (1.10, 1.20, 1.30)   # gyro x/y/z
        assert row[7:10] == (10.0, 20.0, 30.0)  # mag x/y/z
        assert row[10] == 26.5                  # temp_c
        assert row[11] == _FIXTURE              # data_source (honest synthetic tag)

    def test_lightRowValuesMapped(self, freshDb: ObdDatabase) -> None:
        bus, sub, subscriber, readers = _buildPipeline(freshDb, lightFactory=_MockLight)
        _pump(readers, sub, subscriber, polls=1)

        (row,) = _lightRows(freshDb)
        assert row[1] == 123.4              # lux
        assert row[2:5] == (100, 40, 140)   # visible, infrared, full_spectrum
        assert row[5] == _FIXTURE


# ---------------------------------------------------------------------------
# (2) Absent path: flags on, no sensors -> STATE=absent, zero rows, no fabrication
# ---------------------------------------------------------------------------
class TestAbsentPath:
    def test_absentSensors_stateAbsent_zeroRows_noFabricatedSamples(
        self, freshDb: ObdDatabase
    ) -> None:
        bus, sub, subscriber, readers = _buildPipeline(
            freshDb, imuFactory=_absentFactory, lightFactory=_absentFactory
        )
        # Watch the retained presence STATE topics.
        stateSub = bus.subscribe(["state.sensor.*"], QoS.LOSSY, "state-watch")

        # start() probes (absent), publishes STATE=absent, starts NO poll thread.
        for reader in readers:
            reader.start()
            reader.stop()

        # Presence STATE says absent for both sensors.
        seen: dict[str, float] = {}
        while True:
            s = stateSub.poll()
            if s is None:
                break
            seen[s.topic] = s.value
        assert seen.get(STATE_IMU) == ABSENT
        assert seen.get(STATE_LIGHT) == ABSENT

        # Not a single raw sample was published (silence, never a fabricated 0.0).
        assert sub.poll() is None
        subscriber.flushPending()
        assert _imuRows(freshDb) == []
        assert _lightRows(freshDb) == []


# ---------------------------------------------------------------------------
# (3) Golden-master regression: realtime_data byte-identical to the inline path
#     (reuses the F-110 discipline -- see tests/pi/bus/test_persistence_golden_master.py)
# ---------------------------------------------------------------------------
_GM_COLS = "parameter_name, value, unit, profile_id, drive_id, data_source"
_PROFILE_ID = "daily"
_OBD_READINGS = [
    ("RPM", 3500.0, "rpm"),
    ("COOLANT_TEMP", 92.0, "degC"),
    ("SPEED", 64.0, "km/h"),
]


def _seededDb(tmp_path: Path, name: str) -> ObdDatabase:
    """An initialized DB with the FK-target profile row seeded (realtime_data)."""
    db = ObdDatabase(str(tmp_path / name))
    db.initialize()
    with db.connect() as conn:
        conn.cursor().execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)", (_PROFILE_ID, "Daily")
        )
    return db


def _realtimeRows(db: ObdDatabase) -> list[tuple]:
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {_GM_COLS} FROM realtime_data ORDER BY id")
        return [tuple(r) for r in cur.fetchall()]


def _logInline(db: ObdDatabase) -> None:
    """The pre-bus reference path: ObdDataLogger.logReading directly."""
    logger = ObdDataLogger(
        connection=None, database=db, profileId=_PROFILE_ID, dataSource="real"
    )
    for name, val, unit in _OBD_READINGS:
        logger.logReading(LoggedReading(name, val, datetime.now(), unit, None))


def _obdConfig(*, imu: bool, light: bool) -> dict[str, Any]:
    return {
        "pi": {
            "bus": {"enabled": True},
            "sensors": {
                "imu": {"enabled": imu, "sampleHz": 50, "persistHz": 25},
                "light": {"enabled": light, "sampleHz": 1},
                "retentionDays": 7,
            },
        }
    }


class TestGoldenMasterRegression:
    def test_flagsOff_realtimeByteIdenticalToInlinePath(self, tmp_path: Path) -> None:
        # (a) reference: inline logReading.
        dbA = _seededDb(tmp_path, "gm_off_a.db")
        _logInline(dbA)

        # (b) bus OBD path with the EDR path NOT built (flags off -> factory None).
        dbB = _seededDb(tmp_path, "gm_off_b.db")
        loggerB = ObdDataLogger(
            connection=None, database=dbB, profileId=_PROFILE_ID, dataSource="real"
        )
        bus = SampleBus()
        obdSub = bus.subscribe(["raw.obd.*"], QoS.LOSSLESS, "persistence")
        ps = PersistenceSubscriber(obdSub, loggerB)
        edr = createEdrPersistenceSubscriberFromConfig(
            _obdConfig(imu=False, light=False), bus, dbB
        )
        assert edr is None  # ships dark: nothing built when both flags are off

        for i, (name, val, unit) in enumerate(_OBD_READINGS, start=1):
            bus.publish(
                Sample(f"raw.obd.{name}", "obd", val, unit,
                       "2026-06-18T00:00:00Z", float(i), None, "real", i)
            )
            ps.handleSample(obdSub.poll())

        assert _realtimeRows(dbA) == _realtimeRows(dbB)
        assert len(_realtimeRows(dbB)) == len(_OBD_READINGS)

    def test_flagsOn_obdOnly_realtimeByteIdentical_andZeroEdrRows(
        self, tmp_path: Path
    ) -> None:
        # (a) reference: inline logReading.
        dbA = _seededDb(tmp_path, "gm_on_a.db")
        _logInline(dbA)

        # (b) bus OBD path with a LIVE EDR subscriber alongside (flags on). It
        # subscribes raw.imu.*/raw.light.* only, so raw.obd.* cannot reach it.
        dbB = _seededDb(tmp_path, "gm_on_b.db")
        loggerB = ObdDataLogger(
            connection=None, database=dbB, profileId=_PROFILE_ID, dataSource="real"
        )
        bus = SampleBus()
        obdSub = bus.subscribe(["raw.obd.*"], QoS.LOSSLESS, "persistence")
        ps = PersistenceSubscriber(obdSub, loggerB)
        edr = createEdrPersistenceSubscriberFromConfig(
            _obdConfig(imu=True, light=True), bus, dbB
        )
        assert edr is not None  # built when a sensor flag is on

        for i, (name, val, unit) in enumerate(_OBD_READINGS, start=1):
            bus.publish(
                Sample(f"raw.obd.{name}", "obd", val, unit,
                       "2026-06-18T00:00:00Z", float(i), None, "real", i)
            )
            ps.handleSample(obdSub.poll())
        edr.stop()  # drains the EDR subscription + flushes (nothing to flush)

        # realtime_data byte-identical to the pre-bus inline path...
        assert _realtimeRows(dbA) == _realtimeRows(dbB)
        # ...and the coexisting EDR subscriber wrote zero rows (OBD-only feed).
        assert _imuRows(dbB) == []
        assert _lightRows(dbB) == []


# ---------------------------------------------------------------------------
# (4) Saturation: a saturating TSL2591 read persists lux=NULL + raw counts
# ---------------------------------------------------------------------------
class TestSaturation:
    def test_saturatingLight_persistsNullLux_keepsRawCounts_neverInf(
        self, freshDb: ObdDatabase
    ) -> None:
        bus, sub, subscriber, readers = _buildPipeline(
            freshDb, lightFactory=_SaturatingLight
        )
        _pump(readers, sub, subscriber, polls=1)

        (row,) = _lightRows(freshDb)
        assert row[1] is None                        # lux persisted NULL, never inf
        assert row[2:5] == (65535, 65535, 65535)     # raw counts still recorded
        # Belt-and-suspenders: whatever persisted for lux, it is not a float inf.
        assert not (isinstance(row[1], float) and math.isinf(row[1]))
