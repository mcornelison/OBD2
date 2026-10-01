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
# 2026-09-13    | Rex          | US-743: case-insensitive SSID guard (casefold)
# 2026-09-30    | Rex          | US-776-b: nmcli SSID reader tests
# 2026-10-01    | Rex          | US-776-c: three-way IP reader; only a positive
#               |              | AWAY (foreign SSID / no home-subnet IP) is AWAY
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
* Subprocess infrastructure failure (nmcli missing, timeout) surfaces
  as ``UNKNOWN`` -- distinct from AWAY.
* Transition logging: a state change from one HomeNetworkState to another
  emits an INFO log line with old + new state.  First observation does
  NOT log (there is no "previous").

The detector module is Windows-testable -- all subprocess / HTTP boundaries
are injection seams.  No real sockets, no real ``nmcli``.
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

from src.pi.network import HomeNetworkDetector, HomeNetworkState, home_detector
from src.pi.network.home_detector import _readLocalIps, _readSsidViaNmcli

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
                "serverPingPath": "/api/v1/health",
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


def _nmcliCompleted(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    """A finished ``nmcli -t -f ACTIVE,SSID device wifi`` run."""
    return subprocess.CompletedProcess(
        args=["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list"],
        returncode=returncode, stdout=stdout, stderr="",
    )


def _fakeRun(
    nmcli: subprocess.CompletedProcess[str] | BaseException,
    hostnameStdout: str,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """A ``subprocess.run`` stand-in that answers nmcli and ``hostname -I``."""

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "nmcli":
            if isinstance(nmcli, BaseException):
                raise nmcli
            return nmcli
        if argv[0] == "hostname":
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=hostnameStdout, stderr="",
            )
        raise AssertionError(f"unexpected subprocess call: {argv}")

    return run


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
        """nmcli command missing (returns None) + home-subnet IP -> UNKNOWN."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: None,
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.getHomeNetworkState() == HomeNetworkState.UNKNOWN

    def test_ssidReaderReturnsEmpty_returnsAway(self) -> None:
        """SSID reader returns empty string (not connected) -> AWAY, not UNKNOWN.

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
# US-743: SSID comparison is case-insensitive (casefold, not lower)
# =============================================================================


class TestSsidComparisonIgnoresCase:
    """A case-only difference between config and the live SSID is still home.

    Measured 2026-09-13 on the Pi in the home garage: ``iwgetid -r`` read
    ``DeathstarWifi`` while ``pi.homeNetwork.ssid`` held ``DeathStarWiFi``.
    Both look right to a human reading a log, and the detector said AWAY.
    """

    def test_caseOnlyMismatch_measuredStrings_returnsAtHome(self) -> None:
        """The exact measured pair -> AT_HOME, via both public entry points."""
        detector = HomeNetworkDetector(
            _baseConfig(**{"pi.homeNetwork.ssid": "DeathStarWiFi"}),
            ssidReader=lambda: "DeathstarWifi",
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is True
        assert detector.getHomeNetworkState() == HomeNetworkState.AT_HOME_SERVER_REACHABLE

    def test_genuinelyDifferentSsid_stillAway(self) -> None:
        """Ignoring case did not make the comparison a prefix or fuzzy match."""
        httpOpener = _openerReturning(_FakeResponse(status=200))
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "deathstarwifi-guest",
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=httpOpener,
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is False
        assert detector.getHomeNetworkState() == HomeNetworkState.AWAY
        assert httpOpener.calls == []  # type: ignore[attr-defined]

    def test_nonAsciiCaseDifference_foldedByCasefoldNotLower(self) -> None:
        """German sharp s: ``lower()`` keeps it, ``casefold()`` expands it to ``ss``.

        So a ``lower()`` comparison would still answer AWAY for this pair.
        """
        configured, live = "Straße", "STRASSE"
        assert configured.lower() != live.lower()
        assert configured.casefold() == live.casefold()

        detector = HomeNetworkDetector(
            _baseConfig(**{"pi.homeNetwork.ssid": configured}),
            ssidReader=lambda: live,
            ipReader=lambda: ["10.27.27.28"],
            httpOpener=_openerRaising(urllib.error.URLError("connection refused")),
            apiKey="test-key",
        )

        assert detector.getHomeNetworkState() == HomeNetworkState.AT_HOME_SERVER_DOWN

    def test_caseOnlyMismatch_wrongSubnet_stillAway(self) -> None:
        """The subnet half still gates: a case-matched SSID alone is never home."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathstarWifi",
            ipReader=lambda: ["192.168.1.42"],
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )

        assert detector.isAtHomeWifi() is False
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

    def test_osError_returnsFalseNotRaise(self) -> None:
        detector = HomeNetworkDetector(
            _baseConfig(),
            httpOpener=_openerRaising(ConnectionResetError("reset by peer")),
            apiKey="test-key",
        )

        assert detector.isServerReachable() is False

    def test_httpError4xx_returnsFalse(self) -> None:
        """Server reachable but rejected -- treat as 'not usable'.

        401/403/404 means we can't use the endpoint; from the ping-check
        perspective that's the same as unreachable.
        """
        httpError = urllib.error.HTTPError(
            url="http://test/api/v1/health",
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
# Helpers (_readSsidViaNmcli, _readLocalIps)
# =============================================================================


class TestSubprocessHelpers:
    """The default subprocess helpers must degrade gracefully off-Pi."""

    def test_readSsidViaNmcli_connected_returnsActiveSsid(self) -> None:
        """The 'yes' row is the associated AP; its SSID is returned."""
        completed = _nmcliCompleted("no:CoffeeShop\nyes:DeathstarWifi\nno:Other\n")
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readSsidViaNmcli()
        assert result == "DeathstarWifi"

    def test_readSsidViaNmcli_noActiveRow_returnsEmptyString(self) -> None:
        """nmcli ran but no AP is active -> "" (AWAY signal)."""
        completed = _nmcliCompleted("no:CoffeeShop\nno:Other\n")
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readSsidViaNmcli()
        assert result == ""

    def test_readSsidViaNmcli_emptyList_returnsEmptyString(self) -> None:
        completed = _nmcliCompleted("")
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readSsidViaNmcli()
        assert result == ""

    def test_readSsidViaNmcli_nonZeroReturn_returnsEmptyString(self) -> None:
        """nmcli exits non-zero (e.g. no WiFi device) -> "" as before."""
        completed = _nmcliCompleted("", returncode=10)
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readSsidViaNmcli()
        assert result == ""

    def test_readSsidViaNmcli_fileNotFound_returnsNone(self) -> None:
        """nmcli binary missing -> None (UNKNOWN signal)."""
        with patch("src.pi.network.home_detector.subprocess.run",
                   side_effect=FileNotFoundError("nmcli not found")):
            result = _readSsidViaNmcli()
        assert result is None

    def test_readSsidViaNmcli_timeout_returnsNone(self) -> None:
        """Subprocess timeout -> None (UNKNOWN signal)."""
        with patch("src.pi.network.home_detector.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="nmcli", timeout=2.0)):
            result = _readSsidViaNmcli()
        assert result is None

    def test_readSsidViaNmcli_osError_returnsNone(self) -> None:
        with patch("src.pi.network.home_detector.subprocess.run",
                   side_effect=OSError("exec format error")):
            result = _readSsidViaNmcli()
        assert result is None

    def test_readSsidViaNmcli_escapedColonAndBackslash_unescaped(self) -> None:
        """Terse mode escapes ':' and '\\' inside values; the SSID is unescaped."""
        completed = _nmcliCompleted("yes:Net\\:Work\\\\5G\n")
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readSsidViaNmcli()
        assert result == "Net:Work\\5G"

    def test_readSsidViaNmcli_command_isTerseActiveSsidWithBoundedTimeout(self) -> None:
        """nmcli, terse ACTIVE,SSID, UTF-8 decode, timeout no longer than iwgetid's 2 s."""
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=_nmcliCompleted("yes:DeathstarWifi\n")) as run:
            _readSsidViaNmcli()
        argv = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        assert argv[0] == "nmcli"
        assert argv[argv.index("-t")] == "-t"
        assert argv[argv.index("-f") + 1] == "ACTIVE,SSID"
        assert kwargs["encoding"] == "utf-8"
        assert 0 < kwargs["timeout"] <= 2.0

    def test_defaultSsidReader_isNmcli(self) -> None:
        detector = HomeNetworkDetector(_baseConfig())
        assert detector._ssidReader is _readSsidViaNmcli
        assert not hasattr(home_detector, "_readSsidViaIwgetid")

    def test_readSsidViaNmcli_isOnlyNmcliCall_noIwgetid(self) -> None:
        """The production reader never shells out to iwgetid (absent on the Pi)."""
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=_nmcliCompleted("")) as run:
            _readSsidViaNmcli()
        assert [c.args[0][0] for c in run.call_args_list] == ["nmcli"]

    def test_readLocalIps_success_returnsList(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hostname", "-I"], returncode=0,
            stdout="10.27.27.28 fe80::1%wlan0 \n", stderr="",
        )
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readLocalIps()
        assert result == ["10.27.27.28", "fe80::1%wlan0"]

    def test_readLocalIps_fileNotFound_returnsNone(self) -> None:
        """US-776-c: a failed read is None, never [] (which reads as AWAY)."""
        with patch("src.pi.network.home_detector.subprocess.run",
                   side_effect=FileNotFoundError("hostname not found")):
            result = _readLocalIps()
        assert result is None

    @pytest.mark.parametrize(
        "failure",
        [
            subprocess.TimeoutExpired(cmd="hostname", timeout=2.0),
            OSError("exec format error"),
        ],
        ids=["timeout", "osError"],
    )
    def test_readLocalIps_infraFailure_returnsNone(self, failure: BaseException) -> None:
        with patch("src.pi.network.home_detector.subprocess.run", side_effect=failure):
            result = _readLocalIps()
        assert result is None

    def test_readLocalIps_nonZeroReturn_returnsNone(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hostname", "-I"], returncode=1, stdout="", stderr="boom",
        )
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readLocalIps()
        assert result is None

    def test_readLocalIps_successNoAddresses_returnsEmptyList(self) -> None:
        """A SUCCESSFUL read with no addresses is a genuine [] -- not a failure."""
        completed = subprocess.CompletedProcess(
            args=["hostname", "-I"], returncode=0, stdout="\n", stderr="",
        )
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed):
            result = _readLocalIps()
        assert result == []

    def test_readLocalIps_timeoutNoLongerThanSsidReader(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hostname", "-I"], returncode=0, stdout="10.27.27.28\n", stderr="",
        )
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=completed) as run:
            _readLocalIps()
        assert 0 < run.call_args.kwargs["timeout"] <= home_detector._NMCLI_TIMEOUT_SECONDS


# =============================================================================
# Default nmcli reader through _computeState (US-776-b)
# =============================================================================


class TestNmcliReaderThroughState:
    """The DEFAULT reader, fed faked nmcli output, lands on each state.

    No ``ssidReader`` is injected, so these run the production nmcli parse.
    The SSID-plus-subnet double check and the US-743 casefold must hold.
    """

    def _state(
        self,
        nmcli: subprocess.CompletedProcess[str] | BaseException,
        hostnameStdout: str = "10.27.27.28 \n",
        status: int = 200,
    ) -> HomeNetworkState:
        detector = HomeNetworkDetector(
            _baseConfig(),
            httpOpener=_openerReturning(_FakeResponse(status=status)),
            apiKey="test-key",
        )
        with patch("src.pi.network.home_detector.subprocess.run",
                   side_effect=_fakeRun(nmcli, hostnameStdout)):
            return detector._computeState()

    def test_connectedHomeSsid_homeSubnet_serverUp_atHomeReachable(self) -> None:
        # Live router case ("DeathstarWifi") vs config "DeathStarWiFi" -- US-743.
        state = self._state(_nmcliCompleted("no:Neighbour\nyes:DeathstarWifi\n"))
        assert state == HomeNetworkState.AT_HOME_SERVER_REACHABLE

    def test_connectedHomeSsid_homeSubnet_serverDown_atHomeDown(self) -> None:
        state = self._state(_nmcliCompleted("yes:DeathStarWiFi\n"), status=503)
        assert state == HomeNetworkState.AT_HOME_SERVER_DOWN

    def test_connectedHomeSsid_foreignSubnet_away(self) -> None:
        """SSID match alone is not home: the subnet check still gates AT_HOME."""
        state = self._state(
            _nmcliCompleted("yes:DeathStarWiFi\n"), hostnameStdout="192.168.1.42\n",
        )
        assert state == HomeNetworkState.AWAY

    def test_connectedOtherSsid_homeSubnet_away(self) -> None:
        state = self._state(_nmcliCompleted("yes:CoffeeShop\n"))
        assert state == HomeNetworkState.AWAY

    def test_disconnected_away(self) -> None:
        state = self._state(_nmcliCompleted("no:DeathStarWiFi\nno:CoffeeShop\n"))
        assert state == HomeNetworkState.AWAY

    def test_nmcliMissing_unknown(self) -> None:
        state = self._state(FileNotFoundError("nmcli"))
        assert state == HomeNetworkState.UNKNOWN

    def test_nmcliTimeout_unknown(self) -> None:
        state = self._state(subprocess.TimeoutExpired(cmd="nmcli", timeout=2.0))
        assert state == HomeNetworkState.UNKNOWN


# =============================================================================
# US-776-c: a failed IP read never counts as a positive AWAY
# =============================================================================


class TestThreeWayIpRead:
    """Only a positive AWAY -- a foreign SSID, or a SUCCESSFUL IP read with no
    home-subnet address -- is AWAY. A dead SSID or IP reader is UNKNOWN."""

    def _state(self, ssid: str | None, ips: list[str] | None) -> HomeNetworkState:
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: ssid,
            ipReader=lambda: ips,
            httpOpener=_openerReturning(_FakeResponse(status=200)),
            apiKey="test-key",
        )
        return detector.getHomeNetworkState()

    def test_homeSsid_failedIpRead_unknown(self) -> None:
        assert self._state("DeathStarWiFi", None) == HomeNetworkState.UNKNOWN

    def test_noneSsid_failedIpRead_unknown(self) -> None:
        assert self._state(None, None) == HomeNetworkState.UNKNOWN

    def test_noneSsid_homeIp_unknown(self) -> None:
        assert self._state(None, ["10.27.27.28"]) == HomeNetworkState.UNKNOWN

    def test_noneSsid_foreignIp_away(self) -> None:
        assert self._state(None, ["192.168.1.42"]) == HomeNetworkState.AWAY

    def test_noneSsid_noAddresses_away(self) -> None:
        assert self._state(None, []) == HomeNetworkState.AWAY

    @pytest.mark.parametrize("ips", [["10.27.27.28"], None, []], ids=["homeIp", "failed", "none"])
    def test_foreignSsid_awayWhateverTheIpRead(self, ips: list[str] | None) -> None:
        assert self._state("CoffeeShopWiFi", ips) == HomeNetworkState.AWAY

    def test_homeSsid_failedIpRead_noServerProbe(self) -> None:
        """UNKNOWN is decided without a network call."""
        opener = _openerReturning(_FakeResponse(status=200))
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: None,
            httpOpener=opener,
            apiKey="test-key",
        )
        assert detector.getHomeNetworkState() == HomeNetworkState.UNKNOWN
        assert opener.calls == []  # type: ignore[attr-defined]

    def test_failedIpRead_isAtHomeWifiFalse(self) -> None:
        """isAtHomeWifi keeps its bool contract: a failed read is not home."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathStarWiFi",
            ipReader=lambda: None,
        )
        assert detector.isAtHomeWifi() is False

    def test_defaultIpReader_hostnameMissing_homeSsid_unknown(self) -> None:
        """The DEFAULT IP reader, failing, lands UNKNOWN -- not AWAY."""
        detector = HomeNetworkDetector(
            _baseConfig(),
            ssidReader=lambda: "DeathStarWiFi",
            httpOpener=_openerReturning(_FakeResponse(status=200)),
        )
        with patch("src.pi.network.home_detector.subprocess.run",
                   side_effect=FileNotFoundError("hostname")):
            assert detector.getHomeNetworkState() == HomeNetworkState.UNKNOWN


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
