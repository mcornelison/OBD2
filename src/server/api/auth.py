################################################################################
# File Name: auth.py
# Purpose/Description: API key authentication dependency for protected FastAPI
#                      routers. Extracts X-API-Key header and compares against
#                      the configured shared secret via hmac.compare_digest.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-002 —
#               |              | requireApiKey dependency, constant-time compare
# ================================================================================
################################################################################

"""
API key authentication for the Eclipse OBD-II companion server.

Provides the :func:`requireApiKey` FastAPI dependency which enforces the
``X-API-Key`` header against the configured ``API_KEY`` secret from
:class:`src.server.config.Settings`.

Usage — attach to any router that must be authenticated (spec §2.1):

    from fastapi import Depends
    from src.server.api.auth import requireApiKey

    app.include_router(
        syncRouter,
        prefix="/api/v1",
        dependencies=[Depends(requireApiKey)],
    )

``GET /api/v1/health`` is **intentionally** registered without this dependency
and remains reachable without any key, so operators can probe status without
credentials.

Constant-time comparison: this module uses :func:`hmac.compare_digest` to
avoid timing side-channels that a naive ``==`` comparison would leak.
"""

from __future__ import annotations

from hmac import compare_digest

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

# ---- Constants ---------------------------------------------------------------

API_KEY_HEADER_NAME = "X-API-Key"
MISSING_KEY_DETAIL = "Missing API key"
INVALID_KEY_DETAIL = "Invalid API key"

# ``auto_error=False`` hands us ``None`` when the header is absent so we can
# emit our own "Missing API key" 401 (FastAPI's default would be a 403).
_apiKeyHeaderScheme = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


# ---- Dependency --------------------------------------------------------------


async def requireApiKey(
    request: Request,
    apiKey: str | None = Security(_apiKeyHeaderScheme),
) -> None:
    """
    Enforce the ``X-API-Key`` header against the configured server secret.

    Args:
        request: The incoming request. Used to read ``app.state.settings``
            so tests can inject a :class:`Settings` instance without touching
            environment variables.
        apiKey: Value of the ``X-API-Key`` header, or ``None`` when absent.

    Raises:
        HTTPException(401, "Missing API key"): when the header is absent.
        HTTPException(401, "Invalid API key"): when the header does not
            match, or when the server has no ``API_KEY`` configured (fail-
            closed: a missing server config must not silently accept any key).
    """
    if apiKey is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=MISSING_KEY_DETAIL,
        )

    settings = getattr(request.app.state, "settings", None)
    expectedKey = getattr(settings, "API_KEY", "") or ""

    # Fail-closed when the server has no key configured — prevents an empty
    # string header from silently authenticating via ``compare_digest("", "")``
    # returning True.
    if not expectedKey or not compare_digest(apiKey, expectedKey):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_KEY_DETAIL,
        )


# ---- Public API --------------------------------------------------------------

__all__ = [
    "API_KEY_HEADER_NAME",
    "INVALID_KEY_DETAIL",
    "MISSING_KEY_DETAIL",
    "requireApiKey",
]
