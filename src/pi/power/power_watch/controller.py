################################################################################
# File Name: controller.py
# Purpose/Description: PowerWatch controller for Phase-2 power-watch. On a
#                      BATTERY signal it FIRST debounces -- requires sustained
#                      on-battery across a confirm window (spec sec 6.2
#                      "sustained on-battery, debounced") -- only then runs the
#                      bounded pipeline under a total cap and powers off; a
#                      transient blip (e.g. boot VCELL sag while external power
#                      is physically present) aborts with NO poweroff. A failed
#                      VCELL read NEVER forces poweroff (uncertain != lost
#                      power); the VCELL floor is a backstop only on a
#                      successful low read AFTER sustained battery is confirmed.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T4 PowerWatch controller.
# 2026-05-18    | Plan    | HOTFIX (bricking loop): the old controller acted on
#                           the FIRST unconfirmed BATTERY transition and treated
#                           a failed VCELL read as floor->immediate poweroff --
#                           on a real Pi the UpsMonitor slope rule reports
#                           BATTERY on the boot VCELL sag (external power still
#                           connected) and I2C settles late at boot, so the Pi
#                           powered itself off ~10-15s after every boot. Added
#                           the debounced sustained-confirmation gate the spec
#                           always required; reversed the uncertain-VCELL
#                           direction (uncertain -> do NOT poweroff).
# ================================================================================
################################################################################
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)
__all__ = ["PowerWatch"]


class PowerWatch:
    def __init__(
        self,
        *,
        isOnBattery: Callable[[], bool],
        vcell: Callable[[], float],
        runPipelineFn: Callable[[], None],
        powerOffFn: Callable[[], None],
        vcellFloor: float,
        totalCapSec: float,
        confirmWindowSec: float,
        confirmPollSec: float,
        sleepFn: Callable[[float], None] | None = None,
        monotonicFn: Callable[[], float] | None = None,
    ):
        """Args:
            isOnBattery: Zero-arg predicate, True while on battery (DI'd to the
                real UpsMonitor in the service). NOTE this is a VCELL-trend
                heuristic, not a ground-truth external-power signal -- it can
                blip BATTERY transiently (boot sag) even on external power,
                which is exactly why the confirm window below exists.
            vcell: Zero-arg, returns battery VCELL in VOLTS (not mV).
            runPipelineFn: Already-bound zero-arg bounded pre-shutdown pipeline.
            powerOffFn: Already-bound zero-arg graceful OS poweroff.
            vcellFloor: Safety-floor in VOLTS. A SUCCESSFUL read <= this, AFTER
                sustained battery is confirmed, short-circuits to poweroff. A
                FAILED read never triggers poweroff.
            totalCapSec: Hard total-window cap (SECONDS) on the pipeline.
            confirmWindowSec: isOnBattery() must stay True continuously for at
                least this long (SECONDS) before any poweroff -- the debounce
                that rejects transient/boot blips. 0 = no debounce (test only).
            confirmPollSec: Re-sample cadence (SECONDS) during the confirm
                window.
            sleepFn: DI sleep (default time.sleep); tests pass a no-op.
            monotonicFn: DI monotonic clock (default time.monotonic).
        """
        self._isOnBattery = isOnBattery
        self._vcell = vcell
        self._runPipeline = runPipelineFn
        self._powerOff = powerOffFn
        self._vcellFloor = vcellFloor
        self._totalCapSec = totalCapSec
        self._confirmWindowSec = confirmWindowSec
        self._confirmPollSec = confirmPollSec
        self._sleep = sleepFn if sleepFn is not None else time.sleep
        self._monotonic = monotonicFn if monotonicFn is not None else time.monotonic

    def _confirmSustainedOnBattery(self) -> bool:
        """Return True only if isOnBattery() stays True continuously for the
        whole confirm window. The instant it reads not-on-battery, return
        False (transient -> do NOT shut down; external power is present).

        confirmWindowSec <= 0 collapses to a single immediate check.
        """
        if not self._isOnBattery():
            return False
        deadline = self._monotonic() + self._confirmWindowSec
        while self._monotonic() < deadline:
            self._sleep(self._confirmPollSec)
            if not self._isOnBattery():
                return False
        return True

    def handleOnBattery(self) -> None:
        """Called when a BATTERY signal fires. Debounce FIRST: only a sustained
        on-battery state (held across confirmWindowSec) is a real power loss; a
        transient blip aborts with NO poweroff. On confirmed sustained battery:
        a successful VCELL read <= floor short-circuits to poweroff; otherwise
        run the bounded pipeline then (if still on battery) graceful poweroff.
        A FAILED VCELL read never forces poweroff -- uncertainty about voltage
        is not loss of power; we already confirmed sustained battery, so we
        proceed via the normal bounded pipeline (no floor fast-path this cycle).
        """
        if not self._confirmSustainedOnBattery():
            logger.info(
                "powerwatch: on-battery NOT sustained through %.0fs confirm "
                "window -- transient (external power present), abort + resume",
                self._confirmWindowSec,
            )
            return
        logger.warning(
            "powerwatch: sustained-on-battery confirmed (%.0fs) -- "
            "entering bounded pre-shutdown window",
            self._confirmWindowSec,
        )
        try:
            v = self._vcell()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "powerwatch: VCELL read failed (%s) -- battery already "
                "confirmed sustained; proceeding via bounded pipeline "
                "(no floor fast-path this cycle, NOT an immediate poweroff)",
                exc,
            )
            v = None
        if v is not None and v <= self._vcellFloor:
            logger.warning(
                "powerwatch: VCELL %.3f <= floor %.3f (battery confirmed) -- "
                "skip pipeline, poweroff now", v, self._vcellFloor,
            )
            self._powerOff()
            return
        done = threading.Event()

        def _pipe() -> None:
            try:
                self._runPipeline()
            except Exception as exc:  # noqa: BLE001 -- runner already isolates; belt+braces
                logger.error("powerwatch: pipeline wrapper raised: %s", exc)
            finally:
                done.set()

        th = threading.Thread(target=_pipe, name="pw-pipeline", daemon=True)
        th.start()
        done.wait(timeout=self._totalCapSec)  # total cap; a hung pipeline cannot block poweroff
        if not self._isOnBattery():
            logger.info(
                "powerwatch: power returned during window -- abort, resume normal op"
            )
            return
        logger.warning("powerwatch: pre-shutdown window resolved -- graceful poweroff")
        self._powerOff()
