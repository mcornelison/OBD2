################################################################################
# File Name: test_sync.py
# Purpose/Description: Tests for the POST /api/v1/sync delta sync endpoint
#                      (US-CMP-004). Covers Pydantic request validation, the
#                      sync core (upsert + drive detection + sync_history), and
#                      route-level auth / payload-size / response shape.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-CMP-004 — delta sync
# ================================================================================
################################################################################

"""
Tests for ``src/server/api/sync.py`` — the ``POST /api/v1/sync`` endpoint.

Split into four concerns:

1. **Pydantic request validation** — shape, required fields, accepted tables.
2. **Sync core** — dialect-aware upsert + drive-data detection against a sync
   SQLite engine (mirrors test_load_data.py). Validates idempotency, counts,
   and that ``source_device`` / ``sync_batch_id`` are stamped on every row.
3. **Route behaviour** — auth, 413 on oversize body, response envelope.
4. **sync_history** — row created with correct status / counts / tables list.

Route-level tests that need a real AsyncEngine use ``aiosqlite`` when
installed; when it's not, they skip cleanly (same pattern test_db_models.py
uses for aiomysql).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import (  # noqa: E402
    Base,
    ConnectionLog,
    RealtimeData,
    SyncHistory,
)

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def syncEngine():
    """Sync SQLAlchemy engine against a temp SQLite file with server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _buildValidRequest(
    deviceId: str = "test-device",
    batchId: str = "batch-001",
) -> dict:
    """Minimal valid sync request with one row in each of two tables."""
    return {
        "deviceId": deviceId,
        "batchId": batchId,
        "tables": {
            "realtime_data": {
                "lastSyncedId": 0,
                "rows": [
                    {
                        "id": 1,
                        "timestamp": "2026-04-16T08:00:00",
                        "parameter_name": "RPM",
                        "value": 2500.0,
                        "unit": "rpm",
                        "profile_id": "daily",
                    },
                ],
            },
            "connection_log": {
                "lastSyncedId": 0,
                "rows": [
                    {
                        "id": 1,
                        "timestamp": "2026-04-16T08:00:00",
                        "event_type": "drive_start",
                        "success": 1,
                    },
                    {
                        "id": 2,
                        "timestamp": "2026-04-16T08:05:00",
                        "event_type": "drive_end",
                        "success": 1,
                    },
                ],
            },
        },
    }


# ==============================================================================
# 1) Pydantic request validation
# ==============================================================================


class TestSyncRequestValidation:
    """The request model rejects malformed payloads before any DB work."""

    def test_validPayload_parsesWithoutError(self):
        from src.server.api.sync import SyncRequest

        model = SyncRequest.model_validate(_buildValidRequest())
        assert model.deviceId == "test-device"
        assert model.batchId == "batch-001"
        assert "realtime_data" in model.tables

    def test_missingDeviceId_rejected(self):
        from pydantic import ValidationError

        from src.server.api.sync import SyncRequest

        payload = _buildValidRequest()
        del payload["deviceId"]
        with pytest.raises(ValidationError):
            SyncRequest.model_validate(payload)

    def test_emptyDeviceId_rejected(self):
        from pydantic import ValidationError

        from src.server.api.sync import SyncRequest

        payload = _buildValidRequest(deviceId="")
        with pytest.raises(ValidationError):
            SyncRequest.model_validate(payload)

    def test_missingBatchId_rejected(self):
        from pydantic import ValidationError

        from src.server.api.sync import SyncRequest

        payload = _buildValidRequest()
        del payload["batchId"]
        with pytest.raises(ValidationError):
            SyncRequest.model_validate(payload)

    def test_missingTables_rejected(self):
        from pydantic import ValidationError

        from src.server.api.sync import SyncRequest

        payload = _buildValidRequest()
        del payload["tables"]
        with pytest.raises(ValidationError):
            SyncRequest.model_validate(payload)

    def test_unknownTableName_rejected(self):
        from pydantic import ValidationError

        from src.server.api.sync import SyncRequest

        payload = _buildValidRequest()
        payload["tables"]["not_a_real_table"] = {"lastSyncedId": 0, "rows": []}
        with pytest.raises(ValidationError):
            SyncRequest.model_validate(payload)

    def test_allEightAcceptedTables(self):
        """Spec §2.2: accepted names are exactly the 8 synced tables."""
        from src.server.api.sync import ACCEPTED_TABLES

        assert ACCEPTED_TABLES == {
            "realtime_data",
            "statistics",
            "profiles",
            "vehicle_info",
            "ai_recommendations",
            "connection_log",
            "alert_log",
            "calibration_sessions",
        }


# ==============================================================================
# 2) driveDataReceived helper
# ==============================================================================


class TestDriveDataReceived:
    """``driveDataReceived`` is true iff connection_log has a drive_end row."""

    def test_connectionLogWithDriveEnd_returnsTrue(self):
        from src.server.api.sync import detectDriveDataReceived

        tables = {
            "connection_log": {
                "lastSyncedId": 0,
                "rows": [
                    {"id": 1, "event_type": "drive_start"},
                    {"id": 2, "event_type": "drive_end"},
                ],
            },
        }
        assert detectDriveDataReceived(tables) is True

    def test_connectionLogWithoutDriveEnd_returnsFalse(self):
        from src.server.api.sync import detectDriveDataReceived

        tables = {
            "connection_log": {
                "lastSyncedId": 0,
                "rows": [
                    {"id": 1, "event_type": "drive_start"},
                    {"id": 2, "event_type": "connect"},
                ],
            },
        }
        assert detectDriveDataReceived(tables) is False

    def test_noConnectionLog_returnsFalse(self):
        from src.server.api.sync import detectDriveDataReceived

        tables = {
            "realtime_data": {"lastSyncedId": 0, "rows": [{"id": 1}]},
        }
        assert detectDriveDataReceived(tables) is False

    def test_emptyConnectionLog_returnsFalse(self):
        from src.server.api.sync import detectDriveDataReceived

        tables = {"connection_log": {"lastSyncedId": 0, "rows": []}}
        assert detectDriveDataReceived(tables) is False


# ==============================================================================
# 3) Sync core — upsert + sync_history (sync Session against SQLite)
# ==============================================================================


class TestSyncCore:
    """
    The sync core is a sync function taking a Session so it can be unit tested
    without an async engine. In production the endpoint calls it via
    ``AsyncSession.run_sync(...)``.
    """

    def test_freshPayload_rowsInserted_countsReturned(self, syncEngine):
        from src.server.api.sync import runSyncUpsert

        with Session(syncEngine) as session:
            result = runSyncUpsert(
                session=session,
                deviceId="test-device",
                batchId="batch-001",
                tables=_buildValidRequest()["tables"],
                syncHistoryId=1,
            )
            session.commit()

        assert result["realtime_data"]["inserted"] == 1
        assert result["realtime_data"]["updated"] == 0
        assert result["connection_log"]["inserted"] == 2
        assert result["connection_log"]["updated"] == 0

    def test_rowsStampedWithSourceDeviceAndBatch(self, syncEngine):
        from src.server.api.sync import runSyncUpsert

        with Session(syncEngine) as session:
            runSyncUpsert(
                session=session,
                deviceId="my-pi",
                batchId="batch-xyz",
                tables=_buildValidRequest()["tables"],
                syncHistoryId=42,
            )
            session.commit()

        with Session(syncEngine) as session:
            rtRow = session.execute(select(RealtimeData)).scalar_one()
            assert rtRow.source_device == "my-pi"
            assert rtRow.source_id == 1
            assert rtRow.sync_batch_id == 42
            assert rtRow.synced_at is not None

    def test_sourceIdMapsFromPiIdField(self, syncEngine):
        """Spec §2.2: ``Pi id field maps to source_id``."""
        from src.server.api.sync import runSyncUpsert

        tables = {
            "realtime_data": {
                "lastSyncedId": 0,
                "rows": [
                    {
                        "id": 4242,
                        "timestamp": "2026-04-16T08:00:00",
                        "parameter_name": "RPM",
                        "value": 1000.0,
                    },
                ],
            },
        }
        with Session(syncEngine) as session:
            runSyncUpsert(
                session=session,
                deviceId="test-device",
                batchId="batch-1",
                tables=tables,
                syncHistoryId=1,
            )
            session.commit()

        with Session(syncEngine) as session:
            row = session.execute(select(RealtimeData)).scalar_one()
            assert row.source_id == 4242

    def test_idempotentReSync_updatesInsteadOfDuplicating(self, syncEngine):
        """Syncing the same payload twice must yield the same DB state."""
        from src.server.api.sync import runSyncUpsert

        tables = _buildValidRequest()["tables"]

        with Session(syncEngine) as session:
            runSyncUpsert(
                session=session,
                deviceId="test-device",
                batchId="batch-first",
                tables=tables,
                syncHistoryId=1,
            )
            session.commit()

        with Session(syncEngine) as session:
            result = runSyncUpsert(
                session=session,
                deviceId="test-device",
                batchId="batch-second",
                tables=tables,
                syncHistoryId=2,
            )
            session.commit()

        # Second call: everything is an update, no inserts
        assert result["realtime_data"]["inserted"] == 0
        assert result["realtime_data"]["updated"] == 1
        assert result["connection_log"]["inserted"] == 0
        assert result["connection_log"]["updated"] == 2

        with Session(syncEngine) as session:
            rtCount = session.execute(select(RealtimeData)).all()
            clCount = session.execute(select(ConnectionLog)).all()
            assert len(rtCount) == 1
            assert len(clCount) == 2

    def test_differentDeviceSameSourceId_insertsBoth(self, syncEngine):
        """Upsert key is ``(source_device, source_id)`` — different device = new row."""
        from src.server.api.sync import runSyncUpsert

        tables = _buildValidRequest()["tables"]

        with Session(syncEngine) as session:
            runSyncUpsert(
                session=session,
                deviceId="pi-a",
                batchId="batch-1",
                tables=tables,
                syncHistoryId=1,
            )
            session.commit()

        with Session(syncEngine) as session:
            runSyncUpsert(
                session=session,
                deviceId="pi-b",
                batchId="batch-2",
                tables=tables,
                syncHistoryId=2,
            )
            session.commit()

        with Session(syncEngine) as session:
            rows = session.execute(select(RealtimeData)).scalars().all()
            assert len(rows) == 2
            assert {r.source_device for r in rows} == {"pi-a", "pi-b"}

    def test_emptyTables_returnsZeroCounts(self, syncEngine):
        from src.server.api.sync import runSyncUpsert

        with Session(syncEngine) as session:
            result = runSyncUpsert(
                session=session,
                deviceId="test-device",
                batchId="batch-1",
                tables={},
                syncHistoryId=1,
            )
            session.commit()

        assert result == {}


# ==============================================================================
# 4) Route behaviour — auth, payload size, response envelope
# ==============================================================================


def _makeSettings(apiKey: str = "valid-key", maxMb: int = 10):
    from src.server.config import Settings

    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=apiKey,
        MAX_SYNC_PAYLOAD_MB=maxMb,
    )


def _buildAppForRouteTests(apiKey: str = "valid-key", maxMb: int = 10):
    """Build a bare FastAPI app with the sync router registered."""
    from src.server.api.app import createApp

    settings = _makeSettings(apiKey=apiKey, maxMb=maxMb)
    app = createApp(settings=settings)
    app.state.engine = None  # no engine for auth / size tests
    return app


class TestSyncAuth:
    """Auth is enforced by the shared ``requireApiKey`` dependency (US-CMP-002)."""

    def test_missingApiKey_returns401(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post("/api/v1/sync", json=_buildValidRequest())

        assert response.status_code == 401

    def test_invalidApiKey_returns401(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/sync",
                json=_buildValidRequest(),
                headers={"X-API-Key": "wrong"},
            )

        assert response.status_code == 401


class TestSyncPayloadSize:
    """Oversize payloads rejected with 413 before body parsing / DB work."""

    def test_contentLengthOverCap_returns413(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests(maxMb=1)  # cap at 1 MB
        oversizeBody = b"x" * (2 * 1024 * 1024)  # 2 MB of junk
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/sync",
                content=oversizeBody,
                headers={
                    "X-API-Key": "valid-key",
                    "Content-Type": "application/json",
                },
            )

        assert response.status_code == 413


class TestSyncInvalidBody:
    """Malformed JSON body → 422 (Pydantic validation)."""

    def test_malformedBody_returns422(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/sync",
                json={"tables": {}},  # missing deviceId, batchId
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 422

    def test_unknownTableName_returns422(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        payload = _buildValidRequest()
        payload["tables"]["not_a_table"] = {"lastSyncedId": 0, "rows": []}
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/sync",
                json=payload,
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 422


# ==============================================================================
# 5) Full route + DB integration — requires aiosqlite
# ==============================================================================


try:
    import aiosqlite as _aiosqlite  # noqa: F401
    _HAS_AIOSQLITE = True
except ImportError:
    _HAS_AIOSQLITE = False


_skipNoAsyncDb = pytest.mark.skipif(
    not _HAS_AIOSQLITE,
    reason="aiosqlite not installed — skipping async DB route tests",
)


if _HAS_AIOSQLITE:
    import pytest_asyncio  # type: ignore[import-not-found]

    _asyncFixture = pytest_asyncio.fixture
else:
    _asyncFixture = pytest.fixture


@_asyncFixture
async def asyncAppAndEngine():
    """
    Build an app with a real AsyncEngine backed by aiosqlite and the server
    schema pre-created. Used for end-to-end route tests that assert on DB
    side effects (sync_history rows, upserted data, response shape).
    """
    import tempfile as _tempfile

    from sqlalchemy.ext.asyncio import create_async_engine

    from src.server.api.app import createApp

    tmp = _tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    # Sync engine once to create_all, then dispose — async aiosqlite is used
    # by the app itself for all subsequent operations.
    syncEng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(syncEng)
    syncEng.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    settings = _makeSettings(apiKey="valid-key", maxMb=10)
    app = createApp(settings=settings)
    app.state.engine = engine

    try:
        yield app, engine
    finally:
        await engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)


@_skipNoAsyncDb
class TestSyncHappyPath:
    """Full request → 200, response envelope, DB side-effects."""

    @pytest.mark.asyncio
    async def test_validRequest_returns200_andExpectedShape(
        self, asyncAppAndEngine,
    ):
        import httpx

        app, _engine = asyncAppAndEngine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/sync",
                json=_buildValidRequest(),
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["batchId"] == "batch-001"
        assert "tablesProcessed" in body
        assert body["tablesProcessed"]["realtime_data"]["inserted"] == 1
        assert body["driveDataReceived"] is True
        assert body["autoAnalysisTriggered"] is False
        assert "syncedAt" in body

    @pytest.mark.asyncio
    async def test_validRequest_writesSyncHistoryRow(self, asyncAppAndEngine):
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        app, engine = asyncAppAndEngine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/v1/sync",
                json=_buildValidRequest(),
                headers={"X-API-Key": "valid-key"},
            )

        async with AsyncSession(engine) as session:
            result = await session.execute(select(SyncHistory))
            rows = result.scalars().all()

        assert len(rows) == 1
        hist = rows[0]
        assert hist.device_id == "test-device"
        assert hist.status == "completed"
        assert hist.rows_synced == 3  # 1 realtime + 2 connection_log
        # tables_synced stored as JSON string of per-table counts
        assert hist.tables_synced is not None
        parsed = json.loads(hist.tables_synced)
        assert "realtime_data" in parsed
        assert "connection_log" in parsed
        assert hist.completed_at is not None

    @pytest.mark.asyncio
    async def test_validRequest_writesUpsertedRows(self, asyncAppAndEngine):
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        app, engine = asyncAppAndEngine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/v1/sync",
                json=_buildValidRequest(deviceId="pi-7"),
                headers={"X-API-Key": "valid-key"},
            )

        async with AsyncSession(engine) as session:
            rt = (await session.execute(select(RealtimeData))).scalars().all()
            cl = (await session.execute(select(ConnectionLog))).scalars().all()

        assert len(rt) == 1
        assert rt[0].source_device == "pi-7"
        assert rt[0].source_id == 1
        assert rt[0].parameter_name == "RPM"
        assert len(cl) == 2
        assert {r.event_type for r in cl} == {"drive_start", "drive_end"}


@_skipNoAsyncDb
class TestSyncIdempotence:
    """Invariant: syncing the same batch twice yields the same DB state."""

    @pytest.mark.asyncio
    async def test_doubleSync_sameBatchId_sameDbState(self, asyncAppAndEngine):
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        app, engine = asyncAppAndEngine
        payload = _buildValidRequest()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            r1 = await client.post(
                "/api/v1/sync",
                json=payload,
                headers={"X-API-Key": "valid-key"},
            )
            r2 = await client.post(
                "/api/v1/sync",
                json=payload,
                headers={"X-API-Key": "valid-key"},
            )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.json()["tablesProcessed"]["realtime_data"]["updated"] == 1
        assert r2.json()["tablesProcessed"]["realtime_data"]["inserted"] == 0

        async with AsyncSession(engine) as session:
            rt = (await session.execute(select(RealtimeData))).scalars().all()
            cl = (await session.execute(select(ConnectionLog))).scalars().all()

        assert len(rt) == 1
        assert len(cl) == 2


@_skipNoAsyncDb
class TestSyncDriveDataReceived:
    """Flag is true iff payload includes ``event_type=drive_end`` rows."""

    @pytest.mark.asyncio
    async def test_payloadWithDriveEnd_flagsTrue(self, asyncAppAndEngine):
        import httpx

        app, _engine = asyncAppAndEngine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/sync",
                json=_buildValidRequest(),
                headers={"X-API-Key": "valid-key"},
            )

        assert response.json()["driveDataReceived"] is True

    @pytest.mark.asyncio
    async def test_payloadWithoutDriveEnd_flagsFalse(self, asyncAppAndEngine):
        import httpx

        app, _engine = asyncAppAndEngine
        payload = _buildValidRequest()
        # Remove connection_log entirely
        del payload["tables"]["connection_log"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/sync",
                json=payload,
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        assert response.json()["driveDataReceived"] is False


@_skipNoAsyncDb
class TestSyncFailure:
    """DB error during upsert → 500 and sync_history.status = 'failed'."""

    @pytest.mark.asyncio
    async def test_upsertError_returns500_andMarksHistoryFailed(
        self, asyncAppAndEngine,
    ):
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.api import sync as syncMod

        app, engine = asyncAppAndEngine

        def _raise(*_a, **_kw):
            raise RuntimeError("boom")

        with patch.object(syncMod, "runSyncUpsert", side_effect=_raise):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/sync",
                    json=_buildValidRequest(),
                    headers={"X-API-Key": "valid-key"},
                )

        assert response.status_code == 500

        async with AsyncSession(engine) as session:
            result = await session.execute(select(SyncHistory))
            rows = result.scalars().all()

        assert len(rows) == 1
        assert rows[0].status == "failed"
        # No upserted data — rollback should have dropped everything
        async with AsyncSession(engine) as session:
            rt = (await session.execute(select(RealtimeData))).scalars().all()
            cl = (await session.execute(select(ConnectionLog))).scalars().all()
        assert rt == []
        assert cl == []
