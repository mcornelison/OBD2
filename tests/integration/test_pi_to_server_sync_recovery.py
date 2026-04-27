################################################################################
# File Name: test_pi_to_server_sync_recovery.py
# Purpose/Description: End-to-end integration test for US-226 sync recovery.
#                      Seeds a Pi SQLite with pending deltas, instantiates an
#                      ApplicationOrchestrator, fires the interval sync trigger,
#                      and asserts rows land on a stdlib mock server.  Catches
#                      the stranded-Drive-3 class of regression: "sync pipeline
#                      never runs".
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""US-226 sync-recovery integration test.

Scope: exercise the full orchestrator -> SyncClient -> mock server path
the runLoop takes when ``pi.sync`` is configured.  Distinct from
``test_pi_to_server_e2e.py`` (US-166), which drives SyncClient directly
without the orchestrator -- this test's value is proving the
*orchestrator-level* sync trigger actually runs.

Test path:

1. Seed a temp Pi SQLite with realtime_data + connection_log rows.
2. Stand up a local stdlib mock server that accepts POST /api/v1/sync.
3. Build a full (validator-walked) Pi config pointing at the mock.
4. Construct :class:`ApplicationOrchestrator` with ``simulate=True``.
5. Call ``_initializeSyncClient`` + ``_maybeTriggerIntervalSync``
   (bypasses the real runLoop so the test doesn't need to cancel a
   thread).
6. Assert: rows received on the server = rows pending on the Pi;
   sync_log high-water mark advanced; a second trigger within
   ``intervalSeconds`` is a no-op.

This is CI-friendly: stdlib HTTP server only, no external deps.
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

from pi.obdii.orchestrator.core import ApplicationOrchestrator
from src.common.config.validator import ConfigValidator
from src.pi.data import sync_log

pytestmark = pytest.mark.integration


# =============================================================================
# Mock sync server (minimal variant of test_pi_to_server_e2e's handler)
# =============================================================================


class _MockSyncHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, N802
        return  # silence default stderr logs

    def do_POST(self) -> None:  # noqa: N802
        store: _MockStore = self.server.mockStore  # type: ignore[attr-defined]
        if self.path != "/api/v1/sync":
            self._sendJson(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        apiKey = self.headers.get("X-API-Key") or self.headers.get("X-Api-Key")
        if not apiKey or apiKey != store.expectedApiKey:
            self._sendJson(HTTPStatus.UNAUTHORIZED, {"error": "bad api key"})
            return
        contentLength = int(self.headers.get("Content-Length", "0"))
        rawBody = self.rfile.read(contentLength) if contentLength else b""
        try:
            payload = json.loads(rawBody.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._sendJson(HTTPStatus.BAD_REQUEST, {"error": "bad json"})
            return
        store.recordBatch(payload=payload)
        tables = payload.get("tables", {})
        self._sendJson(HTTPStatus.OK, {
            "status": "ok",
            "batchId": payload.get("batchId", ""),
            "tablesProcessed": {
                t: {"inserted": len(s.get("rows", [])), "updated": 0, "errors": 0}
                for t, s in tables.items()
            },
        })

    def _sendJson(self, code: HTTPStatus, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(int(code))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class _MockStore:
    def __init__(self, expectedApiKey: str) -> None:
        self.expectedApiKey = expectedApiKey
        self._lock = threading.Lock()
        self._batches: list[dict[str, Any]] = []

    def recordBatch(self, *, payload: dict[str, Any]) -> None:
        with self._lock:
            self._batches.append(payload)

    @property
    def batches(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._batches)

    def rowsFor(self, tableName: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for batch in self.batches:
            section = batch.get("tables", {}).get(tableName)
            if section is None:
                continue
            rows.extend(section.get("rows", []))
        return rows


def _findFreePort() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


_EXPECTED_API_KEY = "recovery-test-key"


@pytest.fixture
def mockServer() -> Iterator[tuple[str, _MockStore]]:
    store = _MockStore(expectedApiKey=_EXPECTED_API_KEY)
    port = _findFreePort()
    server = ThreadingHTTPServer(("127.0.0.1", port), _MockSyncHandler)
    server.mockStore = store  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


# =============================================================================
# Pi-side fixture
# =============================================================================


@pytest.fixture
def piDb(tmp_path: Path) -> Path:
    """Temp Pi SQLite seeded with pending realtime_data + connection_log rows."""
    dbPath = tmp_path / "pi.db"
    with sqlite3.connect(dbPath) as conn:
        # Create every in-scope table at its canonical PK shape.
        for tableName in sync_log.IN_SCOPE_TABLES:
            if tableName in sync_log.SNAPSHOT_TABLES:
                pkColumn = "id" if tableName == "profiles" else "vin"
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
        # Seed 7 pending rows (mirroring Drive 3's "rows stranded" scenario).
        for i in range(7):
            conn.execute(
                "INSERT INTO realtime_data (timestamp, parameter_name, value) "
                "VALUES (?, ?, ?)",
                (f"2026-04-23T00:00:{i:02d}Z", "RPM", 1000.0 + i),
            )
        conn.execute(
            "INSERT INTO connection_log (timestamp, event_type) VALUES (?, ?)",
            ("2026-04-23T00:00:30Z", "drive_end"),
        )
        sync_log.initDb(conn)
        conn.commit()
    return dbPath


def _buildConfig(dbPath: Path, baseUrl: str) -> dict[str, Any]:
    raw = {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": str(dbPath)},
            "companionService": {
                "enabled": True,
                "baseUrl": baseUrl,
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 5,
                "batchSize": 500,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [1],
            },
            "sync": {
                "enabled": True,
                "intervalSeconds": 60,
                "triggerOn": ["interval", "drive_end"],
            },
        },
        "server": {},
    }
    return ConfigValidator().validate(raw)


# =============================================================================
# Tests
# =============================================================================


class TestSyncRecovery:
    def test_intervalTrigger_pushesPendingRowsToServer(
        self, piDb, mockServer, monkeypatch
    ) -> None:
        """Orchestrator interval trigger pushes pending deltas end-to-end."""
        monkeypatch.setenv("COMPANION_API_KEY", _EXPECTED_API_KEY)
        baseUrl, store = mockServer
        config = _buildConfig(piDb, baseUrl)

        orch = ApplicationOrchestrator(config=config, simulate=True)
        orch._initializeSyncClient()

        assert orch.syncClient is not None

        fired = orch._maybeTriggerIntervalSync()

        assert fired is True

        # All 7 rows must have landed on the server.
        receivedRealtime = store.rowsFor("realtime_data")
        assert len(receivedRealtime) == 7

        # connection_log event also synced.
        receivedConnLog = store.rowsFor("connection_log")
        assert len(receivedConnLog) == 1
        assert receivedConnLog[0]["event_type"] == "drive_end"

        # Sync_log high-water marks advanced on the Pi side.
        with sqlite3.connect(piDb) as conn:
            lastId, _, _, _ = sync_log.getHighWaterMark(conn, "realtime_data")
            assert lastId == 7

    def test_secondCall_withinInterval_isNoOp(
        self, piDb, mockServer, monkeypatch
    ) -> None:
        """Cadence gate: second interval tick within intervalSeconds skips."""
        monkeypatch.setenv("COMPANION_API_KEY", _EXPECTED_API_KEY)
        baseUrl, store = mockServer
        config = _buildConfig(piDb, baseUrl)
        orch = ApplicationOrchestrator(config=config, simulate=True)
        orch._initializeSyncClient()

        fired1 = orch._maybeTriggerIntervalSync()
        fired2 = orch._maybeTriggerIntervalSync()

        assert fired1 is True
        assert fired2 is False
        # Exactly one full set of batches (one per non-empty in-scope table).
        # Empirically 2 batches: realtime_data + connection_log (the only
        # seeded tables); every other in-scope table is EMPTY so no HTTP.
        assert len(store.batches) == 2

    def test_driveEndTrigger_pushesImmediately(
        self, piDb, mockServer, monkeypatch
    ) -> None:
        """Drive-end trigger fires a push outside the interval cadence."""
        monkeypatch.setenv("COMPANION_API_KEY", _EXPECTED_API_KEY)
        baseUrl, store = mockServer
        config = _buildConfig(piDb, baseUrl)
        orch = ApplicationOrchestrator(config=config, simulate=True)
        orch._initializeSyncClient()

        fired = orch.triggerDriveEndSync()

        assert fired is True
        assert len(store.rowsFor("realtime_data")) == 7

    def test_intervalFiresEvenWithoutDriveEnd(
        self, piDb, mockServer, monkeypatch
    ) -> None:
        """Invariant: interval sync works when drive_end trigger not configured."""
        monkeypatch.setenv("COMPANION_API_KEY", _EXPECTED_API_KEY)
        baseUrl, store = mockServer
        config = _buildConfig(piDb, baseUrl)
        config["pi"]["sync"]["triggerOn"] = ["interval"]  # interval only
        orch = ApplicationOrchestrator(config=config, simulate=True)
        orch._initializeSyncClient()

        fired = orch._maybeTriggerIntervalSync()

        assert fired is True
        assert len(store.rowsFor("realtime_data")) == 7
