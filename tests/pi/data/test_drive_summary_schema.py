################################################################################
# File Name: test_drive_summary_schema.py
# Purpose/Description: Tests for the Pi SQLite drive_summary schema +
#                      idempotent migration helper (US-206).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-206) | Initial -- drive_summary schema + migration.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.obdii.drive_summary` schema + ``ObdDatabase`` wiring."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_summary import (
    DRIVE_SUMMARY_TABLE,
    SCHEMA_DRIVE_SUMMARY,
    ensureDriveSummaryTable,
)


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """An initialized, empty ObdDatabase backed by a new file."""
    db = ObdDatabase(str(tmp_path / "test_drivesummary.db"), walMode=False)
    db.initialize()
    return db


class TestFreshSchema:
    """After initialize(), drive_summary has the expected column shape."""

    def test_tableIsCreated(self, freshDb: ObdDatabase) -> None:
        assert DRIVE_SUMMARY_TABLE in freshDb.getTableNames()

    def test_columnShape(self, freshDb: ObdDatabase) -> None:
        cols = {c['name']: c for c in freshDb.getTableInfo(DRIVE_SUMMARY_TABLE)}
        expected = {
            'drive_id',
            'drive_start_timestamp',
            'ambient_temp_at_start_c',
            'starting_battery_v',
            'barometric_kpa_at_start',
            'data_source',
        }
        assert set(cols.keys()) == expected

    def test_driveIdIsPrimaryKey(self, freshDb: ObdDatabase) -> None:
        cols = {c['name']: c for c in freshDb.getTableInfo(DRIVE_SUMMARY_TABLE)}
        assert cols['drive_id']['pk'] == 1

    def test_metadataColumnsAreNullable(self, freshDb: ObdDatabase) -> None:
        cols = {c['name']: c for c in freshDb.getTableInfo(DRIVE_SUMMARY_TABLE)}
        for name in ('ambient_temp_at_start_c', 'starting_battery_v',
                     'barometric_kpa_at_start'):
            assert cols[name]['notnull'] == 0, (
                f"{name} must be nullable to honor cold-start NULL rule"
            )

    def test_dataSourceDefaultIsReal(self, freshDb: ObdDatabase) -> None:
        cols = {c['name']: c for c in freshDb.getTableInfo(DRIVE_SUMMARY_TABLE)}
        # sqlite PRAGMA table_info returns defaults as strings; trim quotes.
        default = str(cols['data_source']['dflt_value']).strip("'\"")
        assert default == 'real'

    def test_dataSourceCheckConstraintRejectsBogus(
        self, freshDb: ObdDatabase
    ) -> None:
        # ObdDatabase.connect() wraps sqlite3.IntegrityError into a
        # DatabaseConnectionError.  The underlying CHECK constraint is
        # what rejects the row.
        from src.pi.obdii.database import DatabaseConnectionError
        with pytest.raises((sqlite3.IntegrityError, DatabaseConnectionError)):
            with freshDb.connect() as conn:
                conn.execute(
                    f"INSERT INTO {DRIVE_SUMMARY_TABLE} "
                    "(drive_id, data_source) VALUES (?, ?)",
                    (1, 'bogus_source'),
                )

    def test_driveStartTimestampDefaultsToCanonicalIso(
        self, freshDb: ObdDatabase
    ) -> None:
        with freshDb.connect() as conn:
            conn.execute(
                f"INSERT INTO {DRIVE_SUMMARY_TABLE} (drive_id) VALUES (1)"
            )
            row = conn.execute(
                f"SELECT drive_start_timestamp FROM {DRIVE_SUMMARY_TABLE} "
                "WHERE drive_id = 1"
            ).fetchone()
        # Canonical ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ
        assert row[0].endswith('Z')
        assert 'T' in row[0]
        assert len(row[0]) == 20


class TestMigrationIdempotency:
    """ensureDriveSummaryTable is idempotent across multiple calls."""

    def test_firstCallOnBareDbReturnsTrue(self, tmp_path: Path) -> None:
        path = tmp_path / "bare.db"
        conn = sqlite3.connect(str(path))
        try:
            created = ensureDriveSummaryTable(conn)
            assert created is True
        finally:
            conn.close()

    def test_secondCallIsNoOpReturnsFalse(self, tmp_path: Path) -> None:
        path = tmp_path / "bare.db"
        conn = sqlite3.connect(str(path))
        try:
            assert ensureDriveSummaryTable(conn) is True
            assert ensureDriveSummaryTable(conn) is False
        finally:
            conn.close()

    def test_migrationCreatesTableOnPreUs206Database(
        self, tmp_path: Path
    ) -> None:
        """A legacy db missing drive_summary picks it up via ensureDriveSummaryTable."""
        path = tmp_path / "legacy.db"
        # Simulate a legacy DB that has drive_counter but no drive_summary
        # table.  Direct call to ensureDriveSummaryTable (rather than
        # ObdDatabase.initialize, which rebuilds the full schema) isolates
        # the migration contract.
        legacyConn = sqlite3.connect(str(path))
        legacyConn.execute(
            "CREATE TABLE drive_counter ("
            "id INTEGER PRIMARY KEY CHECK (id=1), "
            "last_drive_id INTEGER NOT NULL DEFAULT 0)"
        )
        legacyConn.commit()

        # Before migration: drive_summary missing.
        row = legacyConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = 'drive_summary'"
        ).fetchone()
        assert row is None

        # After migration: drive_summary present; counter untouched.
        created = ensureDriveSummaryTable(legacyConn)
        legacyConn.commit()
        assert created is True

        row = legacyConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = 'drive_summary'"
        ).fetchone()
        assert row is not None
        legacyConn.close()


class TestSchemaStringContents:
    """Sanity check on the DDL string itself -- authoritative grep target."""

    def test_schemaMentionsCanonicalStrftimeDefault(self) -> None:
        assert "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')" in SCHEMA_DRIVE_SUMMARY

    def test_schemaDeclaresDriveIdPrimaryKey(self) -> None:
        assert "drive_id INTEGER PRIMARY KEY" in SCHEMA_DRIVE_SUMMARY

    def test_schemaListsAllThreeMetadataColumns(self) -> None:
        assert "ambient_temp_at_start_c REAL" in SCHEMA_DRIVE_SUMMARY
        assert "starting_battery_v REAL" in SCHEMA_DRIVE_SUMMARY
        assert "barometric_kpa_at_start REAL" in SCHEMA_DRIVE_SUMMARY
