################################################################################
# File Name: pld_sensor.py
# Purpose/Description: X1209 UPS HAT Power-Loss-Detection (PLD) reader. The HAT
#                      drives BCM GPIO6 as a hardware "external power present"
#                      line (HIGH=power good, LOW=power lost) -- per Geekworm's
#                      x120x reference pld.py. This is the DETERMINISTIC
#                      ground-truth power signal that replaces the VCELL-trend
#                      heuristic (UpsMonitor.getPowerSource) as the powerwatch
#                      trigger after the 2026-05-18 bricking loop, where the
#                      heuristic reported BATTERY on the boot VCELL sag while
#                      external power was physically connected.
# Author: (implementation plan 2026-05-18)
# Creation Date: 2026-05-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-18    | Plan    | Initial -- bricking hotfix: GPIO6 PLD ground-truth.
# ================================================================================
################################################################################
"""X1209 GPIO6 power-loss-detection reader (deterministic, not heuristic)."""
from __future__ import annotations

import errno
import logging
from collections.abc import Callable
from typing import Any

from .platform_utils import isRaspberryPi

logger = logging.getLogger(__name__)
__all__ = [
    "PLD_UNAVAILABLE_ABSENT",
    "PLD_UNAVAILABLE_CONTENDED",
    "PLD_UNAVAILABLE_ERROR",
    "PldSensor",
]

# Why an unavailable PldSensor must say WHICH kind of unavailable it is
# (US-668, Atlas 2026-09-02).
#
# Before this, ANY exception at construction set ``_dev = None`` and
# ``isAvailable`` went False, with no way to ask what happened.  So a GPIO line
# ALREADY CLAIMED BY ANOTHER PROCESS was reported identically to a Pi with no
# PLD wired at all.  eclipse-powerwatch and eclipse-obd both opened BCM 6, the
# loser of that race got EBUSY, and it read as "no power sensor fitted" --
# permanently, because there is no re-open path.  It looked like missing
# hardware from 2026-05-16 onward.
#
# EBUSY means "someone else has it." ENODEV means "it is not there."  Those
# demand opposite responses -- fix the ownership, versus fit the hardware -- and
# a sensor that cannot tell them apart sends every operator down the wrong one.
PLD_UNAVAILABLE_CONTENDED: str = "contended"
PLD_UNAVAILABLE_ABSENT: str = "absent"
PLD_UNAVAILABLE_ERROR: str = "error"


def _defaultDeviceFactory(pin: int) -> Any:
    """Build a gpiozero DigitalInputDevice on `pin`, mirroring gpio_button.py's
    defensive guard. The X1209 actively drives GPIO6 so NO Pi-side pull is
    used; active_state=True -> .value == 1 when the pin is physically HIGH.
    Raises on non-Pi / missing gpiozero so the caller marks itself
    unavailable (and a missing signal is treated as power-present -- the
    NON-bricking direction)."""
    if not isRaspberryPi():
        raise RuntimeError("PLD GPIO not available -- not running on Raspberry Pi")
    from gpiozero import DigitalInputDevice  # local import: optional on dev hosts

    return DigitalInputDevice(pin, pull_up=None, active_state=True)


class PldSensor:
    """Reads the X1209 GPIO6 PLD line. ``isExternalPowerPresent()`` is the
    authoritative trigger input for powerwatch.

    SAFETY INVARIANT: if the signal cannot be read (no gpiozero / not a Pi /
    pin error), ``isExternalPowerPresent()`` returns True and
    ``isPowerLost()`` returns False -- i.e. "uncertain" means "do NOT shut
    down". This is the deliberate inverse of the old VCELL fail-safe that
    bricked the Pi by treating uncertainty as power-loss.
    """

    def __init__(
        self,
        *,
        pin: int = 6,
        powerPresentHigh: bool = True,
        deviceFactory: Callable[[int], Any] | None = None,
    ) -> None:
        """Args:
            pin: BCM GPIO for the PLD line (X1209 = 6).
            powerPresentHigh: True if HIGH means external power present
                (X1209 reference pld.py: pld_state==1 -> power present).
            deviceFactory: callable(pin) -> object exposing ``.value``
                (1=HIGH, 0=LOW) and ``.close()``; DI'd for tests/non-Pi.
        """
        self._pin = pin
        self._powerPresentHigh = powerPresentHigh
        factory = deviceFactory if deviceFactory is not None else _defaultDeviceFactory
        self._dev: Any | None = None
        self._unavailableReason: str | None = None
        try:
            self._dev = factory(pin)
            logger.info("PldSensor armed on GPIO%d (powerPresentHigh=%s)",
                        pin, powerPresentHigh)
        except Exception as exc:  # noqa: BLE001 -- unavailable must be safe, never fatal
            logger.warning(
                "PldSensor unavailable on GPIO%d (%s) -- power will be treated "
                "as PRESENT (safe: never self-shutdown on an unreadable signal)",
                pin, exc,
            )
            self._dev = None
            self._unavailableReason = self._classifyFailure(exc)

    @staticmethod
    def _classifyFailure(exc: BaseException) -> str:
        """Name WHY the line could not be opened.

        The distinction is the whole point: contention and absence look
        identical to ``isAvailable`` and demand opposite fixes.
        """
        errno_ = getattr(exc, "errno", None)
        if errno_ == errno.EBUSY:
            return PLD_UNAVAILABLE_CONTENDED
        if errno_ in (errno.ENODEV, errno.ENOENT, errno.ENXIO):
            return PLD_UNAVAILABLE_ABSENT
        # gpiozero raises its own types; fall back to the message, then to a
        # generic error rather than guessing one of the two specific answers.
        text = str(exc).lower()
        if "busy" in text or "in use" in text:
            return PLD_UNAVAILABLE_CONTENDED
        if "not running on raspberry pi" in text or "no such device" in text:
            return PLD_UNAVAILABLE_ABSENT
        return PLD_UNAVAILABLE_ERROR

    @property
    def isAvailable(self) -> bool:
        """True iff the GPIO line was opened."""
        return self._dev is not None

    @property
    def unavailableReason(self) -> str | None:
        """Why the line is unavailable, or None when it opened fine."""
        return None if self._dev is not None else self._unavailableReason

    def isExternalPowerPresent(self) -> bool:
        """True if external/input power is present. Unavailable/error -> True
        (the non-bricking safe direction)."""
        if self._dev is None:
            return True
        try:
            high = int(self._dev.value) == 1
        except Exception as exc:  # noqa: BLE001 -- a read error must not mean "power lost"
            logger.error(
                "PldSensor GPIO%d read failed (%s) -- treating as power "
                "PRESENT (safe direction)", self._pin, exc,
            )
            return True
        return high if self._powerPresentHigh else not high

    def isPowerLost(self) -> bool:
        """True only when we can read the line AND it says power is lost."""
        return self.isAvailable and not self.isExternalPowerPresent()

    def startupPolarityOk(self) -> bool:
        """One-shot arming self-check. The service only starts because the Pi
        booted on a live feed, so at startup the line MUST read
        power-present. If it is unavailable or reads power-lost, the
        pin/polarity is wrong -> caller must REFUSE to arm the shutdown path
        (fail to "do not shut down")."""
        return self.isAvailable and self.isExternalPowerPresent()

    def close(self) -> None:
        """Release the GPIO line. Safe to call repeatedly."""
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("PldSensor close error (ignored): %s", exc)
            self._dev = None
