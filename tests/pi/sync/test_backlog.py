################################################################################
# File Name: test_backlog.py
# Purpose/Description: US-621 -- guards for the sync-backlog reader that the
#                      shutdown custody record is built on. The properties under
#                      test are all about HONESTY: an unreadable table must never
#                      resolve to "delivered", a table that does not exist must
#                      never resolve to "unknown", and the reader must never
#                      raise (it runs on the poweroff path, where a raise is
#                      strictly worse than a missing number).
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-621) | Initial -- backlog reader honesty guards.
# ================================================================================
################################################################################
"""US-621 guards for the pre-poweroff sync-backlog reader."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.pi.data import sync_log
from src.pi.sync.backlog import (
    BACKLOG_DELIVERED,
    BACKLOG_OUTSTANDING,
    BACKLOG_UNKNOWN,
    SyncBacklog,
    countOutstandingRows,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _makeDb(tmp_path: Path, *, rows: int = 0, syncedTo: int = 0) -> str:
    """Build an on-disk Pi DB with realtime_data seeded and a sync_log cursor."""
    dbPath = str(tmp_path / "eclipse.db")
    conn = sqlite3.connect(dbPath)
    sync_log.initDb(conn)
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
    for i in range(rows):
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES (?, ?, ?)",
            (f"2026-08-29T00:00:{i % 60:02d}Z", "RPM", 1000.0 + i),
        )
    if syncedTo:
        sync_log.updateHighWaterMark(
            conn, "realtime_data", syncedTo, "batch-1", "ok"
        )
    conn.commit()
    conn.close()
    return dbPath


# --------------------------------------------------------------------------- #
# The three verdicts, and the lines between them
# --------------------------------------------------------------------------- #


class TestBacklogVerdicts:
    """delivered / outstanding / unknown must never be conflated."""

    def test_countOutstandingRows_emptyQueue_reportsDeliveredExplicitly(
        self, tmp_path: Path
    ) -> None:
        """
        Given: every captured row already synced
        When: the backlog is read at poweroff
        Then: the verdict is DELIVERED, stated positively

        US-621 VC-2: a clean shutdown with an empty queue must SAY SO, so
        "silent" is never ambiguous. An empty result that merely returns zero
        and logs nothing is indistinguishable from a reader that never ran.
        """
        # Arrange
        dbPath = _makeDb(tmp_path, rows=12, syncedTo=12)

        # Act
        backlog = countOutstandingRows(dbPath)

        # Assert
        assert backlog.verdict == BACKLOG_DELIVERED
        assert backlog.total == 0
        assert backlog.isComplete is True

    def test_countOutstandingRows_partiallyDrained_reportsTheRemainder(
        self, tmp_path: Path
    ) -> None:
        """
        Given: 1300 captured rows of which only one 500-row batch got away
        When: the backlog is read at poweroff
        Then: it reports the 800 that did NOT

        This is the observed 2026-08-28 shape in miniature: forcePush moves one
        batch per table per call, so a shutdown right after it returns OK still
        strands the remainder.
        """
        # Arrange
        dbPath = _makeDb(tmp_path, rows=1300, syncedTo=500)

        # Act
        backlog = countOutstandingRows(dbPath)

        # Assert
        assert backlog.verdict == BACKLOG_OUTSTANDING
        assert backlog.total == 800
        assert backlog.perTable["realtime_data"] == 800

    def test_countOutstandingRows_unreadableTable_isUnknownNotDelivered(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a table whose delta cannot be read (sync_log itself is gone)
        When: the backlog is read
        Then: the verdict is UNKNOWN -- never DELIVERED

        The whole defect class this story sits in is a record that reports the
        healthy state when it could not actually observe. Not looking is not
        the same as looking and finding nothing.
        """
        # Arrange -- drop sync_log so the high-water mark cannot be resolved
        dbPath = _makeDb(tmp_path, rows=10)
        conn = sqlite3.connect(dbPath)
        conn.execute("DROP TABLE sync_log")
        conn.commit()
        conn.close()

        # Act
        backlog = countOutstandingRows(dbPath)

        # Assert
        assert backlog.verdict == BACKLOG_UNKNOWN
        assert backlog.isComplete is False
        assert "realtime_data" in backlog.unreadableTables

    def test_countOutstandingRows_absentTable_isZeroNotUnknown(
        self, tmp_path: Path
    ) -> None:
        """
        Given: an in-scope table that this DB has never created
        When: the backlog is read
        Then: it contributes 0 and is NOT counted as unreadable

        A table that does not exist cannot be holding unsynced rows. Calling
        that "unknown" would make every healthy Pi report UNKNOWN forever and
        the signal would be worthless within a week.
        """
        # Arrange -- only realtime_data exists; every other delta table is absent
        dbPath = _makeDb(tmp_path, rows=4, syncedTo=4)

        # Act
        backlog = countOutstandingRows(dbPath)

        # Assert
        assert backlog.unreadableTables == ()
        assert backlog.verdict == BACKLOG_DELIVERED
        assert "connection_log" not in backlog.perTable

    def test_countOutstandingRows_outstandingWinsOverUnknown(
        self, tmp_path: Path
    ) -> None:
        """
        Given: readable rows outstanding AND another table unreadable
        When: the backlog is read
        Then: OUTSTANDING -- the known bad news outranks the unknown

        The total is then a LOWER BOUND, and isComplete says so. Reporting
        UNKNOWN here would bury a measured, actionable row count.
        """
        # Arrange
        dbPath = _makeDb(tmp_path, rows=90, syncedTo=10)
        conn = sqlite3.connect(dbPath)
        conn.execute(
            "CREATE TABLE connection_log (id INTEGER PRIMARY KEY, note TEXT)"
        )
        # A view-shaped break: the column the delta cursor needs is gone.
        conn.execute("DROP TABLE sync_log")
        conn.commit()
        conn.close()

        # Re-create sync_log for realtime_data ONLY, leaving connection_log's
        # own read to fail on the missing pk column.
        conn = sqlite3.connect(dbPath)
        sync_log.initDb(conn)
        sync_log.updateHighWaterMark(
            conn, "realtime_data", 10, "batch-1", "ok"
        )
        conn.execute("DROP TABLE connection_log")
        conn.execute("CREATE TABLE connection_log (nope TEXT)")
        conn.commit()
        conn.close()

        # Act
        backlog = countOutstandingRows(dbPath)

        # Assert
        assert backlog.verdict == BACKLOG_OUTSTANDING
        assert backlog.total == 80
        assert backlog.isComplete is False
        assert "connection_log" in backlog.unreadableTables


class TestBacklogNeverRaises:
    """It runs immediately before poweroff; a raise there is the worst outcome."""

    def test_countOutstandingRows_missingDbFile_returnsUnknownNotRaise(
        self, tmp_path: Path
    ) -> None:
        """
        Given: the database path does not exist
        When: the backlog is read
        Then: UNKNOWN is returned and nothing propagates
        """
        # Act
        backlog = countOutstandingRows(str(tmp_path / "absent.db"))

        # Assert
        assert backlog.verdict == BACKLOG_UNKNOWN
        assert backlog.error is not None

    def test_countOutstandingRows_corruptDb_returnsUnknownNotRaise(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a file that is not a SQLite database at all
        When: the backlog is read
        Then: UNKNOWN is returned and nothing propagates
        """
        # Arrange
        junk = tmp_path / "junk.db"
        junk.write_bytes(b"this is definitely not sqlite" * 64)

        # Act
        backlog = countOutstandingRows(str(junk))

        # Assert
        assert backlog.verdict == BACKLOG_UNKNOWN

    def test_countOutstandingRows_emptyDbPath_returnsUnknownNotRaise(self) -> None:
        """
        Given: no configured database path
        When: the backlog is read
        Then: UNKNOWN -- no path is ever guessed
        """
        # Act
        backlog = countOutstandingRows("")

        # Assert
        assert backlog.verdict == BACKLOG_UNKNOWN


class TestBacklogIsReadOnly:
    """A shutdown-path reader must not write to the database it inspects."""

    def test_countOutstandingRows_doesNotCreateOrMutateTables(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a DB with no sync_log at all
        When: the backlog is read
        Then: the reader does NOT initialise or otherwise write the schema

        Convenience-initialising here would mean the poweroff path writes to a
        database it was only asked to look at, on a Pi that is losing power.
        """
        # Arrange
        dbPath = str(tmp_path / "bare.db")
        conn = sqlite3.connect(dbPath)
        conn.execute("CREATE TABLE realtime_data (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        # Act
        countOutstandingRows(dbPath)

        # Assert
        conn = sqlite3.connect(dbPath)
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        assert "sync_log" not in names


class TestSyncBacklogSummary:
    """The one-line summary is what reaches the journal, so pin its content."""

    def test_describe_outstandingCarriesTheCountAndTheWorstTable(self) -> None:
        """
        Given: an outstanding backlog across two tables
        When: it is described for the operator
        Then: the total and the per-table detail are both present
        """
        # Arrange
        backlog = SyncBacklog(
            perTable={"realtime_data": 14500, "power_log": 3},
            unreadableTables=(),
            error=None,
        )

        # Act
        text = backlog.describe()

        # Assert
        assert "14503" in text
        assert "realtime_data=14500" in text

    def test_describe_deliveredSaysSoRatherThanReportingZero(self) -> None:
        """
        Given: an empty, fully-readable queue
        When: it is described
        Then: the text states delivery positively
        """
        # Arrange
        backlog = SyncBacklog(
            perTable={"realtime_data": 0}, unreadableTables=(), error=None
        )

        # Act
        text = backlog.describe()

        # Assert
        assert BACKLOG_DELIVERED in text

    def test_describe_unknownNamesWhatCouldNotBeRead(self) -> None:
        """
        Given: a table that could not be read
        When: the backlog is described
        Then: the unreadable table is named, so the gap is diagnosable
        """
        # Arrange
        backlog = SyncBacklog(
            perTable={}, unreadableTables=("power_log",), error="locked"
        )

        # Act
        text = backlog.describe()

        # Assert
        assert BACKLOG_UNKNOWN in text
        assert "power_log" in text


@pytest.mark.parametrize(
    ("perTable", "unreadable", "expected"),
    [
        ({}, (), BACKLOG_DELIVERED),
        ({"realtime_data": 0}, (), BACKLOG_DELIVERED),
        ({"realtime_data": 1}, (), BACKLOG_OUTSTANDING),
        ({"realtime_data": 0}, ("power_log",), BACKLOG_UNKNOWN),
        ({"realtime_data": 5}, ("power_log",), BACKLOG_OUTSTANDING),
        ({}, ("power_log",), BACKLOG_UNKNOWN),
    ],
)
def test_verdict_truthTable(
    perTable: dict[str, int], unreadable: tuple[str, ...], expected: str
) -> None:
    """
    Given: every combination of readable counts and unreadable tables
    When: the verdict is resolved
    Then: it follows the stated precedence -- outstanding > unknown > delivered
    """
    backlog = SyncBacklog(
        perTable=perTable, unreadableTables=unreadable, error=None
    )
    assert backlog.verdict == expected
