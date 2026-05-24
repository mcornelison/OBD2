################################################################################
# File Name: test_drive_counter_sync.py
# Purpose/Description: Integration tests for the Pi -> server drive_counter
#                      sync path (US-314 / B-064).  Asserts that a Pi
#                      drive_counter advance gets bundled into the next sync
#                      POST so the server-side singleton is kept in lockstep.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-314) | Initial -- runtime-validation gate for B-064.
# ================================================================================
################################################################################

"""Pi-side runtime-validation gate for the drive_counter sync wiring.

Pre-fix discriminator (RED phase): :meth:`SyncClient.forcePush` builds
its outbound JSON payload from :data:`sync_log.IN_SCOPE_TABLES`, which
does NOT include ``drive_counter``.  Asserting the captured request
body contains a top-level ``driveCounter`` key fails because nothing
in the pre-fix code path emits one.

Post-fix (GREEN phase): :meth:`SyncClient` reads the local SQLite
``drive_counter.last_drive_id`` and bundles it as a top-level
``driveCounter: {lastDriveId: N}`` field in a dedicated POST so the
server can upsert the singleton.

Tests use the same in-memory mock-HTTP-opener pattern as
``test_sync_client.py`` (US-149) -- no real network, no real server.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import urllib.error
from collections.abc import Callable
from typing import Any

import pytest

from src.pi.data import sync_log
from src.pi.obdii.drive_id import (
    DRIVE_COUNTER_TABLE,
    ensureDriveCounter,
)
from src.pi.sync import PushStatus, SyncClient

# =============================================================================
# Helpers / fixtures
# =============================================================================


def _createEmptyInScopeTables(conn: sqlite3.Connection) -> None:
    """Create minimal stand-ins for every IN_SCOPE_TABLES entry.

    Mirrors the helper in test_sync_client.py so this module stays
    self-contained.  forcePush() iterates IN_SCOPE_TABLES; missing
    tables would surface as ``OperationalError`` and mask the real
    assertion.
    """
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
    conn.commit()


def _seedDriveCounter(conn: sqlite3.Connection, lastDriveId: int) -> None:
    """Force the singleton to a specific ``last_drive_id`` for tests."""
    ensureDriveCounter(conn)
    conn.execute(
        f"UPDATE {DRIVE_COUNTER_TABLE} SET last_drive_id = ? WHERE id = 1",
        (int(lastDriveId),),
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
def tempDbPath() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    sync_log.initDb(conn)
    _createEmptyInScopeTables(conn)
    conn.close()
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    key = "test-key-abcdef"
    monkeypatch.setenv("COMPANION_API_KEY", key)
    return key


@pytest.fixture
def noSleep() -> Callable[[float], None]:
    calls: list[float] = []

    def _record(seconds: float) -> None:
        calls.append(float(seconds))

    _record.calls = calls  # type: ignore[attr-defined]
    return _record


class _CapturingResponse:
    """Mimics ``urllib`` response for the success case."""

    def __init__(self, body: bytes = b'{"status":"ok"}') -> None:
        self._body = body

    def __enter__(self) -> _CapturingResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _capturingOpener() -> Callable[..., Any]:
    """Opener that records every POST body for later inspection."""
    bodies: list[dict[str, Any]] = []

    def _opener(req: Any, timeout: float = 30) -> _CapturingResponse:  # noqa: ARG001
        raw = req.data if hasattr(req, "data") else b""
        if raw:
            bodies.append(json.loads(raw.decode("utf-8")))
        return _CapturingResponse()

    _opener.bodies = bodies  # type: ignore[attr-defined]
    return _opener


# =============================================================================
# US-314: drive_counter is bundled into outbound sync.
# =============================================================================


class TestDriveCounterBundledInForcePush:
    """forcePush() emits a payload carrying the local drive_counter value."""

    def test_forcePush_emitsDriveCounterPayload(
        self,
        tempDbPath: str,
        stubApiKey: str,  # noqa: ARG002 -- env injection
        noSleep: Any,
    ) -> None:
        """Pi at drive_id=10 -> at least one POST body carries driveCounter=10.

        Pre-fix RED discriminator: forcePush iterates IN_SCOPE_TABLES; no
        path in the pre-fix code emits a top-level ``driveCounter`` field.
        This assertion fails on the pre-fix tree because no body has it.
        """
        with sqlite3.connect(tempDbPath) as conn:
            _seedDriveCounter(conn, lastDriveId=10)

        opener = _capturingOpener()
        client = SyncClient(
            _baseConfig(tempDbPath), httpOpener=opener, sleep=noSleep,
        )

        client.forcePush()

        bodies = opener.bodies  # type: ignore[attr-defined]
        bodiesWithCounter = [b for b in bodies if "driveCounter" in b]
        assert len(bodiesWithCounter) >= 1, (
            f"forcePush did not emit driveCounter; bodies={bodies}"
        )
        assert bodiesWithCounter[0]["driveCounter"] == {"lastDriveId": 10}

    def test_forcePush_doesNotEmitCounter_whenTableMissing(
        self,
        tempDbPath: str,
        stubApiKey: str,  # noqa: ARG002
        noSleep: Any,
    ) -> None:
        """No drive_counter table -> forcePush still succeeds + omits the field.

        Defensive: a fresh DB created before US-200 ran would not have
        the singleton table.  The sync path must not fail in that case;
        it just skips the counter field.
        """
        # Drop the drive_counter table to simulate pre-US-200 state.
        with sqlite3.connect(tempDbPath) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {DRIVE_COUNTER_TABLE}")
            conn.commit()

        opener = _capturingOpener()
        client = SyncClient(
            _baseConfig(tempDbPath), httpOpener=opener, sleep=noSleep,
        )

        summary = client.forcePush()

        # No FAILED tables -- counter omission is silent + benign.
        assert summary.tablesFailed == 0
        bodies = opener.bodies  # type: ignore[attr-defined]
        assert all("driveCounter" not in b for b in bodies)

    def test_forcePush_emitsCounter_evenWhenAllTablesEmpty(
        self,
        tempDbPath: str,
        stubApiKey: str,  # noqa: ARG002
        noSleep: Any,
    ) -> None:
        """Counter advances are independent of capture-table writes.

        A drive that ends but has no realtime_data / connection_log
        rows pending (pure replay or analytics-only profile) still
        needs to advance the server-side counter.  At least ONE body
        must carry the driveCounter even when every other table is
        EMPTY.
        """
        with sqlite3.connect(tempDbPath) as conn:
            _seedDriveCounter(conn, lastDriveId=10)
            # Tables are all empty -- pushDelta returns EMPTY for each.

        opener = _capturingOpener()
        client = SyncClient(
            _baseConfig(tempDbPath), httpOpener=opener, sleep=noSleep,
        )

        client.forcePush()

        bodies = opener.bodies  # type: ignore[attr-defined]
        bodiesWithCounter = [b for b in bodies if "driveCounter" in b]
        assert len(bodiesWithCounter) >= 1, (
            "drive_counter advance must sync even when capture tables empty"
        )
        assert bodiesWithCounter[0]["driveCounter"]["lastDriveId"] == 10


class TestPushDriveCounterMethod:
    """Direct API surface for the new pushDriveCounter() method."""

    def test_pushDriveCounter_postsLastDriveId(
        self,
        tempDbPath: str,
        stubApiKey: str,  # noqa: ARG002
        noSleep: Any,
    ) -> None:
        with sqlite3.connect(tempDbPath) as conn:
            _seedDriveCounter(conn, lastDriveId=42)

        opener = _capturingOpener()
        client = SyncClient(
            _baseConfig(tempDbPath), httpOpener=opener, sleep=noSleep,
        )

        result = client.pushDriveCounter()

        assert result.status == PushStatus.OK
        assert result.tableName == DRIVE_COUNTER_TABLE
        bodies = opener.bodies  # type: ignore[attr-defined]
        assert len(bodies) == 1
        body = bodies[0]
        assert body["deviceId"] == "chi-eclipse-01"
        assert body["driveCounter"] == {"lastDriveId": 42}
        # tables present but empty -- server upserts only the counter.
        assert body.get("tables", {}) == {}

    def test_pushDriveCounter_emptyResult_whenCounterAtZero(
        self,
        tempDbPath: str,
        stubApiKey: str,  # noqa: ARG002
        noSleep: Any,
    ) -> None:
        """No drives minted yet -> EMPTY status, no POST."""
        with sqlite3.connect(tempDbPath) as conn:
            ensureDriveCounter(conn)
            conn.commit()
            # last_drive_id stays at the seeded default of 0.

        opener = _capturingOpener()
        client = SyncClient(
            _baseConfig(tempDbPath), httpOpener=opener, sleep=noSleep,
        )

        result = client.pushDriveCounter()

        assert result.status == PushStatus.EMPTY
        bodies = opener.bodies  # type: ignore[attr-defined]
        assert bodies == []

    def test_pushDriveCounter_disabled_whenCompanionOff(
        self,
        tempDbPath: str,
        stubApiKey: str,  # noqa: ARG002
        noSleep: Any,
    ) -> None:
        """Companion service disabled -> DISABLED, no POST."""
        with sqlite3.connect(tempDbPath) as conn:
            _seedDriveCounter(conn, lastDriveId=5)

        opener = _capturingOpener()
        client = SyncClient(
            _baseConfig(tempDbPath, enabled=False),
            httpOpener=opener,
            sleep=noSleep,
        )

        result = client.pushDriveCounter()

        assert result.status == PushStatus.DISABLED
        bodies = opener.bodies  # type: ignore[attr-defined]
        assert bodies == []

    def test_pushDriveCounter_failure_doesNotRaise(
        self,
        tempDbPath: str,
        stubApiKey: str,  # noqa: ARG002
        noSleep: Any,
    ) -> None:
        """Server 500 -> FAILED status, no exception."""
        with sqlite3.connect(tempDbPath) as conn:
            _seedDriveCounter(conn, lastDriveId=7)

        def _opener(req: Any, timeout: float = 30) -> Any:  # noqa: ARG001
            raise urllib.error.HTTPError(
                url="http://test/", code=500, msg="boom",
                hdrs=None, fp=None,  # type: ignore[arg-type]
            )

        client = SyncClient(
            _baseConfig(tempDbPath), httpOpener=_opener, sleep=noSleep,
        )
        result = client.pushDriveCounter()

        assert result.status == PushStatus.FAILED
        assert "500" in result.reason
