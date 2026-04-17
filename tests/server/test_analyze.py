################################################################################
# File Name: test_analyze.py
# Purpose/Description: Tests for the POST /api/v1/analyze endpoint focusing on
#                      request validation, auth, and envelope shape. Deep
#                      service-layer coverage (analytics wiring, Ollama error
#                      mapping, persistence) lives in test_analyze_real.py.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-147 — stub AI endpoint
# 2026-04-16    | Ralph Agent  | US-CMP-005 — drop stub-only invariants; keep
#               |              | request-validation and auth tests that still
#               |              | apply to the real endpoint.
# ================================================================================
################################################################################

"""
Shape / auth tests for ``src/server/api/analyze.py``.

Three concerns covered here:

1. **Pydantic request validation** — shape, required fields.
2. **Route auth** — inherits ``requireApiKey`` like /sync; missing/invalid
   keys must 401.
3. **Body-level 422** — missing required fields travel through the full stack.

End-to-end coverage (analytics wiring, Ollama error mapping, DB persistence)
lives in ``test_analyze_real.py`` (US-CMP-005).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


# ==============================================================================
# Helpers
# ==============================================================================


def _makeSettings(apiKey: str = "valid-key"):
    from src.server.config import Settings

    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=apiKey,
    )


def _buildAppForRouteTests(apiKey: str = "valid-key"):
    """Build a bare FastAPI app (no engine) for auth / validation tests."""
    from src.server.api.app import createApp

    settings = _makeSettings(apiKey=apiKey)
    app = createApp(settings=settings)
    app.state.engine = None  # no engine for auth / validation tests
    return app


def _validRequest(driveId: int = 42) -> dict:
    return {
        "drive_id": driveId,
        "parameters": {"focus": ["RPM", "MAF"]},
    }


# ==============================================================================
# 1) Pydantic request validation
# ==============================================================================


class TestAnalyzeRequestValidation:
    """The request model rejects malformed payloads before any DB work."""

    def test_validPayload_parsesWithoutError(self):
        from src.server.api.analyze import AnalyzeRequest

        model = AnalyzeRequest.model_validate(_validRequest())
        assert model.drive_id == 42
        assert model.parameters == {"focus": ["RPM", "MAF"]}

    def test_missingDriveId_rejected(self):
        from pydantic import ValidationError

        from src.server.api.analyze import AnalyzeRequest

        payload = _validRequest()
        del payload["drive_id"]
        with pytest.raises(ValidationError):
            AnalyzeRequest.model_validate(payload)

    def test_missingParameters_rejected(self):
        from pydantic import ValidationError

        from src.server.api.analyze import AnalyzeRequest

        payload = _validRequest()
        del payload["parameters"]
        with pytest.raises(ValidationError):
            AnalyzeRequest.model_validate(payload)


# ==============================================================================
# 2) Route auth (inherits requireApiKey)
# ==============================================================================


class TestAnalyzeAuth:
    """Auth is enforced by the shared ``requireApiKey`` dependency (US-CMP-002)."""

    def test_missingApiKey_returns401(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post("/api/v1/analyze", json=_validRequest())

        assert response.status_code == 401

    def test_invalidApiKey_returns401(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/analyze",
                json=_validRequest(),
                headers={"X-API-Key": "wrong"},
            )

        assert response.status_code == 401


# ==============================================================================
# 3) Route body validation (through the full stack)
# ==============================================================================


class TestAnalyzeInvalidBody:
    """Malformed body → 422."""

    def test_missingDriveId_returns422(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/analyze",
                json={"parameters": {}},
                headers={"X-API-Key": "valid-key"},
            )
        assert response.status_code == 422

    def test_missingParameters_returns422(self):
        from fastapi.testclient import TestClient

        app = _buildAppForRouteTests()
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/analyze",
                json={"drive_id": 7},
                headers={"X-API-Key": "valid-key"},
            )
        assert response.status_code == 422
