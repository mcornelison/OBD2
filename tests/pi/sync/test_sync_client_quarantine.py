################################################################################
# File Name: test_sync_client_quarantine.py
# Purpose/Description: US-391 (F-076) -- SyncClient queue-level quarantine.
#                      Proves the full lifecycle the story requires: N
#                      consecutive server-rejection failures -> quarantine ->
#                      surfaced exactly once -> re-attempts throttled (no
#                      per-cycle network spam) -> re-drainable once the push
#                      succeeds (e.g. after US-367 backfills the ECU era).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-28    | Rex (US-391) | Initial -- quarantine lifecycle + surface-once
#               |              | + throttle-skip + re-drain + network-failures-
#               |              | do-not-quarantine.
# ================================================================================
################################################################################

"""US-391 SyncClient quarantine tests.

The HTTP boundary is mocked via an injected ``httpOpener``; the clock is
injected so the throttle window is deterministic.  No sockets, no real sleeps,
no wall-clock.
"""

from __future__ import annotations

import io
import logging
import os
import sqlite3
import tempfile
import urllib.error
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.pi.data import sync_log
from src.pi.sync import PushStatus, SyncClient

_TABLE = "dtc_freeze_frame"


# =============================================================================
# Helpers / fixtures
# =============================================================================


def _config(dbPath: str, *, threshold: int = 3, throttleSeconds: int = 3600) -> dict[str, Any]:
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://10.27.27.120:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 0,  # no inner retries -> 1 attempt per push
                "retryBackoffSeconds": [],
                "quarantineThreshold": threshold,
                "quarantineThrottleSeconds": throttleSeconds,
            },
        },
    }


@pytest.fixture
def tempDbPath() -> str:
    """Temp SQLite with a migrated sync_log + one dtc_freeze_frame row to push."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    sync_log.initDb(conn)
    sync_log.ensureQuarantineSchema(conn)
    # Create empty stubs for every in-scope table so pushAllDeltas / forcePush
    # can iterate without "no such table" (production creates all at boot).
    for tableName in sync_log.IN_SCOPE_TABLES:
        if tableName == _TABLE:
            continue
        if tableName in sync_log.SNAPSHOT_TABLES:
            pkColumn = "id" if tableName == "profiles" else "vin"
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {tableName} ({pkColumn} TEXT PRIMARY KEY)"
            )
            continue
        pkColumn = sync_log.PK_COLUMN[tableName]
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {tableName} "
            f"({pkColumn} INTEGER PRIMARY KEY AUTOINCREMENT)"
        )
    conn.execute(
        "CREATE TABLE dtc_freeze_frame (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "captured_at_timestamp_utc TEXT, vehicle_info_vin TEXT)"
    )
    conn.execute(
        "INSERT INTO dtc_freeze_frame (captured_at_timestamp_utc, vehicle_info_vin) "
        "VALUES ('2026-06-05T09:00:00Z', 'UNRESOLVABLE_VIN')"
    )
    conn.commit()
    conn.close()
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


class _Clock:
    """Controllable injected clock returning an aware UTC datetime."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _noSleep(_seconds: float) -> None:
    return None


class _Fake500:
    """Opener that always raises HTTP 500 (server rejection) and counts calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, req: Any, timeout: float = 30) -> Any:  # noqa: ARG002
        self.calls += 1
        raise urllib.error.HTTPError(
            url="http://test/", code=500, msg="resolution failed",
            hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
        )


class _FakeResponse:
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return b'{"status":"ok"}'


class _FakeSuccess:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, req: Any, timeout: float = 30) -> Any:  # noqa: ARG002
        self.calls += 1
        return _FakeResponse()


class _FakeTimeout:
    """Opener that always raises a transient network timeout."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, req: Any, timeout: float = 30) -> Any:  # noqa: ARG002
        self.calls += 1
        raise TimeoutError("timed out")


@pytest.fixture(autouse=True)
def _stubApiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key")


# =============================================================================
# AC6: N-failures -> quarantine -> single surfacing -> re-drain
# =============================================================================


def test_quarantineLifecycle_nFailsThenThrottleThenRedrain(
    tempDbPath: str, caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock(datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC))
    opener500 = _Fake500()
    client = SyncClient(
        _config(tempDbPath, threshold=3, throttleSeconds=3600),
        httpOpener=opener500, sleep=_noSleep, clock=clock,
    )

    caplog.set_level(logging.WARNING, logger="src.pi.sync.client")

    # 3 consecutive server-rejection failures -> the 3rd quarantines.
    r1 = client.pushDelta(_TABLE)
    r2 = client.pushDelta(_TABLE)
    r3 = client.pushDelta(_TABLE)
    assert [r1.status, r2.status, r3.status] == [
        PushStatus.FAILED, PushStatus.FAILED, PushStatus.FAILED,
    ]
    assert opener500.calls == 3  # each push hit the network

    with sqlite3.connect(tempDbPath) as conn:
        count, quarantinedAt = sync_log.getQuarantineState(conn, _TABLE)
    assert count == 3
    assert quarantinedAt is not None  # quarantined on the 3rd failure

    # 4th cycle within the throttle window: SKIP the push, no network call.
    r4 = client.pushDelta(_TABLE)
    assert r4.status == PushStatus.QUARANTINED
    assert opener500.calls == 3  # unchanged -> not re-attempted every cycle

    # Surfaced exactly once across all four pushes.
    quarantineLogs = [
        rec for rec in caplog.records if "SYNC_QUARANTINE" in rec.getMessage()
    ]
    assert len(quarantineLogs) == 1

    # Throttle window elapses + the resolution target now exists (US-367):
    # a throttled re-attempt succeeds and re-drains the record.
    clock.advance(3601)
    opener = _FakeSuccess()
    client._httpOpener = opener  # noqa: SLF001 -- swap transport for re-drain
    r5 = client.pushDelta(_TABLE)
    assert r5.status == PushStatus.OK
    assert opener.calls == 1  # the re-drain DID hit the network

    with sqlite3.connect(tempDbPath) as conn:
        count, quarantinedAt = sync_log.getQuarantineState(conn, _TABLE)
        lastId, _, _, status = sync_log.getHighWaterMark(conn, _TABLE)
    assert count == 0  # cleared on success
    assert quarantinedAt is None
    assert lastId == 1  # HWM finally advanced once the row drained
    assert status == "ok"


def test_quarantinedRecord_preservedAndHwmNotAdvanced(tempDbPath: str) -> None:
    """While quarantined the raw record stays on the Pi; HWM never advanced."""
    clock = _Clock(datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC))
    client = SyncClient(
        _config(tempDbPath, threshold=2),
        httpOpener=_Fake500(), sleep=_noSleep, clock=clock,
    )
    client.pushDelta(_TABLE)
    client.pushDelta(_TABLE)  # quarantined here

    with sqlite3.connect(tempDbPath) as conn:
        rawRows = conn.execute("SELECT COUNT(*) FROM dtc_freeze_frame").fetchone()[0]
        lastId, _, _, _ = sync_log.getHighWaterMark(conn, _TABLE)
    assert rawRows == 1  # preserved, never dropped
    assert lastId == 0  # failed pushes never advance the high-water mark


def test_networkFailures_doNotQuarantine(tempDbPath: str) -> None:
    """Transient network failures must NOT count toward quarantine."""
    clock = _Clock(datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC))
    client = SyncClient(
        _config(tempDbPath, threshold=2),
        httpOpener=_FakeTimeout(), sleep=_noSleep, clock=clock,
    )
    r1 = client.pushDelta(_TABLE)
    r2 = client.pushDelta(_TABLE)
    r3 = client.pushDelta(_TABLE)

    assert [r1.status, r2.status, r3.status] == [PushStatus.FAILED] * 3
    with sqlite3.connect(tempDbPath) as conn:
        count, quarantinedAt = sync_log.getQuarantineState(conn, _TABLE)
    assert count == 0  # network failures are not "identical resolution failures"
    assert quarantinedAt is None


def test_forcePushBypassesQuarantineThrottle(tempDbPath: str) -> None:
    """forcePush is the explicit re-drain: it ignores the throttle window."""
    clock = _Clock(datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC))
    client = SyncClient(
        _config(tempDbPath, threshold=2, throttleSeconds=99999),
        httpOpener=_Fake500(), sleep=_noSleep, clock=clock,
    )
    client.pushDelta(_TABLE)
    client.pushDelta(_TABLE)  # quarantined

    # A normal cycle would skip (throttle huge); forcePush attempts anyway.
    success = _FakeSuccess()
    client._httpOpener = success  # noqa: SLF001
    summary = client.forcePush()

    ffResult = next(r for r in summary.results if r.tableName == _TABLE)
    assert ffResult.status == PushStatus.OK
    assert success.calls >= 1
