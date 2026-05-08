################################################################################
# File Name: sync_cadence_controller.py
# Purpose/Description: Engine-aware sync cadence state machine
#                      (IDLE / ACTIVE / DRAINING) per B-053 Option 2 / US-298.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex (US-298) | Initial implementation: 3-state cadence
#                               controller with drive_start/drive_end event
#                               listeners, configurable cadence constants,
#                               and missed-drive-start fallback (any
#                               non-empty heartbeat in IDLE auto-promotes
#                               to ACTIVE).  Decision-API only -- US-299
#                               wires the integration into SyncClient.
# ================================================================================
################################################################################

"""
Engine-aware sync poll cadence (B-053 Option 2).

The pre-Sprint-26 sync loop polled at a constant 5/sec regardless of whether
the engine was running, producing 100k+ ``sync_log`` rows on the server side
and burning Pi battery on the UPS during long engine-off windows.  Per CIO
2026-05-05 inspection the polling is meaningful work ~5% of the time and
noise the other 95%.

This controller implements the approved hybrid: IDLE state is a 60s
heartbeat (catches stragglers + connectivity check), drive_start escalates
to a 5s ACTIVE cadence (live-stream during the drive for Spool's tuning
analysis), and drive_end fires a single final flush (DRAINING) before
returning to IDLE.

Architecture
------------

The controller does NOT call :class:`SyncClient` -- that wiring lands in
US-299.  Instead it exposes a *decision API*:

* :meth:`onDriveStart` and :meth:`onDriveEnd` are non-blocking event
  handlers wired into the existing US-200 ``onDriveStart`` / ``onDriveEnd``
  callback surface.  They mutate state only.
* :meth:`shouldSyncNow` is polled by the sync loop and returns ``True``
  when the cadence cooldown for the current state has elapsed (or when
  state is DRAINING -- the single final flush ignores cadence).
* :meth:`markSynced` is called by the sync loop after a sync attempt
  completes so the controller can refresh its cooldown and apply the
  missed-drive-start fallback.

Missed drive_start fallback
---------------------------

If the OBD layer's drive-detect callback fails to fire (BT flake at engine
startup is the canonical case), an IDLE-state heartbeat that comes back
with rows is a strong signal the engine actually started.  We escalate to
ACTIVE so we don't spend a whole drive at 60s cadence because of a single
missed event.  Empty heartbeats (the normal idle case) leave state alone.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import StrEnum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module constants (cadence values per B-053 Option 2 + CIO 2026-05-07)
# ---------------------------------------------------------------------------

# IDLE heartbeat: 60s catches stragglers + connectivity check during
# engine-off windows.  Lower than this wastes UPS battery; higher than
# this risks missing a flaked drive_start for too long.
DEFAULT_IDLE_CADENCE_SECONDS: float = 60.0

# ACTIVE cadence: 5s during a drive.  Per CIO 2026-05-07 "follow Spool's
# workflow" = post-drive batch review (5s is plenty for Spool's tuning
# analysis; 1s would be over-engineering and burn battery).
DEFAULT_ACTIVE_CADENCE_SECONDS: float = 5.0


class SyncCadenceState(StrEnum):
    """3-state machine for sync cadence."""

    IDLE = "idle"
    ACTIVE = "active"
    DRAINING = "draining"


class SyncCadenceController:
    """
    Engine-aware sync cadence state machine.

    The controller answers a single question: "should the sync loop fire a
    sync attempt RIGHT NOW?"  Its answer changes based on engine state
    (transitioned via :meth:`onDriveStart` / :meth:`onDriveEnd`) and a
    cadence cooldown that resets on each :meth:`markSynced` call.

    Args:
        now: Optional clock callable returning monotonic seconds.  Defaults
            to :func:`time.monotonic`.  Test fixtures inject a fake clock
            so cadence tests are deterministic.
        idleSeconds: IDLE-state heartbeat cadence in seconds.  Defaults
            to :data:`DEFAULT_IDLE_CADENCE_SECONDS` (60s).
        activeSeconds: ACTIVE-state cadence in seconds.  Defaults to
            :data:`DEFAULT_ACTIVE_CADENCE_SECONDS` (5s).
    """

    def __init__(
        self,
        now: Callable[[], float] | None = None,
        idleSeconds: float = DEFAULT_IDLE_CADENCE_SECONDS,
        activeSeconds: float = DEFAULT_ACTIVE_CADENCE_SECONDS,
    ) -> None:
        self._now: Callable[[], float] = now if now is not None else time.monotonic
        self._idleSeconds: float = idleSeconds
        self._activeSeconds: float = activeSeconds
        self._state: SyncCadenceState = SyncCadenceState.IDLE
        # ``None`` = never synced; first :meth:`shouldSyncNow` returns True
        # so the sync loop establishes a baseline cursor.
        self._lastSyncAt: float | None = None
        self._lastNonEmptySyncAt: float | None = None

    # -- read-only accessors ----------------------------------------------

    @property
    def state(self) -> SyncCadenceState:
        return self._state

    @property
    def lastSyncAt(self) -> float | None:
        return self._lastSyncAt

    @property
    def lastNonEmptySyncAt(self) -> float | None:
        return self._lastNonEmptySyncAt

    # -- event handlers (non-blocking, called from drive detector) --------

    def onDriveStart(self) -> None:
        """
        Drive-start event handler.

        IDLE -> ACTIVE.  No-op if already ACTIVE (re-entrant safety for
        the missed-drive-start fallback path that may have already
        promoted us).  No-op if DRAINING (a stale drive_start arriving
        after drive_end is most likely a callback ordering glitch -- the
        next non-empty heartbeat will re-promote via fallback).
        """
        if self._state == SyncCadenceState.IDLE:
            self._state = SyncCadenceState.ACTIVE
            logger.info("SyncCadenceController: IDLE -> ACTIVE (drive_start)")

    def onDriveEnd(self) -> None:
        """
        Drive-end event handler.

        ACTIVE -> DRAINING (fires one final flush via the next
        :meth:`shouldSyncNow` call which always returns ``True`` in
        DRAINING).  No-op if IDLE (drive_end without a preceding
        drive_start is a callback ordering glitch).
        """
        if self._state == SyncCadenceState.ACTIVE:
            self._state = SyncCadenceState.DRAINING
            logger.info("SyncCadenceController: ACTIVE -> DRAINING (drive_end)")

    # -- decision API (polled by sync loop) -------------------------------

    def shouldSyncNow(self) -> bool:
        """
        Cadence-aware decision: is the sync loop due to fire?

        Returns:
            True when the cadence cooldown for the current state has
            elapsed, or when state is DRAINING (single final flush
            ignores cadence), or on the first call before any sync has
            been recorded.
        """
        if self._state == SyncCadenceState.DRAINING:
            return True
        if self._lastSyncAt is None:
            return True
        cadence = self._cadenceForState()
        return (self._now() - self._lastSyncAt) >= cadence

    def markSynced(self, *, hadRows: bool = False) -> None:
        """
        Record that a sync attempt just completed.

        Refreshes the cadence cooldown.  Applies the missed-drive-start
        fallback if state is IDLE and the sync returned rows (engine is
        likely running but drive_start callback never fired).  Resolves
        DRAINING -> IDLE because the single final flush is now done.

        Args:
            hadRows: ``True`` if the sync attempt pushed at least one
                row (the caller is expected to have this signal already
                from ``SyncClient``).  ``False`` for empty heartbeats.
        """
        timestamp = self._now()
        self._lastSyncAt = timestamp
        if hadRows:
            self._lastNonEmptySyncAt = timestamp

        if self._state == SyncCadenceState.DRAINING:
            self._state = SyncCadenceState.IDLE
            logger.info("SyncCadenceController: DRAINING -> IDLE (flush complete)")
        elif self._state == SyncCadenceState.IDLE and hadRows:
            # Missed drive_start fallback -- a non-empty heartbeat in IDLE
            # is a strong signal the engine is running.
            self._state = SyncCadenceState.ACTIVE
            logger.warning(
                "SyncCadenceController: IDLE -> ACTIVE (missed drive_start "
                "fallback; non-empty heartbeat sync)"
            )

    # -- internal ---------------------------------------------------------

    def _cadenceForState(self) -> float:
        if self._state == SyncCadenceState.ACTIVE:
            return self._activeSeconds
        # DRAINING is short-circuited in shouldSyncNow; only IDLE reaches here.
        return self._idleSeconds
