################################################################################
# File Name: test_edr_purge_sync_gated.py
# Purpose/Description: US-768 -- the ONE EDR purge deletes only rows the server
#                      already has. purgeExpired() requires ts_utc < cutoff AND
#                      id <= that table's sync high-water mark; an unreadable
#                      mark deletes nothing; below 15 GB free it WARNS and still
#                      deletes no unsynced row. Also pins that no second EDR
#                      delete path exists under src/pi.
# Author: Rex (US-768)
# Creation Date: 2026-09-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-18    | Rex (US-768) | Initial -- sync-gated purge, low-disk warning.
# ================================================================================
################################################################################
"""Tests for the sync-gated EDR retention purge (US-768)."""

from __future__ import annotations

import inspect
import logging
import sqlite3
from pathlib import Path

import pytest

import pi.bus.edr_persistence_subscriber as subscriberModule
from common.time.helper import utcIsoNow
from pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber
from pi.obdii.database import ObdDatabase

# US-805 / ARCH-045: derived from the sync contract, not a hardcoded pair. A
# new EDR table used to inherit NONE of this guard -- its DELETE would sit
# outside purgeExpired, ungated, and this test would still pass. The guard
# must cover every EDR table by construction, not by someone remembering.
from src.common.edr.sync_contract import EDR_SYNC_TABLES  # noqa: E402
from src.pi.data import sync_log

_EDR_TABLES = tuple(EDR_SYNC_TABLES)
_OLD_TS = "2020-01-01T00:00:00Z"
_PLENTY_FREE = 100 * 1000**3
_LOW_FREE = 1 * 1000**3
_SRC_PI = Path(__file__).resolve().parents[3] / "src" / "pi"


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_edr_purge.db"), walMode=False)
    db.initialize()
    return db


def _insertRow(db: ObdDatabase, table: str, ts: str) -> int:
    # US-805: edr_imu_derived carries fusion_version NOT NULL with NO DEFAULT, on
    # purpose -- a row that cannot say WHICH algorithm produced it is exactly the
    # thing the separate table exists to prevent, and a DEFAULT would let a
    # forgetful writer record a plausible WRONG version instead of failing. So
    # the column is supplied here rather than softened in the schema.
    extraCols, extraVals = ("", "")
    if table == "edr_imu_derived":
        extraCols, extraVals = ", fusion_version", ", 1"
    with db.connect() as conn:
        cur = conn.execute(
            f"INSERT INTO {table} (ts_utc, ts_capture, seq{extraCols}) "
            f"VALUES (?, 0.0, 1{extraVals})",
            (ts,),
        )
        return int(cur.lastrowid)


def _setMark(db: ObdDatabase, table: str, lastId: int) -> None:
    with db.connect() as conn:
        sync_log.initDb(conn)
        sync_log.updateHighWaterMark(conn, table, lastId, "test-batch")


def _ids(db: ObdDatabase, table: str) -> list[int]:
    with db.connect() as conn:
        return [r[0] for r in conn.execute(f"SELECT id FROM {table} ORDER BY id")]


def _seedBothSidesOfMark(db: ObdDatabase) -> dict[str, dict[str, list[int]]]:
    """Per table: one fresh synced row, two old synced rows, two old unsynced rows."""
    layout: dict[str, dict[str, list[int]]] = {}
    for table in _EDR_TABLES:
        fresh = _insertRow(db, table, utcIsoNow())
        oldSynced = [_insertRow(db, table, _OLD_TS) for _ in range(2)]
        oldUnsynced = [_insertRow(db, table, _OLD_TS) for _ in range(2)]
        _setMark(db, table, oldSynced[-1])
        layout[table] = {"fresh": [fresh], "oldSynced": oldSynced, "oldUnsynced": oldUnsynced}
    return layout


def _subscriber(db: ObdDatabase, freeBytes: int = _PLENTY_FREE) -> EdrPersistenceSubscriber:
    return EdrPersistenceSubscriber(
        None, db, retentionDays=7, freeDiskBytesFn=lambda: freeBytes
    )


class TestSyncGatedPurge:
    def test_purge_rowsOnBothSidesOfMark_deletesOnlyOldRowsAtOrBelowMark(
        self, freshDb: ObdDatabase
    ) -> None:
        """
        Given: old rows at/below and above each table's high-water mark, plus a
               fresh synced row
        When: the purge runs
        Then: only the old rows at or below the mark are deleted
        """
        layout = _seedBothSidesOfMark(freshDb)

        imuDeleted, lightDeleted, _derived = _subscriber(freshDb).purgeExpired()

        assert (imuDeleted, lightDeleted) == (2, 2)
        for table in _EDR_TABLES:
            expected = sorted(layout[table]["fresh"] + layout[table]["oldUnsynced"])
            assert _ids(freshDb, table) == expected

    def test_purge_tablesHaveIndependentMarks_eachTableUsesItsOwn(
        self, freshDb: ObdDatabase
    ) -> None:
        imuIds = [_insertRow(freshDb, "edr_imu_sample", _OLD_TS) for _ in range(3)]
        lightIds = [_insertRow(freshDb, "edr_light_sample", _OLD_TS) for _ in range(3)]
        _setMark(freshDb, "edr_imu_sample", imuIds[2])
        _setMark(freshDb, "edr_light_sample", lightIds[0])

        imuDeleted, lightDeleted, _derived = _subscriber(freshDb).purgeExpired()

        assert (imuDeleted, lightDeleted) == (3, 1)
        assert _ids(freshDb, "edr_light_sample") == lightIds[1:]

    def test_purge_noSyncLogRowYet_deletesNothing(self, freshDb: ObdDatabase) -> None:
        # A table the server has never acknowledged has mark 0: nothing is synced.
        with freshDb.connect() as conn:
            sync_log.initDb(conn)
        for table in _EDR_TABLES:
            _insertRow(freshDb, table, _OLD_TS)

        assert _subscriber(freshDb).purgeExpired() == (0, 0, 0)
        for table in _EDR_TABLES:
            assert len(_ids(freshDb, table)) == 1


class TestUnreadableMark:
    def test_purge_markReadRaises_deletesNothingAndLogs(
        self, freshDb: ObdDatabase, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: synced old rows in both tables, and a high-water read that raises
        When: the purge runs
        Then: both table counts are unchanged and the failure is logged
        """
        _seedBothSidesOfMark(freshDb)
        before = {t: _ids(freshDb, t) for t in _EDR_TABLES}

        def _raise(conn, tableName):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(subscriberModule.sync_log, "getHighWaterMark", _raise)
        with caplog.at_level(logging.WARNING, logger=subscriberModule.__name__):
            result = _subscriber(freshDb).purgeExpired()

        # US-805: THREE counts -- imu, light, derived -- never two with the
        # derived rows folded into the imu one.
        assert result == (0, 0, 0)
        assert {t: _ids(freshDb, t) for t in _EDR_TABLES} == before
        assert any(
            "high-water" in r.getMessage() and "disk I/O error" in r.getMessage()
            for r in caplog.records if r.levelno == logging.WARNING
        )

    def test_purge_secondTableMarkRaises_firstTableAlsoUntouched(
        self, freshDb: ObdDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Both marks are read before ANY delete, so a failure on the light table
        # cannot leave the IMU table half-purged.
        _seedBothSidesOfMark(freshDb)
        before = {t: _ids(freshDb, t) for t in _EDR_TABLES}
        realRead = sync_log.getHighWaterMark

        def _raiseOnLight(conn, tableName):
            if tableName == "edr_light_sample":
                raise sqlite3.DatabaseError("malformed")
            return realRead(conn, tableName)

        monkeypatch.setattr(subscriberModule.sync_log, "getHighWaterMark", _raiseOnLight)

        assert _subscriber(freshDb).purgeExpired() == (0, 0, 0)
        assert {t: _ids(freshDb, t) for t in _EDR_TABLES} == before

    def test_purge_syncLogTableMissing_deletesNothing(self, freshDb: ObdDatabase) -> None:
        with freshDb.connect() as conn:
            conn.execute("DROP TABLE IF EXISTS sync_log")
        for table in _EDR_TABLES:
            _insertRow(freshDb, table, _OLD_TS)

        assert _subscriber(freshDb).purgeExpired() == (0, 0, 0)
        for table in _EDR_TABLES:
            assert len(_ids(freshDb, table)) == 1
        with freshDb.connect() as conn:
            # The purge reads the mark; it never creates sync schema to get one.
            assert conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'sync_log'"
            ).fetchone()[0] == 0

    def test_maybePurge_markReadRaises_isNonFatal(
        self, freshDb: ObdDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seedBothSidesOfMark(freshDb)
        before = {t: _ids(freshDb, t) for t in _EDR_TABLES}

        def _raise(conn, tableName):
            raise RuntimeError("boom")

        monkeypatch.setattr(subscriberModule.sync_log, "getHighWaterMark", _raise)
        clock = {"t": 0.0}
        sub = EdrPersistenceSubscriber(
            None, freshDb, retentionDays=7, monotonicFn=lambda: clock["t"],
            retentionCheckIntervalS=1.0, freeDiskBytesFn=lambda: _PLENTY_FREE,
        )
        clock["t"] = 2.0

        assert sub.maybePurge() is True
        assert {t: _ids(freshDb, t) for t in _EDR_TABLES} == before


class TestLowDisk:
    def test_purge_belowFloor_warnsAndKeepsEveryUnsyncedRow(
        self, freshDb: ObdDatabase, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: old rows above the mark and 1 GB free (below the 15 GB floor)
        When: the purge runs
        Then: a WARNING is emitted and the unsynced count is unchanged, while
              synced old rows are still deleted
        """
        layout = _seedBothSidesOfMark(freshDb)

        with caplog.at_level(logging.WARNING, logger=subscriberModule.__name__):
            result = _subscriber(freshDb, freeBytes=_LOW_FREE).purgeExpired()

        assert result == (2, 2, 2)
        for table in _EDR_TABLES:
            remaining = set(_ids(freshDb, table))
            assert set(layout[table]["oldUnsynced"]) <= remaining
        assert any(
            "15 GB" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
        )

    def test_purge_belowFloorAndNothingSynced_deletesNothing(
        self, freshDb: ObdDatabase
    ) -> None:
        for table in _EDR_TABLES:
            _insertRow(freshDb, table, _OLD_TS)
            _setMark(freshDb, table, 0)

        assert _subscriber(freshDb, freeBytes=0).purgeExpired() == (0, 0, 0)
        for table in _EDR_TABLES:
            assert len(_ids(freshDb, table)) == 1

    @pytest.mark.parametrize(
        ("freeBytes", "warns"),
        [(15 * 1000**3 - 1, True), (15 * 1000**3, False), (_PLENTY_FREE, False)],
    )
    def test_purge_floorBoundary_warnsOnlyBelow15Gb(
        self, freshDb: ObdDatabase, caplog: pytest.LogCaptureFixture,
        freeBytes: int, warns: bool,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=subscriberModule.__name__):
            _subscriber(freshDb, freeBytes=freeBytes).purgeExpired()

        lowDisk = [r for r in caplog.records if "15 GB" in r.getMessage()]
        assert bool(lowDisk) is warns

    def test_purge_freeSpaceUnreadable_stillSyncGatedAndLogged(
        self, freshDb: ObdDatabase, caplog: pytest.LogCaptureFixture
    ) -> None:
        layout = _seedBothSidesOfMark(freshDb)

        def _raise() -> int:
            raise OSError("statvfs failed")

        sub = EdrPersistenceSubscriber(None, freshDb, retentionDays=7, freeDiskBytesFn=_raise)
        with caplog.at_level(logging.WARNING, logger=subscriberModule.__name__):
            assert sub.purgeExpired() == (2, 2, 2)

        for table in _EDR_TABLES:
            assert set(layout[table]["oldUnsynced"]) <= set(_ids(freshDb, table))
        assert any("statvfs failed" in r.getMessage() for r in caplog.records)

    def test_defaultFreeDiskRead_measuresTheDatabaseVolume(
        self, freshDb: ObdDatabase
    ) -> None:
        sub = EdrPersistenceSubscriber(None, freshDb, retentionDays=7)
        assert sub._freeDiskBytes() > 0


class TestOneDeletePath:
    def test_everyEdrDeleteUnderSrcPi_isInsidePurgeExpiredAndSyncGated(self) -> None:
        """grep -rn 'DELETE FROM edr_' src/pi == the purge's statements, each gated."""
        hits: list[tuple[Path, str]] = []
        for path in _SRC_PI.rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "DELETE FROM edr_" in line:
                    hits.append((path, line))

        purgeSource = inspect.getsource(EdrPersistenceSubscriber.purgeExpired)
        assert len(hits) == len(_EDR_TABLES)
        for path, line in hits:
            assert path.name == "edr_persistence_subscriber.py"
            assert line.strip() in purgeSource
            assert "ts_utc < ?" in line and "id <= ?" in line

    def test_edrSyncCursorColumn_isTheIdTheDeleteCompares(self) -> None:
        for table in _EDR_TABLES:
            assert sync_log.PK_COLUMN[table] == "id"
