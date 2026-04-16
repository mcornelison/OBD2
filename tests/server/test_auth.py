################################################################################
# File Name: test_auth.py
# Purpose/Description: Tests for the API key authentication dependency
#                      (US-CMP-002). Verifies missing/invalid/valid key handling,
#                      constant-time comparison, and /health exemption.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-CMP-002 — API key auth
# ================================================================================
################################################################################

"""
Tests for ``src/server/api/auth.py`` — the ``requireApiKey`` FastAPI dependency.

Covers:
    - Missing X-API-Key header → 401 with detail "Missing API key"
    - Invalid X-API-Key value   → 401 with detail "Invalid API key"
    - Valid   X-API-Key value   → 200 (protected route passes through)
    - Empty configured API_KEY  → fail-closed (every request is invalid)
    - hmac.compare_digest is used for the comparison (constant-time)
    - GET /api/v1/health remains reachable without any X-API-Key header
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


# ---- Helpers ------------------------------------------------------------------


def _makeSettings(apiKey: str):
    """Construct a Settings instance with DATABASE_URL stub + given API_KEY."""
    from src.server.config import Settings

    return Settings(DATABASE_URL="mysql+aiomysql://stub/stub", API_KEY=apiKey)


def _buildAppWithProtectedRoute(apiKey: str = "valid-key"):
    """
    Build a FastAPI app with:
        - The real /api/v1/health router (public).
        - A test /api/v1/protected router that requires ``requireApiKey``.

    This lets us exercise the auth dependency end-to-end via TestClient without
    waiting for real protected endpoints (US-CMP-004 /sync, US-147 /analyze).
    """
    from fastapi import APIRouter, Depends

    from src.server.api.app import API_PREFIX, createApp
    from src.server.api.auth import requireApiKey

    settings = _makeSettings(apiKey)
    app = createApp(settings=settings)

    testRouter = APIRouter()

    @testRouter.get("/protected")
    async def _protected() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(
        testRouter,
        prefix=API_PREFIX,
        dependencies=[Depends(requireApiKey)],
    )
    return app


# ---- Missing-key tests --------------------------------------------------------


class TestMissingKey:
    """Absence of X-API-Key header → 401 with detail 'Missing API key'."""

    def test_missingHeaderReturns401(self):
        from fastapi.testclient import TestClient

        app = _buildAppWithProtectedRoute()
        with TestClient(app) as client:
            response = client.get("/api/v1/protected")

        assert response.status_code == 401

    def test_missingHeaderDetailIsMissingApiKey(self):
        from fastapi.testclient import TestClient

        app = _buildAppWithProtectedRoute()
        with TestClient(app) as client:
            response = client.get("/api/v1/protected")

        assert response.json() == {"detail": "Missing API key"}


# ---- Invalid-key tests --------------------------------------------------------


class TestInvalidKey:
    """Wrong X-API-Key value → 401 with detail 'Invalid API key'."""

    def test_wrongKeyReturns401(self):
        from fastapi.testclient import TestClient

        app = _buildAppWithProtectedRoute(apiKey="valid-key")
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/protected",
                headers={"X-API-Key": "wrong-key"},
            )

        assert response.status_code == 401

    def test_wrongKeyDetailIsInvalidApiKey(self):
        from fastapi.testclient import TestClient

        app = _buildAppWithProtectedRoute(apiKey="valid-key")
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/protected",
                headers={"X-API-Key": "wrong-key"},
            )

        assert response.json() == {"detail": "Invalid API key"}

    def test_emptyConfiguredKeyRejectsAnyProvidedKey(self):
        """
        If the server has no API_KEY configured, *any* non-empty header value
        must be rejected as invalid. Fail-closed is required so a missing
        server config cannot silently open the server — the short-circuit on
        ``not expectedKey`` must fire before ``compare_digest`` is called.
        """
        from fastapi.testclient import TestClient

        app = _buildAppWithProtectedRoute(apiKey="")
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/protected",
                headers={"X-API-Key": "anything"},
            )

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid API key"}


# ---- Valid-key tests ----------------------------------------------------------


class TestValidKey:
    """Correct X-API-Key value → dependency passes, route returns 200."""

    def test_validKeyReturns200(self):
        from fastapi.testclient import TestClient

        app = _buildAppWithProtectedRoute(apiKey="secret-42")
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/protected",
                headers={"X-API-Key": "secret-42"},
            )

        assert response.status_code == 200
        assert response.json() == {"ok": True}


# ---- Constant-time comparison tests ------------------------------------------


class TestConstantTimeComparison:
    """``hmac.compare_digest`` must be used (grounding ref, server spec §2.1)."""

    def test_compareDigestIsInvokedOnValidKey(self):
        # Wrap the real function so we can verify the call while letting it
        # behave normally.
        import hmac

        from fastapi.testclient import TestClient

        realCompare = hmac.compare_digest

        with patch(
            "src.server.api.auth.compare_digest",
            side_effect=realCompare,
        ) as mockCompare:
            app = _buildAppWithProtectedRoute(apiKey="token-abc")
            with TestClient(app) as client:
                client.get(
                    "/api/v1/protected",
                    headers={"X-API-Key": "token-abc"},
                )

        assert mockCompare.called, "auth.py must use hmac.compare_digest"
        # The call should compare the header value against the configured key.
        # Accept either argument order (implementation detail).
        args, _ = mockCompare.call_args
        assert set(args) == {"token-abc", "token-abc"}


# ---- /health exemption tests --------------------------------------------------


class TestHealthExempt:
    """GET /api/v1/health remains reachable without any X-API-Key header."""

    def test_healthWithoutKeyReturns200(self):
        from fastapi.testclient import TestClient

        # Patch the health internals so the route doesn't hit a real DB/Ollama.
        app = _buildAppWithProtectedRoute(apiKey="some-key")
        with (
            patch("src.server.api.health._checkMysql", new=AsyncMock(return_value="up")),
            patch("src.server.api.health._checkOllama", new=AsyncMock(return_value="up")),
            patch("src.server.api.health._getLastSync", new=AsyncMock(return_value=None)),
            patch(
                "src.server.api.health._getLastAnalysis",
                new=AsyncMock(return_value=None),
            ),
            patch("src.server.api.health._getDriveCount", new=AsyncMock(return_value=0)),
        ):
            import time

            app.state.startTime = time.time()
            with TestClient(app) as client:
                response = client.get("/api/v1/health")  # no X-API-Key header

        assert response.status_code == 200
