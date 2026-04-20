################################################################################
# File Name: test_obd_connection_mac_vs_path.py
# Purpose/Description: Tests that obd_connection resolves MAC -> rfcomm path (US-193 / TD-023)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | Initial (US-193 — fix MAC-as-serial-port bug)
# ================================================================================
################################################################################

"""
Regression tests for the TD-023 bug.

The bug: `src/pi/obdii/obd_connection.py` passed the Bluetooth MAC
directly into `obd.OBD(port=...)` which pyserial-opens the MAC string as a
device path and raises ENOENT.

The fix: if the configured port looks like a MAC, resolve it to a
`/dev/rfcommN` path via an idempotent rfcomm bind *before* handing it to
`obd.OBD()`. If it already looks like a path (e.g. `/dev/rfcomm0`), pass
it through unchanged for backwards compatibility.

These tests drive obd_connection via the `obdFactory` injection so no
real OBD hardware is required. The bluetooth_helper module is
monkeypatched so no real rfcomm is required either.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.pi.obdii.obd_connection import ObdConnection


class _RecordingFactory:
    """Captures the port string handed to the fake OBD factory."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, portstr: str, timeout: int) -> Any:
        self.calls.append({"portstr": portstr, "timeout": timeout})

        class _Ok:
            def is_connected(self) -> bool:
                return True

            def close(self) -> None:
                pass

        return _Ok()


def _buildConfig(port: str, **overrides: Any) -> dict[str, Any]:
    bluetooth = {
        "macAddress": port,
        "retryDelays": [],        # fast tests
        "maxRetries": 0,
        "connectionTimeoutSeconds": 5,
    }
    bluetooth.update(overrides)
    return {"pi": {"bluetooth": bluetooth}}


# ================================================================================
# MAC input path
# ================================================================================

class TestMacInputResolvesToRfcommPath:

    def test_connect_macConfigured_bindsAndPassesPathToFactory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bindCalls: list[dict[str, Any]] = []

        def fakeBind(
            macAddress: str, device: int = 0, channel: int = 1, subprocessRunner: Any = None
        ) -> str:
            bindCalls.append({"mac": macAddress, "device": device, "channel": channel})
            return f"/dev/rfcomm{device}"

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.bindRfcomm", fakeBind
        )
        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.releaseRfcomm",
            lambda device=0, subprocessRunner=None: None,
        )

        factory = _RecordingFactory()
        config = _buildConfig("00:04:3E:85:0D:FB")
        conn = ObdConnection(config=config, database=None, obdFactory=factory)

        ok = conn.connect()

        assert ok is True
        assert len(bindCalls) == 1
        assert bindCalls[0]["mac"] == "00:04:3E:85:0D:FB"
        # Factory saw the resolved serial path, not the MAC
        assert len(factory.calls) == 1
        assert factory.calls[0]["portstr"] == "/dev/rfcomm0"

    def test_connect_usesConfiguredDeviceAndChannel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def fakeBind(
            macAddress: str, device: int = 0, channel: int = 1, subprocessRunner: Any = None
        ) -> str:
            seen.update({"mac": macAddress, "device": device, "channel": channel})
            return f"/dev/rfcomm{device}"

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.bindRfcomm", fakeBind
        )
        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.releaseRfcomm",
            lambda device=0, subprocessRunner=None: None,
        )

        factory = _RecordingFactory()
        config = _buildConfig(
            "00:04:3E:85:0D:FB", rfcommDevice=2, rfcommChannel=3
        )
        conn = ObdConnection(config=config, database=None, obdFactory=factory)

        conn.connect()

        assert seen["device"] == 2
        assert seen["channel"] == 3
        assert factory.calls[0]["portstr"] == "/dev/rfcomm2"

    def test_connect_bindFails_surfacesStderrAndReturnsFalse(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from src.pi.obdii.bluetooth_helper import BluetoothHelperError

        def failingBind(*_: Any, **__: Any) -> str:
            raise BluetoothHelperError(
                "rfcomm bind 0 00:04:3E:85:0D:FB 1 failed (rc=1): "
                "Can't create device: Operation not permitted"
            )

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.bindRfcomm", failingBind
        )
        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.releaseRfcomm",
            lambda device=0, subprocessRunner=None: None,
        )

        factory = _RecordingFactory()
        config = _buildConfig("00:04:3E:85:0D:FB")
        conn = ObdConnection(config=config, database=None, obdFactory=factory)

        # Bind errors are surfaced; connect() returns False after retries
        caplog.set_level("WARNING")
        ok = conn.connect()
        assert ok is False
        # stderr surfaced into the log with the exact command attempted
        assert any(
            "rfcomm bind 0 00:04:3E:85:0D:FB 1" in rec.message
            for rec in caplog.records
        )
        assert any(
            "Operation not permitted" in rec.message for rec in caplog.records
        )
        # factory NOT called because we never got a path
        assert factory.calls == []


# ================================================================================
# Path (BC) input
# ================================================================================

class TestPathInputPassesThroughUnchanged:

    def test_connect_rfcommPathConfigured_skipsBindAndUsesPath(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"bind": 0}

        def fakeBind(*_: Any, **__: Any) -> str:
            called["bind"] += 1
            return "/dev/rfcomm0"

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.bindRfcomm", fakeBind
        )
        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.releaseRfcomm",
            lambda device=0, subprocessRunner=None: None,
        )

        factory = _RecordingFactory()
        config = _buildConfig("/dev/rfcomm0")
        conn = ObdConnection(config=config, database=None, obdFactory=factory)

        ok = conn.connect()

        assert ok is True
        assert called["bind"] == 0
        assert factory.calls[0]["portstr"] == "/dev/rfcomm0"


# ================================================================================
# Idempotent reconnect after connection drop
# ================================================================================

class TestIdempotentReconnect:

    def test_connect_twice_bindCalledTwiceAndReleaseBetween(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bindCalls: list[str] = []
        releaseCalls: list[int] = []

        def fakeBind(
            macAddress: str, device: int = 0, channel: int = 1, subprocessRunner: Any = None
        ) -> str:
            bindCalls.append(macAddress)
            return f"/dev/rfcomm{device}"

        def fakeRelease(device: int = 0, subprocessRunner: Any = None) -> None:
            releaseCalls.append(device)

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.bindRfcomm", fakeBind
        )
        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.releaseRfcomm", fakeRelease
        )

        factory = _RecordingFactory()
        config = _buildConfig("00:04:3E:85:0D:FB")
        conn = ObdConnection(config=config, database=None, obdFactory=factory)

        assert conn.connect() is True
        conn.disconnect()
        assert conn.connect() is True

        assert len(bindCalls) == 2
        # release happened once (on disconnect); bind idempotency handled by helper
        assert len(releaseCalls) == 1


# ================================================================================
# disconnect releases rfcomm
# ================================================================================

class TestDisconnectReleasesRfcomm:

    def test_disconnect_afterMacConnect_callsReleaseRfcomm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        releaseCalls: list[int] = []

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.bindRfcomm",
            lambda macAddress, device=0, channel=1, subprocessRunner=None: f"/dev/rfcomm{device}",
        )
        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.releaseRfcomm",
            lambda device=0, subprocessRunner=None: releaseCalls.append(device),
        )

        factory = _RecordingFactory()
        config = _buildConfig("00:04:3E:85:0D:FB")
        conn = ObdConnection(config=config, database=None, obdFactory=factory)

        conn.connect()
        conn.disconnect()

        assert releaseCalls == [0]

    def test_disconnect_afterPathConnect_doesNotCallRelease(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        releaseCalls: list[int] = []

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.bindRfcomm",
            lambda macAddress, device=0, channel=1, subprocessRunner=None: "/dev/rfcomm0",
        )
        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.releaseRfcomm",
            lambda device=0, subprocessRunner=None: releaseCalls.append(device),
        )

        factory = _RecordingFactory()
        config = _buildConfig("/dev/rfcomm0")
        conn = ObdConnection(config=config, database=None, obdFactory=factory)

        conn.connect()
        conn.disconnect()

        assert releaseCalls == []  # path-style: we did not bind, so do not release
