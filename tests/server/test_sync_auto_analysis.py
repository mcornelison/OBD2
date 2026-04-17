################################################################################
# File Name: test_sync_auto_analysis.py
# Purpose/Description: Tests for auto-analysis-on-drive-receipt (US-CMP-006):
#                      when POST /sync contains drive_end events in
#                      connection_log, the server non-blockingly enqueues an AI
#                      analysis task via the shared services.analysis layer.
#                      Covers drive-boundary extraction, Ollama preflight
#                      gating, happy-path task enqueue + completion, and the
#                      graceful-degradation paths that keep /sync 200 even
#                      when Ollama is unreachable or the analysis fails.
# Author: Ralph Agent
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Ralph Agent  | Initial TDD tests for US-CMP-006
# ================================================================================
################################################################################

"""
Tests for the auto-analysis trigger added to POST /api/v1/sync (US-CMP-006).

Four concerns:

1. **Boundary extraction** — pure helper pairs drive_start/drive_end rows from
   a connection_log payload, skipping unpaired starts / orphaned ends / non-
   drive events.
2. **Happy path** — sync body contains a drive_end, Ollama ping is mocked
   True, analysis invoker is mocked to a canned JSON array. The response
   reports ``autoAnalysisTriggered=True``, a ``drive_summary`` row is created,
   and the enqueued task persists an ``AnalysisRecommendation`` row.
3. **Graceful degradation** — Ollama unreachable during preflight ping makes
   ``autoAnalysisTriggered=False`` *without* affecting the 200 status.
4. **No drive_end** — boundary extractor finds nothing; no tasks enqueued;
   ``autoAnalysisTriggered=False``; sync contract otherwise unchanged.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("jinja2")

from sqlalchemy import create_engine, select  # noqa: E402

from src.server.db.models import (  # noqa: E402
    AnalysisHistory,
    AnalysisRecommendation,
    Base,
    DriveSummary,
)

# ==============================================================================
# aiosqlite gating (same pattern as test_sync / test_analyze_real)
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


# ==============================================================================
# 1) Boundary extraction — pure helper
# ==============================================================================


class TestExtractDriveBoundaries:
    """``extractDriveBoundaries`` pairs drive_start/drive_end events."""

    def test_pairedStartEnd_returnsSingleBoundary(self):
        from src.server.services.analysis import extractDriveBoundaries

        rows = [
            {"timestamp": "2026-04-17T08:00:00", "event_type": "drive_start"},
            {"timestamp": "2026-04-17T08:05:00", "event_type": "drive_end"},
        ]
        assert extractDriveBoundaries(rows) == [
            (datetime(2026, 4, 17, 8, 0, 0), datetime(2026, 4, 17, 8, 5, 0)),
        ]

    def test_multiplePairedDrives_allReturned(self):
        from src.server.services.analysis import extractDriveBoundaries

        rows = [
            {"timestamp": "2026-04-17T08:00:00", "event_type": "drive_start"},
            {"timestamp": "2026-04-17T08:05:00", "event_type": "drive_end"},
            {"timestamp": "2026-04-17T09:00:00", "event_type": "drive_start"},
            {"timestamp": "2026-04-17T09:10:00", "event_type": "drive_end"},
        ]
        result = extractDriveBoundaries(rows)
        assert len(result) == 2
        assert result[0][0] == datetime(2026, 4, 17, 8, 0, 0)
        assert result[1][1] == datetime(2026, 4, 17, 9, 10, 0)

    def test_unpairedStart_ignored(self):
        from src.server.services.analysis import extractDriveBoundaries

        rows = [
            {"timestamp": "2026-04-17T08:00:00", "event_type": "drive_start"},
        ]
        assert extractDriveBoundaries(rows) == []

    def test_orphanedEnd_ignored(self):
        from src.server.services.analysis import extractDriveBoundaries

        rows = [
            {"timestamp": "2026-04-17T08:05:00", "event_type": "drive_end"},
        ]
        assert extractDriveBoundaries(rows) == []

    def test_nonDriveEvents_skipped(self):
        from src.server.services.analysis import extractDriveBoundaries

        rows = [
            {"timestamp": "2026-04-17T07:55:00", "event_type": "obd_connected"},
            {"timestamp": "2026-04-17T08:00:00", "event_type": "drive_start"},
            {"timestamp": "2026-04-17T08:05:00", "event_type": "drive_end"},
            {"timestamp": "2026-04-17T08:06:00", "event_type": "obd_disconnected"},
        ]
        assert extractDriveBoundaries(rows) == [
            (datetime(2026, 4, 17, 8, 0, 0), datetime(2026, 4, 17, 8, 5, 0)),
        ]

    def test_unorderedTimestamps_sortedBeforePairing(self):
        from src.server.services.analysis import extractDriveBoundaries

        rows = [
            {"timestamp": "2026-04-17T08:05:00", "event_type": "drive_end"},
            {"timestamp": "2026-04-17T08:00:00", "event_type": "drive_start"},
        ]
        assert extractDriveBoundaries(rows) == [
            (datetime(2026, 4, 17, 8, 0, 0), datetime(2026, 4, 17, 8, 5, 0)),
        ]

    def test_malformedTimestampString_skipped(self):
        from src.server.services.analysis import extractDriveBoundaries

        rows = [
            {"timestamp": "nonsense", "event_type": "drive_start"},
            {"timestamp": "2026-04-17T08:05:00", "event_type": "drive_end"},
        ]
        assert extractDriveBoundaries(rows) == []

    def test_datetimeTimestamp_acceptedAsIs(self):
        """Already-parsed datetimes pass through without reparsing."""
        from src.server.services.analysis import extractDriveBoundaries

        rows = [
            {
                "timestamp": datetime(2026, 4, 17, 8, 0, 0),
                "event_type": "drive_start",
            },
            {
                "timestamp": datetime(2026, 4, 17, 8, 5, 0),
                "event_type": "drive_end",
            },
        ]
        assert len(extractDriveBoundaries(rows)) == 1


# ==============================================================================
# 2) Full route integration — requires aiosqlite + pytest-asyncio
# ==============================================================================


def _makeSettings(apiKey: str = "valid-key", maxMb: int = 10):
    from src.server.config import Settings

    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=apiKey,
        MAX_SYNC_PAYLOAD_MB=maxMb,
        OLLAMA_BASE_URL="http://fake-ollama:11434",
        OLLAMA_MODEL="llama3.1:8b-test",
    )


def _buildSyncRequestWithDrive(
    deviceId: str = "chi-eclipse-01",
    batchId: str = "batch-auto-1",
) -> dict:
    """A minimal sync payload that should trigger one auto-analysis."""
    return {
        "deviceId": deviceId,
        "batchId": batchId,
        "tables": {
            "realtime_data": {
                "lastSyncedId": 0,
                "rows": [
                    {
                        "id": 1,
                        "timestamp": "2026-04-17T08:00:30",
                        "parameter_name": "RPM",
                        "value": 2500.0,
                        "unit": "rpm",
                        "profile_id": "daily",
                    },
                    {
                        "id": 2,
                        "timestamp": "2026-04-17T08:01:00",
                        "parameter_name": "RPM",
                        "value": 2600.0,
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
                        "timestamp": "2026-04-17T08:00:00",
                        "event_type": "drive_start",
                        "success": 1,
                    },
                    {
                        "id": 2,
                        "timestamp": "2026-04-17T08:05:00",
                        "event_type": "drive_end",
                        "success": 1,
                    },
                ],
            },
        },
    }


@_asyncFixture
async def asyncAppAndEngine():
    """App + real AsyncEngine backed by a file-based aiosqlite DB."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.server.api.app import createApp

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    syncEng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(syncEng)
    syncEng.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    settings = _makeSettings()
    app = createApp(settings=settings)
    app.state.engine = engine

    try:
        yield app, engine
    finally:
        await engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)


async def _drainPendingAutoAnalysis(analysisModule) -> None:
    """Await any background tasks the auto-analysis path spawned."""
    pending = list(analysisModule._pendingAutoAnalysisTasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@_skipNoAsyncDb
class TestAutoAnalysisHappyPath:
    """Drive end + healthy Ollama → analysis task enqueued + persists recs."""

    @pytest.mark.asyncio
    async def test_driveEnd_triggersAnalysisAndPersistsRecommendation(
        self, asyncAppAndEngine, monkeypatch
    ):
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine

        async def fakePing(*_args, **_kwargs):
            return True

        monkeypatch.setattr(analysisModule, "pingOllama", fakePing)

        fakeResponse = json.dumps(
            [
                {
                    "rank": 1,
                    "category": "Cooling",
                    "recommendation": "Monitor coolant trend.",
                    "confidence": 0.8,
                },
            ]
        )
        monkeypatch.setattr(
            analysisModule, "_invokeOllama", lambda **_kw: fakeResponse
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/sync",
                json=_buildSyncRequestWithDrive(),
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["driveDataReceived"] is True
        assert body["autoAnalysisTriggered"] is True

        await _drainPendingAutoAnalysis(analysisModule)

        async with AsyncSession(engine) as session:
            drives = (await session.execute(select(DriveSummary))).scalars().all()
            histories = (
                await session.execute(select(AnalysisHistory))
            ).scalars().all()
            recs = (
                await session.execute(select(AnalysisRecommendation))
            ).scalars().all()

        assert len(drives) == 1
        assert drives[0].device_id == "chi-eclipse-01"
        assert drives[0].start_time == datetime(2026, 4, 17, 8, 0, 0)
        assert drives[0].end_time == datetime(2026, 4, 17, 8, 5, 0)

        assert len(histories) == 1
        assert histories[0].status == "completed"
        assert histories[0].drive_id == drives[0].id

        assert len(recs) == 1
        assert recs[0].category == "Cooling"


@_skipNoAsyncDb
class TestAutoAnalysisNoDriveEnd:
    """No drive_end → boundary extractor empty → analysis skipped silently."""

    @pytest.mark.asyncio
    async def test_noDriveEnd_autoAnalysisFlagFalse_andNoTasks(
        self, asyncAppAndEngine, monkeypatch
    ):
        import httpx

        from src.server.services import analysis as analysisModule

        app, _engine = asyncAppAndEngine

        async def fakePing(*_args, **_kwargs):
            return True  # Ollama reachable, but still no work to enqueue

        monkeypatch.setattr(analysisModule, "pingOllama", fakePing)

        # Build a payload that has realtime_data but *no* drive_end
        payload = _buildSyncRequestWithDrive()
        payload["tables"]["connection_log"]["rows"] = [
            {
                "id": 1,
                "timestamp": "2026-04-17T08:00:00",
                "event_type": "drive_start",
                "success": 1,
            },
        ]

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
        body = response.json()
        assert body["driveDataReceived"] is False
        assert body["autoAnalysisTriggered"] is False


@_skipNoAsyncDb
class TestAutoAnalysisOllamaUnavailable:
    """Ollama ping fails → sync still 200 but autoAnalysisTriggered=False."""

    @pytest.mark.asyncio
    async def test_ollamaUnreachable_syncSucceedsFlagFalse_warningLogged(
        self, asyncAppAndEngine, monkeypatch, caplog
    ):
        import logging

        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine

        async def fakePing(*_args, **_kwargs):
            return False

        monkeypatch.setattr(analysisModule, "pingOllama", fakePing)

        def exploding_invoke(**_kw):  # pragma: no cover — must not be reached
            raise AssertionError("Ollama must not be invoked when ping fails")

        monkeypatch.setattr(
            analysisModule, "_invokeOllama", exploding_invoke
        )

        with caplog.at_level(logging.WARNING, logger="src.server.services.analysis"):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/sync",
                    json=_buildSyncRequestWithDrive(),
                    headers={"X-API-Key": "valid-key"},
                )

        assert response.status_code == 200
        body = response.json()
        assert body["driveDataReceived"] is True
        assert body["autoAnalysisTriggered"] is False

        # No analysis_history or recommendation rows should have been written.
        async with AsyncSession(engine) as session:
            histories = (
                await session.execute(select(AnalysisHistory))
            ).scalars().all()
        assert histories == []

        assert any(
            "Ollama" in record.getMessage() for record in caplog.records
        ), "expected a WARNING mentioning Ollama when preflight ping fails"


@_skipNoAsyncDb
class TestAutoAnalysisFailureIsolation:
    """Analysis raises after enqueue → sync success already returned, error logged."""

    @pytest.mark.asyncio
    async def test_analysisRaises_syncStillSucceeds_andNoRecommendations(
        self, asyncAppAndEngine, monkeypatch, caplog
    ):
        import logging

        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine

        async def fakePing(*_args, **_kwargs):
            return True

        monkeypatch.setattr(analysisModule, "pingOllama", fakePing)

        def raiseUnreachable(**_kw):
            raise analysisModule.OllamaUnreachable("boom")

        monkeypatch.setattr(analysisModule, "_invokeOllama", raiseUnreachable)

        with caplog.at_level(logging.ERROR, logger="src.server.services.analysis"):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/sync",
                    json=_buildSyncRequestWithDrive(),
                    headers={"X-API-Key": "valid-key"},
                )

        # Sync is already returned; task failed after that.
        assert response.status_code == 200
        body = response.json()
        assert body["autoAnalysisTriggered"] is True

        await _drainPendingAutoAnalysis(analysisModule)

        async with AsyncSession(engine) as session:
            recs = (
                await session.execute(select(AnalysisRecommendation))
            ).scalars().all()
        assert recs == []

        assert any(
            "Auto-analysis" in record.getMessage() and record.levelno == logging.ERROR
            for record in caplog.records
        ), "expected an ERROR log for the failed analysis task"
