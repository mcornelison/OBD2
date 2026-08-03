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
# 2026-06-29    | US-394 A-2  | Added the F-103 shutdown-splash phase-emit hook:
#                              an OPTIONAL generic `phaseEmitFn` callback emitted
#                              at each code-path transition (grace -> cancelled |
#                              flushing -> powering_off). The sequencer is the
#                              SSOT of shutdown phase + timing; it owns the phase
#                              DECISIONS and NEVER imports the splash subsystem
#                              (unidirectional dependency, spec §6/§481). The hook
#                              is best-effort + guarded -- an emit that raises
#                              NEVER blocks shutdown progress (A-2 constraint c).
#                              When no emitter is wired the sequencer behaves
#                              byte-identically to before. See the A-6 timing
#                              invariant below + specs/architecture.md §10.6.
# ================================================================================
################################################################################
#
# Phase-emit timing contract with the splash subsystem (F-103) [Atlas A-6]:
#   Splash plays a 7.5s animation budget triggered on phase=grace.
#   If config `smoothingSec` < 4, splash animation may be killed
#   mid-frame when poweroff fires before animation completes.
#   Acceptable failure mode: degraded UX, no data loss.
#   Default smoothingSec=7 provides ~10-12s total time-to-poweroff,
#   comfortably exceeding splash's 7.5s budget.
# Ownership of the time-coupling lives HERE (the sequencer's docstring); the
# splash holds the invariant by trusting it. No new config key, no runtime
# coordination -- a clean unidirectional dependency: the splash depends on this
# timing contract; the sequencer does not know the splash exists.
#
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

logger = logging.getLogger(__name__)
__all__ = [
    "PHASE_CANCELLED",
    "PHASE_FLUSHING",
    "PHASE_GRACE",
    "PHASE_POWERING_OFF",
    "DEFAULT_SHUTDOWN_REASON",
    "ShutdownSequencer",
]

# --- Shutdown phase transitions (the sequencer is the SSOT of phase) ----------
# The F-103 splash subsystem CONSUMES these strings via
# pi.splash.shutdown_state_emitter (which imports them) -- a strictly
# unidirectional dependency (spec §6/§481: the splash depends on the sequencer's
# phase + timing contract; the sequencer never depends on the splash).
#   grace        = smoothing-begun (T=0; sustained-loss NOT yet confirmed).
#   cancelled    = smoothing failed (power returned) -> abort.
#   flushing     = smoothing-confirmed; bounded pipeline tasks executing.
#   powering_off = immediately before `systemctl poweroff`.
PHASE_GRACE = "grace"
PHASE_CANCELLED = "cancelled"
PHASE_FLUSHING = "flushing"
PHASE_POWERING_OFF = "powering_off"

# v1 treats all shutdown reasons identically; the splash never branches on it.
DEFAULT_SHUTDOWN_REASON = "ignition_off"


def _defaultNowIso() -> str:
    """Default ISO-8601 UTC stamp for the shutdown-state grace-start time."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        phaseEmitFn: Callable[..., None] | None = None,
        nowIsoFn: Callable[[], str] | None = None,
        shutdownReason: str = DEFAULT_SHUTDOWN_REASON,
        prePowerOffFn: Callable[[], None] | None = None,
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
            phaseEmitFn: OPTIONAL F-103 shutdown-splash phase-emit hook. Called
                as ``phaseEmitFn(phase, *, tGraceStartedAtIso, tGraceTotalS,
                tRemainingS, reason)`` at each transition (a ``PHASE_*`` string).
                Best-effort: the call site guards it so an emit that raises NEVER
                blocks shutdown (Atlas A-2 constraint c). ``None`` (the default)
                disables the hook and the sequencer runs the exact legacy path
                (no extra ``isOnBattery()`` reads), so existing behavior + tests
                are unchanged.
            nowIsoFn: DI clock returning the ISO-8601 grace-start stamp for the
                shutdown-state payload (default UTC now). Only consulted when
                ``phaseEmitFn`` is wired.
            shutdownReason: The ``reason`` field for the shutdown-state payload
                (v1 always ``ignition_off``; the splash never branches on it).
            prePowerOffFn: OPTIONAL zero-arg hook run immediately BEFORE
                ``powerOffFn`` on EVERY path that actually powers off -- both
                the bounded-pipeline path and the VCELL-floor fast path.
                US-526 wires it to the production drain-event close, which
                Atlas ruled the PRIMARY close (Option C, 2026-08-02): under
                Spool's depth gate the run-to-cutoff drain is the only
                qualifying drain and it ends exactly here, so the close must be
                guaranteed on this path. It is deliberately NOT a pipeline
                ShutdownTask -- the floor fast-path SKIPS the pipeline, which
                is precisely how a run-to-cutoff drain ends, so a task-based
                close would miss every row the verdict needs.
                Runs LAST before poweroff so a depth read is as deep as the
                drain actually got. Best-effort and guarded exactly like
                ``phaseEmitFn``: a hook that raises NEVER blocks poweroff
                (bookkeeping is never worth leaving the Pi up on a dying
                battery). NOT called on an abort (transient blip, or power
                returning mid-window) -- an aborted shutdown is not a drain
                end, and the collector's BATTERY->AC transition owns that
                close. ``None`` (the default) runs the exact legacy path.
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
        self._phaseEmitFn = phaseEmitFn
        self._prePowerOffFn = prePowerOffFn
        self._shutdownReason = shutdownReason
        self._nowIso = nowIsoFn if nowIsoFn is not None else _defaultNowIso
        # Grace-window bookkeeping (set when the grace phase is emitted).
        self._graceStartedAtIso: str | None = None
        self._graceStartMono: float | None = None

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
        # F-103 [A-2]: emit `grace` at T=0 (BEFORE smoothing resolves) so the
        # splash triggers immediately -- the animation IS the grace countdown.
        # Guarded on the hook being wired so the legacy path adds NO extra
        # isOnBattery() read (existing iterator-based mocks keep their pattern).
        if self._phaseEmitFn is not None:
            if not self._isOnBattery():
                return
            self._beginGraceAndEmit()
        if not self._smoothedPowerLost():
            logger.info(
                "shutdown-sequencer: power-lost NOT sustained through %.0fs "
                "smoothing window -- transient (external power present), "
                "abort + resume",
                self._smoothingSec,
            )
            self._emitPhase(PHASE_CANCELLED)
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
            # Floor backstop skips the pipeline -> no `flushing` phase happened;
            # emit `powering_off` directly (honest instrument).
            self._emitPhase(PHASE_POWERING_OFF)
            # US-526: THE run-to-cutoff drain ends right here. This is the path
            # a depth-gate-qualifying drain takes, so the close must fire on it.
            self._runPrePowerOff()
            self._powerOff()
            return
        # F-103 [A-2]: smoothing confirmed + above floor -> the bounded pipeline
        # is about to run. `flushing` per the spec enum.
        self._emitPhase(PHASE_FLUSHING)
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
            # Power came back mid-window: tell the splash to abort too so it does
            # not sit in BLACK_TAIL waiting for a poweroff that will not come.
            self._emitPhase(PHASE_CANCELLED)
            return
        logger.warning(
            "shutdown-sequencer: pre-shutdown window resolved -- graceful poweroff"
        )
        self._emitPhase(PHASE_POWERING_OFF)
        self._runPrePowerOff()
        self._powerOff()

    # ----- US-526 pre-poweroff hook (drain-event close, Atlas Option C) -------

    def _runPrePowerOff(self) -> None:
        """Run the pre-poweroff hook (best-effort, never raises).

        A no-op when no ``prePowerOffFn`` is wired. Guarded so a failing drain
        close can NEVER delay or prevent the poweroff it precedes -- same
        contract as :meth:`_emitPhase`. The failure is logged loudly because a
        missed close means the boot reaper will mark that drain interrupted
        (runtime + depth NULL), i.e. one lost measurement rather than a silent
        wrong one.
        """
        if self._prePowerOffFn is None:
            return
        try:
            self._prePowerOffFn()
        except Exception as exc:  # noqa: BLE001 -- best-effort, belt+braces
            logger.error(
                "shutdown-sequencer: pre-poweroff hook failed (%s) -- ignored, "
                "poweroff proceeds. Any open drain row stays open and will be "
                "marked interrupted by the boot reaper.",
                exc,
            )

    # ----- F-103 shutdown-splash phase-emit hook (US-394 / Atlas A-2) ---------

    def _beginGraceAndEmit(self) -> None:
        """Capture the grace-window start (ISO + monotonic) and emit `grace`.

        Called once, the instant a power-lost signal arrives, before smoothing
        resolves -- so the splash triggers at T=0.
        """
        self._graceStartedAtIso = self._nowIso()
        self._graceStartMono = self._monotonic()
        self._emitPhase(PHASE_GRACE)

    def _graceRemainingS(self) -> float:
        """Seconds left in the grace (smoothing) window, clamped at 0.

        Before grace begins (or if the monotonic clock is unset) the full
        ``smoothingSec`` budget is reported.
        """
        if self._graceStartMono is None:
            return self._smoothingSec
        elapsed = self._monotonic() - self._graceStartMono
        return max(0.0, self._smoothingSec - elapsed)

    def _emitPhase(self, phase: str) -> None:
        """Emit one shutdown-state phase event (best-effort, never raises).

        A no-op when no ``phaseEmitFn`` is wired. The call is wrapped so a hook
        that raises NEVER blocks the shutdown progression (Atlas A-2 constraint
        c). The payload carries the grace-window timing the splash trusts; the
        sequencer remains ignorant of the splash schema (it passes raw fields).
        """
        if self._phaseEmitFn is None:
            return
        try:
            self._phaseEmitFn(
                phase,
                tGraceStartedAtIso=self._graceStartedAtIso,
                tGraceTotalS=self._smoothingSec,
                tRemainingS=self._graceRemainingS(),
                reason=self._shutdownReason,
            )
        except Exception as exc:  # noqa: BLE001 -- emit is best-effort, belt+braces
            logger.error(
                "shutdown-sequencer: phase-emit '%s' failed (%s) -- ignored "
                "(shutdown progress is never blocked by the splash hook)",
                phase,
                exc,
            )
