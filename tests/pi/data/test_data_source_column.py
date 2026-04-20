################################################################################
# File Name: test_data_source_column.py
# Purpose/Description: Schema + behavior tests for the data_source column
#                      across Pi capture tables (US-195, Spool CR #4).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-195 (CR #4)
# ================================================================================
################################################################################

"""Tests for the Pi-side ``data_source`` column (Spool CR #4 / US-195).

Validates that every capture table that can receive non-real rows carries
a ``data_source TEXT NOT NULL DEFAULT 'real'`` column with a CHECK
constraint restricting values to ``'real' | 'replay' | 'physics_sim' |
'fixture'``, and that the idempotent migration helper can add the column
to a pre-US-195 schema without data loss.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

import pytest

from src.pi.obdii.data_source import (
    CAPTURE_TABLES,
    DATA_SOURCE_DEFAULT,
    DATA_SOURCE_VALUES,
    ensureDataSourceColumn,
)
from src.pi.obdii.database import DatabaseConnectionError, ObdDatabase


@pytest.fixture
def freshDb(tmp_path) -> Generator[ObdDatabase, None, None]:
    """Build a freshly-initialized Pi database on disk."""
    dbPath = tmp_path / "obd.db"
    db = ObdDatabase(str(dbPath), walMode=False)
    db.initialize()
    yield db


@pytest.fixture
def rawConn(tmp_path) -> Generator[sqlite3.Connection, None, None]:
    """Hand-rolled raw connection for migration-simulation tests."""
    conn = sqlite3.connect(str(tmp_path / "obd.db"))
    try:
        yield conn
    finally:
        conn.close()


def _columnInfo(
    conn: sqlite3.Connection,
    tableName: str,
    columnName: str,
) -> dict | None:
    """Return PRAGMA table_info row for ``columnName`` or None."""
    rows = conn.execute(f"PRAGMA table_info({tableName})").fetchall()
    keys = ('cid', 'name', 'type', 'notnull', 'dflt_value', 'pk')
    for row in rows:
        info = dict(zip(keys, row, strict=True))
        if info['name'] == columnName:
            return info
    return None


# ================================================================================
# Constants + enum discipline
# ================================================================================

def test_dataSourceEnum_expectedFourValues():
    """DATA_SOURCE_VALUES is the Spool-enumerated closed set."""
    assert DATA_SOURCE_VALUES == ('real', 'replay', 'physics_sim', 'fixture')


def test_dataSourceDefault_isReal():
    """Default for the live-OBD path is 'real' per CR #4."""
    assert DATA_SOURCE_DEFAULT == 'real'


def test_captureTables_matchesSpoolEnumeration():
    """CAPTURE_TABLES matches the Spool CR #4 list.

    Excludes tables that can only ever carry real data (vehicle_info,
    sync_log, alerts) per sprint doNotTouch list.
    """
    assert set(CAPTURE_TABLES) == {
        'realtime_data',
        'connection_log',
        'statistics',
        'calibration_sessions',
        'profiles',
    }


# ================================================================================
# Fresh schema: every capture table has data_source column
# ================================================================================

@pytest.mark.parametrize('tableName', [
    'realtime_data',
    'connection_log',
    'statistics',
    'calibration_sessions',
    'profiles',
])
def test_freshSchema_captureTableHasDataSourceColumn(freshDb, tableName):
    """Every capture table has data_source on fresh init."""
    with freshDb.connect() as conn:
        info = _columnInfo(conn, tableName, 'data_source')

    assert info is not None, f"{tableName} missing data_source column"
    assert info['notnull'] == 1
    assert info['dflt_value'] is not None
    assert "'real'" in info['dflt_value']


def test_freshSchema_liveInsert_defaultsToReal(freshDb):
    """INSERT without data_source on realtime_data falls through to 'real'."""
    with freshDb.connect() as conn:
        conn.execute(
            "INSERT INTO realtime_data (parameter_name, value, unit) "
            "VALUES (?, ?, ?)",
            ('RPM', 850.0, 'rpm'),
        )
        row = conn.execute(
            "SELECT data_source FROM realtime_data WHERE parameter_name='RPM'"
        ).fetchone()

    assert row['data_source'] == 'real'


def test_freshSchema_validEnumValueAccepted(freshDb):
    """INSERT with explicit 'replay' is persisted."""
    with freshDb.connect() as conn:
        conn.execute(
            "INSERT INTO realtime_data "
            "(parameter_name, value, unit, data_source) "
            "VALUES (?, ?, ?, ?)",
            ('COOLANT_TEMP', 75.0, 'C', 'replay'),
        )
        row = conn.execute(
            "SELECT data_source FROM realtime_data "
            "WHERE parameter_name='COOLANT_TEMP'"
        ).fetchone()

    assert row['data_source'] == 'replay'


def test_freshSchema_invalidEnumValueRejected(freshDb):
    """CHECK constraint rejects values outside the enum.

    The ObdDatabase context manager wraps sqlite3.IntegrityError in
    DatabaseConnectionError, so we assert the wrapper and confirm the
    underlying IntegrityError via ``__cause__``.
    """
    with pytest.raises(DatabaseConnectionError) as excinfo:
        with freshDb.connect() as conn:
            conn.execute(
                "INSERT INTO realtime_data "
                "(parameter_name, value, unit, data_source) "
                "VALUES (?, ?, ?, ?)",
                ('RPM', 850.0, 'rpm', 'garbage'),
            )
    assert isinstance(excinfo.value.__cause__, sqlite3.IntegrityError)
    assert 'CHECK constraint failed' in str(excinfo.value.__cause__)


def test_freshSchema_connectionLogDefault(freshDb):
    """connection_log live-path insert picks up default 'real'."""
    with freshDb.connect() as conn:
        conn.execute(
            "INSERT INTO connection_log (event_type, success) VALUES (?, ?)",
            ('connect_attempt', 1),
        )
        row = conn.execute(
            "SELECT data_source FROM connection_log"
        ).fetchone()

    assert row['data_source'] == 'real'


def test_freshSchema_statisticsDefault(freshDb):
    """statistics live-path insert picks up default 'real'.

    Seeds a profile row first because statistics has an FK to profiles.
    """
    with freshDb.connect() as conn:
        conn.execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)",
            ('daily', 'Daily Commute'),
        )
        conn.execute(
            "INSERT INTO statistics "
            "(parameter_name, profile_id, avg_value) VALUES (?, ?, ?)",
            ('RPM', 'daily', 850.0),
        )
        row = conn.execute(
            "SELECT data_source FROM statistics"
        ).fetchone()

    assert row['data_source'] == 'real'


# ================================================================================
# Idempotent migration: pre-US-195 schema -> with data_source
# ================================================================================

def _createPreUs195Table(conn: sqlite3.Connection) -> None:
    """Simulate a pre-US-195 realtime_data schema without data_source."""
    conn.execute("""
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT,
            profile_id TEXT
        )
    """)
    conn.execute(
        "INSERT INTO realtime_data (parameter_name, value) VALUES (?, ?)",
        ('RPM', 793.0),
    )
    conn.commit()


def test_ensureDataSourceColumn_addsColumnToLegacyTable(rawConn):
    """ensureDataSourceColumn upgrades a pre-US-195 table in place."""
    _createPreUs195Table(rawConn)

    ensureDataSourceColumn(rawConn, 'realtime_data')

    info = _columnInfo(rawConn, 'realtime_data', 'data_source')
    assert info is not None
    assert info['notnull'] == 1
    # Existing row gets the default via SQLite's ADD COLUMN semantics.
    existing = rawConn.execute(
        "SELECT data_source FROM realtime_data WHERE parameter_name='RPM'"
    ).fetchone()
    assert existing[0] == 'real'


def test_ensureDataSourceColumn_idempotent(rawConn):
    """Running the migration twice is a no-op."""
    _createPreUs195Table(rawConn)

    ensureDataSourceColumn(rawConn, 'realtime_data')
    ensureDataSourceColumn(rawConn, 'realtime_data')  # second call

    columns = rawConn.execute(
        "PRAGMA table_info(realtime_data)"
    ).fetchall()
    dataSourceColumns = [r for r in columns if r[1] == 'data_source']
    assert len(dataSourceColumns) == 1


def test_initialize_migratesLegacySchema(tmp_path):
    """ObdDatabase.initialize() upgrades a pre-US-195 DB file in place."""
    dbPath = tmp_path / "obd.db"
    # Build a pre-US-195 realtime_data out-of-band.
    conn = sqlite3.connect(str(dbPath))
    _createPreUs195Table(conn)
    conn.close()

    db = ObdDatabase(str(dbPath), walMode=False)
    db.initialize()

    with db.connect() as conn:
        info = _columnInfo(conn, 'realtime_data', 'data_source')

    assert info is not None
