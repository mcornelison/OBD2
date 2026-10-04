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
# 2026-09-13    | Rex          | US-743: SSID compared case-insensitively (casefold)
# 2026-09-30    | Rex          | US-776-a: serverPingPath fallback /api/v1/health
# 2026-09-30    | Rex          | US-776-b: SSID read via nmcli (no iwgetid on Pi)
# 2026-10-01    | Rex          | US-776-c: three-way IP reader (None on a failed
#               |              | read); only a positive AWAY is AWAY, a dead SSID
#               |              | or IP reader is UNKNOWN
# 2026-10-01    | Rex          | US-776-d: probeServer() -> ProbeResult sibling;
#               |              | isServerReachable() is its 2xx; lastProbe
# 2026-10-01    | Rex          | US-776-e: AT_HOME_JOINING -- home SSID in the
#               |              | cached scan list, not associated (scanReader)
# 2026-10-03    | Atlas (ARCH-065a) | Ruling 19: AT_HOME_STATES / AT_HOME_STATE_NAMES --
#               |              | the ONE owner of "the car was at home" (monthly
#               |              | test hold gate + boot finaliser floor stamp)
# ================================================================================
################################################################################

"""
Pi home-network detection.

:class:`HomeNetworkDetector` composes three signals:

1. ``nmcli -t -f ACTIVE,SSID device wifi`` for the currently-associated
   WiFi SSID
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

:class:`HomeNetworkState` has five values:

* ``AT_HOME_SERVER_REACHABLE`` -- SSID + subnet both match AND ping 2xx
* ``AT_HOME_SERVER_DOWN``      -- SSID + subnet both match but ping fails
* ``AT_HOME_JOINING``          -- not associated, but the home SSID is in
  NetworkManager's cached scan list: the rejoin is pending (US-776-e).
  The shutdown sync waits for the association inside its ceiling.
* ``AWAY``                     -- a POSITIVE not-home answer: a foreign
  SSID (whatever the IP read says), or a successful IP read with no
  address in the home subnet
* ``UNKNOWN``                  -- no positive AWAY, but home cannot be
  confirmed: the SSID reader is unavailable (``nmcli`` missing or timing
  out) and the IP read did not rule home out, or the IP read itself
  failed.  The shutdown sync DRAINS on UNKNOWN (US-776-c): a dead
  instrument must never disable the drain.

Note that ``nmcli`` listing no active AP, or exiting non-zero (i.e.,
"not connected to anything") with the home SSID absent from the cached
scan list maps to ``AWAY`` -- that is a deterministic
"not home" answer, not a lack of information.  The same holds for a
``hostname -I`` that succeeds with no addresses; a ``hostname -I`` that
FAILS returns ``None`` and is a lack of information.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "AT_HOME_STATES",
    "AT_HOME_STATE_NAMES",
    "PROBE_MISCONFIGURED_STATUSES",
    "HomeNetworkDetector",
    "HomeNetworkState",
    "ProbeResult",
]

logger = logging.getLogger(__name__)


# Subprocess budgets -- both helpers shell out briefly.  Keep them short
# so a hung nmcli can't stall the whole detector for more than a blink.
_NMCLI_TIMEOUT_SECONDS = 2.0
_HOSTNAME_TIMEOUT_SECONDS = 2.0

# nmcli terse mode backslash-escapes ':' and '\' inside field values.
_NMCLI_TERSE_ESCAPE = re.compile(r"\\(.)")


# =============================================================================
# State enum
# =============================================================================


class HomeNetworkState(StrEnum):
    """Composed home-network state the orchestrator branches on."""

    AT_HOME_SERVER_REACHABLE = "at_home_server_reachable"
    AT_HOME_SERVER_DOWN = "at_home_server_down"
    AT_HOME_JOINING = "at_home_joining"  # US-776-e: home SSID cached, not associated
    AWAY = "away"
    UNKNOWN = "unknown"


#: ARCH-065 (Ruling 19): the states that mean the car was AT HOME -- the ONE
#: owner.  The monthly-test hold is gated on the loss's state being one of
#: these, and the boot finaliser stamps a floor-ended drain ``replace`` only in
#: one of these.  UNKNOWN is not home (nothing confirmed it); AWAY is not.
AT_HOME_STATES: frozenset[HomeNetworkState] = frozenset({
    HomeNetworkState.AT_HOME_SERVER_REACHABLE,
    HomeNetworkState.AT_HOME_SERVER_DOWN,
    HomeNetworkState.AT_HOME_JOINING,
})

#: The same set as the durable record stores it (the enum NAME, e.g. as
#: ``HomeStateAtLoss.stateName`` and ``startup_log.prior_boot_home_state``).
AT_HOME_STATE_NAMES: frozenset[str] = frozenset(state.name for state in AT_HOME_STATES)


# =============================================================================
# Server probe result (US-776-d)
# =============================================================================

#: Atlas ruling 4 (Sprint 95): a server that answers the probe with one of
#: these is UP -- the configured route (404/405) or key (401/403) is wrong.
#: Every other non-2xx answer, and no answer at all, reads as server down.
PROBE_MISCONFIGURED_STATUSES: frozenset[int] = frozenset({401, 403, 404, 405})


@dataclass(frozen=True)
class ProbeResult:
    """One GET of the server probe route.

    Attributes:
        status: The HTTP status the server answered with, or ``None`` when
            no answer came back (connection error, timeout, no base URL).
        error: Why the probe was not a 2xx, or ``None`` when it was.
    """

    status: int | None
    error: str | None

    @property
    def isReachable(self) -> bool:
        """True on a 2xx -- the only answer :meth:`isServerReachable` accepts."""
        return self.status is not None and 200 <= self.status < 300

    @property
    def isMisconfigured(self) -> bool:
        """True when the server answered but rejected the route or the key."""
        return self.status in PROBE_MISCONFIGURED_STATUSES


# =============================================================================
# Default subprocess helpers (injection-replaceable in tests)
# =============================================================================


def _unescapeNmcliTerse(value: str) -> str:
    """Undo nmcli terse-mode escaping (``\\:`` -> ``:``, ``\\\\`` -> ``\\``)."""
    return _NMCLI_TERSE_ESCAPE.sub(r"\1", value)


def _listWifiRows(timeout: float) -> list[tuple[str, str]] | None:
    """Run ``nmcli -t -f ACTIVE,SSID device wifi list --rescan no``.

    ``--rescan no`` reads NetworkManager's cached AP list: the default
    rescan can outlast the timeout, and a forced rescan needs polkit rights
    the service user lacks (US-776-e, measured).

    Returns:
        ``None`` when nmcli is unavailable (missing, timeout, OS error);
        ``[]`` when it exited non-zero; otherwise one ``(active, ssid)`` pair
        per listed AP, the SSID unescaped.
    """
    try:
        result = subprocess.run(
            # US-776-b: replaced `iwgetid -r` -- iwgetid is not installed on
            # the Pi, so the reader returned None on every call and the Pi
            # never believed it was home.  nmcli is installed.
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list",
             "--rescan", "no"],
            # An SSID is USER-AUTHORED and routinely non-ASCII, so this is the
            # one site in the tree where the locale-default codec is not a
            # theoretical exposure: a household name with an accent in it
            # decodes to a different string under cp1252 than under UTF-8, and
            # `_isHomeSsid` then compares that mojibake against the configured
            # name and reports AWAY while sitting in the driveway.
            # (US-710 / TD-068)
            capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return []
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        # ACTIVE is yes/no and never contains ':', so the first ':' always
        # separates it from the (possibly escaped) SSID.
        active, separator, ssid = line.partition(":")
        if separator:
            rows.append((active, _unescapeNmcliTerse(ssid)))
    return rows


def _readSsidViaNmcli(timeout: float = _NMCLI_TIMEOUT_SECONDS) -> str | None:
    """Return the current WiFi SSID, or a signal value.

    Takes the SSID of the :func:`_listWifiRows` row whose ACTIVE field is
    ``yes`` -- the associated AP is always in the cache.

    Returns:
        * ``None`` if the detection infrastructure is unavailable
          (``nmcli`` binary missing, subprocess timeout, OS error).
          Callers interpret this as :attr:`HomeNetworkState.UNKNOWN`.
        * An empty string if ``nmcli`` exited non-zero or listed no active
          AP (not connected to any WiFi).  Callers then consult the scan
          cache: the home SSID in it is :attr:`HomeNetworkState.AT_HOME_JOINING`,
          otherwise :attr:`HomeNetworkState.AWAY`.
        * The unescaped SSID string on success.
    """
    rows = _listWifiRows(timeout)
    if rows is None:
        return None
    for active, ssid in rows:
        if active == "yes":
            return ssid
    return ""


def _readVisibleSsidsViaNmcli(timeout: float = _NMCLI_TIMEOUT_SECONDS) -> list[str] | None:
    """Return every SSID in NetworkManager's cached scan list (US-776-e).

    Associated or not; hidden networks (empty SSID) are skipped.  Reads the
    cache only -- never forces a rescan or ``nmcli con up``.

    Returns:
        ``None`` when nmcli is unavailable, ``[]`` when it exited non-zero or
        lists nothing, otherwise the SSIDs in listed order.
    """
    rows = _listWifiRows(timeout)
    if rows is None:
        return None
    return [ssid for _active, ssid in rows if ssid]


def _readLocalIps(timeout: float = _HOSTNAME_TIMEOUT_SECONDS) -> list[str] | None:
    """Return the list of local IPs reported by ``hostname -I``.

    Three-way, like :func:`_readSsidViaNmcli` (US-776-c):

    Returns:
        * ``None`` if the read itself failed (``hostname`` missing,
          subprocess timeout, OS error, non-zero exit).  A failed read says
          nothing about where the Pi is, so it must never read as AWAY.
        * A list of address strings on a successful read -- possibly empty,
          which is a genuine "no addresses".
    """
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return [ip for ip in result.stdout.strip().split() if ip]


# =============================================================================
# Detector
# =============================================================================


class HomeNetworkDetector:
    """Detect whether the Pi is at home and whether the server is reachable.

    Construction is side-effect-free.  Every external call (nmcli,
    hostname -I, HTTP ping) is deferred until :meth:`isAtHomeWifi`,
    :meth:`isServerReachable`, or :meth:`getHomeNetworkState` is invoked.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        ssidReader: Callable[[], str | None] | None = None,
        ipReader: Callable[[], list[str] | None] | None = None,
        httpOpener: Callable[..., Any] | None = None,
        apiKey: str | None = None,
        scanReader: Callable[[], list[str] | None] | None = None,
    ) -> None:
        """Construct a detector bound to a validated Pi config.

        Args:
            config: Full (tier-aware) config dict.  Reads
                ``pi.homeNetwork`` + ``pi.companionService.baseUrl``.
            ssidReader: Callable returning the current SSID, ``""`` for
                "not connected", or ``None`` for "infra unavailable".
                Defaults to :func:`_readSsidViaNmcli`.
            ipReader: Callable returning the list of local IPs (strings),
                or ``None`` when the read itself failed.  Defaults to
                :func:`_readLocalIps`.
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
            scanReader: Callable returning the SSIDs in NetworkManager's
                cached scan list, or ``None`` when it cannot be read.  Read
                only when the SSID reader says "not associated" (US-776-e).
                Defaults to :func:`_readVisibleSsidsViaNmcli`.
        """
        piConfig: dict[str, Any] = config.get("pi", {}) or {}
        homeNet: dict[str, Any] = piConfig.get("homeNetwork", {}) or {}
        companion: dict[str, Any] = piConfig.get("companionService", {}) or {}

        self._ssid: str = str(homeNet.get("ssid", "DeathStarWiFi"))
        self._subnet: str = str(homeNet.get("subnet", "10.27.27.0/24"))  # b044-exempt: defensive fallback mirroring validator default
        self._pingTimeout: float = float(homeNet.get("pingTimeoutSeconds", 3))
        self._pingPath: str = str(homeNet.get("serverPingPath", "/api/v1/health"))
        self._baseUrl: str = str(companion.get("baseUrl", "")).rstrip("/")

        self._ssidReader: Callable[[], str | None] = ssidReader or _readSsidViaNmcli
        self._ipReader: Callable[[], list[str] | None] = ipReader or _readLocalIps
        self._scanReader: Callable[[], list[str] | None] = (
            scanReader or _readVisibleSsidsViaNmcli
        )
        self._httpOpener: Callable[..., Any] = httpOpener or urllib.request.urlopen
        self._apiKey: str | None = apiKey

        self._previousState: HomeNetworkState | None = None
        self._lastProbe: ProbeResult | None = None

    # ---- public API --------------------------------------------------------

    @property
    def lastProbe(self) -> ProbeResult | None:
        """The probe behind the most recent :meth:`getHomeNetworkState`.

        ``None`` when that state was decided without probing the server
        (AWAY, UNKNOWN), or before any state has been computed.  Lets the
        shutdown sync say WHY the server read as down without probing again
        (US-776-d).
        """
        return self._lastProbe

    def isAtHomeWifi(self) -> bool:
        """Return True only if SSID matches **and** a local IP is in the home subnet.

        Both checks must pass.  A spoofed home-SSID on a foreign router
        will fail the subnet check; a random IP collision (e.g., tethered
        through a hotspot that happens to use 10.27.27.0/24) will fail
        the SSID check.  Defense in depth.
        """
        ssid = self._ssidReader()
        if not ssid or not self._isHomeSsid(ssid):
            return False
        # A failed IP read (None) is not home either: this stays a bool.
        return self._hasIpInHomeSubnet() is True

    def isServerReachable(self) -> bool:
        """Return True if a GET against the configured ping endpoint is 2xx.

        Never raises.  The 2xx of :meth:`probeServer` (US-776-d, Atlas
        ruling 4): any HTTP error, URL error, timeout, or underlying OS error
        maps to False -- the orchestrator treats unreachable-for-any-reason
        the same way.  Callers that need the reason use :meth:`probeServer`.
        """
        return self.probeServer().isReachable

    def probeServer(self) -> ProbeResult:
        """GET the configured ping endpoint once and say what came back.

        Never raises.  The call is bounded by ``pingTimeoutSeconds``.  The
        result is also kept as :attr:`lastProbe`.

        Returns:
            A :class:`ProbeResult`: the HTTP status the server answered with
            (2xx included), or ``status=None`` with the error when no answer
            came back.
        """
        result = self._probe()
        self._lastProbe = result
        return result

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

    def _probe(self) -> ProbeResult:
        if not self._baseUrl:
            return ProbeResult(
                status=None, error="pi.companionService.baseUrl is not configured"
            )
        url = f"{self._baseUrl}{self._pingPath}"
        headers = {"X-API-Key": self._apiKey or ""}
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._httpOpener(req, timeout=self._pingTimeout) as response:
                code = int(
                    getattr(response, "status", None)
                    or getattr(response, "code", None)
                    or 0
                )
        except urllib.error.HTTPError as exc:
            # Before URLError/OSError: HTTPError subclasses both, and it is
            # the one failure that carries the server's answer.
            logger.debug("ping to %s answered HTTP %s", url, exc.code)
            return ProbeResult(status=int(exc.code), error=f"HTTP {exc.code}: {exc.reason}")
        except Exception as exc:  # noqa: BLE001 -- never raise; no answer is server-down
            logger.debug("ping to %s failed: %s", url, exc)
            return ProbeResult(status=None, error=str(exc) or type(exc).__name__)
        if 200 <= code < 300:
            return ProbeResult(status=code, error=None)
        return ProbeResult(status=code, error=f"HTTP {code}")

    def _computeState(self) -> HomeNetworkState:
        # US-776-c: only a POSITIVE answer is AWAY -- a foreign SSID, or a
        # successful IP read with no home-subnet address.  A dead SSID or IP
        # reader is UNKNOWN, never AWAY: a dead instrument gating the shutdown
        # drain is how the drain stayed off for weeks (Atlas gap 2,
        # design-patterns section 6).
        # US-776-d: a state decided without probing must not carry an older
        # probe's answer.
        self._lastProbe = None
        ssid = self._ssidReader()
        if ssid == "" and self._isHomeSsidVisible():
            # US-776-e: not associated, but the home AP is in range -- the
            # rejoin is pending (measured ~49 s after arriving, drive 96).
            # Decided before the IP read: unassociated, there is no home IP.
            return HomeNetworkState.AT_HOME_JOINING
        if ssid is not None and not self._isHomeSsid(ssid):
            # Includes the empty-string "not connected" case.
            return HomeNetworkState.AWAY
        inHomeSubnet = self._hasIpInHomeSubnet()
        if inHomeSubnet is False:
            return HomeNetworkState.AWAY
        if ssid is None or inHomeSubnet is None:
            return HomeNetworkState.UNKNOWN
        if self.isServerReachable():
            return HomeNetworkState.AT_HOME_SERVER_REACHABLE
        return HomeNetworkState.AT_HOME_SERVER_DOWN

    def _isHomeSsid(self, ssid: str) -> bool:
        # An SSID is user-authored: the router and pi.homeNetwork.ssid can hold
        # the same name in different case, and both read as correct in a log
        # (measured: live "DeathstarWifi" vs config "DeathStarWiFi"). casefold()
        # rather than lower() because SSIDs are routinely non-ASCII and lower()
        # does not fold them fully (e.g. "ß" stays "ß" but casefolds to "ss").
        # Exact match otherwise -- no strip, no prefix -- and the subnet check
        # still gates AT_HOME. (US-743)
        return ssid.casefold() == self._ssid.casefold()

    def _isHomeSsidVisible(self) -> bool:
        """True when the home SSID is in the cached scan list.

        A failed cache read (``None``) is False: nmcli already answered "not
        associated", the AWAY it gave before US-776-e.
        """
        visible = self._scanReader()
        if not visible:
            return False
        return any(self._isHomeSsid(ssid) for ssid in visible)

    def _hasIpInHomeSubnet(self) -> bool | None:
        """True/False from a successful IP read; None when the read failed."""
        ips = self._ipReader()
        if ips is None:
            return None
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
