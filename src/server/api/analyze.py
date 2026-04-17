################################################################################
# File Name: analyze.py
# Purpose/Description: POST /api/v1/analyze — real Ollama-backed AI analysis
#                      endpoint. Delegates to src.server.services.analysis for
#                      orchestration; this module owns request/response shape
#                      and the auth-wired router (US-CMP-005).
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-147 — stub /analyze
# 2026-04-16    | Ralph Agent  | US-CMP-005 — replace stub with real Ollama path.
#               |              | Response shape preserved (Pi-side contract).
# ================================================================================
################################################################################

"""
Real AI analysis endpoint.

``POST /api/v1/analyze`` returns Ollama-generated tuning recommendations for a
drive. The response envelope shape is the contract locked by US-147 and must
not change without a Pi-side migration::

    {
        "status": "ok",
        "analysis_id": "analysis-<uuid>",
        "message": "...",
        "recommendations": [{"rank", "category", "recommendation", "confidence"}],
        "model": "<ollama model>",
        "processingTimeMs": <int>
    }

All orchestration (analytics refresh, prompt rendering, Ollama call, DB
persistence) lives in :mod:`src.server.services.analysis`. This module only
translates HTTP → service call → HTTP response and maps service-layer
exceptions to the documented status codes.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from src.server.services.analysis import (
    ANALYSIS_ID_PREFIX,
    AnalysisResult,
    DriveNotFound,
    OllamaHttpFailure,
    OllamaUnreachable,
    runAnalysis,
)

logger = logging.getLogger(__name__)

# ---- Defaults for local dev when no Settings are wired ---------------------

_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
_DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
_DEFAULT_TIMEOUT_SECONDS = 120


# ==============================================================================
# Request / Response models
# ==============================================================================


class AnalyzeRequest(BaseModel):
    """POST /analyze request body."""

    model_config = ConfigDict(extra="forbid")

    drive_id: int = Field(..., description="Drive ID to analyse.")
    parameters: dict[str, Any] = Field(
        ...,
        description="Free-form analysis parameters (focus areas, options).",
    )


class AnalyzeResponse(BaseModel):
    """POST /analyze response envelope — locked shape shared with US-147."""

    model_config = ConfigDict(populate_by_name=True)

    status: str
    analysis_id: str
    message: str
    recommendations: list[dict[str, Any]]
    model: str
    processingTimeMs: int


# ==============================================================================
# Route
# ==============================================================================


router = APIRouter()


def _ollamaSettings(request: Request) -> tuple[str, str, int]:
    """Pull Ollama settings off app.state, falling back to defaults for tests."""
    settings = getattr(request.app.state, "settings", None)
    baseUrl = getattr(settings, "OLLAMA_BASE_URL", None) or _DEFAULT_OLLAMA_BASE_URL
    model = getattr(settings, "OLLAMA_MODEL", None) or _DEFAULT_OLLAMA_MODEL
    timeout = int(
        getattr(settings, "ANALYSIS_TIMEOUT_SECONDS", None)
        or _DEFAULT_TIMEOUT_SECONDS
    )
    return baseUrl, model, timeout


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: Request, body: AnalyzeRequest) -> AnalyzeResponse:
    """Run a real AI analysis for ``body.drive_id``.

    Error → HTTP mapping:

    * Drive not found                          → 404
    * Ollama connection/timeout failure        → 503 ``Ollama unavailable``
    * Ollama non-2xx HTTP                      → 502
    * Unexpected exception                     → 500
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database engine not configured on app.state.engine",
        )

    baseUrl, model, timeoutSeconds = _ollamaSettings(request)

    try:
        result: AnalysisResult = await runAnalysis(
            engine=engine,
            driveId=body.drive_id,
            ollamaBaseUrl=baseUrl,
            ollamaModel=model,
            ollamaTimeoutSeconds=timeoutSeconds,
            parameters=body.parameters,
        )
    except DriveNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except OllamaUnreachable as exc:
        logger.warning("Ollama unreachable for drive_id=%s: %s", body.drive_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama unavailable",
        ) from exc
    except OllamaHttpFailure as exc:
        logger.error("Ollama HTTP error for drive_id=%s: %s", body.drive_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama error: {exc}",
        ) from exc

    return AnalyzeResponse(
        status=result.status,
        analysis_id=result.analysis_id,
        message=result.message,
        recommendations=[
            {
                "rank": r.rank,
                "category": r.category,
                "recommendation": r.recommendation,
                "confidence": r.confidence,
            }
            for r in result.recommendations
        ],
        model=result.model,
        processingTimeMs=result.processingTimeMs,
    )


# ---- Public API --------------------------------------------------------------

__all__ = [
    "ANALYSIS_ID_PREFIX",
    "AnalyzeRequest",
    "AnalyzeResponse",
    "analyze",
    "router",
]
