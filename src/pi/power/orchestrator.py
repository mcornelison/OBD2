################################################################################
# File Name: orchestrator.py
# Purpose/Description: PowerDownOrchestrator -- staged shutdown state machine.
#                      Consumes UpsMonitor VCELL + power-source change callbacks;
#                      fires WARNING / IMMINENT / TRIGGER stage behaviors with
#                      hysteresis; opens + closes battery_health_log rows
#                      (US-217); wraps ShutdownHandler._executeShutdown as the
#                      terminal action. US-234 (Sprint 19) switched the trigger
#                      source from MAX17048 SOC% to VCELL volts after 4 drain
#                      tests proved SOC%-based thresholds unfireable on this
#                      hardware (40-pt SOC calibration error).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-216) | Initial -- staged shutdown orchestrator
#                              | (SOC%-based thresholds 30/25/20).
# 2026-04-29    | Rex (US-234) | Switched trigger source SOC% -> VCELL volts
#                              | (3.70/3.55/3.45 with 0.05V hysteresis). Reason:
#                              | MAX17048 SOC% calibration is 40-pt off on this
#                              | unit; SOC%-based thresholds NEVER fired across
#                              | 4 drain tests despite hard-crashes at VCELL
#                              | 3.36-3.45V every test. tick() now takes
#                              | currentVcell:float; ShutdownThresholds fields
#                              | are warningVcell/imminentVcell/triggerVcell/
#                              | hysteresisVcell. battery_health_log start_soc
#                              | + end_soc columns now hold VCELL volts (schema
#                              | unchanged per US-234 doNotTouch). See
#                              | offices/pm/inbox/2026-04-29-from-spool-sprint19-
#                              | consolidated.md Section P0 #1 for grounding.
# 2026-05-01    | Rex (US-252) | Added powerLogWriter(eventType,vcell) optional
#                              | callable injected via constructor; invoked
#                              | from _enterWarning / _enterImminent /
#                              | _enterTrigger so each stage transition
#                              | leaves a forensic row in power_log.  Companion
#                              | to the dedicated _powerDownTickThread in
#                              | hardware_manager that decouples tick() from
#                              | the display loop -- across 5 drain tests
#                              | the orchestrator NEVER FIRED because tick()
#                              | was gated on _statusDisplay being non-None.
# 2026-05-01    | Rex (US-262) | Added _tickCount counter (incremented at TOP of
#                              | tick() BEFORE any early-return guard so the
#                              | counter advances even when the method bails
#                              | on enabled=False or PowerSource UNKNOWN), plus
#                              | read-only `tickCount` and `currentStage`
#                              | properties.  Drives drain_forensics CSV's
#                              | pd_tick_count + pd_stage columns; their
#                              | values discriminate Drain-7 verdict per
#                              | Spool's truth-table (count stays 0 -> US-265
#                              | hypothesis; count increments but stage stays
#                              | NORMAL -> US-266; stage advances but
#                              | power_log empty -> US-267).  No lock --
#                              | int read of a single-writer counter is GIL-
#                              | atomic in CPython, and the spec invariant
#                              | mandates the accessor MUST NOT acquire any
#                              | lock that tick() itself holds.
# 2026-05-02    | Rex (US-266) | Discriminator B instrumentation -- DEBUG-log
#                              | every early-return inside tick() so a post-
#                              | Drain-7 forensic walk in journalctl can pin
#                              | down which silent-bail guard (if any)
#                              | swallowed the BATTERY -> WARNING transition
#                              | when the logger CSV's pd_tick_count column
#                              | is incrementing but pd_stage stays NORMAL.
#                              | Audit found 4 silent-bail early-return paths
#                              | (enabled=False / state=TRIGGER terminal /
#                              | source=EXTERNAL during NORMAL / source=
#                              | UNKNOWN); each now emits a single logger.
#                              | debug() line capturing the bail-causing value.
#                              | Behavior is unchanged -- guards return at
#                              | the same site and same condition; only the
#                              | DEBUG log is added.  Audit findings about
#                              | the spec's hypothesis modes "vcell=None /
#                              | threshold=None" -- those would currently
#                              | TypeError on the threshold comparison and be
#                              | caught loud by hardware_manager._powerDown
#                              | TickLoop's `except Exception` (an ERROR log,
#                              | not a silent bail), so they are NOT
#                              | hypothesis-B candidates and NO new defensive
#                              | guards were added (per the "behavior
#                              | unchanged / no logic refactored" invariant).
# ================================================================================
################################################################################

"""Power-down orchestrator (US-216 + US-234, Spool 4-drain analysis).

Problem
-------
The 2026-04-20 UPS drain test showed the Pi hard-crashes at ~0% SOC because
the only live shutdown path was ``ShutdownHandler``'s binary 10% trigger +
30s-after-BATTERY timer. CIO directive 2 mandated a staged ladder; US-216
landed it at warning 30% / imminent 25% / trigger 20% SOC.

Across 4 drain tests over 9 days (Drains 1-4) the SOC%-based ladder
NEVER FIRED -- hard-crashes at VCELL 3.36-3.45V every test, with
MAX17048 reporting SOC 57-63% at crash time (a 40-pt overstatement
caused by the chip's ModelGauge mis-calibration on this unit). US-234
fixes the trigger source: read VCELL volts directly from the cell,
compare against voltage thresholds aligned with measured drain
behavior. The state-machine shape (NORMAL -> WARNING -> IMMINENT ->
TRIGGER + AC-restore + hysteresis + callback isolation) is preserved.

Design
------
Pure state machine driven by :meth:`PowerDownOrchestrator.tick`. The
caller (hardware_manager's display update loop) feeds ``(currentVcell,
currentSource)`` pairs at the UPS poll cadence (5s). On each tick:

1. ``currentSource == EXTERNAL`` during a non-NORMAL state triggers the
   AC-restore path: cancel pending stages, close the drain-event row as
   ``recovered``, back to NORMAL.
2. ``currentSource == BATTERY`` with falling VCELL escalates the state
   monotonically: NORMAL -> WARNING -> IMMINENT -> TRIGGER. The
   inequality is ``currentVcell <= threshold`` since LiPo cell voltage
   FALLS as the cell discharges.
3. Hysteresis: once in WARNING, VCELL must climb back to
   ``warningVcell + hysteresisVcell`` (e.g. 3.75V) to de-escalate.
   Prevents flap on VCELL reads oscillating around the threshold.
4. TRIGGER is terminal -- further ticks are ignored, ``shutdownAction``
   fires exactly once.

Stage behaviors
---------------
* **WARNING@<=3.70V**: open ``battery_health_log`` row; invoke optional
  ``onWarning`` callback. Callers wire the callback to: set
  ``pi_state.no_new_drives=true``, force SyncClient push.
* **IMMINENT@<=3.55V**: invoke optional ``onImminent`` callback. Callers
  wire: stop OBD poll-tier dispatch, close BT via US-211 clean-close,
  force KEY_OFF on active drive via ``DriveDetector.forceKeyOff``.
* **TRIGGER@<=3.45V**: close the drain-event row, invoke ``shutdownAction``
  (typically ``ShutdownHandler._executeShutdown`` = ``systemctl
  poweroff``). One-way action.
* **AC-restore**: cancel pending stages, close drain-event row with
  ``notes='recovered'``, invoke optional ``onAcRestore`` callback.

Schema note (US-234)
--------------------
``battery_health_log.start_soc`` and ``battery_health_log.end_soc`` are
unchanged by US-234 (per doNotTouch). They now carry VCELL volts
(typical 3.45 - 4.20) instead of SOC % (typical 20 - 100). Future
analytics consumers must be aware that rows written before US-234 hold
SOC %, and rows written after hold volts. A column-rename or a
``unit`` discriminator column is a Sprint 20+ candidate; not in scope here.

Callback error isolation
------------------------
Stage callbacks are invoked with broad exception capture -- a raising
``onWarning`` must not prevent further escalation to TRIGGER. Shutdown
action failures are logged but do not block state transition.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.pi.power.battery_health import BatteryHealthRecorder

# Deferred to avoid a circular import. ``src.pi.hardware.ups_monitor`` goes
# through ``src/pi/hardware/__init__.py`` which re-exports
# ``hardware_manager``, which imports this module back for
# ``PowerDownOrchestrator`` + ``ShutdownThresholds``. Using TYPE_CHECKING
# for the type hint and a local import inside :meth:`tick` keeps the
# module top-level free of the cycle.
if TYPE_CHECKING:  # pragma: no cover
    from src.pi.hardware.ups_monitor import PowerSource

__all__ = [
    'PowerDownOrchestrator',
    'PowerLogWriter',
    'PowerState',
    'ShutdownThresholds',
]

logger = logging.getLogger(__name__)


# ================================================================================
# Configuration dataclass
# ================================================================================


@dataclass(frozen=True)
class ShutdownThresholds:
    """Config schema: ``pi.power.shutdownThresholds``.

    US-234: trigger source moved from MAX17048 SOC% to VCELL volts. The
    field names changed accordingly (no back-compat shim -- the old
    SOC% values were unfireable on this hardware so callers MUST migrate).

    Attributes:
        enabled: Master on/off. When False, :meth:`PowerDownOrchestrator.tick`
            is a no-op and the legacy ShutdownHandler path remains the sole
            shutdown mechanism.
        warningVcell: VCELL volts at which to enter WARNING stage
            (default 3.70). Triggers when ``currentVcell <= warningVcell``.
        imminentVcell: VCELL volts at which to enter IMMINENT stage
            (default 3.55).
        triggerVcell: VCELL volts at which to fire TRIGGER stage +
            ``systemctl poweroff`` (default 3.45). Spool's 4-drain
            recommendation -- gives ~90s headroom above buck-converter
            dropout (3.36-3.45V observed crash range).
        hysteresisVcell: Volts above a stage's threshold required to
            de-escalate from that stage (default 0.05). Prevents flap
            on VCELL reads oscillating around the threshold.
    """

    enabled: bool = True
    warningVcell: float = 3.70
    imminentVcell: float = 3.55
    triggerVcell: float = 3.45
    hysteresisVcell: float = 0.05


# ================================================================================
# State enum
# ================================================================================


class PowerState(Enum):
    """Orchestrator state machine values."""

    NORMAL = "normal"
    WARNING = "warning"
    IMMINENT = "imminent"
    TRIGGER = "trigger"


# ================================================================================
# Orchestrator
# ================================================================================


StageCallback = Callable[[], None]
ShutdownAction = Callable[[], None]
# US-252: (eventType, vcell) -> None.  Hardware_manager wires this to a
# closure over ``logShutdownStage(database, ...)`` so each stage entry
# leaves a forensic row in ``power_log``.
PowerLogWriter = Callable[[str, float], None]


class PowerDownOrchestrator:
    """Staged-shutdown state machine driven by VCELL + power-source ticks.

    Constructor requires a live :class:`BatteryHealthRecorder` (US-217)
    and a ``shutdownAction`` callable. Stage-behavior callbacks are
    optional; hardware_manager wires them to concrete actions
    (DB flag toggle, BT close, DriveDetector.forceKeyOff, sync push)
    when their components are available.

    Attributes:
        state: Current :class:`PowerState`.
        activeDrainEventId: ``drain_event_id`` of the open
            battery_health_log row, or ``None`` when no drain event is
            active.
    """

    def __init__(
        self,
        *,
        thresholds: ShutdownThresholds,
        batteryHealthRecorder: BatteryHealthRecorder,
        shutdownAction: ShutdownAction,
        onWarning: StageCallback | None = None,
        onImminent: StageCallback | None = None,
        onAcRestore: StageCallback | None = None,
        powerLogWriter: PowerLogWriter | None = None,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            thresholds: Config values (enabled flag + VCELL bands).
            batteryHealthRecorder: US-217 drain-event writer. Orchestrator
                opens the row at WARNING entry and closes it at TRIGGER
                or AC-restore.
            shutdownAction: Callable invoked exactly once on TRIGGER entry.
                Typically bound to ``ShutdownHandler._executeShutdown``
                which in turn runs ``systemctl poweroff``.
            onWarning: Optional callable invoked on WARNING entry. Wired
                by hardware_manager to DB flag toggle + sync push.
            onImminent: Optional callable invoked on IMMINENT entry.
                Wired to OBD poll stop + BT close + force KEY_OFF.
            onAcRestore: Optional callable invoked when power returns
                during a non-NORMAL state (after drain row is closed
                as recovered).
            powerLogWriter: US-252 optional ``(eventType, vcell)`` callable
                invoked on each stage entry (WARNING / IMMINENT / TRIGGER)
                so the stage transition is persisted to ``power_log`` for
                post-mortem reconstruction.  Errors are logged-and-ignored
                because the stage transition itself MUST proceed --
                forensics cannot block safety.
        """
        self._thresholds = thresholds
        self._recorder = batteryHealthRecorder
        self._shutdownAction = shutdownAction
        self._onWarning = onWarning
        self._onImminent = onImminent
        self._onAcRestore = onAcRestore
        self._powerLogWriter = powerLogWriter

        self._state: PowerState = PowerState.NORMAL
        self._activeDrainEventId: int | None = None
        self._shutdownFired: bool = False
        # Track the highest VCELL seen on battery in this drain event so
        # the battery_health_log row records the true drain-start VCELL
        # rather than the WARNING threshold crossing. Reset on AC restore.
        self._highestBatteryVcell: float | None = None
        # US-262 forensic counter -- incremented at the TOP of tick() before
        # any early-return guard so a stays-at-0 reading post-drain proves
        # the dedicated _powerDownTickThread never advanced (hypothesis A).
        self._tickCount: int = 0

        logger.debug(
            "PowerDownOrchestrator initialized: enabled=%s "
            "warning=%.2fV imminent=%.2fV trigger=%.2fV hysteresis=%.2fV",
            thresholds.enabled,
            thresholds.warningVcell,
            thresholds.imminentVcell,
            thresholds.triggerVcell,
            thresholds.hysteresisVcell,
        )

    @property
    def state(self) -> PowerState:
        return self._state

    @property
    def currentStage(self) -> PowerState:
        """Snapshot-read alias for :attr:`state` (US-262).

        Provided for the drain_forensics logger's ``pd_stage`` column.
        Returns the live state without acquiring any lock -- enum
        attribute reads are GIL-atomic in CPython, and the US-262
        invariant mandates the accessor MUST NOT acquire any lock that
        :meth:`tick` itself holds. The caller may receive a value that
        is one tick stale; that is acceptable for forensic CSV.
        """
        return self._state

    @property
    def tickCount(self) -> int:
        """Number of times :meth:`tick` has been entered (US-262).

        Increments at the TOP of :meth:`tick` BEFORE any early-return
        guard, so the counter advances even when the method bails on
        ``enabled=False``, ``PowerSource UNKNOWN``, or terminal
        ``TRIGGER`` state. This is intentional: drain_forensics's
        ``pd_tick_count`` column discriminates Drain-7 verdict per
        Spool's truth-table -- a stays-at-0 reading post-drain proves
        the dedicated ``_powerDownTickThread`` never advanced
        (hypothesis A); a non-zero reading with ``pd_stage`` stuck on
        NORMAL discriminates hypothesis B.

        Snapshot-read; no lock acquired (GIL-atomic int read in
        CPython, single-writer counter).
        """
        return self._tickCount

    @property
    def activeDrainEventId(self) -> int | None:
        return self._activeDrainEventId

    def tick(self, *, currentVcell: float, currentSource: PowerSource) -> None:
        """Evaluate one state-machine tick.

        Args:
            currentVcell: Current battery cell voltage in volts (LiPo
                3.0-4.3) from ``UpsMonitor.getVcell``.
            currentSource: Current power source from
                ``UpsMonitor.getPowerSource``.
        """
        from src.pi.hardware.ups_monitor import PowerSource as _PS

        # US-262: increment counter BEFORE any early-return guard so the
        # forensic CSV's pd_tick_count column distinguishes "thread never
        # ran" (count==0) from "thread ran but bailed early" (count>0,
        # pd_stage==NORMAL). Single-writer counter, no lock needed.
        self._tickCount += 1

        # US-266 Discriminator B: every silent-bail early-return below
        # emits a DEBUG log capturing the bail-causing value.  The
        # forensic chain (logger CSV pd_tick_count column + journalctl
        # DEBUG lines) lets a post-Drain-7 walk identify which guard,
        # if any, swallowed a BATTERY -> WARNING transition.  Behavior
        # is otherwise unchanged: same conditions, same returns.
        sourceValue = getattr(currentSource, "value", currentSource)

        if not self._thresholds.enabled:
            logger.debug(
                "tick early-return: thresholds.enabled=False "
                "(currentVcell=%s source=%s)",
                currentVcell, sourceValue,
            )
            return

        if self._state == PowerState.TRIGGER:
            # Terminal state -- no further action.
            logger.debug(
                "tick early-return: state=TRIGGER terminal "
                "(currentVcell=%s source=%s)",
                currentVcell, sourceValue,
            )
            return

        if currentSource == _PS.EXTERNAL:
            # AC restore during non-NORMAL -> full reset.
            if self._state != PowerState.NORMAL:
                self._acRestore(currentVcell)
                return
            # state == NORMAL on EXTERNAL: silent bail.  Either wall
            # power is genuinely feeding the UPS (happy path) or the
            # upstream getPowerSource() returned a STALE-CACHED
            # EXTERNAL because its VCELL-history buffer lacked
            # decisive evidence.  No escalation is possible from
            # NORMAL on EXTERNAL; DEBUG-log so post-mortem can
            # correlate journalctl with the logger CSV's pd_stage.
            logger.debug(
                "tick early-return: source=EXTERNAL state=NORMAL "
                "(currentVcell=%s; wall-power or stale-cache)",
                currentVcell,
            )
            return

        if currentSource != _PS.BATTERY:
            # UNKNOWN -> do nothing (next tick may clarify)
            logger.debug(
                "tick early-return: source=%s expected BATTERY "
                "(currentVcell=%s)",
                sourceValue, currentVcell,
            )
            return

        # On battery. Track the highest VCELL seen pre-WARNING so the
        # drain-event row captures the true starting VCELL.
        if self._state == PowerState.NORMAL and (
            self._highestBatteryVcell is None
            or currentVcell > self._highestBatteryVcell
        ):
            self._highestBatteryVcell = currentVcell

        # Check escalation. Use a fall-through so a single fast
        # drop (4.20 -> 3.40) fires all stages in order before committing
        # to TRIGGER. Inequality is <= because LiPo VCELL FALLS on
        # discharge.
        if (
            self._state == PowerState.NORMAL
            and currentVcell <= self._thresholds.warningVcell
        ):
            self._enterWarning(currentVcell)

        if (
            self._state == PowerState.WARNING
            and currentVcell <= self._thresholds.imminentVcell
        ):
            self._enterImminent(currentVcell)

        if (
            self._state == PowerState.IMMINENT
            and currentVcell <= self._thresholds.triggerVcell
        ):
            self._enterTrigger(currentVcell)
            return

        # Check de-escalation. Only meaningful during a drain where
        # VCELL recovers without an AC transition (rare; belt-and-braces
        # for the hysteresis invariant in the story).
        if self._state == PowerState.WARNING:
            deEscalateAt = (
                self._thresholds.warningVcell
                + self._thresholds.hysteresisVcell
            )
            if currentVcell >= deEscalateAt:
                self._deEscalateWarningToNormal(currentVcell)

    # --------------------------------------------------------------------- #
    # Stage entry helpers
    # --------------------------------------------------------------------- #

    def _enterWarning(self, vcell: float) -> None:
        logger.warning(
            "PowerDownOrchestrator: WARNING at %.3fV -- opening drain event",
            vcell,
        )
        # Use the highest VCELL observed on battery in this drain if it's
        # higher than the current WARNING-entry VCELL. This captures the
        # drain-start VCELL for battery_health_log analytics. Stored in
        # the start_soc column (US-234 reuses existing schema; column
        # name says SOC but value is volts post-US-234 -- see module
        # docstring).
        startVcell = (
            self._highestBatteryVcell
            if self._highestBatteryVcell is not None
            and self._highestBatteryVcell > vcell
            else vcell
        )
        try:
            self._activeDrainEventId = self._recorder.startDrainEvent(
                startSoc=float(startVcell),
                loadClass='production',
            )
        except Exception as e:  # noqa: BLE001
            # Drain-event open failure is logged but not fatal -- the ladder
            # must still advance so shutdown fires in time.
            logger.error(
                "PowerDownOrchestrator: failed to open drain event: %s", e,
            )
            self._activeDrainEventId = None
        self._state = PowerState.WARNING
        self._writePowerLogStage("stage_warning", vcell)
        self._invokeCallback("onWarning", self._onWarning)

    def _enterImminent(self, vcell: float) -> None:
        logger.warning(
            "PowerDownOrchestrator: IMMINENT at %.3fV", vcell,
        )
        self._state = PowerState.IMMINENT
        self._writePowerLogStage("stage_imminent", vcell)
        self._invokeCallback("onImminent", self._onImminent)

    def _enterTrigger(self, vcell: float) -> None:
        logger.warning(
            "PowerDownOrchestrator: TRIGGER at %.3fV -- initiating poweroff",
            vcell,
        )
        # Close the drain event BEFORE poweroff so the row has a valid
        # end_timestamp / end_soc even if the process exits immediately.
        self._closeDrainEvent(vcell, ambientTempC=None)
        self._state = PowerState.TRIGGER
        # Forensic stage row BEFORE poweroff -- if the process is killed
        # mid-_shutdownAction the post-mortem still has the trigger
        # crossing in power_log.
        self._writePowerLogStage("stage_trigger", vcell)
        if self._shutdownFired:
            return
        self._shutdownFired = True
        try:
            self._shutdownAction()
        except Exception as e:  # noqa: BLE001
            logger.error(
                "PowerDownOrchestrator: shutdownAction raised: %s", e,
            )

    def _acRestore(self, currentVcell: float) -> None:
        priorState = self._state
        logger.info(
            "PowerDownOrchestrator: AC restored at %.3fV during %s -- "
            "cancelling",
            currentVcell, priorState.value,
        )
        self._closeDrainEvent(currentVcell, ambientTempC=None)
        self._state = PowerState.NORMAL
        self._shutdownFired = False
        self._highestBatteryVcell = None
        self._invokeCallback("onAcRestore", self._onAcRestore)

    def _deEscalateWarningToNormal(self, currentVcell: float) -> None:
        logger.info(
            "PowerDownOrchestrator: WARNING -> NORMAL at %.3fV "
            "(hysteresis recovery on battery)",
            currentVcell,
        )
        self._closeDrainEvent(currentVcell, ambientTempC=None)
        self._state = PowerState.NORMAL

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _closeDrainEvent(
        self, endVcell: float, *, ambientTempC: float | None,
    ) -> None:
        """Close the active drain-event row, if any.

        Writes ``endVcell`` into the ``end_soc`` column. The column
        name is unchanged from US-217 but post-US-234 the value is
        VCELL volts, not SOC %.
        """
        if self._activeDrainEventId is None:
            return
        try:
            self._recorder.endDrainEvent(
                drainEventId=self._activeDrainEventId,
                endSoc=float(endVcell),
                ambientTempC=ambientTempC,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                "PowerDownOrchestrator: failed to close drain event %d: %s",
                self._activeDrainEventId, e,
            )
        finally:
            self._activeDrainEventId = None

    def _invokeCallback(
        self, name: str, callback: StageCallback | None,
    ) -> None:
        """Call a stage callback with broad-exception isolation."""
        if callback is None:
            return
        try:
            callback()
        except Exception as e:  # noqa: BLE001
            logger.error(
                "PowerDownOrchestrator: %s callback raised: %s", name, e,
            )

    def _writePowerLogStage(self, eventType: str, vcell: float) -> None:
        """Persist a stage transition to ``power_log`` (US-252).

        Errors are logged-and-ignored: forensics MUST NOT block the
        safety ladder from advancing.  When ``powerLogWriter`` is None
        (test contexts that don't need DB writes) this is a no-op.
        """
        if self._powerLogWriter is None:
            return
        try:
            self._powerLogWriter(eventType, vcell)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "PowerDownOrchestrator: powerLogWriter raised on %s: %s",
                eventType, e,
            )


# ================================================================================
# Factory
# ================================================================================


def createShutdownThresholdsFromConfig(
    config: dict[str, Any],
) -> ShutdownThresholds:
    """Build :class:`ShutdownThresholds` from a config dict.

    Reads ``config['pi']['power']['shutdownThresholds']``; any missing
    field falls through to the dataclass default. US-234 fields are
    ``warningVcell`` / ``imminentVcell`` / ``triggerVcell`` /
    ``hysteresisVcell`` (volts).

    Args:
        config: Root config dict.

    Returns:
        Populated :class:`ShutdownThresholds`.
    """
    section = (
        config.get('pi', {}).get('power', {}).get('shutdownThresholds', {})
    )
    defaults = ShutdownThresholds()
    return ShutdownThresholds(
        enabled=bool(section.get('enabled', defaults.enabled)),
        warningVcell=float(
            section.get('warningVcell', defaults.warningVcell),
        ),
        imminentVcell=float(
            section.get('imminentVcell', defaults.imminentVcell),
        ),
        triggerVcell=float(
            section.get('triggerVcell', defaults.triggerVcell),
        ),
        hysteresisVcell=float(
            section.get('hysteresisVcell', defaults.hysteresisVcell),
        ),
    )
