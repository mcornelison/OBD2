################################################################################
# File Name: test_home_detector_joining.py
# Purpose/Description: US-776-e -- AT_HOME_JOINING: the home SSID is in
#                      NetworkManager's cached scan list but the Pi is not
#                      associated (yet). Measured on drive 96: the rejoin
#                      lands ~49 s after arriving home.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-01    | Rex          | Initial -- US-776-e JOINING detection.
# ================================================================================
################################################################################
"""US-776-e: the detector reports AT_HOME_JOINING from the cached scan list."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

from src.pi.network import HomeNetworkDetector, HomeNetworkState, home_detector
from src.pi.network.home_detector import _readVisibleSsidsViaNmcli

_HOME_SSID = "DeathStarWiFi"


def _config() -> dict[str, Any]:
    return {
        "pi": {
            "homeNetwork": {
                "ssid": _HOME_SSID,
                "subnet": "10.27.27.0/24",
                "pingTimeoutSeconds": 3,
                "serverPingPath": "/api/v1/health",
            },
            "companionService": {"baseUrl": "http://10.27.27.10:8000"},
        },
    }


class _Response:
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _Opener:
    """urlopen stand-in that counts calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _req: object, timeout: float) -> _Response:
        self.calls += 1
        return _Response()


def _nmcli(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["nmcli"], returncode=returncode, stdout=stdout, stderr="",
    )


def _detector(
    ssid: Callable[[], str | None],
    scan: Callable[[], list[str] | None],
    *,
    ips: list[str] | None = None,
    opener: _Opener | None = None,
) -> HomeNetworkDetector:
    return HomeNetworkDetector(
        _config(),
        ssidReader=ssid,
        ipReader=lambda: ips,
        scanReader=scan,
        httpOpener=opener or _Opener(),
        apiKey="test-key",
    )


# =============================================================================
# The cached-scan reader
# =============================================================================


class TestReadVisibleSsids:

    def test_listsEverySsidInTheCache_activeOrNot_unescaped(self) -> None:
        completed = _nmcli("no:Neighbour\nno:DeathstarWifi\nyes:Net\\:Work\n")
        with patch("src.pi.network.home_detector.subprocess.run", return_value=completed):
            assert _readVisibleSsidsViaNmcli() == ["Neighbour", "DeathstarWifi", "Net:Work"]

    def test_hiddenNetworkWithEmptySsid_skipped(self) -> None:
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=_nmcli("no:\nno:Neighbour\n")):
            assert _readVisibleSsidsViaNmcli() == ["Neighbour"]

    def test_emptyCache_emptyList(self) -> None:
        with patch("src.pi.network.home_detector.subprocess.run", return_value=_nmcli("")):
            assert _readVisibleSsidsViaNmcli() == []

    def test_nonZeroExit_emptyList(self) -> None:
        """Same reading as the association reader: nmcli ran, nothing to list."""
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=_nmcli("", returncode=10)):
            assert _readVisibleSsidsViaNmcli() == []

    @pytest.mark.parametrize(
        "failure",
        [
            FileNotFoundError("nmcli"),
            subprocess.TimeoutExpired(cmd="nmcli", timeout=2.0),
            OSError("exec format error"),
        ],
        ids=["missing", "timeout", "osError"],
    )
    def test_infraFailure_none(self, failure: BaseException) -> None:
        with patch("src.pi.network.home_detector.subprocess.run", side_effect=failure):
            assert _readVisibleSsidsViaNmcli() is None

    def test_command_readsTheCacheOnly_noRescanNoConUp_boundedTimeout(self) -> None:
        """Never force a rescan or `nmcli con up` (polkit rights the user lacks)."""
        with patch("src.pi.network.home_detector.subprocess.run",
                   return_value=_nmcli("")) as run:
            _readVisibleSsidsViaNmcli()
        argv = run.call_args.args[0]
        assert argv[0] == "nmcli"
        assert argv[argv.index("--rescan") + 1] == "no"
        assert "con" not in argv and "connection" not in argv and "up" not in argv
        assert 0 < run.call_args.kwargs["timeout"] <= home_detector._NMCLI_TIMEOUT_SECONDS
        assert run.call_args.kwargs["encoding"] == "utf-8"

    def test_defaultScanReader_isTheNmcliCacheReader(self) -> None:
        detector = HomeNetworkDetector(_config())
        assert detector._scanReader is _readVisibleSsidsViaNmcli


# =============================================================================
# _computeState -> AT_HOME_JOINING
# =============================================================================


class TestJoiningState:

    def test_homeSsidVisible_notAssociated_joining(self) -> None:
        """Case differs from config, as on the live router (US-743 casefold)."""
        opener = _Opener()
        detector = _detector(lambda: "", lambda: ["Neighbour", "DeathstarWifi"], opener=opener)

        assert detector.getHomeNetworkState() == HomeNetworkState.AT_HOME_JOINING
        # Not associated: there is no route to probe yet.
        assert opener.calls == 0
        assert detector.lastProbe is None

    def test_homeSsidNotVisible_notAssociated_away(self) -> None:
        assert _detector(lambda: "", lambda: ["Neighbour"]).getHomeNetworkState() == (
            HomeNetworkState.AWAY
        )

    def test_emptyScan_notAssociated_away(self) -> None:
        assert _detector(lambda: "", lambda: []).getHomeNetworkState() == HomeNetworkState.AWAY

    def test_scanReadFailed_notAssociated_stillAway(self) -> None:
        """nmcli answered 'not associated'; a failed cache read adds nothing to it."""
        assert _detector(lambda: "", lambda: None).getHomeNetworkState() == HomeNetworkState.AWAY

    def test_foreignSsidAssociated_homeVisible_awayWithoutReadingTheScan(self) -> None:
        """A foreign association stays AWAY (US-776-c); JOINING needs no association."""
        scans: list[str] = []

        def scan() -> list[str]:
            scans.append("scan")
            return [_HOME_SSID]

        assert _detector(lambda: "CoffeeShop", scan).getHomeNetworkState() == (
            HomeNetworkState.AWAY
        )
        assert scans == []

    def test_associatedHome_scanNotRead(self) -> None:
        scans: list[str] = []

        def scan() -> list[str]:
            scans.append("scan")
            return [_HOME_SSID]

        state = _detector(lambda: _HOME_SSID, scan, ips=["10.27.27.28"]).getHomeNetworkState()
        assert state == HomeNetworkState.AT_HOME_SERVER_REACHABLE
        assert scans == []

    def test_deadSsidReader_unknownNotJoining(self) -> None:
        """A dead association read is UNKNOWN (US-776-c), whatever the cache says."""
        state = _detector(lambda: None, lambda: [_HOME_SSID], ips=["10.27.27.28"])
        assert state.getHomeNetworkState() == HomeNetworkState.UNKNOWN

    def test_joiningThenAssociated_transitionLogged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        reads = iter(["", _HOME_SSID])
        detector = _detector(lambda: next(reads), lambda: [_HOME_SSID], ips=["10.27.27.28"])

        with caplog.at_level(logging.INFO, logger="src.pi.network.home_detector"):
            first = detector.getHomeNetworkState()
            second = detector.getHomeNetworkState()

        assert first == HomeNetworkState.AT_HOME_JOINING
        assert second == HomeNetworkState.AT_HOME_SERVER_REACHABLE
        assert "at_home_joining -> at_home_server_reachable" in caplog.text


# =============================================================================
# The DEFAULT nmcli readers through the state (faked subprocess)
# =============================================================================


class TestDefaultNmcliThroughState:

    def _state(self, nmclis: list[str], hostname: str = "\n") -> list[HomeNetworkState]:
        """One getHomeNetworkState() per nmcli output; both readers see it."""
        detector = HomeNetworkDetector(_config(), httpOpener=_Opener(), apiKey="test-key")
        current = {"stdout": ""}

        def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            if argv[0] == "nmcli":
                return _nmcli(current["stdout"])
            if argv[0] == "hostname":
                return subprocess.CompletedProcess(argv, 0, hostname, "")
            raise AssertionError(f"unexpected subprocess call: {argv}")

        states: list[HomeNetworkState] = []
        with patch("src.pi.network.home_detector.subprocess.run", side_effect=run):
            for stdout in nmclis:
                current["stdout"] = stdout
                states.append(detector.getHomeNetworkState())
        return states

    def test_visibleUnassociated_joining(self) -> None:
        assert self._state(["no:Neighbour\nno:DeathstarWifi\n"]) == [
            HomeNetworkState.AT_HOME_JOINING
        ]

    def test_notVisible_away(self) -> None:
        assert self._state(["no:Neighbour\n"]) == [HomeNetworkState.AWAY]

    def test_visibleThenAssociated_joiningThenAtHome(self) -> None:
        states = self._state(
            ["no:DeathstarWifi\n", "yes:DeathstarWifi\n"], hostname="10.27.27.28\n",
        )
        assert states == [
            HomeNetworkState.AT_HOME_JOINING,
            HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        ]
