################################################################################
# File Name: battery_health_emitter.py
# Purpose/Description: F-097 battery-health emitter [Atlas A-3]. The schema +
#   best-effort writer for the `battery-health` SSOT that the carousel dashboard
#   Battery Health card consumes. The cell is the Pi UPS-HAT LiPo (MAX17048 fuel
#   gauge), NEVER the car's 12 V lead-acid (F-11). The orchestrator/power tier
#   OWNS this emitter (it holds the live MAX17048 reads + the `battery_health_log`
#   history + the power-watch draining state, A-3); it calls the injected
#   `emit(...)` callable -- the dashboard renders what this file says, it never
#   polls hardware (specs/ssot-design-pattern.md).
#
#   Two render-breaking honesty traps are locked at this data contract:
#     * F-8 (voltage-is-not-percent): there is NO code path here from `vcellV`
#       to `soc`. The SoC percent comes ONLY from the MAX17048 SoC register; a
#       null register read passes through as `soc=None` (the card omits the
#       percent and shows only volts). The trap is locked by ABSENCE -- the
#       emitter structurally cannot lerp a percent from voltage.
#     * A-6 (no-false-failsafe): the failsafe `ladder` is forced null whenever
#       `draining` is false, even if a caller supplies one -- the drain ladder
#       never renders unless the pack is actually draining (the D-2 dishonest-
#       instrument trap). The live runtime-remaining + ladder thresholds are
#       Spool-owned (S-2, failsafe-only) and arrive inside the caller's `ladder`
#       dict; this module never fabricates them.
#   Schema pinned in docs/superpowers/specs/2026-06-05-pi-touch-carousel-
#   dashboard-f092-f097-design.md §7 (state file shapes).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-401 battery-health card)
# ================================================================================
################################################################################

"""Battery-health schema builder + the best-effort emit factory (Atlas A-3)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime

# Reuse the boot-state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

logger = logging.getLogger(__name__)

# The single SSOT slot the carousel Battery Health card polls (4 Hz tmpfs read).
BATTERY_HEALTH_FILENAME = "battery-health"

# Spool health verdicts (consumer-side view of the cell's condition). The
# display maps these tiers -> colour ONLY; it never classifies (Spool owns the
# verdict, this module carries it verbatim).
#   green = full-charge-reachable + sane cutoff + no degradation -> ok.
#   attn  = a weak trend / a watch condition -> amber.
#   low   = the pack cannot be trusted to shut down cleanly -> red.
HEALTH_GREEN = "green"
HEALTH_ATTN = "attn"
HEALTH_LOW = "low"

# The ISO-8601 instant format the F-103 emitters stamp (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

__all__ = [
    "BATTERY_HEALTH_FILENAME",
    "HEALTH_ATTN",
    "HEALTH_GREEN",
    "HEALTH_LOW",
    "buildBatteryHealthState",
    "makeBatteryHealthEmitter",
]


def buildBatteryHealthState(
    *,
    vcellV: float | None,
    soc: int | None,
    socCalibrated: bool,
    crate: float | None,
    charging: bool,
    draining: bool,
    restedVcellV: float | None,
    weakEvents30d: int,
    restedHistory: list[float],
    health: str,
    fullChargeReached: bool,
    runtimeToCutoffS: int | None,
    ambientTempC: float | None,
    lastHealthCheckTs: str | None,
    ladder: dict | None,
    nowIso: str,
) -> dict:
    """Assemble the battery-health payload (pure; spec §7 pinned A-3 schema).

    Args:
        vcellV: Authoritative cell voltage from ``battery_health_log`` / live
            MAX17048 (VOLTS, ~4.2->3.4). NOT a percent.
        soc: State-of-charge percent from the MAX17048 SoC REGISTER only, or
            None when the register read is unavailable. NEVER derived from
            ``vcellV`` (F-8).
        socCalibrated: Whether the SoC register has been calibrated (a fresh
            gauge reads uncalibrated -- the card tags it ``(uncalibrated)``).
        crate: Charge/discharge rate (%/hr; sign = direction) or None.
        charging: Whether the cell is charging.
        draining: Whether wall power is lost AND the pack is actually draining
            (the failsafe-render gate -- A-6).
        restedVcellV: Most recent rested cell voltage, or None.
        weakEvents30d: Count of Spool-defined weak events in the last 30 days.
        restedHistory: Recent rested-VCELL trend (volts).
        health: Spool verdict -- ``HEALTH_GREEN`` / ``HEALTH_ATTN`` /
            ``HEALTH_LOW``.
        fullChargeReached: Whether the pack reached 4.20-4.22 V last cycle.
        runtimeToCutoffS: Health-stat typical full-drain runtime (NOT the live
            failsafe estimate), or None.
        ambientTempC: Ambient temperature, or None when never logged (the card
            renders "not captured" -- F-10, never a fabricated number).
        lastHealthCheckTs: ISO-8601 instant of the last drain/health cycle, or
            None. The card always pairs a GREEN verdict with this date + age so
            a stale reading is not mistaken for live (the stale-green guard F-9).
        ladder: The failsafe ladder dict (``stage`` / ``thresholds`` /
            ``runtimeRemainingS``) supplied by the power-watch tier, or None.
            Forced to None here whenever ``draining`` is false (A-6).
        nowIso: ISO-8601 emission timestamp (freshness marker + age basis).

    Returns:
        The battery-health dict with exactly the spec §7 A-3 keys.
    """
    # A-6 no-false-failsafe: the failsafe ladder may ONLY exist while draining.
    # Enforced here (the SSOT) so a buggy caller can never light a phantom drain.
    safeLadder = ladder if draining else None
    return {
        "vcellV": vcellV,
        "soc": soc,
        "socCalibrated": socCalibrated,
        "crate": crate,
        "charging": charging,
        "draining": draining,
        "restedVcellV": restedVcellV,
        "weakEvents30d": weakEvents30d,
        "restedHistory": restedHistory,
        "health": health,
        "fullChargeReached": fullChargeReached,
        "runtimeToCutoffS": runtimeToCutoffS,
        "ambientTempC": ambientTempC,
        "lastHealthCheckTs": lastHealthCheckTs,
        "ladder": safeLadder,
        "ts": nowIso,
    }


def makeBatteryHealthEmitter(
    statesDir: str,
    *,
    nowIsoFn: Callable[[], str] | None = None,
) -> Callable[..., None]:
    """Build the battery-health emit callable owned by the power tier (A-3).

    The returned callable takes the live MAX17048 / health-log / draining
    readings, applies the A-6 failsafe invariant, and writes the battery-health
    SSOT atomically. Best-effort by contract: a write failure is logged but
    NEVER raised, so the emit hook can never block the orchestrator's main loop.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        nowIsoFn: Injected clock for ``ts`` (default UTC now, second resolution).

    Returns:
        The emit callable (same keyword readings as ``buildBatteryHealthState``
        minus ``nowIso``, which the clock supplies).
    """
    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime(_ISO_FMT))
    target = os.path.join(statesDir, BATTERY_HEALTH_FILENAME)

    def emit(
        *,
        vcellV: float | None,
        soc: int | None,
        socCalibrated: bool,
        crate: float | None,
        charging: bool,
        draining: bool,
        restedVcellV: float | None,
        weakEvents30d: int,
        restedHistory: list[float],
        health: str,
        fullChargeReached: bool,
        runtimeToCutoffS: int | None,
        ambientTempC: float | None,
        lastHealthCheckTs: str | None,
        ladder: dict | None,
    ) -> None:
        try:
            payload = buildBatteryHealthState(
                vcellV=vcellV,
                soc=soc,
                socCalibrated=socCalibrated,
                crate=crate,
                charging=charging,
                draining=draining,
                restedVcellV=restedVcellV,
                weakEvents30d=weakEvents30d,
                restedHistory=restedHistory,
                health=health,
                fullChargeReached=fullChargeReached,
                runtimeToCutoffS=runtimeToCutoffS,
                ambientTempC=ambientTempC,
                lastHealthCheckTs=lastHealthCheckTs,
                ladder=ladder,
                nowIso=nowFn(),
            )
            ensureStatesDir(statesDir)
            writeStateAtomic(target, payload)
        except Exception as exc:  # noqa: BLE001 -- best-effort, never block the loop
            logger.error(
                "battery-health emit failed (%s) -- ignored (the dashboard hook "
                "never blocks the orchestrator)",
                exc,
            )

    return emit
