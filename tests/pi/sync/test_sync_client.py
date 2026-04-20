################################################################################
# File Name: test_sync_client.py
# Purpose/Description: Outcome-based tests for the Pi HTTP SyncClient (US-149),
#                      with the CRITICAL failure-path invariant first.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-149
# ================================================================================
################################################################################

"""
Tests for :mod:`src.pi.sync.client`.

The sprint invariant for US-149 is that a failed push NEVER advances
``sync_log.last_synced_id``.  The failure-path tests are intentionally at
the top of this file so that if the impl regresses, the first failing test
a reader sees is the data-integrity guarantee -- not a stylistic edge case.

All tests mock the HTTP boundary by injecting a fake ``httpOpener`` callable
into :class:`SyncClient`.  No sockets are opened.  Backoff sleeps are also
stubbed so retry tests finish in milliseconds.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import urllib.error
from collections.abc import Callable
from typing import Any

import pytest

from src.common.errors.handler import ConfigurationError
from src.pi.data import sync_log
from src.pi.sync import PushStatus, SyncClient

# =============================================================================
# Helpers / fixtures
# =============================================================================


def _createEmptyInScopeTables(conn: sqlite3.Connection) -> None:
    """Create minimal stand-ins for every IN_SCOPE_TABLES entry.

    Production parity: the Pi creates all 8 tables at boot (via ObdDatabase).
    Tests that exercise :meth:`SyncClient.pushAllDeltas` need the same
    surface so the client can iterate without tripping
    ``OperationalError: no such table``.

    US-194 update: each stub uses its PRODUCTION primary-key column so
    the per-table PK registry path exercises correctly.  Most delta
    tables use ``id``; calibration_sessions uses ``session_id``; the
    snapshot tables (profiles, vehicle_info) use TEXT natural PKs.
    """
    for tableName in sync_log.IN_SCOPE_TABLES:
        if tableName in sync_log.SNAPSHOT_TABLES:
            # TEXT natural PK -- never queried via delta-by-PK path.
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
    """Replace the stub realtime_data with the richer schema used in tests."""
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
    """Append ``n`` realtime_data rows, preserving existing ids.

    Assumes :func:`_installRealtimeSchema` has already run (fixture does
    this on setup).  Safe to call repeatedly within a test.
    """
    for i in range(n):
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES (?, ?, ?)",
            (f"2026-04-18T00:00:{i:02d}Z", "RPM", 1000.0 + i),
        )
    conn.commit()


def _baseConfig(dbPath: str, *, enabled: bool = True) -> dict[str, Any]:
    """Build a minimal but realistic Pi config dict."""
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
def tempDbPath() -> str:
    """Temp file-backed SQLite DB with sync_log + realtime_data ready."""
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
def noSleep(monkeypatch: pytest.MonkeyPatch) -> Callable[[float], None]:
    """Provide a sleep stub that records calls without actually sleeping."""
    calls: list[float] = []

    def _record(seconds: float) -> None:
        calls.append(float(seconds))

    _record.calls = calls  # type: ignore[attr-defined]
    return _record


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    """Populate COMPANION_API_KEY for the duration of the test."""
    key = "test-key-abcdef"
    monkeypatch.setenv("COMPANION_API_KEY", key)
    return key


class _FakeResponse:
    """Minimal context-manager wrapper that mimics ``urllib`` response."""

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
    """Opener that returns 200 OK for every call and records the request."""
    calls: list[Any] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append((req, timeout))
        return _FakeResponse(body=b'{"status":"ok"}', status=200)

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


def _httpErrorOpener(code: int, reason: str = "Server Error") -> Callable[..., Any]:
    """Opener that always raises ``urllib.error.HTTPError`` with ``code``."""
    calls: list[int] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append(code)
        raise urllib.error.HTTPError(
            url=getattr(req, "full_url", "http://test/"),
            code=code,
            msg=reason,
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


def _timeoutOpener() -> Callable[..., Any]:
    """Opener that always raises ``TimeoutError`` (aka ``socket.timeout``)."""
    calls: list[int] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append(1)
        raise TimeoutError("timed out")

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


def _urlErrorOpener() -> Callable[..., Any]:
    """Opener that always raises ``urllib.error.URLError`` (connection refused)."""
    calls: list[int] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append(1)
        raise urllib.error.URLError("Connection refused")

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


# =============================================================================
# CRITICAL INVARIANT: failed push must NEVER advance the high-water mark.
# =============================================================================


class TestCriticalInvariantFailedPushDoesNotAdvanceHighWaterMark:
    """Sprint-flagged data-integrity tests.  Go first, read first.

    If any of these fails, the bug is load-bearing -- a silent
    high-water-mark advance after a failed push means rows on the Pi are
    marked 'synced' but never reached the server, and they are lost if the
    Pi SQLite is reset before the next successful sync.
    """

    def test_500Error_failsAllRetries_hwmNotAdvanced(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _httpErrorOpener(code=500, reason="Internal Server Error")
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        result = client.pushDelta("realtime_data")

        assert result.status == PushStatus.FAILED
        assert result.rowsPushed == 0
        assert "500" in result.reason

        # Attempted 1 + retryMaxAttempts = 4 times with delays [1,2,4].
        assert len(opener.calls) == 4  # type: ignore[attr-defined]
        assert noSleep.calls == [1.0, 2.0, 4.0]  # type: ignore[attr-defined]

        # The high-water mark id did NOT advance past 0.
        with sqlite3.connect(tempDbPath) as conn:
            lastId, _ts, lastBatch, status = sync_log.getHighWaterMark(
                conn, "realtime_data",
            )
        assert lastId == 0, (
            f"HWM advanced to {lastId} after failed push -- DATA LOSS RISK"
        )
        assert status == "failed"
        assert lastBatch == result.batchId  # diagnostic trace kept

    def test_timeout_failsAllRetries_hwmNotAdvanced(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _timeoutOpener()
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        result = client.pushDelta("realtime_data")

        assert result.status == PushStatus.FAILED
        assert result.rowsPushed == 0
        assert "timeout" in result.reason.lower()

        with sqlite3.connect(tempDbPath) as conn:
            lastId, _, _, status = sync_log.getHighWaterMark(conn, "realtime_data")
        assert lastId == 0
        assert status == "failed"

    def test_connectionRefused_failsAllRetries_hwmNotAdvanced(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _urlErrorOpener()
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        result = client.pushDelta("realtime_data")

        assert result.status == PushStatus.FAILED
        with sqlite3.connect(tempDbPath) as conn:
            lastId, _, _, status = sync_log.getHighWaterMark(conn, "realtime_data")
        assert lastId == 0
        assert status == "failed"

    def test_401_failsImmediately_hwmNotAdvanced_noRetry(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _httpErrorOpener(code=401, reason="Unauthorized")
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        result = client.pushDelta("realtime_data")

        assert result.status == PushStatus.FAILED
        # No retries on 4xx (except 429): exactly ONE call to the opener.
        assert len(opener.calls) == 1  # type: ignore[attr-defined]
        assert noSleep.calls == []  # type: ignore[attr-defined]

        with sqlite3.connect(tempDbPath) as conn:
            lastId, _, _, status = sync_log.getHighWaterMark(conn, "realtime_data")
        assert lastId == 0
        assert status == "failed"

    def test_403_failsImmediately_hwmNotAdvanced_noRetry(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _httpErrorOpener(code=403, reason="Forbidden")
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        result = client.pushDelta("realtime_data")

        assert result.status == PushStatus.FAILED
        assert len(opener.calls) == 1  # type: ignore[attr-defined]

        with sqlite3.connect(tempDbPath) as conn:
            lastId, _, _, _ = sync_log.getHighWaterMark(conn, "realtime_data")
        assert lastId == 0


# =============================================================================
# 429 retry semantics
# =============================================================================


class TestRateLimitRetry:

    def test_429_retriesWithBackoff_thenFailsIfPersistent(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _httpErrorOpener(code=429, reason="Too Many Requests")
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        result = client.pushDelta("realtime_data")

        assert result.status == PushStatus.FAILED
        assert len(opener.calls) == 4  # type: ignore[attr-defined]
        assert noSleep.calls == [1.0, 2.0, 4.0]  # type: ignore[attr-defined]

    def test_429ThenSuccess_advancesHwmAndStopsRetrying(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        attempts = [0]

        def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
            attempts[0] += 1
            if attempts[0] == 1:
                raise urllib.error.HTTPError(
                    url="http://test/sync",
                    code=429, msg="slow down",
                    hdrs=None,  # type: ignore[arg-type]
                    fp=io.BytesIO(b""),
                )
            return _FakeResponse(body=b'{"status":"ok"}', status=200)

        client = SyncClient(config, httpOpener=_opener, sleep=noSleep)
        result = client.pushDelta("realtime_data")

        assert result.status == PushStatus.OK
        assert result.rowsPushed == 5
        assert attempts[0] == 2  # 1 fail + 1 success
        assert noSleep.calls == [1.0]  # type: ignore[attr-defined]

        with sqlite3.connect(tempDbPath) as conn:
            lastId, _, lastBatch, status = sync_log.getHighWaterMark(
                conn, "realtime_data",
            )
        assert lastId == 5
        assert status == "ok"
        assert lastBatch == result.batchId


# =============================================================================
# Success path
# =============================================================================


class TestSuccessPath:

    def test_pushDelta_200_advancesHwmToMaxId_andReturnsOk(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _successOpener()
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        result = client.pushDelta("realtime_data")

        assert result.status == PushStatus.OK
        assert result.rowsPushed == 5
        assert result.tableName == "realtime_data"
        assert result.batchId.startswith("chi-eclipse-01-")

        with sqlite3.connect(tempDbPath) as conn:
            lastId, _, lastBatch, status = sync_log.getHighWaterMark(
                conn, "realtime_data",
            )
        assert lastId == 5
        assert status == "ok"
        assert lastBatch == result.batchId

    def test_twoCyclesSuccess_secondOnlyShipsNewRows(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        """Advance HWM on cycle 1; cycle 2 sees only rows with id > 5."""
        config = _baseConfig(tempDbPath)
        opener = _successOpener()
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        first = client.pushDelta("realtime_data")
        assert first.status == PushStatus.OK
        assert first.rowsPushed == 5

        # Append 3 more rows; only those should be shipped next time.
        with sqlite3.connect(tempDbPath) as conn:
            _writeRealtimeRows(conn, 3)

        second = client.pushDelta("realtime_data")
        assert second.status == PushStatus.OK
        assert second.rowsPushed == 3

        # Verify the second request only contained rows with id > 5.
        secondRequest = opener.calls[-1][0]  # type: ignore[attr-defined]
        body = json.loads(secondRequest.data.decode("utf-8"))
        sentIds = [row["id"] for row in body["tables"]["realtime_data"]["rows"]]
        assert min(sentIds) > 5

        with sqlite3.connect(tempDbPath) as conn:
            lastId, _, _, _ = sync_log.getHighWaterMark(conn, "realtime_data")
        assert lastId == 8

    def test_requestPayload_hasExpectedShape(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _successOpener()
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        client.pushDelta("realtime_data")

        req = opener.calls[-1][0]  # type: ignore[attr-defined]
        assert req.full_url == "http://10.27.27.10:8000/api/v1/sync"
        assert req.get_method() == "POST"
        headers = dict(req.header_items())
        assert headers.get("X-api-key") == stubApiKey
        assert headers.get("Content-type") == "application/json"
        body = json.loads(req.data.decode("utf-8"))
        assert body["deviceId"] == "chi-eclipse-01"
        assert body["batchId"].startswith("chi-eclipse-01-")
        assert "realtime_data" in body["tables"]
        assert len(body["tables"]["realtime_data"]["rows"]) == 5
        assert body["tables"]["realtime_data"]["lastSyncedId"] == 0


# =============================================================================
# Disabled / empty / all-deltas
# =============================================================================


class TestDisabledAndEmpty:

    def test_disabledConfig_returnsDisabled_noNetworkCall(
        self, tempDbPath: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath, enabled=False)
        opener = _successOpener()
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        result = client.pushDelta("realtime_data")

        assert result.status == PushStatus.DISABLED
        assert result.rowsPushed == 0
        assert len(opener.calls) == 0  # type: ignore[attr-defined]

        # HWM unchanged (not even rewritten).
        with sqlite3.connect(tempDbPath) as conn:
            lastId, _, _, status = sync_log.getHighWaterMark(conn, "realtime_data")
        assert lastId == 0
        assert status == "pending"

    def test_emptyDelta_returnsEmpty_noNetworkCall(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _successOpener()
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        # First push clears all 5 seed rows.
        first = client.pushDelta("realtime_data")
        assert first.rowsPushed == 5

        # Second push has nothing to send.
        second = client.pushDelta("realtime_data")
        assert second.status == PushStatus.EMPTY
        assert second.rowsPushed == 0
        # One call total (for the first push only).
        assert len(opener.calls) == 1  # type: ignore[attr-defined]

    def test_pushAllDeltas_returnsOneResultPerInScopeTable(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        opener = _successOpener()
        client = SyncClient(config, httpOpener=opener, sleep=noSleep)

        results = client.pushAllDeltas()

        assert len(results) == len(sync_log.IN_SCOPE_TABLES)
        returnedTables = {r.tableName for r in results}
        assert returnedTables == sync_log.IN_SCOPE_TABLES

        # Only realtime_data has rows in our fixture DB.
        byTable = {r.tableName: r for r in results}
        assert byTable["realtime_data"].status == PushStatus.OK
        assert byTable["realtime_data"].rowsPushed == 5
        # US-194: snapshot tables surface as SKIPPED (they do not fit
        # the delta-by-PK model); the remaining delta tables are empty.
        for tableName in sync_log.SNAPSHOT_TABLES:
            assert byTable[tableName].status == PushStatus.SKIPPED
        for tableName in (
            sync_log.IN_SCOPE_TABLES
            - sync_log.SNAPSHOT_TABLES
            - {"realtime_data"}
        ):
            # Other delta tables are present but empty.
            assert byTable[tableName].status == PushStatus.EMPTY


# =============================================================================
# Construction / config surface
# =============================================================================


class TestConstruction:

    def test_missingApiKey_raisesConfigurationError(
        self, tempDbPath: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("COMPANION_API_KEY", raising=False)
        config = _baseConfig(tempDbPath)

        with pytest.raises(ConfigurationError) as exc:
            SyncClient(config)

        assert "COMPANION_API_KEY" in str(exc.value)

    def test_missingApiKey_okWhenDisabled(
        self, tempDbPath: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Disabled services don't need an API key (tests + dev environments)."""
        monkeypatch.delenv("COMPANION_API_KEY", raising=False)
        config = _baseConfig(tempDbPath, enabled=False)
        # Should not raise.
        client = SyncClient(config)
        assert client.isEnabled is False

    def test_missingDbPath_raisesConfigurationError(
        self, stubApiKey: str,  # noqa: ARG002
    ) -> None:
        config = {
            "deviceId": "chi-eclipse-01",
            "pi": {"companionService": {"enabled": True}},
        }
        with pytest.raises(ConfigurationError) as exc:
            SyncClient(config)
        assert "pi.database.path" in str(exc.value)

    def test_unknownTableName_raisesValueError(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        config = _baseConfig(tempDbPath)
        client = SyncClient(config, httpOpener=_successOpener(), sleep=noSleep)
        with pytest.raises(ValueError):
            client.pushDelta("malicious; DROP TABLE realtime_data;--")

    def test_injectedDbPath_overridesConfig(
        self, tempDbPath: str, stubApiKey: str, noSleep: Any,  # noqa: ARG002
    ) -> None:
        fd, otherPath = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(otherPath)
            sync_log.initDb(conn)
            _createEmptyInScopeTables(conn)
            _installRealtimeSchema(conn)
            _writeRealtimeRows(conn, 2)
            conn.close()

            config = _baseConfig(tempDbPath)
            client = SyncClient(
                config,
                dbPath=otherPath,
                httpOpener=_successOpener(),
                sleep=noSleep,
            )
            result = client.pushDelta("realtime_data")
            assert result.rowsPushed == 2
        finally:
            try:
                os.remove(otherPath)
            except OSError:
                pass
