################################################################################
# File Name: test_pld_sensor.py
# Purpose/Description: Tests for PldSensor -- the X1209 GPIO6 Power-Loss
#                      Detection reader. Ground-truth external-power signal
#                      (HIGH=power present, LOW=power lost) that replaces the
#                      VCELL-trend heuristic as the powerwatch trigger after
#                      the 2026-05-18 bricking loop. gpiozero is dependency-
#                      injected so these run on Windows with no Pi/GPIO.
# Author: (implementation plan 2026-05-18)
# Creation Date: 2026-05-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-18    | Plan    | Initial -- bricking hotfix: GPIO6 PLD trigger.
# ================================================================================
################################################################################
from src.pi.hardware.pld_sensor import PldSensor


class _FakeDev:
    """Stand-in for gpiozero.DigitalInputDevice: .value 1=HIGH, 0=LOW."""

    def __init__(self, value):
        self.value = value
        self.closed = False

    def close(self):
        self.closed = True


def test_power_present_when_gpio_high_active_high():
    s = PldSensor(pin=6, powerPresentHigh=True,
                  deviceFactory=lambda pin: _FakeDev(1))
    assert s.isExternalPowerPresent() is True
    assert s.isPowerLost() is False


def test_power_lost_when_gpio_low_active_high():
    s = PldSensor(pin=6, powerPresentHigh=True,
                  deviceFactory=lambda pin: _FakeDev(0))
    assert s.isExternalPowerPresent() is False
    assert s.isPowerLost() is True


def test_polarity_inverted_config():
    # If a board variant drives LOW=present, config flips it.
    s = PldSensor(pin=6, powerPresentHigh=False,
                  deviceFactory=lambda pin: _FakeDev(0))
    assert s.isExternalPowerPresent() is True


def test_unavailable_when_factory_raises_and_reads_are_safe():
    def _boom(_pin):
        raise RuntimeError("no gpiozero / not a Pi")

    s = PldSensor(pin=6, powerPresentHigh=True, deviceFactory=_boom)
    assert s.isAvailable is False
    # SAFETY: when the signal is unavailable we must NOT report power-lost
    # (that is the bricking direction). Unavailable => treat as power present.
    assert s.isExternalPowerPresent() is True
    assert s.isPowerLost() is False


def test_selfcheck_passes_when_present_at_startup():
    s = PldSensor(pin=6, powerPresentHigh=True,
                  deviceFactory=lambda pin: _FakeDev(1))
    assert s.startupPolarityOk() is True


def test_selfcheck_fails_when_reads_power_lost_at_startup():
    # The service only starts because the Pi is running on a live feed at
    # boot; GPIO6 reading "lost" at startup means the pin/polarity is wrong
    # -> refuse to arm (fail to "do not shut down").
    s = PldSensor(pin=6, powerPresentHigh=True,
                  deviceFactory=lambda pin: _FakeDev(0))
    assert s.startupPolarityOk() is False


def test_selfcheck_fails_when_unavailable():
    s = PldSensor(pin=6, powerPresentHigh=True,
                  deviceFactory=lambda _p: (_ for _ in ()).throw(OSError("x")))
    assert s.startupPolarityOk() is False
