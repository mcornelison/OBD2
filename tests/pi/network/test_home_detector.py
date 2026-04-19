################################################################################
# File Name: test_home_detector.py
# Purpose/Description: Outcome-based tests for the Pi home-network detector
#                      (US-188) -- B-043 building block. Covers the four
#                      HomeNetworkState branches + defense-in-depth SSID/subnet
#                      co-check + transition logging.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-188
# ================================================================================
################################################################################

"""
Tests for :mod:`src.pi.network.home_detector`.

The detector is the Component 1 building block of B-043 (auto-sync +
conditional shutdown on power loss).  Scope is DETECTION ONLY -- no
orchestration, no subscribe-to-UPS, no shutdown.  This test module
therefore asserts on the four ``HomeNetworkState`` branches plus:

* Defense in depth: SSID match AND subnet match must BOTH be true for
  ``isAtHomeWifi()`` -- catches a spoofed home-SSID on a foreign router.
* Subprocess infrastructure failure (iwgetid missing, timeout) surfaces
  as ``UNKNOWN`` -- distinct from AWAY.
* Transition logging: a state change from one HomeNetworkState to another
  emits an INFO log line with old + new state.  First observation does
  NOT log (there is no "previous").

The detector module is Windows-testable -- all subprocess / HTTP boundaries
are injection seams.  No real sockets, no real ``iwgetid``.
"""

from __future__ import annotations

import io
import logging
import subprocess
import urllib.error
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

from src.pi.network import HomeNetworkDetector, HomeNetworkState
from src.pi.network.home_detector import _readLocalIps, _readSsidViaIwgetid

# =============================================================================
# Fixtures
# =============================================================================


def _baseConfig(**overrides: Any) -> dict[str, Any]:
    """Minimal Pi config shape that the detector reads."""
    config: dict[str, Any] = {
        "pi": {
            "homeNetwork": {
                "ssid": "DeathStarWiFi",
                "subnet": "10.27.27.0/24",
                "pingTimeoutSeconds": 3,
                "serverPingPath": "/api/v1/ping",
            },
            "companionService": {
                "baseUrl": "http://10.27.27.10:8000",
            },
        },
    }
    for dottedKey, value in overrides.items():
        keys = dottedKey.split(".")
        cursor = config
        for key in keys[:-1]:
            cursor = cursor.setdefault(key, {})
        cursor[keys[-1]] = value
    return config


class _FakeResponse:
    """Minimal context-manager matching urlopen() return semantics."""

    def __init__(self, status: int = 200, body: bytes = b"{}"):
        self.status = status
        self.code = status  # urllib pre-3.9 parity
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def _openerReturning(response: _FakeResponse) -> Callable[..., Any]:
    calls: list[dict[str, Any]] = []

    def opener(request: Any, *args: Any, **kwargs: Any) -> _FakeResponse:
        calls.append({"request": request, "kwargs": kwargs})
        return response

    opener.calls = calls  # type: ignore[attr-defined]
    return opener


def _openerRaising(exc: BaseException) -> Callable[..., Any]:
    calls: list[dict[str, Any]] = []

    def opener(request: Any, *args: Any, **kwargs: Any) -> _FakeResponse:
        calls.append({"request": request, "kwargs": kwargs})
        raise exc

    opener.calls = calls  # type: ignore[attr-defined]
    return opener


# =============================================================================
# getHomeNetworkState — the four branches required by acceptance
# =============================================================================


class TestHomeNetworkStateBranches:
    """Each HomeNetworkState value has at least one scenario exercising it."""

    def test_atHomeServerUp_returnsAtHomeReachable(self) -> None:
        """SSID matches, IP in subnet, ping returns 200 -> AT_HOME_SERVER_REACHABLE."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.getHomeNetworkState() == HomeNetworkState.AT_HOME_SERVER_REACHABLE

    def test_atHomeServerDown_returnsAtHomeDown(self) -> None:
        """SSID matches, IP in subnet, ping errors out -> AT_HOME_SERVER_DOWN."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_openerRaising(urllib.error.URLError("connection refused")),
            apiKey="test-key",
        )

        assert detector.getHomeNetworkState() == HomeNetworkState.AT_HOME_SERVER_DOWN

    def test_ssidMismatch_returnsAway(self) -> None:
        """SSID does not match -> AWAY (don't even bother pinging)."""
        httpOpener = _openerReturning(_FakeResponse(status=200))
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "CoffeeShopWiFi",
            ipReader=lambda: ["192.168.1.42"],
            httpOpener=httpOpener,
            apiKey="test-key",
        )

        assert detector.getHomeNetworkState() == HomeNetworkState.AWAY
        # Short-circuit: SSID mismatch means we should NOT have pinged.
        assert httpOpener.calls == []  # type: ignore[attr-defined]

    def test_noWifiInfra_returnsUnknown(self) -> None:
        """iwgetid command missing (returns None) -> UNKNOWN."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: None,
            ipReader=lambda: [],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.getHomeNetworkState() == HomeNetworkState.UNKNOWN

    def test_ssidReaderReturnsEmpty_returnsAway(self) -> None:
        """iwgetid returns empty string (not connected) -> AWAY, not UNKNOWN.

        UNKNOWN is reserved for infra-missing (tool unavailable / timeout).
        Plain 'not connected to any WiFi' is a deterministic AWAY answer.
        """
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "",
            ipReader=lambda: [],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.getHomeNetworkState() == HomeNetworkState.AWAY


# =============================================================================
# Defense-in-depth: both SSID and subnet must match
# =============================================================================


class TestIsAtHomeWifiBothChecksRequired:
    """A spoofed home SSID on a foreign router must NOT trigger home-mode."""

    def test_ssidMatchButWrongSubnet_returnsAway(self) -> None:
        """SSID=DeathStarWiFi but IP is in 192.168.1.0/24 -> AWAY."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: ["192.168.1.42"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is False
        assert detector.getHomeNetworkState() == HomeNetworkState.AWAY

    def test_subnetMatchButWrongSsid_returnsAway(self) -> None:
        """Rare edge (VPN / wired into home via hotspot) -- still AWAY.

        The both-required rule treats SSID as the primary truth; any IP in
        the home subnet without the correct SSID is reachable-by-accident,
        not home-mode.
        """
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "NeighborWiFi",
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is False
        assert detector.getHomeNetworkState() == HomeNetworkState.AWAY

    def test_bothMatch_isAtHomeWifiTrue(self) -> None:
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is True

    def test_multipleIps_anyInSubnetCounts(self) -> None:
        """A Pi with multi-iface (eth0 + wlan0) returns True if ANY IP is home."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: ["169.254.1.5", "10.27.27.28", "fe80::1"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is True

    def test_emptyIpList_returnsFalse(self) -> None:
        """hostname -I returns nothing -> can't be home."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: [],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is False


# =============================================================================
# isServerReachable — bounded timeout, no-raise on network errors
# =============================================================================


class TestIsServerReachable:

    def test_status2xx_returnsTrue(self) -> None:
        detector = HomeNetworkDetector(
            _baseConfig(),
            httpOpener=_openerReturning(_FakeResponse(status=204)),
            apiKey="test-key",
        )

        assert detector.isServerReachable() is True

    def test_urlError_returnsFalseNotRaise(self) -> None:
        detector = HomeNetworkDetector(
            _baseConfig(),
            httpOpener=_openerRaising(urllib.error.URLError("DNS fail")),
            apiKey="test-key",
        )

        assert detector.isServerReachable() is False

    def test_timeoutError_returnsFalseNotRaise(self) -> None:
        detector = HomeNetworkDetector(
            _baseConfig(),
            httpOpener=_openerRaising(TimeoutError("deadline exceeded")),
            apiKey="test-key",
        )

        assert detector.isServerReachable() is False

    def test_httpError4xx_returnsFalse(self) -> None:
        """Server reachable but rejected -- treat as 'not usable'.

        401/403/404 means we can't use the endpoint; from the ping-check
        perspective that's the same as unreachable.
        """
        httpError = urllib.error.HTTPError(
            url="http://test/api/v1/ping",
            code=401,
            msg="Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )
        detector = HomeNetworkDetector(
            _baseConfig(),
            httpOpener=_openerRaising(httpError),
            apiKey="wrong-key",
        )

        assert detector.isServerReachable() is False

    def test_boundedTimeout_passedToOpener(self) -> None:
        """pingTimeoutSeconds flows into urlopen(..., timeout=)."""
        opener = _openerReturning(_FakeResponse(status=200))
        detector = HomeNetworkDetector(
            _baseConfig(**{"pi.homeNetwork.pingTimeoutSeconds": 7}),
            httpOpener=opener,
            apiKey="test-key",
        )

        detector.isServerReachable()

        assert opener.calls[0]["kwargs"]["timeout"] == 7.0  # type: ignore[attr-defined]

    def test_apiKeyHeader_sentOnPing(self) -> None:
        opener = _openerReturning(_FakeResponse(status=200))
        detector = HomeNetworkDetector(
            _baseConfig(),
            httpOpener=opener,
            apiKey="secret-key-123",
        )

        detector.isServerReachable()

        req = opener.calls[0]["request"]  # type: ignore[attr-defined]
        headers = dict(req.header_items())
        # urllib capitalizes header names: 'X-API-Key' -> 'X-api-key'
        casefolded = {k.casefold(): v for k, v in headers.items()}
        assert casefolded.get("x-api-key") == "secret-key-123"

    def test_noBaseUrl_returnsFalse(self) -> None:
        """Missing companionService.baseUrl -> cannot ping -> False."""
        config = _baseConfig()
        config["pi"]["companionService"]["baseUrl"] = ""
        detector = HomeNetworkDetector(
            config,
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isServerReachable() is False


# =============================================================================
# State transition logging
# =============================================================================


class TestTransitionLogging:

    def _makeDetector(
        self,
        *,
        ssid: str = "DeathStarWiFi",
        ips: list[str] | None = None,
        pingOk: bool = True,
    ) -> HomeNetworkDetector:
        opener = (
            _openerReturning(_FakeResponse(status=200))
            if pingOk
            else _openerRaising(urllib.error.URLError("down"))
        )
        return HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: ssid,
            ipReader=lambda: ips if ips is not None else ["10.27.27.28"],
            httpOpener=opener,
            apiKey="test-key",
        )

    def test_firstCall_doesNotLogTransition(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """First state observation establishes baseline -- no transition to log."""
        detector = self._makeDetector()
        caplog.set_level(logging.INFO, logger="src.pi.network.home_detector")

        detector.getHomeNetworkState()

        transitionLogs = [
            rec for rec in caplog.records
            if "state changed" in rec.getMessage()
        ]
        assert transitionLogs == []

    def test_stateChange_logsInfo(self, caplog: pytest.LogCaptureFixture) -> None:
        """Second call with a different state emits INFO with old + new."""
        detector = self._makeDetector()
        caplog.set_level(logging.INFO, logger="src.pi.network.home_detector")

        first = detector.getHomeNetworkState()
        # Now flip the ssid reader so next call sees AWAY.
        detector._ssidReader = lambda: "CoffeeShopWiFi"  # noqa: SLF001
        second = detector.getHomeNetworkState()

        assert first == HomeNetworkState.AT_HOME_SERVER_REACHABLE
        assert second == HomeNetworkState.AWAY
        transitionLogs = [
            rec.getMessage() for rec in caplog.records
            if "state changed" in rec.getMessage()
        ]
        assert len(transitionLogs) == 1
        assert "at_home_server_reachable" in transitionLogs[0]
        assert "away" in transitionLogs[0]

    def test_sameState_twice_doesNotLog(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Stable-state polling should not spam logs."""
        detector = self._makeDetector()
        caplog.set_level(logging.INFO, logger="src.pi.network.home_detector")

        detector.getHomeNetworkState()
        detector.getHomeNetworkState()
        detector.getHomeNetworkState()

        transitionLogs = [
            rec for rec in caplog.records
            if "state changed" in rec.getMessage()
        ]
        assert transitionLogs == []


# =============================================================================
# Helpers (_readSsidViaIwgetid, _readLocalIps)
# =============================================================================


class TestSubprocessHelpers:
    """The default subprocess helpers must degrade gracefully off-Pi."""

    def test_readSsidViaIwgetid_fileNotFound_returnsNone(self) -> None:
        """iwgetid command missing -> None (UNKNOWN signal)."""
        with patch("src.pi.network.home_detector.subprocess.run",
                   side_effect=FileNotFoundError("iwgetid not found")):
            result = _readSsidViaIwgetid()
        assert result is None

    def test_readSsidViaIwgetid_timeout_returnsNone(self) -> None:
        """Subprocess timeout -> None (UNKNOWN signal)."""
        with patch("src.pi.network.home_detector.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="iwgetid", timeout=2.0)):
            result = _readSsidViaIwgetid()
        assert result is None

    def test_readSsidViaIwgetid_success_returnsStrippedSsid(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["iwgetid", "-r"], returncode=0, stdout="DeathStarWiFi\n",
            stderr="",
        )
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readSsidViaIwgetid()
        assert result == "DeathStarWiFi"

    def test_readSsidViaIwgetid_nonZeroReturn_returnsEmptyString(self) -> None:
        """Not connected -> iwgetid exits non-zero -> "" (AWAY signal)."""
        completed = subprocess.CompletedProcess(
            args=["iwgetid", "-r"], returncode=255, stdout="", stderr="",
        )
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readSsidViaIwgetid()
        assert result == ""

    def test_readLocalIps_success_returnsList(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hostname", "-I"], returncode=0,
            stdout="10.27.27.28 fe80::1%wlan0 \n", stderr="",
        )
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readLocalIps()
        assert result == ["10.27.27.28", "fe80::1%wlan0"]

    def test_readLocalIps_fileNotFound_returnsEmpty(self) -> None:
        with patch("src.pi.network.home_detector.subprocess.run",
                   side_effect=FileNotFoundError("hostname not found")):
            result = _readLocalIps()
        assert result == []


# =============================================================================
# Config-driven behavior
# =============================================================================


class TestConfigDrivenBehavior:

    def test_customSsid_respected(self) -> None:
        """SSID comes from config, not hardcoded."""
        config = _baseConfig(**{"pi.homeNetwork.ssid": "AlternateWiFi"})
        detector = HomeNetworkDetector(
            config,
            ssidReader=lambda: "AlternateWiFi",
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is True

    def test_customSubnet_respected(self) -> None:
        config = _baseConfig(**{"pi.homeNetwork.subnet": "192.168.1.0/24"})
        detector = HomeNetworkDetector(
            config,
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: ["192.168.1.100"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is True

    def test_customPingPath_respected(self) -> None:
        opener = _openerReturning(_FakeResponse(status=200))
        config = _baseConfig(
            **{"pi.homeNetwork.serverPingPath": "/custom/health"},
        )
        detector = HomeNetworkDetector(
            config, httpOpener=opener, apiKey="test-key",
        )

        detector.isServerReachable()

        req = opener.calls[0]["request"]  # type: ignore[attr-defined]
        assert req.full_url.endswith("/custom/health")

    def test_invalidCidr_returnsFalseForIsAtHomeWifi(self) -> None:
        """Bad subnet string shouldn't crash isAtHomeWifi(); degrade to False."""
        config = _baseConfig(**{"pi.homeNetwork.subnet": "not-a-cidr"})
        detector = HomeNetworkDetector(
            config,
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is False
