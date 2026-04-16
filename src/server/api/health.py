################################################################################
# File Name: health.py
# Purpose/Description: GET /api/v1/health endpoint — component status, last-sync
#                      / last-analysis markers, drive count, uptime. No auth.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-008 — router,
#               |              | component checks, status logic, uptime format
# ================================================================================
################################################################################

"""
Health endpoint for the Eclipse OBD-II companion server.

Registers a FastAPI router that exposes ``GET /api/v1/health`` (when
included in the app under prefix ``/api/v1``).  The response envelope matches
server spec §1.3::

    {
        "status": "healthy | degraded | unhealthy",
        "version": "1.0.0",
        "components": { "api": "up", "mysql": "up|down", "ollama": "up|down|stub" },
        "lastSync": null,
        "lastAnalysis": null,
        "driveCount": 0,
        "uptime": "2d 4h 30m"
    }

Status logic:
    * ``mysql == "down"`` → ``unhealthy``
    * ``mysql == "up"`` and ``ollama == "up"`` → ``healthy``
    * otherwise (mysql up, ollama issues) → ``degraded``

The endpoint is intentionally **public** (no API key required) per spec §2.1
so operators can probe status without credentials.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.server.api.app import APP_VERSION
from src.server.db.connection import getAsyncSession
from src.server.db.models import AnalysisHistory, DriveSummary, SyncHistory

logger = logging.getLogger(__name__)

# ---- Constants ---------------------------------------------------------------

OLLAMA_HEALTH_TIMEOUT_SECONDS = 2.0
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60

router = APIRouter()


# ---- Pure helpers ------------------------------------------------------------


def _computeStatus(mysql: str, ollama: str) -> str:
    """
    Roll component states up into an overall status string.

    Args:
        mysql: ``"up"`` or ``"down"``.
        ollama: ``"up"``, ``"down"``, or ``"stub"``.

    Returns:
        ``"healthy"``, ``"degraded"``, or ``"unhealthy"``.
    """
    if mysql != "up":
        return "unhealthy"
    if ollama != "up":
        return "degraded"
    return "healthy"


def _formatUptime(seconds: float) -> str:
    """
    Format a duration in seconds as ``"Xd Yh Zm"``.

    Seconds are truncated (not rounded) — sub-minute runs render as ``0m``.
    """
    total = max(0, int(seconds))
    days, remainder = divmod(total, SECONDS_PER_DAY)
    hours, remainder = divmod(remainder, SECONDS_PER_HOUR)
    minutes = remainder // SECONDS_PER_MINUTE
    return f"{days}d {hours}h {minutes}m"


# ---- Component checks --------------------------------------------------------


async def _checkMysql(engine: Any) -> str:
    """
    Return ``"up"`` if a trivial ``SELECT 1`` succeeds, ``"down"`` otherwise.

    ``engine`` may be ``None`` (e.g. when the app was constructed without a
    lifespan for unit tests) — treated as ``down``.
    """
    if engine is None:
        return "down"
    try:
        async with engine.connect() as conn:
            await conn.execute(select(1))
        return "up"
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("mysql health check failed: %s", exc)
        return "down"
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        logger.warning("mysql health check unexpected error: %s", exc)
        return "down"


async def _checkOllama(baseUrl: str) -> str:
    """
    Return ``"up"`` when Ollama root responds 200, ``"down"`` otherwise.

    Uses a short timeout so a slow or missing Ollama can't stall the
    health endpoint.
    """
    if not baseUrl:
        return "down"
    url = baseUrl.rstrip("/") + "/"
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_HEALTH_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
        return "up" if response.status_code == 200 else "down"
    except (httpx.HTTPError, OSError) as exc:
        logger.debug("ollama health check failed: %s", exc)
        return "down"
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        logger.debug("ollama health check unexpected error: %s", exc)
        return "down"


# ---- Data probes -------------------------------------------------------------


async def _getLastSync(engine: Any) -> str | None:
    """Return the most-recent ``sync_history.completed_at`` as ISO text."""
    if engine is None:
        return None
    try:
        factory = getAsyncSession(engine)
        async with factory() as session:
            result = await session.execute(
                select(SyncHistory.completed_at)
                .where(SyncHistory.completed_at.isnot(None))
                .order_by(SyncHistory.completed_at.desc())
                .limit(1)
            )
            row = result.first()
            return row[0].isoformat() if row and row[0] is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("lastSync probe failed: %s", exc)
        return None


async def _getLastAnalysis(engine: Any) -> str | None:
    """Return the most-recent ``analysis_history.completed_at`` as ISO text."""
    if engine is None:
        return None
    try:
        factory = getAsyncSession(engine)
        async with factory() as session:
            result = await session.execute(
                select(AnalysisHistory.completed_at)
                .where(AnalysisHistory.completed_at.isnot(None))
                .order_by(AnalysisHistory.completed_at.desc())
                .limit(1)
            )
            row = result.first()
            return row[0].isoformat() if row and row[0] is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("lastAnalysis probe failed: %s", exc)
        return None


async def _getDriveCount(engine: Any) -> int:
    """Return ``COUNT(*)`` from ``drive_summary`` (0 on error / missing engine)."""
    if engine is None:
        return 0
    try:
        factory = getAsyncSession(engine)
        async with factory() as session:
            result = await session.execute(select(func.count(DriveSummary.id)))
            count = result.scalar_one()
            return int(count) if count is not None else 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("driveCount probe failed: %s", exc)
        return 0


# ---- Route -------------------------------------------------------------------


@router.get("/health")
async def getHealth(request: Request) -> dict[str, Any]:
    """
    Return component-level health status for the server.

    Pulls ``engine``, ``settings``, and ``startTime`` from ``app.state`` when
    available; each is optional so the endpoint also works on a bare app
    used in unit tests.
    """
    state = request.app.state
    engine = getattr(state, "engine", None)
    settings = getattr(state, "settings", None)
    startTime = getattr(state, "startTime", None)

    ollamaBaseUrl = getattr(settings, "OLLAMA_BASE_URL", "") if settings else ""

    mysql = await _checkMysql(engine)
    ollama = await _checkOllama(ollamaBaseUrl)

    lastSync = await _getLastSync(engine)
    lastAnalysis = await _getLastAnalysis(engine)
    driveCount = await _getDriveCount(engine)

    uptimeSeconds = (time.time() - startTime) if startTime else 0.0

    return {
        "status": _computeStatus(mysql, ollama),
        "version": APP_VERSION,
        "components": {
            "api": "up",
            "mysql": mysql,
            "ollama": ollama,
        },
        "lastSync": lastSync,
        "lastAnalysis": lastAnalysis,
        "driveCount": driveCount,
        "uptime": _formatUptime(uptimeSeconds),
    }


# ---- Public API --------------------------------------------------------------

__all__ = ["router"]
