################################################################################
# File Name: test_sync_status.py
# Purpose/Description: US-795(a) -- the server SAYS what it knows about each
#                      car's queue: a reader service over sync_history, a CLI
#                      and GET /api/v1/sync/status, all built on the one
#                      currency assessor (no second reader).
# Author: Atlas (Architect) -- US-795(a), CIO-directed build
# Creation Date: 2026-10-06
################################################################################
"""The server-side status of each car's sync queue (US-795(a)).

CIO rulings 2026-10-06: the server reports EVERYTHING unsynced as a total plus
a drive/sensor split, states the age of the last contact, never gives an
online/offline verdict, and shows the stall alarm. The words come from
``src/server/api/currency.renderCurrency``; this module only reads rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import Base, SyncHistory  # noqa: E402
from src.server.services import sync_status  # noqa: E402

_NOW = datetime(2026, 10, 6, 23, 35, 0, tzinfo=UTC)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'server.db'}")
    Base.metadata.create_all(eng)
    return eng


def _add(engine, device: str, at: datetime, rows: int | None, *,
         complete: bool | None = True, drive: int | None = None,
         sensor: int | None = None, status: str = "completed") -> None:
    with Session(engine) as session:
        session.add(SyncHistory(
            device_id=device, status=status, started_at=_naive(at),
            completed_at=_naive(at), residual_rows=rows,
            residual_complete=complete, residual_drive_rows=drive,
            residual_sensor_rows=sensor,
        ))
        session.commit()


class TestTheReader:

    def test_theNewestCompletedContactIsTheAnswer(self, engine) -> None:
        _add(engine, "car-a", _NOW - timedelta(minutes=10), 900, drive=100, sensor=800)
        _add(engine, "car-a", _NOW - timedelta(minutes=4), 300, drive=0, sensor=300)
        _add(engine, "car-a", _NOW - timedelta(minutes=1), None, status="failed")

        with Session(engine) as session:
            (status,) = sync_status.readSyncStatus(session, now=_NOW)

        assert status.deviceId == "car-a"
        assert status.lastContact == "2026-10-06T23:31:00Z"
        assert status.ageSeconds == 240
        assert (status.outstandingRows, status.driveRows, status.sensorRows) == (300, 0, 300)
        assert status.statement == (
            "last contact 2026-10-06T23:31:00Z (4 min ago): 300 queued (exact) "
            "- drive 0, sensor 300; nothing known since"
        )

    def test_everyCarThatHasReportedIsListed_noHostIsHardcoded(self, engine) -> None:
        _add(engine, "car-b", _NOW, 0)
        _add(engine, "car-a", _NOW, 5)

        with Session(engine) as session:
            devices = [s.deviceId for s in sync_status.readSyncStatus(session, now=_NOW)]

        assert devices == ["car-a", "car-b"]

    def test_oneDeviceCanBeAskedFor(self, engine) -> None:
        _add(engine, "car-a", _NOW, 5)
        _add(engine, "car-b", _NOW, 0)

        with Session(engine) as session:
            statuses = sync_status.readSyncStatus(session, now=_NOW, deviceId="car-b")

        assert [s.deviceId for s in statuses] == ["car-b"]

    def test_aDeviceNeverHeardFrom_isStatedAsSuch(self, engine) -> None:
        with Session(engine) as session:
            (status,) = sync_status.readSyncStatus(session, now=_NOW, deviceId="car-z")

        assert status.state == "unknown"
        assert status.lastContact is None
        assert status.statement == "no contact recorded; nothing known"

    def test_aContactWithoutAResidual_isUnknownNotZero(self, engine) -> None:
        _add(engine, "car-a", _NOW, None, complete=None)

        with Session(engine) as session:
            (status,) = sync_status.readSyncStatus(session, now=_NOW)

        assert status.state == "unknown"
        assert status.outstandingRows is None

    def test_theStallAlarmReachesTheStatus(self, engine) -> None:
        for minutes in (3, 2, 1):
            _add(engine, "car-a", _NOW - timedelta(minutes=minutes), 400)

        with Session(engine) as session:
            (status,) = sync_status.readSyncStatus(session, now=_NOW)

        assert status.fault is not None
        assert "| ALARM:" in status.statement

    def test_toDict_isTheApiShape(self, engine) -> None:
        _add(engine, "car-a", _NOW, 0, drive=0, sensor=0)

        with Session(engine) as session:
            (status,) = sync_status.readSyncStatus(session, now=_NOW)

        assert status.toDict() == {
            "deviceId": "car-a", "state": "current",
            "lastContact": "2026-10-06T23:35:00Z", "ageSeconds": 0,
            "outstandingRows": 0, "exact": True, "driveRows": 0, "sensorRows": 0,
            "fault": None,
            "statement": (
                "last contact 2026-10-06T23:35:00Z (under 1 min ago): 0 queued (exact) "
                "- drive 0, sensor 0; nothing known since"
            ),
        }


class TestTheCli:

    def test_printsOneLinePerCar(self, engine, monkeypatch, capsys) -> None:
        from src.server.cli import sync_status as cli

        _add(engine, "car-a", datetime.now(UTC) - timedelta(minutes=2), 12, drive=2, sensor=10)
        monkeypatch.setattr(cli, "resolveSyncDatabaseUrl", lambda: str(engine.url))

        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert out.startswith("car-a: last contact ")
        assert "12 queued (exact) - drive 2, sensor 10; nothing known since" in out

    def test_noContactsAtAll_saysSo(self, engine, monkeypatch, capsys) -> None:
        from src.server.cli import sync_status as cli

        monkeypatch.setattr(cli, "resolveSyncDatabaseUrl", lambda: str(engine.url))

        assert cli.main([]) == 0
        assert "no sync contact recorded for any device" in capsys.readouterr().out


class TestTheApi:

    def _app(self):
        from src.server.api.app import createApp
        from src.server.config import Settings

        app = createApp(settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:", API_KEY="valid-key",
        ))
        app.state.engine = object()  # the reader is replaced below; never touched
        return app

    def test_returnsTheStatusList(self, monkeypatch) -> None:
        from fastapi.testclient import TestClient

        from src.server.api import sync as sync_module

        canned = sync_status.deviceSyncStatus(
            "car-a",
            [sync_status.ContactRecord(
                contactedAt=_NOW, residualRows=0, residualComplete=True,
                residualDriveRows=0, residualSensorRows=0,
            )],
            now=_NOW,
        )
        seen: dict = {}

        async def _fake(engine, *, now, deviceId):
            seen["deviceId"] = deviceId
            return [canned]

        monkeypatch.setattr(sync_module, "readSyncStatusAsync", _fake)
        with TestClient(self._app()) as client:
            response = client.get(
                "/api/v1/sync/status", params={"deviceId": "car-a"},
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        assert response.json() == [canned.toDict()]
        assert seen["deviceId"] == "car-a"

    def test_requiresTheApiKey(self) -> None:
        from fastapi.testclient import TestClient

        with TestClient(self._app()) as client:
            assert client.get("/api/v1/sync/status").status_code == 401


try:
    import aiosqlite as _aiosqlite  # noqa: F401

    _HAS_AIOSQLITE = True
except ImportError:  # pragma: no cover
    _HAS_AIOSQLITE = False


@pytest.mark.skipif(not _HAS_AIOSQLITE, reason="aiosqlite not installed")
class TestTheWholeLoopThroughTheRealApp:
    """WIRING, end to end (CIO 2026-10-06: "make sure ... it is wired up
    correctly"). The real createApp and both real routes over a real async
    database -- nothing patched: a Pi push carrying a residual is ingested,
    stored, read back by the status route and stated."""

    def test_aPushWithAResidual_isStatedByTheStatusRoute(self, tmp_path) -> None:
        from fastapi.testclient import TestClient
        from sqlalchemy.ext.asyncio import create_async_engine

        from src.server.api.app import createApp
        from src.server.config import Settings

        dbFile = tmp_path / "loop.db"
        syncEngine = create_engine(f"sqlite:///{dbFile}")
        Base.metadata.create_all(syncEngine)
        syncEngine.dispose()

        app = createApp(settings=Settings(
            DATABASE_URL=f"sqlite+aiosqlite:///{dbFile}", API_KEY="valid-key",
        ))
        app.state.engine = create_async_engine(f"sqlite+aiosqlite:///{dbFile}")
        headers = {"X-API-Key": "valid-key"}
        push = {
            "deviceId": "car-a",
            "batchId": "car-a-b1",
            "tables": {"connection_log": {"lastSyncedId": 0, "rows": [{
                "id": 1, "timestamp": "2026-10-06T23:00:00Z", "event_type": "connect_attempt",
                "mac_address": "x", "success": 1, "error_message": None,
                "retry_count": 0, "data_source": "real", "drive_id": None,
            }]}},
            "residual": {"outstandingRows": 1200, "complete": True,
                         "groups": {"drive": 200, "sensor": 1000}},
        }

        with TestClient(app) as client:
            posted = client.post("/api/v1/sync", json=push, headers=headers)
            assert posted.status_code == 200, posted.text
            got = client.get("/api/v1/sync/status", headers=headers)

        assert got.status_code == 200, got.text
        (status,) = got.json()
        assert status["deviceId"] == "car-a"
        assert (status["outstandingRows"], status["driveRows"], status["sensorRows"]) == (1200, 200, 1000)
        assert status["exact"] is True
        assert "1200 queued (exact) - drive 200, sensor 1000; nothing known since" in status["statement"]
