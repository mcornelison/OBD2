################################################################################
# File Name: test_sensor_schema.py
# Purpose/Description: Unit tests for the single-source EDR raw-sensor schema
#                      contract (src/common/edr/sensor_schema.py) -- verifies the
#                      ADR section 2.2 DDL: columns, data_source CHECK, indexes,
#                      schema_version default, and idempotency (US-408).
# Author: Rex (US-408)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Rex (US-408) | Initial -- EDR versioned schema contract tests.
# ================================================================================
################################################################################
"""Tests for the versioned EDR raw-sensor schema contract (A-4 anti-divergence)."""

from __future__ import annotations

import sqlite3

import pytest

from src.common.edr.sensor_schema import (
    EDR_INDEXES,
    EDR_SCHEMAS,
    SCHEMA_VERSION,
)

# Exact column order per ADR 2026-06-30 section 2.2 (edr-sensor-reader-schema-bus).
IMU_COLUMNS = [
    "id", "ts_utc", "ts_capture", "seq",
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
    "mag_x", "mag_y", "mag_z",
    "temp_c", "drive_id", "data_source", "schema_version",
]
LIGHT_COLUMNS = [
    "id", "ts_utc", "ts_capture", "seq",
    "lux", "visible", "infrared", "full_spectrum",
    "gain", "integration_ms",
    "drive_id", "data_source", "schema_version",
]


def _applySchema(conn: sqlite3.Connection) -> None:
    """Create all EDR tables + indexes on a connection, mirroring Pi startup."""
    for _name, ddl in EDR_SCHEMAS:
        conn.executescript(ddl)
    for _name, ddl in EDR_INDEXES:
        conn.executescript(ddl)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """An in-memory SQLite connection with the EDR schema applied once."""
    connection = sqlite3.connect(":memory:")
    _applySchema(connection)
    yield connection
    connection.close()


class TestSchemaVersionConstant:
    def test_schemaVersion_isBareIntOne(self) -> None:
        """
        Given: the EDR contract module
        When: reading SCHEMA_VERSION
        Then: it is a bare int == 1 (mirrors power_watch.RECORD_SCHEMA_VERSION).
        """
        assert isinstance(SCHEMA_VERSION, int)
        assert not isinstance(SCHEMA_VERSION, bool)
        assert SCHEMA_VERSION == 1


class TestTableColumns:
    def test_imuTable_hasExactAdrColumns(self, conn: sqlite3.Connection) -> None:
        """edr_imu_sample columns match ADR section 2.2 exactly, in order."""
        cols = [r[1] for r in conn.execute("PRAGMA table_info(edr_imu_sample)")]
        assert cols == IMU_COLUMNS

    def test_lightTable_hasExactAdrColumns(self, conn: sqlite3.Connection) -> None:
        """edr_light_sample columns match ADR section 2.2 exactly, in order."""
        cols = [r[1] for r in conn.execute("PRAGMA table_info(edr_light_sample)")]
        assert cols == LIGHT_COLUMNS

    def test_notNullContract_matchesAdr(self, conn: sqlite3.Connection) -> None:
        """ts_utc, ts_capture, seq, data_source, schema_version are NOT NULL; the
        sensor value columns (lux, accel_*, drive_id) are nullable (honest-absence)."""
        imu = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(edr_imu_sample)")}
        assert imu["ts_utc"] == 1 and imu["ts_capture"] == 1 and imu["seq"] == 1
        assert imu["data_source"] == 1 and imu["schema_version"] == 1
        assert imu["accel_x"] == 0 and imu["drive_id"] == 0
        light = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(edr_light_sample)")}
        assert light["lux"] == 0 and light["drive_id"] == 0


class TestIndexes:
    def test_allFourAdrIndexesExist(self, conn: sqlite3.Connection) -> None:
        """The 4 ADR section 2.2 indexes (drive_id + ts on both tables) exist."""
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name LIKE 'ix_edr_%'"
            )
        }
        assert names == {
            "ix_edr_imu_sample_drive_id",
            "ix_edr_imu_sample_ts",
            "ix_edr_light_sample_drive_id",
            "ix_edr_light_sample_ts",
        }


class TestDataSourceCheck:
    def test_validDataSource_accepted(self, conn: sqlite3.Connection) -> None:
        """A row with an enum-valid data_source persists."""
        conn.execute(
            "INSERT INTO edr_imu_sample (ts_utc, ts_capture, seq, data_source) "
            "VALUES ('2026-06-30T00:00:00Z', 0.0, 1, 'fixture')"
        )
        assert conn.execute("SELECT COUNT(*) FROM edr_imu_sample").fetchone()[0] == 1

    def test_invalidDataSource_rejectedByCheck(self, conn: sqlite3.Connection) -> None:
        """The data_source CHECK contract rejects a value outside the enum."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO edr_light_sample (ts_utc, ts_capture, seq, data_source) "
                "VALUES ('2026-06-30T00:00:00Z', 0.0, 1, 'bogus')"
            )


class TestSchemaVersionStamped:
    def test_schemaVersionDefaultsToOne_onImu(self, conn: sqlite3.Connection) -> None:
        """A row inserted without schema_version defaults to 1 (ADR section 2.5)."""
        conn.execute(
            "INSERT INTO edr_imu_sample (ts_utc, ts_capture, seq) "
            "VALUES ('2026-06-30T00:00:00Z', 0.0, 1)"
        )
        row = conn.execute("SELECT schema_version FROM edr_imu_sample").fetchone()
        assert row[0] == SCHEMA_VERSION == 1

    def test_schemaVersionDefaultsToOne_onLight(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO edr_light_sample (ts_utc, ts_capture, seq) "
            "VALUES ('2026-06-30T00:00:00Z', 0.0, 1)"
        )
        row = conn.execute("SELECT schema_version FROM edr_light_sample").fetchone()
        assert row[0] == 1


class TestIdempotency:
    def test_applyingSchemaTwice_isNoOp(self) -> None:
        """CREATE ... IF NOT EXISTS run twice does not raise or duplicate tables."""
        connection = sqlite3.connect(":memory:")
        try:
            _applySchema(connection)
            _applySchema(connection)  # second pass must be a no-op
            tables = {
                r[0]
                for r in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'edr_%'"
                )
            }
            assert tables == {"edr_imu_sample", "edr_light_sample"}
        finally:
            connection.close()
