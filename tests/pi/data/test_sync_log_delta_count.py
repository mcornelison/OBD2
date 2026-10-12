################################################################################
# File Name: test_sync_log_delta_count.py
# Purpose/Description: US-621 -- guards for sync_log.countDeltaRows, the
#                      outstanding-row counter the shutdown custody record is
#                      built on. The load-bearing property is PARITY: the count
#                      must be produced by the SAME delta predicate getDeltaRows
#                      pushes with, so "N rows outstanding" can never disagree
#                      with what a sync would actually send. A count derived by
#                      its own logic is a confident wrong number, which is worse
#                      than no number at all.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-621) | Initial -- countDeltaRows parity + semantics.
# ================================================================================
################################################################################
"""US-621 guards for the sync_log outstanding-row counter."""
from __future__ import annotations

import sqlite3

import pytest

from src.pi.data import sync_log

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Fresh in-memory SQLite connection with sync_log ready."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    sync_log.initDb(c)
    yield c
    c.close()


@pytest.fixture
def connWithRealtime(conn: sqlite3.Connection) -> sqlite3.Connection:
    """sync_log + a minimal realtime_data table (the pk-only legacy cursor)."""
    conn.execute(
        """
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


@pytest.fixture
def connWithPiState(conn: sqlite3.Connection) -> sqlite3.Connection:
    """sync_log + pi_state, an opt-in COMBINED-cursor table (US-315).

    pi_state is in SYNC_UPDATE_TABLES_PK, so once the _sync_modified_at
    migration has run its delta predicate is (pk > lastId OR modified > floor).
    """
    conn.execute(
        """
        CREATE TABLE pi_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            no_new_drives INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    sync_log.ensureSyncModifiedAtSchema(conn)
    return conn


def _insertRealtimeRows(c: sqlite3.Connection, n: int) -> None:
    """Seed N placeholder realtime_data rows."""
    for i in range(n):
        c.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES (?, ?, ?)",
            (f"2026-08-29T00:00:{i:02d}Z", "RPM", 1000.0 + i),
        )
    c.commit()


# --------------------------------------------------------------------------- #
# THE load-bearing guard: count and push must share one predicate
# --------------------------------------------------------------------------- #


class TestCountMatchesWhatAPushWouldSend:
    """countDeltaRows must agree with getDeltaRows, always."""

    @pytest.mark.parametrize("lastId", [0, 1, 7, 41, 42, 100])
    def test_countDeltaRows_matchesGetDeltaRowsAcrossCursorPositions(
        self, connWithRealtime: sqlite3.Connection, lastId: int
    ) -> None:
        """
        Given: 42 unsynced rows and a cursor anywhere in or past the range
        When: the backlog is counted and the same delta is fetched unbounded
        Then: the two agree exactly -- one predicate, two uses
        """
        # Arrange
        _insertRealtimeRows(connWithRealtime, 42)

        # Act
        counted = sync_log.countDeltaRows(
            connWithRealtime, "realtime_data", lastId
        )
        fetched = sync_log.getDeltaRows(
            connWithRealtime, "realtime_data", lastId, limit=10_000
        )

        # Assert
        assert counted == len(fetched)

    def test_countDeltaRows_isNotCappedByTheTransportBatchSize(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        """
        Given: a backlog far larger than the 500-row transport batch size
        When: the outstanding rows are counted
        Then: the FULL backlog is reported, not one batch

        This is the whole point of the story: forcePush() moves at most
        batchSize rows PER TABLE PER CALL, so a count that inherited that cap
        would report "500 outstanding" forever and the operator would never
        learn the real depth of the queue.
        """
        # Arrange
        _insertRealtimeRows(connWithRealtime, 1300)

        # Act
        counted = sync_log.countDeltaRows(connWithRealtime, "realtime_data", 0)

        # Assert
        assert counted == 1300
        # and it exceeds a single batch, which is the property that matters
        assert counted > 500

    def test_countDeltaRows_countsUpdatedRowsOnCombinedCursorTables(
        self, connWithPiState: sqlite3.Connection
    ) -> None:
        """
        Given: an opt-in table whose row was pushed and then UPDATEd
        When: the backlog is counted with the pk cursor already past that row
        Then: the row still counts as outstanding, matching getDeltaRows

        The combined cursor (US-315 / B-065) is what makes an UPDATE to an
        already-pushed row re-sync. A counter that only looked at the pk cursor
        would report an empty queue while real changes waited.
        """
        # Arrange
        connWithPiState.execute("INSERT INTO pi_state (no_new_drives) VALUES (0)")
        connWithPiState.commit()
        connWithPiState.execute("UPDATE pi_state SET no_new_drives = 1 WHERE id = 1")
        connWithPiState.commit()

        # Act -- pk cursor is PAST the row; only the modified cursor can see it
        counted = sync_log.countDeltaRows(
            connWithPiState, "pi_state", 1, lastModifiedAt=None
        )
        fetched = sync_log.getDeltaRows(
            connWithPiState, "pi_state", 1, limit=10_000, lastModifiedAt=None
        )

        # Assert
        assert counted == len(fetched)
        assert counted == 1

    def test_countDeltaRows_emptyQueueIsZeroNotFalsy(
        self, connWithRealtime: sqlite3.Connection
    ) -> None:
        """
        Given: every row already synced
        When: the backlog is counted
        Then: it is exactly 0 -- an explicit "delivered", not an absence
        """
        # Arrange
        _insertRealtimeRows(connWithRealtime, 5)

        # Act
        counted = sync_log.countDeltaRows(connWithRealtime, "realtime_data", 5)

        # Assert
        assert counted == 0


class TestCountDeltaRowsRejectsOutOfScopeTables:
    """The counter inherits the whitelist, so it cannot be an injection seam."""

    def test_countDeltaRows_snapshotTable_raisesValueError(
        self, conn: sqlite3.Connection
    ) -> None:
        """
        Given: a snapshot table, which has no monotonic delta cursor
        When: it is counted
        Then: ValueError -- same refusal getDeltaRows makes
        """
        with pytest.raises(ValueError):
            sync_log.countDeltaRows(conn, "profiles", 0)

    def test_countDeltaRows_unknownTable_raisesValueError(
        self, conn: sqlite3.Connection
    ) -> None:
        """
        Given: a table name outside the whitelist
        When: it is counted
        Then: ValueError before any SQL is composed
        """
        with pytest.raises(ValueError):
            sync_log.countDeltaRows(conn, "realtime_data; DROP TABLE x", 0)
