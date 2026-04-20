################################################################################
# File Name: test_sync_log_pk_variants.py
# Purpose/Description: Tests for per-table primary-key registry in
#                      src.pi.data.sync_log (TD-025 + TD-026 / US-194).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | US-194 -- cover TEXT PK (profiles),
#               |              | INTEGER non-id PK (calibration_sessions),
#               |              | TEXT natural PK (vehicle_info) + missing
#               |              | column error surfaces
# ================================================================================
################################################################################

"""
Regression coverage for the sync_log per-table PK registry (US-194).

Session 23 milestone push uncovered that ``getDeltaRows`` hardcoded
``WHERE id > ?`` and wrapped ``int(lastId)``.  Three tables break that
assumption:

1. ``calibration_sessions`` -- integer PK named ``session_id`` (not ``id``)
2. ``profiles`` -- TEXT PK with values like ``'daily'`` / ``'performance'``
3. ``vehicle_info`` -- TEXT PK ``vin``

After US-194, the module exposes:

- :data:`sync_log.PK_COLUMN` -- ``dict[tableName, pkColumn]`` for every
  delta-eligible (append-only) table
- :data:`sync_log.DELTA_SYNC_TABLES` -- ``frozenset`` of append-only tables
- :data:`sync_log.SNAPSHOT_TABLES` -- ``frozenset`` of upsert/static tables
  that are explicitly excluded from the delta-by-PK path
- :data:`sync_log.IN_SCOPE_TABLES` -- preserved as the union (BC for the
  server-payload whitelist and seed_pi_fixture harness)

These tests drive the module directly with an in-memory sqlite3 connection
that mirrors the *production* schema (natural PKs preserved), unlike the
fixture-style stubs in ``tests/pi/sync/test_sync_client.py`` which gave every
table an ``id INTEGER`` primary key and therefore could not see this class
of bug.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.pi.data import sync_log

# --------------------------------------------------------------------------- #
# Constants / expected mappings (authoritative from production schema)
# --------------------------------------------------------------------------- #

# Tables that are append-only (event streams).  All have an integer PK,
# though two do not name that PK ``id``.
EXPECTED_PK_COLUMN: dict[str, str] = {
    'realtime_data':       'id',
    'statistics':          'id',
    'ai_recommendations':  'id',
    'connection_log':      'id',
    'alert_log':           'id',
    'calibration_sessions': 'session_id',
}

# Tables excluded from delta-by-PK sync.  These are upsert/snapshot style --
# delta-by-PK is semantically meaningless for them.
EXPECTED_SNAPSHOT_TABLES: frozenset[str] = frozenset({
    'profiles',
    'vehicle_info',
})

# Everything the server whitelist accepts (preserved for BC).
EXPECTED_IN_SCOPE: frozenset[str] = (
    frozenset(EXPECTED_PK_COLUMN.keys()) | EXPECTED_SNAPSHOT_TABLES
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def conn() -> sqlite3.Connection:
    """Empty in-memory connection with sync_log initialized."""
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    sync_log.initDb(c)
    yield c
    c.close()


@pytest.fixture
def connWithCalibrationSessions(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Connection with calibration_sessions at production PK shape.

    Mirrors ``src/pi/obdii/database_schema.py::SCHEMA_CALIBRATION_SESSIONS``:
    the PK is ``session_id INTEGER PRIMARY KEY AUTOINCREMENT`` -- NOT ``id``.
    """
    conn.execute("""
        CREATE TABLE calibration_sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            notes TEXT,
            profile_id TEXT,
            data_source TEXT NOT NULL DEFAULT 'real'
        )
    """)
    conn.commit()
    return conn


@pytest.fixture
def connWithProfiles(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Connection with profiles at production PK shape (``id TEXT PK``)."""
    conn.execute("""
        CREATE TABLE profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            polling_interval_ms INTEGER DEFAULT 1000,
            data_source TEXT NOT NULL DEFAULT 'real'
        )
    """)
    conn.execute(
        "INSERT INTO profiles (id, name) VALUES (?, ?)",
        ('daily', 'Daily Driving'),
    )
    conn.execute(
        "INSERT INTO profiles (id, name) VALUES (?, ?)",
        ('performance', 'Performance'),
    )
    conn.commit()
    return conn


@pytest.fixture
def connWithVehicleInfo(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Connection with vehicle_info at production PK shape (``vin TEXT PK``)."""
    conn.execute("""
        CREATE TABLE vehicle_info (
            vin TEXT PRIMARY KEY,
            make TEXT,
            model TEXT,
            year INTEGER
        )
    """)
    conn.execute(
        "INSERT INTO vehicle_info (vin, make, model, year) "
        "VALUES (?, ?, ?, ?)",
        ('4A3AK34Y2WE046123', 'Mitsubishi', 'Eclipse', 1998),
    )
    conn.commit()
    return conn


def _insertCalibrationRows(conn: sqlite3.Connection, n: int) -> None:
    for i in range(n):
        conn.execute(
            "INSERT INTO calibration_sessions (start_time, notes) "
            "VALUES (?, ?)",
            (f"2026-04-19T12:00:{i:02d}Z", f"session-{i}"),
        )
    conn.commit()


# --------------------------------------------------------------------------- #
# Registry shape
# --------------------------------------------------------------------------- #


class TestPkColumnRegistry:
    """PK_COLUMN must cover every append-only (delta-eligible) table."""

    def test_PK_COLUMN_exists_as_dict(self) -> None:
        assert isinstance(sync_log.PK_COLUMN, dict)

    def test_PK_COLUMN_matches_expected_mapping(self) -> None:
        """Every delta-eligible table maps to its production PK column."""
        assert sync_log.PK_COLUMN == EXPECTED_PK_COLUMN

    def test_PK_COLUMN_calibration_sessions_uses_session_id(self) -> None:
        """TD-025 core: calibration_sessions PK is session_id, NOT id."""
        assert sync_log.PK_COLUMN['calibration_sessions'] == 'session_id'

    def test_PK_COLUMN_standard_tables_use_id(self) -> None:
        """All five append-only tables with id INTEGER PK keep 'id'."""
        for table in (
            'realtime_data',
            'statistics',
            'ai_recommendations',
            'connection_log',
            'alert_log',
        ):
            assert sync_log.PK_COLUMN[table] == 'id'

    def test_PK_COLUMN_excludes_snapshot_tables(self) -> None:
        """Snapshot tables must NOT be in the PK registry."""
        assert 'profiles' not in sync_log.PK_COLUMN
        assert 'vehicle_info' not in sync_log.PK_COLUMN


class TestDeltaSyncTables:
    """DELTA_SYNC_TABLES is the keyset of PK_COLUMN -- no drift allowed."""

    def test_DELTA_SYNC_TABLES_matches_PK_COLUMN_keys(self) -> None:
        assert sync_log.DELTA_SYNC_TABLES == frozenset(
            sync_log.PK_COLUMN.keys()
        )

    def test_DELTA_SYNC_TABLES_has_six_entries(self) -> None:
        """Crystalize the expected count so additions are deliberate."""
        assert len(sync_log.DELTA_SYNC_TABLES) == 6

    def test_DELTA_SYNC_TABLES_excludes_profiles(self) -> None:
        assert 'profiles' not in sync_log.DELTA_SYNC_TABLES

    def test_DELTA_SYNC_TABLES_excludes_vehicle_info(self) -> None:
        assert 'vehicle_info' not in sync_log.DELTA_SYNC_TABLES


class TestSnapshotTables:
    """SNAPSHOT_TABLES names the upsert/static tables excluded from delta."""

    def test_SNAPSHOT_TABLES_matches_expected(self) -> None:
        assert sync_log.SNAPSHOT_TABLES == EXPECTED_SNAPSHOT_TABLES

    def test_SNAPSHOT_TABLES_and_DELTA_SYNC_TABLES_are_disjoint(self) -> None:
        overlap = sync_log.SNAPSHOT_TABLES & sync_log.DELTA_SYNC_TABLES
        assert overlap == frozenset()


class TestInScopeTablesBackCompat:
    """IN_SCOPE_TABLES stays the union (preserves the server whitelist)."""

    def test_IN_SCOPE_TABLES_equals_union_of_delta_and_snapshot(self) -> None:
        assert sync_log.IN_SCOPE_TABLES == (
            sync_log.DELTA_SYNC_TABLES | sync_log.SNAPSHOT_TABLES
        )

    def test_IN_SCOPE_TABLES_unchanged_content(self) -> None:
        """All eight historical tables still in-scope (BC for seed + server)."""
        assert sync_log.IN_SCOPE_TABLES == EXPECTED_IN_SCOPE


# --------------------------------------------------------------------------- #
# getDeltaRows semantics -- integer non-id PK (TD-025 core bug)
# --------------------------------------------------------------------------- #


class TestGetDeltaRowsIntegerNonIdPk:
    """calibration_sessions: PK is session_id, not id."""

    def test_getDeltaRows_queries_session_id_column(
        self, connWithCalibrationSessions: sqlite3.Connection,
    ) -> None:
        """Queries use session_id as the delta cursor -- no 'no such column: id'."""
        _insertCalibrationRows(connWithCalibrationSessions, n=3)
        rows = sync_log.getDeltaRows(
            connWithCalibrationSessions,
            'calibration_sessions',
            lastId=0,
            limit=100,
        )
        assert len(rows) == 3
        # session_id column MUST be present (SELECT *).
        assert all('session_id' in row for row in rows)

    def test_getDeltaRows_orders_by_session_id_ascending(
        self, connWithCalibrationSessions: sqlite3.Connection,
    ) -> None:
        _insertCalibrationRows(connWithCalibrationSessions, n=5)
        rows = sync_log.getDeltaRows(
            connWithCalibrationSessions,
            'calibration_sessions',
            lastId=0,
            limit=100,
        )
        sessionIds = [row['session_id'] for row in rows]
        assert sessionIds == sorted(sessionIds)

    def test_getDeltaRows_respects_lastId_boundary_on_session_id(
        self, connWithCalibrationSessions: sqlite3.Connection,
    ) -> None:
        _insertCalibrationRows(connWithCalibrationSessions, n=5)
        rows = sync_log.getDeltaRows(
            connWithCalibrationSessions,
            'calibration_sessions',
            lastId=2,
            limit=100,
        )
        assert [row['session_id'] for row in rows] == [3, 4, 5]

    def test_getDeltaRows_respects_limit(
        self, connWithCalibrationSessions: sqlite3.Connection,
    ) -> None:
        _insertCalibrationRows(connWithCalibrationSessions, n=10)
        rows = sync_log.getDeltaRows(
            connWithCalibrationSessions,
            'calibration_sessions',
            lastId=0,
            limit=3,
        )
        assert len(rows) == 3
        assert [row['session_id'] for row in rows] == [1, 2, 3]


# --------------------------------------------------------------------------- #
# getDeltaRows -- snapshot tables (TEXT PK) are rejected, not crashed
# --------------------------------------------------------------------------- #


class TestGetDeltaRowsSnapshotTablesRejected:
    """profiles + vehicle_info raise a clear ValueError, never cast 'daily'."""

    def test_getDeltaRows_profiles_raises_ValueError(
        self, connWithProfiles: sqlite3.Connection,
    ) -> None:
        """TD-026 regression: no ``int('daily')`` explosion.

        Snapshot tables are not delta-syncable.  Attempting it surfaces as
        a clear ValueError rather than a ValueError buried inside an int()
        cast on 'daily' / 'performance'.
        """
        with pytest.raises(ValueError, match="not delta-syncable|not in delta"):
            sync_log.getDeltaRows(
                connWithProfiles, 'profiles', lastId=0, limit=100,
            )

    def test_getDeltaRows_vehicle_info_raises_ValueError(
        self, connWithVehicleInfo: sqlite3.Connection,
    ) -> None:
        """TD-025 regression: vin TEXT PK never hits the delta query."""
        with pytest.raises(ValueError, match="not delta-syncable|not in delta"):
            sync_log.getDeltaRows(
                connWithVehicleInfo, 'vehicle_info', lastId=0, limit=100,
            )

    def test_getDeltaRows_profiles_error_mentions_table_name(
        self, connWithProfiles: sqlite3.Connection,
    ) -> None:
        """Error message is debuggable -- includes the offending table name."""
        with pytest.raises(ValueError) as exc:
            sync_log.getDeltaRows(
                connWithProfiles, 'profiles', lastId=0, limit=100,
            )
        assert 'profiles' in str(exc.value)


# --------------------------------------------------------------------------- #
# getDeltaRows -- standard id INTEGER PK still works (regression guard)
# --------------------------------------------------------------------------- #


class TestGetDeltaRowsStandardIdPkStillWorks:
    """realtime_data and peers must not regress from this fix."""

    @pytest.fixture
    def connWithRealtime(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        conn.execute("""
            CREATE TABLE realtime_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                parameter_name TEXT NOT NULL,
                value REAL NOT NULL
            )
        """)
        conn.commit()
        for i in range(3):
            conn.execute(
                "INSERT INTO realtime_data "
                "(timestamp, parameter_name, value) "
                "VALUES (?, ?, ?)",
                (f"2026-04-19T00:00:{i:02d}Z", "RPM", 1000.0 + i),
            )
        conn.commit()
        return conn

    def test_getDeltaRows_realtime_data_uses_id(
        self, connWithRealtime: sqlite3.Connection,
    ) -> None:
        rows = sync_log.getDeltaRows(
            connWithRealtime, 'realtime_data', lastId=0, limit=100,
        )
        assert len(rows) == 3
        assert [row['id'] for row in rows] == [1, 2, 3]

    def test_getDeltaRows_realtime_data_respects_lastId(
        self, connWithRealtime: sqlite3.Connection,
    ) -> None:
        rows = sync_log.getDeltaRows(
            connWithRealtime, 'realtime_data', lastId=1, limit=100,
        )
        assert [row['id'] for row in rows] == [2, 3]


# --------------------------------------------------------------------------- #
# Unknown tables -- whitelist guard unchanged (BC invariant)
# --------------------------------------------------------------------------- #


class TestUnknownTableRejected:
    """Unknown / injection table names still raise the whitelist ValueError."""

    def test_getDeltaRows_unknown_table_raises_ValueError(
        self, conn: sqlite3.Connection,
    ) -> None:
        with pytest.raises(ValueError):
            sync_log.getDeltaRows(
                conn, 'users; DROP TABLE profiles; --', lastId=0, limit=100,
            )

    def test_getDeltaRows_battery_log_still_out_of_scope(
        self, conn: sqlite3.Connection,
    ) -> None:
        """battery_log is local-only health telemetry -- must stay excluded."""
        with pytest.raises(ValueError):
            sync_log.getDeltaRows(
                conn, 'battery_log', lastId=0, limit=100,
            )
