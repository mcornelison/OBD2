################################################################################
# File Name: test_server_ping_route.py
# Purpose/Description: Proves pi.homeNetwork.serverPingPath names a GET route the
#                      server application actually registers (US-776-a).
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-30    | Rex          | Initial implementation for US-776-a
# ================================================================================
################################################################################

"""
The shutdown reachability check must GET a route that exists on the server.

``serverPingPath`` shipped as ``/api/v1/ping`` -- a 404 -- so
:meth:`HomeNetworkDetector.isServerReachable` returned False on every
shutdown and the drain was skipped as "server unavailable".  The unit tests
never caught it because they mock the HTTP opener, so any path "worked".

These tests read the REAL route table from
:func:`src.server.api.app.createApp` (no mock, no hardcoded path list) and
match the configured path against it the way Starlette routes a request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.routing import Match

from src.common.config.validator import DEFAULTS
from src.pi.network import HomeNetworkDetector
from src.server.api.app import createApp

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "config.json"
MISSING_ROUTE = "/api/v1/ping"


def _shippedPingPath() -> str:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        config: dict[str, Any] = json.load(handle)
    return str(config["pi"]["homeNetwork"]["serverPingPath"])


def _isRegisteredGetRoute(app: FastAPI, path: str) -> bool:
    """True when a GET to ``path`` fully matches a route on ``app``.

    ``Match.FULL`` requires both the path and the method to match;
    a path served only by POST comes back ``Match.PARTIAL``.
    """
    scope = {
        "type": "http",
        "path": path,
        "method": "GET",
        "root_path": "",
        "query_string": b"",
        "headers": [],
    }
    return any(route.matches(scope)[0] == Match.FULL for route in app.routes)


def _assertServerGetRoute(path: str) -> None:
    app = createApp()
    assert _isRegisteredGetRoute(app, path), (
        f"pi.homeNetwork.serverPingPath {path!r} is not a GET route registered "
        f"by the server app -- the reachability check would always see a 404"
    )


@pytest.fixture
def server() -> FastAPI:
    return createApp()


class TestServerPingRouteIsReal:
    def test_shippedServerPingPath_isRegisteredServerGetRoute(self) -> None:
        """
        Given: config.json as shipped
        When: its serverPingPath is matched against the server route table
        Then: a GET route fully matches it
        """
        _assertServerGetRoute(_shippedPingPath())

    def test_missingRoute_failsAndNamesThePath(self) -> None:
        """
        Given: serverPingPath set to the route that does not exist
        When: the same route check runs
        Then: it fails, and the message names the missing route
        """
        with pytest.raises(AssertionError) as excInfo:
            _assertServerGetRoute(MISSING_ROUTE)

        assert MISSING_ROUTE in str(excInfo.value)

    def test_postOnlyRoute_isNotAGetRoute(self, server: FastAPI) -> None:
        """A path the server serves only by POST must not pass as a ping route."""
        assert _isRegisteredGetRoute(server, "/api/v1/sync") is False


class TestServerPingPathDefaultsAgree:
    def test_validatorDefault_isRegisteredServerGetRoute(self, server: FastAPI) -> None:
        defaultPath = DEFAULTS["pi.homeNetwork.serverPingPath"]

        assert defaultPath == _shippedPingPath()
        assert _isRegisteredGetRoute(server, defaultPath)

    def test_detectorFallback_matchesShippedPath(self) -> None:
        """With no serverPingPath configured, the detector GETs the shipped path."""
        requested: list[str] = []

        class _Response:
            status = 200

            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        def opener(req: Any, **kwargs: Any) -> _Response:
            requested.append(req.full_url)
            return _Response()

        detector = HomeNetworkDetector(
            {"pi": {"homeNetwork": {}, "companionService": {"baseUrl": "http://srv"}}},
            httpOpener=opener,
            apiKey="k",
        )

        assert detector.isServerReachable() is True
        assert requested == [f"http://srv{_shippedPingPath()}"]
