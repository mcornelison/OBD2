################################################################################
# File Name: reconnect_loop.py
# Purpose/Description: BT-resilient reconnect-wait loop for US-211.
#                      Accepts injectable probe + event logger + sleep, so
#                      the orchestrator can host the loop synchronously and
#                      unit tests can drive it deterministically.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-211) | Initial -- Spool Session 6 amended Story 2.
# 2026-04-23    | Rex (US-232) | TD-035 close: add shutdownEvent seam so
#               |              | signal-handler set() wakes the backoff
#               |              | sleep + aborts the loop within ~ms
#               |              | instead of waiting out the 60s cap.
# ================================================================================
################################################################################

"""Reconnect-wait loop with backoff capped at 60 seconds.

Spool Session 6 grounding (verbatim): *"Backoff schedule: 1s, 5s, 10s,
30s, 60s, 60s... (cap at 60s)"*. The loop polls an adapter-reachability
probe until it returns True, then yields control back to the caller to
reopen the OBD connection. Per-iteration rows land in
``connection_log`` via the injected event logger so a post-hoc review
reads as a flap timeline rather than a silent gap.

Invariants (Spool amended Story 2):

* Process NEVER exits from inside the loop. Only FATAL exceptions raised
  by the caller escape.
* Backoff caps at 60s; no exponential blow-up.
* Probe is lightweight -- do NOT pass a full python-obd OBD() factory;
  use :func:`src.pi.obdii.bluetooth_helper.isRfcommReachable` or an
  equivalent stat/AT-probe function.
* The loop itself does not touch the python-obd connection -- caller owns
  teardown before entering and reopen after exit.

Example::

    from src.pi.obdii.reconnect_loop import ReconnectLoop
    from src.pi.obdii.bluetooth_helper import isRfcommReachable
    from src.pi.data.connection_logger import logConnectionEvent

    loop = ReconnectLoop(
        probe=lambda: isRfcommReachable(device=0),
        eventLogger=lambda eventType, retryCount: logConnectionEvent(
            database=db, eventType=eventType, retryCount=retryCount,
        ),
    )
    loop.waitForAdapter()  # Blocks until probe returns True.
    # Caller now reopens python-obd and resumes capture.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

__all__ = [
    'BACKOFF_CAP_SECONDS',
    'DEFAULT_BACKOFF_SCHEDULE',
    'ReconnectLoop',
]

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

#: Hard cap on the per-iteration sleep -- never exceed 60 seconds.
BACKOFF_CAP_SECONDS: int = 60

#: Backoff schedule per Spool Session 6 grounding. After the explicit
#: prefix, the loop reuses :data:`BACKOFF_CAP_SECONDS` indefinitely.
#: The tuple captures the "initial ramp" -- runtime concatenates 60s tail
#: by clamping any index past the end to the cap.
DEFAULT_BACKOFF_SCHEDULE: tuple[int, ...] = (1, 5, 10, 30, 60)


# ================================================================================
# Loop
# ================================================================================

class ReconnectLoop:
    """Reconnect-wait loop with capped backoff.

    The loop is intentionally stateful (not a generator) so the caller
    can ``reset()`` it after a successful reconnect without recreating
    the instance or losing the injected callbacks.

    Args:
        probe: Zero-arg callable returning True when the adapter is
            reachable. Typically
            :func:`src.pi.obdii.bluetooth_helper.isRfcommReachable`
            bound with the desired rfcomm device number. May raise --
            the loop logs and treats any exception as "not reachable".
        eventLogger: Two-arg callable ``(eventType: str, retryCount: int)``
            that writes one ``connection_log`` row. None to suppress
            logging (useful in unit tests).
        sleepFn: Injectable sleep function. Defaults to :func:`time.sleep`.
            Tests replace it to run deterministically in ~0 wall-clock.
        schedule: Backoff schedule prefix. Defaults to
            :data:`DEFAULT_BACKOFF_SCHEDULE`. The last value repeats
            once exhausted; any value above :data:`BACKOFF_CAP_SECONDS`
            is clamped to the cap.
        shouldExitFn: Optional zero-arg callable returning True to abort
            the loop early (systemd stop / shutdown signal). Checked on
            every iteration before the probe and again before the sleep.
        shutdownEvent: Optional :class:`threading.Event` that, when set,
            aborts the loop the same way ``shouldExitFn`` does *and*
            wakes any in-progress backoff sleep immediately (US-232 /
            TD-035). Main-thread signal handlers install SIGTERM/SIGINT
            handlers that ``set()`` the event; worker-thread sleeps
            observe the wake through ``event.wait(timeout=backoff)``.
            Without this, a ``time.sleep(60)`` would block SIGTERM
            observation until the sleep expired and systemd would
            escalate to SIGKILL after TimeoutStopSec.
    """

    def __init__(
        self,
        probe: Callable[[], bool],
        eventLogger: Callable[[str, int], None] | None = None,
        sleepFn: Callable[[float], None] | None = None,
        schedule: tuple[int, ...] = DEFAULT_BACKOFF_SCHEDULE,
        shouldExitFn: Callable[[], bool] | None = None,
        shutdownEvent: threading.Event | None = None,
    ) -> None:
        self._probe = probe
        self._eventLogger = eventLogger
        # US-232 / TD-035: when shutdownEvent is provided, the default sleep
        # becomes event.wait() so a set() from the signal handler wakes us
        # immediately. When no event is provided, behavior is unchanged
        # (legacy time.sleep path).
        self._shutdownEvent = shutdownEvent
        if sleepFn is not None:
            self._sleepFn = sleepFn
        elif shutdownEvent is not None:
            self._sleepFn = self._eventAwareSleep
        else:
            self._sleepFn = time.sleep
        self._schedule = schedule
        self._shouldExitFn = shouldExitFn
        self._iteration = 0

    def _eventAwareSleep(self, seconds: float) -> None:
        """Sleep that wakes early when ``shutdownEvent`` is set.

        ``threading.Event.wait`` returns immediately once the event has
        been set; normal timeout expiry returns False. Either return
        value is fine here -- the subsequent ``_shouldExit()`` check is
        what actually aborts the loop. Using the event as the sleep
        primitive just means we notice the shutdown at most a few ms
        after the signal handler fires, not after the 60s backoff cap.
        """
        if self._shutdownEvent is None:
            time.sleep(seconds)
            return
        self._shutdownEvent.wait(timeout=seconds)

    def reset(self) -> None:
        """Reset backoff to the start of the schedule.

        Call after a successful reconnect so the next BT flap starts at
        1s, not at the cap. Does not touch the probe or event logger.
        """
        self._iteration = 0

    def getCurrentDelay(self) -> int:
        """Return the sleep duration for the *next* iteration.

        Exposed for observability/tests. After ``getCurrentDelay()`` the
        internal iteration counter is unchanged; ``waitForAdapter()``
        drives the counter forward.
        """
        return self._delayAt(self._iteration)

    def _delayAt(self, iteration: int) -> int:
        """Compute the schedule entry for a given iteration index.

        Args:
            iteration: Zero-based iteration number.

        Returns:
            Sleep duration in seconds, clamped to :data:`BACKOFF_CAP_SECONDS`.
        """
        if iteration < 0:
            iteration = 0
        if iteration < len(self._schedule):
            value = self._schedule[iteration]
        else:
            value = self._schedule[-1] if self._schedule else BACKOFF_CAP_SECONDS
        return min(value, BACKOFF_CAP_SECONDS)

    def waitForAdapter(self, maxIterations: int | None = None) -> bool:
        """Block until the probe returns True (adapter reachable) or abort.

        On each iteration the loop:

        1. Checks ``shouldExitFn`` (if provided) and returns False if set.
        2. Logs an ``adapter_wait`` event with the current retryCount.
        3. Sleeps for the scheduled backoff duration.
        4. Logs a ``reconnect_attempt`` event and fires the probe.
        5. If the probe returns True, logs ``reconnect_success``, resets
           the backoff, and returns True.
        6. Otherwise increments the iteration counter and repeats.

        Args:
            maxIterations: Safety net for tests. None means run forever
                (production). Production callers rely on
                :attr:`_shouldExitFn` for early exit.

        Returns:
            True if the probe succeeded and capture should resume.
            False if the loop aborted via ``shouldExitFn`` or hit
            ``maxIterations``.
        """
        # Local import to keep reconnect_loop.py dependency-free at
        # module load time (connection_logger pulls in src.common.time).
        from src.pi.data.connection_logger import (
            EVENT_ADAPTER_WAIT,
            EVENT_RECONNECT_ATTEMPT,
            EVENT_RECONNECT_SUCCESS,
        )

        iterationsRun = 0
        while True:
            if self._shouldExit():
                logger.info(
                    "Reconnect loop exiting early | iteration=%d", self._iteration
                )
                return False

            delay = self._delayAt(self._iteration)
            retryCount = self._iteration + 1

            self._emit(EVENT_ADAPTER_WAIT, retryCount)
            logger.info(
                "Adapter unreachable -- waiting %ds before probe %d",
                delay,
                retryCount,
            )
            self._sleepFn(float(delay))

            if self._shouldExit():
                return False

            self._emit(EVENT_RECONNECT_ATTEMPT, retryCount)
            reachable = self._safeProbe()
            if reachable:
                self._emit(EVENT_RECONNECT_SUCCESS, retryCount)
                logger.info(
                    "Adapter reachable after %d probe(s) | resuming capture",
                    retryCount,
                )
                self.reset()
                return True

            self._iteration += 1
            iterationsRun += 1
            if maxIterations is not None and iterationsRun >= maxIterations:
                logger.warning(
                    "Reconnect loop hit maxIterations=%d without success",
                    maxIterations,
                )
                return False

    # --------------------------------------------------------------------------
    # Internals
    # --------------------------------------------------------------------------

    def _shouldExit(self) -> bool:
        # US-232 / TD-035: shutdownEvent takes precedence over shouldExitFn
        # so SIGTERM responsiveness never depends on the optional callback.
        if self._shutdownEvent is not None and self._shutdownEvent.is_set():
            return True
        if self._shouldExitFn is None:
            return False
        try:
            return bool(self._shouldExitFn())
        except Exception as exc:  # noqa: BLE001
            logger.debug("shouldExitFn raised %s -- treating as False", exc)
            return False

    def _safeProbe(self) -> bool:
        """Run the probe, swallowing exceptions as 'not reachable'."""
        try:
            return bool(self._probe())
        except Exception as exc:  # noqa: BLE001
            logger.debug("Probe raised %s -- treating as not reachable", exc)
            return False

    def _emit(self, eventType: str, retryCount: int) -> None:
        if self._eventLogger is None:
            return
        try:
            self._eventLogger(eventType, retryCount)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Event logger raised %s for %s", exc, eventType)


def buildDefaultReconnectLoop(
    database: Any,
    macAddress: str | None = None,
    rfcommDevice: int = 0,
    sleepFn: Callable[[float], None] | None = None,
    shouldExitFn: Callable[[], bool] | None = None,
    shutdownEvent: threading.Event | None = None,
) -> ReconnectLoop:
    """Assemble a :class:`ReconnectLoop` with production defaults.

    Args:
        database: ``ObdDatabase``-shaped object for event logging. None
            suppresses logging.
        macAddress: Adapter MAC recorded on each logged row for cross-
            reference against connect events.
        rfcommDevice: /dev/rfcommN device number. Default 0 (OBDLink LX).
        sleepFn: Injectable sleep; defaults to :func:`time.sleep`.
        shouldExitFn: Optional abort predicate.
        shutdownEvent: Optional :class:`threading.Event` that aborts the
            loop and wakes the backoff sleep (US-232 / TD-035).

    Returns:
        Configured :class:`ReconnectLoop` ready to call.
    """
    from src.pi.data.connection_logger import logConnectionEvent
    from src.pi.obdii.bluetooth_helper import isRfcommReachable

    def probe() -> bool:
        return isRfcommReachable(device=rfcommDevice)

    def eventLogger(eventType: str, retryCount: int) -> None:
        logConnectionEvent(
            database=database,
            eventType=eventType,
            macAddress=macAddress,
            success=(eventType == 'reconnect_success'),
            retryCount=retryCount,
        )

    return ReconnectLoop(
        probe=probe,
        eventLogger=eventLogger,
        sleepFn=sleepFn,
        shouldExitFn=shouldExitFn,
        shutdownEvent=shutdownEvent,
    )
