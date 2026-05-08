################################################################################
# File Name: test_battery_health_log_schema.py
# Purpose/Description: Tests for the Pi SQLite battery_health_log schema +
#                      idempotent migration helper (US-217).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-217) | Initial -- schema + migration.
# 2026-05-07    | Rex (US-289) | Added start_vcell_v + end_vcell_v to the
#                               expected column set in test_columnShape.
#                               Spool Sprint 26 Story 6 column rename --
#                               the new columns ship alongside the legacy
#                               start_soc / end_soc during deprecation.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.power.battery_health` schema + migration helper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.pi.obdii.database import DatabaseConnectionError, ObdDatabase
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    SCHEMA_BATTERY_HEALTH_LOG,
    ensureBatteryHealthLogTable,
)


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """An initialized, empty ObdDatabase backed by a new file."""
    db = ObdDatabase(str(tmp_path / "test_bhl.db"), walMode=False)
    db.initialize()
    return db


class TestFreshSchema:
    """After initialize(), battery_health_log has the expected column shape."""

    def test_tableIsCreated(self, freshDb: ObdDatabase) -> None:
        assert BATTERY_HEALTH_LOG_TABLE in freshDb.getTableNames()

    def test_columnShape(self, freshDb: ObdDatabase) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        expected = {
            'drain_event_id',
            'start_timestamp',
            'end_timestamp',
            'start_soc',  # DEPRECATED by US-289 (kept during rename window)
            'end_soc',    # DEPRECATED by US-289 (kept during rename window)
            'start_vcell_v',  # US-289 rename
            'end_vcell_v',    # US-289 rename
            'runtime_seconds',
            'ambient_temp_c',
            'load_class',
            'notes',
            'data_source',
        }
        assert set(cols.keys()) == expected

    def test_drainEventIdIsPrimaryKey(self, freshDb: ObdDatabase) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        assert cols['drain_event_id']['pk'] == 1

    def test_startSocIsNotNull(self, freshDb: ObdDatabase) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        assert cols['start_soc']['notnull'] == 1

    def test_endSocAndEndTimestampAreNullable(
        self, freshDb: ObdDatabase,
    ) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        # Pre-close rows leave these NULL.
        assert cols['end_soc']['notnull'] == 0
        assert cols['end_timestamp']['notnull'] == 0
        assert cols['runtime_seconds']['notnull'] == 0
        assert cols['ambient_temp_c']['notnull'] == 0

    def test_loadClassDefaultIsProduction(self, freshDb: ObdDatabase) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        default = str(cols['load_class']['dflt_value']).strip("'\"")
        assert default == 'production'

    def test_dataSourceDefaultIsReal(self, freshDb: ObdDatabase) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        default = str(cols['data_source']['dflt_value']).strip("'\"")
        assert default == 'real'

    def test_startTimestampDefaultIsCanonicalIso(
        self, freshDb: ObdDatabase,
    ) -> None:
        """DB DEFAULT populates a canonical ISO-8601 UTC stamp."""
        with freshDb.connect() as conn:
            conn.execute(
                f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} (start_soc) "
                "VALUES (?)",
                (100.0,),
            )
            row = conn.execute(
                f"SELECT start_timestamp FROM {BATTERY_HEALTH_LOG_TABLE} "
                "WHERE drain_event_id = (SELECT MAX(drain_event_id) "
                f"FROM {BATTERY_HEALTH_LOG_TABLE})"
            ).fetchone()
        # Canonical ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ (20 chars).
        assert row[0].endswith('Z')
        assert 'T' in row[0]
        assert len(row[0]) == 20


class TestCheckConstraints:
    """CHECK constraints reject out-of-enum values at INSERT time."""

    def test_loadClassCheckRejectsBogus(self, freshDb: ObdDatabase) -> None:
        with pytest.raises((sqlite3.IntegrityError, DatabaseConnectionError)):
            with freshDb.connect() as conn:
                conn.execute(
                    f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} "
                    "(start_soc, load_class) VALUES (?, ?)",
                    (100.0, 'bogus_class'),
                )

    def test_dataSourceCheckRejectsBogus(self, freshDb: ObdDatabase) -> None:
        with pytest.raises((sqlite3.IntegrityError, DatabaseConnectionError)):
            with freshDb.connect() as conn:
                conn.execute(
                    f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} "
                    "(start_soc, data_source) VALUES (?, ?)",
                    (100.0, 'bogus_source'),
                )

    def test_loadClassAcceptsAllThreeValues(self, freshDb: ObdDatabase) -> None:
        with freshDb.connect() as conn:
            for loadClass in ('production', 'test', 'sim'):
                conn.execute(
                    f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} "
                    "(start_soc, load_class) VALUES (?, ?)",
                    (100.0, loadClass),
                )
        # Three successful inserts.
        with freshDb.connect() as conn:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchone()[0]
        assert count == 3


class TestAutoIncrement:
    """drain_event_id is auto-incremented + monotonic."""

    def test_multipleInsertsGetDistinctMonotonicIds(
        self, freshDb: ObdDatabase,
    ) -> None:
        with freshDb.connect() as conn:
            for soc in (100.0, 80.0, 60.0):
                conn.execute(
                    f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} (start_soc) "
                    "VALUES (?)",
                    (soc,),
                )
            ids = [
                row[0]
                for row in conn.execute(
                    f"SELECT drain_event_id FROM {BATTERY_HEALTH_LOG_TABLE} "
                    "ORDER BY drain_event_id ASC"
                ).fetchall()
            ]
        assert len(ids) == 3
        assert ids == sorted(set(ids))  # distinct + ascending


class TestMigrationIdempotency:
    """ensureBatteryHealthLogTable is idempotent across multiple calls."""

    def test_firstCallOnBareDbReturnsTrue(self, tmp_path: Path) -> None:
        path = tmp_path / "bare.db"
        conn = sqlite3.connect(str(path))
        try:
            assert ensureBatteryHealthLogTable(conn) is True
        finally:
            conn.close()

    def test_secondCallIsNoOpReturnsFalse(self, tmp_path: Path) -> None:
        path = tmp_path / "bare.db"
        conn = sqlite3.connect(str(path))
        try:
            assert ensureBatteryHealthLogTable(conn) is True
            assert ensureBatteryHealthLogTable(conn) is False
        finally:
            conn.close()

    def test_migrationCreatesTableOnPreUs217Database(
        self, tmp_path: Path,
    ) -> None:
        """A legacy db missing battery_health_log picks it up via the helper."""
        path = tmp_path / "legacy.db"
        legacyConn = sqlite3.connect(str(path))
        # Simulate a pre-US-217 db with some other capture table.
        legacyConn.execute(
            "CREATE TABLE realtime_data ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp TEXT, parameter_name TEXT, value REAL)"
        )
        legacyConn.commit()

        # Before migration: battery_health_log missing.
        row = legacyConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            f"AND name = '{BATTERY_HEALTH_LOG_TABLE}'"
        ).fetchone()
        assert row is None

        # After migration: present.
        assert ensureBatteryHealthLogTable(legacyConn) is True
        legacyConn.commit()
        row = legacyConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            f"AND name = '{BATTERY_HEALTH_LOG_TABLE}'"
        ).fetchone()
        assert row is not None
        legacyConn.close()

    def test_migrationCreatesStartIndex(self, tmp_path: Path) -> None:
        """IX_battery_health_log_start is created by the migration helper."""
        path = tmp_path / "bare.db"
        conn = sqlite3.connect(str(path))
        try:
            ensureBatteryHealthLogTable(conn)
            conn.commit()
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                f"AND tbl_name = '{BATTERY_HEALTH_LOG_TABLE}'"
            ).fetchall()
            names = {row[0] for row in indexes}
            assert 'IX_battery_health_log_start' in names
        finally:
            conn.close()


class TestSchemaStringContents:
    """Sanity check on the DDL string itself."""

    def test_schemaMentionsCanonicalStrftimeDefault(self) -> None:
        assert (
            "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            in SCHEMA_BATTERY_HEALTH_LOG
        )

    def test_schemaDeclaresDrainEventIdAutoincrement(self) -> None:
        assert (
            "drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT"
            in SCHEMA_BATTERY_HEALTH_LOG
        )

    def test_schemaDeclaresLoadClassCheckConstraint(self) -> None:
        assert (
            "CHECK (load_class IN ('production','test','sim'))"
            in SCHEMA_BATTERY_HEALTH_LOG
        )
