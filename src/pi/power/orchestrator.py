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
# 2026-05-02    | Rex (US-276) | Wired the orchestrator state-file writer.
#                              | PowerDownOrchestrator now writes
#                              | /var/run/eclipse-obd/orchestrator-state.json
#                              | on every tick via atomic rename (write to
#                              | <path>.tmp + os.replace).  Schema:
#                              | pd_stage / pd_tick_count (load-bearing per
#                              | scripts/drain_forensics.py reader, US-276
#                              | stop-condition #2) plus lastTickTimestamp /
#                              | lastVcellRead / powerSource forensic fields
#                              | (Spool's Story 2 spec).  Closes the Sprint-22
#                              | ship gap that left the logger CSV's pd_stage
#                              | + pd_tick_count columns at unknown / -1
#                              | across Drains 6 and 7.  Failure path
#                              | (PermissionError / missing dir / full disk)
#                              | logs at ERROR but NEVER propagates --
#                              | forensics MUST NOT block the safety ladder.
#                              | Per US-276 stop-condition #1, the writer
#                              | does NOT create the parent directory --
#                              | US-277's deploy-pi.sh + systemd-tmpfiles
#                              | owns /var/run/eclipse-obd/ provisioning;
#                              | a missing dir falls through to the OSError
#                              | catch and is logged-and-skipped.
#                              | The writer is reached via try/finally
#                              | wrapping the tick() body so EVERY exit path
#                              | (early returns + normal flow) emits a fresh
#                              | snapshot.  No-op when stateFilePath is None
#                              | (default; preserves all existing test
#                              | fixtures that never wired the writer).
# 2026-05-03    | Rex (US-279) | LADDER FIX -- the actual close of the 8-drain
#                              | saga.  Drain Test 8 (2026-05-03 08:50-09:08
#                              | CDT) ran with full Sprint 23 instrumentation
#                              | and ISOLATED the bug definitively: tick()
#                              | reads power_source from a stale/decoupled
#                              | view.  UpsMonitor's polling loop logged the
#                              | BATTERY transition at 08:50:22 but every
#                              | one of 214 orchestrator tick decisions
#                              | emitted reason=power_source!=BATTERY.
#                              | Fix per CIO 2026-05-03 mandate (Option B
#                              | event-driven callback): orchestrator now
#                              | exposes _onPowerSourceChange(newSource) and
#                              | maintains self._powerSource attribute updated
#                              | synchronously on every transition the
#                              | UpsMonitor polling thread fires.  tick() reads
#                              | self._powerSource as the authoritative source
#                              | when the callback has fired at least once,
#                              | falling back to the currentSource parameter
#                              | only for back-compat with existing test
#                              | fixtures that never wired the callback.  This
#                              | ELIMINATES the stale-arg bug class -- once
#                              | the polling thread observes BATTERY the
#                              | orchestrator sees BATTERY on every subsequent
#                              | tick regardless of what the caller passes.
#                              | Lifecycle.py wires the registration via
#                              | UpsMonitor.registerSourceChangeCallback (new
#                              | API).  The runtime-validation gate is the
#                              | new tests/pi/power/test_orchestrator_battery_
#                              | callback.py integration test that mirrors
#                              | Drain 8's failure mode and FAILS pre-fix.
# 2026-05-03    | Rex (US-280) | Silent-fail diagnosis on the US-276 state-file
#                              | writer.  Drain Test 8 (2026-05-03 08:50-09:08
#                              | CDT) CSV showed pd_stage=unknown / pd_tick_
#                              | count=-1 across all 177 data rows -- the
#                              | writer was failing every tick at runtime.
#                              | Pre-US-280 the OSError catch logged at
#                              | ERROR but the log was indistinguishable
#                              | from any other writer ERROR and spammed
#                              | at the 5s tick cadence (200+ identical
#                              | ERROR lines drown every other journal
#                              | signal in a 17-min battery window).
#                              | US-280 introduces self._stateFileFirst
#                              | FailureLogged flag + a single distinguished
#                              | "STATE_FILE_FIRST_FAILURE" alarm log on the
#                              | first failure (capturing exception type +
#                              | path + message), with subsequent failures
#                              | suppressed silently.  Post-fix journalctl
#                              | grep gets a 3-cell truth-table from the
#                              | (alarm-present, alarm-absent + tickCount > 0,
#                              | alarm-absent + tickCount == 0) signals.
#                              | tick() never propagates the exception
#                              | (US-276 invariant preserved -- forensics
#                              | MUST NOT block the safety ladder).
# 2026-05-07    | Rex (US-288) | Stage state-machine latching (Spool Story 5).
#                              | Drain analysis showed 7 WARNING + 6 IMMINENT
#                              | rows across 4 drain tests vs 4 TRIGGER --
#                              | _enterWarning / _enterImminent re-fired on
#                              | every tick where the existing _state-based
#                              | gate passed, including after a hysteresis-
#                              | induced de-escalation back to NORMAL (the
#                              | VCELL >= warningVcell + hysteresisVcell
#                              | recovery path).  Fix: new _highWaterStage
#                              | attribute (PowerState) tracks the highest
#                              | stage entered in the current drain event;
#                              | escalation gates use _highWaterStage instead
#                              | of _state.  WARNING fires only if high-water
#                              | is NORMAL; IMMINENT only if high-water in
#                              | {NORMAL, WARNING}; TRIGGER only if in
#                              | {NORMAL, WARNING, IMMINENT}.  _acRestore
#                              | resets the high-water mark to NORMAL so a
#                              | fresh drain event fires every stage again.
#                              | Hysteresis de-escalation continues to mutate
#                              | _state for the US-234 invariant but does NOT
#                              | reset the high-water mark -- the latching
#                              | gate is orthogonal to hysteresis.  TRIGGER
#                              | atomicity unchanged (still gated by the
#                              | _state == TRIGGER terminal early-return AND
#                              | the _shutdownFired flag).  Existing US-234
#                              | hysteresis tests in test_orchestrator_vcell_
#                              | hysteresis.py continue to pass unchanged --
#                              | none of them re-test WARNING re-fire after
#                              | a hysteresis recovery, which is the bug
#                              | class US-288 closes.
# 2026-05-02    | Rex (US-275) | Round 3 discriminator -- INFO-log every
#                              | BATTERY-relevant tick() call with the full
#                              | decision-relevant state (vcell + currentStage
#                              | + thresholds + willTransition + reason) so a
#                              | post-Drain-8 forensic walk at the default
#                              | journalctl level (US-266 DEBUG was invisible
#                              | by default) identifies which gating mode is
#                              | silently bailing. Drain Test 7 proved tick
#                              | thread runs (337 ticks across 16 min on
#                              | battery) but _enterStage was NEVER called
#                              | despite VCELL crossing all 3 thresholds.
#                              | The 5 reason values discriminate:
#                              | power_source!=BATTERY = state-caching bug;
#                              | vcell_none = upstream None-corruption (NEW
#                              | defensive guard -- previously TypeError'd
#                              | loud); already_at_stage = TRIGGER terminal;
#                              | threshold_not_crossed = comparison-logic
#                              | bug (sign error/units mismatch);
#                              | OK = transition fired (if no STAGE_* row
#                              | post-OK -> bug is downstream of tick()).
#                              | NO log on AC happy path (EXTERNAL during
#                              | NORMAL) so journal is not flooded.
#                              | US-266 DEBUG logs preserved unchanged.
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

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.common.time.helper import utcIsoNow
from src.pi.power.battery_health import BatteryHealthRecorder

# Deferred to avoid a circular import. ``pi.hardware.ups_monitor`` goes
# through ``pi/hardware/__init__.py`` which re-exports
# ``hardware_manager``, which imports this module back for
# ``PowerDownOrchestrator`` + ``ShutdownThresholds``. Using TYPE_CHECKING
# for the type hint and a local import inside :meth:`tick` keeps the
# module top-level free of the cycle.
#
# V0.24.1 hotfix: import path is the no-prefix `pi.hardware.ups_monitor`
# rather than `src.pi.hardware.ups_monitor`.  Production main.py adds
# both `<repo>/` and `<repo>/src/` to sys.path; the two import forms
# resolve to DISTINCT module objects with DISTINCT PowerSource enum
# classes.  Pre-fix the polling thread (lifecycle.py:1489 imports
# `pi.hardware.X`) delivered enum values from one module while tick()
# compared against `_PS` from the other -- equality always False,
# ladder bailed every tick across 9 drain tests.
if TYPE_CHECKING:  # pragma: no cover
    from pi.hardware.ups_monitor import PowerSource

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
        stateFilePath: Path | None = None,
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
            stateFilePath: US-276 optional path for the JSON state file the
                drain-forensics logger reads.  When set, every :meth:`tick`
                writes ``{pd_stage, pd_tick_count, lastTickTimestamp,
                lastVcellRead, powerSource}`` via atomic rename so the
                logger CSV's ``pd_stage`` + ``pd_tick_count`` columns hold
                live values instead of ``unknown`` / ``-1`` sentinels.
                When ``None`` (default), tick() is unchanged from
                pre-US-276 behavior -- this preserves every existing test
                fixture that never wired the writer.
        """
        self._thresholds = thresholds
        self._recorder = batteryHealthRecorder
        self._shutdownAction = shutdownAction
        self._onWarning = onWarning
        self._onImminent = onImminent
        self._onAcRestore = onAcRestore
        self._powerLogWriter = powerLogWriter
        self._stateFilePath = stateFilePath

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

        # US-279 LADDER FIX -- live power source attribute updated by
        # _onPowerSourceChange callback (registered on UpsMonitor at
        # lifecycle wiring time).  Initialized to None: tick() falls back to
        # the currentSource parameter when the callback has not fired yet
        # (back-compat with all test fixtures that pass currentSource= and
        # never wire the callback).  Once the polling thread observes ANY
        # source transition, self._powerSource is set authoritatively and
        # tick() reads it on every subsequent call regardless of what the
        # caller passes -- this is the source-of-truth shift that closes
        # the 8-drain saga bug class (Drain Test 8 isolated the stale/
        # decoupled view in tick()'s caller).
        self._powerSource: PowerSource | None = None

        # US-280 first-failure dedup flag for the state-file writer.  Set
        # True the first time _writeStateFile catches an OSError; gates the
        # distinguished STATE_FILE_FIRST_FAILURE alarm so journalctl gets
        # exactly one log per orchestrator instance.  Subsequent failures
        # are silently suppressed to avoid spamming ~200 identical ERROR
        # lines across a 17-min battery drain (the Drain 8 failure mode).
        self._stateFileFirstFailureLogged: bool = False

        # US-288 stage-latching high-water mark.  Tracks the highest stage
        # entered in the current drain event so escalation gates ratchet
        # one-way: once advanced, do NOT re-fire the same stage even if
        # VCELL hysteresis fluctuates _state back to NORMAL.  Set by
        # _enterWarning / _enterImminent / _enterTrigger; reset to NORMAL
        # by _acRestore (a real AC restoration ends the drain event so the
        # next BATTERY cycle SHOULD fire all 3 stages again).  Orthogonal
        # to _state -- hysteresis still mutates _state for the US-234
        # invariant (VCELL recovery >= 3.75V returns state to NORMAL) but
        # NEVER touches the high-water mark.  Pre-US-288 drain analysis
        # showed 7 WARNING + 6 IMMINENT rows across 4 drain tests (vs 4
        # TRIGGER); the latch closes that bug class.
        self._highWaterStage: PowerState = PowerState.NORMAL

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

    def _onPowerSourceChange(self, newSource: PowerSource) -> None:
        """Receive an authoritative PowerSource transition (US-279).

        Registered as a callback on :class:`UpsMonitor` via
        :meth:`UpsMonitor.registerSourceChangeCallback` at lifecycle
        wiring time.  The polling thread invokes this method
        synchronously on every EXTERNAL <-> BATTERY (or <-> UNKNOWN)
        transition with the new ``PowerSource``.  The single side
        effect is to update :attr:`_powerSource`; the next
        :meth:`tick` call (whether from the same thread or another) sees
        the fresh value and the gating guard passes when on BATTERY.

        Single-writer / single-reader pattern (callback writes, tick()
        reads); enum attribute reads + writes are GIL-atomic in CPython,
        so no lock is required.

        Args:
            newSource: The new :class:`PowerSource` observed by UpsMonitor.
        """
        self._powerSource = newSource
        logger.debug(
            "PowerDownOrchestrator._onPowerSourceChange: %s -> live power source",
            getattr(newSource, "value", newSource),
        )

    def tick(self, *, currentVcell: float, currentSource: PowerSource) -> None:
        """Evaluate one state-machine tick.

        US-279: When :meth:`_onPowerSourceChange` has fired at least
        once (i.e. :attr:`_powerSource` is non-None), tick() reads the
        callback-driven attribute as the authoritative source and
        IGNORES the ``currentSource`` parameter.  The parameter remains
        in the signature for back-compat with existing test fixtures
        and as a fallback for the cold-start window before the polling
        thread has observed any transition.  This source-of-truth shift
        is the close of the 8-drain saga -- pre-US-279 every tick read
        the (potentially stale) caller-passed value, and Drain Test 8
        proved that pattern can decouple from UpsMonitor's live view
        for an entire 17-min battery window without firing the ladder.

        Args:
            currentVcell: Current battery cell voltage in volts (LiPo
                3.0-4.3) from ``UpsMonitor.getVcell``.
            currentSource: Fallback power source for back-compat / cold
                start.  Once the callback has fired, ``self._powerSource``
                takes precedence and this argument is ignored.
        """
        # US-262: increment counter BEFORE any early-return guard so the
        # forensic CSV's pd_tick_count column distinguishes "thread never
        # ran" (count==0) from "thread ran but bailed early" (count>0,
        # pd_stage==NORMAL). Single-writer counter, no lock needed.
        self._tickCount += 1

        # US-279: callback-driven source is authoritative once it has
        # fired; otherwise fall back to the caller-passed value.  This
        # eliminates the Drain 8 stale-cached-read failure mode while
        # preserving every existing test fixture that wires currentSource=.
        effectiveSource = (
            self._powerSource if self._powerSource is not None
            else currentSource
        )

        # US-266 Discriminator B: every silent-bail early-return below
        # emits a DEBUG log capturing the bail-causing value.  The
        # forensic chain (logger CSV pd_tick_count column + journalctl
        # DEBUG lines) lets a post-Drain-7 walk identify which guard,
        # if any, swallowed a BATTERY -> WARNING transition.  Behavior
        # is otherwise unchanged: same conditions, same returns.
        #
        # US-275 Round 3 discriminator: every BATTERY-relevant tick also
        # emits ONE INFO-level log line capturing the per-tick decision
        # so a post-Drain-8 walk at the default journalctl level can
        # identify which gating mode is silently bailing. The AC happy
        # path (EXTERNAL during NORMAL) is the only path that does NOT
        # emit -- prevents log spam during normal operation.
        sourceValue = getattr(effectiveSource, "value", effectiveSource)
        priorState = self._state

        # US-276 try/finally: state-file write must happen on EVERY exit
        # path (early returns + normal flow) so the drain_forensics logger
        # CSV's pd_stage + pd_tick_count columns hold live values across
        # all tick() outcomes, not just the happy path.
        try:
            self._tickBody(
                currentVcell=currentVcell,
                currentSource=effectiveSource,
                sourceValue=sourceValue,
                priorState=priorState,
            )
        finally:
            self._writeStateFile(
                lastVcellRead=currentVcell,
                powerSource=str(sourceValue),
            )

    def _tickBody(
        self,
        *,
        currentVcell: float,
        currentSource: PowerSource,
        sourceValue: Any,
        priorState: PowerState,
    ) -> None:
        """Original tick() body extracted for the US-276 try/finally wrap.

        Behavior is byte-identical to pre-US-276; the extraction exists
        purely so the state-file write happens on every return path.

        V0.24.1 hotfix: import via `pi.hardware.ups_monitor` (no `src.`
        prefix) so the PowerSource enum class loaded here matches the
        one the UpsMonitor polling thread delivers via the registered
        callback.  Pre-fix the prefix mismatch produced two distinct
        enum classes -- BATTERY_via_pi != BATTERY_via_src_pi -- and
        every tick bailed `power_source!=BATTERY`.
        """
        from pi.hardware.ups_monitor import PowerSource as _PS

        if not self._thresholds.enabled:
            logger.debug(
                "tick early-return: thresholds.enabled=False "
                "(currentVcell=%s source=%s)",
                currentVcell, sourceValue,
            )
            # No US-275 INFO log here -- enabled=False is a config setting,
            # not a diagnostic signal. The orchestrator is intentionally
            # off; spamming the journal would obscure useful signals.
            return

        if self._state == PowerState.TRIGGER:
            # Terminal state -- no further action.
            logger.debug(
                "tick early-return: state=TRIGGER terminal "
                "(currentVcell=%s source=%s)",
                currentVcell, sourceValue,
            )
            self._logTickDecision(
                currentVcell=currentVcell,
                currentStage=priorState,
                willTransition=False,
                reason="already_at_stage",
            )
            return

        if currentSource == _PS.EXTERNAL:
            # AC restore during non-NORMAL -> full reset.
            if self._state != PowerState.NORMAL:
                self._acRestore(currentVcell)
                # _acRestore logs at INFO level on its own; the US-275
                # INFO log is for the per-tick gating decision, and the
                # AC-restore path is fundamentally a state transition
                # that has its own dedicated log line. Skip US-275 here
                # to avoid duplicate-with-different-shape log noise.
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
            # No US-275 INFO log on the AC happy path -- the journal
            # would flood at the UPS poll cadence (5s) during normal
            # non-drain operation. The negative-invariant test
            # TestAcHappyPathEmitsNoInfoLog enforces this rule.
            return

        if currentSource != _PS.BATTERY:
            # UNKNOWN -> do nothing (next tick may clarify)
            logger.debug(
                "tick early-return: source=%s expected BATTERY "
                "(currentVcell=%s)",
                sourceValue, currentVcell,
            )
            self._logTickDecision(
                currentVcell=currentVcell,
                currentStage=priorState,
                willTransition=False,
                reason="power_source!=BATTERY",
            )
            return

        # US-275 defensive None-guard for vcell. UpsMonitor.getVcell()
        # raises on read failure rather than returning None, so the only
        # path here is upstream state-caching corruption (a stale-cached
        # None reaching tick() across module boundaries). Pre-US-275 this
        # path TypeError'd on the threshold comparison below and was
        # caught loud by _powerDownTickLoop's except Exception as ERROR;
        # post-US-275 we bail with a single INFO discriminator instead --
        # the high-frequency forensic signal Spool wants for Drain Test 8.
        if currentVcell is None:
            self._logTickDecision(
                currentVcell=None,
                currentStage=priorState,
                willTransition=False,
                reason="vcell_none",
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
        #
        # US-288 latching: gate on _highWaterStage instead of _state.
        # WARNING fires only if high-water is NORMAL (never advanced past).
        # IMMINENT fires only if high-water in {NORMAL, WARNING} (allows
        # forward escalation IMMINENT-from-NORMAL after a hysteresis-induced
        # de-escalation, while blocking IMMINENT re-fire once entered).
        # TRIGGER fires only if high-water in {NORMAL, WARNING, IMMINENT}
        # (one-way ratchet; the existing _shutdownFired flag separately
        # ensures shutdownAction runs at most once even on multiple TRIGGER
        # entries in pathological code paths).
        if (
            self._highWaterStage == PowerState.NORMAL
            and currentVcell <= self._thresholds.warningVcell
        ):
            self._enterWarning(currentVcell)

        if (
            self._highWaterStage in (PowerState.NORMAL, PowerState.WARNING)
            and currentVcell <= self._thresholds.imminentVcell
        ):
            self._enterImminent(currentVcell)

        if (
            self._highWaterStage in (
                PowerState.NORMAL, PowerState.WARNING, PowerState.IMMINENT,
            )
            and currentVcell <= self._thresholds.triggerVcell
        ):
            self._enterTrigger(currentVcell)
            self._logTickDecision(
                currentVcell=currentVcell,
                currentStage=priorState,
                willTransition=True,
                reason="OK",
            )
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

        # US-275 end-of-decision INFO log. willTransition is computed by
        # comparing the post-tick state to priorState -- if state changed,
        # a stage transition fired (NORMAL->WARNING, WARNING->IMMINENT,
        # WARNING->NORMAL via hysteresis). The IMMINENT->TRIGGER path
        # already logged + returned above.
        willTransition = self._state != priorState
        reason = "OK" if willTransition else "threshold_not_crossed"
        self._logTickDecision(
            currentVcell=currentVcell,
            currentStage=priorState,
            willTransition=willTransition,
            reason=reason,
        )

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
        self._highWaterStage = PowerState.WARNING
        self._writePowerLogStage("stage_warning", vcell)
        self._invokeCallback("onWarning", self._onWarning)

    def _enterImminent(self, vcell: float) -> None:
        logger.warning(
            "PowerDownOrchestrator: IMMINENT at %.3fV", vcell,
        )
        self._state = PowerState.IMMINENT
        self._highWaterStage = PowerState.IMMINENT
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
        self._highWaterStage = PowerState.TRIGGER
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
        # US-288: a real AC restoration ends the drain event.  Reset the
        # high-water mark so the next BATTERY cycle re-fires every stage
        # (drain analysis: 1 row of each stage type per power-down event).
        self._highWaterStage = PowerState.NORMAL
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

    def _logTickDecision(
        self,
        *,
        currentVcell: float | None,
        currentStage: PowerState,
        willTransition: bool,
        reason: str,
    ) -> None:
        """Emit the US-275 per-tick decision log.

        Shape locked by Spool's Story 1 spec block::

            PowerDownOrchestrator.tick: vcell=3.276 currentStage=NORMAL
              thresholds={WARNING:3.70, IMMINENT:3.55, TRIGGER:3.45}
              willTransition=False reason=<reason>

        The 5 ``reason`` field values discriminate Drain Test 8 hypothesis
        modes (see module-level docstring + the US-275 mod-history entry).
        ``currentStage`` is the PRE-tick state so a forensic walk can
        correlate the journalctl line with the logger CSV's ``pd_stage``
        column at the same tick timestamp.

        ``currentVcell`` is rendered as ``None`` when the upstream
        state-caching corruption mode (US-275 vcell_none guard) bails;
        otherwise as ``%.3f`` for 1mV resolution matching the LiPo
        signal-to-noise floor.
        """
        vcellRepr = "None" if currentVcell is None else f"{currentVcell:.3f}"
        logger.info(
            "PowerDownOrchestrator.tick: vcell=%s currentStage=%s "
            "thresholds={WARNING:%.2f, IMMINENT:%.2f, TRIGGER:%.2f} "
            "willTransition=%s reason=%s",
            vcellRepr,
            currentStage.value,
            self._thresholds.warningVcell,
            self._thresholds.imminentVcell,
            self._thresholds.triggerVcell,
            willTransition,
            reason,
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

    def _writeStateFile(
        self,
        *,
        lastVcellRead: float | None,
        powerSource: str,
    ) -> None:
        """Atomically rewrite the orchestrator state JSON file (US-276).

        Closes the Sprint-22 ship gap that left the drain_forensics logger's
        ``pd_stage`` and ``pd_tick_count`` CSV columns at ``unknown`` /
        ``-1`` sentinels across Drains 6 + 7.  The reader at
        ``scripts/drain_forensics.py::_readOrchestratorState`` requires the
        ``pd_stage`` and ``pd_tick_count`` keys verbatim (US-276
        stop-condition #2: do NOT change reader).  Spool's Story 2 spec
        also asks for ``lastTickTimestamp`` (canonical ISO via
        :func:`utcIsoNow`), ``lastVcellRead``, and ``powerSource`` as
        additive forensic fields.

        Atomic rename via ``os.replace`` (POSIX renameat2 on Linux) so the
        sibling drain_forensics process never sees a partial / corrupt
        JSON file -- the reader either gets the prior file or the new one.
        Any filesystem failure (PermissionError, missing parent dir, full
        disk) is logged at ERROR but NEVER propagates -- forensics MUST
        NOT block the safety ladder.

        No-op when ``stateFilePath`` is ``None`` (test fixtures that never
        wired the writer; preserves the pre-US-276 default).
        """
        if self._stateFilePath is None:
            return

        # US-276 stop-condition #1: directory creation is US-277's
        # territory (deploy-pi.sh + systemd-tmpfiles).  When the parent
        # directory is missing, the open() below raises FileNotFoundError
        # (subclass of OSError); we log-and-skip rather than create the
        # directory ourselves.
        try:
            payload = {
                'pd_stage': self._state.value,
                'pd_tick_count': self._tickCount,
                'lastTickTimestamp': utcIsoNow(),
                'lastVcellRead': lastVcellRead,
                'powerSource': powerSource,
            }
            tmpPath = self._stateFilePath.with_suffix(
                self._stateFilePath.suffix + '.tmp',
            )
            with tmpPath.open('w', encoding='utf-8') as fp:
                json.dump(payload, fp)
            os.replace(tmpPath, self._stateFilePath)
        except OSError as e:
            # US-280: first failure emits a distinguished alarm capturing
            # exception type + path + message so post-mortem can grep
            # journalctl for STATE_FILE_FIRST_FAILURE; subsequent failures
            # are silently suppressed to avoid log spam at the 5s tick
            # cadence (Drain 8 baseline: 200+ identical ERROR lines).
            if not self._stateFileFirstFailureLogged:
                logger.error(
                    "PowerDownOrchestrator: STATE_FILE_FIRST_FAILURE -- "
                    "%s on %s: %s "
                    "(alarm raised once; subsequent failures suppressed "
                    "to avoid journal spam at tick cadence)",
                    type(e).__name__,
                    self._stateFilePath,
                    e,
                )
                self._stateFileFirstFailureLogged = True


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
