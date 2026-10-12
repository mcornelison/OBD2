################################################################################
# File Name: test_probe_server.py
# Purpose/Description: US-776-d -- HomeNetworkDetector.probeServer() returns a
#                      ProbeResult(status, error) that tells a misconfigured
#                      probe (404/405/401/403) from a down server (connection
#                      error, timeout, 5xx); isServerReachable() stays the bool
#                      2xx-of-probeServer() its callers already use.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-01    | Rex          | Initial -- US-776-d probeServer sibling (Atlas
#               |              | ruling 4)
# ================================================================================
################################################################################
"""Tests for :meth:`HomeNetworkDetector.probeServer` and :class:`ProbeResult`."""

from __future__ import annotations

import io
import urllib.error
from collections.abc import Callable
from typing import Any

import pytest

from src.pi.network.home_detector import (
    HomeNetworkDetector,
    HomeNetworkState,
    ProbeResult,
)

_BASE_URL = "http://10.27.27.10:8000"
_PATH = "/api/v1/health"


def _config(baseUrl: str = _BASE_URL) -> dict[str, Any]:
    return {
        "pi": {
            "homeNetwork": {
                "ssid": "DeathStarWiFi",
                "subnet": "10.27.27.0/24",
                "pingTimeoutSeconds": 3,
                "serverPingPath": _PATH,
            },
            "companionService": {"baseUrl": baseUrl},
        },
    }


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _httpError(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url=f"{_BASE_URL}{_PATH}", code=code, msg="err", hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )


def _detector(
    opener: Callable[..., Any],
    *,
    ssid: str | None = "DeathStarWiFi",
    ips: list[str] | None = None,
    baseUrl: str = _BASE_URL,
) -> HomeNetworkDetector:
    return HomeNetworkDetector(
        _config(baseUrl),
        ssidReader=lambda: ssid,
        ipReader=lambda: ["10.27.27.28"] if ips is None else ips,
        httpOpener=opener,
        apiKey="test-key",
    )


def _returning(status: int) -> Callable[..., Any]:
    def opener(_req: Any, timeout: float) -> _Response:
        return _Response(status)

    return opener


def _raising(exc: BaseException) -> Callable[..., Any]:
    def opener(_req: Any, timeout: float) -> _Response:
        raise exc

    return opener


# =============================================================================
# Classification (Atlas ruling 4)
# =============================================================================


class TestProbeClassification:

    @pytest.mark.parametrize("status", [200, 204])
    def test_2xx_isReachable_notMisconfigured(self, status: int) -> None:
        result = _detector(_returning(status)).probeServer()

        assert result == ProbeResult(status=status, error=None)
        assert result.isReachable is True
        assert result.isMisconfigured is False

    @pytest.mark.parametrize("status", [404, 405, 401, 403])
    def test_routeOrKeyRejected_isMisconfigured(self, status: int) -> None:
        """
        Given: the server answers the probe with 404/405/401/403
        When: probeServer() runs
        Then: the result carries the status and classifies as misconfigured --
            the server is up; the configured route or key is wrong
        """
        result = _detector(_raising(_httpError(status))).probeServer()

        assert result.status == status
        assert result.error
        assert result.isMisconfigured is True
        assert result.isReachable is False

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_5xx_isServerDown_notMisconfigured(self, status: int) -> None:
        result = _detector(_raising(_httpError(status))).probeServer()

        assert result.status == status
        assert result.isMisconfigured is False
        assert result.isReachable is False

    @pytest.mark.parametrize(
        "exc",
        [
            urllib.error.URLError("connection refused"),
            TimeoutError("deadline exceeded"),
            ConnectionResetError("reset by peer"),
            OSError("network unreachable"),
        ],
    )
    def test_connectionErrorOrTimeout_noStatus_serverDown(self, exc: Exception) -> None:
        result = _detector(_raising(exc)).probeServer()

        assert result.status is None
        assert result.error
        assert result.isMisconfigured is False
        assert result.isReachable is False

    def test_noBaseUrl_noHttpCall_noStatus(self) -> None:
        calls: list[object] = []

        def opener(req: Any, timeout: float) -> _Response:
            calls.append(req)
            return _Response(200)

        result = _detector(opener, baseUrl="").probeServer()

        assert calls == []
        assert result.status is None
        assert result.error
        assert result.isReachable is False

    def test_probe_neverRaises_onUnexpectedError(self) -> None:
        result = _detector(_raising(ValueError("bad header"))).probeServer()

        assert result.status is None
        assert "bad header" in (result.error or "")


# =============================================================================
# isServerReachable keeps its bool contract: 2xx of probeServer()
# =============================================================================


class TestIsServerReachableIsTwoXxOfProbe:

    @pytest.mark.parametrize(
        ("opener", "expected"),
        [
            (_returning(200), True),
            (_returning(204), True),
            (_raising(_httpError(404)), False),
            (_raising(_httpError(401)), False),
            (_raising(_httpError(503)), False),
            (_raising(urllib.error.URLError("refused")), False),
            (_raising(TimeoutError("slow")), False),
        ],
    )
    def test_boolMatchesProbe(self, opener: Callable[..., Any], expected: bool) -> None:
        detector = _detector(opener)

        assert detector.isServerReachable() is expected
        assert detector.probeServer().isReachable is expected


# =============================================================================
# lastProbe -- what the shutdown sync reads to classify its outcome
# =============================================================================


class TestLastProbe:

    def test_noProbeYet_isNone(self) -> None:
        assert _detector(_returning(200)).lastProbe is None

    def test_homeState_404_lastProbeMisconfigured(self) -> None:
        """
        Given: at home (SSID + subnet) and the probe route 404s
        When: getHomeNetworkState() runs
        Then: the state is AT_HOME_SERVER_DOWN (bool contract unchanged) and
            lastProbe records the 404 so the shutdown can say why
        """
        detector = _detector(_raising(_httpError(404)))

        state = detector.getHomeNetworkState()

        assert state is HomeNetworkState.AT_HOME_SERVER_DOWN
        assert detector.lastProbe is not None
        assert detector.lastProbe.status == 404
        assert detector.lastProbe.isMisconfigured is True

    def test_awayAfterAProbe_lastProbeCleared(self) -> None:
        """A state computed without a probe never reports an older probe."""
        ssid: list[str | None] = ["DeathStarWiFi"]
        detector = HomeNetworkDetector(
            _config(),
            ssidReader=lambda: ssid[0],
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_raising(_httpError(404)),
            apiKey="k",
        )
        detector.getHomeNetworkState()
        assert detector.lastProbe is not None

        ssid[0] = "CoffeeShop"
        assert detector.getHomeNetworkState() is HomeNetworkState.AWAY

        assert detector.lastProbe is None
