################################################################################
# File Name: home_detector.py
# Purpose/Description: Pi home-network detection (US-188) -- building block 1 of
#                      B-043 (auto-sync + conditional shutdown).  Tells the
#                      orchestrator whether the Pi is on home WiFi and whether
#                      the companion server is reachable.
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
Pi home-network detection.

:class:`HomeNetworkDetector` composes three signals:

1. ``iwgetid -r`` for the currently-associated WiFi SSID
2. ``hostname -I`` for the Pi's local IPv4/IPv6 addresses
3. An HTTP GET against ``{companionService.baseUrl}{serverPingPath}`` with
   the ``X-API-Key`` header and a bounded timeout

All three are injection seams so the module is Windows-testable without
any of them actually running.  The default helpers use stdlib
:mod:`subprocess` + :mod:`urllib.request` -- no new deps added to
requirements-pi.txt.

Scope is **detection only**.  This module never shuts the Pi down, never
subscribes to UPS power-source signals, and never calls :class:`SyncClient`
(which would be a circular-dep trap per the sprint invariants).  The
future PowerLossOrchestrator (US-189, Sprint 14) owns the glue.

States
------

:class:`HomeNetworkState` has four values:

* ``AT_HOME_SERVER_REACHABLE`` -- SSID + subnet both match AND ping 2xx
* ``AT_HOME_SERVER_DOWN``      -- SSID + subnet both match but ping fails
* ``AWAY``                     -- not on home WiFi (by either check)
* ``UNKNOWN``                  -- SSID-detection infra is unavailable
  (``iwgetid`` missing or timing out).  Distinguished from AWAY so the
  orchestrator can decide separately (e.g., "wait and retry" vs
  "definitely shut down without sync").

Note that ``iwgetid`` returning a non-zero exit code with no SSID (i.e.,
"not connected to anything") maps to ``AWAY`` -- that is a deterministic
"not home" answer, not a lack of information.
"""

from __future__ import annotations

import ipaddress
import logging
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from enum import StrEnum
from typing import Any

__all__ = ["HomeNetworkDetector", "HomeNetworkState"]

logger = logging.getLogger(__name__)


# Subprocess budgets -- both helpers shell out briefly.  Keep them short
# so a hung iwgetid can't stall the whole detector for more than a blink.
_IWGETID_TIMEOUT_SECONDS = 2.0
_HOSTNAME_TIMEOUT_SECONDS = 2.0


# =============================================================================
# State enum
# =============================================================================


class HomeNetworkState(StrEnum):
    """Composed home-network state the orchestrator branches on."""

    AT_HOME_SERVER_REACHABLE = "at_home_server_reachable"
    AT_HOME_SERVER_DOWN = "at_home_server_down"
    AWAY = "away"
    UNKNOWN = "unknown"


# =============================================================================
# Default subprocess helpers (injection-replaceable in tests)
# =============================================================================


def _readSsidViaIwgetid(timeout: float = _IWGETID_TIMEOUT_SECONDS) -> str | None:
    """Return the current WiFi SSID, or a signal value.

    Returns:
        * ``None`` if the detection infrastructure is unavailable
          (``iwgetid`` binary missing, subprocess timeout, OS error).
          Callers interpret this as :attr:`HomeNetworkState.UNKNOWN`.
        * An empty string if ``iwgetid`` ran but returned non-zero
          (not connected to any WiFi).  Callers interpret this as
          :attr:`HomeNetworkState.AWAY`.
        * The stripped SSID string on success.
    """
    try:
        result = subprocess.run(
            ["iwgetid", "-r"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _readLocalIps(timeout: float = _HOSTNAME_TIMEOUT_SECONDS) -> list[str]:
    """Return the list of local IPs reported by ``hostname -I``.

    Empty list on any subprocess failure -- callers treat empty as
    "can't determine home-subnet membership" which collapses to False in
    :meth:`HomeNetworkDetector.isAtHomeWifi`.
    """
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return [ip for ip in result.stdout.strip().split() if ip]


# =============================================================================
# Detector
# =============================================================================


class HomeNetworkDetector:
    """Detect whether the Pi is at home and whether the server is reachable.

    Construction is side-effect-free.  Every external call (iwgetid,
    hostname -I, HTTP ping) is deferred until :meth:`isAtHomeWifi`,
    :meth:`isServerReachable`, or :meth:`getHomeNetworkState` is invoked.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        ssidReader: Callable[[], str | None] | None = None,
        ipReader: Callable[[], list[str]] | None = None,
        httpOpener: Callable[..., Any] | None = None,
        apiKey: str | None = None,
    ) -> None:
        """Construct a detector bound to a validated Pi config.

        Args:
            config: Full (tier-aware) config dict.  Reads
                ``pi.homeNetwork`` + ``pi.companionService.baseUrl``.
            ssidReader: Callable returning the current SSID, ``""`` for
                "not connected", or ``None`` for "infra unavailable".
                Defaults to :func:`_readSsidViaIwgetid`.
            ipReader: Callable returning the list of local IPs (strings).
                Defaults to :func:`_readLocalIps`.
            httpOpener: :func:`urllib.request.urlopen`-compatible callable
                for the server-ping HTTP call.  Defaults to the stdlib
                function.
            apiKey: API key value for the ``X-API-Key`` header on the
                ping.  Resolved from the env var named in
                ``pi.companionService.apiKeyEnv`` by callers that need
                the real key; tests pass a fake string.  Empty/``None``
                is acceptable when the ping endpoint doesn't enforce
                auth -- the server still responds with 401 in that case
                and ``isServerReachable`` returns False, which is the
                safe answer.
        """
        piConfig: dict[str, Any] = config.get("pi", {}) or {}
        homeNet: dict[str, Any] = piConfig.get("homeNetwork", {}) or {}
        companion: dict[str, Any] = piConfig.get("companionService", {}) or {}

        self._ssid: str = str(homeNet.get("ssid", "DeathStarWiFi"))
        self._subnet: str = str(homeNet.get("subnet", "10.27.27.0/24"))  # b044-exempt: defensive fallback mirroring validator default
        self._pingTimeout: float = float(homeNet.get("pingTimeoutSeconds", 3))
        self._pingPath: str = str(homeNet.get("serverPingPath", "/api/v1/ping"))
        self._baseUrl: str = str(companion.get("baseUrl", "")).rstrip("/")

        self._ssidReader: Callable[[], str | None] = ssidReader or _readSsidViaIwgetid
        self._ipReader: Callable[[], list[str]] = ipReader or _readLocalIps
        self._httpOpener: Callable[..., Any] = httpOpener or urllib.request.urlopen
        self._apiKey: str | None = apiKey

        self._previousState: HomeNetworkState | None = None

    # ---- public API --------------------------------------------------------

    def isAtHomeWifi(self) -> bool:
        """Return True only if SSID matches **and** a local IP is in the home subnet.

        Both checks must pass.  A spoofed home-SSID on a foreign router
        will fail the subnet check; a random IP collision (e.g., tethered
        through a hotspot that happens to use 10.27.27.0/24) will fail
        the SSID check.  Defense in depth.
        """
        ssid = self._ssidReader()
        if not ssid or ssid != self._ssid:
            return False
        return self._hasIpInHomeSubnet()

    def isServerReachable(self) -> bool:
        """Return True if a GET against the configured ping endpoint is 2xx.

        Never raises.  Any HTTP error, URL error, timeout, or underlying
        OS error is swallowed and mapped to False -- the orchestrator
        treats unreachable-for-any-reason the same way.
        """
        if not self._baseUrl:
            return False
        url = f"{self._baseUrl}{self._pingPath}"
        headers = {"X-API-Key": self._apiKey or ""}
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._httpOpener(req, timeout=self._pingTimeout) as response:
                code = (
                    getattr(response, "status", None)
                    or getattr(response, "code", None)
                    or 0
                )
                return 200 <= int(code) < 300
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            logger.debug("ping to %s failed: %s", url, exc)
            return False

    def getHomeNetworkState(self) -> HomeNetworkState:
        """Compose SSID + subnet + ping into one :class:`HomeNetworkState`.

        Side effect: on the FIRST call, records the resulting state as
        the baseline (no log line emitted).  On subsequent calls, if the
        state differs from the previous observation, emits an INFO log
        with the old + new state names.  Same-state polling is silent.
        """
        newState = self._computeState()
        self._maybeLogTransition(newState)
        return newState

    # ---- internals ---------------------------------------------------------

    def _computeState(self) -> HomeNetworkState:
        ssid = self._ssidReader()
        if ssid is None:
            return HomeNetworkState.UNKNOWN
        if ssid != self._ssid:
            # Includes the empty-string "not connected" case.
            return HomeNetworkState.AWAY
        if not self._hasIpInHomeSubnet():
            return HomeNetworkState.AWAY
        if self.isServerReachable():
            return HomeNetworkState.AT_HOME_SERVER_REACHABLE
        return HomeNetworkState.AT_HOME_SERVER_DOWN

    def _hasIpInHomeSubnet(self) -> bool:
        ips = self._ipReader()
        if not ips:
            return False
        try:
            network = ipaddress.ip_network(self._subnet, strict=False)
        except ValueError:
            logger.warning(
                "pi.homeNetwork.subnet is not a valid CIDR: %r", self._subnet,
            )
            return False
        for raw in ips:
            # Strip zone suffixes ("fe80::1%wlan0" -> "fe80::1") -- ipaddress
            # rejects the Linux zone-id form.
            bare = raw.split("%", 1)[0]
            try:
                if ipaddress.ip_address(bare) in network:
                    return True
            except ValueError:
                continue
        return False

    def _maybeLogTransition(self, newState: HomeNetworkState) -> None:
        if self._previousState is None:
            self._previousState = newState
            return
        if newState != self._previousState:
            logger.info(
                "home network state changed: %s -> %s",
                self._previousState.value, newState.value,
            )
            self._previousState = newState
