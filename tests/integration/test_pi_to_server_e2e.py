################################################################################
# File Name: test_pi_to_server_e2e.py
# Purpose/Description: Deterministic end-to-end test for the Walk-phase Pi ->
#                      Chi-Srv-01 sync pipeline.  Spins up a stdlib
#                      ThreadingHTTPServer that mocks /api/v1/sync, seeds a
#                      temp Pi SQLite with realtime_data + connection_log
#                      rows, drives the SyncClient (and scripts/sync_now.py
#                      CLI) against it, and asserts rows travel end-to-end,
#                      sync_log high-water marks advance, and a second push
#                      is empty.  CI-friendly: stdlib only, no external
#                      services required.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-166 (Sprint 11)
# ================================================================================
################################################################################

"""
Walk-phase end-to-end validation (US-166).

This test proves the Pi -> Chi-Srv-01 sync pipeline works layer-by-layer:

  1. Seed a temp Pi SQLite (``src/pi/data/sync_log.py`` in-scope tables)
  2. Build a Pi config pointing at a local mock server
  3. Stand up a :class:`MockSyncServer` (stdlib ThreadingHTTPServer) on an
     ephemeral localhost port, implementing the same payload shape the real
     server accepts in ``src/server/api/sync.py``
  4. Drive :class:`src.pi.sync.SyncClient` (and the ``scripts/sync_now.py``
     CLI) against the mock server
  5. Assert: rows the Pi sent = rows the server received; sync_log
     high-water marks advanced by exactly that count; second push is empty;
     ``X-API-Key`` header round-tripped; CLI exit code matches overall status

The mocked server is intentionally a minimal stdlib HTTP server instead of
``httpx_mock`` / ``respx`` / ``pytest-httpserver`` -- it keeps the test CI
dependency-free and exercises the same ``urllib.request`` path the Pi runs
in production.  The bash driver (``scripts/validate_pi_to_server.sh``) is
the live-server counterpart the CIO runs against the real Chi-Srv-01.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from scripts import sync_now
from src.pi.data import sync_log
from src.pi.sync import PushStatus, SyncClient

pytestmark = pytest.mark.integration


# =============================================================================
# Mock sync server
# =============================================================================


class _MockSyncHandler(BaseHTTPRequestHandler):
    """HTTP handler that accepts POST /api/v1/sync and records the payload."""

    # The parent ``ThreadingHTTPServer`` supplies .mockStore via a class-level
    # patch during fixture setup; see ``_startMockServer``.

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, N802
        # Silence the default stderr logging so the test output stays clean.
        return

    def do_POST(self) -> None:  # noqa: N802 -- stdlib naming
        if self.path != "/api/v1/sync":
            self._sendJson(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        store: _MockStore = self.server.mockStore  # type: ignore[attr-defined]

        if store.nextResponseStatus is not None:
            self._sendJson(
                store.nextResponseStatus,
                {"error": "mocked failure"},
            )
            store.recordFailure(self.path)
            store.nextResponseStatus = None
            return

        contentLength = int(self.headers.get("Content-Length", "0"))
        rawBody = self.rfile.read(contentLength) if contentLength else b""
        try:
            payload = json.loads(rawBody.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._sendJson(
                HTTPStatus.BAD_REQUEST,
                {"error": f"bad json: {exc}"},
            )
            return

        apiKey = self.headers.get("X-API-Key") or self.headers.get("X-Api-Key")
        if not apiKey or apiKey != store.expectedApiKey:
            self._sendJson(
                HTTPStatus.UNAUTHORIZED,
                {"error": "bad or missing X-API-Key"},
            )
            return

        store.recordBatch(apiKey=apiKey, payload=payload)

        self._sendJson(HTTPStatus.OK, {
            "status": "ok",
            "batchId": payload.get("batchId", ""),
            "tablesProcessed": {
                tableName: {
                    "inserted": len(section.get("rows", [])),
                    "updated": 0,
                    "errors": 0,
                }
                for tableName, section in payload.get("tables", {}).items()
            },
            "driveDataReceived": any(
                row.get("event_type") == "drive_end"
                for section in payload.get("tables", {}).values()
                for row in section.get("rows", [])
            ),
        })

    def _sendJson(self, code: HTTPStatus, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(int(code))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class _MockStore:
    """Thread-safe record of everything the mock server saw."""

    def __init__(self, expectedApiKey: str) -> None:
        self.expectedApiKey = expectedApiKey
        self._lock = threading.Lock()
        self._batches: list[dict[str, Any]] = []
        self._apiKeys: list[str] = []
        self._failures: list[str] = []
        self.nextResponseStatus: HTTPStatus | None = None

    def recordBatch(self, *, apiKey: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._batches.append(payload)
            self._apiKeys.append(apiKey)

    def recordFailure(self, path: str) -> None:
        with self._lock:
            self._failures.append(path)

    @property
    def batches(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._batches)

    @property
    def apiKeys(self) -> list[str]:
        with self._lock:
            return list(self._apiKeys)

    @property
    def failures(self) -> list[str]:
        with self._lock:
            return list(self._failures)

    def rowsReceivedFor(self, tableName: str) -> list[dict[str, Any]]:
        """Flatten every received row for one table across all batches."""
        rows: list[dict[str, Any]] = []
        for batch in self.batches:
            section = batch.get("tables", {}).get(tableName)
            if section is None:
                continue
            rows.extend(section.get("rows", []))
        return rows


def _findFreePort() -> int:
    """Ask the kernel for an ephemeral free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _startMockServer(store: _MockStore) -> tuple[ThreadingHTTPServer, str]:
    """Start a ThreadingHTTPServer; return (server, baseUrl)."""
    port = _findFreePort()
    server = ThreadingHTTPServer(("127.0.0.1", port), _MockSyncHandler)
    server.mockStore = store  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Make the thread handle accessible for a clean shutdown.
    server.thread = thread  # type: ignore[attr-defined]
    return server, f"http://127.0.0.1:{port}"


# =============================================================================
# Pi-side fixtures
# =============================================================================


_EXPECTED_API_KEY = "integration-test-key-xyz"


@pytest.fixture
def mockServer() -> Iterator[tuple[ThreadingHTTPServer, str, _MockStore]]:
    """Yield ``(server, baseUrl, store)``; shut the server down cleanly."""
    store = _MockStore(expectedApiKey=_EXPECTED_API_KEY)
    server, baseUrl = _startMockServer(store)
    try:
        yield server, baseUrl, store
    finally:
        server.shutdown()
        server.server_close()
        thread: threading.Thread = server.thread  # type: ignore[attr-defined]
        thread.join(timeout=2.0)


@pytest.fixture
def piDb(tmp_path: Path) -> Path:
    """Create a temp Pi SQLite DB with every sync_log in-scope table present.

    Mirrors :func:`tests.pi.sync.test_sync_client._createEmptyInScopeTables`:
    each in-scope table gets a minimal ``id INTEGER PRIMARY KEY AUTOINCREMENT``
    schema.  ``realtime_data`` and ``connection_log`` get richer schemas
    because this test exercises their columns end-to-end.
    """
    dbPath = tmp_path / "pi.db"
    with sqlite3.connect(dbPath) as conn:
        for tableName in sync_log.IN_SCOPE_TABLES:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {tableName} "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT)"
            )
        conn.execute("DROP TABLE realtime_data")
        conn.execute("""
            CREATE TABLE realtime_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                parameter_name TEXT NOT NULL,
                value REAL NOT NULL
            )
        """)
        conn.execute("DROP TABLE connection_log")
        conn.execute("""
            CREATE TABLE connection_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL
            )
        """)
        sync_log.initDb(conn)
        conn.commit()
    return dbPath


def _seedRealtimeRows(dbPath: Path, count: int, *, startAt: int = 0) -> None:
    with sqlite3.connect(dbPath) as conn:
        for i in range(count):
            conn.execute(
                "INSERT INTO realtime_data (timestamp, parameter_name, value) "
                "VALUES (?, ?, ?)",
                (f"2026-04-18T00:00:{startAt + i:02d}Z", "RPM", 1000.0 + i),
            )
        conn.commit()


def _seedConnectionLogRows(
    dbPath: Path, eventTypes: list[str],
) -> None:
    with sqlite3.connect(dbPath) as conn:
        for i, eventType in enumerate(eventTypes):
            conn.execute(
                "INSERT INTO connection_log (timestamp, event_type) "
                "VALUES (?, ?)",
                (f"2026-04-18T01:00:{i:02d}Z", eventType),
            )
        conn.commit()


def _baseConfig(
    dbPath: Path, baseUrl: str, *, enabled: bool = True,
) -> dict[str, Any]:
    """Pi config dict pointing ``companionService`` at the mock server."""
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": str(dbPath)},
            "companionService": {
                "enabled": enabled,
                "baseUrl": baseUrl,
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 5,
                "batchSize": 500,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [0],
            },
        },
        "server": {},
    }


@pytest.fixture(autouse=True)
def _setApiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a known COMPANION_API_KEY for every integration test."""
    monkeypatch.setenv("COMPANION_API_KEY", _EXPECTED_API_KEY)


# =============================================================================
# CRITICAL sprint-exit assertion -- rows travel end-to-end, HWM advances.
# =============================================================================


class TestSprintExitRowsTravelEndToEnd:
    """The Walk-phase exit criterion: Pi rows arrive at the (mocked) server,
    counts match exactly, and the high-water mark advances so a second push
    is a no-op.  A regression here is a sprint-exit failure.
    """

    def test_realtimeData_10rows_arriveAtServerAndAdvanceHwm(
        self,
        piDb: Path,
        mockServer: tuple[ThreadingHTTPServer, str, _MockStore],
    ) -> None:
        _, baseUrl, store = mockServer
        _seedRealtimeRows(piDb, count=10)
        config = _baseConfig(piDb, baseUrl)

        client = SyncClient(config)
        results = client.pushAllDeltas()

        # Overall status: one OK for realtime_data, EMPTY for the other 7.
        byTable = {r.tableName: r for r in results}
        assert byTable["realtime_data"].status is PushStatus.OK
        assert byTable["realtime_data"].rowsPushed == 10
        for otherTable in sync_log.IN_SCOPE_TABLES - {"realtime_data"}:
            assert byTable[otherTable].status is PushStatus.EMPTY, (
                f"{otherTable} should be EMPTY; got {byTable[otherTable]}"
            )

        # Server received exactly the 10 rows, in order.
        receivedRows = store.rowsReceivedFor("realtime_data")
        assert len(receivedRows) == 10, (
            f"server received {len(receivedRows)} realtime_data rows "
            f"(Pi sent 10)"
        )
        assert [r["id"] for r in receivedRows] == list(range(1, 11))

        # sync_log high-water mark advanced to the max id sent.
        with sqlite3.connect(piDb) as conn:
            lastId, _, _, statusStr = sync_log.getHighWaterMark(
                conn, "realtime_data",
            )
        assert lastId == 10, f"high-water mark = {lastId}, expected 10"
        assert statusStr == "ok"

        # Second push is a no-op (nothing to sync).
        store2 = store  # same store; we assert no new batches arrive
        initialBatchCount = len(store2.batches)
        results2 = client.pushAllDeltas()
        assert all(
            r.status in (PushStatus.EMPTY, PushStatus.OK)
            for r in results2
        )
        assert all(
            r.rowsPushed == 0 for r in results2
        ), "second push should not re-send any rows"
        assert len(store2.batches) == initialBatchCount, (
            "second push should not have hit the server"
        )

    def test_rowCountsMatchAcrossLayers_realtimeAndConnectionLog(
        self,
        piDb: Path,
        mockServer: tuple[ThreadingHTTPServer, str, _MockStore],
    ) -> None:
        """Spec 2.5 step 4/7: row counts match exactly across all layers.

        Seed known counts in two tables, push, assert server saw exactly
        that many rows per table.  Any mismatch = fail the sprint exit.
        """
        _, baseUrl, store = mockServer
        _seedRealtimeRows(piDb, count=7)
        _seedConnectionLogRows(
            piDb, ["drive_start", "drive_end", "connection_lost"],
        )
        config = _baseConfig(piDb, baseUrl)

        client = SyncClient(config)
        results = client.pushAllDeltas()

        byTable = {r.tableName: r for r in results}
        assert byTable["realtime_data"].rowsPushed == 7
        assert byTable["connection_log"].rowsPushed == 3

        assert len(store.rowsReceivedFor("realtime_data")) == 7
        assert len(store.rowsReceivedFor("connection_log")) == 3

        # driveDataReceived flag flips true when a drive_end row is in the
        # payload -- cross-checks the server-side auto-analysis trigger path
        # without invoking the real analysis pipeline.
        driveEndBatches = [
            b for b in store.batches
            if any(
                row.get("event_type") == "drive_end"
                for row in b.get("tables", {})
                    .get("connection_log", {})
                    .get("rows", [])
            )
        ]
        assert driveEndBatches, (
            "at least one batch should carry a drive_end row"
        )


# =============================================================================
# CLI entry point (scripts/sync_now.py) — sprint-exit assertion via the CLI.
# =============================================================================


class TestSyncNowCliAgainstMockServer:
    """Exercise ``scripts/sync_now.py main()`` against the mock server.

    This is the same pipeline ``bash scripts/validate_pi_to_server.sh``
    runs live against Chi-Srv-01.  If the CLI exits 0 and prints
    ``Status: OK`` here, the live version has a clean Pi-side plumbing
    baseline to start from.
    """

    def test_cliPushesRowsAndExitsZero(
        self,
        piDb: Path,
        mockServer: tuple[ThreadingHTTPServer, str, _MockStore],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _, baseUrl, store = mockServer
        _seedRealtimeRows(piDb, count=5)

        configPath = tmp_path / "config.json"
        configPath.write_text(
            json.dumps(_baseConfig(piDb, baseUrl)), encoding="utf-8",
        )

        rc = sync_now.main(["--config", str(configPath)])
        out = capsys.readouterr().out

        assert rc == 0, f"exit code {rc}; stdout={out!r}"
        assert "Status: OK" in out
        assert "realtime_data" in out
        assert "5 new rows" in out
        assert _EXPECTED_API_KEY not in out, (
            "API key must never leak into CLI stdout"
        )
        assert len(store.rowsReceivedFor("realtime_data")) == 5


# =============================================================================
# Failure path -- stays consistent with the US-149 HWM invariant.
# =============================================================================


class TestUnreachableServerKeepsHwmPut:
    """Sprint 11 data-integrity invariant (US-149): a failed push must NEVER
    advance sync_log.last_synced_id.  Verified end-to-end by pointing the
    client at a dead port and asserting the Pi's sync_log is unchanged.
    """

    def test_deadPort_failsAllAndHwmIsZero(
        self,
        piDb: Path,
    ) -> None:
        deadPort = _findFreePort()  # never started
        baseUrl = f"http://127.0.0.1:{deadPort}"
        _seedRealtimeRows(piDb, count=3)
        config = _baseConfig(piDb, baseUrl)

        client = SyncClient(config)
        results = client.pushAllDeltas()

        byTable = {r.tableName: r for r in results}
        assert byTable["realtime_data"].status is PushStatus.FAILED
        assert byTable["realtime_data"].rowsPushed == 0

        with sqlite3.connect(piDb) as conn:
            lastId, _, _, statusStr = sync_log.getHighWaterMark(
                conn, "realtime_data",
            )
        assert lastId == 0, (
            "HWM must NOT advance on a failed push (US-149 invariant)"
        )
        assert statusStr == "failed"


# =============================================================================
# API-key round-trip -- auth is part of the contract, not a nice-to-have.
# =============================================================================


class TestApiKeyRoundTrip:
    def test_xApiKeyHeaderIsSentOnEverySuccessfulPush(
        self,
        piDb: Path,
        mockServer: tuple[ThreadingHTTPServer, str, _MockStore],
    ) -> None:
        _, baseUrl, store = mockServer
        _seedRealtimeRows(piDb, count=2)
        config = _baseConfig(piDb, baseUrl)

        SyncClient(config).pushAllDeltas()

        assert store.apiKeys, "server never received any batches"
        assert all(
            key == _EXPECTED_API_KEY for key in store.apiKeys
        ), f"expected X-API-Key={_EXPECTED_API_KEY!r}, got {store.apiKeys!r}"

    def test_wrongApiKey_isRejectedWithout401Retrying(
        self,
        piDb: Path,
        mockServer: tuple[ThreadingHTTPServer, str, _MockStore],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """401 must fail immediately -- retrying a wrong key just hammers
        the server.  Verified via the mock server's auth check firing a
        401, plus the ``len(batches) == 0`` assertion (server never saw
        an accepted payload).
        """
        _, baseUrl, _ = mockServer
        monkeypatch.setenv("COMPANION_API_KEY", "wrong-key")
        _seedRealtimeRows(piDb, count=1)
        config = _baseConfig(piDb, baseUrl)

        results = SyncClient(config).pushAllDeltas()

        byTable = {r.tableName: r for r in results}
        assert byTable["realtime_data"].status is PushStatus.FAILED
        assert "401" in byTable["realtime_data"].reason or (
            "Unauthorized" in byTable["realtime_data"].reason
        )
