################################################################################
# File Name: test_pi_only_smoke.py
# Purpose/Description: Smoke tests for the @pytest.mark.pi_only marker
# Author: Rex (Ralph)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Rex (Ralph)  | US-182: minimal Pi-hardware assertions, gated
# ================================================================================
################################################################################

"""
Smoke tests that demonstrate the ``@pytest.mark.pi_only`` opt-in mechanism.

These tests make assertions about the host that can only hold on real Pi 5
hardware (``/proc/device-tree/model`` says "Raspberry Pi", ``/dev/i2c-1``
exists, ``platform.machine() == 'aarch64'``). They are auto-skipped off-Pi
unless ``ECLIPSE_PI_HOST=1`` is set — see ``tests/conftest.py`` for the
collection-time gate.

Run on-Pi (US-182 verification):
    ECLIPSE_PI_HOST=1 ~/obd2-venv/bin/python -m pytest -m pi_only -v

Run off-Pi (smoke test of the skip path):
    pytest -m pi_only -v   # expect 0 run / N skipped
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest

pytestmark = pytest.mark.pi_only


class TestPiHardwareSmoke:
    """Assertions that only hold on genuine Pi 5 hardware."""

    def test_platformMachine_isAarch64(self) -> None:
        """
        Given: Running on Raspberry Pi 5 under 64-bit Raspberry Pi OS
        When: platform.machine() is inspected
        Then: Reports 'aarch64' (not 'x86_64' / 'AMD64')
        """
        assert platform.machine() == 'aarch64', (
            f"Expected aarch64, got {platform.machine()!r}. "
            "pi_only smoke is running on a non-Pi host."
        )

    def test_i2cBusOne_deviceNodeExists(self) -> None:
        """
        Given: Pi OS with i2c-dev enabled (per /boot/firmware/config.txt)
        When: /dev/i2c-1 is checked
        Then: The device node exists (bus 1 is the GPIO-header I2C bus)
        """
        assert Path('/dev/i2c-1').exists(), (
            "/dev/i2c-1 missing — enable i2c-dev in /boot/firmware/config.txt"
        )

    def test_deviceTreeModel_mentionsRaspberryPi(self) -> None:
        """
        Given: Raspberry Pi OS runs with a populated device tree
        When: /proc/device-tree/model is read
        Then: Contains the string 'Raspberry Pi'
        """
        modelPath = Path('/proc/device-tree/model')
        assert modelPath.exists(), "Device tree model node missing"
        model = modelPath.read_bytes().rstrip(b'\x00').decode('utf-8', errors='replace')
        assert 'Raspberry Pi' in model, f"Unexpected device-tree model: {model!r}"

    def test_eclipsePiHostOptIn_isReflectedInEnv(self) -> None:
        """
        Given: Test is running, so the conftest marker gate let it through
        When: ECLIPSE_PI_HOST or real-aarch64 detection is checked
        Then: At least one of the two gate conditions is observable.

        This guards against silent regressions in the opt-in mechanism
        (e.g. someone removes the env-var check but leaves auto-detect).
        """
        isOptedIn = os.environ.get('ECLIPSE_PI_HOST') == '1'
        isRealPi = platform.machine() == 'aarch64'
        assert isOptedIn or isRealPi, (
            'pi_only test ran without either ECLIPSE_PI_HOST=1 or aarch64 '
            'platform detection — the conftest gate is mis-configured.'
        )
