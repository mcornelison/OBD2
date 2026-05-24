################################################################################
# File Name: test_update_propagation.py
# Purpose/Description: Sprint 30 / V0.27.4 US-315 (B-065) regression gate --
#                      Pi -> server UPDATE propagation for delta-syncable
#                      tables that issue UPDATE on existing rows
#                      (battery_health_log close-event, drive_summary metadata
#                      backfill, dtc_log last_seen bump).  Pre-fix: cursor was
#                      pk-monotone INSERT-only; once a row INSERTed and the
#                      cursor advanced past its PK, no mechanism re-fetched it.
#                      Post-fix: a parallel modified_at cursor catches UPDATEs
#                      to existing rows alongside the INSERT delta.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-315) | Initial implementation -- B-065 close
# ================================================================================
################################################################################

"""
Sprint US-315 / B-065 regression gate: UPDATE propagation alongside INSERT delta.

The bug: ``src/pi/sync/client.py`` + ``src/pi/data/sync_log.py`` use a
pk-monotone high-water-mark cursor.  Once a row INSERTs and the cursor
advances past its PK, no mechanism re-fetches it -- UPDATEs to existing
rows on the Pi never propagate to the server.  Empirical evidence: 6 of 6
drains (10-15) on the V0.27.2 deploy showed Pi-side close-event UPDATE
never landed on the server (Spool 2026-05-10 audit).

The fix design (additive):

* Per-table opt-in via :data:`sync_log.SYNC_UPDATE_TABLES_PK`.
* Each opt-in table gets a ``_sync_modified_at`` TEXT column + AFTER UPDATE
  trigger.  The trigger sets the column to ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')``
  whenever an application UPDATE doesn't explicitly touch it (the
  ``WHEN NEW IS OLD`` guard).
* :data:`sync_log` schema gains ``last_synced_modified_at`` TEXT column.
* :func:`sync_log.getDeltaRows` runs a combined query for opt-in tables:
  ``WHERE pk > ? OR _sync_modified_at > ?``.  Non-opt-in tables retain
  the legacy pk-only query.
* :meth:`SyncClient.pushDelta` advances both cursors after success.

These tests would FAIL pre-fix on the second push step (UPDATE never
propagates) and pass post-fix.
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

# =============================================================================
# HTTP capture stub
# =============================================================================


class _CapturingOpener:
    """Capture every POST payload routed through urlopen.

    Used in place of ``urllib.request.urlopen`` so we can assert on the
    exact wire-shape Pi sent (without opening a real socket).  Returns a
    minimal context-manager object whose ``read()`` drains cleanly --
    matches the surface the SyncClient uses (line 686-688 of client.py).
    """

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req: Any, timeout: float | None = None) -> Any:
        body = req.data.decode("utf-8") if req.data else "{}"
        self.requests.append(json.loads(body))
        return _FakeResponse()


class _FakeResponse:
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def read(self) -> bytes:
        return b""


# =============================================================================
# Fixtures + helpers
# =============================================================================


@pytest.fixture
def piDb(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Yield a freshly-created Pi SQLite path; clean up after the test."""
    monkeypatch.setenv("COMPANION_API_KEY", "test-key")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    # On Windows, SQLite handles can briefly outlive the test under GC
    # pressure; tolerate the rare PermissionError on the temp dir cleanup
    # rather than failing the run for housekeeping noise.
    try:
        if os.path.exists(path):
            os.unlink(path)
    except PermissionError:
        pass


def _baseConfig(dbPath: str, *, enabled: bool = True) -> dict[str, Any]:
    """Minimal Pi config for SyncClient tests."""
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "companionService": {
                "enabled": enabled,
                "baseUrl": "http://localhost:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 5,
                "batchSize": 500,
                "retryMaxAttempts": 0,
                "retryBackoffSeconds": [],
            },
        },
    }


def _setupBatteryHealthLogTable(conn: sqlite3.Connection) -> None:
    """Production-shape battery_health_log + B-065 sync bookkeeping."""
    conn.execute("""
        CREATE TABLE battery_health_log (
            drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_timestamp TEXT,
            end_timestamp TEXT,
            start_soc REAL,
            end_soc REAL,
            start_vcell_v REAL,
            end_vcell_v REAL,
            runtime_seconds INTEGER,
            ambient_temp_c REAL
        )
    """)
    sync_log.ensureSyncModifiedAtSchema(conn)
    conn.commit()


def _setupDriveSummaryTable(conn: sqlite3.Connection) -> None:
    """Production-shape drive_summary slice for backfill propagation tests."""
    conn.execute("""
        CREATE TABLE drive_summary (
            drive_id INTEGER PRIMARY KEY,
            ambient_temp_at_start_c REAL,
            starting_battery_v REAL,
            barometric_kpa_at_start REAL,
            data_source TEXT NOT NULL DEFAULT 'real'
        )
    """)
    sync_log.ensureSyncModifiedAtSchema(conn)
    conn.commit()


def _setupDtcLogTable(conn: sqlite3.Connection) -> None:
    """Production-shape dtc_log slice for last_seen bump tests."""
    conn.execute("""
        CREATE TABLE dtc_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_id INTEGER,
            dtc_code TEXT NOT NULL,
            first_seen_timestamp TEXT NOT NULL,
            last_seen_timestamp TEXT NOT NULL
        )
    """)
    sync_log.ensureSyncModifiedAtSchema(conn)
    conn.commit()


def _setupRealtimeDataTable(conn: sqlite3.Connection) -> None:
    """Production-shape realtime_data slice for INSERT-only regression tests."""
    conn.execute("""
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL
        )
    """)
    sync_log.ensureSyncModifiedAtSchema(conn)
    conn.commit()


# =============================================================================
# Tests -- ensureSyncModifiedAtSchema migration
# =============================================================================


class TestEnsureSyncModifiedAtSchema:
    """Migration helper: idempotent ALTER TABLE + CREATE TRIGGER."""

    def test_addsModifiedAtColumn_andTrigger_toBatteryHealthLog(
        self, piDb: str,
    ) -> None:
        """First call adds the column + trigger; trigger fires on UPDATE."""
        with sqlite3.connect(piDb) as conn:
            _setupBatteryHealthLogTable(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(battery_health_log)")}
            assert "_sync_modified_at" in cols
            # Trigger fires on UPDATE: insert a row, update it, observe the
            # column got populated.
            conn.execute(
                "INSERT INTO battery_health_log "
                "(start_timestamp, start_vcell_v) VALUES (?, ?)",
                ("2026-05-10T10:00:00Z", 4.17),
            )
            conn.commit()
            preUpdate = conn.execute(
                "SELECT _sync_modified_at FROM battery_health_log "
                "WHERE drain_event_id = 1",
            ).fetchone()
            # Pre-UPDATE: column is NULL (we don't backfill on INSERT;
            # INSERT delta path uses pk cursor).
            assert preUpdate[0] is None

            conn.execute(
                "UPDATE battery_health_log SET end_timestamp = ? "
                "WHERE drain_event_id = 1",
                ("2026-05-10T10:13:00Z",),
            )
            conn.commit()
            postUpdate = conn.execute(
                "SELECT _sync_modified_at FROM battery_health_log "
                "WHERE drain_event_id = 1",
            ).fetchone()
            assert postUpdate[0] is not None
            assert postUpdate[0].startswith("2026-")  # ISO8601 stamp

    def test_isIdempotent_safeToCallTwice(self, piDb: str) -> None:
        """Re-running migration is a no-op (column + trigger already exist)."""
        with sqlite3.connect(piDb) as conn:
            _setupBatteryHealthLogTable(conn)
            # Second call must not raise (idempotency invariant).
            sync_log.ensureSyncModifiedAtSchema(conn)
            conn.commit()
            # Verify state is consistent.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(battery_health_log)")}
            assert "_sync_modified_at" in cols

    def test_addsLastSyncedModifiedAtColumn_toSyncLogTable(self, piDb: str) -> None:
        """sync_log gains last_synced_modified_at column for the new cursor."""
        with sqlite3.connect(piDb) as conn:
            _setupBatteryHealthLogTable(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(sync_log)")}
            assert "last_synced_modified_at" in cols


# =============================================================================
# Tests -- UPDATE propagation per opt-in table
# =============================================================================


class TestUpdatePropagation:
    """B-065 fix: pushDelta propagates UPDATEs alongside INSERT delta."""

    def test_batteryHealthLog_closeEvent_updatePropagatesViaSecondPush(
        self, piDb: str,
    ) -> None:
        """Drain close-event UPDATE re-pushes the existing row to the server.

        Pre-fix: second pushDelta returns EMPTY (cursor at max(pk), no
        modified_at branch).  Post-fix: returns OK with rowsPushed=1 and
        the payload contains the row with its close-event fields.
        """
        with sqlite3.connect(piDb) as conn:
            _setupBatteryHealthLogTable(conn)
            conn.execute(
                "INSERT INTO battery_health_log "
                "(start_timestamp, start_vcell_v) VALUES (?, ?)",
                ("2026-05-10T10:00:00Z", 4.17),
            )
            conn.commit()

        opener = _CapturingOpener()
        client = SyncClient(
            _baseConfig(piDb), httpOpener=opener, sleep=lambda _s: None,
        )

        # First push: INSERT delta (existing path, unchanged).
        r1 = client.pushDelta("battery_health_log")
        assert r1.status == PushStatus.OK
        assert r1.rowsPushed == 1
        firstRows = opener.requests[-1]["tables"]["battery_health_log"]["rows"]
        assert len(firstRows) == 1
        assert firstRows[0]["end_timestamp"] is None  # not yet closed

        # Pi-side close-event UPDATE (production: BatteryHealthRecorder
        # .endDrainEvent at battery_health.py:539).
        with sqlite3.connect(piDb) as conn:
            conn.execute(
                "UPDATE battery_health_log SET "
                "end_timestamp = ?, end_vcell_v = ?, runtime_seconds = ? "
                "WHERE drain_event_id = 1",
                ("2026-05-10T10:13:00Z", 3.42, 780),
            )
            conn.commit()

        # Second push: UPDATE propagation (B-065 fix).
        r2 = client.pushDelta("battery_health_log")
        assert r2.status == PushStatus.OK, (
            f"B-065 regression: UPDATE not propagated; "
            f"got status={r2.status} reason={r2.reason!r}"
        )
        assert r2.rowsPushed == 1
        secondRows = opener.requests[-1]["tables"]["battery_health_log"]["rows"]
        assert len(secondRows) == 1
        assert secondRows[0]["end_timestamp"] == "2026-05-10T10:13:00Z"
        assert secondRows[0]["end_vcell_v"] == 3.42
        assert secondRows[0]["runtime_seconds"] == 780

    def test_driveSummary_metadataBackfill_updatePropagatesViaSecondPush(
        self, piDb: str,
    ) -> None:
        """drive_summary cold-start NULL backfill UPDATE propagates."""
        with sqlite3.connect(piDb) as conn:
            _setupDriveSummaryTable(conn)
            # Initial INSERT with NULL backfill columns (the Drive-3
            # cold-start NULL bug US-228 / drive_summary.py:605).
            conn.execute(
                "INSERT INTO drive_summary "
                "(drive_id, ambient_temp_at_start_c, "
                " starting_battery_v, barometric_kpa_at_start) "
                "VALUES (?, ?, ?, ?)",
                (11, None, None, None),
            )
            conn.commit()

        opener = _CapturingOpener()
        client = SyncClient(
            _baseConfig(piDb), httpOpener=opener, sleep=lambda _s: None,
        )

        r1 = client.pushDelta("drive_summary")
        assert r1.status == PushStatus.OK and r1.rowsPushed == 1

        # Backfill UPDATE (drive_summary.py:741).
        with sqlite3.connect(piDb) as conn:
            conn.execute(
                "UPDATE drive_summary SET "
                "ambient_temp_at_start_c = ?, "
                "starting_battery_v = ?, "
                "barometric_kpa_at_start = ? "
                "WHERE drive_id = ?",
                (24.5, 12.4, 100.8, 11),
            )
            conn.commit()

        r2 = client.pushDelta("drive_summary")
        assert r2.status == PushStatus.OK, (
            f"B-065 regression: UPDATE not propagated; "
            f"got status={r2.status} reason={r2.reason!r}"
        )
        assert r2.rowsPushed == 1
        secondRows = opener.requests[-1]["tables"]["drive_summary"]["rows"]
        assert len(secondRows) == 1
        assert secondRows[0]["ambient_temp_at_start_c"] == 24.5
        assert secondRows[0]["starting_battery_v"] == 12.4
        assert secondRows[0]["barometric_kpa_at_start"] == 100.8

    def test_dtcLog_lastSeenBump_updatePropagatesViaSecondPush(
        self, piDb: str,
    ) -> None:
        """dtc_log last_seen_timestamp UPDATE on repeat sighting propagates."""
        with sqlite3.connect(piDb) as conn:
            _setupDtcLogTable(conn)
            conn.execute(
                "INSERT INTO dtc_log "
                "(drive_id, dtc_code, first_seen_timestamp, last_seen_timestamp) "
                "VALUES (?, ?, ?, ?)",
                (11, "P0420", "2026-05-10T10:00:00Z", "2026-05-10T10:00:00Z"),
            )
            conn.commit()

        opener = _CapturingOpener()
        client = SyncClient(
            _baseConfig(piDb), httpOpener=opener, sleep=lambda _s: None,
        )

        r1 = client.pushDelta("dtc_log")
        assert r1.status == PushStatus.OK and r1.rowsPushed == 1

        # last_seen bump (dtc_logger.py:541).
        with sqlite3.connect(piDb) as conn:
            conn.execute(
                "UPDATE dtc_log SET last_seen_timestamp = ? "
                "WHERE drive_id = ? AND dtc_code = ?",
                ("2026-05-10T10:30:00Z", 11, "P0420"),
            )
            conn.commit()

        r2 = client.pushDelta("dtc_log")
        assert r2.status == PushStatus.OK, (
            f"B-065 regression: UPDATE not propagated; "
            f"got status={r2.status} reason={r2.reason!r}"
        )
        assert r2.rowsPushed == 1
        secondRows = opener.requests[-1]["tables"]["dtc_log"]["rows"]
        assert len(secondRows) == 1
        assert secondRows[0]["last_seen_timestamp"] == "2026-05-10T10:30:00Z"


# =============================================================================
# Tests -- INSERT-only contract preserved (no regressions)
# =============================================================================


class TestInsertOnlyPathPreserved:
    """The INSERT-side delta logic for non-opt-in tables MUST stay unchanged.

    realtime_data is the canonical INSERT-only table -- never UPDATEd
    in production.  The pk-monotone cursor is its sole sync mechanism.
    These tests pin the back-compat invariant from the doNotTouch list.
    """

    def test_pushDelta_advancesCursor_andEmptyOnSecondCall(
        self, piDb: str,
    ) -> None:
        """realtime_data: standard pk-monotone delta semantics, no regress."""
        with sqlite3.connect(piDb) as conn:
            _setupRealtimeDataTable(conn)
            for i in range(5):
                conn.execute(
                    "INSERT INTO realtime_data (timestamp, parameter_name, value) "
                    "VALUES (?, ?, ?)",
                    (f"2026-05-10T00:00:{i:02d}Z", "RPM", 1000.0 + i),
                )
            conn.commit()

        opener = _CapturingOpener()
        client = SyncClient(
            _baseConfig(piDb), httpOpener=opener, sleep=lambda _s: None,
        )

        r1 = client.pushDelta("realtime_data")
        assert r1.status == PushStatus.OK
        assert r1.rowsPushed == 5

        # Second call: nothing new, cursor at max -- EMPTY (back-compat).
        r2 = client.pushDelta("realtime_data")
        assert r2.status == PushStatus.EMPTY
        assert r2.rowsPushed == 0

    def test_pushDelta_doesNotDoublePush_afterUpdate_onOptInTable(
        self, piDb: str,
    ) -> None:
        """After UPDATE propagates once, third push is EMPTY (cursor advanced).

        Pin the invariant that both cursors advance correctly so a
        steady-state Pi doesn't re-push the same UPDATE forever.
        """
        with sqlite3.connect(piDb) as conn:
            _setupBatteryHealthLogTable(conn)
            conn.execute(
                "INSERT INTO battery_health_log "
                "(start_timestamp, start_vcell_v) VALUES (?, ?)",
                ("2026-05-10T10:00:00Z", 4.17),
            )
            conn.commit()

        opener = _CapturingOpener()
        client = SyncClient(
            _baseConfig(piDb), httpOpener=opener, sleep=lambda _s: None,
        )

        # INSERT push.
        r1 = client.pushDelta("battery_health_log")
        assert r1.status == PushStatus.OK

        # UPDATE -> push -> assert OK.
        with sqlite3.connect(piDb) as conn:
            conn.execute(
                "UPDATE battery_health_log SET end_timestamp = ? "
                "WHERE drain_event_id = 1",
                ("2026-05-10T10:13:00Z",),
            )
            conn.commit()
        r2 = client.pushDelta("battery_health_log")
        assert r2.status == PushStatus.OK

        # Third push: nothing new since the UPDATE was already propagated.
        r3 = client.pushDelta("battery_health_log")
        assert r3.status == PushStatus.EMPTY
        assert r3.rowsPushed == 0
