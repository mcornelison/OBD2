################################################################################
# File Name: test_pi_to_server_stored_ack_e2e.py
# Purpose/Description: End-to-end proof of US-776-i: the REAL Pi SyncClient
#                      pushes a row through EVERY delta sync table to the REAL
#                      server app (US-776-h stored ack) on a test database, and
#                      each table's mark advances to its stored maximum.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-11    | Rex (US-776-i)| Initial -- real client, real app, every table
# ================================================================================
################################################################################

"""
Real Pi client -> real server app, every delta table (US-776-i).

No ack is mocked here: that shape is what US-776-i removes.  The Pi database
is built by the production ``ObdDatabase.initialize()``, the server app is
``createApp()`` on a SQLite test database holding the server schema, and the
client's ``httpOpener`` hands each ``urllib`` request to the app in-process.
Every table in :data:`sync_log.DELTA_SYNC_TABLES` gets rows, so a table the
server stores short BY DESIGN -- one that could never advance under the
matching-ack rule -- fails here by name.
"""

from __future__ import annotations

import io
import sqlite3
import tempfile
import urllib.error
import urllib.parse
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from pi.obdii.database import ObdDatabase
from src.pi.data import sync_log
from src.pi.sync import PushStatus, SyncClient
from src.server.api.app import createApp
from src.server.config import Settings
from src.server.db.models import Base

pytestmark = pytest.mark.integration

_API_KEY = "stored-ack-e2e-key"
_DEVICE_ID = "chi-eclipse-01"

# One INSERT per delta table, run twice so each table holds two rows (pi_state
# is a singleton: initialize() already wrote its one row).  Columns are the
# NOT NULL ones without a default, read from the production schema.
_SEED_INSERTS: dict[str, str] = {
    "realtime_data": (
        "INSERT INTO realtime_data (timestamp, parameter_name, value, unit) "
        "VALUES ('2026-10-11T13:14:00Z', 'RPM', 812.0, 'rpm')"
    ),
    "statistics": (
        "INSERT INTO statistics (parameter_name, profile_id, max_value) "
        "VALUES ('RPM', 'daily', 6100.0)"
    ),
    "ai_recommendations": (
        "INSERT INTO ai_recommendations (recommendation) VALUES ('check IAT')"
    ),
    "connection_log": (
        "INSERT INTO connection_log (event_type, success) VALUES ('connect_attempt', 1)"
    ),
    "alert_log": (
        "INSERT INTO alert_log (alert_type, parameter_name, value, threshold) "
        "VALUES ('high', 'COOLANT_TEMP', 104.0, 100.0)"
    ),
    "calibration_sessions": (
        "INSERT INTO calibration_sessions (notes) VALUES ('bench')"
    ),
    "dtc_log": (
        "INSERT INTO dtc_log (dtc_code, status) VALUES ('P0301', 'stored')"
    ),
    "drive_summary": (
        "INSERT INTO drive_summary (drive_id, starting_battery_v) "
        "VALUES ((SELECT COALESCE(MAX(drive_id), 100) + 1 FROM drive_summary), 12.6)"
    ),
    "battery_health_log": (
        "INSERT INTO battery_health_log (start_vcell_v) VALUES (4.1)"
    ),
    "dtc_freeze_frame": (
        "INSERT INTO dtc_freeze_frame (pid_responses_json) VALUES ('{}')"
    ),
    "power_log": (
        "INSERT INTO power_log (event_type, power_source) VALUES ('ac_lost', 'battery')"
    ),
    "edr_imu_sample": (
        "INSERT INTO edr_imu_sample (ts_utc, ts_capture, seq, accel_z) "
        "VALUES ('2026-10-11T13:14:00.020Z', 1001.02, 1, 9.81)"
    ),
    "edr_light_sample": (
        "INSERT INTO edr_light_sample (ts_utc, ts_capture, seq, lux) "
        "VALUES ('2026-10-11T13:14:01.000Z', 1002.0, 1, 310.0)"
    ),
    "edr_imu_derived": (
        "INSERT INTO edr_imu_derived (ts_utc, ts_capture, seq, fusion_version, pitch_deg) "
        "VALUES ('2026-10-11T13:14:00.040Z', 1001.04, 2, 1, 1.5)"
    ),
    "drain_vcell_trajectory": (
        "INSERT INTO drain_vcell_trajectory (ts_utc, ts_capture, seq, vcell_v, cell_epoch) "
        "VALUES ('2026-10-11T13:20:00Z', 2000.0, 0, 3.9, 'unknown')"
    ),
}


# =============================================================================
# The bridge: urllib request -> the real ASGI app
# =============================================================================


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _AppOpener:
    """``urlopen``-compatible callable that serves each request from the app."""

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def __call__(self, req: Any, timeout: float = 30) -> _Response:  # noqa: ARG002
        path = urllib.parse.urlsplit(req.full_url).path
        response = self._client.request(
            req.get_method(), path, content=req.data, headers=dict(req.header_items()),
        )
        if response.status_code >= 400:
            raise urllib.error.HTTPError(
                req.full_url, response.status_code, response.reason_phrase,
                hdrs=None,  # type: ignore[arg-type]
                fp=io.BytesIO(response.content),
            )
        return _Response(response.content)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def serverDbUrl() -> Iterator[str]:
    """A temp SQLite file holding the server schema; yields its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    engine.dispose()
    yield tmp.name
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture
def appOpener(serverDbUrl: str) -> Iterator[_AppOpener]:
    """The real server app on the test database, behind a urllib opener."""
    # NullPool: TestClient runs each request on its own event loop, and an
    # aiosqlite connection must not outlive the loop that opened it.
    engine = create_async_engine(f"sqlite+aiosqlite:///{serverDbUrl}", poolclass=NullPool)
    app = createApp(settings=Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=_API_KEY,
        MAX_SYNC_PAYLOAD_MB=10,
    ))
    app.state.engine = engine
    yield _AppOpener(TestClient(app))


@pytest.fixture
def piDbPath(tmp_path: Path) -> str:
    """The production Pi schema with two rows in every delta table."""
    path = str(tmp_path / "pi.db")
    ObdDatabase(path).initialize()
    with sqlite3.connect(path) as conn:
        sync_log.initDb(conn)
        for _ in range(2):
            for statement in _SEED_INSERTS.values():
                conn.execute(statement)
        conn.commit()
    return path


@pytest.fixture(autouse=True)
def _apiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", _API_KEY)


def _config(piDbPath: str) -> dict[str, Any]:
    return {
        "deviceId": _DEVICE_ID,
        "pi": {
            "database": {"path": piDbPath},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://stored-ack.test",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 5,
                "batchSize": 500,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [0],
            },
        },
    }


def _piMax(piDbPath: str, tableName: str) -> int:
    pkColumn = sync_log.PK_COLUMN[tableName]
    with sqlite3.connect(piDbPath) as conn:
        return int(conn.execute(f"SELECT MAX({pkColumn}) FROM {tableName}").fetchone()[0])


def _serverMax(serverDbUrl: str, tableName: str) -> int | None:
    engine = create_engine(f"sqlite:///{serverDbUrl}")
    try:
        with engine.connect() as conn:
            return conn.execute(
                text(f"SELECT MAX(source_id) FROM {tableName} WHERE source_device = :d"),
                {"d": _DEVICE_ID},
            ).scalar()
    finally:
        engine.dispose()


# =============================================================================
# The proof
# =============================================================================


class TestEveryDeltaTableAdvancesOnTheRealAck:
    """Real client, real app: each table's mark lands on its stored maximum."""

    def test_seed_coversEveryDeltaTable(self) -> None:
        """
        Given: the delta sync set
        When: compared with the tables this test seeds
        Then: they are identical -- a newly registered table must be seeded here
        """
        assert set(_SEED_INSERTS) | {"pi_state"} == set(sync_log.DELTA_SYNC_TABLES)

    def test_pushAllDeltas_everyTableOk_markEqualsStoredMax(
        self, piDbPath: str, appOpener: _AppOpener, serverDbUrl: str,
    ) -> None:
        """
        Given: rows in every delta table, a real server app holding nothing
        When: the real SyncClient runs pushAllDeltas against it
        Then: every delta table is OK, and each mark equals both the Pi's
              largest pk and the server's largest stored source_id
        """
        client = SyncClient(_config(piDbPath), httpOpener=appOpener, sleep=lambda _s: None)

        results = {r.tableName: r for r in client.pushAllDeltas()}

        notOk = {
            name: (results[name].status, results[name].reason)
            for name in sync_log.DELTA_SYNC_TABLES
            if results[name].status is not PushStatus.OK
        }
        assert notOk == {}
        assert {name: results[name].rowsPushed for name in sync_log.DELTA_SYNC_TABLES} == {
            name: (1 if name == "pi_state" else 2) for name in sync_log.DELTA_SYNC_TABLES
        }
        with sqlite3.connect(piDbPath) as conn:
            marks = {
                name: sync_log.getHighWaterMark(conn, name)[0]
                for name in sync_log.DELTA_SYNC_TABLES
            }
        for name in sorted(sync_log.DELTA_SYNC_TABLES):
            assert marks[name] == _piMax(piDbPath, name), name
            assert marks[name] == _serverMax(serverDbUrl, name), name

    def test_secondSweep_isEmpty(
        self, piDbPath: str, appOpener: _AppOpener,
    ) -> None:
        """
        Given: a sweep whose every table advanced on the real ack
        When: the client sweeps again with no new rows
        Then: no delta table pushes a row -- the marks really moved
        """
        client = SyncClient(_config(piDbPath), httpOpener=appOpener, sleep=lambda _s: None)
        client.pushAllDeltas()

        second = {r.tableName: r for r in client.pushAllDeltas()}

        assert {
            name: second[name].status for name in sync_log.DELTA_SYNC_TABLES
        } == {name: PushStatus.EMPTY for name in sync_log.DELTA_SYNC_TABLES}
