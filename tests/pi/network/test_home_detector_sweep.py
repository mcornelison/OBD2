################################################################################
# File Name: test_home_detector_sweep.py
# Purpose/Description: Tests for HomeNetworkDetector.sweep() (US-776-j1) -- ONE
#                      bounded, forced WiFi scan that says whether home is
#                      ACTIVE_HOME, VISIBLE, NOT_VISIBLE, or the scan FAILED.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-11    | Rex          | Initial implementation for US-776-j1
# ================================================================================
################################################################################

"""
Tests for :meth:`src.pi.network.home_detector.HomeNetworkDetector.sweep`.

The cached scan list (``--rescan no``) often lacks home right after a drive,
so a key-off at home read AWAY.  The sweep forces one scan, bounded by
``pi.homeNetwork.sweepTimeoutSec``, and answers from that one call alone.
A scan that cannot answer (not authorized, non-zero exit, timeout, nmcli
missing) is FAILED -- never NOT_VISIBLE, which would read as AWAY.

Every test drives a fake ``subprocess.run``-compatible runner; no real nmcli.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from src.common.config.validator import DEFAULTS
from src.pi.network.home_detector import (
    NMCLI_SWEEP_COMMAND,
    HomeNetworkDetector,
    SweepResult,
)

_HOME = "DeathStarWiFi"


class _FakeRunner:
    """subprocess.run stand-in: records the call, returns or raises as scripted."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        raises: BaseException | None = None,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode
        self._raises = raises
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(args), kwargs))
        if self._raises is not None:
            raise self._raises
        return subprocess.CompletedProcess(
            args, self._returncode, stdout=self._stdout, stderr=self._stderr,
        )


def _detector(runner: _FakeRunner, **homeNetwork: Any) -> HomeNetworkDetector:
    config = {"pi": {"homeNetwork": {"ssid": _HOME, **homeNetwork}}}
    return HomeNetworkDetector(config, sweepRunner=runner)


# --- mapping ------------------------------------------------------------------


def test_sweep_homePresentNotAssociated_isVisible() -> None:
    runner = _FakeRunner(stdout="yes:NeighborNet\nno:DeathStarWiFi\nno:Other\n")

    assert _detector(runner).sweep() is SweepResult.VISIBLE


def test_sweep_homeAssociated_isActiveHome() -> None:
    runner = _FakeRunner(stdout="no:NeighborNet\nyes:DeathStarWiFi\n")

    assert _detector(runner).sweep() is SweepResult.ACTIVE_HOME


def test_sweep_homeAbsent_isNotVisible() -> None:
    runner = _FakeRunner(stdout="yes:GasStationGuest\nno:Starbucks\n")

    assert _detector(runner).sweep() is SweepResult.NOT_VISIBLE


def test_sweep_emptyListSuccessfulScan_isNotVisible() -> None:
    """A scan that worked and found nothing is a positive 'home not here'."""
    runner = _FakeRunner(stdout="")

    assert _detector(runner).sweep() is SweepResult.NOT_VISIBLE


def test_sweep_homeInDifferentCase_isVisible() -> None:
    """US-743: live 'DeathstarWifi' vs config 'DeathStarWiFi' -- casefold match."""
    runner = _FakeRunner(stdout="no:DeathstarWifi\n")

    assert _detector(runner).sweep() is SweepResult.VISIBLE


def test_sweep_escapedColonInSsid_isUnescapedBeforeMatch() -> None:
    runner = _FakeRunner(stdout="no:Death\\:Star\n")
    config = {"pi": {"homeNetwork": {"ssid": "Death:Star"}}}

    assert HomeNetworkDetector(config, sweepRunner=runner).sweep() is SweepResult.VISIBLE


# --- failure is FAILED, never NOT_VISIBLE -------------------------------------


def test_sweep_notAuthorized_isFailed() -> None:
    runner = _FakeRunner(
        stderr="Error: org.freedesktop.NetworkManager.wifi.scan request failed: "
               "not authorized.\n",
        returncode=1,
    )

    assert _detector(runner).sweep() is SweepResult.FAILED


def test_sweep_notAuthorizedWithZeroExitAndCachedRows_isFailed() -> None:
    """The refusal is FAILED even if nmcli still prints its cached list.

    That list is the stale cache the sweep exists to replace; a NOT_VISIBLE
    from it would be the very AWAY this story removes.
    """
    runner = _FakeRunner(
        stdout="yes:Starbucks\n",
        stderr="Warning: wifi.scan request failed: not authorized\n",
        returncode=0,
    )

    assert _detector(runner).sweep() is SweepResult.FAILED


def test_sweep_nonZeroExit_isFailed() -> None:
    runner = _FakeRunner(stdout="", stderr="Error: NetworkManager is not running.", returncode=8)

    assert _detector(runner).sweep() is SweepResult.FAILED


def test_sweep_timeout_isFailed() -> None:
    runner = _FakeRunner(raises=subprocess.TimeoutExpired(NMCLI_SWEEP_COMMAND, 6))

    assert _detector(runner).sweep() is SweepResult.FAILED


@pytest.mark.parametrize("exc", [FileNotFoundError("nmcli"), OSError("boom")])
def test_sweep_nmcliUnavailable_isFailed(exc: BaseException) -> None:
    runner = _FakeRunner(raises=exc)

    assert _detector(runner).sweep() is SweepResult.FAILED


# --- one call, the forced-scan command, bounded by config ---------------------


def test_sweep_runsExactlyOneForcedScanCommand() -> None:
    runner = _FakeRunner(stdout="no:DeathStarWiFi\n")

    _detector(runner).sweep()

    assert len(runner.calls) == 1
    args, _kwargs = runner.calls[0]
    assert args == [
        "nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi", "list", "--rescan", "yes",
    ]


def test_sweep_timeoutComesFromConfig() -> None:
    runner = _FakeRunner(stdout="")

    _detector(runner, sweepTimeoutSec=4.5).sweep()

    _args, kwargs = runner.calls[0]
    assert kwargs["timeout"] == 4.5


def test_sweep_timeoutDefaultsToTheValidatorDefault() -> None:
    runner = _FakeRunner(stdout="")

    _detector(runner).sweep()

    _args, kwargs = runner.calls[0]
    assert kwargs["timeout"] == DEFAULTS["pi.homeNetwork.sweepTimeoutSec"] == 6


def test_sweep_doesNotTouchTheCachedReaders() -> None:
    """The sweep answers from its one call; the cached SSID/scan readers stay unused."""
    runner = _FakeRunner(stdout="no:DeathStarWiFi\n")

    def _boom() -> Any:
        raise AssertionError("cached reader called by sweep()")

    detector = HomeNetworkDetector(
        {"pi": {"homeNetwork": {"ssid": _HOME}}},
        sweepRunner=runner, ssidReader=_boom, scanReader=_boom, ipReader=_boom,
    )

    assert detector.sweep() is SweepResult.VISIBLE
