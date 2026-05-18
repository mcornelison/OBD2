################################################################################
# File Name: controller.py
# Purpose/Description: PowerWatch controller for Phase-2 power-watch: on
#                      sustained-on-battery, applies the VCELL-floor
#                      short-circuit, runs the bounded pipeline under a
#                      total-window cap, aborts+resumes if external power
#                      returns, else unconditional graceful poweroff.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T4 PowerWatch controller.
# ================================================================================
################################################################################
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)
__all__ = ["PowerWatch"]


class PowerWatch:
    def __init__(self, *, isOnBattery: Callable[[], bool], vcell: Callable[[], float],
                 runPipelineFn: Callable[[], None], powerOffFn: Callable[[], None],
                 vcellFloor: float, totalCapSec: float):
        """Args:
            isOnBattery: Zero-arg predicate, True while on battery (DI'd to the
                real UpsMonitor in the service).
            vcell: Zero-arg, returns battery VCELL in VOLTS (not mV).
            runPipelineFn: Already-bound zero-arg callable that runs the
                bounded pre-shutdown pipeline.
            powerOffFn: Already-bound zero-arg callable that performs the
                graceful OS poweroff.
            vcellFloor: Safety-floor threshold in VOLTS; VCELL <= this (or a
                failed VCELL read) short-circuits straight to poweroff.
            totalCapSec: Hard total-window cap in SECONDS.
        """
        self._isOnBattery = isOnBattery
        self._vcell = vcell
        self._runPipeline = runPipelineFn
        self._powerOff = powerOffFn
        self._vcellFloor = vcellFloor
        self._totalCapSec = totalCapSec

    def handleOnBattery(self) -> None:
        """Called once when sustained-on-battery is detected. Bounded; on
        external-power-return at any checkpoint -> abort + resume (no
        poweroff); else run the bounded pipeline then unconditional
        graceful poweroff.

        The poweroff is reached on every path that is not an explicit
        power-return abort. A failed VCELL read is treated as the safe
        floor (uncertain is never treated as healthy)."""
        if not self._isOnBattery():
            logger.info("powerwatch: power returned before window start -- resume")
            return
        try:
            v = self._vcell()
        except Exception as exc:  # noqa: BLE001
            logger.error("powerwatch: vcell read failed (%s) -- treat as safe-floor", exc)
            v = self._vcellFloor - 1.0   # force the safe short-circuit
        if v <= self._vcellFloor:
            logger.warning("powerwatch: VCELL %.3f <= floor %.3f -- skip pipeline, poweroff now",
                           v, self._vcellFloor)
            self._powerOff()
            return
        done = threading.Event()
        def _pipe():
            try:
                self._runPipeline()
            except Exception as exc:  # noqa: BLE001 -- runner already isolates; belt+braces
                logger.error("powerwatch: pipeline wrapper raised: %s", exc)
            finally:
                done.set()
        th = threading.Thread(target=_pipe, name="pw-pipeline", daemon=True)
        th.start()
        done.wait(timeout=self._totalCapSec)   # total cap; a hung pipeline cannot block poweroff
        if not self._isOnBattery():
            logger.info("powerwatch: power returned during window -- abort, resume normal op")
            return
        logger.warning("powerwatch: pre-shutdown window resolved -- graceful poweroff")
        self._powerOff()
