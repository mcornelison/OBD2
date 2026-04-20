################################################################################
# File Name: test_drive_id_migration.py
# Purpose/Description: Schema + migration tests for the drive_id column across
#                      Pi capture tables + the drive_counter sequence table
#                      (US-200 / Spool Data v2 Story 2).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Tests for the Pi-side ``drive_id`` column + drive_counter sequence.

US-200 adds a nullable ``drive_id INTEGER`` column to
``realtime_data``, ``connection_log``, ``statistics`` and ``alert_log``
plus an indexed lookup for per-drive analytics. Existing rows stay
NULL (Invariant #4: do NOT retag Session 23's 149 rows).

A small ``drive_counter`` single-row table backs the monotonic
Pi-local sequence.  Invariant: never reuse a drive_id, never go
backwards (NTP skew doesn't matter because we use a sequence, not
wall-clock ms).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_id import (
    DRIVE_COUNTER_TABLE,
    DRIVE_ID_COLUMN,
    DRIVE_ID_TABLES,
    ensureAllDriveIdColumns,
    ensureDriveCounter,
    ensureDriveIdColumn,
    makeDriveIdGenerator,
    nextDriveId,
)


@pytest.fixture
def freshDb(tmp_path) -> Generator[ObdDatabase, None, None]:
    dbPath = tmp_path / "obd.db"
    db = ObdDatabase(str(dbPath), walMode=False)
    db.initialize()
    yield db


@pytest.fixture
def rawConn(tmp_path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(tmp_path / "obd.db"))
    try:
        yield conn
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


# ================================================================================
# Fresh-schema: drive_id present on all in-scope tables with nullable INTEGER
# ================================================================================

class TestFreshSchema:
    @pytest.mark.parametrize("tableName", DRIVE_ID_TABLES)
    def test_driveIdPresentOnTable(
        self, freshDb: ObdDatabase, tableName: str
    ) -> None:
        with freshDb.connect() as conn:
            cols = _columns(conn, tableName)
            assert DRIVE_ID_COLUMN in cols

    @pytest.mark.parametrize("tableName", DRIVE_ID_TABLES)
    def test_driveIdIsNullable(
        self, freshDb: ObdDatabase, tableName: str
    ) -> None:
        with freshDb.connect() as conn:
            info = conn.execute(f"PRAGMA table_info({tableName})").fetchall()
            row = next(r for r in info if r[1] == DRIVE_ID_COLUMN)
            # row[3] = notnull flag; 0 = nullable
            assert row[3] == 0, (
                f"{tableName}.{DRIVE_ID_COLUMN} should be nullable so "
                "pre-US-200 rows + no-active-drive rows can coexist"
            )

    @pytest.mark.parametrize("tableName", DRIVE_ID_TABLES)
    def test_driveIdIndexExists(
        self, freshDb: ObdDatabase, tableName: str
    ) -> None:
        with freshDb.connect() as conn:
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
                (tableName,),
            ).fetchall()
            indexNames = [i[0] for i in indexes]
            expected = f"IX_{tableName}_drive_id"
            assert expected in indexNames, (
                f"{tableName} missing index {expected}; "
                f"have {indexNames}"
            )

    def test_driveCounterTableExists(self, freshDb: ObdDatabase) -> None:
        with freshDb.connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (DRIVE_COUNTER_TABLE,),
            ).fetchone()
            assert row is not None

    def test_driveCounterSeededWithOneRow(self, freshDb: ObdDatabase) -> None:
        with freshDb.connect() as conn:
            rows = conn.execute(
                f"SELECT id, last_drive_id FROM {DRIVE_COUNTER_TABLE}"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == 1  # singleton row
            assert rows[0][1] == 0  # no drives yet


# ================================================================================
# Migration: adding drive_id to a pre-US-200 schema
# ================================================================================

class TestMigration:
    def _createPreUs200Schema(self, conn: sqlite3.Connection) -> None:
        """Minimal schema snapshot before US-200 added drive_id."""
        conn.execute(
            """CREATE TABLE realtime_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                parameter_name TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                profile_id TEXT,
                data_source TEXT NOT NULL DEFAULT 'real'
            )"""
        )
        conn.execute(
            """CREATE TABLE connection_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                event_type TEXT NOT NULL,
                mac_address TEXT,
                success INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parameter_name TEXT NOT NULL,
                analysis_date DATETIME NOT NULL,
                profile_id TEXT NOT NULL,
                sample_count INTEGER
            )"""
        )
        conn.execute(
            """CREATE TABLE alert_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                alert_type TEXT NOT NULL,
                parameter_name TEXT NOT NULL,
                value REAL NOT NULL,
                threshold REAL NOT NULL
            )"""
        )
        conn.commit()

    def test_ensureDriveIdColumnAddsOnce(self, rawConn: sqlite3.Connection) -> None:
        self._createPreUs200Schema(rawConn)
        assert DRIVE_ID_COLUMN not in _columns(rawConn, 'realtime_data')
        added = ensureDriveIdColumn(rawConn, 'realtime_data')
        assert added is True
        assert DRIVE_ID_COLUMN in _columns(rawConn, 'realtime_data')

    def test_ensureDriveIdColumnIdempotent(
        self, rawConn: sqlite3.Connection
    ) -> None:
        self._createPreUs200Schema(rawConn)
        ensureDriveIdColumn(rawConn, 'realtime_data')
        # Second call is a no-op, not an error
        added = ensureDriveIdColumn(rawConn, 'realtime_data')
        assert added is False
        # Column appears exactly once
        cols = _columns(rawConn, 'realtime_data')
        assert cols.count(DRIVE_ID_COLUMN) == 1

    def test_ensureDriveIdColumnMissingTableIsNoop(
        self, rawConn: sqlite3.Connection
    ) -> None:
        added = ensureDriveIdColumn(rawConn, 'nope_does_not_exist')
        assert added is False

    def test_ensureAllDriveIdColumnsCoversAllTables(
        self, rawConn: sqlite3.Connection
    ) -> None:
        self._createPreUs200Schema(rawConn)
        migrated = ensureAllDriveIdColumns(rawConn)
        # All 4 tables migrated
        assert set(migrated) == set(DRIVE_ID_TABLES)
        for table in DRIVE_ID_TABLES:
            assert DRIVE_ID_COLUMN in _columns(rawConn, table)

    def test_preExistingRowsGetNullDriveId(
        self, rawConn: sqlite3.Connection
    ) -> None:
        """Invariant #4: pre-US-200 rows must remain untagged (NULL), not
        retroactively set to a sentinel like 0."""
        self._createPreUs200Schema(rawConn)
        rawConn.execute(
            "INSERT INTO realtime_data (parameter_name, value, unit, profile_id) "
            "VALUES ('RPM', 800.0, 'rpm', 'daily')"
        )
        rawConn.commit()
        ensureDriveIdColumn(rawConn, 'realtime_data')
        row = rawConn.execute(
            "SELECT drive_id FROM realtime_data WHERE parameter_name='RPM'"
        ).fetchone()
        assert row[0] is None


# ================================================================================
# Counter sequence: monotonic, no reuse, no backwards motion
# ================================================================================

class TestCounterSequence:
    def test_ensureDriveCounterCreatesTable(
        self, rawConn: sqlite3.Connection
    ) -> None:
        ensureDriveCounter(rawConn)
        row = rawConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (DRIVE_COUNTER_TABLE,),
        ).fetchone()
        assert row is not None

    def test_ensureDriveCounterIdempotent(
        self, rawConn: sqlite3.Connection
    ) -> None:
        ensureDriveCounter(rawConn)
        ensureDriveCounter(rawConn)
        rows = rawConn.execute(
            f"SELECT last_drive_id FROM {DRIVE_COUNTER_TABLE}"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 0  # still 0 because no one asked for a drive_id

    def test_nextDriveIdFirstCallReturnsOne(
        self, rawConn: sqlite3.Connection
    ) -> None:
        ensureDriveCounter(rawConn)
        assert nextDriveId(rawConn) == 1

    def test_nextDriveIdMonotonic(
        self, rawConn: sqlite3.Connection
    ) -> None:
        ensureDriveCounter(rawConn)
        seq = [nextDriveId(rawConn) for _ in range(5)]
        assert seq == [1, 2, 3, 4, 5]

    def test_nextDriveIdPersistsAcrossReopen(
        self, tmp_path
    ) -> None:
        dbPath = tmp_path / "obd.db"
        conn1 = sqlite3.connect(str(dbPath))
        try:
            ensureDriveCounter(conn1)
            first = nextDriveId(conn1)
            conn1.commit()
        finally:
            conn1.close()
        conn2 = sqlite3.connect(str(dbPath))
        try:
            ensureDriveCounter(conn2)  # idempotent
            second = nextDriveId(conn2)
            conn2.commit()
        finally:
            conn2.close()
        assert first == 1
        assert second == 2  # survived the reopen -- no reuse

    def test_makeDriveIdGeneratorClosure(
        self, rawConn: sqlite3.Connection
    ) -> None:
        ensureDriveCounter(rawConn)
        gen = makeDriveIdGenerator(rawConn)
        assert gen() == 1
        assert gen() == 2


# ================================================================================
# DDL fragment contract
# ================================================================================

class TestDDL:
    def test_driveIdColumnConstantShape(self) -> None:
        assert DRIVE_ID_COLUMN == 'drive_id'

    def test_driveIdTablesContainsExpectedSet(self) -> None:
        # Spool Priority 3 enumeration: realtime_data, connection_log,
        # statistics, alert_log.
        assert set(DRIVE_ID_TABLES) == {
            'realtime_data',
            'connection_log',
            'statistics',
            'alert_log',
        }

    def test_driveCounterTableConstant(self) -> None:
        assert DRIVE_COUNTER_TABLE == 'drive_counter'
