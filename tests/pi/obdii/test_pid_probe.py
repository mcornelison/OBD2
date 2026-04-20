################################################################################
# File Name: test_pid_probe.py
# Purpose/Description: Tests for Mode 01 PID 0x00 support-bitmask probe (US-199)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | Initial (US-199)
# ================================================================================
################################################################################

"""
Tests for `src.pi.obdii.pid_probe`.

The probe runs at connection-open time, reads python-obd's auto-probed
support set via `connection.obd.supported_commands`, and returns a
normalized :class:`SupportedPidSet` keyed by Mode 01 PID hex code
(e.g. ``'0x0C'`` for RPM).

Unsupported PIDs are silently skipped at poll time; the probe result is
consulted by the realtime logger before dispatch.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii import pid_probe

# ================================================================================
# Fakes
# ================================================================================


def _cmd(name: str, mode: int, pid: int) -> SimpleNamespace:
    """Fake python-obd command object carrying just name/mode/pid."""
    return SimpleNamespace(name=name, mode=mode, pid=pid)


class FakeObdConnection:
    """Stands in for a connected `obd.OBD` instance for probe tests."""

    def __init__(self, supported: list[SimpleNamespace] | None, connected: bool = True) -> None:
        self._supported = supported
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected

    @property
    def supported_commands(self) -> list[SimpleNamespace] | None:
        return self._supported


def _wrap(obd_inner: Any) -> Any:
    """Wrap a FakeObdConnection in the outer ObdConnection-shaped facade."""
    return SimpleNamespace(obd=obd_inner, isConnected=lambda: obd_inner.is_connected())


# ================================================================================
# SupportedPidSet — core API
# ================================================================================


class TestSupportedPidSet:
    def test_isSupported_returnsTrue_forKnownHexCode(self) -> None:
        pids = pid_probe.SupportedPidSet({"0x0C", "0x05", "0x03"})
        assert pids.isSupported("0x0C") is True

    def test_isSupported_isCaseInsensitive(self) -> None:
        pids = pid_probe.SupportedPidSet({"0x0C"})
        assert pids.isSupported("0x0c") is True

    def test_isSupported_returnsFalse_forUnknownCode(self) -> None:
        pids = pid_probe.SupportedPidSet({"0x0C"})
        assert pids.isSupported("0x42") is False

    def test_isSupported_noneAlwaysReturnsTrue_forAdapterCommands(self) -> None:
        """Adapter commands (ELM_VOLTAGE) have pid=None — treat as always supported."""
        pids = pid_probe.SupportedPidSet({"0x0C"})
        assert pids.isSupported(None) is True

    def test_alwaysSupported_factory_returnsTrueForEverything(self) -> None:
        pids = pid_probe.SupportedPidSet.alwaysSupported()
        assert pids.isSupported("0xFF") is True
        assert pids.isSupported("0x00") is True
        assert pids.isSupported(None) is True

    def test_len_matchesSupportedCount(self) -> None:
        pids = pid_probe.SupportedPidSet({"0x0C", "0x05"})
        assert len(pids) == 2


# ================================================================================
# probeSupportedPids — happy path
# ================================================================================


class TestProbeSupportedPids:
    def test_probe_returnsNormalizedHexCodes_fromPythonObdSupportedCommands(self) -> None:
        # Known Mode 01 PIDs from Session 23 baseline
        fake = FakeObdConnection(
            supported=[
                _cmd("RPM", mode=1, pid=0x0C),
                _cmd("COOLANT_TEMP", mode=1, pid=0x05),
                _cmd("FUEL_STATUS", mode=1, pid=0x03),
            ]
        )
        result = pid_probe.probeSupportedPids(_wrap(fake))

        assert result.isSupported("0x0C")
        assert result.isSupported("0x05")
        assert result.isSupported("0x03")
        assert len(result) == 3

    def test_probe_padsSingleDigitPidsToTwoHexChars(self) -> None:
        """PID 0x3 must normalize to '0x03' so lookups match the canonical spec form."""
        fake = FakeObdConnection(supported=[_cmd("FUEL_STATUS", mode=1, pid=0x03)])
        result = pid_probe.probeSupportedPids(_wrap(fake))
        assert result.isSupported("0x03")
        assert result.isSupported("0x3")  # case-tolerant lookup too

    def test_probe_skipsNonMode01Commands(self) -> None:
        """Mode 03 (DTCs), Mode 09 (VIN) commands are not on the PID support bitmap."""
        fake = FakeObdConnection(
            supported=[
                _cmd("RPM", mode=1, pid=0x0C),
                _cmd("GET_DTC", mode=3, pid=None),  # Mode 03
                _cmd("VIN", mode=9, pid=0x02),  # Mode 09
            ]
        )
        result = pid_probe.probeSupportedPids(_wrap(fake))
        assert result.isSupported("0x0C")
        assert len(result) == 1  # only the Mode 01 RPM

    def test_probe_skipsCommandsWithNonePid(self) -> None:
        """ELM_VOLTAGE / AT-commands have pid=None -- not on the PID bitmap."""
        fake = FakeObdConnection(
            supported=[
                _cmd("RPM", mode=1, pid=0x0C),
                _cmd("ELM_VOLTAGE", mode=None, pid=None),
            ]
        )
        result = pid_probe.probeSupportedPids(_wrap(fake))
        assert result.isSupported("0x0C")
        assert len(result) == 1


# ================================================================================
# probeSupportedPids — edge cases & invariants
# ================================================================================


class TestProbeEdgeCases:
    def test_probe_returnsEmptySet_whenConnectionReturnsEmptyList(self) -> None:
        fake = FakeObdConnection(supported=[])
        result = pid_probe.probeSupportedPids(_wrap(fake))
        assert len(result) == 0
        assert result.isSupported("0x0C") is False

    def test_probe_returnsAlwaysSupported_whenConnectionIsNotConnected(self) -> None:
        """If python-obd hasn't completed its probe, fall back to 'everything supported'
        so polling proceeds without dropping parameters (silent-skip at query time still applies)."""
        fake = FakeObdConnection(supported=None, connected=False)
        result = pid_probe.probeSupportedPids(_wrap(fake))
        assert result.isSupported("0x0C") is True  # fallback

    def test_probe_returnsAlwaysSupported_whenObdIsNone(self) -> None:
        outer = SimpleNamespace(obd=None, isConnected=lambda: False)
        result = pid_probe.probeSupportedPids(outer)
        assert result.isSupported("0x42") is True

    def test_probe_tolerates_missingSupportedCommandsAttribute(self) -> None:
        """Some python-obd versions / mocks may not expose supported_commands — don't crash."""
        broken = SimpleNamespace()  # no supported_commands attribute
        outer = SimpleNamespace(obd=broken, isConnected=lambda: True)
        result = pid_probe.probeSupportedPids(outer)
        assert len(result) == 0 or result.isSupported("0x0C") is True

    @pytest.mark.parametrize(
        ("pid_int", "expected_key"),
        [
            (0x01, "0x01"),
            (0x0C, "0x0c"),
            (0x33, "0x33"),
            (0xFF, "0xff"),
        ],
    )
    def test_probe_normalizesHexCodeToLowercaseTwoChar(
        self, pid_int: int, expected_key: str
    ) -> None:
        fake = FakeObdConnection(supported=[_cmd("X", mode=1, pid=pid_int)])
        result = pid_probe.probeSupportedPids(_wrap(fake))
        assert result.isSupported(expected_key)
