################################################################################
# File Name: test_release_endpoint.py
# Purpose/Description: Tests for src/server/api/release.py (B-047 US-B / US-246).
#                      Covers GET /api/v1/release/current happy path + 503 +
#                      auth, GET /api/v1/release/history list shape + empty +
#                      auth.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial TDD tests for US-246 (Sprint 20)
# ================================================================================
################################################################################

"""Endpoint tests for ``/api/v1/release/current`` + ``/api/v1/release/history``.

Mocks ``src.server.api.release._getReader`` so the route runs without touching
the filesystem; uses TestClient + a settings-injected Settings (matches the
test_auth.py + test_health.py patterns).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


# ---- Helpers -----------------------------------------------------------------


VALID_API_KEY = "valid-key"


def _validRecord(version: str = "V0.19.0") -> dict:
    return {
        "version": version,
        "releasedAt": "2026-04-29T14:32:00Z",
        "gitHash": "5025508",
        "theme": "test sprint",
        "description": "Sprint 19 close",
    }


def _buildApp(apiKey: str = VALID_API_KEY):
    """Build a real createApp() instance with Settings carrying ``apiKey``."""
    from src.server.api.app import createApp
    from src.server.config import Settings

    settings = Settings(DATABASE_URL="mysql+aiomysql://stub/stub", API_KEY=apiKey)
    return createApp(settings=settings)


def _stubReader(currentRecord: dict | None = None, historyRecords: list[dict] | None = None) -> MagicMock:
    """Return a MagicMock that mimics the ReleaseReader public surface."""
    reader = MagicMock()
    reader.readCurrent.return_value = currentRecord
    reader.readHistory.return_value = historyRecords or []
    return reader


# ---- /release/current --------------------------------------------------------


class TestReleaseCurrentEndpoint:
    """GET /api/v1/release/current happy + sad paths."""

    def test_validRecord_returns200WithFullPayload(self) -> None:
        from fastapi.testclient import TestClient

        app = _buildApp()
        record = _validRecord()
        with patch(
            "src.server.api.release._getReader",
            return_value=_stubReader(currentRecord=record),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/release/current",
                    headers={"X-API-Key": VALID_API_KEY},
                )

        assert response.status_code == 200
        body = response.json()
        for key in ("version", "releasedAt", "gitHash", "description"):
            assert key in body
        assert body["version"] == record["version"]
        assert body["releasedAt"] == record["releasedAt"]
        assert body["gitHash"] == record["gitHash"]
        assert body["description"] == record["description"]

    def test_missingRecord_returns503(self) -> None:
        from fastapi.testclient import TestClient

        app = _buildApp()
        with patch(
            "src.server.api.release._getReader",
            return_value=_stubReader(currentRecord=None),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/release/current",
                    headers={"X-API-Key": VALID_API_KEY},
                )

        assert response.status_code == 503
        body = response.json()
        assert "detail" in body

    def test_missingApiKey_returns401(self) -> None:
        from fastapi.testclient import TestClient

        app = _buildApp()
        with patch(
            "src.server.api.release._getReader",
            return_value=_stubReader(currentRecord=_validRecord()),
        ):
            with TestClient(app) as client:
                response = client.get("/api/v1/release/current")

        assert response.status_code == 401

    def test_invalidApiKey_returns401(self) -> None:
        from fastapi.testclient import TestClient

        app = _buildApp()
        with patch(
            "src.server.api.release._getReader",
            return_value=_stubReader(currentRecord=_validRecord()),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/release/current",
                    headers={"X-API-Key": "wrong-key"},
                )

        assert response.status_code == 401


# ---- /release/history --------------------------------------------------------


class TestReleaseHistoryEndpoint:
    """GET /api/v1/release/history shape + empty + auth."""

    def test_returns200WithReleasesList(self) -> None:
        from fastapi.testclient import TestClient

        app = _buildApp()
        records = [
            _validRecord("V0.16.0"),
            _validRecord("V0.17.0"),
            _validRecord("V0.18.0"),
        ]
        with patch(
            "src.server.api.release._getReader",
            return_value=_stubReader(historyRecords=records),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/release/history",
                    headers={"X-API-Key": VALID_API_KEY},
                )

        assert response.status_code == 200
        body = response.json()
        assert "releases" in body
        assert isinstance(body["releases"], list)
        assert len(body["releases"]) == 3
        assert [r["version"] for r in body["releases"]] == ["V0.16.0", "V0.17.0", "V0.18.0"]

    def test_emptyHistory_returns200WithEmptyList(self) -> None:
        from fastapi.testclient import TestClient

        app = _buildApp()
        with patch(
            "src.server.api.release._getReader",
            return_value=_stubReader(historyRecords=[]),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/release/history",
                    headers={"X-API-Key": VALID_API_KEY},
                )

        assert response.status_code == 200
        assert response.json() == {"releases": []}

    def test_missingApiKey_returns401(self) -> None:
        from fastapi.testclient import TestClient

        app = _buildApp()
        with patch(
            "src.server.api.release._getReader",
            return_value=_stubReader(historyRecords=[_validRecord()]),
        ):
            with TestClient(app) as client:
                response = client.get("/api/v1/release/history")

        assert response.status_code == 401


# ---- Reader resolution -------------------------------------------------------


class TestReaderResolution:
    """_getReader builds a reader from app.state.settings (no patching)."""

    def test_buildsReaderFromAppStateSettings(self, tmp_path) -> None:
        """End-to-end: with no mocks, the reader reads the actual configured paths."""
        import json as jsonmod

        from fastapi.testclient import TestClient

        from src.server.api.app import createApp
        from src.server.config import Settings

        currentPath = tmp_path / ".deploy-version"
        currentPath.write_text(jsonmod.dumps(_validRecord("V0.20.0")), encoding="utf-8")

        settings = Settings(
            DATABASE_URL="mysql+aiomysql://stub/stub",
            API_KEY=VALID_API_KEY,
            RELEASE_VERSION_PATH=str(currentPath),
            RELEASE_HISTORY_PATH=str(tmp_path / "missing-history.jsonl"),
        )
        app = createApp(settings=settings)
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/release/current",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert response.status_code == 200
        assert response.json()["version"] == "V0.20.0"
