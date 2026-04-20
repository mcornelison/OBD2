################################################################################
# File Name: engine_state.py
# Purpose/Description: Engine-state machine + drive_id generator for the Pi
#                      collector (US-200 / Spool Data v2 Story 2).  Pure
#                      class, no DB side effects -- callers inject the
#                      drive_id generator and own persistence.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex (US-200) | Initial -- engine state machine + drive_id
#                               transitions for Spool-spec'd per-drive scoping.
# ================================================================================
################################################################################

"""Engine-state machine for drive_id scoping (Spool Priority 3 / US-200).

The Pi collector writes rows into ``realtime_data``, ``connection_log``,
``statistics`` and ``alert_log`` at ~3 rows/sec across multiple drives.
Before US-200 those rows had no per-drive grouping -- the Session 23
drill produced 149 real rows spanning 2 connection windows and we could
not say "give me the warmup curve of drive N" without manual time-slicing.

US-200 introduces a ``drive_id`` column on the 4 capture tables, filled
in by writers from the state machine below.  The state machine owns the
transitions (UNKNOWN -> CRANKING -> RUNNING -> KEY_OFF) and the
assignment of ``drive_id`` via an injectable generator; the actual
persistence layer (``drive_id`` table counter, migration helpers) lives
in :mod:`src.pi.obdii.drive_id`.

Transition model::

    UNKNOWN ----rpm >= crankThreshold---> CRANKING  [drive_id assigned]
    CRANKING ---rpm >= runningThreshold--> RUNNING
    RUNNING ----rpm=0 AND speed=0 for N s-> KEY_OFF  [drive_id closed]
    *       ----forceKeyOff()------------> KEY_OFF  [external signal]

Invariants honored by this module:

* drive_id is assigned ONCE on UNKNOWN->CRANKING entry and remains
  stable until the next KEY_OFF transition.  A stall that doesn't reach
  the KEY_OFF debounce window keeps the same drive_id (we never left
  RUNNING).
* drive_id is provided by an injectable callable, not generated from
  wall-clock time -- NTP resync on the Pi can skew time backwards and
  break monotonicity.  The default implementation in ``drive_id.py`` is
  a SQLite counter table.
* The state machine is RPM/speed-driven; forceKeyOff() is a one-way
  external signal (BT disconnect, user hits the stop button) that is
  ONE input, not the primary driver.  An engine that keeps running
  while BT drops stays in RUNNING from the state machine's POV.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

__all__ = [
    'EngineState',
    'EngineStateTransition',
    'EngineStateMachine',
    'DEFAULT_CRANKING_RPM_THRESHOLD',
    'DEFAULT_RUNNING_RPM_THRESHOLD',
    'DEFAULT_KEY_OFF_DURATION_SECONDS',
]


# ================================================================================
# Spool-spec defaults
# ================================================================================

# Cranking trigger: ECU-reported RPM rising from 0 to >=250.  This is the
# starter-motor-plus-combustion-attempt regime for the 4G63; idle is ~750.
DEFAULT_CRANKING_RPM_THRESHOLD: float = 250.0

# Running trigger: once RPM climbs past this the engine is self-sustaining.
# 500 RPM is a conservative floor -- well above cranking RPM but well below
# warm idle (~750-850 per Session 23 warm-idle fingerprint).
DEFAULT_RUNNING_RPM_THRESHOLD: float = 500.0

# KEY_OFF debounce: continuous window where RPM=0 AND speed=0 must hold
# before we declare the engine off.  Spool calls 30s a "reasonable start,
# tunable" -- short enough that a proper engine-off is detected promptly
# after the CIO parks, long enough that stop-and-go traffic doesn't
# false-positive (which would start a new drive_id on every red light).
DEFAULT_KEY_OFF_DURATION_SECONDS: float = 30.0


# ================================================================================
# Public enum + transition event
# ================================================================================

class EngineState(StrEnum):
    """Coarse engine-running states seen from RPM + speed."""

    UNKNOWN = 'unknown'
    CRANKING = 'cranking'
    RUNNING = 'running'
    KEY_OFF = 'key_off'


@dataclass(frozen=True)
class EngineStateTransition:
    """Emitted whenever the machine's state changes.

    Attributes:
        fromState: Previous state.
        toState: New state.
        timestamp: Observation time that triggered the change.  Carried
            through to :meth:`EngineStateMachine.observeReading`.
        driveId: The drive_id associated with this transition.  On
            CRANKING entry this is the newly-assigned id; on KEY_OFF
            exit this is the id being closed.  On other transitions
            (UNKNOWN->CRANKING that was already CRANKING, etc.) this is
            the currently-active id.  May be ``None`` only for
            transitions that leave the machine with no active drive
            (e.g. forceKeyOff() from UNKNOWN -- not currently emitted).
    """

    fromState: EngineState
    toState: EngineState
    timestamp: datetime
    driveId: int | None


# ================================================================================
# Core state machine
# ================================================================================

class EngineStateMachine:
    """Stateful classifier: RPM + speed observations -> engine state.

    Usage::

        fromSrc = drive_id.makeDriveIdGenerator(connection)
        sm = EngineStateMachine(driveIdGenerator=fromSrc)
        transition = sm.observeReading(rpm=rpmValue, speed=speedValue, now=ts)
        if transition:
            logger.info(f"engine state: {transition.fromState} -> {transition.toState}")
        if sm.currentDriveId is not None:
            writeRowWithDriveId(sm.currentDriveId, ...)
    """

    def __init__(
        self,
        *,
        crankingRpmThreshold: float = DEFAULT_CRANKING_RPM_THRESHOLD,
        runningRpmThreshold: float = DEFAULT_RUNNING_RPM_THRESHOLD,
        keyOffDurationSeconds: float = DEFAULT_KEY_OFF_DURATION_SECONDS,
        driveIdGenerator: Callable[[], int] | None = None,
    ) -> None:
        if crankingRpmThreshold <= 0:
            raise ValueError(
                f"crankingRpmThreshold must be > 0; got {crankingRpmThreshold}"
            )
        if runningRpmThreshold < crankingRpmThreshold:
            raise ValueError(
                "runningRpmThreshold must be >= crankingRpmThreshold; "
                f"got cranking={crankingRpmThreshold} running={runningRpmThreshold}"
            )
        if keyOffDurationSeconds <= 0:
            raise ValueError(
                "keyOffDurationSeconds must be > 0; "
                f"got {keyOffDurationSeconds}"
            )
        self._crankingRpmThreshold = crankingRpmThreshold
        self._runningRpmThreshold = runningRpmThreshold
        self._keyOffDurationSeconds = keyOffDurationSeconds
        self._driveIdGenerator = driveIdGenerator
        self._state: EngineState = EngineState.UNKNOWN
        self._currentDriveId: int | None = None
        # Timestamp of first observation in the current "engine-off" run
        # (rpm=0 AND speed=0 while in RUNNING).  None whenever we break
        # out of that run.
        self._keyOffRunStart: datetime | None = None
        self._transitionCount: int = 0

    # ================================================================================
    # Public read-only state
    # ================================================================================

    @property
    def state(self) -> EngineState:
        """Current engine state."""
        return self._state

    @property
    def currentDriveId(self) -> int | None:
        """Currently-open drive_id, or ``None`` if no drive is active."""
        return self._currentDriveId

    @property
    def transitionCount(self) -> int:
        """Total state transitions since construction.  Useful for assertions."""
        return self._transitionCount

    # ================================================================================
    # Observation -- the hot path
    # ================================================================================

    def observeReading(
        self,
        *,
        rpm: float | None,
        speed: float | None,
        now: datetime,
    ) -> EngineStateTransition | None:
        """Feed one RPM + speed observation; return any resulting transition.

        Args:
            rpm: Engine RPM; ``None`` if no fresh reading is available
                this tick.
            speed: Vehicle speed; ``None`` if no fresh reading.  Used
                only for the KEY_OFF debounce -- RPM alone drives the
                CRANKING / RUNNING transitions.
            now: Observation time.  Caller owns the clock.

        Returns:
            An :class:`EngineStateTransition` if this observation caused
            a state change, else ``None``.
        """
        # A None RPM carries zero information about the engine; we
        # refuse to advance the state machine.  (An all-None speed is
        # fine as long as RPM is present; the KEY_OFF gate will simply
        # not clear until we also get speed=0.)
        if rpm is None:
            return None

        if self._state == EngineState.UNKNOWN:
            return self._handleUnknown(rpm, now)
        if self._state == EngineState.CRANKING:
            return self._handleCranking(rpm, now)
        if self._state == EngineState.RUNNING:
            return self._handleRunning(rpm, speed, now)
        # KEY_OFF -- wait for a fresh crank to open a new drive.
        return self._handleKeyOff(rpm, now)

    def forceKeyOff(
        self, now: datetime
    ) -> EngineStateTransition | None:
        """External signal that the engine is off (BT disconnect, shutdown).

        Forces an immediate transition to KEY_OFF from CRANKING or
        RUNNING, skipping the debounce.  No-op from UNKNOWN (we never
        had a drive) and from KEY_OFF (already there).
        """
        if self._state in (EngineState.UNKNOWN, EngineState.KEY_OFF):
            return None
        closedId = self._currentDriveId
        return self._transitionTo(EngineState.KEY_OFF, now, closedId,
                                  closeDrive=True)

    # ================================================================================
    # Per-state handlers (private)
    # ================================================================================

    def _handleUnknown(
        self, rpm: float, now: datetime
    ) -> EngineStateTransition | None:
        if rpm >= self._crankingRpmThreshold:
            newId = self._openNewDrive()
            return self._transitionTo(EngineState.CRANKING, now, newId)
        return None

    def _handleCranking(
        self, rpm: float, now: datetime
    ) -> EngineStateTransition | None:
        if rpm >= self._runningRpmThreshold:
            return self._transitionTo(
                EngineState.RUNNING, now, self._currentDriveId
            )
        return None

    def _handleRunning(
        self,
        rpm: float,
        speed: float | None,
        now: datetime,
    ) -> EngineStateTransition | None:
        # Both RPM and speed must be zero to start / continue the
        # KEY_OFF debounce window.  Speed defaults to 0 if missing:
        # that's conservative since a missing speed reading during idle
        # on the 2G Eclipse is common (python-obd returns None when the
        # ECU hasn't responded yet to the SPEED query).  Caller is
        # expected to pass speed=0 explicitly when cert / parked.
        speedValue = 0.0 if speed is None else speed
        if rpm == 0 and speedValue == 0:
            if self._keyOffRunStart is None:
                self._keyOffRunStart = now
                return None
            elapsed = (now - self._keyOffRunStart).total_seconds()
            if elapsed >= self._keyOffDurationSeconds:
                closedId = self._currentDriveId
                return self._transitionTo(
                    EngineState.KEY_OFF, now, closedId, closeDrive=True
                )
            return None
        # Any non-zero observation breaks the run
        self._keyOffRunStart = None
        return None

    def _handleKeyOff(
        self, rpm: float, now: datetime
    ) -> EngineStateTransition | None:
        if rpm >= self._crankingRpmThreshold:
            newId = self._openNewDrive()
            return self._transitionTo(EngineState.CRANKING, now, newId)
        return None

    # ================================================================================
    # Drive id + transition machinery
    # ================================================================================

    def _openNewDrive(self) -> int:
        if self._driveIdGenerator is None:
            raise RuntimeError(
                "drive_id generator not configured; cannot open a new drive"
            )
        newId = self._driveIdGenerator()
        self._currentDriveId = newId
        return newId

    def _transitionTo(
        self,
        newState: EngineState,
        now: datetime,
        driveId: int | None,
        *,
        closeDrive: bool = False,
    ) -> EngineStateTransition:
        transition = EngineStateTransition(
            fromState=self._state,
            toState=newState,
            timestamp=now,
            driveId=driveId,
        )
        self._state = newState
        self._transitionCount += 1
        if closeDrive:
            self._currentDriveId = None
            self._keyOffRunStart = None
        # Any non-RUNNING state has no active KEY_OFF debounce window
        if newState != EngineState.RUNNING:
            self._keyOffRunStart = None
        return transition
