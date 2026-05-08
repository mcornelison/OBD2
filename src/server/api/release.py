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
# 2026-05-08    | Rex          | US-297: pruneReleaseHistory helper exposing the
#               |              |   B-047 D4 retention surface for deploy-script /
#               |              |   admin invocation
# ================================================================================
################################################################################

"""Release registry endpoints (B-047 US-B + D4).

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

US-297 / B-047 D4 retention: ``pruneReleaseHistory`` exposes the trail-prune
surface for deploy-time invocation (``deploy-server.sh`` step 5.5 or admin
CLI). The actual retention logic lives in
``src.server.services.release_reader.ReleaseReader.pruneHistory`` -- this
module provides the Settings-aware entry point that mirrors ``_getReader``.
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


# ---- B-047 D4 retention surface (US-297) ------------------------------------


def pruneReleaseHistory(settings: object | None = None) -> int:
    """Enforce B-047 D4 retention on ``.deploy-version-history``.

    Settings-aware entry point intended for deploy-script or admin invocation
    (e.g. ``python -c "from src.server.api.release import pruneReleaseHistory;
    pruneReleaseHistory()"`` after a new release lands). Delegates to
    ``ReleaseReader.pruneHistory`` so unit tests cover the truncation logic
    in one place.

    Args:
        settings: Optional Settings-like object; ``None`` falls back to module
            defaults (resolves the deploy-server.sh-stamped paths against the
            server CWD = project root in production).

    Returns:
        Number of records pruned (0 when the file is below cap or absent).
    """
    reader = ReleaseReader.fromSettings(settings if settings is not None else object())
    return reader.pruneHistory()


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


__all__ = ["pruneReleaseHistory", "router"]
