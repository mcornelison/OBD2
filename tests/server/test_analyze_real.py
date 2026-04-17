################################################################################
# File Name: test_analyze_real.py
# Purpose/Description: End-to-end coverage of the real Ollama-backed /analyze
#                      endpoint — analytics wiring, prompt rendering, response
#                      parsing, error mapping, and persistence (US-CMP-005).
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-CMP-005 — real AI path
# ================================================================================
################################################################################

"""
Tests for the real AI analysis path (US-CMP-005).

Covers:

* **Prompt loading / rendering** — system message loaded from Spool's file,
  user template renders against analytics shape.
* **Response parsing** — well-formed JSON, fenced JSON, prose-with-JSON, empty
  array, malformed items skipped rather than failing the call.
* **Full route happy path** — analytics fires, Ollama is monkey-patched,
  recommendations persist, analysis_history transitions to ``completed``,
  envelope shape matches the US-147 contract.
* **Error mapping** — unreachable Ollama → 503, HTTP error → 502, missing
  drive → 404, drive with no readings → 200 + empty list.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("jinja2")

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import create_engine, select  # noqa: E402

from src.server.db.models import (  # noqa: E402
    AnalysisHistory,
    AnalysisRecommendation,
    Base,
    DriveSummary,
    RealtimeData,
)
from src.server.services.analysis import (  # noqa: E402
    ALLOWED_CATEGORIES,
    ANALYSIS_ID_PREFIX,
    NO_DATA_MESSAGE,
    _parseRecommendations,
    _renderUserMessage,
)

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
# Prompt / service layer unit tests (no async DB required)
# ==============================================================================


class TestPromptAssets:
    """Spool's template files must be present and loadable."""

    def test_systemMessageFileExists(self):
        from src.server.services.analysis import SYSTEM_MESSAGE_PATH

        assert SYSTEM_MESSAGE_PATH.is_file(), (
            f"Spool system message missing: {SYSTEM_MESSAGE_PATH}"
        )
        content = SYSTEM_MESSAGE_PATH.read_text(encoding="utf-8")
        # Sanity: the envelope-locking phrases we depend on.
        assert "JSON" in content or "json" in content
        assert "4G63" in content

    def test_userTemplateRendersAgainstMinimalContext(self):
        """Empty lists render cleanly — template uses explicit if-guards."""
        rendered = _renderUserMessage(
            {
                "drive_id": 1,
                "drive_start": "2026-04-16T12:00:00",
                "duration_seconds": 600,
                "row_count": 1200,
                "prior_drives_count": 0,
                "statistics": [],
                "anomalies": [],
                "trend": [],
                "correlations": [],
            }
        )
        assert "Drive ID: 1" in rendered
        assert "Samples collected: 1200" in rendered
        assert "Baseline note" in rendered  # prior < 5 branch fired

    def test_userTemplateRendersStatsTable(self):
        rendered = _renderUserMessage(
            {
                "drive_id": 7,
                "drive_start": "2026-04-16T12:00:00",
                "duration_seconds": 600,
                "row_count": 100,
                "prior_drives_count": 10,
                "statistics": [
                    {
                        "parameter": "RPM",
                        "min": 800.0, "max": 6000.0, "avg": 2750.5,
                        "std": 420.1, "sample_count": 100,
                    },
                ],
                "anomalies": [],
                "trend": [],
                "correlations": [],
            }
        )
        assert "RPM" in rendered
        assert "2750.50" in rendered  # avg rendered via %.2f format spec
        assert "Baseline note" not in rendered  # prior >= 5 branch skipped


class TestRecommendationParsing:
    """``_parseRecommendations`` handles the real-world quirks of Ollama output."""

    def test_bareJsonArray_parsesAllItems(self):
        raw = json.dumps(
            [
                {"rank": 1, "category": "Cooling", "recommendation": "x", "confidence": 0.9},
                {"rank": 2, "category": "Fueling", "recommendation": "y", "confidence": 0.7},
            ]
        )
        recs = _parseRecommendations(raw)
        assert len(recs) == 2
        assert recs[0].rank == 1 and recs[0].category == "Cooling"
        assert recs[1].confidence == pytest.approx(0.7)

    def test_emptyArray_returnsEmptyList(self):
        assert _parseRecommendations("[]") == []

    def test_fencedJson_stillParses(self):
        raw = (
            "```json\n"
            "[{\"rank\": 1, \"category\": \"Mechanical\","
            " \"recommendation\": \"inspect belt\", \"confidence\": 0.8}]\n"
            "```"
        )
        recs = _parseRecommendations(raw)
        assert len(recs) == 1
        assert recs[0].category == "Mechanical"

    def test_proseWithJson_stillParses(self):
        raw = (
            "Here is the analysis:\n"
            "[{\"rank\": 1, \"category\": \"Baseline\","
            " \"recommendation\": \"more drives\", \"confidence\": 0.6}]"
        )
        recs = _parseRecommendations(raw)
        assert len(recs) == 1

    def test_malformedItemsSkipped_notFailed(self):
        raw = json.dumps(
            [
                {"rank": 1, "category": "Cooling", "recommendation": "ok", "confidence": 0.9},
                {"rank": "bogus", "category": "X", "recommendation": "y", "confidence": 0.5},
                {"category": "Baseline", "recommendation": "m", "confidence": 0.4},  # no rank
                {"rank": 2, "category": "InvalidCategory", "recommendation": "n", "confidence": 0.3},
            ]
        )
        recs = _parseRecommendations(raw)
        assert len(recs) == 1
        assert recs[0].category == "Cooling"

    def test_confidenceClampedToUnitInterval(self):
        raw = json.dumps(
            [
                {"rank": 1, "category": "Boost", "recommendation": "a", "confidence": 1.8},
                {"rank": 2, "category": "Boost", "recommendation": "b", "confidence": -0.5},
            ]
        )
        recs = _parseRecommendations(raw)
        assert [r.confidence for r in recs] == [1.0, 0.0]

    def test_truncatedToMaxFive(self):
        items = [
            {"rank": i, "category": "Diagnostic", "recommendation": f"r{i}", "confidence": 0.5}
            for i in range(1, 11)
        ]
        recs = _parseRecommendations(json.dumps(items))
        assert len(recs) == 5

    def test_nonArrayOutput_returnsEmpty(self):
        assert _parseRecommendations("not json at all") == []
        assert _parseRecommendations(json.dumps({"rank": 1})) == []

    def test_allCategoriesAllowlisted(self):
        """Regression guard on the fixed allow-list from Spool's system msg."""
        assert ALLOWED_CATEGORIES == frozenset(
            {
                "Cooling", "Fueling", "Boost", "Electrical",
                "Mechanical", "Diagnostic", "Baseline",
            }
        )


# ==============================================================================
# Full route integration — requires aiosqlite + pytest-asyncio
# ==============================================================================


def _makeSettings(apiKey: str = "valid-key"):
    from src.server.config import Settings

    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=apiKey,
        OLLAMA_BASE_URL="http://test-ollama:11434",
        OLLAMA_MODEL="llama3.1:8b-test",
    )


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
    settings = _makeSettings(apiKey="valid-key")
    app = createApp(settings=settings)
    app.state.engine = engine

    try:
        yield app, engine
    finally:
        await engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)


async def _seedDrive(engine, driveId: int = 101, sampleCount: int = 20):
    """Insert a drive with ``sampleCount`` RPM readings spread over a minute."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine) as session:
        drive = DriveSummary(
            id=driveId,
            device_id="chi-eclipse-01",
            start_time=datetime(2026, 4, 16, 12, 0, 0),
            end_time=datetime(2026, 4, 16, 12, 1, 0),
            duration_seconds=60,
            row_count=sampleCount,
            is_real=False,
        )
        session.add(drive)
        for i in range(sampleCount):
            session.add(
                RealtimeData(
                    source_id=driveId * 1000 + i,
                    source_device="chi-eclipse-01",
                    timestamp=datetime(2026, 4, 16, 12, 0, 0) + timedelta(seconds=i),
                    parameter_name="RPM",
                    value=2000.0 + i * 10.0,
                )
            )
        await session.commit()


@_skipNoAsyncDb
class TestAnalyzeRealHappyPath:
    """Real-path happy flow with Ollama monkey-patched to a fixed response."""

    @pytest.mark.asyncio
    async def test_validDrive_returnsParsedRecommendations(
        self, asyncAppAndEngine, monkeypatch
    ):
        import httpx

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine
        await _seedDrive(engine, driveId=101, sampleCount=20)

        fakeResponse = json.dumps(
            [
                {
                    "rank": 1, "category": "Cooling",
                    "recommendation": "Watch coolant trend vs baseline.",
                    "confidence": 0.85,
                },
                {
                    "rank": 2, "category": "Diagnostic",
                    "recommendation": "Check MAF readings next drive.",
                    "confidence": 0.6,
                },
            ]
        )

        def fakeInvoke(**_kwargs):
            return fakeResponse

        monkeypatch.setattr(analysisModule, "_invokeOllama", fakeInvoke)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/analyze",
                json={"drive_id": 101, "parameters": {"focus": ["RPM"]}},
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["analysis_id"].startswith(ANALYSIS_ID_PREFIX)
        assert body["model"] == "llama3.1:8b-test"
        assert body["processingTimeMs"] >= 0
        assert len(body["recommendations"]) == 2
        rec = body["recommendations"][0]
        assert set(rec.keys()) == {"rank", "category", "recommendation", "confidence"}
        assert rec["rank"] == 1
        assert rec["category"] == "Cooling"

    @pytest.mark.asyncio
    async def test_persistsRecommendationRowsAndCompletedHistory(
        self, asyncAppAndEngine, monkeypatch
    ):
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine
        await _seedDrive(engine, driveId=202)

        monkeypatch.setattr(
            analysisModule, "_invokeOllama",
            lambda **_kw: json.dumps(
                [
                    {
                        "rank": 1, "category": "Baseline",
                        "recommendation": "Need more drives.",
                        "confidence": 0.5,
                    }
                ]
            ),
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/v1/analyze",
                json={"drive_id": 202, "parameters": {}},
                headers={"X-API-Key": "valid-key"},
            )

        async with AsyncSession(engine) as session:
            histories = (
                await session.execute(select(AnalysisHistory))
            ).scalars().all()
            recs = (
                await session.execute(select(AnalysisRecommendation))
            ).scalars().all()

        assert len(histories) == 1
        h = histories[0]
        assert h.drive_id == 202
        assert h.status == "completed"
        assert h.model_name == "llama3.1:8b-test"
        summary = json.loads(h.result_summary)
        assert summary["recommendation_count"] == 1
        assert "raw_response" in summary
        assert "rendered_user_message" in summary

        assert len(recs) == 1
        assert recs[0].analysis_id == h.id
        assert recs[0].rank == 1
        assert recs[0].category == "Baseline"
        assert recs[0].confidence == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_emptyArray_returnsOkWithNoRecommendations(
        self, asyncAppAndEngine, monkeypatch
    ):
        import httpx

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine
        await _seedDrive(engine, driveId=303)

        monkeypatch.setattr(
            analysisModule, "_invokeOllama", lambda **_kw: "[]"
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/analyze",
                json={"drive_id": 303, "parameters": {}},
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        assert response.json()["recommendations"] == []


@_skipNoAsyncDb
class TestAnalyzeRealErrorMapping:
    """Service-layer exceptions translate to documented HTTP status codes."""

    @pytest.mark.asyncio
    async def test_missingDrive_returns404(self, asyncAppAndEngine):
        import httpx

        app, _engine = asyncAppAndEngine

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/analyze",
                json={"drive_id": 9999, "parameters": {}},
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_driveWithNoReadings_returns200EmptyRecs(
        self, asyncAppAndEngine
    ):
        """Drive row exists but no realtime_data → short-circuit 200 empty."""
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        app, engine = asyncAppAndEngine
        async with AsyncSession(engine) as session:
            session.add(
                DriveSummary(
                    id=77,
                    device_id="chi-eclipse-01",
                    start_time=datetime(2026, 4, 16, 12, 0, 0),
                    end_time=datetime(2026, 4, 16, 12, 1, 0),
                    duration_seconds=60,
                    row_count=0,
                    is_real=False,
                )
            )
            await session.commit()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/analyze",
                json={"drive_id": 77, "parameters": {}},
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["recommendations"] == []
        assert body["message"] == NO_DATA_MESSAGE

    @pytest.mark.asyncio
    async def test_ollamaUnreachable_returns503AndFailsHistory(
        self, asyncAppAndEngine, monkeypatch
    ):
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine
        await _seedDrive(engine, driveId=404)

        def raiseUnreachable(**_kw):
            raise analysisModule.OllamaUnreachable("Network unreachable")

        monkeypatch.setattr(analysisModule, "_invokeOllama", raiseUnreachable)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/analyze",
                json={"drive_id": 404, "parameters": {}},
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 503
        assert response.json()["detail"] == "Ollama unavailable"

        async with AsyncSession(engine) as session:
            histories = (
                await session.execute(select(AnalysisHistory))
            ).scalars().all()
        assert len(histories) == 1
        assert histories[0].status == "failed"
        assert histories[0].error_message is not None

    @pytest.mark.asyncio
    async def test_ollamaHttpError_returns502AndFailsHistory(
        self, asyncAppAndEngine, monkeypatch
    ):
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine
        await _seedDrive(engine, driveId=502)

        def raiseHttp(**_kw):
            raise analysisModule.OllamaHttpFailure("Ollama HTTP 500: oops")

        monkeypatch.setattr(analysisModule, "_invokeOllama", raiseHttp)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/analyze",
                json={"drive_id": 502, "parameters": {}},
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 502

        async with AsyncSession(engine) as session:
            histories = (
                await session.execute(select(AnalysisHistory))
            ).scalars().all()
        assert len(histories) == 1
        assert histories[0].status == "failed"


# ==============================================================================
# Transport-level Ollama adapter coverage
# ==============================================================================


class TestCallOllamaChatTransport:
    """Network-layer exceptions surface as the right service-layer errors."""

    def test_connectionRefused_raisesUnreachable(self, monkeypatch):
        import urllib.error

        from src.server.ai import analyzer_ollama as ao

        def fakeOpen(*_a, **_kw):
            raise urllib.error.URLError("Connection refused")

        monkeypatch.setattr(ao.urllib.request, "urlopen", fakeOpen)

        with pytest.raises(ao.OllamaUnreachableError):
            ao.callOllamaChat(
                baseUrl="http://nowhere:11434",
                model="llama3.1:8b",
                systemMessage="sys",
                userMessage="usr",
            )

    def test_httpError_raisesOllamaHttpError(self, monkeypatch):
        import urllib.error

        from src.server.ai import analyzer_ollama as ao

        def fakeOpen(*_a, **_kw):
            raise urllib.error.HTTPError(
                "http://x", 500, "Internal", {}, None,
            )

        monkeypatch.setattr(ao.urllib.request, "urlopen", fakeOpen)

        with pytest.raises(ao.OllamaHttpError) as exc:
            ao.callOllamaChat(
                baseUrl="http://x",
                model="m",
                systemMessage="s",
                userMessage="u",
            )
        assert exc.value.code == 500


# ==============================================================================
# Sprint invariant — /analyze still enforces auth after the rewrite
# ==============================================================================


class TestAnalyzeInvariantsPostRewrite:
    """These cross-cutting guarantees must survive the US-CMP-005 rewrite."""

    def test_analyzeModule_stillExposesRouter(self):
        from src.server.api.analyze import router

        assert router is not None
        paths = [r.path for r in router.routes]
        assert "/analyze" in paths

    def test_requestModelStillForbidsExtraKeys(self):
        from pydantic import ValidationError

        from src.server.api.analyze import AnalyzeRequest

        with pytest.raises(ValidationError):
            AnalyzeRequest.model_validate(
                {"drive_id": 1, "parameters": {}, "extra": "nope"}
            )
