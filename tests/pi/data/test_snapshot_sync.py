################################################################################
# File Name: test_snapshot_sync.py
# Purpose/Description: Pi-side tests for the natural-key SNAPSHOT_SYNC reader +
#                      cursor (US-416 / F-101): the last_snapshot_cursor migration,
#                      getSnapshotRows delta-by-cursorCol, cursor advance/no-rewind,
#                      and the whitelist guard. Uses a throwaway registered table.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-416) | Initial -- Pi snapshot reader + cursor tests.
# ================================================================================
################################################################################

"""Pi snapshot-sync reader/cursor tests (US-416)."""

from __future__ import annotations

import sqlite3

import pytest

from src.common.sync.snapshot_registry import SNAPSHOT_SYNC, SnapshotSyncSpec
from src.pi.data import sync_log

_TABLE = "test_startup_snap"


@pytest.fixture
def conn() -> sqlite3.Connection:
    """In-memory SQLite with the test snapshot table + a registered spec."""
    SNAPSHOT_SYNC[_TABLE] = SnapshotSyncSpec(
        naturalKeyCols=("boot_id",), cursorCol="recorded_at",
    )
    connection = sqlite3.connect(":memory:")
    connection.execute(
        f"CREATE TABLE {_TABLE} ("
        "  boot_id      TEXT PRIMARY KEY,"
        "  recorded_at  TEXT NOT NULL,"
        "  boot_reason  TEXT"
        ")",
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()
        SNAPSHOT_SYNC.pop(_TABLE, None)


def _seed(connection: sqlite3.Connection, bootId: str, recordedAt: str) -> None:
    connection.execute(
        f"INSERT INTO {_TABLE} (boot_id, recorded_at, boot_reason) VALUES (?, ?, ?)",
        (bootId, recordedAt, "power_on"),
    )
    connection.commit()


class TestEnsureSnapshotSyncSchema:
    """The last_snapshot_cursor column migration is idempotent."""

    def test_freshDbHasColumn(self, conn: sqlite3.Connection) -> None:
        sync_log.initDb(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_log)")}
        assert sync_log.SNAPSHOT_SYNC_CURSOR_COLUMN in cols

    def test_migratesLegacyDb(self, conn: sqlite3.Connection) -> None:
        # Build a pre-US-416 sync_log WITHOUT the snapshot cursor column.
        conn.execute(
            "CREATE TABLE sync_log ("
            "  table_name TEXT PRIMARY KEY,"
            "  last_synced_id INTEGER NOT NULL DEFAULT 0"
            ")",
        )
        conn.commit()
        assert sync_log.ensureSnapshotSyncSchema(conn) is True
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_log)")}
        assert sync_log.SNAPSHOT_SYNC_CURSOR_COLUMN in cols
        # Second call is a no-op.
        assert sync_log.ensureSnapshotSyncSchema(conn) is False


class TestGetSnapshotCursor:
    def test_noneBeforeFirstSync(self, conn: sqlite3.Connection) -> None:
        sync_log.initDb(conn)
        assert sync_log.getSnapshotCursor(conn, _TABLE) is None

    def test_returnsStoredCursor(self, conn: sqlite3.Connection) -> None:
        sync_log.initDb(conn)
        sync_log.updateSnapshotCursor(
            conn, _TABLE, "2026-07-01T10:00:00Z", "batch-1",
        )
        assert sync_log.getSnapshotCursor(conn, _TABLE) == "2026-07-01T10:00:00Z"

    def test_unregisteredTableRaises(self, conn: sqlite3.Connection) -> None:
        sync_log.initDb(conn)
        with pytest.raises(ValueError, match="not registered for snapshot sync"):
            sync_log.getSnapshotCursor(conn, "no_such_table")


class TestGetSnapshotRows:
    def test_returnsAllWhenCursorNone(self, conn: sqlite3.Connection) -> None:
        _seed(conn, "b1", "2026-07-01T10:00:00Z")
        _seed(conn, "b2", "2026-07-01T11:00:00Z")
        rows = sync_log.getSnapshotRows(conn, _TABLE, None, 100)
        assert [r["boot_id"] for r in rows] == ["b1", "b2"]

    def test_orderedByCursorAscending(self, conn: sqlite3.Connection) -> None:
        # Insert out of chronological order; expect chronological output.
        _seed(conn, "late", "2026-07-01T12:00:00Z")
        _seed(conn, "early", "2026-07-01T09:00:00Z")
        rows = sync_log.getSnapshotRows(conn, _TABLE, None, 100)
        assert [r["boot_id"] for r in rows] == ["early", "late"]

    def test_cursorBoundsVolume(self, conn: sqlite3.Connection) -> None:
        """Only rows strictly after the cursor are returned (cursor bounds volume)."""
        _seed(conn, "b1", "2026-07-01T10:00:00Z")
        _seed(conn, "b2", "2026-07-01T11:00:00Z")
        _seed(conn, "b3", "2026-07-01T12:00:00Z")
        rows = sync_log.getSnapshotRows(
            conn, _TABLE, "2026-07-01T11:00:00Z", 100,
        )
        assert [r["boot_id"] for r in rows] == ["b3"]

    def test_limitCaps(self, conn: sqlite3.Connection) -> None:
        _seed(conn, "b1", "2026-07-01T10:00:00Z")
        _seed(conn, "b2", "2026-07-01T11:00:00Z")
        rows = sync_log.getSnapshotRows(conn, _TABLE, None, 1)
        assert len(rows) == 1
        assert rows[0]["boot_id"] == "b1"

    def test_unregisteredTableRaises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="not registered for snapshot sync"):
            sync_log.getSnapshotRows(conn, "no_such_table", None, 100)


class TestUpdateSnapshotCursor:
    def test_advancesCursor(self, conn: sqlite3.Connection) -> None:
        sync_log.initDb(conn)
        sync_log.updateSnapshotCursor(conn, _TABLE, "2026-07-01T10:00:00Z", "b1")
        sync_log.updateSnapshotCursor(conn, _TABLE, "2026-07-01T12:00:00Z", "b2")
        assert sync_log.getSnapshotCursor(conn, _TABLE) == "2026-07-01T12:00:00Z"

    def test_neverRewinds(self, conn: sqlite3.Connection) -> None:
        """A stale/earlier cursor must not roll the high-water mark backward."""
        sync_log.initDb(conn)
        sync_log.updateSnapshotCursor(conn, _TABLE, "2026-07-01T12:00:00Z", "b1")
        sync_log.updateSnapshotCursor(conn, _TABLE, "2026-07-01T09:00:00Z", "b2")
        assert sync_log.getSnapshotCursor(conn, _TABLE) == "2026-07-01T12:00:00Z"

    def test_invalidStatusRaises(self, conn: sqlite3.Connection) -> None:
        sync_log.initDb(conn)
        with pytest.raises(ValueError, match="status"):
            sync_log.updateSnapshotCursor(
                conn, _TABLE, "2026-07-01T10:00:00Z", "b1", status="bogus",
            )
