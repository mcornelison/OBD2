################################################################################
# File Name: test_analyze.py
# Purpose/Description: Tests for the POST /api/v1/analyze stub AI endpoint
#                      (US-147). Verifies request validation, response envelope,
#                      analysis_history side-effect, and auth enforcement.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-147 — stub AI endpoint
# ================================================================================
################################################################################

"""
Tests for ``src/server/api/analyze.py`` — the ``POST /api/v1/analyze`` stub.

Split into four concerns:

1. **Pydantic request validation** — shape, required fields.
2. **Route auth** — inherits ``requireApiKey`` like /sync; missing/invalid keys
   must 401.
3. **Response envelope** — exact shape from sprint US-147 acceptance
   (``status``, ``analysis_id`` with ``stub-{uuid}`` format, ``message``,
   ``recommendations`` empty list, ``model="stub"``, ``processingTimeMs=0``).
4. **Side effect on ``analysis_history``** — row written with
   ``model_name="stub"``, ``status="completed"``, and the ``analysis_id``
   recoverable from ``result_summary`` JSON.

Route-level tests that need a real AsyncEngine use ``aiosqlite`` when
installed; when it's not, they skip cleanly (same pattern test_sync.py uses).
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from sqlalchemy import create_engine, select  # noqa: E402

from src.server.db.models import AnalysisHistory, Base  # noqa: E402

# ==============================================================================
# Helpers
# ==============================================================================


def _makeSettings(apiKey: str = "valid-key"):
    from src.server.config import Settings

    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=apiKey,
    )


def _buildAppForRouteTests(apiKey: str = "valid-key"):
    """Build a bare FastAPI app (no engine) for auth / validation tests."""
    from src.server.api.app import createApp

    settings = _makeSettings(apiKey=apiKey)
    app = createApp(settings=settings)
    app.state.engine = None  # no engine for auth / validation tests
    return app


def _validRequest(driveId: int = 42) -> dict:
    """Minimal valid analyze request."""
    return {
        "drive_id": driveId,
        "parameters": {"focus": ["RPM", "MAF"]},
    }


# ==============================================================================
# 1) Pydantic request validation
# ==============================================================================


class TestAnalyzeRequestValidation:
    """The request model rejects malformed payloads before any DB work."""

    def test_validPayload_parsesWithoutError(self):
        from src.server.api.analyze import AnalyzeRequest

        model = AnalyzeRequest.model_validate(_validRequest())
        assert model.drive_id == 42
        assert model.parameters == {"focus": ["RPM", "MAF"]}

    def test_missingDriveId_rejected(self):
        from pydantic import ValidationError

        from src.server.api.analyze import AnalyzeRequest

        payload = _validRequest()
        del payload["drive_id"]
        with pytest.raises(ValidationError):
            AnalyzeRequest.model_validate(payload)

    def test_missingParameters_rejected(self):
        from pydantic import ValidationError

        from src.server.api.analyze import AnalyzeRequest

        payload = _validRequest()
        del payload["parameters"]
        with pytest.raises(ValidationError):
            AnalyzeRequest.model_validate(payload)


# ==============================================================================
# 2) Route auth (inherits requireApiKey)
# ==============================================================================


class TestAnalyzeAuth:
    """Auth is enforced by the shared ``requireApiKey`` dependency (US-CMP-002)."""

    def test_missingApiKey_returns401(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post("/api/v1/analyze", json=_validRequest())

        assert response.status_code == 401

    def test_invalidApiKey_returns401(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/analyze",
                json=_validRequest(),
                headers={"X-API-Key": "wrong"},
            )

        assert response.status_code == 401


# ==============================================================================
# 3) Route body validation (through the full stack)
# ==============================================================================


class TestAnalyzeInvalidBody:
    """Malformed body → 422."""

    def test_missingDriveId_returns422(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/analyze",
                json={"parameters": {}},
                headers={"X-API-Key": "valid-key"},
            )
        assert response.status_code == 422

    def test_missingParameters_returns422(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/analyze",
                json={"drive_id": 7},
                headers={"X-API-Key": "valid-key"},
            )
        assert response.status_code == 422


# ==============================================================================
# 4) Full route + DB integration — requires aiosqlite
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
    schema pre-created. Used for route tests that assert on DB side-effects
    (analysis_history rows) and on the response envelope.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.server.api.app import createApp

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    # Sync engine once to create_all, then dispose — the app uses the
    # aiosqlite async engine for all subsequent operations.
    syncEng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(syncEng)
    syncEng.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    settings = _makeSettings(apiKey="valid-key")
    app = createApp(settings=settings)
    app.state.engine = engine

    try:
        yield app, engine
    finally:
        await engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)


@_skipNoAsyncDb
class TestAnalyzeHappyPath:
    """Full request → 200 with the stub envelope."""

    @pytest.mark.asyncio
    async def test_validRequest_returns200_andStubShape(self, asyncAppAndEngine):
        import httpx

        app, _engine = asyncAppAndEngine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/analyze",
                json=_validRequest(driveId=101),
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["model"] == "stub"
        assert body["processingTimeMs"] == 0
        assert body["recommendations"] == []
        assert body["message"] == (
            "Stub analysis — real implementation pending US-CMP-005"
        )
        assert isinstance(body["analysis_id"], str)
        assert body["analysis_id"].startswith("stub-")

    @pytest.mark.asyncio
    async def test_analysisIdIsValidUuid(self, asyncAppAndEngine):
        import httpx

        app, _engine = asyncAppAndEngine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/analyze",
                json=_validRequest(),
                headers={"X-API-Key": "valid-key"},
            )

        analysisId = response.json()["analysis_id"]
        # ``stub-{uuid}`` — trailing portion must parse as a UUID.
        _, _, rawUuid = analysisId.partition("stub-")
        uuid.UUID(rawUuid)  # raises if invalid

    @pytest.mark.asyncio
    async def test_twoRequests_produceUniqueAnalysisIds(self, asyncAppAndEngine):
        import httpx

        app, _engine = asyncAppAndEngine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            r1 = await client.post(
                "/api/v1/analyze",
                json=_validRequest(driveId=1),
                headers={"X-API-Key": "valid-key"},
            )
            r2 = await client.post(
                "/api/v1/analyze",
                json=_validRequest(driveId=2),
                headers={"X-API-Key": "valid-key"},
            )

        assert r1.json()["analysis_id"] != r2.json()["analysis_id"]


@_skipNoAsyncDb
class TestAnalyzeHistoryRow:
    """The endpoint writes one ``analysis_history`` row per request."""

    @pytest.mark.asyncio
    async def test_writesAnalysisHistoryRow_withStubMetadata(
        self, asyncAppAndEngine,
    ):
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        app, engine = asyncAppAndEngine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/analyze",
                json=_validRequest(driveId=555),
                headers={"X-API-Key": "valid-key"},
            )

        analysisId = response.json()["analysis_id"]

        async with AsyncSession(engine) as session:
            rows = (await session.execute(select(AnalysisHistory))).scalars().all()

        assert len(rows) == 1
        row = rows[0]
        assert row.model_name == "stub"
        assert row.status == "completed"
        assert row.drive_id == 555
        # analysis_id stored in result_summary JSON (no dedicated column).
        summary = json.loads(row.result_summary)
        assert summary["analysis_id"] == analysisId
        assert summary["processing_time_ms"] == 0


# ==============================================================================
# 5) Invariant — no import from src.server.analytics
# ==============================================================================


class TestNoAnalyticsImport:
    """Sprint invariant: no dependency on src.server.analytics (stub only)."""

    def test_analyzeModule_doesNotImportAnalytics(self):
        """
        Parse analyze.py and confirm no ``src.server.analytics`` import
        appears at module scope. The real analytics wiring lands in
        US-CMP-005 (run phase).
        """
        import src.server.api.analyze as analyzeModule

        source = Path(analyzeModule.__file__).read_text(encoding="utf-8")
        assert "src.server.analytics" not in source, (
            "Stub analyze endpoint must not depend on src.server.analytics — "
            "that wiring lands in US-CMP-005 (run phase)."
        )
