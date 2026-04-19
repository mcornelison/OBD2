################################################################################
# File Name: test_sync_log.py
# Purpose/Description: Outcome-based tests for the Pi sync_log table + delta
#                      query helpers (US-148).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-148
# ================================================================================
################################################################################

"""
Tests for ``src.pi.data.sync_log``.

Covers:
- Schema DDL (idempotent initDb, exact column + constraint shape).
- In-scope / out-of-scope table whitelist (battery_log + power_log excluded;
  unknown / SQL-injection names rejected with ValueError).
- ``getDeltaRows`` paging semantics (id ASC, strictly > lastId, limit).
- ``getHighWaterMark`` / ``updateHighWaterMark`` round-trip, defaults, UPSERT
  insert vs. update paths, atomic single-transaction advance.
- End-to-end integration cycle: seed realtime_data rows -> query delta ->
  advance high-water mark -> seed more rows -> second delta returns only new
  rows -> repeat.

All tests drive an in-memory sqlite3 connection directly so the sync_log
module stays decoupled from ``src.pi.obdii.database.ObdDatabase`` (per the PM
scope on US-148 — sync bookkeeping lives next to, not inside, the OBD DB).
"""

from __future__ import annotations

import sqlite3

import pytest

from src.pi.data import sync_log

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def conn() -> sqlite3.Connection:
    """Fresh in-memory SQLite connection with Row factory + sync_log ready."""
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    sync_log.initDb(c)
    yield c
    c.close()


@pytest.fixture
def connWithRealtime(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Sync_log + a minimal realtime_data table for delta-query tests."""
    conn.execute("""
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def _insertRealtimeRows(conn: sqlite3.Connection, n: int) -> None:
    """Seed N placeholder realtime_data rows (ids auto-increment from the
    current max + 1)."""
    for i in range(n):
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES (?, ?, ?)",
            (f"2026-04-18T00:00:{i:02d}Z", "RPM", 1000.0 + i),
        )
    conn.commit()


# --------------------------------------------------------------------------- #
# Schema + initDb
# --------------------------------------------------------------------------- #

class TestInitDbCreatesSchema:

    def test_initDb_createsSyncLogTable(self) -> None:
        c = sqlite3.connect(':memory:')
        sync_log.initDb(c)
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_log'"
        ).fetchall()
        assert len(rows) == 1

    def test_initDb_columnsMatchSpec(self) -> None:
        c = sqlite3.connect(':memory:')
        sync_log.initDb(c)
        info = {row[1]: row for row in c.execute("PRAGMA table_info(sync_log)")}
        assert set(info.keys()) == {
            'table_name',
            'last_synced_id',
            'last_synced_at',
            'last_batch_id',
            'status',
        }
        # table_name is PRIMARY KEY
        assert info['table_name'][5] == 1  # pk column from PRAGMA
        # last_synced_id is NOT NULL INTEGER
        assert info['last_synced_id'][2].upper() == 'INTEGER'
        assert info['last_synced_id'][3] == 1  # notnull

    def test_initDb_isIdempotent(self) -> None:
        c = sqlite3.connect(':memory:')
        sync_log.initDb(c)
        # Second call must not raise (table already exists).
        sync_log.initDb(c)
        # And must not duplicate the table.
        rows = c.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='sync_log'"
        ).fetchone()
        assert rows[0] == 1

    def test_initDb_idempotentPreservesExistingRows(self) -> None:
        c = sqlite3.connect(':memory:')
        sync_log.initDb(c)
        sync_log.updateHighWaterMark(c, 'realtime_data', 42, 'batch-A')
        sync_log.initDb(c)  # second init must not clobber
        hwm = sync_log.getHighWaterMark(c, 'realtime_data')
        assert hwm[0] == 42
        assert hwm[3] == 'ok'


class TestStatusCheckConstraint:
    """CHECK (status IN ('ok','pending','failed')) — rejects garbage."""

    def test_statusCheck_rejectsInvalidValue(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sync_log (table_name, last_synced_id, status) "
                "VALUES ('realtime_data', 0, 'bogus')"
            )
            conn.commit()


# --------------------------------------------------------------------------- #
# In-scope / out-of-scope whitelist
# --------------------------------------------------------------------------- #

class TestInScopeTables:

    def test_includesSpecifiedPiSyncTables(self) -> None:
        assert 'realtime_data' in sync_log.IN_SCOPE_TABLES
        assert 'statistics' in sync_log.IN_SCOPE_TABLES
        assert 'profiles' in sync_log.IN_SCOPE_TABLES
        assert 'vehicle_info' in sync_log.IN_SCOPE_TABLES
        assert 'ai_recommendations' in sync_log.IN_SCOPE_TABLES
        assert 'connection_log' in sync_log.IN_SCOPE_TABLES
        assert 'alert_log' in sync_log.IN_SCOPE_TABLES
        assert 'calibration_sessions' in sync_log.IN_SCOPE_TABLES

    def test_excludesPiOnlyTables(self) -> None:
        # battery_log and power_log are explicitly Pi-only per the Walk spec.
        assert 'battery_log' not in sync_log.IN_SCOPE_TABLES
        assert 'power_log' not in sync_log.IN_SCOPE_TABLES


# --------------------------------------------------------------------------- #
# getDeltaRows
# --------------------------------------------------------------------------- #

class TestGetDeltaRows:

    def test_lastIdZero_returnsAllRowsOrderedById(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        _insertRealtimeRows(connWithRealtime, 5)
        rows = sync_log.getDeltaRows(connWithRealtime, 'realtime_data', 0, 100)
        assert len(rows) == 5
        ids = [r['id'] for r in rows]
        assert ids == sorted(ids)
        assert ids[0] == 1

    def test_lastIdN_returnsOnlyRowsWithIdGreaterThanN(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        _insertRealtimeRows(connWithRealtime, 5)
        rows = sync_log.getDeltaRows(connWithRealtime, 'realtime_data', 3, 100)
        assert [r['id'] for r in rows] == [4, 5]

    def test_limit_cappsReturnedRowCount(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        _insertRealtimeRows(connWithRealtime, 10)
        rows = sync_log.getDeltaRows(connWithRealtime, 'realtime_data', 0, 3)
        assert len(rows) == 3
        assert [r['id'] for r in rows] == [1, 2, 3]

    def test_noDeltaRows_returnsEmptyList(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        _insertRealtimeRows(connWithRealtime, 5)
        rows = sync_log.getDeltaRows(connWithRealtime, 'realtime_data', 5, 100)
        assert rows == []

    def test_returnsDictLikeRowsWithColumnAccess(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        _insertRealtimeRows(connWithRealtime, 1)
        rows = sync_log.getDeltaRows(connWithRealtime, 'realtime_data', 0, 10)
        assert rows[0]['parameter_name'] == 'RPM'
        assert rows[0]['value'] == 1000.0

    def test_unknownTable_raisesValueError(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        with pytest.raises(ValueError, match='not in sync scope'):
            sync_log.getDeltaRows(connWithRealtime, 'not_a_real_table', 0, 10)

    def test_sqlInjectionAttempt_raisesValueError(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        # Acceptance-criteria literal: must be rejected, never interpolated.
        with pytest.raises(ValueError):
            sync_log.getDeltaRows(
                connWithRealtime,
                'malicious; DROP TABLE realtime_data;--',
                0,
                10,
            )
        # And realtime_data must still be intact.
        count = connWithRealtime.execute(
            "SELECT COUNT(*) FROM realtime_data"
        ).fetchone()[0]
        assert count == 0

    def test_piOnlyTables_raiseValueError(
        self, conn: sqlite3.Connection
    ) -> None:
        # Even if caller knows battery_log exists on the Pi, sync rejects it.
        with pytest.raises(ValueError):
            sync_log.getDeltaRows(conn, 'battery_log', 0, 10)
        with pytest.raises(ValueError):
            sync_log.getDeltaRows(conn, 'power_log', 0, 10)


# --------------------------------------------------------------------------- #
# getHighWaterMark / updateHighWaterMark
# --------------------------------------------------------------------------- #

class TestHighWaterMark:

    def test_getHighWaterMark_missingRow_returnsDefaults(
        self, conn: sqlite3.Connection
    ) -> None:
        hwm = sync_log.getHighWaterMark(conn, 'realtime_data')
        assert hwm == (0, None, None, 'pending')

    def test_updateHighWaterMark_insertsNewRow(
        self, conn: sqlite3.Connection
    ) -> None:
        sync_log.updateHighWaterMark(
            conn, 'realtime_data', 42, 'batch-A', status='ok'
        )
        hwm = sync_log.getHighWaterMark(conn, 'realtime_data')
        assert hwm[0] == 42
        assert hwm[2] == 'batch-A'
        assert hwm[3] == 'ok'
        assert hwm[1] is not None  # last_synced_at set

    def test_updateHighWaterMark_updatesExistingRow(
        self, conn: sqlite3.Connection
    ) -> None:
        sync_log.updateHighWaterMark(conn, 'realtime_data', 10, 'batch-A')
        sync_log.updateHighWaterMark(conn, 'realtime_data', 25, 'batch-B')
        hwm = sync_log.getHighWaterMark(conn, 'realtime_data')
        assert hwm[0] == 25
        assert hwm[2] == 'batch-B'
        # Single row per table (PK enforced).
        count = conn.execute(
            "SELECT COUNT(*) FROM sync_log WHERE table_name='realtime_data'"
        ).fetchone()[0]
        assert count == 1

    def test_updateHighWaterMark_defaultStatusOk(
        self, conn: sqlite3.Connection
    ) -> None:
        sync_log.updateHighWaterMark(conn, 'realtime_data', 1, 'batch-A')
        hwm = sync_log.getHighWaterMark(conn, 'realtime_data')
        assert hwm[3] == 'ok'

    def test_updateHighWaterMark_advancesAllFieldsTogether(
        self, conn: sqlite3.Connection
    ) -> None:
        sync_log.updateHighWaterMark(
            conn, 'realtime_data', 7, 'batch-seven', status='ok'
        )
        row = conn.execute(
            "SELECT last_synced_id, last_synced_at, last_batch_id, status "
            "FROM sync_log WHERE table_name='realtime_data'"
        ).fetchone()
        # All four fields were written atomically.
        assert row[0] == 7
        assert row[1] is not None
        assert row[2] == 'batch-seven'
        assert row[3] == 'ok'

    def test_updateHighWaterMark_rejectsUnknownTable(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(ValueError):
            sync_log.updateHighWaterMark(conn, 'battery_log', 1, 'batch-x')

    def test_updateHighWaterMark_rejectsInvalidStatus(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(ValueError):
            sync_log.updateHighWaterMark(
                conn, 'realtime_data', 1, 'batch-x', status='garbled'
            )

    def test_getHighWaterMark_rejectsUnknownTable(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(ValueError):
            sync_log.getHighWaterMark(conn, 'battery_log')


# --------------------------------------------------------------------------- #
# End-to-end integration cycle (the AC example)
# --------------------------------------------------------------------------- #

class TestIntegrationCycle:

    def test_fullCycle_deltaAdvance_deltaAdvance(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        # Seed 5 rows. Fresh high-water mark = 0.
        _insertRealtimeRows(connWithRealtime, 5)

        hwm = sync_log.getHighWaterMark(connWithRealtime, 'realtime_data')
        assert hwm[0] == 0

        first = sync_log.getDeltaRows(
            connWithRealtime, 'realtime_data', hwm[0], 1000
        )
        assert len(first) == 5
        maxId1 = max(r['id'] for r in first)

        sync_log.updateHighWaterMark(
            connWithRealtime, 'realtime_data', maxId1, 'batch-1'
        )
        assert sync_log.getHighWaterMark(
            connWithRealtime, 'realtime_data'
        )[0] == maxId1

        # Second delta before any new rows: empty.
        assert sync_log.getDeltaRows(
            connWithRealtime, 'realtime_data', maxId1, 1000
        ) == []

        # Seed 3 more rows.
        _insertRealtimeRows(connWithRealtime, 3)
        second = sync_log.getDeltaRows(
            connWithRealtime, 'realtime_data', maxId1, 1000
        )
        assert len(second) == 3
        for row in second:
            assert row['id'] > maxId1

        maxId2 = max(r['id'] for r in second)
        sync_log.updateHighWaterMark(
            connWithRealtime, 'realtime_data', maxId2, 'batch-2'
        )
        assert sync_log.getHighWaterMark(
            connWithRealtime, 'realtime_data'
        )[0] == maxId2
