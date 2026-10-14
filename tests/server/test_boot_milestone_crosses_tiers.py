################################################################################
# File Name: test_boot_milestone_crosses_tiers.py
# Purpose/Description: US-860-d -- boot_milestone is registered for delta sync
#                      on both tiers (Pi PK_COLUMN on 'id', server
#                      _TABLE_REGISTRY -> BootMilestone), the two tiers' column
#                      sets are pinned EQUAL, and the real Pi SyncClient pushes
#                      a boot's ladder to the real server app on the id cursor.
# Author: Rex (US-860-d)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-860-d)| Initial.
# ================================================================================
################################################################################
"""The boot milestone ladder crosses the tier boundary (US-860-d)."""

from __future__ import annotations

import io
import sqlite3
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
from src.pi.diagnostics.boot_milestone import MILESTONES
from src.pi.obdii.database_schema import SCHEMA_BOOT_MILESTONE
from src.pi.sync import PushStatus, SyncClient
from src.server.api.app import createApp
from src.server.api.sync import _TABLE_REGISTRY, ACCEPTED_TABLES
from src.server.config import Settings
from src.server.db.models import Base, BootMilestone

_TABLE = "boot_milestone"
_API_KEY = "boot-milestone-e2e-key"
_DEVICE_ID = "chi-eclipse-01"
_BOOT_ID = "3f1c0d2e-boot"

# Server-owned columns: the server's own key and the sync bookkeeping.
_SERVER_ONLY_COLUMNS = frozenset(
    {"id", "source_device", "source_id", "synced_at", "sync_batch_id"}
)


def _piSyncedColumns(conn: sqlite3.Connection) -> set[str]:
    """The Pi table's columns minus its id (which lands in source_id)."""
    rows = conn.execute(f"PRAGMA table_info({_TABLE})").fetchall()
    return {row[1] for row in rows} - {"id"}


def _serverSyncedColumns() -> set[str]:
    """The server model's columns minus the server-owned ones."""
    return set(BootMilestone.__table__.columns.keys()) - _SERVER_ONLY_COLUMNS


# =============================================================================
# Registration + the column-set pin
# =============================================================================


class TestRegistration:
    def test_piRegistersTheTableOnTheIdCursor(self) -> None:
        assert sync_log.PK_COLUMN[_TABLE] == "id"
        assert _TABLE in sync_log.DELTA_SYNC_TABLES

    def test_piDoesNotOptIntoTheUpdateCursor(self) -> None:
        """Rows never mutate (first-write-wins), so no modified_at cursor."""
        assert _TABLE not in sync_log.SYNC_UPDATE_TABLES_PK

    def test_serverAcceptsTheTableWithNoRename(self) -> None:
        assert _TABLE_REGISTRY[_TABLE] == (BootMilestone, ())
        assert _TABLE in ACCEPTED_TABLES


class TestColumnSetsAreEqual:
    def test_piColumns_equalTheServersSyncedColumns(self, tmp_path: Path) -> None:
        path = str(tmp_path / "pi.db")
        ObdDatabase(path).initialize()
        with sqlite3.connect(path) as conn:
            piColumns = _piSyncedColumns(conn)

        assert piColumns == _serverSyncedColumns()
        assert piColumns == {"boot_id", "milestone", "ts_utc", "uptime_s"}

    def test_aPiOnlyColumn_breaksThePin(self) -> None:
        """
        Given: the Pi table with one extra column the server does not have
        When: the two column sets are compared as the pin above compares them
        Then: they differ by exactly that column -- the pin would fail
        """
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(SCHEMA_BOOT_MILESTONE)
            conn.execute(f"ALTER TABLE {_TABLE} ADD COLUMN pi_only_note TEXT")
            piColumns = _piSyncedColumns(conn)
        finally:
            conn.close()

        assert piColumns != _serverSyncedColumns()
        assert piColumns - _serverSyncedColumns() == {"pi_only_note"}


# =============================================================================
# Real Pi client -> real server app (the e2e bridge, as US-776-i)
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


@pytest.fixture
def serverDbPath(tmp_path: Path) -> str:
    """A SQLite file holding the server schema."""
    path = str(tmp_path / "server.db")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


@pytest.fixture
def appOpener(serverDbPath: str) -> Iterator[_AppOpener]:
    """The real server app on the test database, behind a urllib opener."""
    # NullPool: TestClient runs each request on its own event loop, and an
    # aiosqlite connection must not outlive the loop that opened it.
    engine = create_async_engine(f"sqlite+aiosqlite:///{serverDbPath}", poolclass=NullPool)
    app = createApp(settings=Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=_API_KEY,
        MAX_SYNC_PAYLOAD_MB=10,
    ))
    app.state.engine = engine
    yield _AppOpener(TestClient(app))


@pytest.fixture
def piDbPath(tmp_path: Path) -> str:
    """The production Pi schema, boot_milestone empty."""
    path = str(tmp_path / "pi.db")
    ObdDatabase(path).initialize()
    with sqlite3.connect(path) as conn:
        sync_log.initDb(conn)
    return path


@pytest.fixture(autouse=True)
def _apiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", _API_KEY)


def _client(piDbPath: str, opener: _AppOpener, *, batchSize: int) -> SyncClient:
    config = {
        "deviceId": _DEVICE_ID,
        "pi": {
            "database": {"path": piDbPath},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://boot-milestone.test",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 5,
                "batchSize": batchSize,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [0],
            },
        },
    }
    return SyncClient(config, httpOpener=opener, sleep=lambda _s: None)


def _writeMilestones(piDbPath: str, rows: list[tuple[str, str, float]]) -> None:
    """Write (milestone, ts_utc, uptime_s) rows for one boot, in order."""
    with sqlite3.connect(piDbPath) as conn:
        conn.executemany(
            "INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) "
            "VALUES (?, ?, ?, ?)",
            [(_BOOT_ID, milestone, ts, uptime) for milestone, ts, uptime in rows],
        )
        conn.commit()


def _serverRows(serverDbPath: str) -> list[tuple[int, str, str, float]]:
    engine = create_engine(f"sqlite:///{serverDbPath}")
    try:
        with engine.connect() as conn:
            return [
                (int(r[0]), r[1], r[2], float(r[3]))
                for r in conn.execute(
                    text(
                        "SELECT source_id, boot_id, milestone, uptime_s "
                        "FROM boot_milestone WHERE source_device = :d ORDER BY source_id"
                    ),
                    {"d": _DEVICE_ID},
                )
            ]
    finally:
        engine.dispose()


class TestDeltaPushOnTheIdCursor:
    def test_twoMilestonesInOneSecond_batchOfOne_bothLand(
        self, piDbPath: str, appOpener: _AppOpener, serverDbPath: str,
    ) -> None:
        """
        Given: two milestones written in the same second
        When: pushed with a batch limit of 1, then pushed again
        Then: both rows reach the server -- the id cursor loses none at the
              batch boundary, where a timestamp cursor could
        """
        _writeMilestones(piDbPath, [
            (MILESTONES[0], "2026-10-13T12:00:00Z", 0.0),
            (MILESTONES[1], "2026-10-13T12:00:00Z", 0.0),
        ])
        client = _client(piDbPath, appOpener, batchSize=1)

        first = client.pushDelta(_TABLE)
        second = client.pushDelta(_TABLE)
        third = client.pushDelta(_TABLE)

        assert (first.status, first.rowsPushed) == (PushStatus.OK, 1)
        assert (second.status, second.rowsPushed) == (PushStatus.OK, 1)
        assert third.status is PushStatus.EMPTY
        assert _serverRows(serverDbPath) == [
            (1, _BOOT_ID, MILESTONES[0], 0.0),
            (2, _BOOT_ID, MILESTONES[1], 0.0),
        ]

    def test_aWholeLadder_landsOnce_andTheSecondPushIsEmpty(
        self, piDbPath: str, appOpener: _AppOpener, serverDbPath: str,
    ) -> None:
        """
        Given: the full 7-rung ladder for one boot
        When: pushed, then pushed again with nothing new
        Then: 7 server rows carrying the Pi ids, and the second push is EMPTY
        """
        assert len(MILESTONES) == 7
        ladder = [
            (milestone, f"2026-10-13T12:00:{index:02d}Z", float(index))
            for index, milestone in enumerate(MILESTONES)
        ]
        _writeMilestones(piDbPath, ladder)
        client = _client(piDbPath, appOpener, batchSize=500)

        first = client.pushDelta(_TABLE)
        second = client.pushDelta(_TABLE)

        assert (first.status, first.rowsPushed) == (PushStatus.OK, 7)
        assert second.status is PushStatus.EMPTY
        assert _serverRows(serverDbPath) == [
            (index + 1, _BOOT_ID, milestone, float(index))
            for index, milestone in enumerate(MILESTONES)
        ]
