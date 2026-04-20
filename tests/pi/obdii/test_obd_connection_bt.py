################################################################################
# File Name: test_obd_connection_bt.py
# Purpose/Description: Bluetooth-path connection tests with mocked subprocess
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | Initial (US-196 — US-167 AC #7 carryforward)
# ================================================================================
################################################################################

"""
Mocked Bluetooth connection tests — US-167 AC #7 carryforward.

Where ``test_obd_connection_mac_vs_path.py`` already covers the basic
MAC-vs-path resolution logic at the obdFactory boundary, this file
exercises the *subprocess layer* that bluetooth_helper sits on, so we
catch regressions in the rfcomm-shell edge cases without needing a real
dongle:

  - rfcomm binary missing on PATH (bluez not installed) surfaces a clear
    message, not a cryptic FileNotFoundError at the python-obd edge.
  - Already-bonded (Session 23 state) pre-bound rfcomm short-circuits —
    same MAC is a no-op, different MAC triggers release+rebind.
  - Multiple consecutive connect/disconnect cycles do not leak rfcomm
    bindings (we release exactly as many times as we bound).
  - A transient rfcomm-bind failure (e.g. bluetooth.service restarting)
    raises a BluetoothHelperError containing the exact command string
    + stderr for operator diagnosis.

No real Bluetooth hardware, no pyserial, no bluez required to run — all
subprocess calls are intercepted via the injected runner.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from src.pi.obdii import bluetooth_helper as bh
from src.pi.obdii.obd_connection import ObdConnection

# ================================================================================
# Fakes
# ================================================================================


class FakeSubprocessRunner:
    """Scripted subprocess runner — returns canned CompletedProcess objects."""

    def __init__(self, responses: list[tuple[int, str, str]]) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        if not self.responses:
            raise AssertionError(f"FakeSubprocessRunner exhausted on cmd={cmd}")
        rc, out, err = self.responses.pop(0)
        return subprocess.CompletedProcess(cmd, rc, out, err)


class _FakeObd:
    """Minimal ``obd.OBD`` double honouring the interface ObdConnection uses."""

    def __init__(self) -> None:
        self._connected = True
        self.closeCount = 0

    def is_connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        self._connected = False
        self.closeCount += 1


class RecordingObdFactory:
    """Records the port-string ObdConnection hands to ``obd.OBD``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.instances: list[_FakeObd] = []

    def __call__(self, portstr: str, timeout: int) -> _FakeObd:
        self.calls.append({"portstr": portstr, "timeout": timeout})
        instance = _FakeObd()
        self.instances.append(instance)
        return instance


def _config(mac: str = "00:04:3E:85:0D:FB", **overrides: Any) -> dict[str, Any]:
    bluetooth: dict[str, Any] = {
        "macAddress": mac,
        "retryDelays": [],           # fast tests
        "maxRetries": 0,
        "connectionTimeoutSeconds": 5,
    }
    bluetooth.update(overrides)
    return {"pi": {"bluetooth": bluetooth}}


# ================================================================================
# rfcomm binary missing on PATH
# ================================================================================


class TestBluezNotInstalled:

    def test_rfcomm_missing_surfaces_clear_helper_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If bluez isn't installed, the error names the binary — not a bare ENOENT."""

        def missingRunner(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError(cmd[0])

        # Exercise the helper directly — this is the layer nearest the OS that
        # translates "binary missing" into a user-facing BluetoothHelperError.
        with pytest.raises(bh.BluetoothHelperError) as excinfo:
            bh.bindRfcomm(
                "00:04:3E:85:0D:FB",
                subprocessRunner=missingRunner,
            )

        msg = str(excinfo.value)
        assert "rfcomm" in msg, f"error must name the missing binary: {msg!r}"
        assert "bluez" in msg.lower(), (
            f"error should hint at bluez install: {msg!r}"
        )


# ================================================================================
# Session 23 pre-bonded state
# ================================================================================


class TestSession23PreBondedState:

    def test_already_bound_same_mac_is_no_op(self) -> None:
        """rfcomm show returns the same MAC → no bind invocation happens."""
        mac = "00:04:3E:85:0D:FB"
        runner = FakeSubprocessRunner([
            # rfcomm show 0 → already bound to our MAC
            (0, f"rfcomm0: {mac} channel 1 clean\n", ""),
        ])

        path = bh.bindRfcomm(mac, subprocessRunner=runner)

        assert path == "/dev/rfcomm0"
        # Exactly one call: the show. No bind, no release.
        assert len(runner.calls) == 1
        assert runner.calls[0][:2] == ["rfcomm", "show"]

    def test_bound_to_different_mac_triggers_release_then_rebind(self) -> None:
        """rfcomm show returns a stale MAC → release + fresh bind."""
        runner = FakeSubprocessRunner([
            # show → bound to a stale MAC
            (0, "rfcomm0: AA:BB:CC:DD:EE:FF channel 1 clean\n", ""),
            (0, "", ""),  # release succeeds
            (0, "", ""),  # bind succeeds
        ])

        path = bh.bindRfcomm("11:22:33:44:55:66", subprocessRunner=runner)

        assert path == "/dev/rfcomm0"
        assert runner.calls[0][:2] == ["rfcomm", "show"]
        assert runner.calls[1][:2] == ["rfcomm", "release"]
        assert runner.calls[2][:2] == ["rfcomm", "bind"]
        assert runner.calls[2][3] == "11:22:33:44:55:66"


# ================================================================================
# Connect/disconnect cycles don't leak bindings
# ================================================================================


class TestMultipleConnectCycles:

    def test_three_cycles_release_count_matches_bind_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bindCount = {"n": 0}
        releaseCount = {"n": 0}

        def fakeBind(
            macAddress: str,
            device: int = 0,
            channel: int = 1,
            subprocessRunner: Any = None,
        ) -> str:
            bindCount["n"] += 1
            return f"/dev/rfcomm{device}"

        def fakeRelease(device: int = 0, subprocessRunner: Any = None) -> None:
            releaseCount["n"] += 1

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.bindRfcomm", fakeBind
        )
        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.releaseRfcomm", fakeRelease
        )

        factory = RecordingObdFactory()
        conn = ObdConnection(config=_config(), database=None, obdFactory=factory)

        for _ in range(3):
            assert conn.connect() is True
            conn.disconnect()

        assert bindCount["n"] == 3
        assert releaseCount["n"] == 3
        assert len(factory.calls) == 3

    def test_path_style_cycles_never_release(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Path-style config (no MAC) must never touch rfcomm release — ownership is the operator's."""
        releaseCalls: list[int] = []
        bindCalls: list[str] = []

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.bindRfcomm",
            lambda macAddress, device=0, channel=1, subprocessRunner=None: (
                bindCalls.append(macAddress) or f"/dev/rfcomm{device}"
            ),
        )
        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.releaseRfcomm",
            lambda device=0, subprocessRunner=None: releaseCalls.append(device),
        )

        factory = RecordingObdFactory()
        conn = ObdConnection(
            config=_config("/dev/rfcomm0"), database=None, obdFactory=factory
        )

        for _ in range(2):
            conn.connect()
            conn.disconnect()

        assert bindCalls == []           # MAC path never invoked
        assert releaseCalls == []        # no instance-owned bind → no release


# ================================================================================
# Transient rfcomm-bind failure diagnosis
# ================================================================================


class TestTransientBindFailureDiagnosis:

    def test_bind_stderr_surfaces_in_error(self) -> None:
        """rfcomm bind failure with stderr → BluetoothHelperError preserves it verbatim."""
        runner = FakeSubprocessRunner([
            (1, "", "rfcomm show 0: No such device\n"),  # not bound — OK to proceed
            (1, "", "Can't create device: Operation not permitted\n"),  # bind fails
        ])

        with pytest.raises(bh.BluetoothHelperError) as excinfo:
            bh.bindRfcomm("00:04:3E:85:0D:FB", subprocessRunner=runner)

        msg = str(excinfo.value)
        # Exact stderr surfaces
        assert "Operation not permitted" in msg
        # And the exact command that failed
        assert "rfcomm bind 0 00:04:3E:85:0D:FB 1" in msg


# ================================================================================
# rfcomm show parse sanity
# ================================================================================


class TestRfcommShowParsing:

    def test_blank_output_returns_none(self) -> None:
        """Empty rfcomm-show output (device not bound) parses to None."""
        runner = FakeSubprocessRunner([(0, "", "")])
        assert bh.isRfcommBound(subprocessRunner=runner) is False

    def test_no_such_device_stderr_returns_not_bound(self) -> None:
        runner = FakeSubprocessRunner([(1, "", "No such device\n")])
        assert bh.isRfcommBound(subprocessRunner=runner) is False

    def test_bound_output_returns_true(self) -> None:
        runner = FakeSubprocessRunner([
            (0, "rfcomm0: 00:04:3E:85:0D:FB channel 1 clean\n", "")
        ])
        assert bh.isRfcommBound(subprocessRunner=runner) is True


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
