################################################################################
# File Name: test_edr_sync_registration.py
# Purpose/Description: US-766 (F-142) -- EDR rows sync like any other table
#                      while staying OUT of the power-loss shutdown drain.
#                      Guards the one-line registration, the exclude/only
#                      parameters, and the property the whole story turns on:
#                      the main sync-custody verdict must be byte-identical
#                      with and without an EDR backlog outstanding.
# Author: Atlas (Architect)
# Creation Date: 2026-09-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-16    | Atlas        | Initial -- CIO-directed build (charter s2
#               |              | override recorded in board/wip/ARCH-029.md).
# ================================================================================
################################################################################

"""US-766 guards: EDR syncs normally, and never rides the shutdown drain.

The asymmetry this file exists to protect
-----------------------------------------

The power-loss drain budget is measured in SECONDS.  The EDR backlog was
measured at **15.16 million rows** on 2026-09-16 and grows ~1.77M/day.  Those
two facts cannot share a code path.

But the fix must not be "make the drain ignore EDR and call it done", because
sync custody (US-621) answers a question people rely on: *did the safety-critical
data get away before the Pi died?*  If an unbounded archival backlog were folded
into that verdict, every healthy shutdown would report OUTSTANDING forever -- and
a verdict that always fails is a verdict nobody reads.  So EDR is reported, on
its own line, beside a verdict that does not move.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.common.edr.sync_contract import (
    EDR_SYNC_TABLES,
    SHUTDOWN_DRAIN_EXCLUDED_TABLES,
)
from src.pi.data import sync_log
from src.pi.power.power_watch.sync_custody import buildCustodyRecord
from src.pi.sync.backlog import (
    BACKLOG_DELIVERED,
    BACKLOG_OUTSTANDING,
    countOutstandingRows,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _makeDb(
    tmp_path: Path,
    *,
    realtimeRows: int = 0,
    realtimeSynced: int = 0,
    edrRows: int = 0,
    edrSynced: int = 0,
) -> str:
    """Build a Pi DB carrying both an ordinary capture table and EDR."""
    # Callers pass a SUBDIRECTORY when they need two independent databases in
    # one test; sqlite3.connect creates the file but never the directory.
    tmp_path.mkdir(parents=True, exist_ok=True)
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
    conn.execute(
        """
        CREATE TABLE edr_imu_sample (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            ts_capture REAL NOT NULL,
            seq INTEGER NOT NULL,
            accel_x REAL, accel_y REAL, accel_z REAL,
            gyro_x REAL, gyro_y REAL, gyro_z REAL,
            mag_x REAL, mag_y REAL, mag_z REAL,
            temp_c REAL,
            drive_id INTEGER,
            data_source TEXT NOT NULL,
            schema_version INTEGER NOT NULL
        )
        """
    )
    for i in range(realtimeRows):
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES (?, ?, ?)",
            (f"2026-09-16T00:00:{i % 60:02d}Z", "RPM", 1000.0 + i),
        )
    for i in range(edrRows):
        conn.execute(
            "INSERT INTO edr_imu_sample "
            "(ts_utc, ts_capture, seq, data_source, schema_version) "
            "VALUES (?, ?, ?, 'real', 1)",
            (f"2026-09-16T00:00:{i % 60:02d}Z", float(i), i),
        )
    if realtimeSynced:
        sync_log.updateHighWaterMark(
            conn, "realtime_data", realtimeSynced, "batch-1", "ok"
        )
    if edrSynced:
        sync_log.updateHighWaterMark(
            conn, "edr_imu_sample", edrSynced, "batch-1", "ok"
        )
    conn.commit()
    conn.close()
    return dbPath


# --------------------------------------------------------------------------- #
# Registration -- one line, both paths
# --------------------------------------------------------------------------- #


class TestRegistration:
    """A single PK_COLUMN entry must reach both sweeps."""

    def test_edrIsDeltaSyncable(self) -> None:
        for table in EDR_SYNC_TABLES:
            assert sync_log.PK_COLUMN[table] == "id"
            assert table in sync_log.DELTA_SYNC_TABLES

    def test_edrIsInScopeForPushAllDeltas(self) -> None:
        """pushAllDeltas walks IN_SCOPE_TABLES, not DELTA_SYNC_TABLES."""
        for table in EDR_SYNC_TABLES:
            assert table in sync_log.IN_SCOPE_TABLES

    def test_edrIsInsertOnly(self) -> None:
        """Append-only: no modified_at cursor, so no UPDATE trigger.

        An opt-in here would put an AFTER UPDATE trigger on a table taking
        ~1.77M rows/day to propagate updates that never happen.
        """
        for table in EDR_SYNC_TABLES:
            assert table not in sync_log.SYNC_UPDATE_TABLES_PK

    def test_everyEdrTableIsDrainExcluded(self) -> None:
        assert set(EDR_SYNC_TABLES) <= SHUTDOWN_DRAIN_EXCLUDED_TABLES


# --------------------------------------------------------------------------- #
# Backlog counting: exclude / only
# --------------------------------------------------------------------------- #


class TestBacklogFiltering:
    """The counter must be able to answer two different questions."""

    def test_unfilteredCountsEverything(self, tmp_path: Path) -> None:
        dbPath = _makeDb(tmp_path, realtimeRows=10, edrRows=40)
        backlog = countOutstandingRows(dbPath)
        assert backlog.perTable["realtime_data"] == 10
        assert backlog.perTable["edr_imu_sample"] == 40

    def test_excludeDropsEdrEntirely(self, tmp_path: Path) -> None:
        dbPath = _makeDb(tmp_path, realtimeRows=10, edrRows=40)
        backlog = countOutstandingRows(
            dbPath, excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES
        )
        assert backlog.perTable == {"realtime_data": 10}
        assert backlog.total == 10

    def test_excludedTableIsNotReportedUnreadable(self, tmp_path: Path) -> None:
        """Excluded is not the same as unreadable.

        Folding a deliberate exclusion into unreadableTables would flip the
        verdict to UNKNOWN and make every shutdown look uncertain.
        """
        dbPath = _makeDb(tmp_path, realtimeRows=10, edrRows=40)
        backlog = countOutstandingRows(
            dbPath, excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES
        )
        assert backlog.unreadableTables == ()
        assert backlog.isComplete is True

    def test_onlyTablesCountsJustEdr(self, tmp_path: Path) -> None:
        dbPath = _makeDb(tmp_path, realtimeRows=10, edrRows=40)
        backlog = countOutstandingRows(dbPath, onlyTables=EDR_SYNC_TABLES)
        assert backlog.perTable == {"edr_imu_sample": 40}
        assert backlog.total == 40

    def test_onlyTablesRespectsTheSyncCursor(self, tmp_path: Path) -> None:
        dbPath = _makeDb(tmp_path, edrRows=40, edrSynced=25)
        backlog = countOutstandingRows(dbPath, onlyTables=EDR_SYNC_TABLES)
        assert backlog.total == 15


# --------------------------------------------------------------------------- #
# THE load-bearing property: the custody verdict does not move
# --------------------------------------------------------------------------- #


class TestCustodyVerdictIsUnaffectedByEdr:
    """A huge EDR backlog must not make a clean shutdown look dirty."""

    def test_verdictIsDeliveredDespiteEdrBacklog(self, tmp_path: Path) -> None:
        dbPath = _makeDb(
            tmp_path, realtimeRows=10, realtimeSynced=10, edrRows=5_000
        )
        drain = countOutstandingRows(
            dbPath, excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES
        )
        assert drain.verdict == BACKLOG_DELIVERED

    def test_realBacklogStillReportsOutstanding(self, tmp_path: Path) -> None:
        """The exclusion must not blind the verdict to real stranded rows."""
        dbPath = _makeDb(
            tmp_path, realtimeRows=1300, realtimeSynced=500, edrRows=5_000
        )
        drain = countOutstandingRows(
            dbPath, excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES
        )
        assert drain.verdict == BACKLOG_OUTSTANDING
        assert drain.total == 800

    def test_custodyRecordIsByteIdenticalWithAndWithoutEdr(
        self, tmp_path: Path
    ) -> None:
        """The acceptance clause, stated exactly.

        Same non-EDR state, wildly different EDR state -> the custody record's
        verdict half must not differ by a single byte.
        """
        noEdr = _makeDb(tmp_path / "a", realtimeRows=10, realtimeSynced=10)
        withEdr = _makeDb(
            tmp_path / "b", realtimeRows=10, realtimeSynced=10, edrRows=9_999
        )

        recordA = buildCustodyRecord(
            countOutstandingRows(
                noEdr, excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES
            ),
            nowIso="2026-09-16T00:00:00Z",
        )
        recordB = buildCustodyRecord(
            countOutstandingRows(
                withEdr, excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES
            ),
            nowIso="2026-09-16T00:00:00Z",
        )
        assert recordA == recordB

    def test_custodyRecordCarriesEdrCountSeparately(
        self, tmp_path: Path
    ) -> None:
        """Reported, but never mixed into the verdict."""
        dbPath = _makeDb(
            tmp_path, realtimeRows=10, realtimeSynced=10, edrRows=9_999
        )
        record = buildCustodyRecord(
            countOutstandingRows(
                dbPath, excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES
            ),
            nowIso="2026-09-16T00:00:00Z",
            edrBacklog=countOutstandingRows(dbPath, onlyTables=EDR_SYNC_TABLES),
        )
        assert record["verdict"] == BACKLOG_DELIVERED
        assert record["outstandingRows"] == 0
        assert record["edrOutstandingRows"] == 9_999
        # The EDR count must not leak into the verdict's own evidence.
        assert "edr_imu_sample" not in record["perTable"]

    def test_edrCountAbsentWhenNotSupplied(self, tmp_path: Path) -> None:
        """Back-compat: an omitted EDR reader reports a typed absence, not 0.

        Zero would claim the EDR queue was measured and found empty.
        """
        dbPath = _makeDb(tmp_path, realtimeRows=10, realtimeSynced=10)
        record = buildCustodyRecord(
            countOutstandingRows(dbPath), nowIso="2026-09-16T00:00:00Z"
        )
        assert record["edrOutstandingRows"] is None
