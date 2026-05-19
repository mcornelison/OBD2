################################################################################
# File Name: controller.py
# Purpose/Description: ShutdownSequencer controller (renamed from PowerWatch in
#                      SS-T5). On a power-LOST signal from the SSOT trigger
#                      (PowerSourceProvider.isPowerLost over X1209 GPIO6 PLD) it
#                      FIRST applies smoothing -- requires sustained-lost across
#                      smoothingSec (spec sec 3 in-V1 safety property) -- only
#                      then runs the bounded pipeline under a total cap and
#                      powers off. A transient blip (electrical noise, boot
#                      settling) aborts with NO poweroff. A failed VCELL read
#                      NEVER forces poweroff (uncertain != lost power); the
#                      VCELL floor is a backstop only on a SUCCESSFUL low read
#                      AFTER sustained power-lost is confirmed.
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
# 2026-05-19    | Plan SS-T5 | Renamed PowerWatch -> ShutdownSequencer + ctor
#                              params confirmWindowSec/confirmPollSec ->
#                              smoothingSec/smoothingPollSec + internal
#                              _confirmSustainedOnBattery -> _smoothedPowerLost.
#                              Logic unchanged (the hotfix debounce IS the spec
#                              sec 3 smoothing). Docstrings updated for the
#                              SSOT trigger context: isOnBattery is now fed by
#                              PowerSourceProvider.isPowerLost (GPIO6 ground
#                              truth), not the retired VCELL-trend heuristic.
# ================================================================================
################################################################################
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)
__all__ = ["ShutdownSequencer"]


class ShutdownSequencer:
    def __init__(
        self,
        *,
        isOnBattery: Callable[[], bool],
        vcell: Callable[[], float],
        runPipelineFn: Callable[[], None],
        powerOffFn: Callable[[], None],
        vcellFloor: float,
        totalCapSec: float,
        smoothingSec: float,
        smoothingPollSec: float,
        sleepFn: Callable[[float], None] | None = None,
        monotonicFn: Callable[[], float] | None = None,
    ):
        """Args:
            isOnBattery: Zero-arg predicate, True while power is LOST (DI'd to
                ``PowerSourceProvider.isPowerLost`` in the service -- the SSOT
                over the X1209 GPIO6 PLD line, ground truth, not a heuristic).
                Smoothing below still applies: a transient electrical blip or
                boot-settling jitter can briefly read lost-then-present even
                on a healthy line, and shutdown must NEVER fire on such a blip.
            vcell: Zero-arg, returns battery VCELL in VOLTS (not mV).
            runPipelineFn: Already-bound zero-arg bounded pre-shutdown pipeline.
            powerOffFn: Already-bound zero-arg graceful OS poweroff.
            vcellFloor: Safety-floor in VOLTS. A SUCCESSFUL read <= this, AFTER
                sustained power-lost is confirmed, short-circuits to poweroff.
                A FAILED read never triggers poweroff.
            totalCapSec: Hard total-window cap (SECONDS) on the pipeline.
            smoothingSec: ``isOnBattery()`` must stay True continuously for at
                least this long (SECONDS) before any poweroff -- the in-V1
                safety property (spec sec 3) that rejects transient/boot blips.
                0 = no smoothing (test only).
            smoothingPollSec: Re-sample cadence (SECONDS) during the smoothing
                interval.
            sleepFn: DI sleep (default time.sleep); tests pass a no-op.
            monotonicFn: DI monotonic clock (default time.monotonic).
        """
        self._isOnBattery = isOnBattery
        self._vcell = vcell
        self._runPipeline = runPipelineFn
        self._powerOff = powerOffFn
        self._vcellFloor = vcellFloor
        self._totalCapSec = totalCapSec
        self._smoothingSec = smoothingSec
        self._smoothingPollSec = smoothingPollSec
        self._sleep = sleepFn if sleepFn is not None else time.sleep
        self._monotonic = monotonicFn if monotonicFn is not None else time.monotonic

    def _smoothedPowerLost(self) -> bool:
        """Return True only if ``isOnBattery()`` stays True continuously for
        the whole smoothing interval. The instant it reads not-on-battery,
        return False (blip -> do NOT shut down; external power is present).

        ``smoothingSec`` <= 0 collapses to a single immediate check.
        """
        if not self._isOnBattery():
            return False
        deadline = self._monotonic() + self._smoothingSec
        while self._monotonic() < deadline:
            self._sleep(self._smoothingPollSec)
            if not self._isOnBattery():
                return False
        return True

    def handleOnBattery(self) -> None:
        """Called when a power-LOST signal fires. Apply smoothing FIRST: only
        a sustained-lost state (held across ``smoothingSec``) is a real power
        loss; a transient blip aborts with NO poweroff. On confirmed sustained
        loss: a successful VCELL read <= floor short-circuits to poweroff;
        otherwise run the bounded pipeline then (if still on battery) graceful
        poweroff. A FAILED VCELL read never forces poweroff -- uncertainty
        about voltage is not loss of power; we already confirmed sustained
        battery, so we proceed via the normal bounded pipeline (no floor
        fast-path this cycle).
        """
        if not self._smoothedPowerLost():
            logger.info(
                "shutdown-sequencer: power-lost NOT sustained through %.0fs "
                "smoothing window -- transient (external power present), "
                "abort + resume",
                self._smoothingSec,
            )
            return
        logger.warning(
            "shutdown-sequencer: sustained power-lost confirmed (%.0fs "
            "smoothing) -- entering bounded pre-shutdown window",
            self._smoothingSec,
        )
        try:
            v = self._vcell()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "shutdown-sequencer: VCELL read failed (%s) -- power-lost "
                "already confirmed sustained; proceeding via bounded pipeline "
                "(no floor fast-path this cycle, NOT an immediate poweroff)",
                exc,
            )
            v = None
        if v is not None and v <= self._vcellFloor:
            logger.warning(
                "shutdown-sequencer: VCELL %.3f <= floor %.3f (power-lost "
                "confirmed) -- skip pipeline, poweroff now", v, self._vcellFloor,
            )
            self._powerOff()
            return
        done = threading.Event()

        def _pipe() -> None:
            try:
                self._runPipeline()
            except Exception as exc:  # noqa: BLE001 -- runner already isolates; belt+braces
                logger.error("shutdown-sequencer: pipeline wrapper raised: %s", exc)
            finally:
                done.set()

        th = threading.Thread(target=_pipe, name="pw-pipeline", daemon=True)
        th.start()
        done.wait(timeout=self._totalCapSec)  # total cap; a hung pipeline cannot block poweroff
        if not self._isOnBattery():
            logger.info(
                "shutdown-sequencer: power returned during window -- abort, "
                "resume normal op"
            )
            return
        logger.warning(
            "shutdown-sequencer: pre-shutdown window resolved -- graceful poweroff"
        )
        self._powerOff()
