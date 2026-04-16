################################################################################
# File Name: test_health.py
# Purpose/Description: Tests for the server /api/v1/health endpoint (US-CMP-008)
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-CMP-008 — GET /health
# ================================================================================
################################################################################

"""
Tests for ``src/server/api/health.py`` — the component-status health endpoint.

Covers:
    - Pure helpers (status computation, uptime formatting) — no fastapi needed
    - Route shape (path, method, JSON keys) via TestClient — requires fastapi
    - Status matrix (healthy / degraded / unhealthy) — mocks component checks
    - No-auth behaviour on /health — exempt from API key middleware

Tests that need ``fastapi`` / ``httpx`` skip cleanly when the server deps are
not installed in the developer venv (same pattern used for ``aiomysql``).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

# ``src/server/api/health.py`` imports fastapi at module scope; skip the whole
# suite when server deps aren't installed in the developer venv (same policy as
# ``tests/server/test_db_models.py`` uses for aiomysql).
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

# ---- Pure helper tests (no fastapi needed) -----------------------------------


class TestStatusComputation:
    """_computeStatus should follow spec §1.3 status logic."""

    def test_mysqlDownIsUnhealthy(self):
        from src.server.api.health import _computeStatus

        assert _computeStatus("down", "up") == "unhealthy"
        assert _computeStatus("down", "down") == "unhealthy"

    def test_mysqlUpAndOllamaUpIsHealthy(self):
        from src.server.api.health import _computeStatus

        assert _computeStatus("up", "up") == "healthy"

    def test_mysqlUpButOllamaDownIsDegraded(self):
        from src.server.api.health import _computeStatus

        assert _computeStatus("up", "down") == "degraded"
        assert _computeStatus("up", "stub") == "degraded"


class TestUptimeFormatting:
    """_formatUptime renders seconds as ``Nd Nh Nm`` per spec example."""

    def test_zeroSeconds(self):
        from src.server.api.health import _formatUptime

        assert _formatUptime(0) == "0d 0h 0m"

    def test_minutesOnly(self):
        from src.server.api.health import _formatUptime

        assert _formatUptime(5 * 60) == "0d 0h 5m"

    def test_hoursAndMinutes(self):
        from src.server.api.health import _formatUptime

        assert _formatUptime(4 * 3600 + 30 * 60) == "0d 4h 30m"

    def test_daysHoursMinutes(self):
        from src.server.api.health import _formatUptime

        assert _formatUptime(2 * 86400 + 4 * 3600 + 30 * 60) == "2d 4h 30m"

    def test_secondsTruncatedNotRounded(self):
        from src.server.api.health import _formatUptime

        # 59 seconds is still 0 minutes
        assert _formatUptime(59) == "0d 0h 0m"


# ---- Endpoint tests (require fastapi + httpx) --------------------------------


def _buildTestApp():
    """
    Build an app wired for testing with component checks overridden.

    Overrides:
        - ``_checkMysql`` / ``_checkOllama`` — return caller-supplied values
        - ``_getLastSync`` / ``_getLastAnalysis`` / ``_getDriveCount``
          — return fixed values
    Returns an app with ``app.state.startTime`` set so uptime is deterministic.
    """
    from src.server.api.app import createApp

    app = createApp()
    app.state.startTime = time.time() - (2 * 86400 + 4 * 3600 + 30 * 60)
    app.state.engine = None
    return app


class TestHealthEndpointShape:
    """GET /api/v1/health returns the JSON envelope defined in spec §1.3."""

    def _makeClient(self, mysql="up", ollama="up", lastSync=None, lastAnalysis=None, driveCount=0):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = _buildTestApp()

        # Patch the in-router helpers so the route executes without DB/HTTP.
        with (
            patch("src.server.api.health._checkMysql", new=AsyncMock(return_value=mysql)),
            patch("src.server.api.health._checkOllama", new=AsyncMock(return_value=ollama)),
            patch("src.server.api.health._getLastSync", new=AsyncMock(return_value=lastSync)),
            patch(
                "src.server.api.health._getLastAnalysis",
                new=AsyncMock(return_value=lastAnalysis),
            ),
            patch(
                "src.server.api.health._getDriveCount",
                new=AsyncMock(return_value=driveCount),
            ),
        ):
            with TestClient(app) as client:
                yield client

    def test_pathIsApiV1Health(self):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = _buildTestApp()
        with (
            patch("src.server.api.health._checkMysql", new=AsyncMock(return_value="up")),
            patch("src.server.api.health._checkOllama", new=AsyncMock(return_value="up")),
            patch("src.server.api.health._getLastSync", new=AsyncMock(return_value=None)),
            patch("src.server.api.health._getLastAnalysis", new=AsyncMock(return_value=None)),
            patch("src.server.api.health._getDriveCount", new=AsyncMock(return_value=0)),
        ):
            with TestClient(app) as client:
                response = client.get("/api/v1/health")

        assert response.status_code == 200

    def test_responseContainsAllRequiredKeys(self):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = _buildTestApp()
        with (
            patch("src.server.api.health._checkMysql", new=AsyncMock(return_value="up")),
            patch("src.server.api.health._checkOllama", new=AsyncMock(return_value="up")),
            patch(
                "src.server.api.health._getLastSync",
                new=AsyncMock(return_value="2026-04-16T12:00:00"),
            ),
            patch(
                "src.server.api.health._getLastAnalysis",
                new=AsyncMock(return_value="2026-04-16T12:30:00"),
            ),
            patch("src.server.api.health._getDriveCount", new=AsyncMock(return_value=42)),
        ):
            with TestClient(app) as client:
                body = client.get("/api/v1/health").json()

        # spec §1.3 keys
        for key in ("status", "version", "components", "lastSync", "lastAnalysis", "driveCount", "uptime"):
            assert key in body, f"missing key: {key}"
        for component in ("api", "mysql", "ollama"):
            assert component in body["components"], f"missing component: {component}"

    def test_responseBodyValuesFromMocks(self):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = _buildTestApp()
        with (
            patch("src.server.api.health._checkMysql", new=AsyncMock(return_value="up")),
            patch("src.server.api.health._checkOllama", new=AsyncMock(return_value="up")),
            patch(
                "src.server.api.health._getLastSync",
                new=AsyncMock(return_value="2026-04-16T12:00:00"),
            ),
            patch("src.server.api.health._getLastAnalysis", new=AsyncMock(return_value=None)),
            patch("src.server.api.health._getDriveCount", new=AsyncMock(return_value=7)),
        ):
            with TestClient(app) as client:
                body = client.get("/api/v1/health").json()

        assert body["status"] == "healthy"
        assert body["components"]["api"] == "up"
        assert body["components"]["mysql"] == "up"
        assert body["components"]["ollama"] == "up"
        assert body["lastSync"] == "2026-04-16T12:00:00"
        assert body["lastAnalysis"] is None
        assert body["driveCount"] == 7
        assert body["uptime"] == "2d 4h 30m"
        assert body["version"]  # non-empty


class TestHealthStatusMatrix:
    """End-to-end status computation through the HTTP layer."""

    @pytest.mark.parametrize(
        "mysql,ollama,expected",
        [
            ("up", "up", "healthy"),
            ("up", "down", "degraded"),
            ("up", "stub", "degraded"),
            ("down", "up", "unhealthy"),
            ("down", "down", "unhealthy"),
        ],
    )
    def test_statusMatrix(self, mysql, ollama, expected):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = _buildTestApp()
        with (
            patch("src.server.api.health._checkMysql", new=AsyncMock(return_value=mysql)),
            patch("src.server.api.health._checkOllama", new=AsyncMock(return_value=ollama)),
            patch("src.server.api.health._getLastSync", new=AsyncMock(return_value=None)),
            patch("src.server.api.health._getLastAnalysis", new=AsyncMock(return_value=None)),
            patch("src.server.api.health._getDriveCount", new=AsyncMock(return_value=0)),
        ):
            with TestClient(app) as client:
                body = client.get("/api/v1/health").json()

        assert body["status"] == expected


class TestHealthNoAuth:
    """/health must be reachable without any API key header (spec §2.1)."""

    def test_noApiKeyHeaderStillReturns200(self):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = _buildTestApp()
        with (
            patch("src.server.api.health._checkMysql", new=AsyncMock(return_value="up")),
            patch("src.server.api.health._checkOllama", new=AsyncMock(return_value="up")),
            patch("src.server.api.health._getLastSync", new=AsyncMock(return_value=None)),
            patch("src.server.api.health._getLastAnalysis", new=AsyncMock(return_value=None)),
            patch("src.server.api.health._getDriveCount", new=AsyncMock(return_value=0)),
        ):
            with TestClient(app) as client:
                # No X-API-Key / Authorization headers supplied.
                response = client.get("/api/v1/health")

        assert response.status_code == 200


# ---- Component-check helpers: failure modes ----------------------------------


class TestCheckMysql:
    """_checkMysql returns 'down' on any connection failure."""

    def test_noneEngineReturnsDown(self):
        pytest.importorskip("sqlalchemy")
        import asyncio

        from src.server.api.health import _checkMysql

        result = asyncio.run(_checkMysql(None))
        assert result == "down"

    def test_exceptionFromEngineReturnsDown(self):
        pytest.importorskip("sqlalchemy")
        import asyncio
        from unittest.mock import MagicMock

        from src.server.api.health import _checkMysql

        engine = MagicMock()
        engine.connect.side_effect = RuntimeError("boom")

        result = asyncio.run(_checkMysql(engine))
        assert result == "down"


class TestCheckOllama:
    """_checkOllama returns 'up' only on HTTP 200, 'down' otherwise."""

    def test_emptyUrlReturnsDown(self):
        pytest.importorskip("httpx")
        import asyncio

        from src.server.api.health import _checkOllama

        assert asyncio.run(_checkOllama("")) == "down"

    def test_timeoutReturnsDown(self):
        pytest.importorskip("httpx")
        import asyncio

        import httpx

        from src.server.api import health

        async def _boom(*args, **kwargs):
            raise httpx.ConnectError("no route")

        with patch.object(httpx.AsyncClient, "get", new=_boom):
            result = asyncio.run(health._checkOllama("http://localhost:11434"))
        assert result == "down"
