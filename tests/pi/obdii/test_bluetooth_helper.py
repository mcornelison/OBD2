################################################################################
# File Name: test_bluetooth_helper.py
# Purpose/Description: Tests for Bluetooth/rfcomm helper (TD-023 / US-193)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | Initial (US-193)
# ================================================================================
################################################################################

"""
Unit tests for `src.pi.obdii.bluetooth_helper`.

These tests run on Windows (no real rfcomm available) by injecting a
subprocess runner double. They cover:

- MAC address regex detection (Invariant: `^[0-9A-F]{2}(:[0-9A-F]{2}){5}$`)
- Idempotent rfcomm bind (already-bound-same-MAC short-circuits)
- Re-bind when existing bind points at a different MAC
- rfcomm release (idempotent when nothing is bound)
- stderr surfacing on non-zero exit
- US-211: isRfcommReachable probe short-circuits when device node
  missing and falls through to rfcomm show otherwise.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from src.pi.obdii import bluetooth_helper as bh

# ================================================================================
# Subprocess double
# ================================================================================

class FakeRunner:
    """
    Records invocations and replays canned completed processes.

    Each entry in `responses` is a tuple:
        (returncode, stdout, stderr)
    popped in order.  If exhausted, the runner raises.
    """

    def __init__(self, responses: list[tuple[int, str, str]] | None = None):
        self.responses = list(responses or [])
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        if not self.responses:
            raise AssertionError(f"FakeRunner out of responses for cmd={cmd}")
        rc, out, err = self.responses.pop(0)
        return subprocess.CompletedProcess(cmd, rc, out, err)


# ================================================================================
# MAC detection
# ================================================================================

class TestIsMacAddress:

    @pytest.mark.parametrize("value", [
        "00:04:3E:85:0D:FB",
        "AA:BB:CC:DD:EE:FF",
        "aa:bb:cc:dd:ee:ff",
        "12:34:56:78:9A:BC",
    ])
    def test_isMacAddress_validMac_returnsTrue(self, value: str) -> None:
        assert bh.isMacAddress(value) is True

    @pytest.mark.parametrize("value", [
        "/dev/rfcomm0",
        "/dev/ttyUSB0",
        "COM3",
        "00:04:3E:85:0D",       # 5 octets, not 6
        "00:04:3E:85:0D:FB:ZZ", # extra
        "0004.3E85.0DFB",       # wrong separator
        "",
        "   ",
        "00-04-3E-85-0D-FB",    # dash not colon
    ])
    def test_isMacAddress_nonMac_returnsFalse(self, value: str) -> None:
        assert bh.isMacAddress(value) is False


# ================================================================================
# bindRfcomm
# ================================================================================

class TestBindRfcomm:

    def test_bindRfcomm_notBound_runsBindAndReturnsPath(self) -> None:
        runner = FakeRunner(responses=[
            (1, "", "Can't get info for /dev/rfcomm0: No such device\n"),  # show
            (0, "", ""),                                                    # bind
        ])
        path = bh.bindRfcomm(
            macAddress="00:04:3E:85:0D:FB",
            device=0,
            channel=1,
            subprocessRunner=runner,
        )
        assert path == "/dev/rfcomm0"
        # show invoked first (idempotency check), then bind
        assert len(runner.calls) == 2
        assert runner.calls[0][0] == "rfcomm"
        assert runner.calls[0][1] == "show"
        assert runner.calls[1][0] == "rfcomm"
        assert runner.calls[1][1] == "bind"
        assert "00:04:3E:85:0D:FB" in runner.calls[1]
        assert "1" in runner.calls[1]

    def test_bindRfcomm_alreadyBoundSameMac_isNoOp(self) -> None:
        runner = FakeRunner(responses=[
            (0, "rfcomm0: 00:04:3E:85:0D:FB channel 1 clean\n", ""),  # show
        ])
        path = bh.bindRfcomm(
            macAddress="00:04:3E:85:0D:FB",
            device=0,
            channel=1,
            subprocessRunner=runner,
        )
        assert path == "/dev/rfcomm0"
        assert len(runner.calls) == 1  # only show, no bind

    def test_bindRfcomm_caseInsensitiveMacComparison(self) -> None:
        runner = FakeRunner(responses=[
            (0, "rfcomm0: 00:04:3e:85:0d:fb channel 1 clean\n", ""),  # show returns lowercase
        ])
        path = bh.bindRfcomm(
            macAddress="00:04:3E:85:0D:FB",  # request uppercase
            device=0,
            channel=1,
            subprocessRunner=runner,
        )
        assert path == "/dev/rfcomm0"
        assert len(runner.calls) == 1

    def test_bindRfcomm_boundToDifferentMac_releasesAndRebinds(self) -> None:
        runner = FakeRunner(responses=[
            (0, "rfcomm0: AA:BB:CC:DD:EE:FF channel 1 clean\n", ""),  # show: wrong MAC
            (0, "", ""),                                               # release
            (0, "", ""),                                               # bind
        ])
        path = bh.bindRfcomm(
            macAddress="00:04:3E:85:0D:FB",
            device=0,
            channel=1,
            subprocessRunner=runner,
        )
        assert path == "/dev/rfcomm0"
        assert len(runner.calls) == 3
        assert runner.calls[1][1] == "release"
        assert runner.calls[2][1] == "bind"

    def test_bindRfcomm_bindFails_raisesWithStderr(self) -> None:
        runner = FakeRunner(responses=[
            (1, "", "No such device\n"),
            (1, "", "Can't create device: Operation not permitted\n"),
        ])
        with pytest.raises(bh.BluetoothHelperError) as exc:
            bh.bindRfcomm(
                macAddress="00:04:3E:85:0D:FB",
                device=0,
                channel=1,
                subprocessRunner=runner,
            )
        # stderr surfaced, exact invocation in message
        assert "Operation not permitted" in str(exc.value)
        assert "rfcomm" in str(exc.value)
        assert "bind" in str(exc.value)

    def test_bindRfcomm_nonDefaultDeviceChannel_usedInPath(self) -> None:
        runner = FakeRunner(responses=[
            (1, "", "No such device\n"),
            (0, "", ""),
        ])
        path = bh.bindRfcomm(
            macAddress="00:04:3E:85:0D:FB",
            device=2,
            channel=3,
            subprocessRunner=runner,
        )
        assert path == "/dev/rfcomm2"
        bind_call = runner.calls[1]
        assert "2" in bind_call
        assert "3" in bind_call
        assert "00:04:3E:85:0D:FB" in bind_call

    def test_bindRfcomm_invalidMac_raisesValueError(self) -> None:
        runner = FakeRunner()
        with pytest.raises(ValueError):
            bh.bindRfcomm(
                macAddress="/dev/rfcomm0",
                device=0,
                channel=1,
                subprocessRunner=runner,
            )

    def test_bindRfcomm_runnerMissingCommand_raisesHelperError(self) -> None:
        def boom(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("rfcomm not found")

        with pytest.raises(bh.BluetoothHelperError) as exc:
            bh.bindRfcomm(
                macAddress="00:04:3E:85:0D:FB",
                device=0,
                channel=1,
                subprocessRunner=boom,
            )
        assert "rfcomm" in str(exc.value)


# ================================================================================
# releaseRfcomm
# ================================================================================

class TestReleaseRfcomm:

    def test_releaseRfcomm_bound_runsRelease(self) -> None:
        runner = FakeRunner(responses=[
            (0, "rfcomm0: 00:04:3E:85:0D:FB channel 1 clean\n", ""),  # show
            (0, "", ""),                                               # release
        ])
        bh.releaseRfcomm(device=0, subprocessRunner=runner)
        assert len(runner.calls) == 2
        assert runner.calls[1][1] == "release"
        assert "0" in runner.calls[1]

    def test_releaseRfcomm_notBound_isNoOp(self) -> None:
        runner = FakeRunner(responses=[
            (1, "", "Can't get info for /dev/rfcomm0: No such device\n"),  # show
        ])
        # Should not raise and not call release
        bh.releaseRfcomm(device=0, subprocessRunner=runner)
        assert len(runner.calls) == 1  # only show

    def test_releaseRfcomm_releaseFails_raises(self) -> None:
        runner = FakeRunner(responses=[
            (0, "rfcomm0: 00:04:3E:85:0D:FB channel 1 clean\n", ""),
            (1, "", "Can't release device: Operation not permitted\n"),
        ])
        with pytest.raises(bh.BluetoothHelperError) as exc:
            bh.releaseRfcomm(device=0, subprocessRunner=runner)
        assert "Operation not permitted" in str(exc.value)


# ================================================================================
# isRfcommBound
# ================================================================================

class TestIsRfcommBound:

    def test_isRfcommBound_bound_returnsTrue(self) -> None:
        runner = FakeRunner(responses=[
            (0, "rfcomm0: 00:04:3E:85:0D:FB channel 1 clean\n", ""),
        ])
        assert bh.isRfcommBound(device=0, subprocessRunner=runner) is True

    def test_isRfcommBound_notBound_returnsFalse(self) -> None:
        runner = FakeRunner(responses=[
            (1, "", "Can't get info for /dev/rfcomm0: No such device\n"),
        ])
        assert bh.isRfcommBound(device=0, subprocessRunner=runner) is False


# ================================================================================
# parseShowOutput (internal, but pins contract)
# ================================================================================

class TestParseShowOutput:

    def test_parseShowOutput_parsesMacChannel(self) -> None:
        line = "rfcomm0: 00:04:3E:85:0D:FB channel 1 clean\n"
        info = bh._parseShowOutput(line)
        assert info is not None
        assert info.macAddress.lower() == "00:04:3e:85:0d:fb"
        assert info.channel == 1

    def test_parseShowOutput_noMacReturnsNone(self) -> None:
        assert bh._parseShowOutput("") is None
        assert bh._parseShowOutput("garbage\n") is None


# ================================================================================
# US-211 -- isRfcommReachable probe
# ================================================================================

class TestIsRfcommReachable:
    """The reconnect loop fires this probe every backoff cycle.

    Two layers:
      1. stat(/dev/rfcommN) -- short-circuit False when node missing.
      2. rfcomm show N -- False if unbound, True if bound.
    """

    def test_reachable_when_node_exists_and_rfcomm_show_reports_bound(self) -> None:
        runner = FakeRunner([
            (0, "rfcomm0: 00:04:3E:85:0D:FB channel 1 clean\n", ""),
        ])
        assert bh.isRfcommReachable(
            device=0,
            subprocessRunner=runner,
            pathExists=lambda path: True,
        ) is True
        # Exactly one rfcomm show call.
        assert runner.calls == [["rfcomm", "show", "0"]]

    def test_unreachable_when_node_missing_shortCircuits(self) -> None:
        """Layer 1 fails -> layer 2 never runs -> runner has no calls."""
        runner = FakeRunner()  # No responses -- would raise if called.
        assert bh.isRfcommReachable(
            device=0,
            subprocessRunner=runner,
            pathExists=lambda path: False,
        ) is False
        assert runner.calls == []

    def test_unreachable_when_rfcomm_show_reports_unbound(self) -> None:
        runner = FakeRunner([
            (1, "", "Can't get info for /dev/rfcomm0: No such device\n"),
        ])
        assert bh.isRfcommReachable(
            device=0,
            subprocessRunner=runner,
            pathExists=lambda path: True,
        ) is False

    def test_unreachable_when_rfcomm_raises_BluetoothHelperError(self) -> None:
        runner = FakeRunner([
            (2, "", "rfcomm: Permission denied\n"),
        ])
        # _runShow raises BluetoothHelperError on unrecognized stderr; the
        # probe must swallow that and return False (not crash the loop).
        assert bh.isRfcommReachable(
            device=0,
            subprocessRunner=runner,
            pathExists=lambda path: True,
        ) is False

    def test_unreachable_when_pathExists_raises(self) -> None:
        """Defense-in-depth: a crashing stat-check is treated as 'not reachable'."""
        def raising(path: str) -> bool:
            raise OSError("I/O error")

        runner = FakeRunner()  # Not reached.
        assert bh.isRfcommReachable(
            device=0,
            subprocessRunner=runner,
            pathExists=raising,
        ) is False
        assert runner.calls == []

    def test_device_zero_is_the_default(self) -> None:
        """Bare isRfcommReachable() with no device arg checks /dev/rfcomm0."""
        observed: list[str] = []

        def trackingExists(path: str) -> bool:
            observed.append(path)
            return False

        bh.isRfcommReachable(pathExists=trackingExists)
        assert observed == ["/dev/rfcomm0"]
