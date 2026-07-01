################################################################################
# File Name: test_sync_client_snapshot.py
# Purpose/Description: Tests for SyncClient.pushSnapshot (US-416 / F-101) -- the
#                      natural-key snapshot-sync push. Verifies a successful push
#                      advances the time-cursor, a caught-up cursor yields EMPTY,
#                      a failed push does NOT advance the cursor (rows stay
#                      re-sendable), the disabled path, and the wire payload shape.
#                      HTTP boundary is mocked; no sockets opened.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-416) | Initial -- pushSnapshot cursor + failure tests.
# ================================================================================
################################################################################

"""Tests for :meth:`src.pi.sync.client.SyncClient.pushSnapshot` (US-416)."""

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

from src.common.sync.snapshot_registry import SNAPSHOT_SYNC, SnapshotSyncSpec
from src.pi.data import sync_log
from src.pi.sync import PushStatus, SyncClient

_TABLE = "test_startup_snap"


@pytest.fixture
def tempDbPath() -> str:
    """Temp SQLite DB with sync_log + a seeded registered snapshot table."""
    SNAPSHOT_SYNC[_TABLE] = SnapshotSyncSpec(
        naturalKeyCols=("boot_id",), cursorCol="recorded_at",
    )
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    sync_log.initDb(conn)
    conn.execute(
        f"CREATE TABLE {_TABLE} ("
        "  boot_id TEXT PRIMARY KEY,"
        "  recorded_at TEXT NOT NULL,"
        "  boot_reason TEXT"
        ")",
    )
    conn.executemany(
        f"INSERT INTO {_TABLE} (boot_id, recorded_at, boot_reason) VALUES (?, ?, ?)",
        [
            ("boot-a", "2026-07-01T10:00:00Z", "power_on"),
            ("boot-b", "2026-07-01T11:00:00Z", "power_on"),
        ],
    )
    conn.commit()
    conn.close()
    try:
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
        SNAPSHOT_SYNC.pop(_TABLE, None)


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key")
    return "test-key"


def _config(dbPath: str, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "companionService": {
                "enabled": enabled,
                "baseUrl": "http://10.27.27.120:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [1],
            },
        },
    }


class _FakeResponse:
    def __init__(self, body: bytes = b"{}") -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _successOpener() -> Callable[..., Any]:
    calls: list[Any] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append(req)
        return _FakeResponse(b'{"status":"ok"}')

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


def _errorOpener(code: int = 500) -> Callable[..., Any]:
    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        raise urllib.error.HTTPError(
            url="http://test/", code=code, msg="Server Error",
            hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
        )

    return _opener


class TestPushSnapshotSuccess:
    def test_pushesRowsAndAdvancesCursor(
        self, tempDbPath: str, stubApiKey: str,
    ) -> None:
        opener = _successOpener()
        client = SyncClient(
            _config(tempDbPath), httpOpener=opener, sleep=lambda _s: None,
        )
        result = client.pushSnapshot(_TABLE)
        assert result.status == PushStatus.OK
        assert result.rowsPushed == 2

        # Cursor advanced to the max recorded_at pushed.
        conn = sqlite3.connect(tempDbPath)
        try:
            assert (
                sync_log.getSnapshotCursor(conn, _TABLE) == "2026-07-01T11:00:00Z"
            )
        finally:
            conn.close()

    def test_secondPushIsEmpty(self, tempDbPath: str, stubApiKey: str) -> None:
        opener = _successOpener()
        client = SyncClient(
            _config(tempDbPath), httpOpener=opener, sleep=lambda _s: None,
        )
        client.pushSnapshot(_TABLE)
        second = client.pushSnapshot(_TABLE)
        assert second.status == PushStatus.EMPTY
        assert second.rowsPushed == 0

    def test_wirePayloadCarriesRowsUnderTableName(
        self, tempDbPath: str, stubApiKey: str,
    ) -> None:
        opener = _successOpener()
        client = SyncClient(
            _config(tempDbPath), httpOpener=opener, sleep=lambda _s: None,
        )
        client.pushSnapshot(_TABLE)
        req = opener.calls[0]
        body = json.loads(req.data.decode("utf-8"))
        assert _TABLE in body["tables"]
        bootIds = {r["boot_id"] for r in body["tables"][_TABLE]["rows"]}
        assert bootIds == {"boot-a", "boot-b"}


class TestPushSnapshotFailure:
    def test_failedPushDoesNotAdvanceCursor(
        self, tempDbPath: str, stubApiKey: str,
    ) -> None:
        client = SyncClient(
            _config(tempDbPath), httpOpener=_errorOpener(500),
            sleep=lambda _s: None,
        )
        result = client.pushSnapshot(_TABLE)
        assert result.status == PushStatus.FAILED

        conn = sqlite3.connect(tempDbPath)
        try:
            # Cursor stays at the beginning -> rows are re-sendable next cycle.
            assert sync_log.getSnapshotCursor(conn, _TABLE) is None
        finally:
            conn.close()


class TestPushSnapshotDisabled:
    def test_disabledServiceReturnsDisabled(self, tempDbPath: str) -> None:
        client = SyncClient(_config(tempDbPath, enabled=False))
        result = client.pushSnapshot(_TABLE)
        assert result.status == PushStatus.DISABLED
