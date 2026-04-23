################################################################################
# File Name: test_sync_force_push.py
# Purpose/Description: SyncClient.forcePush() tests -- explicit-intent manual
#                      flush wrapping pushAllDeltas with a PushSummary.
#                      US-225 / TD-034 close (US-216 WARNING stage behavior).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Tests for :meth:`SyncClient.forcePush`.

The API is semantically identical to :meth:`pushAllDeltas` (no normal-sync
invariants are bypassed) so the test surface focuses on:

1. **Summary aggregation** -- counts match per-table results across all
   PushStatus values.
2. **AUTH / timeout respect** -- the same env key + companion config
   that pushDelta uses is the path forcePush takes.
3. **Disabled companion** -- forcePush returns a benign
   ``disabled=True`` summary; no HTTP calls.
4. **Failure isolation** -- a failed table leaves its HWM untouched
   (inherited pushDelta invariant) while other tables still push.
"""

from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import urllib.error
from collections.abc import Callable, Generator
from typing import Any

import pytest

from src.pi.data import sync_log
from src.pi.sync.client import PushStatus, PushSummary, SyncClient

# ================================================================================
# Shared fixtures (mirroring test_sync_client.py minimal surface)
# ================================================================================


def _createEmptyInScopeTables(conn: sqlite3.Connection) -> None:
    for tableName in sync_log.IN_SCOPE_TABLES:
        if tableName in sync_log.SNAPSHOT_TABLES:
            pkColumn = 'id' if tableName == 'profiles' else 'vin'
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {tableName} "
                f"({pkColumn} TEXT PRIMARY KEY)"
            )
            continue
        pkColumn = sync_log.PK_COLUMN[tableName]
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {tableName} "
            f"({pkColumn} INTEGER PRIMARY KEY AUTOINCREMENT)"
        )
    conn.commit()


def _installRealtimeSchema(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS realtime_data")
    conn.execute("""
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL
        )
    """)
    conn.commit()


def _writeRealtimeRows(conn: sqlite3.Connection, n: int) -> None:
    for i in range(n):
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES (?, ?, ?)",
            (f"2026-04-23T00:00:{i:02d}Z", "RPM", 1000.0 + i),
        )
    conn.commit()


def _baseConfig(dbPath: str, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "companionService": {
                "enabled": enabled,
                "baseUrl": "http://10.27.27.10:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 3,
                "retryBackoffSeconds": [1, 2, 4, 8, 16],
            },
        },
    }


@pytest.fixture
def tempDbPath() -> Generator[str, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    sync_log.initDb(conn)
    _createEmptyInScopeTables(conn)
    _installRealtimeSchema(conn)
    _writeRealtimeRows(conn, 5)
    conn.close()
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture
def noSleep() -> Callable[[float], None]:
    def _record(seconds: float) -> None:
        pass
    return _record


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    key = "test-key-forcepush"
    monkeypatch.setenv("COMPANION_API_KEY", key)
    return key


class _FakeResponse:
    def __init__(self, body: bytes = b"{}", status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _successOpener() -> Callable[..., Any]:
    calls: list[Any] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:
        calls.append((req, timeout))
        return _FakeResponse(body=b'{"status":"ok"}', status=200)

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


def _alwaysFailOpener(code: int = 500) -> Callable[..., Any]:
    calls: list[int] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:
        calls.append(code)
        raise urllib.error.HTTPError(
            url=getattr(req, "full_url", "http://test/"),
            code=code,
            msg="Server Error",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


# ================================================================================
# Summary aggregation
# ================================================================================


class TestSummaryAggregation:
    def test_forcePush_returnsPushSummary(
        self, tempDbPath, stubApiKey, noSleep
    ) -> None:
        client = SyncClient(
            _baseConfig(tempDbPath),
            httpOpener=_successOpener(),
            sleep=noSleep,
        )

        summary = client.forcePush()

        assert isinstance(summary, PushSummary)
        assert summary.elapsed > 0

    def test_summaryCountsMatchPerTableStatuses(
        self, tempDbPath, stubApiKey, noSleep
    ) -> None:
        client = SyncClient(
            _baseConfig(tempDbPath),
            httpOpener=_successOpener(),
            sleep=noSleep,
        )

        summary = client.forcePush()

        tableCount = len(summary.results)
        assert tableCount == len(sync_log.IN_SCOPE_TABLES)

        manualOk = sum(
            1 for r in summary.results if r.status == PushStatus.OK
        )
        manualEmpty = sum(
            1 for r in summary.results if r.status == PushStatus.EMPTY
        )
        manualSkipped = sum(
            1 for r in summary.results if r.status == PushStatus.SKIPPED
        )
        manualFailed = sum(
            1 for r in summary.results if r.status == PushStatus.FAILED
        )

        assert summary.tablesOk == manualOk
        assert summary.tablesEmpty == manualEmpty
        assert summary.tablesSkipped == manualSkipped
        assert summary.tablesFailed == manualFailed

    def test_rowsPushedSumsAcrossOkResults(
        self, tempDbPath, stubApiKey, noSleep
    ) -> None:
        client = SyncClient(
            _baseConfig(tempDbPath),
            httpOpener=_successOpener(),
            sleep=noSleep,
        )

        summary = client.forcePush()

        manualRows = sum(
            r.rowsPushed for r in summary.results if r.status == PushStatus.OK
        )
        assert summary.rowsPushed == manualRows
        # realtime_data had 5 rows seeded -- that path should OK + sum.
        assert summary.rowsPushed == 5


# ================================================================================
# Disabled companion service
# ================================================================================


class TestDisabledCompanion:
    def test_disabledService_returnsDisabledTrueSummary(
        self, tempDbPath, noSleep
    ) -> None:
        # enabled=False -> SyncClient accepts without resolving the
        # API key; pushDelta short-circuits to DISABLED.
        client = SyncClient(
            _baseConfig(tempDbPath, enabled=False),
            httpOpener=_successOpener(),
            sleep=noSleep,
        )

        summary = client.forcePush()

        assert summary.disabled is True
        assert summary.rowsPushed == 0
        assert summary.tablesOk == 0

    def test_disabledService_makesNoHttpCalls(
        self, tempDbPath, noSleep
    ) -> None:
        opener = _successOpener()
        client = SyncClient(
            _baseConfig(tempDbPath, enabled=False),
            httpOpener=opener,
            sleep=noSleep,
        )

        client.forcePush()

        assert opener.calls == []


# ================================================================================
# AUTH + timeout propagation
# ================================================================================


class TestAuthAndTimeoutRespected:
    def test_forcePush_addsApiKeyHeader(
        self, tempDbPath, stubApiKey, noSleep
    ) -> None:
        opener = _successOpener()
        client = SyncClient(
            _baseConfig(tempDbPath),
            httpOpener=opener,
            sleep=noSleep,
        )

        client.forcePush()

        # Every non-skipped, non-empty call carries the X-API-Key
        # header.  At least one call should fire (realtime_data had 5
        # rows).
        assert len(opener.calls) >= 1
        req, _timeout = opener.calls[0]
        # urllib.request.Request stores headers with canonical
        # capitalization; read via .headers.
        assert req.get_header('X-api-key') == stubApiKey

    def test_forcePush_passesConfiguredTimeout(
        self, tempDbPath, stubApiKey, noSleep
    ) -> None:
        opener = _successOpener()
        cfg = _baseConfig(tempDbPath)
        cfg['pi']['companionService']['syncTimeoutSeconds'] = 7
        client = SyncClient(cfg, httpOpener=opener, sleep=noSleep)

        client.forcePush()

        assert len(opener.calls) >= 1
        _req, timeout = opener.calls[0]
        assert timeout == 7


# ================================================================================
# Failure isolation
# ================================================================================


class TestFailureIsolation:
    def test_allFail_summaryReportsFailuresButClientSurvives(
        self, tempDbPath, stubApiKey, noSleep
    ) -> None:
        client = SyncClient(
            _baseConfig(tempDbPath),
            httpOpener=_alwaysFailOpener(500),
            sleep=noSleep,
        )

        summary = client.forcePush()

        # Only the table with actual rows (realtime_data) can FAIL;
        # all others are EMPTY or SKIPPED and never touch the opener.
        assert summary.tablesFailed >= 1
        assert summary.rowsPushed == 0

    def test_failedPushDoesNotAdvanceHighWaterMark(
        self, tempDbPath, stubApiKey, noSleep
    ) -> None:
        # Baseline HWM is 0.
        conn = sqlite3.connect(tempDbPath)
        sync_log.initDb(conn)
        lastId, *_ = sync_log.getHighWaterMark(conn, 'realtime_data')
        conn.close()
        assert lastId == 0

        client = SyncClient(
            _baseConfig(tempDbPath),
            httpOpener=_alwaysFailOpener(500),
            sleep=noSleep,
        )
        client.forcePush()

        conn = sqlite3.connect(tempDbPath)
        lastId2, *_ = sync_log.getHighWaterMark(conn, 'realtime_data')
        conn.close()
        assert lastId2 == 0  # unchanged (invariant #2 from US-149)
