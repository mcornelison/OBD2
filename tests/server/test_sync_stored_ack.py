################################################################################
# File Name: test_sync_stored_ack.py
# Purpose/Description: Tests for the POST /api/v1/sync post-commit stored ack
#                      (US-776-h): per table storedCount + maxStoredSourceId,
#                      read back AFTER the commit over the batch's source_ids.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-11    | Rex (US-776-h)| Initial tests -- stored ack on the push reply
# ================================================================================
################################################################################

"""
Tests for the stored ack on the ``POST /api/v1/sync`` response (US-776-h).

``tablesProcessed`` is assembled from a select taken BEFORE the write and its
``errors`` field is always 0, so it cannot tell "received" from "stored".  The
``stored`` block is read back after the commit, scoped to the batch's
source_ids for the pushing device, so a row that did not land is visible as a
``storedCount`` below the rows sent.

Every route test runs the REAL app on a SQLite test database (aiosqlite), the
same harness ``test_sync.py`` uses.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("aiosqlite")
pytest_asyncio = pytest.importorskip("pytest_asyncio")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import Base  # noqa: E402

_API_KEY = "valid-key"


# ==============================================================================
# Fixtures + helpers
# ==============================================================================


@pytest_asyncio.fixture
async def appAndEngine():
    """Real app + AsyncEngine on a temp SQLite file holding the server schema."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.server.api.app import createApp
    from src.server.config import Settings

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    syncEng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(syncEng)
    syncEng.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    app = createApp(settings=Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=_API_KEY,
        MAX_SYNC_PAYLOAD_MB=10,
    ))
    app.state.engine = engine
    try:
        yield app, engine
    finally:
        await engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture
def syncEngine():
    """Sync SQLAlchemy engine on a temp SQLite file holding the server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _realtimeRows(sourceIds: list[int]) -> list[dict]:
    return [
        {
            "id": sid,
            "timestamp": "2026-10-11T13:14:00",
            "parameter_name": "RPM",
            "value": 800.0 + sid,
            "unit": "rpm",
        }
        for sid in sourceIds
    ]


def _connectionRows(sourceIds: list[int]) -> list[dict]:
    return [
        {
            "id": sid,
            "timestamp": "2026-10-11T13:14:00",
            "event_type": "connect_attempt",
            "success": 1,
        }
        for sid in sourceIds
    ]


def _payload(deviceId: str, tables: dict[str, list[dict]]) -> dict:
    return {
        "deviceId": deviceId,
        "batchId": "batch-776h",
        "tables": {
            name: {"lastSyncedId": 0, "rows": rows} for name, rows in tables.items()
        },
    }


async def _post(app, payload: dict):
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        return await client.post(
            "/api/v1/sync", json=payload, headers={"X-API-Key": _API_KEY},
        )


# ==============================================================================
# Route: the stored ack on a real push
# ==============================================================================


class TestStoredAckOnPush:
    """A push of N rows answers with what the server holds after the commit."""

    @pytest.mark.asyncio
    async def test_pushOfNRows_storedCountN_maxIsLargestSent(self, appAndEngine):
        """
        Given: a delta push of 4 realtime_data rows, ids not in send order
        When: the server commits the batch
        Then: stored.realtime_data is storedCount 4, maxStoredSourceId 4111046
        """
        app, _engine = appAndEngine
        sent = [4111043, 4111046, 4111044, 4111045]

        response = await _post(app, _payload("pi-1", {"realtime_data": _realtimeRows(sent)}))

        assert response.status_code == 200
        stored = response.json()["stored"]
        assert stored["realtime_data"] == {
            "storedCount": 4,
            "maxStoredSourceId": 4111046,
        }

    @pytest.mark.asyncio
    async def test_pushOfTwoTables_ackPerTable(self, appAndEngine):
        """
        Given: one push carrying realtime_data (3 rows) and connection_log (2 rows)
        When: the batch commits
        Then: each table carries its own count and maximum
        """
        app, _engine = appAndEngine

        response = await _post(app, _payload("pi-1", {
            "realtime_data": _realtimeRows([10, 11, 12]),
            "connection_log": _connectionRows([7, 9]),
        }))

        stored = response.json()["stored"]
        assert stored["realtime_data"] == {"storedCount": 3, "maxStoredSourceId": 12}
        assert stored["connection_log"] == {"storedCount": 2, "maxStoredSourceId": 9}

    @pytest.mark.asyncio
    async def test_existingResponseKeys_keepTheirMeaning(self, appAndEngine):
        """
        Given: a push of 2 new realtime rows (a Pi on the old build reads these keys)
        When: the server answers
        Then: status, batchId, tablesProcessed{inserted,updated,errors}, syncedAt,
              driveDataReceived and autoAnalysisTriggered are present as before
        """
        app, _engine = appAndEngine

        response = await _post(app, _payload("pi-1", {"realtime_data": _realtimeRows([1, 2])}))

        body = response.json()
        assert body["status"] == "ok"
        assert body["batchId"] == "batch-776h"
        assert body["tablesProcessed"]["realtime_data"] == {
            "inserted": 2, "updated": 0, "errors": 0,
        }
        assert "syncedAt" in body
        assert body["driveDataReceived"] is False
        assert body["autoAnalysisTriggered"] is False

    @pytest.mark.asyncio
    async def test_rePushOfStoredRows_stillCountsThem(self, appAndEngine):
        """
        Given: a batch already stored once
        When: the Pi pushes the same rows again (an update, not an insert)
        Then: storedCount still equals the rows sent -- stored, not newly inserted
        """
        app, _engine = appAndEngine
        payload = _payload("pi-1", {"realtime_data": _realtimeRows([5, 6, 7])})
        await _post(app, payload)

        response = await _post(app, payload)

        body = response.json()
        assert body["tablesProcessed"]["realtime_data"]["updated"] == 3
        assert body["stored"]["realtime_data"] == {"storedCount": 3, "maxStoredSourceId": 7}

    @pytest.mark.asyncio
    async def test_emptyTable_storedCountZero_maxNone(self, appAndEngine):
        """
        Given: a push whose connection_log entry carries no rows
        When: the server answers
        Then: that table reads storedCount 0 and maxStoredSourceId None
        """
        app, _engine = appAndEngine

        response = await _post(app, _payload("pi-1", {
            "realtime_data": _realtimeRows([1]),
            "connection_log": [],
        }))

        assert response.json()["stored"]["connection_log"] == {
            "storedCount": 0, "maxStoredSourceId": None,
        }


# ==============================================================================
# Route: rows that did not land show as a short count
# ==============================================================================


class TestStoredAckShortStore:
    """The ack measures the database, not the request."""

    @pytest.mark.asyncio
    async def test_rowNotStored_storedCountBelowN(self, appAndEngine, monkeypatch):
        """
        Given: a push of 4 rows where the write is forced to drop the last row
        When: the batch commits
        Then: storedCount is 3 (< 4 sent) and the max is the largest STORED id,
              while tablesProcessed (pre-write) still claims 4 inserted
        """
        import src.server.api.sync as syncModule

        realUpsert = syncModule._upsertBatch

        def _dropLastRow(session, model, rows):
            realUpsert(session, model, rows[:-1])

        monkeypatch.setattr(syncModule, "_upsertBatch", _dropLastRow)
        app, _engine = appAndEngine

        response = await _post(app, _payload("pi-1", {
            "realtime_data": _realtimeRows([100, 101, 102, 103]),
        }))

        body = response.json()
        assert body["tablesProcessed"]["realtime_data"]["inserted"] == 4
        assert body["stored"]["realtime_data"] == {"storedCount": 3, "maxStoredSourceId": 102}

    @pytest.mark.asyncio
    async def test_otherDevicesRows_neverCountAsStored(self, appAndEngine, monkeypatch):
        """
        Given: device pi-A already holds source_ids 1-3 on the server
        When: device pi-B pushes source_ids 1-3 and none of its rows are written
        Then: pi-B's ack reads storedCount 0 -- pi-A's rows are not pi-B's
        """
        import src.server.api.sync as syncModule

        app, _engine = appAndEngine
        await _post(app, _payload("pi-A", {"realtime_data": _realtimeRows([1, 2, 3])}))
        monkeypatch.setattr(syncModule, "_upsertBatch", lambda session, model, rows: None)

        response = await _post(app, _payload("pi-B", {"realtime_data": _realtimeRows([1, 2, 3])}))

        assert response.json()["stored"]["realtime_data"] == {
            "storedCount": 0, "maxStoredSourceId": None,
        }


# ==============================================================================
# Core: the readback and the batch's source_ids
# ==============================================================================


class TestReadStoredAck:
    """readStoredAck counts stored rows scoped to (device, batch source_ids)."""

    def test_readStoredAck_countsOnlyTheBatchIds(self, syncEngine):
        """
        Given: pi-1 holds source_ids 1-5
        When: the readback is asked about ids [2, 4, 9]
        Then: storedCount 2 (9 is absent), maxStoredSourceId 4
        """
        from src.server.api.sync import readStoredAck, runSyncUpsert

        with Session(syncEngine) as session:
            runSyncUpsert(
                session, deviceId="pi-1", batchId="b",
                tables={"realtime_data": {"rows": _realtimeRows([1, 2, 3, 4, 5])}},
                syncHistoryId=1,
            )
            session.commit()

        with Session(syncEngine) as session:
            ack = readStoredAck(session, "pi-1", {"realtime_data": [2, 4, 9]})

        assert ack == {"realtime_data": {"storedCount": 2, "maxStoredSourceId": 4}}

    def test_runSyncUpsert_reportsTheBatchSourceIds(self, syncEngine):
        """
        Given: a batch with realtime_data ids [3, 1, 2] and an empty connection_log
        When: runSyncUpsert is handed a collector for the batch's source_ids
        Then: the collector holds exactly the ids written per table
        """
        from src.server.api.sync import runSyncUpsert

        collected: dict[str, list[int]] = {}
        with Session(syncEngine) as session:
            runSyncUpsert(
                session, deviceId="pi-1", batchId="b",
                tables={
                    "realtime_data": {"rows": _realtimeRows([3, 1, 2])},
                    "connection_log": {"rows": []},
                },
                syncHistoryId=1,
                batchSourceIds=collected,
            )

        assert collected == {"realtime_data": [3, 1, 2], "connection_log": []}
