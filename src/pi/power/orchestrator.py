################################################################################
# File Name: orchestrator.py
# Purpose/Description: PowerDownOrchestrator -- staged 30/25/20 SOC shutdown
#                      state machine. Consumes UpsMonitor SOC + power-source
#                      change callbacks; fires WARNING / IMMINENT / TRIGGER
#                      stage behaviors with hysteresis; opens + closes
#                      battery_health_log rows (US-217); wraps
#                      ShutdownHandler._executeShutdown as the terminal
#                      action. Built fresh per Spool audit 2026-04-21 --
#                      the existing power-mgmt codebase (PowerMonitor,
#                      BatteryMonitor, readers, etc.) is dead; only
#                      UpsMonitor + ShutdownHandler run today and neither
#                      implements a staged ladder.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-216) | Initial -- staged shutdown orchestrator.
# ================================================================================
################################################################################

"""Power-down orchestrator (US-216 / CIO directive 2, Spool Session 6).

Problem
-------
The 2026-04-20 UPS drain test showed the Pi hard-crashes at ~0% SOC because
the only live shutdown path was ``ShutdownHandler``'s binary 10% trigger +
30s-after-BATTERY timer. CIO directive 2 mandates a staged ladder at
warning 30% / imminent 25% / trigger 20% to give subsystems time to
quiesce before ``systemctl poweroff``.

Design
------
Pure state machine driven by :meth:`PowerDownOrchestrator.tick`. The
caller (hardware_manager's display update loop) feeds ``(currentSoc,
currentSource)`` pairs at the UPS poll cadence (5s). On each tick:

1. ``currentSource == EXTERNAL`` during a non-NORMAL state triggers the
   AC-restore path: cancel pending stages, close the drain-event row as
   ``recovered``, back to NORMAL.
2. ``currentSource == BATTERY`` with falling SOC escalates the state
   monotonically: NORMAL -> WARNING -> IMMINENT -> TRIGGER.
3. Hysteresis: once in WARNING/IMMINENT, SOC must climb back to
   ``thresholdSoc + hysteresisSoc`` to de-escalate (prevents 29/31
   oscillation).
4. TRIGGER is terminal -- further ticks are ignored, ``shutdownAction``
   fires exactly once.

Stage behaviors
---------------
* **WARNING@30%**: open ``battery_health_log`` row; invoke optional
  ``onWarning`` callback. Callers wire the callback to: set
  ``pi_state.no_new_drives=true``, force SyncClient push.
* **IMMINENT@25%**: invoke optional ``onImminent`` callback. Callers
  wire: stop OBD poll-tier dispatch, close BT via US-211 clean-close,
  force KEY_OFF on active drive via ``DriveDetector.forceKeyOff``.
* **TRIGGER@20%**: close the drain-event row, invoke ``shutdownAction``
  (typically ``ShutdownHandler._executeShutdown`` = ``systemctl
  poweroff``). One-way action.
* **AC-restore**: cancel pending stages, close drain-event row with
  ``notes='recovered'``, invoke optional ``onAcRestore`` callback.

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

    Attributes:
        enabled: Master on/off. When False, :meth:`PowerDownOrchestrator.tick`
            is a no-op and the legacy ShutdownHandler path remains the sole
            shutdown mechanism.
        warningSoc: SOC % at which to enter WARNING stage (default 30).
        imminentSoc: SOC % at which to enter IMMINENT stage (default 25).
        triggerSoc: SOC % at which to fire TRIGGER stage +
            ``systemctl poweroff`` (default 20).
        hysteresisSoc: % band required above a stage's threshold to
            de-escalate from that stage (default 5). Prevents flap on
            SOC reads oscillating around the threshold.
    """

    enabled: bool = True
    warningSoc: int = 30
    imminentSoc: int = 25
    triggerSoc: int = 20
    hysteresisSoc: int = 5


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


class PowerDownOrchestrator:
    """Staged-shutdown state machine driven by SOC + power-source ticks.

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
    ) -> None:
        """Initialize the orchestrator.

        Args:
            thresholds: Config values (enabled flag + SOC bands).
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
        """
        self._thresholds = thresholds
        self._recorder = batteryHealthRecorder
        self._shutdownAction = shutdownAction
        self._onWarning = onWarning
        self._onImminent = onImminent
        self._onAcRestore = onAcRestore

        self._state: PowerState = PowerState.NORMAL
        self._activeDrainEventId: int | None = None
        self._shutdownFired: bool = False
        # Track the highest SOC seen on battery in this drain event so the
        # battery_health_log row records the true drain-start SOC rather
        # than the WARNING threshold crossing. Reset on AC restore.
        self._highestBatterySoc: int | None = None

        logger.debug(
            "PowerDownOrchestrator initialized: enabled=%s "
            "warning=%d imminent=%d trigger=%d hysteresis=%d",
            thresholds.enabled,
            thresholds.warningSoc,
            thresholds.imminentSoc,
            thresholds.triggerSoc,
            thresholds.hysteresisSoc,
        )

    @property
    def state(self) -> PowerState:
        return self._state

    @property
    def activeDrainEventId(self) -> int | None:
        return self._activeDrainEventId

    def tick(self, *, currentSoc: int, currentSource: PowerSource) -> None:
        """Evaluate one state-machine tick.

        Args:
            currentSoc: Current battery SOC % (0-100) from
                ``UpsMonitor.getBatteryPercentage``.
            currentSource: Current power source from
                ``UpsMonitor.getPowerSource``.
        """
        from src.pi.hardware.ups_monitor import PowerSource as _PS

        if not self._thresholds.enabled:
            return

        if self._state == PowerState.TRIGGER:
            # Terminal state -- no further action.
            return

        if currentSource == _PS.EXTERNAL:
            # AC restore during non-NORMAL -> full reset.
            if self._state != PowerState.NORMAL:
                self._acRestore(currentSoc)
            return

        if currentSource != _PS.BATTERY:
            # UNKNOWN -> do nothing (next tick may clarify)
            return

        # On battery. Track the highest SOC seen pre-WARNING so the
        # drain-event row captures the true starting SOC.
        if self._state == PowerState.NORMAL and (
            self._highestBatterySoc is None
            or currentSoc > self._highestBatterySoc
        ):
            self._highestBatterySoc = currentSoc

        # Check escalation. Use a fall-through so a single fast
        # drop (50 -> 18) fires all stages in order before committing to
        # TRIGGER.
        if (
            self._state == PowerState.NORMAL
            and currentSoc <= self._thresholds.warningSoc
        ):
            self._enterWarning(currentSoc)

        if (
            self._state == PowerState.WARNING
            and currentSoc <= self._thresholds.imminentSoc
        ):
            self._enterImminent(currentSoc)

        if (
            self._state == PowerState.IMMINENT
            and currentSoc <= self._thresholds.triggerSoc
        ):
            self._enterTrigger(currentSoc)
            return

        # Check de-escalation. Only meaningful during a drain where SOC
        # recovers without an AC transition (rare; belt-and-braces for
        # the hysteresis invariant in the story).
        if self._state == PowerState.WARNING:
            deEscalateAt = (
                self._thresholds.warningSoc + self._thresholds.hysteresisSoc
            )
            if currentSoc >= deEscalateAt:
                self._deEscalateWarningToNormal(currentSoc)

    # --------------------------------------------------------------------- #
    # Stage entry helpers
    # --------------------------------------------------------------------- #

    def _enterWarning(self, soc: int) -> None:
        logger.warning(
            "PowerDownOrchestrator: WARNING at %d%% -- opening drain event", soc,
        )
        # Use the highest SOC observed on battery in this drain if it's
        # higher than the current WARNING-entry SOC. This captures the
        # drain-start SOC for battery_health_log analytics.
        startSoc = (
            self._highestBatterySoc
            if self._highestBatterySoc is not None
            and self._highestBatterySoc > soc
            else soc
        )
        try:
            self._activeDrainEventId = self._recorder.startDrainEvent(
                startSoc=float(startSoc),
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
        self._invokeCallback("onWarning", self._onWarning)

    def _enterImminent(self, soc: int) -> None:
        logger.warning("PowerDownOrchestrator: IMMINENT at %d%%", soc)
        self._state = PowerState.IMMINENT
        self._invokeCallback("onImminent", self._onImminent)

    def _enterTrigger(self, soc: int) -> None:
        logger.warning(
            "PowerDownOrchestrator: TRIGGER at %d%% -- initiating poweroff", soc,
        )
        # Close the drain event BEFORE poweroff so the row has a valid
        # end_timestamp / end_soc even if the process exits immediately.
        self._closeDrainEvent(soc, ambientTempC=None)
        self._state = PowerState.TRIGGER
        if self._shutdownFired:
            return
        self._shutdownFired = True
        try:
            self._shutdownAction()
        except Exception as e:  # noqa: BLE001
            logger.error(
                "PowerDownOrchestrator: shutdownAction raised: %s", e,
            )

    def _acRestore(self, currentSoc: int) -> None:
        priorState = self._state
        logger.info(
            "PowerDownOrchestrator: AC restored at %d%% during %s -- cancelling",
            currentSoc, priorState.value,
        )
        self._closeDrainEvent(currentSoc, ambientTempC=None)
        self._state = PowerState.NORMAL
        self._shutdownFired = False
        self._highestBatterySoc = None
        self._invokeCallback("onAcRestore", self._onAcRestore)

    def _deEscalateWarningToNormal(self, currentSoc: int) -> None:
        logger.info(
            "PowerDownOrchestrator: WARNING -> NORMAL at %d%% "
            "(hysteresis recovery on battery)",
            currentSoc,
        )
        self._closeDrainEvent(currentSoc, ambientTempC=None)
        self._state = PowerState.NORMAL

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _closeDrainEvent(
        self, endSoc: int, *, ambientTempC: float | None,
    ) -> None:
        """Close the active drain-event row, if any."""
        if self._activeDrainEventId is None:
            return
        try:
            self._recorder.endDrainEvent(
                drainEventId=self._activeDrainEventId,
                endSoc=float(endSoc),
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


# ================================================================================
# Factory
# ================================================================================


def createShutdownThresholdsFromConfig(
    config: dict[str, Any],
) -> ShutdownThresholds:
    """Build :class:`ShutdownThresholds` from a config dict.

    Reads ``config['pi']['power']['shutdownThresholds']``; any missing
    field falls through to the dataclass default.

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
        warningSoc=int(section.get('warningSoc', defaults.warningSoc)),
        imminentSoc=int(section.get('imminentSoc', defaults.imminentSoc)),
        triggerSoc=int(section.get('triggerSoc', defaults.triggerSoc)),
        hysteresisSoc=int(
            section.get('hysteresisSoc', defaults.hysteresisSoc),
        ),
    )
