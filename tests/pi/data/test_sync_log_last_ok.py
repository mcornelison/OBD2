################################################################################
# File Name: test_sync_log_last_ok.py
# Purpose/Description: US-916 -- sync_log.last_ok_at ("data last STORED by the
#                      server") and the system-status sync read behind it:
#                      lastOkTs, rowsWaiting, edrRowsWaiting, notCounted.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Rex (US-916) | Initial
# ================================================================================
################################################################################

"""Tests for US-916: last_ok_at written only by a stored push, read read-only."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pi.obdii.orchestrator.card_state_emitter import (
    SYNC_HEALTH_READ_INTERVAL_S,
    CardStateEmitterMixin,
)
from src.common.edr.sync_contract import EDR_SYNC_TABLES
from src.common.sync.snapshot_registry import SNAPSHOT_SYNC, SnapshotSyncSpec
from src.pi.data import sync_log
from src.pi.sync.backlog import readSyncHealth
from src.pi.sync.client import PushStatus, SyncClient
from tests.pi.sync.stored_ack_reply import storedAckReplyFor

_REPO_ROOT = Path(__file__).resolve().parents[3]
_T1 = "2026-10-22T08:00:00Z"
_T2 = "2026-10-22T08:05:00Z"
_SNAP_TABLE = "test_us916_snap"


# --------------------------------------------------------------------------- #
# Fixtures + helpers
# --------------------------------------------------------------------------- #


def _createDeltaTables(conn: sqlite3.Connection) -> None:
    """Every delta table as a bare integer-PK table, plus the snapshot tables."""
    for tableName, pkColumn in sync_log.PK_COLUMN.items():
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {tableName} "
            f"({pkColumn} INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)"
        )
    conn.execute("CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS vehicle_info (vin TEXT PRIMARY KEY)")
    conn.commit()


def _insertRows(conn: sqlite3.Connection, tableName: str, n: int) -> None:
    conn.executemany(
        f"INSERT INTO {tableName} (v) VALUES (?)", [("x",) for _ in range(n)]
    )
    conn.commit()


@pytest.fixture
def dbPath(tmp_path: Path) -> str:
    path = str(tmp_path / "obd.db")
    conn = sqlite3.connect(path)
    sync_log.initDb(conn)
    _createDeltaTables(conn)
    _insertRows(conn, "realtime_data", 3)
    conn.close()
    return path


@pytest.fixture(autouse=True)
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-us916")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Pin the instant sync_log stamps (``_utcIsoTimestamp``)."""
    current = {"ts": _T1}
    monkeypatch.setattr(sync_log, "_utcIsoTimestamp", lambda: current["ts"])

    def _set(ts: str) -> None:
        current["ts"] = ts

    return _set


@pytest.fixture
def snapshotTable(dbPath: str) -> Iterator[str]:
    SNAPSHOT_SYNC[_SNAP_TABLE] = SnapshotSyncSpec(
        naturalKeyCols=("boot_id",), cursorCol="recorded_at",
    )
    conn = sqlite3.connect(dbPath)
    conn.execute(
        f"CREATE TABLE {_SNAP_TABLE} (boot_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL)"
    )
    conn.execute(
        f"INSERT INTO {_SNAP_TABLE} VALUES ('boot-a', '2026-10-22T07:00:00Z')"
    )
    conn.commit()
    conn.close()
    try:
        yield _SNAP_TABLE
    finally:
        SNAPSHOT_SYNC.pop(_SNAP_TABLE, None)


def _config(dbPath: str) -> dict[str, Any]:
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://10.27.27.10:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [1],
            },
        },
    }


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.status = 200

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _storedOpener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
    return _FakeResponse(storedAckReplyFor(req.data))


def _rejectOpener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
    raise urllib.error.HTTPError(
        url="http://test/", code=500, msg="Server Error",
        hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
    )


def _unreachableOpener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
    raise urllib.error.URLError("connection refused")


def _client(dbPath: str, opener: Callable[..., Any]) -> SyncClient:
    return SyncClient(_config(dbPath), httpOpener=opener, sleep=lambda _s: None)


def _lastOkAt(dbPath: str, tableName: str) -> str | None:
    conn = sqlite3.connect(dbPath)
    try:
        row = conn.execute(
            "SELECT last_ok_at FROM sync_log WHERE table_name = ?", (tableName,)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row is not None else None


def _syncLogColumns(dbPath: str) -> set[str]:
    conn = sqlite3.connect(dbPath)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(sync_log)")}
    finally:
        conn.close()


def _legacySyncLog(dbPath: str) -> None:
    """Replace sync_log with its pre-US-916 shape (no last_ok_at)."""
    conn = sqlite3.connect(dbPath)
    conn.execute("DROP TABLE sync_log")
    conn.execute(
        sync_log.SYNC_LOG_SCHEMA.replace(
            "last_snapshot_cursor    TEXT,\n    last_ok_at              TEXT",
            "last_snapshot_cursor    TEXT",
        )
    )
    conn.execute(
        "INSERT INTO sync_log (table_name, last_synced_id, last_synced_at, status) "
        "VALUES ('realtime_data', 1, '2026-10-01T00:00:00Z', 'ok')"
    )
    conn.commit()
    conn.close()
    assert "last_ok_at" not in _syncLogColumns(dbPath)


class _Host(CardStateEmitterMixin):
    """A bare composer: the database and a scripted monotonic clock."""

    def __init__(self, dbPath: str | None) -> None:
        self._database = SimpleNamespace(dbPath=dbPath) if dbPath else None
        self.nowS = 1000.0
        self._linkClock = lambda: self.nowS


# --------------------------------------------------------------------------- #
# The write side: only a stored push stamps last_ok_at
# --------------------------------------------------------------------------- #


class TestWrittenOnlyByAStoredPush:

    def test_okPush_thenFailedPush_lastOkTsStaysAtTheOkPush(
        self, dbPath: str, clock: Callable[[str], None]
    ) -> None:
        """VC: ok push at T, then a failed push -> sync.lastOkTs = T."""
        clock(_T1)
        assert _client(dbPath, _storedOpener).pushDelta("realtime_data").status == (
            PushStatus.OK
        )
        conn = sqlite3.connect(dbPath)
        _insertRows(conn, "realtime_data", 2)
        conn.close()

        clock(_T2)
        assert _client(dbPath, _unreachableOpener).pushDelta("realtime_data").status == (
            PushStatus.FAILED
        )
        assert _client(dbPath, _rejectOpener).pushDelta("realtime_data").status == (
            PushStatus.FAILED
        )

        assert _lastOkAt(dbPath, "realtime_data") == _T1
        assert readSyncHealth(dbPath).lastOkTs == _T1

    def test_okPush_advancesLastOkAt(
        self, dbPath: str, clock: Callable[[str], None]
    ) -> None:
        clock(_T1)
        _client(dbPath, _storedOpener).pushDelta("realtime_data")
        conn = sqlite3.connect(dbPath)
        _insertRows(conn, "realtime_data", 1)
        conn.close()
        clock(_T2)
        _client(dbPath, _storedOpener).pushDelta("realtime_data")
        assert _lastOkAt(dbPath, "realtime_data") == _T2

    def test_failedWrite_neverTouchesLastOkAt(self, clock: Callable[[str], None]) -> None:
        conn = sqlite3.connect(":memory:")
        sync_log.initDb(conn)
        clock(_T1)
        sync_log.updateHighWaterMark(conn, "realtime_data", 5, "b1", status="ok")
        clock(_T2)
        sync_log.updateHighWaterMark(conn, "realtime_data", 5, "b2", status="failed")
        row = conn.execute(
            "SELECT last_ok_at, last_synced_at, status FROM sync_log"
        ).fetchone()
        assert row == (_T1, _T2, "failed")

    def test_everyTableFailing_lastOkTsUnchanged(
        self, dbPath: str, clock: Callable[[str], None]
    ) -> None:
        clock(_T1)
        _client(dbPath, _storedOpener).pushDelta("realtime_data")
        conn = sqlite3.connect(dbPath)
        for tableName in sync_log.PK_COLUMN:
            _insertRows(conn, tableName, 1)
        conn.close()

        clock(_T2)
        results = _client(dbPath, _rejectOpener).pushAllDeltas()

        assert not any(r.status == PushStatus.OK for r in results)
        assert readSyncHealth(dbPath).lastOkTs == _T1

    def test_snapshotOnlyPush_advancesIt(
        self, dbPath: str, snapshotTable: str, clock: Callable[[str], None]
    ) -> None:
        clock(_T2)
        result = _client(dbPath, _storedOpener).pushSnapshot(snapshotTable)
        assert result.status == PushStatus.OK
        assert _lastOkAt(dbPath, snapshotTable) == _T2
        assert readSyncHealth(dbPath).lastOkTs == _T2

    def test_failedSnapshotWrite_keepsTheStoredOne(self, clock: Callable[[str], None]) -> None:
        SNAPSHOT_SYNC[_SNAP_TABLE] = SnapshotSyncSpec(
            naturalKeyCols=("boot_id",), cursorCol="recorded_at",
        )
        try:
            conn = sqlite3.connect(":memory:")
            sync_log.initDb(conn)
            clock(_T1)
            sync_log.updateSnapshotCursor(conn, _SNAP_TABLE, "c1", "b1", status="ok")
            clock(_T2)
            sync_log.updateSnapshotCursor(conn, _SNAP_TABLE, "c2", "b2", status="failed")
            assert sync_log.getLastOkAt(conn) == _T1
        finally:
            SNAPSHOT_SYNC.pop(_SNAP_TABLE, None)

    def test_okWriteOnALegacySyncLog_addsTheColumnThenStamps(
        self, dbPath: str, clock: Callable[[str], None]
    ) -> None:
        _legacySyncLog(dbPath)
        clock(_T1)
        _client(dbPath, _storedOpener).pushDelta("realtime_data")
        assert "last_ok_at" in _syncLogColumns(dbPath)
        assert _lastOkAt(dbPath, "realtime_data") == _T1

    def test_ensureLastOkSchema_isIdempotent_existingRowsStartNull(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            sync_log.SYNC_LOG_SCHEMA.replace(
                "last_snapshot_cursor    TEXT,\n    last_ok_at              TEXT",
                "last_snapshot_cursor    TEXT",
            )
        )
        conn.execute("INSERT INTO sync_log (table_name) VALUES ('realtime_data')")
        assert sync_log.ensureLastOkSchema(conn) is True
        assert sync_log.ensureLastOkSchema(conn) is False
        assert sync_log.getLastOkAt(conn) is None

    def test_forcePush_advancesIt_asReadByTheOrchestratorsProvider(
        self, dbPath: str, clock: Callable[[str], None]
    ) -> None:
        """Atlas S4: powerwatch's key-off drain (forcePush) moves lastOkTs."""
        clock(_T2)
        summary = _client(dbPath, _storedOpener).forcePush(
            excludeTables=frozenset(EDR_SYNC_TABLES)
        )
        assert summary.tablesOk >= 1

        host = _Host(dbPath)
        assert host._gatherSyncState()["syncLastOkTs"] == _T2


# --------------------------------------------------------------------------- #
# The read side: read-only, never migrates, never raises
# --------------------------------------------------------------------------- #


class TestReadOnlyRead:

    def test_dbWithoutTheColumn_isNull_noRaise_noMigration(self, dbPath: str) -> None:
        _legacySyncLog(dbPath)
        health = readSyncHealth(dbPath)
        assert health.lastOkTs is None
        assert "last_ok_at" not in _syncLogColumns(dbPath)

    def test_noOkPushYet_isNull(self, dbPath: str) -> None:
        assert readSyncHealth(dbPath).lastOkTs is None

    def test_missingDatabase_everyFieldNull_andNotCreated(self, tmp_path: Path) -> None:
        missing = tmp_path / "absent.db"
        health = readSyncHealth(str(missing))
        assert (health.lastOkTs, health.rowsWaiting, health.edrRowsWaiting) == (
            None, None, None,
        )
        assert not missing.exists()

    def test_noDbPath_everyFieldNull(self) -> None:
        health = readSyncHealth(None)
        assert health == type(health)()

    def test_lastOkTs_survivesARestart(
        self, dbPath: str, clock: Callable[[str], None]
    ) -> None:
        """A NEW process reads the same obd.db and gets the stored instant."""
        clock(_T1)
        _client(dbPath, _storedOpener).pushDelta("realtime_data")
        code = (
            "import json, sys\n"
            "from src.pi.sync.backlog import readSyncHealth\n"
            "print(json.dumps(readSyncHealth(sys.argv[1]).lastOkTs))\n"
        )
        # The package imports on both roots (src.pi.* and pi.*), as under pytest.
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(_REPO_ROOT), str(_REPO_ROOT / "src")])
        out = subprocess.run(
            [sys.executable, "-c", code, dbPath],
            cwd=_REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
            check=True,
        )
        assert json.loads(out.stdout.strip().splitlines()[-1]) == _T1


# --------------------------------------------------------------------------- #
# rowsWaiting / edrRowsWaiting / notCounted
# --------------------------------------------------------------------------- #


class TestRowsWaiting:

    def test_120RowsPastTheMarks_rowsWaiting120(self, dbPath: str) -> None:
        """VC: 120 rows past the high-water marks -> sync.rowsWaiting 120."""
        conn = sqlite3.connect(dbPath)
        sync_log.updateHighWaterMark(conn, "realtime_data", 3, "b0")
        _insertRows(conn, "realtime_data", 100)
        _insertRows(conn, "connection_log", 20)
        conn.close()

        assert readSyncHealth(dbPath).rowsWaiting == 120

    def test_rowsPlusEdr_equalsTheSumOfThePushsOwnPredicate(self, dbPath: str) -> None:
        conn = sqlite3.connect(dbPath)
        _insertRows(conn, "alert_log", 4)
        for i, tableName in enumerate(EDR_SYNC_TABLES):
            _insertRows(conn, tableName, 10 + i)
        sync_log.updateHighWaterMark(conn, "realtime_data", 1, "b0")
        expected = 0
        for tableName in sync_log.DELTA_SYNC_TABLES:
            lastId = sync_log.getHighWaterMark(conn, tableName)[0]
            expected += sync_log.countDeltaRows(conn, tableName, lastId)
        conn.close()

        health = readSyncHealth(dbPath)
        assert health.edrRowsWaiting == sum(10 + i for i in range(len(EDR_SYNC_TABLES)))
        assert health.rowsWaiting + health.edrRowsWaiting == expected

    def test_anUnreadableTable_makesItsCountNull_neverAPartialNumber(
        self, dbPath: str
    ) -> None:
        conn = sqlite3.connect(dbPath)
        conn.execute("DROP TABLE alert_log")
        conn.execute("CREATE TABLE alert_log (other INTEGER)")  # no id column
        conn.commit()
        conn.close()

        health = readSyncHealth(dbPath)
        assert health.rowsWaiting is None
        assert health.edrRowsWaiting == 0

    def test_notCounted_isTheSnapshotTables_sorted(
        self, dbPath: str, snapshotTable: str
    ) -> None:
        expected = sorted(sync_log.SNAPSHOT_TABLES | sync_log.snapshotSyncTables())
        assert snapshotTable in expected
        assert list(readSyncHealth(dbPath).notCounted or ()) == expected


# --------------------------------------------------------------------------- #
# The orchestrator's provider: 30 s cache, getattr-tolerant
# --------------------------------------------------------------------------- #


class TestOrchestratorProvider:

    def test_noDatabase_everySyncFieldNull(self) -> None:
        assert _Host(None)._gatherSyncState() == {
            "syncLastOkTs": None,
            "syncRowsWaiting": None,
            "syncEdrRowsWaiting": None,
            "syncNotCounted": None,
        }

    def test_readEveryThirtySeconds_cachedBetween(self, dbPath: str) -> None:
        host = _Host(dbPath)
        first = host._gatherSyncState()
        assert first["syncRowsWaiting"] == 3

        conn = sqlite3.connect(dbPath)
        _insertRows(conn, "realtime_data", 5)
        conn.close()
        host.nowS += SYNC_HEALTH_READ_INTERVAL_S - 1
        assert host._gatherSyncState()["syncRowsWaiting"] == 3

        host.nowS += 1
        assert host._gatherSyncState()["syncRowsWaiting"] == 8

    def test_notCountedIsPublishedAsAList(self, dbPath: str) -> None:
        assert _Host(dbPath)._gatherSyncState()["syncNotCounted"] == sorted(
            sync_log.SNAPSHOT_TABLES | sync_log.snapshotSyncTables()
        )
