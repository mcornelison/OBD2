################################################################################
# File Name: analysis.py
# Purpose/Description: Real AI analysis service — reads drive analytics, renders
#                      Spool's prompt, calls Ollama /api/chat, persists ranked
#                      recommendations. Replaces the US-147 stub on the /analyze
#                      endpoint (US-CMP-005, server spec §3.1).
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-005
# ================================================================================
################################################################################

"""
Analysis service — the orchestration layer between the /analyze FastAPI route
and the underlying analytics, AI, and DB modules.

High-level flow (server spec §3.1 + sprint US-CMP-005 acceptance):

1. Insert an ``analysis_history`` row with ``status="in_progress"``.
2. Load the ``drive_summary`` row. Missing drive → raise :class:`DriveNotFound`
   (API layer maps to 404).
3. Call the analytics engine to refresh per-drive statistics, detect
   anomalies, compute trends per observed parameter, and correlations
   between tuning-relevant pairs. Analytics funcs are sync, so we cross the
   async → sync boundary via :meth:`AsyncSession.run_sync`.
4. If no readings exist in the drive's time window, short-circuit: return an
   empty recommendations envelope and mark ``analysis_history.status =
   "completed"`` with a message.
5. Render Spool's ``user_message.jinja`` against the analytics summary.
6. Call Ollama ``/api/chat`` via :func:`src.server.ai.analyzer_ollama.callOllamaChat`
   with the loaded system message + rendered user message.
7. Parse the JSON reply into :class:`Recommendation` instances; skip malformed
   items rather than failing the whole analysis.
8. Persist per-recommendation rows to ``analysis_recommendations`` and update
   ``analysis_history`` to ``status="completed"`` with the raw response + the
   rendered user message archived in ``result_summary`` (for Spool's review
   ritual — see prompts/DESIGN_NOTE.md §"Suggested review ritual").

Failure modes:

* Ollama connection/timeout → raises :class:`OllamaUnreachable` (API → 503);
  history row marked ``failed``.
* Ollama HTTP non-2xx → raises :class:`OllamaHttpFailure` (API → 502); history
  row marked ``failed``.
* Empty/malformed model output → history row marked ``completed`` with empty
  recommendations; raw content preserved in ``result_summary`` for review.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from src.server.ai.analyzer_ollama import (
    OllamaHttpError,
    OllamaUnreachableError,
    callOllamaChat,
)
from src.server.ai.exceptions import AiAnalyzerGenerationError
from src.server.analytics.advanced import (
    computeCorrelations,
    computeTrends,
    detectAnomalies,
)
from src.server.analytics.basic import computeDriveStatistics
from src.server.db.connection import getAsyncSession
from src.server.db.models import (
    AnalysisHistory,
    AnalysisRecommendation,
    DriveStatistic,
    DriveSummary,
    RealtimeData,
)

logger = logging.getLogger(__name__)

# ---- Constants ---------------------------------------------------------------

ANALYSIS_ID_PREFIX = "analysis-"

# Spool's prompt templates. Paths are resolved relative to this file so the
# server works regardless of CWD. See prompts/__init__.py for rationale.
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM_MESSAGE_PATH = _PROMPT_DIR / "system_message.txt"
USER_TEMPLATE_NAME = "user_message.jinja"

ALLOWED_CATEGORIES = frozenset(
    {
        "Cooling",
        "Fueling",
        "Boost",
        "Electrical",
        "Mechanical",
        "Diagnostic",
        "Baseline",
    }
)

MAX_RECOMMENDATIONS = 5
NO_DATA_MESSAGE = "No readings in the drive's time window — nothing to analyze."


# ---- Service-layer exceptions ------------------------------------------------


class DriveNotFound(Exception):
    """Raised when the requested drive_id has no ``drive_summary`` row."""


class OllamaUnreachable(Exception):
    """Raised when Ollama cannot be reached (connection/timeout)."""


class OllamaHttpFailure(Exception):
    """Raised when Ollama returns a non-2xx HTTP status."""


# ---- Result shapes -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Recommendation:
    """A single parsed recommendation from Ollama."""

    rank: int
    category: str
    recommendation: str
    confidence: float


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Envelope returned to the API layer. Field names mirror the HTTP shape.

    ``processingTimeMs`` is camelCase to match the Pi-facing contract locked
    by US-147.
    """

    status: str
    analysis_id: str
    message: str
    recommendations: list[Recommendation]
    model: str
    processingTimeMs: int


# ---- Prompt loading ----------------------------------------------------------


def _loadSystemMessage() -> str:
    """Return the invariant system message authored by Spool.

    Loaded fresh per call — cost is negligible (~5 KB file) and keeps Spool
    able to edit the file without a server restart. Raises :class:`FileNotFoundError`
    if the file is missing, which is treated as a fatal configuration error.
    """
    return SYSTEM_MESSAGE_PATH.read_text(encoding="utf-8")


def _renderUserMessage(context: dict[str, Any]) -> str:
    """Render ``user_message.jinja`` with ``context`` and return the prompt."""
    env = Environment(
        loader=FileSystemLoader(str(_PROMPT_DIR)),
        autoescape=select_autoescape(disabled_extensions=("jinja", "txt")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(USER_TEMPLATE_NAME)
    return template.render(**context)


# ---- Analytics summary build -------------------------------------------------


def _buildAnalyticsContext(
    session: Session, drive: DriveSummary,
) -> dict[str, Any] | None:
    """
    Refresh analytics for ``drive`` and collect the Jinja render context.

    Returns ``None`` when the drive has zero realtime readings (computeDriveStatistics
    produced no rows) — the caller treats this as the "no data" short-circuit.

    This runs inside a single sync session. Any pre-existing
    ``drive_statistics`` / ``anomaly_log`` rows for the drive are replaced by
    the analytics calls (idempotent by design).
    """
    stats = computeDriveStatistics(session, drive.id)
    if not stats:
        return None

    anomalies = detectAnomalies(session, drive.id)

    # Trend per parameter present in this drive's stats — computeTrends is
    # cheap (reads last N drive_statistics rows for the parameter) and
    # intentionally writes a snapshot each call.
    trends = []
    for s in stats:
        result = computeTrends(session, s.parameter_name)
        if result is not None:
            trends.append(result)

    correlations = computeCorrelations(session)

    # Count prior drives with any stats (signal to the model for baseline
    # maturity — see user_message.jinja "Baseline note" branch).
    priorDrivesCount = session.execute(
        select(DriveStatistic.drive_id)
        .where(DriveStatistic.drive_id != drive.id)
        .distinct()
    ).scalars().all()

    startTime = drive.start_time
    drivenDuration = drive.duration_seconds or 0
    rowCount = drive.row_count or sum(s.sample_count for s in stats)

    return {
        "drive_id": drive.id,
        "drive_start": (
            startTime.isoformat() if hasattr(startTime, "isoformat") else str(startTime)
        ),
        "duration_seconds": int(drivenDuration),
        "row_count": int(rowCount),
        "prior_drives_count": len(priorDrivesCount),
        "statistics": [
            {
                "parameter": s.parameter_name,
                "min": s.min_value,
                "max": s.max_value,
                "avg": s.avg_value,
                "std": s.std_dev,
                "sample_count": s.sample_count,
            }
            for s in stats
        ],
        "anomalies": [
            {
                "parameter": a.parameter_name,
                "sigma": a.deviation_sigma,
                "direction": (
                    "ABOVE" if a.deviation_sigma >= 0.0 else "BELOW"
                ),
                "historical_avg": (a.expected_min + a.expected_max) / 2.0,
            }
            for a in anomalies
        ],
        "trend": [
            {
                "parameter": t.parameter_name,
                "direction": t.direction.value,
                "percent_delta": t.drift_pct,
                "significance": (
                    "significant" if abs(t.drift_pct) > 5.0 else "noise"
                ),
            }
            for t in trends
        ],
        "correlations": [
            {
                "param_a": c.parameter_a,
                "param_b": c.parameter_b,
                "coefficient": c.pearson_r,
            }
            for c in correlations
        ],
    }


# ---- Ollama response parsing -------------------------------------------------


_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _parseRecommendations(raw: str) -> list[Recommendation]:
    """Parse Ollama's raw ``/api/chat`` content into recommendation objects.

    The system prompt asks for a bare JSON array. Real-world LLMs still
    sometimes wrap output in prose or code fences, so we:

    1. Try direct :func:`json.loads`.
    2. Fall back to the first ``[...]`` span via regex (handles fences + prose).

    Items missing required fields, or with categories outside the Spool-defined
    set, are logged and skipped — the story scope prefers "empty list with
    raw-text archived for review" over "500 error on malformed AI output".
    """
    arr: list[Any] | None = None
    try:
        candidate = json.loads(raw)
        if isinstance(candidate, list):
            arr = candidate
    except json.JSONDecodeError:
        match = _JSON_ARRAY_RE.search(raw)
        if match is not None:
            try:
                candidate = json.loads(match.group(0))
                if isinstance(candidate, list):
                    arr = candidate
            except json.JSONDecodeError:
                arr = None

    if arr is None:
        logger.warning("Ollama response did not contain a parseable JSON array")
        return []

    recs: list[Recommendation] = []
    for item in arr[:MAX_RECOMMENDATIONS]:
        if not isinstance(item, dict):
            continue
        try:
            rank = int(item["rank"])
            category = str(item["category"])
            text = str(item["recommendation"])
            confidence = float(item["confidence"])
        except (KeyError, TypeError, ValueError):
            logger.debug("Dropping malformed recommendation item: %r", item)
            continue

        if category not in ALLOWED_CATEGORIES:
            logger.debug(
                "Dropping recommendation with off-envelope category: %r", category
            )
            continue
        if not text.strip():
            continue
        confidence = max(0.0, min(1.0, confidence))

        recs.append(
            Recommendation(
                rank=rank,
                category=category,
                recommendation=text.strip(),
                confidence=confidence,
            )
        )
    return recs


# ---- History row helpers -----------------------------------------------------


def _startHistory(
    session: Session, driveId: int, modelName: str, startedAt: datetime,
) -> int:
    """Insert ``analysis_history`` row in ``in_progress`` state and return id."""
    row = AnalysisHistory(
        drive_id=driveId,
        model_name=modelName,
        started_at=startedAt,
        status="in_progress",
    )
    session.add(row)
    session.flush()  # assigns row.id
    return row.id


def _completeHistory(
    session: Session,
    historyId: int,
    completedAt: datetime,
    resultSummary: dict[str, Any],
) -> None:
    session.execute(
        update(AnalysisHistory)
        .where(AnalysisHistory.id == historyId)
        .values(
            status="completed",
            completed_at=completedAt,
            result_summary=json.dumps(resultSummary, sort_keys=True, default=str),
        )
    )


def _failHistory(
    session: Session, historyId: int, completedAt: datetime, errorMessage: str,
) -> None:
    session.execute(
        update(AnalysisHistory)
        .where(AnalysisHistory.id == historyId)
        .values(
            status="failed",
            completed_at=completedAt,
            error_message=errorMessage,
        )
    )


def _persistRecommendations(
    session: Session, analysisId: int, recs: list[Recommendation],
) -> None:
    for r in recs:
        session.add(
            AnalysisRecommendation(
                analysis_id=analysisId,
                rank=r.rank,
                category=r.category,
                recommendation=r.recommendation,
                confidence=r.confidence,
            )
        )


# ---- Ollama call adapter (module-level so tests can monkeypatch) ------------


def _invokeOllama(
    baseUrl: str,
    model: str,
    systemMessage: str,
    userMessage: str,
    timeoutSeconds: int,
) -> str:
    """Thin adapter over :func:`callOllamaChat` for test monkeypatching.

    Translates the low-level transport exceptions into the service-layer
    exception vocabulary the API router understands.
    """
    try:
        return callOllamaChat(
            baseUrl=baseUrl,
            model=model,
            systemMessage=systemMessage,
            userMessage=userMessage,
            timeoutSeconds=timeoutSeconds,
        )
    except OllamaUnreachableError as exc:
        raise OllamaUnreachable(str(exc)) from exc
    except OllamaHttpError as exc:
        raise OllamaHttpFailure(str(exc)) from exc


# ---- Public service entrypoint -----------------------------------------------


async def runAnalysis(
    engine: AsyncEngine,
    driveId: int,
    *,
    ollamaBaseUrl: str,
    ollamaModel: str,
    ollamaTimeoutSeconds: int = 120,
    parameters: dict[str, Any] | None = None,
) -> AnalysisResult:
    """
    Orchestrate a real AI analysis for ``driveId``.

    Args:
        engine: Async SQLAlchemy engine bound to the server database.
        driveId: PK of the ``drive_summary`` row to analyse.
        ollamaBaseUrl: Base URL for Ollama (e.g. ``"http://10.27.27.10:11434"``).
        ollamaModel: Model name (e.g. ``"llama3.1:8b"``).
        ollamaTimeoutSeconds: HTTP timeout for the chat call.
        parameters: Request-level parameters (focus areas, free-form) — stored
            with the history row for audit. Optional.

    Returns:
        An :class:`AnalysisResult` envelope. Empty ``recommendations`` is a
        valid outcome (Spool's prompt allows the model to return ``[]``).

    Raises:
        DriveNotFound: ``driveId`` has no ``drive_summary`` row.
        OllamaUnreachable: Ollama host not reachable (API layer → 503).
        OllamaHttpFailure: Ollama returned non-2xx HTTP (API layer → 502).
    """
    analysisIdLabel = f"{ANALYSIS_ID_PREFIX}{uuid.uuid4()}"
    startedAt = datetime.now(UTC).replace(tzinfo=None)
    startMonotonic = time.perf_counter()

    factory = getAsyncSession(engine)

    # ---- Phase 1: start history row + validate drive + build analytics ------
    async with factory() as session:
        historyId, analyticsContext, driveExists = await session.run_sync(
            lambda s: _startAndBuildContext(s, driveId, ollamaModel, startedAt)
        )
        await session.commit()

    if not driveExists:
        raise DriveNotFound(f"No drive_summary row for drive_id={driveId}")

    # No readings → short-circuit cleanly; mark history as completed.
    if analyticsContext is None:
        async with factory() as session:
            await session.run_sync(
                lambda s: _completeHistory(
                    s,
                    historyId,
                    datetime.now(UTC).replace(tzinfo=None),
                    {
                        "analysis_id": analysisIdLabel,
                        "processing_time_ms": _elapsedMs(startMonotonic),
                        "recommendation_count": 0,
                        "note": NO_DATA_MESSAGE,
                    },
                )
            )
            await session.commit()
        return AnalysisResult(
            status="ok",
            analysis_id=analysisIdLabel,
            message=NO_DATA_MESSAGE,
            recommendations=[],
            model=ollamaModel,
            processingTimeMs=_elapsedMs(startMonotonic),
        )

    # ---- Phase 2: render prompts and call Ollama ----------------------------
    systemMessage = _loadSystemMessage()
    userMessage = _renderUserMessage(analyticsContext)

    try:
        rawResponse = _invokeOllama(
            baseUrl=ollamaBaseUrl,
            model=ollamaModel,
            systemMessage=systemMessage,
            userMessage=userMessage,
            timeoutSeconds=ollamaTimeoutSeconds,
        )
    except (OllamaUnreachable, OllamaHttpFailure) as exc:
        await _markHistoryFailed(
            factory, historyId, str(exc), datetime.now(UTC).replace(tzinfo=None),
        )
        raise
    except AiAnalyzerGenerationError as exc:
        # Empty / malformed transport response — treat as failed.
        await _markHistoryFailed(
            factory, historyId, str(exc), datetime.now(UTC).replace(tzinfo=None),
        )
        raise OllamaHttpFailure(str(exc)) from exc

    # ---- Phase 3: parse, persist, complete ----------------------------------
    recommendations = _parseRecommendations(rawResponse)
    processingMs = _elapsedMs(startMonotonic)
    completedAt = datetime.now(UTC).replace(tzinfo=None)

    async with factory() as session:
        await session.run_sync(
            lambda s: _finalizeAnalysis(
                s,
                historyId=historyId,
                completedAt=completedAt,
                recommendations=recommendations,
                rawResponse=rawResponse,
                renderedUserMessage=userMessage,
                analysisIdLabel=analysisIdLabel,
                processingMs=processingMs,
            )
        )
        await session.commit()

    message = (
        f"{len(recommendations)} recommendation(s) from {ollamaModel}"
        if recommendations
        else "Analysis complete — no actionable recommendations."
    )
    return AnalysisResult(
        status="ok",
        analysis_id=analysisIdLabel,
        message=message,
        recommendations=recommendations,
        model=ollamaModel,
        processingTimeMs=processingMs,
    )


# ---- Sync helpers (run inside AsyncSession.run_sync) ------------------------


def _startAndBuildContext(
    session: Session, driveId: int, modelName: str, startedAt: datetime,
) -> tuple[int, dict[str, Any] | None, bool]:
    """Insert history row, validate drive, and build analytics context.

    Returned ``driveExists`` tells the caller whether to raise ``DriveNotFound``.
    We still record the history row (as ``failed``) in that case so every
    request leaves an audit trail.
    """
    drive = session.get(DriveSummary, driveId)
    historyId = _startHistory(session, driveId, modelName, startedAt)

    if drive is None:
        _failHistory(
            session,
            historyId,
            startedAt,
            f"drive_summary row not found for drive_id={driveId}",
        )
        return historyId, None, False

    context = _buildAnalyticsContext(session, drive)
    return historyId, context, True


def _finalizeAnalysis(
    session: Session,
    *,
    historyId: int,
    completedAt: datetime,
    recommendations: list[Recommendation],
    rawResponse: str,
    renderedUserMessage: str,
    analysisIdLabel: str,
    processingMs: int,
) -> None:
    _persistRecommendations(session, historyId, recommendations)
    _completeHistory(
        session,
        historyId,
        completedAt,
        {
            "analysis_id": analysisIdLabel,
            "processing_time_ms": processingMs,
            "recommendation_count": len(recommendations),
            "raw_response": rawResponse,
            "rendered_user_message": renderedUserMessage,
        },
    )


async def _markHistoryFailed(
    factory: Any, historyId: int, errorMessage: str, completedAt: datetime,
) -> None:
    """Best-effort failure update; swallows its own DB errors."""
    try:
        async with factory() as session:
            await session.run_sync(
                lambda s: _failHistory(s, historyId, completedAt, errorMessage)
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — already in an error path
        logger.exception("Failed to record analysis_history failure")


def _elapsedMs(startMonotonic: float) -> int:
    return int((time.perf_counter() - startMonotonic) * 1000)


# ==============================================================================
# Auto-analysis on sync receipt (US-CMP-006)
# ==============================================================================
#
# After a successful /sync, the server scans the synced connection_log payload
# for drive_start/drive_end pairs, materializes a drive_summary row for each
# completed drive (the sync path does not create these on its own — only
# scripts/load_data.py did in the crawl phase), and kicks off a non-blocking
# analysis task per drive. The sync HTTP response is never gated on Ollama;
# a preflight ping decides whether to enqueue at all, and individual task
# failures are logged without affecting the (already-returned) sync result.

# Pending tasks set — production side it lets the event loop keep a strong
# reference so tasks don't get GC'd mid-flight; test side it lets tests drain
# the background work before asserting on DB state.
_pendingAutoAnalysisTasks: set[asyncio.Task[Any]] = set()

# Preflight ping timeout — short enough to fail fast, long enough for a local
# Ollama on cold boot.
_OLLAMA_PING_TIMEOUT_SECONDS = 5.0


async def pingOllama(
    baseUrl: str, timeoutSeconds: float = _OLLAMA_PING_TIMEOUT_SECONDS,
) -> bool:
    """Return True iff Ollama's root endpoint responds 200 within the timeout.

    Delegates the blocking ``urllib`` call to the default thread-pool executor
    so the event loop is never blocked. Any error (connection, timeout, DNS)
    is treated as "unreachable" and returns False.
    """

    def _doPing() -> bool:
        request = urllib.request.Request(f"{baseUrl.rstrip('/')}/", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeoutSeconds) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _doPing)


def extractDriveBoundaries(
    rows: list[dict[str, Any]],
) -> list[tuple[datetime, datetime]]:
    """Pair ``drive_start`` / ``drive_end`` events into (start, end) tuples.

    Accepts raw connection_log dicts (timestamps as ISO strings or already-parsed
    datetimes). Rows are sorted by timestamp before pairing. A new drive_start
    before a drive_end discards the pending start (matches load_data.py's
    false-start semantics). Malformed or non-drive events are skipped.
    """
    events: list[tuple[datetime, str]] = []
    for row in rows:
        eventType = row.get("event_type")
        if eventType not in {"drive_start", "drive_end"}:
            continue
        ts = row.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if not isinstance(ts, datetime):
            continue
        events.append((ts, eventType))

    events.sort(key=lambda x: x[0])

    drives: list[tuple[datetime, datetime]] = []
    pendingStart: datetime | None = None
    for ts, eventType in events:
        if eventType == "drive_start":
            pendingStart = ts
        elif eventType == "drive_end" and pendingStart is not None:
            drives.append((pendingStart, ts))
            pendingStart = None
    return drives


def _ensureDriveSummary(
    session: Session, deviceId: str, startTime: datetime, endTime: datetime,
) -> int:
    """Return the drive_summary id for (deviceId, startTime), creating if absent.

    row_count and profile_id are derived from realtime_data already upserted
    for the same time window — matches the idempotent semantics of
    scripts/load_data.py:_createDriveSummaries so crawl and walk paths produce
    equivalent drive_summary rows.
    """
    existingId = session.execute(
        select(DriveSummary.id)
        .where(DriveSummary.device_id == deviceId)
        .where(DriveSummary.start_time == startTime),
    ).scalar_one_or_none()
    if existingId is not None:
        return existingId

    duration = int((endTime - startTime).total_seconds())
    rowCount = session.execute(
        select(func.count())
        .select_from(RealtimeData)
        .where(RealtimeData.source_device == deviceId)
        .where(RealtimeData.timestamp >= startTime)
        .where(RealtimeData.timestamp <= endTime),
    ).scalar_one()
    profileId = session.execute(
        select(RealtimeData.profile_id)
        .where(RealtimeData.source_device == deviceId)
        .where(RealtimeData.timestamp >= startTime)
        .where(RealtimeData.timestamp <= endTime)
        .limit(1),
    ).scalar_one_or_none()

    drive = DriveSummary(
        device_id=deviceId,
        start_time=startTime,
        end_time=endTime,
        duration_seconds=duration,
        row_count=int(rowCount),
        profile_id=profileId,
    )
    session.add(drive)
    session.flush()
    return drive.id


async def _safeRunAnalysis(
    engine: AsyncEngine,
    driveId: int,
    *,
    ollamaBaseUrl: str,
    ollamaModel: str,
    ollamaTimeoutSeconds: int,
) -> None:
    """Run analysis with error capture — failures log ERROR instead of raising.

    Background tasks must not leak exceptions; the /sync response has already
    returned and no caller is awaiting the task.
    """
    try:
        await runAnalysis(
            engine=engine,
            driveId=driveId,
            ollamaBaseUrl=ollamaBaseUrl,
            ollamaModel=ollamaModel,
            ollamaTimeoutSeconds=ollamaTimeoutSeconds,
            parameters={},
        )
    except Exception as exc:  # noqa: BLE001 — background safety net
        logger.error(
            "Auto-analysis task failed for drive_id=%s: %s",
            driveId, exc, exc_info=True,
        )


async def enqueueAutoAnalysisForSync(
    engine: AsyncEngine,
    deviceId: str,
    connectionLogRows: list[dict[str, Any]],
    *,
    ollamaBaseUrl: str,
    ollamaModel: str,
    ollamaTimeoutSeconds: int = 120,
) -> bool:
    """Kick off non-blocking AI analysis for every completed drive in ``rows``.

    Returns True iff at least one :func:`asyncio.create_task` was scheduled.
    False means: no drive_end in the payload, or the Ollama preflight ping
    failed — either way ``/sync`` is unaffected and returns 200.

    Args:
        engine: AsyncEngine bound to the server database.
        deviceId: Source device id used to scope drive_summary rows.
        connectionLogRows: Raw connection_log dicts from the sync payload.
        ollamaBaseUrl: Ollama base URL (used for both the ping and the
            subsequent /api/chat call inside runAnalysis).
        ollamaModel: Model name passed through to runAnalysis.
        ollamaTimeoutSeconds: Per-analysis timeout passed through.
    """
    boundaries = extractDriveBoundaries(connectionLogRows)
    if not boundaries:
        return False

    if not await pingOllama(ollamaBaseUrl):
        logger.warning(
            "Auto-analysis skipped: Ollama unreachable at %s "
            "(device=%s, drives_pending=%d)",
            ollamaBaseUrl, deviceId, len(boundaries),
        )
        return False

    factory = getAsyncSession(engine)
    async with factory() as session:
        driveIds = await session.run_sync(
            lambda s: [
                _ensureDriveSummary(s, deviceId, start, end)
                for start, end in boundaries
            ],
        )
        await session.commit()

    for driveId in driveIds:
        task = asyncio.create_task(
            _safeRunAnalysis(
                engine=engine,
                driveId=driveId,
                ollamaBaseUrl=ollamaBaseUrl,
                ollamaModel=ollamaModel,
                ollamaTimeoutSeconds=ollamaTimeoutSeconds,
            ),
        )
        _pendingAutoAnalysisTasks.add(task)
        task.add_done_callback(_pendingAutoAnalysisTasks.discard)

    return True


# ---- Public API --------------------------------------------------------------

__all__ = [
    "ALLOWED_CATEGORIES",
    "ANALYSIS_ID_PREFIX",
    "MAX_RECOMMENDATIONS",
    "NO_DATA_MESSAGE",
    "AnalysisResult",
    "DriveNotFound",
    "OllamaHttpFailure",
    "OllamaUnreachable",
    "Recommendation",
    "enqueueAutoAnalysisForSync",
    "extractDriveBoundaries",
    "pingOllama",
    "runAnalysis",
]
