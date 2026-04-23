################################################################################
# File Name: test_sync_client_upsert.py
# Purpose/Description: Tests covering SyncClient behavior for the snapshot
#                      (upsert/static) tables excluded from delta sync
#                      (US-194 / TD-025 + TD-026).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | US-194 -- verify snapshot tables (profiles,
#               |              | vehicle_info) are excluded cleanly from
#               |              | pushDelta / pushAllDeltas rather than crashing
# ================================================================================
################################################################################

"""
SyncClient behavior for snapshot (upsert/static) tables after US-194.

Sprint contract: "Upsert/static tables (vehicle_info, calibration_sessions,
profiles) sync via upsert-by-natural-PK path -- or are explicitly excluded
from sync with a clear comment."

US-194 picks the explicit-exclusion route for ``profiles`` and
``vehicle_info`` (both have TEXT natural PKs that make delta-by-PK
semantically meaningless).  ``calibration_sessions`` stays in delta-sync
via the PK registry (its PK is INTEGER, just named ``session_id``).

This test module pins:

1. :meth:`SyncClient.pushDelta` called on a snapshot table returns a
   :class:`PushResult` with a SKIPPED-style status -- never raises,
   never makes a network call.
2. :meth:`SyncClient.pushAllDeltas` reports the snapshot tables in its
   results for back-compat (same length as IN_SCOPE_TABLES), but none
   of them triggers the HTTP path.
3. ``calibration_sessions`` (integer PK with non-standard name) DOES
   still push through delta-sync -- TD-025's integer-PK table works.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from typing import Any

import pytest

from src.pi.data import sync_log
from src.pi.sync import PushStatus, SyncClient

# --------------------------------------------------------------------------- #
# Shared test scaffolding
# --------------------------------------------------------------------------- #


def _baseConfig(dbPath: str) -> dict[str, Any]:
    """Enabled Pi config with a synthetic companion endpoint."""
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


class _RecordingOpener:
    """Fake ``urllib.request.urlopen`` that records every POST.

    Returns an HTTP 200 empty body.  Tests use ``self.calls`` to assert
    which tables actually hit the wire (vs were skipped before network).
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, req: Any, timeout: float) -> Any:
        body = req.data.decode("utf-8") if req.data else ""
        payload = json.loads(body) if body else {}
        self.calls.append({"url": req.full_url, "payload": payload})
        return _fakeResponse(status=200, body=b"{}")


class _FakeHttpResponse:
    """Minimal context-manager-compatible stand-in for an HTTPResponse."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHttpResponse:  # noqa: PYI034
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def _fakeResponse(status: int, body: bytes) -> _FakeHttpResponse:
    return _FakeHttpResponse(status, body)


def _createAllInScopeStubs(conn: sqlite3.Connection) -> None:
    """Create every IN_SCOPE_TABLES table at its PRODUCTION PK shape.

    Unlike the legacy ``_createEmptyInScopeTables`` helper in the US-149
    tests -- which gave every table an ``id INTEGER`` PK and therefore
    could not see the natural-PK bug -- this helper faithfully mirrors
    ``src/pi/obdii/database_schema.py``.
    """
    # Append-only: id INTEGER PK (five tables) + session_id INTEGER PK (one).
    conn.execute(
        "CREATE TABLE realtime_data ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT, parameter_name TEXT, value REAL)"
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
    # calibration_sessions PK is session_id, NOT id.
    conn.execute(
        "CREATE TABLE calibration_sessions ("
        "session_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "start_time TEXT, notes TEXT)"
    )
    # US-204: dtc_log -- append-only id INTEGER PK.
    conn.execute(
        "CREATE TABLE dtc_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "dtc_code TEXT NOT NULL, status TEXT NOT NULL)"
    )
    # US-206: drive_summary -- drive_id is the PK (no auto-increment;
    # the Pi counter mints it).
    conn.execute(
        "CREATE TABLE drive_summary ("
        "drive_id INTEGER PRIMARY KEY, "
        "ambient_temp_at_start_c REAL, "
        "starting_battery_v REAL, "
        "barometric_kpa_at_start REAL, "
        "data_source TEXT NOT NULL DEFAULT 'real')"
    )
    # US-217: battery_health_log -- drain_event_id INTEGER PK AUTOINCREMENT.
    conn.execute(
        "CREATE TABLE battery_health_log ("
        "drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "start_timestamp TEXT NOT NULL, "
        "end_timestamp TEXT, "
        "start_soc REAL NOT NULL, "
        "end_soc REAL, "
        "runtime_seconds INTEGER, "
        "ambient_temp_c REAL, "
        "load_class TEXT NOT NULL DEFAULT 'production', "
        "notes TEXT, "
        "data_source TEXT NOT NULL DEFAULT 'real')"
    )
    # Snapshot tables with natural TEXT PKs.
    conn.execute(
        "CREATE TABLE profiles ("
        "id TEXT PRIMARY KEY, name TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO profiles (id, name) VALUES ('daily', 'Daily')"
    )
    conn.execute(
        "INSERT INTO profiles (id, name) VALUES ('performance', 'Performance')"
    )
    conn.execute(
        "CREATE TABLE vehicle_info ("
        "vin TEXT PRIMARY KEY, make TEXT, model TEXT, year INTEGER)"
    )
    conn.execute(
        "INSERT INTO vehicle_info (vin, make, model, year) "
        "VALUES ('4A3AK34Y2WE046123', 'Mitsubishi', 'Eclipse', 1998)"
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def tmpDbPath() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="sync_upsert_test_")
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def productionShapedDb(tmpDbPath: str) -> str:
    """Create a DB with every in-scope table at production PK shape."""
    with sqlite3.connect(tmpDbPath) as conn:
        sync_log.initDb(conn)
        _createAllInScopeStubs(conn)
    return tmpDbPath


@pytest.fixture
def recordingOpener() -> _RecordingOpener:
    return _RecordingOpener()


@pytest.fixture
def syncClient(
    productionShapedDb: str,
    recordingOpener: _RecordingOpener,
    monkeypatch: pytest.MonkeyPatch,
) -> SyncClient:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-ignored")
    return SyncClient(
        _baseConfig(productionShapedDb),
        httpOpener=recordingOpener,
        sleep=lambda _s: None,
    )


# --------------------------------------------------------------------------- #
# Snapshot tables: pushDelta returns a clean skip
# --------------------------------------------------------------------------- #


class TestPushDeltaOnSnapshotTables:
    """Calling pushDelta on profiles / vehicle_info must never crash."""

    def test_pushDelta_profiles_does_not_raise(
        self, syncClient: SyncClient,
    ) -> None:
        """TD-026 regression: pushDelta('profiles') surfaces cleanly."""
        result = syncClient.pushDelta("profiles")
        assert result is not None
        assert result.tableName == "profiles"

    def test_pushDelta_profiles_returns_non_failed_status(
        self, syncClient: SyncClient,
    ) -> None:
        """Snapshot-table skip is NOT a failure -- it's a deliberate skip.

        PushStatus.FAILED would mark an integrity problem (rerun next
        pass).  A snapshot table's skip is expected behavior; the status
        must distinguish that from a real failure.
        """
        result = syncClient.pushDelta("profiles")
        assert result.status is not PushStatus.FAILED

    def test_pushDelta_vehicle_info_does_not_raise(
        self, syncClient: SyncClient,
    ) -> None:
        """TD-025 regression: vehicle_info (vin TEXT PK) does not crash."""
        result = syncClient.pushDelta("vehicle_info")
        assert result is not None
        assert result.tableName == "vehicle_info"

    def test_pushDelta_profiles_makes_no_network_call(
        self,
        syncClient: SyncClient,
        recordingOpener: _RecordingOpener,
    ) -> None:
        """Snapshot skip happens before any HTTP work."""
        _ = syncClient.pushDelta("profiles")
        assert recordingOpener.calls == []

    def test_pushDelta_vehicle_info_makes_no_network_call(
        self,
        syncClient: SyncClient,
        recordingOpener: _RecordingOpener,
    ) -> None:
        _ = syncClient.pushDelta("vehicle_info")
        assert recordingOpener.calls == []

    def test_pushDelta_snapshot_table_records_zero_rows(
        self, syncClient: SyncClient,
    ) -> None:
        """Skipped push reports 0 rows pushed (for operator reports)."""
        result = syncClient.pushDelta("profiles")
        assert result.rowsPushed == 0


# --------------------------------------------------------------------------- #
# pushAllDeltas end-to-end shape after the fix
# --------------------------------------------------------------------------- #


class TestPushAllDeltasAfterFix:
    """pushAllDeltas runs end-to-end on production PK shape without crashing."""

    def test_pushAllDeltas_returns_one_result_per_in_scope_table(
        self, syncClient: SyncClient,
    ) -> None:
        """BC: result set length still equals IN_SCOPE_TABLES count.

        Snapshot tables surface as SKIPPED-style results, not missing
        entries.  This preserves operator-visible table coverage in
        ``scripts/sync_now.py`` output.
        """
        results = syncClient.pushAllDeltas()
        returnedNames = {r.tableName for r in results}
        assert returnedNames == sync_log.IN_SCOPE_TABLES

    def test_pushAllDeltas_completes_without_exceptions(
        self, syncClient: SyncClient,
    ) -> None:
        """TD-025 acceptance: a fresh-init Pi DB sync completes end-to-end.

        Previously crashed on the first natural-PK table.  After the
        fix, every table is either delta-pushed or skipped -- never
        raises.
        """
        _ = syncClient.pushAllDeltas()  # no raise

    def test_pushAllDeltas_does_not_POST_for_snapshot_tables(
        self,
        syncClient: SyncClient,
        recordingOpener: _RecordingOpener,
    ) -> None:
        """Snapshot tables must not generate any HTTP traffic."""
        _ = syncClient.pushAllDeltas()
        for call in recordingOpener.calls:
            tables = call["payload"].get("tables", {})
            assert "profiles" not in tables
            assert "vehicle_info" not in tables


# --------------------------------------------------------------------------- #
# calibration_sessions -- integer PK with non-standard name DOES push
# --------------------------------------------------------------------------- #


class TestPushDeltaCalibrationSessionsStillWorks:
    """TD-025 partial fix: session_id INTEGER PK uses the registry path."""

    def test_pushDelta_calibration_sessions_no_such_column_id(
        self,
        productionShapedDb: str,
        recordingOpener: _RecordingOpener,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """TD-025 core: no 'no such column: id' error on session_id PK."""
        with sqlite3.connect(productionShapedDb) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO calibration_sessions "
                    "(start_time, notes) VALUES (?, ?)",
                    (f"2026-04-19T12:00:{i:02d}Z", f"s{i}"),
                )
            conn.commit()

        monkeypatch.setenv("COMPANION_API_KEY", "test-key-ignored")
        client = SyncClient(
            _baseConfig(productionShapedDb),
            httpOpener=recordingOpener,
            sleep=lambda _s: None,
        )
        result = client.pushDelta("calibration_sessions")
        assert result.status is PushStatus.OK
        assert result.rowsPushed == 3

    def test_pushDelta_calibration_sessions_advances_high_water_mark(
        self,
        productionShapedDb: str,
        recordingOpener: _RecordingOpener,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Successful push advances last_synced_id for session_id-PK tables."""
        with sqlite3.connect(productionShapedDb) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO calibration_sessions "
                    "(start_time, notes) VALUES (?, ?)",
                    (f"2026-04-19T12:00:{i:02d}Z", f"s{i}"),
                )
            conn.commit()

        monkeypatch.setenv("COMPANION_API_KEY", "test-key-ignored")
        client = SyncClient(
            _baseConfig(productionShapedDb),
            httpOpener=recordingOpener,
            sleep=lambda _s: None,
        )
        _ = client.pushDelta("calibration_sessions")

        with sqlite3.connect(productionShapedDb) as conn:
            lastId, _at, _batch, status = sync_log.getHighWaterMark(
                conn, "calibration_sessions",
            )
        assert lastId == 3
        assert status == "ok"

    def test_pushDelta_calibration_sessions_payload_renames_session_id_to_id(
        self,
        productionShapedDb: str,
        recordingOpener: _RecordingOpener,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Payload rows carry 'id' (from session_id) so server rule applies.

        The server maps Pi-native ``id`` to ``source_id`` (see
        src/server/api/sync.py).  To avoid a server-side protocol change,
        Pi renames ``session_id`` -> ``id`` in calibration_sessions rows
        before POSTing.  The session_id value itself is preserved as the
        authoritative id -- it IS the PK.
        """
        with sqlite3.connect(productionShapedDb) as conn:
            for i in range(2):
                conn.execute(
                    "INSERT INTO calibration_sessions "
                    "(start_time, notes) VALUES (?, ?)",
                    (f"2026-04-19T12:00:{i:02d}Z", f"s{i}"),
                )
            conn.commit()

        monkeypatch.setenv("COMPANION_API_KEY", "test-key-ignored")
        client = SyncClient(
            _baseConfig(productionShapedDb),
            httpOpener=recordingOpener,
            sleep=lambda _s: None,
        )
        _ = client.pushDelta("calibration_sessions")

        assert len(recordingOpener.calls) == 1
        rows = recordingOpener.calls[0]["payload"]["tables"][
            "calibration_sessions"
        ]["rows"]
        assert len(rows) == 2
        # Every row has 'id' (the canonical payload key the server expects).
        assert all("id" in row for row in rows)
        # The 'id' value equals the underlying session_id (1, 2).
        assert sorted(int(row["id"]) for row in rows) == [1, 2]
        # 'session_id' must NOT appear -- the rename is total, not a copy.
        # (Server rejects unknown columns; leaving both causes SQL errors.)
        assert all("session_id" not in row for row in rows)
