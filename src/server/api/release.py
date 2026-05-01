################################################################################
# File Name: release.py
# Purpose/Description: Release registry endpoints (B-047 US-B).
#                      GET /api/v1/release/current  -- authoritative current
#                          release record, consumed by Pi update-checker (US-C).
#                      GET /api/v1/release/history -- last N appended records
#                          for debugging / rollback context.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial implementation (Sprint 20 US-246)
# ================================================================================
################################################################################

"""Release registry endpoints (B-047 US-B).

Both endpoints are protected -- registered in ``src/server/api/app.py`` with
``dependencies=[Depends(requireApiKey)]`` so a missing or invalid X-API-Key
returns 401 before the handler runs.

GET /api/v1/release/current
    Returns the current release record validated against the US-241
    ``{version, releasedAt, gitHash, description}`` schema. Returns 503
    when no valid record is stamped yet (server is up but undeployed
    -- the Pi update-checker should treat this as 'no update available').

GET /api/v1/release/history
    Returns ``{"releases": [...]}`` -- the last N validated entries from
    ``.deploy-version-history`` (default N=10, configurable via
    ``RELEASE_HISTORY_MAX``). Returns ``{"releases": []}`` when the history
    file is absent (the deploy script has not yet been wired to append).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from src.server.services.release_reader import ReleaseReader

logger = logging.getLogger(__name__)

router = APIRouter()


# ---- Reader resolution (module-level for test patching) ---------------------


def _getReader(request: Request) -> ReleaseReader:
    """Build a ReleaseReader from app.state.settings (patched in tests).

    Lifted to a module-level helper so unit tests can ``patch`` it instead
    of constructing a Settings instance with stub paths.
    """
    settings = getattr(request.app.state, "settings", None)
    return ReleaseReader.fromSettings(settings if settings is not None else object())


# ---- Routes -----------------------------------------------------------------


@router.get("/release/current")
async def getReleaseCurrent(request: Request) -> dict[str, Any]:
    """Return the current release record or 503 when no record is stamped."""
    reader = _getReader(request)
    record = reader.readCurrent()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Release record not available; deploy has not stamped .deploy-version",
        )
    return record


@router.get("/release/history")
async def getReleaseHistory(request: Request) -> dict[str, list[dict]]:
    """Return the last N validated release records as ``{"releases": [...]}``."""
    reader = _getReader(request)
    return {"releases": reader.readHistory()}


__all__ = ["router"]
