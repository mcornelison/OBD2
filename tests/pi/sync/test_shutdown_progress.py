################################################################################
# File Name: test_shutdown_progress.py
# Purpose/Description: US-883-b -- the shutdown sync's progress
#                      {waitingAtKeyOff, confirmed}, counted from the ACKED
#                      sync marks against a key-off snapshot, on a real SQLite
#                      file. One test per sprint validation criterion.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-23    | Rex (US-883-b) | Initial.
# ================================================================================
################################################################################
"""Tests for ``src.pi.sync.shutdown_progress``."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.common.edr.sync_contract import SHUTDOWN_DRAIN_EXCLUDED_TABLES
from src.pi.data import sync_log
from src.pi.sync.shutdown_progress import (
    ShutdownSyncProgress,
    countedTables,
    countRemaining,
    takeKeyOffSnapshot,
)

_TIMEOUT = 1.0


@pytest.fixture()
def dbPath(tmp_path: Path) -> str:
    """A Pi database holding one insert table, one update table and one EDR table."""
    path = tmp_path / "obd.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE realtime_data (id INTEGER PRIMARY KEY AUTOINCREMENT, v REAL)")
    conn.execute(
        "CREATE TABLE drive_summary (drive_id INTEGER PRIMARY KEY, note TEXT, "
        "_sync_modified_at TEXT)"
    )
    conn.execute("CREATE TABLE edr_imu_sample (id INTEGER PRIMARY KEY AUTOINCREMENT, ax REAL)")
    sync_log.initDb(conn)
    conn.commit()
    conn.close()
    return str(path)


def _exec(dbPath: str, sql: str, params: tuple = ()) -> None:
    conn = sqlite3.connect(dbPath)
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def _insertRealtime(dbPath: str, ids) -> None:
    conn = sqlite3.connect(dbPath)
    conn.executemany("INSERT INTO realtime_data (id, v) VALUES (?, 1.0)", [(i,) for i in ids])
    conn.commit()
    conn.close()


def _ack(dbPath: str, table: str, lastId: int, lastModifiedAt: str | None = None) -> None:
    """Advance a table's mark exactly as the post-commit stored ack does."""
    conn = sqlite3.connect(dbPath)
    sync_log.updateHighWaterMark(conn, table, lastId, "batch", lastModifiedAt=lastModifiedAt)
    conn.close()


def _progress(dbPath: str) -> tuple[ShutdownSyncProgress, list[dict]]:
    published: list[dict] = []
    progress = ShutdownSyncProgress(dbPath, busyTimeoutSec=_TIMEOUT, publishFn=published.append)
    return progress, published


# --------------------------------------------------------------------------- #
# The counted tables (Atlas Rule 13 gap 3)
# --------------------------------------------------------------------------- #


def test_countedTables_areTheDeltaTablesLessNotCountedAndTheDrainExclusion() -> None:
    """
    Given: the sync registries
    When:  the counted tables are resolved
    Then:  every delta table, the update tables included, minus readSyncHealth's
           notCounted and the drain's EDR exclusion -- no new list
    """
    counted = set(countedTables())
    notCounted = sync_log.SNAPSHOT_TABLES | sync_log.snapshotSyncTables()

    assert counted == set(sync_log.DELTA_SYNC_TABLES) - notCounted - SHUTDOWN_DRAIN_EXCLUDED_TABLES
    assert {"drive_summary", "dtc_log", "realtime_data"} <= counted
    assert not counted & SHUTDOWN_DRAIN_EXCLUDED_TABLES


# --------------------------------------------------------------------------- #
# Validation criteria
# --------------------------------------------------------------------------- #


def test_insertTable_100Waiting_onePassAcks60_confirms60(dbPath: str) -> None:
    """insert table: 100 rows waiting, one pass acks 60 -> waiting 100, confirmed 60."""
    _insertRealtime(dbPath, range(1, 101))
    progress, published = _progress(dbPath)
    progress.snapshot()

    _ack(dbPath, "realtime_data", 60)
    progress.publish()

    assert published == [{"waitingAtKeyOff": 100, "confirmed": 60}]


def test_reSentBatch_leavesConfirmedUnchanged(dbPath: str) -> None:
    """
    Given: 60 of 100 acked
    When:  the same batch is re-sent (the server inserts 0, updates N) and the
           stored ack writes the same mark again
    Then:  confirmed is unchanged -- per-push counts are never summed
    """
    _insertRealtime(dbPath, range(1, 101))
    progress, published = _progress(dbPath)
    progress.snapshot()
    _ack(dbPath, "realtime_data", 60)
    progress.publish()

    _ack(dbPath, "realtime_data", 60)
    progress.publish()

    assert [p["confirmed"] for p in published] == [60, 60]


def test_updateTable_3New2Modified_ackInsertsThenUpdates(dbPath: str) -> None:
    """update table with 3 new rows + 2 modified rows; ack inserts; ack updates
    -> waitingAtKeyOff 5; confirmed 3; then 5."""
    conn = sqlite3.connect(dbPath)
    conn.executemany(
        "INSERT INTO drive_summary (drive_id, note) VALUES (?, 'x')", [(i,) for i in range(1, 6)]
    )
    conn.commit()
    conn.close()
    _ack(dbPath, "drive_summary", 2, "2026-10-23T10:00:00.000Z")
    # Rows 1 and 2 were pushed, then UPDATEd (the trigger re-stamps them).
    _exec(dbPath, "UPDATE drive_summary SET _sync_modified_at = ? WHERE drive_id = 1",
          ("2026-10-23T11:00:00.000Z",))
    _exec(dbPath, "UPDATE drive_summary SET _sync_modified_at = ? WHERE drive_id = 2",
          ("2026-10-23T11:00:01.000Z",))
    progress, published = _progress(dbPath)
    progress.snapshot()

    _ack(dbPath, "drive_summary", 5)
    progress.publish()
    _ack(dbPath, "drive_summary", 5, "2026-10-23T11:00:01.000Z")
    progress.publish()

    assert published == [
        {"waitingAtKeyOff": 5, "confirmed": 3},
        {"waitingAtKeyOff": 5, "confirmed": 5},
    ]


def test_idGaps_countRowsNotTheIdSpan(dbPath: str) -> None:
    """ids 1..10 with 4 missing, 6 rows waiting -> waitingAtKeyOff 6, not 10."""
    _insertRealtime(dbPath, [1, 2, 4, 6, 9, 10])
    progress, published = _progress(dbPath)
    progress.snapshot()

    progress.publish()

    assert published == [{"waitingAtKeyOff": 6, "confirmed": 0}]


def test_driveSummaryInsertedBeforeTheSnapshot_isCountedUntilAcked(dbPath: str) -> None:
    """A drive_summary row inserted before the snapshot, not yet acked, is
    counted; confirmed < waitingAtKeyOff until it is acked."""
    _insertRealtime(dbPath, range(1, 4))
    _exec(dbPath, "INSERT INTO drive_summary (drive_id, note) VALUES (7, 'new drive')")
    progress, published = _progress(dbPath)
    progress.snapshot()

    _ack(dbPath, "realtime_data", 3)
    progress.publish()
    _ack(dbPath, "drive_summary", 7)
    progress.publish()

    assert published == [
        {"waitingAtKeyOff": 4, "confirmed": 3},
        {"waitingAtKeyOff": 4, "confirmed": 4},
    ]


def test_rowsWrittenAfterTheSnapshot_neverEnterEitherCount(dbPath: str) -> None:
    """Rows inserted (or modified) after the snapshot never enter
    waitingAtKeyOff or confirmed, even once acked."""
    _insertRealtime(dbPath, range(1, 11))
    _exec(dbPath, "INSERT INTO drive_summary (drive_id, note) VALUES (1, 'a')")
    _ack(dbPath, "drive_summary", 1)
    progress, published = _progress(dbPath)
    progress.snapshot()

    _insertRealtime(dbPath, range(11, 51))
    _exec(dbPath, "INSERT INTO drive_summary (drive_id, note) VALUES (2, 'b')")
    _ack(dbPath, "realtime_data", 50)
    _ack(dbPath, "drive_summary", 2)
    progress.publish()

    assert published == [{"waitingAtKeyOff": 10, "confirmed": 10}]


def test_edrOnlyBacklog_waitsZero(dbPath: str) -> None:
    """EDR-only backlog -> waitingAtKeyOff 0 (the drain does not carry EDR)."""
    conn = sqlite3.connect(dbPath)
    conn.executemany("INSERT INTO edr_imu_sample (ax) VALUES (?)", [(0.1,)] * 25)
    conn.commit()
    conn.close()
    progress, published = _progress(dbPath)
    progress.snapshot()

    progress.publish()

    assert published == [{"waitingAtKeyOff": 0, "confirmed": 0}]


# --------------------------------------------------------------------------- #
# Honest-instrument edges
# --------------------------------------------------------------------------- #


def test_publish_withoutASnapshot_publishesNothing(dbPath: str) -> None:
    """No snapshot (the run never started) -> nothing is published."""
    progress, published = _progress(dbPath)

    progress.publish()

    assert published == []


def test_unreadableDatabase_snapshotsNothing_andNeverRaises(tmp_path: Path) -> None:
    """A missing database is not an empty queue: no snapshot, nothing published,
    and the read-only open never creates the file."""
    missing = tmp_path / "absent.db"

    assert takeKeyOffSnapshot(str(missing), busyTimeoutSec=_TIMEOUT) is None
    progress, published = _progress(str(missing))
    progress.snapshot()
    progress.publish()

    assert published == []
    assert not missing.exists()


def test_remainingUnreadable_publishesNothing(dbPath: str, tmp_path: Path) -> None:
    """When the marks cannot be read after a pass, no count is sent (never 0)."""
    _insertRealtime(dbPath, range(1, 4))
    snapshot = takeKeyOffSnapshot(dbPath, busyTimeoutSec=_TIMEOUT)
    assert snapshot is not None

    assert countRemaining(str(tmp_path / "gone.db"), snapshot, busyTimeoutSec=_TIMEOUT) is None


def test_aRaisingPublishFn_neverRaises(dbPath: str) -> None:
    """A publish sink that raises never stops the drain pass that called it."""
    _insertRealtime(dbPath, range(1, 4))

    def _boom(_sync: dict) -> None:
        raise RuntimeError("writer down")

    progress = ShutdownSyncProgress(dbPath, busyTimeoutSec=_TIMEOUT, publishFn=_boom)
    progress.snapshot()

    progress.publish()  # must not raise


def test_confirmed_isFlooredAtZero_andNeverExceedsWaiting(dbPath: str) -> None:
    """confirmed stays within 0..waitingAtKeyOff across passes."""
    _insertRealtime(dbPath, range(1, 21))
    progress, published = _progress(dbPath)
    progress.snapshot()

    for mark in (0, 5, 20):
        _ack(dbPath, "realtime_data", mark)
        progress.publish()

    assert [p["confirmed"] for p in published] == [0, 5, 20]
    assert all(0 <= p["confirmed"] <= p["waitingAtKeyOff"] for p in published)
