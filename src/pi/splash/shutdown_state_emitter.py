################################################################################
# File Name: shutdown_state_emitter.py
# Purpose/Description: F-103 shutdown-state emitter [Atlas A-2]. The schema +
#   best-effort writer for the `shutdown-state` SSOT that the grace-period
#   shutdown splash consumes. The ShutdownSequencer is the SSOT of shutdown
#   phase + timing (src/pi/power/power_watch/controller.py); it owns the phase
#   DECISIONS and calls a generic injected `phaseEmitFn` -- it never imports this
#   module, keeping the dependency unidirectional (splash depends on the
#   sequencer's timing contract; the sequencer does not know splash exists, spec
#   §6 / A-6). `makeShutdownPhaseEmitter` builds that callable, wired in
#   src/pi/power/power_watch/__main__.py. The splash renders what this file
#   says; it never decides (specs/ssot-design-pattern.md). Schema is pinned in
#   $FLEET_SHARE/knowledge/superpowers/specs/2026-05-26-b103-splash-animation-design.md §6.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-394 F-103 shutdown splash)
# ================================================================================
################################################################################

"""Shutdown-state schema builder + the best-effort phase-emit factory."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime

# The phase enum + reason default are owned by the ShutdownSequencer (the SSOT of
# shutdown phase); the splash CONSUMES them here -- unidirectional dependency
# (spec §6/§481: splash depends on the sequencer, never the reverse). The power
# controller imports only stdlib, so this is a cheap, cycle-free import.
from pi.power.power_watch.controller import (
    DEFAULT_SHUTDOWN_REASON as DEFAULT_REASON,
)
from pi.power.power_watch.controller import (
    PHASE_CANCELLED,
    PHASE_FLUSHING,
    PHASE_GRACE,
    PHASE_POWERING_OFF,
)

# Reuse the boot-state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

logger = logging.getLogger(__name__)

# The single SSOT slot the splash-grace `.path` unit watches + the kiosk polls.
SHUTDOWN_STATE_FILENAME = "shutdown-state"

# The set of valid phases (consumer-side view of the sequencer's transitions).
#   grace        = smoothing-begun (T=0) -> splash TRIGGERS (PRE_ROLL+ANIMATING).
#   cancelled    = smoothing failed / power returned -> splash ABORTS.
#   flushing     = smoothing-confirmed; bounded pipeline tasks executing.
#   powering_off = immediately before `systemctl poweroff`.
VALID_PHASES = frozenset(
    {PHASE_GRACE, PHASE_CANCELLED, PHASE_FLUSHING, PHASE_POWERING_OFF}
)

__all__ = [
    "DEFAULT_REASON",
    "PHASE_CANCELLED",
    "PHASE_FLUSHING",
    "PHASE_GRACE",
    "PHASE_POWERING_OFF",
    "SHUTDOWN_STATE_FILENAME",
    "VALID_PHASES",
    "buildShutdownState",
    "makeShutdownPhaseEmitter",
]


def buildShutdownState(
    phase: str,
    *,
    tGraceStartedAtIso: str,
    tGraceTotalS: float,
    tRemainingS: float,
    reason: str,
    nowIso: str,
) -> dict:
    """Assemble the shutdown-state payload (pure; spec §6 pinned schema).

    Args:
        phase: One of the ``PHASE_*`` constants (the sequencer transition).
        tGraceStartedAtIso: ISO-8601 instant the grace window began.
        tGraceTotalS: Total grace (smoothing) window in seconds.
        tRemainingS: Seconds remaining in the grace window (0 once elapsed).
        reason: Shutdown reason (v1 always ``ignition_off``; splash ignores it).
        nowIso: ISO-8601 emission timestamp.

    Returns:
        The shutdown-state dict with exactly the spec §6 keys.
    """
    return {
        "phase": phase,
        "tGraceStartedAt": tGraceStartedAtIso,
        "tGraceTotalS": tGraceTotalS,
        "tRemainingS": tRemainingS,
        "reason": reason,
        "ts": nowIso,
    }


def makeShutdownPhaseEmitter(
    statesDir: str, nowIsoFn: Callable[[], str] | None = None
) -> Callable[..., None]:
    """Build the phase-emit callable injected into ``ShutdownSequencer.phaseEmitFn``.

    The returned callable matches the generic emit signature the sequencer
    invokes -- ``emit(phase, *, tGraceStartedAtIso, tGraceTotalS, tRemainingS,
    reason)`` -- and writes the shutdown-state SSOT atomically.

    Best-effort by contract (Atlas A-2, constraint c): a write failure is logged
    but NEVER raised, so the emit hook can never block the shutdown state
    machine. The sequencer additionally guards the call site, belt-and-braces.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        nowIsoFn: Injected clock for the ``ts`` field (default UTC now).

    Returns:
        The phase-emit callable.
    """
    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    target = os.path.join(statesDir, SHUTDOWN_STATE_FILENAME)

    def emit(
        phase: str,
        *,
        tGraceStartedAtIso: str,
        tGraceTotalS: float,
        tRemainingS: float,
        reason: str = DEFAULT_REASON,
    ) -> None:
        try:
            ensureStatesDir(statesDir)
            payload = buildShutdownState(
                phase,
                tGraceStartedAtIso=tGraceStartedAtIso,
                tGraceTotalS=tGraceTotalS,
                tRemainingS=tRemainingS,
                reason=reason,
                nowIso=nowFn(),
            )
            writeStateAtomic(target, payload)
        except Exception as exc:  # noqa: BLE001 -- best-effort, never block shutdown
            logger.error(
                "shutdown-state emit '%s' failed (%s) -- ignored (shutdown "
                "progress is never blocked by the splash hook)",
                phase,
                exc,
            )

    return emit
