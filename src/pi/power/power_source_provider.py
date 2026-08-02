################################################################################
# File Name: power_source_provider.py
# Purpose/Description: Single Source of Truth for the "power source" fact. The
#                      ONLY place in the codebase that acquires power-source
#                      state. Wraps the sound PldSensor (X1209 GPIO6 PLD).
#                      UI and ShutdownSequencer both consume THIS; they differ
#                      only by the policy they apply (UI = instantaneous;
#                      sequencer = smoothed). UpsMonitor.getPowerSource() (the
#                      VCELL-trend heuristic) is retired from this fact.
# Author: (shutdown-sequencer plan 2026-05-18)
# Creation Date: 2026-05-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""SSOT for the power-source fact (wraps the GPIO6 PLD line)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
__all__ = ["PowerSourceProvider"]


class PowerSourceProvider:
    """The single authoritative provider of the power-source fact.

    Consumers apply their own policy; they never acquire power source any
    other way. ``isExternalPowerPresent()`` is instantaneous ground truth
    (UI consumes this directly; the ShutdownSequencer applies smoothing on
    top). Unavailable/unreadable resolves to power-present -- the
    deliberate "uncertain => do NOT shut down" safe direction; the arm
    self-check is the separate guard that refuses to arm in that case.
    """

    def __init__(self, *, pld: Any) -> None:
        """Args:
            pld: A PldSensor-shaped object exposing isExternalPowerPresent(),
                isPowerLost(), startupPolarityOk(), isAvailable.
        """
        self._pld = pld

    @property
    def isAvailable(self) -> bool:
        """True iff the underlying line is readable at all.

        The fact, not a policy: it lets each consumer resolve uncertainty its
        own way over this ONE provider. The ShutdownSequencer keeps the
        non-bricking direction (unreadable => treat as power present); a
        DISPLAY consumer must not, because taking that at face value paints a
        confident "external" off a dead GPIO (US-502 honest-instrument). A pld
        that does not report readability resolves to False -- unknown beats
        assumed-good.
        """
        return bool(getattr(self._pld, "isAvailable", False))

    def isExternalPowerPresent(self) -> bool:
        """Instantaneous ground-truth power-source reading."""
        return bool(self._pld.isExternalPowerPresent())

    def isPowerLost(self) -> bool:
        """True only when the line is readable AND says power lost."""
        return bool(self._pld.isPowerLost())

    def startupArmCheck(self) -> bool:
        """The Pi only booted because power is live, so at start the line
        MUST read power-present. False => wrong pin/polarity/unreadable =>
        caller refuses to arm the shutdown path."""
        ok = bool(self._pld.startupPolarityOk())
        if not ok:
            logger.error(
                "PowerSourceProvider arm self-check FAILED -- refusing to arm "
                "(uncertain power source => do NOT shut down)."
            )
        return ok
