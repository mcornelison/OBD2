################################################################################
# File Name: test_sync_replay_refusal.py
# Purpose/Description: US-901-a (CIO R37) -- a replay (pi.replay.active) or a
#                      --simulate run refuses every SyncClient push at the two
#                      POST sites: all five public push methods return the
#                      typed REFUSED state, the transport is never called and
#                      nothing is written to the database.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-901-a)| Initial -- five push methods x two modes, the
#                               broken-guard control and the lifecycle wiring.
# ================================================================================
################################################################################

"""Tests for the US-901-a replay / --simulate push refusal in SyncClient."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from src.common.sync.snapshot_registry import SNAPSHOT_SYNC, SnapshotSyncSpec
from src.pi.data import sync_log
from src.pi.sync import PushStatus, SyncClient
from src.pi.sync.client import PushResult, PushSummary

_SNAPSHOT_TABLE = "test_replay_snap"
_DRIVE_ID = 7
_REALTIME_ROWS = 3

# =============================================================================
# Fixtures / helpers
# =============================================================================


@pytest.fixture
def seededDb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A database every push method has something to send from.

    realtime_data carries rows above the mark, a registered snapshot table
    carries rows above its cursor and drive_counter is non-zero -- so each of
    the five methods reaches a POST site.  The lazy schema steps the client
    runs on every push are applied here first, so a database dump taken now
    is what an untouched database looks like afterwards.
    """
    monkeypatch.setitem(
        SNAPSHOT_SYNC,
        _SNAPSHOT_TABLE,
        SnapshotSyncSpec(naturalKeyCols=("boot_id",), cursorCol="recorded_at"),
    )
    path = str(tmp_path / "replay.db")
    conn = sqlite3.connect(path)
    sync_log.initDb(conn)
    for tableName in sync_log.IN_SCOPE_TABLES:
        if tableName in sync_log.SNAPSHOT_TABLES:
            pkColumn = "id" if tableName == "profiles" else "vin"
            conn.execute(f"CREATE TABLE {tableName} ({pkColumn} TEXT PRIMARY KEY)")
            continue
        if tableName == "realtime_data":
            continue
        pkColumn = sync_log.PK_COLUMN[tableName]
        conn.execute(
            f"CREATE TABLE {tableName} ({pkColumn} INTEGER PRIMARY KEY AUTOINCREMENT)"
        )
    conn.execute(
        "CREATE TABLE realtime_data (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT NOT NULL, parameter_name TEXT NOT NULL, value REAL NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO realtime_data (timestamp, parameter_name, value) VALUES (?, ?, ?)",
        [(f"2026-10-14T00:00:0{i}Z", "RPM", 900.0 + i) for i in range(_REALTIME_ROWS)],
    )
    conn.execute(
        f"CREATE TABLE {_SNAPSHOT_TABLE} (boot_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL)"
    )
    conn.executemany(
        f"INSERT INTO {_SNAPSHOT_TABLE} (boot_id, recorded_at) VALUES (?, ?)",
        [("boot-a", "2026-10-14T10:00:00Z"), ("boot-b", "2026-10-14T11:00:00Z")],
    )
    conn.execute("CREATE TABLE drive_counter (id INTEGER PRIMARY KEY, last_drive_id INTEGER)")
    conn.execute(
        "INSERT INTO drive_counter (id, last_drive_id) VALUES (1, ?)", (_DRIVE_ID,),
    )
    sync_log.ensureSyncModifiedAtSchema(conn)
    sync_log.ensureQuarantineSchema(conn)
    sync_log.ensureSnapshotSyncSchema(conn)
    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-replay")


def _config(dbPath: str, *, replayActive: bool) -> dict[str, Any]:
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "replay": {"active": replayActive},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://10.27.27.120:8000",  # b044-exempt: test fixture
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [0],
            },
        },
    }


def _raisingTransport() -> Callable[..., Any]:
    """A transport that records and then raises on ANY call."""
    calls: list[Any] = []

    def _opener(req: Any, timeout: float = 30) -> Any:  # noqa: ARG001
        calls.append(req)
        raise AssertionError(f"transport called: {req.full_url}")

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


def _client(dbPath: str, mode: str, transport: Callable[..., Any]) -> SyncClient:
    """A client for a replay run or a --simulate run."""
    return SyncClient(
        _config(dbPath, replayActive=(mode == "replay")),
        simulate=(mode == "simulate"),
        httpOpener=transport,
        sleep=lambda _s: None,
    )


def _dump(dbPath: str) -> list[str]:
    """Every statement that rebuilds the database: schema AND rows."""
    conn = sqlite3.connect(dbPath)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def _syncLogRows(dbPath: str) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(dbPath)
    try:
        return conn.execute("SELECT * FROM sync_log ORDER BY table_name").fetchall()
    finally:
        conn.close()


# The five public push methods (pushSnapshot is the one Atlas G3 added).
_PUSH_METHODS: dict[str, Callable[[SyncClient], Any]] = {
    "pushDelta": lambda c: c.pushDelta("realtime_data"),
    "pushSnapshot": lambda c: c.pushSnapshot(_SNAPSHOT_TABLE),
    "pushDriveCounter": lambda c: c.pushDriveCounter(),
    "pushAllDeltas": lambda c: c.pushAllDeltas(),
    "forcePush": lambda c: c.forcePush(),
}


def _assertRefused(methodName: str, outcome: Any) -> None:
    """Assert ``outcome`` is the typed REFUSED state for ``methodName``."""
    if methodName == "forcePush":
        assert isinstance(outcome, PushSummary)
        assert outcome.refused is True
        # realtime_data, the snapshot table and drive_counter all had data.
        assert outcome.tablesRefused == 3
        assert outcome.tablesFailed == 0
        assert outcome.rowsPushed == 0
        assert outcome.disabled is False
        return
    if methodName == "pushAllDeltas":
        byTable = {r.tableName: r.status for r in outcome}
        assert byTable["realtime_data"] == PushStatus.REFUSED
        assert byTable[_SNAPSHOT_TABLE] == PushStatus.REFUSED
        # Nothing was sent and nothing failed: every other table had no rows.
        assert not {PushStatus.OK, PushStatus.FAILED} & set(byTable.values())
        return
    assert isinstance(outcome, PushResult)
    assert outcome.status == PushStatus.REFUSED
    assert outcome.rowsPushed == 0


# =============================================================================
# The refusal
# =============================================================================


@pytest.mark.parametrize("mode", ["replay", "simulate"])
@pytest.mark.parametrize("methodName", list(_PUSH_METHODS))
def test_everyPushMethod_isRefused_withoutTransportOrWrite(
    seededDb: str, mode: str, methodName: str,
) -> None:
    """
    Given: a replay run (pi.replay.active) or a --simulate run, data to send,
           and a transport that raises on any call
    When:  each of the five public push methods runs
    Then:  it returns the typed REFUSED state, the transport is never called
           and the database (sync_log included) is byte-for-byte unchanged
    """
    transport = _raisingTransport()
    client = _client(seededDb, mode, transport)
    before = _dump(seededDb)

    outcome = _PUSH_METHODS[methodName](client)

    _assertRefused(methodName, outcome)
    assert transport.calls == []  # type: ignore[attr-defined]
    assert _dump(seededDb) == before


@pytest.mark.parametrize("mode", ["replay", "simulate"])
def test_refusedIsDistinctFromDisabledAndFailed(seededDb: str, mode: str) -> None:
    """REFUSED is its own typed state, and it carries the reason."""
    result = _client(seededDb, mode, _raisingTransport()).pushDelta("realtime_data")

    assert result.status not in (PushStatus.DISABLED, PushStatus.FAILED)
    expected = "replay mode" if mode == "replay" else "--simulate run"
    assert result.reason == f"sync refused: {expected}"


def test_replayRefusal_logsTheReason(
    seededDb: str, caplog: pytest.LogCaptureFixture,
) -> None:
    """The interval-tick example: 'sync refused: replay mode', no POST."""
    caplog.set_level(logging.INFO)

    _client(seededDb, "replay", _raisingTransport()).pushAllDeltas()

    assert "sync refused: replay mode" in caplog.text


def test_replayInactive_notSimulate_hasNoRefusalReason(seededDb: str) -> None:
    """Production shape (replay false, not --simulate): nothing to refuse."""
    client = SyncClient(_config(seededDb, replayActive=False))

    assert client.refusalReason is None


# =============================================================================
# The guard is shown to FAIL when broken (design-patterns section 6)
# =============================================================================


@pytest.mark.parametrize("methodName", list(_PUSH_METHODS))
def test_brokenGuard_reachesTheTransport_andWritesSyncLog(
    seededDb: str, methodName: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given: a replay run whose refusal has been disabled
    When:  the push method runs against the same data and transport
    Then:  the transport IS called -- so the refusal test above fails when
           the guard is broken, rather than passing on an unreachable path
    """
    monkeypatch.setattr(SyncClient, "_refuseIfReplayOrSimulate", lambda self: None)
    transport = _raisingTransport()
    client = _client(seededDb, "replay", transport)

    with pytest.raises(AssertionError, match="transport called"):
        _PUSH_METHODS[methodName](client)

    assert len(transport.calls) == 1  # type: ignore[attr-defined]


def test_brokenGuard_failedPush_isVisibleInSyncLog(
    seededDb: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sync_log check can see a write: a FAILED push records status."""
    import urllib.error

    def _refusedConnection(req: Any, timeout: float = 30) -> Any:  # noqa: ARG001
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(SyncClient, "_refuseIfReplayOrSimulate", lambda self: None)
    client = SyncClient(
        _config(seededDb, replayActive=True),
        httpOpener=_refusedConnection,
        sleep=lambda _s: None,
    )
    before = _syncLogRows(seededDb)

    result = client.pushDelta("realtime_data")

    assert result.status == PushStatus.FAILED
    assert _syncLogRows(seededDb) != before


# =============================================================================
# Lifecycle wiring: the orchestrator hands the run's --simulate flag in
# =============================================================================


def _orchestratorConfig() -> dict[str, Any]:
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://10.27.27.120:8000",  # b044-exempt: test fixture
                "apiKeyEnv": "COMPANION_API_KEY",
            },
            "sync": {"enabled": True, "intervalSeconds": 60},
        },
        "server": {},
    }


@pytest.mark.parametrize(
    ("simulate", "expected"), [(True, "--simulate run"), (False, None)],
)
def test_orchestratorSyncClient_carriesTheRunsSimulateFlag(
    simulate: bool, expected: str | None,
) -> None:
    """_initializeSyncClient builds the client with the orchestrator's own
    --simulate flag, so a --simulate run's interval sync is refused."""
    from pi.obdii.orchestrator.core import ApplicationOrchestrator

    orch = ApplicationOrchestrator(config=_orchestratorConfig(), simulate=simulate)
    orch._initializeSyncClient()

    assert orch._syncClient is not None
    assert orch._syncClient.refusalReason == expected
