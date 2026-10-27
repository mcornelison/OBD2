################################################################################
# File Name: test_push_lock.py
# Purpose/Description: One pusher at a time (US-871-a): the push lock every
#                      SyncClient push holds, the per-caller contention
#                      policy, states/sync-activity and the never-rewind mark.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-26    | Rex (US-871-a)| Initial: A1-A5 + caller policies
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.sync.push_lock` and its SyncClient wiring (US-871-a).

MEASURED 2026-10-12: four pushers shared no lock and ~19 % of rows were sent
twice.  A1 reproduces that with two real processes and a slow fake server.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.common.time.helper import CANONICAL_ISO_REGEX
from src.pi.data import sync_log
from src.pi.obdii.orchestrator.core import ApplicationOrchestrator
from src.pi.sync import push_lock
from src.pi.sync.client import PushLockHeld, SyncClient
from src.pi.sync.push_lock import (
    DRAIN_PUSHER,
    SYNC_ACTIVITY_FILENAME,
    holdPushLock,
    readSyncActivity,
)
from tests.pi.sync.stored_ack_reply import storedAckReplyFor

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ROW_COUNT = 5
#: Long enough that the second process is certainly started (interpreter +
#: imports) while the first is still inside its POST.
_SLOW_SERVER_SEC = 4.0
_PROCESS_TIMEOUT_SEC = 60.0


# ================================================================================
# Fixtures
# ================================================================================


def _createDb(path: Path, rows: int = _ROW_COUNT) -> None:
    conn = sqlite3.connect(str(path))
    try:
        sync_log.initDb(conn)
        for tableName in sync_log.IN_SCOPE_TABLES:
            if tableName in sync_log.SNAPSHOT_TABLES:
                pk = "id" if tableName == "profiles" else "vin"
                conn.execute(f"CREATE TABLE IF NOT EXISTS {tableName} ({pk} TEXT PRIMARY KEY)")
                continue
            pk = sync_log.PK_COLUMN[tableName]
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {tableName} "
                f"({pk} INTEGER PRIMARY KEY AUTOINCREMENT)"
            )
        conn.execute("DROP TABLE realtime_data")
        conn.execute(
            "CREATE TABLE realtime_data (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp TEXT NOT NULL, parameter_name TEXT NOT NULL, value REAL NOT NULL)"
        )
        for i in range(rows):
            conn.execute(
                "INSERT INTO realtime_data (timestamp, parameter_name, value) "
                "VALUES (?, ?, ?)",
                (f"2026-10-26T00:00:{i:02d}Z", "RPM", 1000.0 + i),
            )
        conn.commit()
    finally:
        conn.close()


def _config(dbPath: Path, statesDir: Path) -> dict[str, Any]:
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": str(dbPath)},
            "splash": {"statesDir": str(statesDir)},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://10.27.27.10:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [0],
            },
        },
    }


class _Reply:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.status = 200

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _RecordingServer:
    """A fake server that stores every row and records each POST."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    def __call__(self, req: Any, timeout: float | None = None) -> _Reply:
        self.posts.append(json.loads(req.data.decode("utf-8")))
        return _Reply(storedAckReplyFor(req.data))

    def sentRealtimeIds(self) -> list[int]:
        ids: list[int] = []
        for post in self.posts:
            section = (post.get("tables") or {}).get("realtime_data") or {}
            ids.extend(int(row["id"]) for row in section.get("rows", []))
        return ids


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-push-lock")
    ns = SimpleNamespace(
        db=tmp_path / "obd.db",
        lock=tmp_path / "run" / "sync.lock",
        states=tmp_path / "states",
        sentLog=tmp_path / "sent.jsonl",
    )
    _createDb(ns.db)
    return ns


def _client(paths: SimpleNamespace, server: Any, **kwargs: Any) -> SyncClient:
    return SyncClient(
        _config(paths.db, paths.states),
        httpOpener=server,
        sleep=lambda _s: None,
        pushLockPath=str(paths.lock),
        **kwargs,
    )


def _subprocessEnv() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_REPO_ROOT), str(_REPO_ROOT / "src"), env.get("PYTHONPATH", "")]
    )
    env["PYTHONUTF8"] = "1"
    return env


# A pusher in its own process: a real SyncClient against the shared obd.db and
# a slow fake server that appends every realtime_data id it is sent to a log.
_PUSHER_SCRIPT = textwrap.dedent(
    """
    import json, os, sys, time
    from src.pi.sync.client import SyncClient
    from tests.pi.sync.stored_ack_reply import storedAckReplyFor

    dbPath, statesDir, lockPath, sentLog, mode, delay = sys.argv[1:7]

    class Reply:
        status = 200
        def __init__(self, body): self._body = body
        def read(self): return self._body
        def __enter__(self): return self
        def __exit__(self, *exc): return None

    def server(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        section = (payload.get("tables") or {}).get("realtime_data") or {}
        ids = [int(r["id"]) for r in section.get("rows", [])]
        if ids:
            with open(sentLog, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"pid": os.getpid(), "ids": ids}) + "\\n")
            time.sleep(float(delay))
        return Reply(storedAckReplyFor(req.data))

    config = {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "splash": {"statesDir": statesDir},
            "companionService": {
                "enabled": True, "baseUrl": "http://10.27.27.10:8000",
                "apiKeyEnv": "COMPANION_API_KEY", "syncTimeoutSeconds": 30,
                "batchSize": 500, "retryMaxAttempts": 1, "retryBackoffSeconds": [0],
            },
        },
    }
    client = SyncClient(config, httpOpener=server, sleep=lambda s: None,
                        pushLockPath=lockPath, pusher=mode)
    if mode == "pushAllDeltas":
        client.pushAllDeltas()
    else:
        client.forcePush()
    """
)

# A holder in its own process: takes the lock, says so, then waits forever.
_HOLDER_SCRIPT = textwrap.dedent(
    """
    import sys, threading
    from src.pi.sync.push_lock import holdPushLock

    lockPath, statesDir = sys.argv[1:3]
    with holdPushLock("doomed-holder", wait=True, lockPath=lockPath, statesDir=statesDir):
        print("held", flush=True)
        threading.Event().wait()
    """
)


def _startPusher(paths: SimpleNamespace, mode: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            sys.executable, "-c", _PUSHER_SCRIPT,
            str(paths.db), str(paths.states), str(paths.lock), str(paths.sentLog),
            mode, str(_SLOW_SERVER_SEC),
        ],
        cwd=str(_REPO_ROOT),
        env=_subprocessEnv(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _waitFor(predicate: Any, timeoutSec: float) -> bool:
    deadline = time.monotonic() + timeoutSec
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _readMark(dbPath: Path) -> int:
    conn = sqlite3.connect(str(dbPath))
    try:
        return sync_log.getHighWaterMark(conn, "realtime_data")[0]
    finally:
        conn.close()


# ================================================================================
# A1 -- two pushers in two processes never send a row twice
# ================================================================================


def test_two_pushers_never_send_a_row_twice(paths: SimpleNamespace) -> None:
    """
    Given: pushAllDeltas in one process, forcePush in another, a slow server
    When: the second starts while the first is still inside its POST
    Then: every realtime_data row id reaches the server exactly once
    """
    first = _startPusher(paths, "pushAllDeltas")
    try:
        assert _waitFor(paths.sentLog.exists, _PROCESS_TIMEOUT_SEC), (
            "first pusher never reached the server"
        )
        second = _startPusher(paths, "forcePush")
        try:
            _, err2 = second.communicate(timeout=_PROCESS_TIMEOUT_SEC)
        finally:
            second.kill()
        _, err1 = first.communicate(timeout=_PROCESS_TIMEOUT_SEC)
    finally:
        first.kill()

    assert first.returncode == 0, err1.decode("utf-8", "replace")
    assert second.returncode == 0, err2.decode("utf-8", "replace")
    sent = [
        rowId
        for line in paths.sentLog.read_text(encoding="utf-8").splitlines()
        for rowId in json.loads(line)["ids"]
    ]
    counts = Counter(sent)
    assert sorted(counts) == list(range(1, _ROW_COUNT + 1))
    assert {rowId: n for rowId, n in counts.items() if n > 1} == {}, (
        f"rows sent twice: {sent}"
    )
    assert _readMark(paths.db) == _ROW_COUNT


# ================================================================================
# A2 -- the interval tick skips when the lock is held
# ================================================================================


def _orchestratorStub(client: SyncClient) -> SimpleNamespace:
    return SimpleNamespace(
        _syncClient=client,
        _syncTriggerOn=["interval", "drive_end"],
        _syncCadenceController=None,
        _lastSyncAttemptTime=None,
        _syncIntervalSeconds=60,
        _markSkippedSyncTick=ApplicationOrchestrator._markSkippedSyncTick,
        _recordSyncOutcome=lambda rows: pytest.fail("a skipped tick recorded an outcome"),
    )


def test_intervalSync_lockHeld_skipsTheTickAndLogsTheHolder(
    paths: SimpleNamespace, caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: the powerwatch drain holds the push lock
    When: the interval tick fires
    Then: it returns without pushing anything and logs 'held by powerwatch-drain'
    """
    server = _RecordingServer()
    client = _client(paths, server)
    client.hasRouteToServer = lambda: True  # type: ignore[method-assign]
    stub = _orchestratorStub(client)

    with holdPushLock(
        DRAIN_PUSHER, wait=True, lockPath=str(paths.lock), statesDir=str(paths.states),
    ), caplog.at_level(logging.INFO):
        started = time.monotonic()
        result = ApplicationOrchestrator._maybeTriggerIntervalSync(stub)  # type: ignore[arg-type]
        elapsed = time.monotonic() - started

    assert result is False
    assert server.posts == []
    assert elapsed < 2.0, "the interval tick waited on the lock"
    assert "sync skipped: held by powerwatch-drain" in caplog.text
    assert _readMark(paths.db) == 0


def test_driveEndSync_lockHeld_skipsAndLogsTheHolder(
    paths: SimpleNamespace, caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: the powerwatch drain holds the push lock
    When: the drive-end flush fires
    Then: nothing is pushed (not even the drive counter) and 'held by' is logged
    """
    server = _RecordingServer()
    client = _client(paths, server)
    stub = _orchestratorStub(client)

    with holdPushLock(
        DRAIN_PUSHER, wait=True, lockPath=str(paths.lock), statesDir=str(paths.states),
    ), caplog.at_level(logging.INFO):
        result = ApplicationOrchestrator.triggerDriveEndSync(stub)  # type: ignore[arg-type]

    assert result is False
    assert server.posts == []
    assert "sync skipped: held by powerwatch-drain" in caplog.text


def test_intervalSync_lockFree_pushesAndReleases(paths: SimpleNamespace) -> None:
    """
    Given: nobody holds the lock
    When: the interval tick fires
    Then: the rows are pushed and the lock is free again afterwards
    """
    server = _RecordingServer()
    client = _client(paths, server)
    client.hasRouteToServer = lambda: True  # type: ignore[method-assign]
    stub = _orchestratorStub(client)
    stub._recordSyncOutcome = lambda rows: None

    assert ApplicationOrchestrator._maybeTriggerIntervalSync(stub) is True  # type: ignore[arg-type]

    assert sorted(server.sentRealtimeIds()) == list(range(1, _ROW_COUNT + 1))
    with holdPushLock("probe", wait=False, lockPath=str(paths.lock), statesDir=str(paths.states)):
        pass


def test_pushAllDeltas_noWait_lockHeld_raisesWithTheHolderAndPushesNothing(
    paths: SimpleNamespace,
) -> None:
    server = _RecordingServer()
    client = _client(paths, server, lockWait=False)

    with holdPushLock(
        DRAIN_PUSHER, wait=True, lockPath=str(paths.lock), statesDir=str(paths.states),
    ), pytest.raises(PushLockHeld) as raised:
        client.pushAllDeltas()

    assert raised.value.holder == DRAIN_PUSHER
    assert server.posts == []


def test_forcePush_waits_thenPushesOnlyWhatIsLeft(paths: SimpleNamespace) -> None:
    """
    Given: another pusher holds the lock and delivers every row while held
    When: a waiting forcePush (the drain) runs meanwhile
    Then: it blocks, names the holder via onLockWait, and sends no row again
    """
    server = _RecordingServer()
    waitedFor: list[str] = []
    waiting = threading.Event()

    def onWait(holder: str) -> None:
        waitedFor.append(holder)
        waiting.set()

    drain = _client(paths, server, pusher=DRAIN_PUSHER, lockWait=True, onLockWait=onWait)
    first = _client(paths, server)
    outcome: dict[str, Any] = {}

    with holdPushLock(
        "eclipse-obd-interval", wait=True, lockPath=str(paths.lock), statesDir=str(paths.states),
    ):
        worker = threading.Thread(target=lambda: outcome.update(s=drain.forcePush()))
        worker.start()
        assert waiting.wait(timeout=10.0), "the drain never reported waiting"
        assert worker.is_alive(), "the drain did not block on the held lock"
        first._pushAllDeltasLocked(bypassQuarantine=False, excludeTables=())
    worker.join(timeout=30.0)

    assert not worker.is_alive()
    assert waitedFor == ["eclipse-obd-interval"]
    assert outcome["s"].rowsPushed == 0
    assert Counter(server.sentRealtimeIds()) == Counter(range(1, _ROW_COUNT + 1))


def test_syncNow_waitsAndPrintsWhomFor(
    paths: SimpleNamespace, capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Given: the drain holds the lock
    When: sync_now's production client pushes
    Then: it prints 'waiting for powerwatch-drain' and pushes once released
    """
    spec = importlib.util.spec_from_file_location(
        "sync_now_under_test", _REPO_ROOT / "scripts" / "sync_now.py",
    )
    assert spec is not None and spec.loader is not None
    syncNow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(syncNow)

    server = _RecordingServer()
    client = syncNow._defaultSyncClientFactory(_config(paths.db, paths.states))
    client._httpOpener = server
    client._sleep = lambda _s: None
    client._pushLockPath = str(paths.lock)

    printed: list[str] = []

    def sawWaiting() -> bool:
        printed.append(capsys.readouterr().out)
        return "waiting for powerwatch-drain" in "".join(printed)

    worker = threading.Thread(target=client.pushAllDeltas)
    with holdPushLock(
        DRAIN_PUSHER, wait=True, lockPath=str(paths.lock), statesDir=str(paths.states),
    ):
        worker.start()
        assert _waitFor(sawWaiting, 10.0), f"printed: {''.join(printed)!r}"
        assert server.posts == []
    worker.join(timeout=30.0)

    assert not worker.is_alive()
    assert sorted(server.sentRealtimeIds()) == list(range(1, _ROW_COUNT + 1))


# ================================================================================
# A3 -- the mark never moves backwards
# ================================================================================


def test_updateHighWaterMark_lowerAfterHigher_keepsTheHigherMark() -> None:
    """
    Given: the realtime_data mark at 800
    When: a slow failed push re-writes the lastId=500 it read earlier
    Then: the mark stays 800
    """
    conn = sqlite3.connect(":memory:")
    try:
        sync_log.initDb(conn)
        sync_log.updateHighWaterMark(conn, "realtime_data", 800, "batch-b", status="ok")

        sync_log.updateHighWaterMark(conn, "realtime_data", 500, "batch-a", status="failed")

        lastId, _, batchId, status = sync_log.getHighWaterMark(conn, "realtime_data")
        assert lastId == 800
        # The diagnostics columns still record the later write.
        assert (batchId, status) == ("batch-a", "failed")

        sync_log.updateHighWaterMark(conn, "realtime_data", 900, "batch-c", status="ok")
        assert sync_log.getHighWaterMark(conn, "realtime_data")[0] == 900
    finally:
        conn.close()


# ================================================================================
# A4 -- a killed holder frees the lock
# ================================================================================


_WINDOWS_UNLOCK_SETTLE_SEC = 10.0


def _freeNow(paths: SimpleNamespace) -> bool:
    try:
        with holdPushLock(
            "settle-probe", wait=False, lockPath=str(paths.lock), statesDir=str(paths.states),
        ):
            return True
    except PushLockHeld:
        return False


def test_holderKilled_freesTheLockAtOnce(paths: SimpleNamespace) -> None:
    """
    Given: another process holds the push lock
    When: it is killed (SIGKILL on the Pi; TerminateProcess off-Linux)
    Then: the next non-waiting caller acquires at once
    """
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER_SCRIPT, str(paths.lock), str(paths.states)],
        cwd=str(_REPO_ROOT),
        env=_subprocessEnv(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        line = holder.stdout.readline().decode("utf-8").strip()
        assert line == "held", holder.stderr.read().decode("utf-8", "replace") if holder.stderr else line
        with pytest.raises(PushLockHeld) as raised:
            with holdPushLock(
                "probe", wait=False, lockPath=str(paths.lock), statesDir=str(paths.states),
            ):
                pass
        assert raised.value.holder == "doomed-holder"
    finally:
        holder.kill()
        holder.wait(timeout=_PROCESS_TIMEOUT_SEC)

    if push_lock.fcntl is None:
        # Windows dev desk only: the OS unlocks a dead process's byte range
        # "depending on available system resources" (LockFile docs), not at
        # once.  On the Pi the kernel drops a flock with the last descriptor,
        # so the strict at-once acquire below runs with no settle.
        assert _waitFor(lambda: _freeNow(paths), _WINDOWS_UNLOCK_SETTLE_SEC)

    with holdPushLock(
        "next", wait=False, lockPath=str(paths.lock), statesDir=str(paths.states),
    ):
        activity = readSyncActivity(str(paths.states))
    assert activity is not None and activity["pusher"] == "next"


# ================================================================================
# A5 -- states/sync-activity shapes
# ================================================================================


def _activity(paths: SimpleNamespace) -> dict[str, Any]:
    text = (paths.states / SYNC_ACTIVITY_FILENAME).read_text(encoding="utf-8")
    record = json.loads(text)
    assert isinstance(record, dict)
    return record


def test_syncActivity_acquireAndReleaseShapes(paths: SimpleNamespace) -> None:
    """
    Given: no prior sync-activity this boot
    When: a pusher acquires, delivers nothing, and releases; then one delivers
          rows; then one delivers nothing again
    Then: acquire = {pusher, pid, startedTs, ts}; release = {pusher: null,
          lastDeliveredTs, ts}, lastDeliveredTs null -> stamped -> carried over
    """
    kw = {"lockPath": str(paths.lock), "statesDir": str(paths.states)}

    with holdPushLock(DRAIN_PUSHER, wait=True, **kw):
        acquired = _activity(paths)
    assert set(acquired) == {"pusher", "pid", "startedTs", "ts"}
    assert acquired["pusher"] == DRAIN_PUSHER
    assert acquired["pid"] == os.getpid()
    assert acquired["startedTs"] == acquired["ts"]
    assert all(re.match(CANONICAL_ISO_REGEX, acquired[k]) for k in ("startedTs", "ts"))

    released = _activity(paths)
    assert set(released) == {"pusher", "lastDeliveredTs", "ts"}
    assert released["pusher"] is None
    assert released["lastDeliveredTs"] is None

    with holdPushLock(DRAIN_PUSHER, wait=True, **kw) as session:
        session.rowsDelivered = 3
    delivered = _activity(paths)
    assert delivered["pusher"] is None
    assert delivered["lastDeliveredTs"] == delivered["ts"]

    with holdPushLock("sync-now", wait=True, **kw):
        pass
    carried = _activity(paths)
    assert carried["lastDeliveredTs"] == delivered["lastDeliveredTs"]


def test_syncActivity_throughSyncClient_stampsOnlyOnDeliveredRows(
    paths: SimpleNamespace,
) -> None:
    """
    Given: a SyncClient with 5 rows waiting
    When: it pushes them, then pushes again with nothing left
    Then: the first release stamps lastDeliveredTs; the second carries it over
    """
    server = _RecordingServer()
    client = _client(paths, server, pusher=DRAIN_PUSHER)

    client.forcePush()
    first = _activity(paths)
    assert first["pusher"] is None and first["lastDeliveredTs"] is not None

    client.pushAllDeltas()
    second = _activity(paths)
    assert second["lastDeliveredTs"] == first["lastDeliveredTs"]


def test_syncActivity_noRowsDelivered_lastDeliveredStaysNull(paths: SimpleNamespace) -> None:
    """A forced drive-counter upsert alone is not a delivered row."""
    _createDb(paths.db, rows=0)
    client = _client(paths, _RecordingServer(), pusher=DRAIN_PUSHER)

    client.forcePush()

    assert _activity(paths)["lastDeliveredTs"] is None


def test_defaultLockPath_isTheRunDirLock() -> None:
    assert push_lock.DEFAULT_LOCK_PATH == "/run/eclipse-obd/sync.lock"
