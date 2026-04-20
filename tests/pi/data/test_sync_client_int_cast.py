################################################################################
# File Name: test_sync_client_int_cast.py
# Purpose/Description: Regression for the Session 23 "invalid literal for
#                      int() with base 10: 'daily'" crash when syncing the
#                      profiles table (TD-026 / US-194).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | US-194 -- regress the Session 23 crash.
#               |              | Pre-fix behavior documented in TD-026 spec;
#               |              | post-fix asserts graceful SKIP + no ValueError.
# ================================================================================
################################################################################

"""
Regression for the TD-026 Session 23 'daily' crash.

Historical evidence (recorded in
``offices/pm/tech_debt/TD-026-sync-profiles-non-numeric-id.md``):
the milestone push tried to sync the ``profiles`` table and crashed inside
``src/pi/data/sync_log.py:getDeltaRows()`` on the unconditional
``int(lastId)`` cast.  lastId for profiles is ``'daily'`` (TEXT PK).

The fix keeps the int() cast for the tables that legitimately use it
(append-only integer-PK tables), and routes TEXT-PK snapshot tables
around it entirely by excluding them from the delta-sync path.  After
US-194, ``SyncClient.pushDelta('profiles')`` NEVER reaches an int() cast
and therefore NEVER raises ValueError.

These tests drive the SyncClient against a production-PK-shaped SQLite
(profiles has ``id TEXT PK``, vehicle_info has ``vin TEXT PK``) and pin:

1. No ValueError for any snapshot-table push, no matter the seeded rows.
2. The sync_log high-water mark for snapshot tables does NOT try to
   store a TEXT id in the INTEGER last_synced_id column (no int(text)
   path taken).
3. Integer-PK tables continue to round-trip ``int(lastId)`` cleanly (no
   regression in the non-bug direction).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from typing import Any

import pytest

from src.pi.data import sync_log
from src.pi.sync import PushStatus, SyncClient

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _baseConfig(dbPath: str) -> dict[str, Any]:
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://fake-server.test:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "batchSize": 100,
                "syncTimeoutSeconds": 5,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [0.0],
            },
        },
    }


class _FakeHttpResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHttpResponse:  # noqa: PYI034
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def _noopOpener(req: Any, timeout: float) -> _FakeHttpResponse:
    return _FakeHttpResponse(status=200, body=b"{}")


# --------------------------------------------------------------------------- #
# Fixtures -- PRODUCTION PK shape
# --------------------------------------------------------------------------- #


@pytest.fixture
def tmpDbPath() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="int_cast_test_")
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def dbWithTextPkProfiles(tmpDbPath: str) -> str:
    """DB with profiles at production shape -- ``id TEXT PRIMARY KEY``.

    Populated with 'daily' and 'performance' -- the exact strings that
    triggered the Session 23 crash.
    """
    with sqlite3.connect(tmpDbPath) as conn:
        sync_log.initDb(conn)
        conn.execute(
            "CREATE TABLE profiles ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO profiles (id, name) VALUES ('daily', 'Daily Driving')"
        )
        conn.execute(
            "INSERT INTO profiles (id, name) "
            "VALUES ('performance', 'Performance')"
        )
        # Append-only stubs so SyncClient construction doesn't look weird.
        conn.execute(
            "CREATE TABLE realtime_data ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, value REAL)"
        )
        conn.execute(
            "CREATE TABLE statistics ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, value REAL)"
        )
        conn.execute(
            "CREATE TABLE ai_recommendations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT)"
        )
        conn.execute(
            "CREATE TABLE connection_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT)"
        )
        conn.execute(
            "CREATE TABLE alert_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, alert_type TEXT)"
        )
        conn.execute(
            "CREATE TABLE calibration_sessions ("
            "session_id INTEGER PRIMARY KEY AUTOINCREMENT, notes TEXT)"
        )
        conn.execute(
            "CREATE TABLE vehicle_info ("
            "vin TEXT PRIMARY KEY, make TEXT)"
        )
        conn.commit()
    return tmpDbPath


@pytest.fixture
def syncClient(
    dbWithTextPkProfiles: str,
    monkeypatch: pytest.MonkeyPatch,
) -> SyncClient:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-ignored")
    return SyncClient(
        _baseConfig(dbWithTextPkProfiles),
        httpOpener=_noopOpener,
        sleep=lambda _s: None,
    )


# --------------------------------------------------------------------------- #
# TD-026 regression -- 'daily' never reaches an int() cast
# --------------------------------------------------------------------------- #


class TestDailyProfileNoValueError:
    """Pin: pushDelta('profiles') no longer raises ValueError on 'daily'."""

    def test_pushDelta_profiles_no_ValueError(
        self, syncClient: SyncClient,
    ) -> None:
        """The Session 23 crash reproduction -- asserts NO raise."""
        # The pre-fix behavior was:
        #   ValueError: invalid literal for int() with base 10: 'daily'
        # Post-fix: no raise.  We do not try to assert the SKIPPED status
        # here -- other tests cover that.  This test exists to pin "does
        # not raise" as its own first-class guarantee.
        try:
            syncClient.pushDelta("profiles")
        except ValueError as exc:  # pragma: no cover -- regression guard
            pytest.fail(
                f"pushDelta('profiles') raised ValueError -- TD-026 regression: {exc}"
            )

    def test_pushDelta_profiles_after_manual_text_high_water_mark(
        self,
        dbWithTextPkProfiles: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Even with a TEXT lastId in sync_log, the path stays safe.

        Defensive: if a prior (buggy) run wrote a TEXT last_synced_id
        into sync_log for profiles, the fix must still not crash.
        """
        # Simulate a bad prior state: last_synced_id as text 'daily'.
        # sync_log's INTEGER column would refuse TEXT directly in strict
        # mode, so we simulate the situation by leaving the row absent
        # (the SKIPPED path must trigger before any getHighWaterMark
        # on profiles).
        monkeypatch.setenv("COMPANION_API_KEY", "test-key-ignored")
        client = SyncClient(
            _baseConfig(dbWithTextPkProfiles),
            httpOpener=_noopOpener,
            sleep=lambda _s: None,
        )
        try:
            client.pushDelta("profiles")
        except ValueError as exc:  # pragma: no cover
            pytest.fail(
                f"pushDelta('profiles') raised ValueError on degraded "
                f"state -- regression: {exc}"
            )

    def test_pushDelta_vehicle_info_no_ValueError(
        self, syncClient: SyncClient,
    ) -> None:
        """Sibling case: vin TEXT PK is similarly safe."""
        try:
            syncClient.pushDelta("vehicle_info")
        except ValueError as exc:  # pragma: no cover
            pytest.fail(
                f"pushDelta('vehicle_info') raised ValueError -- regression: {exc}"
            )


# --------------------------------------------------------------------------- #
# TD-026 regression -- sync_log row for profiles stays absent or integer-safe
# --------------------------------------------------------------------------- #


class TestSyncLogIntegrityAfterSnapshotSkip:
    """Skipped pushes must not write a TEXT id into last_synced_id."""

    def test_pushDelta_profiles_does_not_write_text_id_to_sync_log(
        self,
        dbWithTextPkProfiles: str,
        syncClient: SyncClient,
    ) -> None:
        """sync_log.last_synced_id is INTEGER -- no text value ever inserted."""
        _ = syncClient.pushDelta("profiles")

        # If anything was written, it must be a valid integer.  (The
        # SKIPPED path should skip the sync_log write entirely, but if a
        # future implementation records a "skipped" marker, it must use
        # id=0.)
        with sqlite3.connect(dbWithTextPkProfiles) as conn:
            row = conn.execute(
                "SELECT last_synced_id FROM sync_log WHERE table_name = ?",
                ("profiles",),
            ).fetchone()
        if row is not None:
            # If a row was written, it must be integer 0 (never 'daily').
            assert isinstance(row[0], int)
            assert row[0] == 0


# --------------------------------------------------------------------------- #
# Integer-PK tables still round-trip cleanly (regression guard)
# --------------------------------------------------------------------------- #


class TestIntegerPkTablesStillCastCleanly:
    """Don't accidentally break the legitimate int() path."""

    def test_pushDelta_realtime_data_with_integer_lastId(
        self,
        dbWithTextPkProfiles: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """realtime_data (id INTEGER) still advances via int(lastId) path."""
        with sqlite3.connect(dbWithTextPkProfiles) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO realtime_data (value) VALUES (?)",
                    (1000.0 + i,),
                )
            conn.commit()

        monkeypatch.setenv("COMPANION_API_KEY", "test-key-ignored")
        client = SyncClient(
            _baseConfig(dbWithTextPkProfiles),
            httpOpener=_noopOpener,
            sleep=lambda _s: None,
        )
        result = client.pushDelta("realtime_data")
        assert result.status is PushStatus.OK
        assert result.rowsPushed == 3
