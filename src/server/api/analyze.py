################################################################################
# File Name: analyze.py
# Purpose/Description: POST /api/v1/analyze stub AI endpoint (US-147). Returns
#                      a canned response with the exact shape US-CMP-005 will
#                      produce in the run phase, and logs each request to
#                      analysis_history for later inspection.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-147 — stub /analyze
# ================================================================================
################################################################################

"""
Stub AI analysis endpoint for the Eclipse OBD-II companion server.

Behaviour (server spec §2.3, sprint US-147):

* ``POST /api/v1/analyze`` accepts a JSON body with ``drive_id`` and
  ``parameters``.
* API key required (attached via ``Depends(requireApiKey)`` at router
  include time in ``src/server/api/app.py``).
* Returns a canned response envelope matching the shape the real run-phase
  endpoint (US-CMP-005) will produce, so the Pi-side client can be wired
  today without knowing the eventual analytics wiring.
* Each request writes a row to ``analysis_history`` with
  ``model_name="stub"``, ``status="completed"``, and an ``analysis_id``
  (plus ``processing_time_ms=0``) stored as JSON in ``result_summary``.
  We store ``analysis_id`` in the JSON blob rather than a dedicated column
  to avoid a schema migration for a stub — the JSON blob pattern mirrors
  ``sync_history.tables_synced`` from US-CMP-004.
* No dependency on ``src/server/analytics/`` — that wiring lands in
  US-CMP-005 (sprint invariant).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from src.server.db.connection import getAsyncSession
from src.server.db.models import AnalysisHistory

logger = logging.getLogger(__name__)

# ---- Constants ---------------------------------------------------------------

STUB_MODEL_NAME = "stub"
STUB_PROCESSING_TIME_MS = 0
STUB_MESSAGE = "Stub analysis — real implementation pending US-CMP-005"
ANALYSIS_ID_PREFIX = "stub-"


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
    """
    POST /analyze response envelope — locked shape shared with US-CMP-005.

    Field-name casing mirrors the sprint-US-147 acceptance block exactly:
    ``analysis_id`` is snake_case (sprint contract) while ``processingTimeMs``
    is camelCase. Divergence from the server spec ``analysisId`` is deliberate
    — the sprint contract wins.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: str
    analysis_id: str
    message: str
    recommendations: list[dict[str, Any]]
    model: str
    processingTimeMs: int


# ==============================================================================
# analysis_history helper (async)
# ==============================================================================


async def _writeAnalysisHistory(
    engine: Any,
    driveId: int,
    analysisId: str,
    startedAt: datetime,
    completedAt: datetime,
) -> None:
    """
    Persist a completed stub analysis to ``analysis_history``.

    ``analysis_id`` and ``processing_time_ms`` are stored in
    ``result_summary`` as JSON because the model has no dedicated columns
    for them — same pattern ``sync_history.tables_synced`` uses for its
    per-table breakdown (US-CMP-004).
    """
    summary = json.dumps(
        {
            "analysis_id": analysisId,
            "processing_time_ms": STUB_PROCESSING_TIME_MS,
        },
        sort_keys=True,
    )
    factory = getAsyncSession(engine)
    async with factory() as session:
        session.add(
            AnalysisHistory(
                drive_id=driveId,
                model_name=STUB_MODEL_NAME,
                started_at=startedAt,
                completed_at=completedAt,
                status="completed",
                result_summary=summary,
            ),
        )
        await session.commit()


# ==============================================================================
# Route
# ==============================================================================


router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: Request, body: AnalyzeRequest) -> AnalyzeResponse:
    """
    Return a stub analysis envelope and log the request.

    The response shape is the contract US-CMP-005 will implement against —
    changing it here forces a matching Pi-side change. Keep it stable.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database engine not configured on app.state.engine",
        )

    analysisId = f"{ANALYSIS_ID_PREFIX}{uuid.uuid4()}"
    now = datetime.now(UTC).replace(tzinfo=None)

    try:
        await _writeAnalysisHistory(
            engine=engine,
            driveId=body.drive_id,
            analysisId=analysisId,
            startedAt=now,
            completedAt=now,
        )
    except Exception:
        logger.exception("analysis_history insert failed for stub request")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record analysis history",
        ) from None

    return AnalyzeResponse(
        status="ok",
        analysis_id=analysisId,
        message=STUB_MESSAGE,
        recommendations=[],
        model=STUB_MODEL_NAME,
        processingTimeMs=STUB_PROCESSING_TIME_MS,
    )


# ---- Public API --------------------------------------------------------------

__all__ = [
    "ANALYSIS_ID_PREFIX",
    "STUB_MESSAGE",
    "STUB_MODEL_NAME",
    "STUB_PROCESSING_TIME_MS",
    "AnalyzeRequest",
    "AnalyzeResponse",
    "analyze",
    "router",
]
