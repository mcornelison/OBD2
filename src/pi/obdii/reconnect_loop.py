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
# 2026-05-08    | Rex (US-301) | Spool 2026-05-08 BUG-1: add runReconnectHeartbeat
#               |              | for the PENDING-state retry path (10s cadence
#               |              | INFO heartbeat + per-tick connect attempt with
#               |              | 5s wall-clock cap + WARNING-level loud bail per
#               |              | V0.24.1 lesson).  Existing ReconnectLoop
#               |              | (post-disconnect-during-capture path) untouched.
# 2026-05-08    | Rex (V0.27.1)| Hotfix: Sprint 27 engine-on test #2 stacking-
#               |              | connect bug.  (1) HEARTBEAT_ATTEMPT_TIMEOUT_SEC
#               |              | 5.0 -> 30.0 to match the empirical K-line
#               |              | cold-protocol-detection envelope on the 1998
#               |              | 4G63 ECU (yesterday's working initial connect
#               |              | took 8s; 5s was below the working envelope).
#               |              | (2) Add inFlightProbeFn keyword to
#               |              | runReconnectHeartbeat: when the probe returns
#               |              | True, the tick logs outcome=already_in_flight
#               |              | and skips the connectFn spawn so the heartbeat
#               |              | does not stack concurrent connect() calls
#               |              | against the Sprint 25 leaked initial-obd-connect
#               |              | daemon.  Closes the "multiple access on port?"
#               |              | pyserial collision pattern that produced 0
#               |              | realtime_data rows in production today.
# 2026-05-11    | Rex (US-325) | I-025: exponential backoff in
#               |              | runReconnectHeartbeat.  Production journal
#               |              | showed _performConnect retrying at a fixed
#               |              | ~30-60s cadence FOREVER while the OBDLink was
#               |              | out of range -- thousands of /dev/rfcomm0
#               |              | touches a day -> on a Pi 5 the WiFi+BT combo
#               |              | chip starved WiFi (assoc dropped twice in 3h
#               |              | on 2026-05-11).  The inter-attempt sleep now
#               |              | grows: min(BASE * 2 ** min(consecutive_
#               |              | failures, BACKOFF_EXP_CAP), MAX_BACKOFF_SEC),
#               |              | BASE == the tickIntervalSec arg (10s in prod),
#               |              | BACKOFF_EXP_CAP == 5, MAX_BACKOFF_SEC == 900.
#               |              | The FIRST gap stays at BASE (V0.27.1 short-
#               |              | outage back-compat); the INFO heartbeat line
#               |              | gains consecutive_failures=N + next_attempt_
#               |              | in_seconds=X.  Counter resets implicitly: a
#               |              | successful connect ends the loop and the
#               |              | daemon is re-spawned fresh on the next
#               |              | dropout.  Fix #2 of the WiFi-drop debug --
#               |              | Fix #1 is the OS-side wifi.powersave=2
#               |              | NetworkManager drop-in (deploy/nm-disable-
#               |              | wifi-powersave.conf, installed by deploy-pi.sh).
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
    'BACKOFF_EXP_CAP',
    'DEFAULT_BACKOFF_SCHEDULE',
    'HEARTBEAT_ATTEMPT_TIMEOUT_SEC',
    'HEARTBEAT_LOG_PREFIX',
    'HEARTBEAT_TICK_INTERVAL_SEC',
    'MAX_BACKOFF_SEC',
    'ReconnectLoop',
    'runReconnectHeartbeat',
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

#: US-301 fixed cadence per CIO 2026-05-08 verbatim mandate ("10-second
#: heartbeat listening to see if the OBD Bluetooth is alive or shut off
#: and was restarted").
HEARTBEAT_TICK_INTERVAL_SEC: float = 10.0

#: V0.27.1: wall-clock cap on each per-tick connect attempt.  Raised from
#: the original US-301 5.0s after Sprint 27 engine-on test #2 evidence
#: showed the cap was below the empirical ISO 9141-2 K-line cold-protocol-
#: detection envelope on the 1998 4G63 ECU (ATZ + ATE0 + ATSP0 negotiation
#: routinely takes 6-10s; yesterday's working initial connect took 8s).
#: 30.0s aligns with ``_initializeConnection``'s budget so the heartbeat
#: gives a healthy connect a fair chance to complete.  Stacking concerns
#: are addressed by the new ``inFlightProbeFn`` parameter -- ticks that
#: fire while a prior connect is still in flight skip cleanly via that
#: probe rather than spawning competing daemons.
HEARTBEAT_ATTEMPT_TIMEOUT_SEC: float = 30.0

#: US-301 INFO log prefix.  Pinned as a constant so call sites + sprint_lint
#: + grep ("RECONNECT HEARTBEAT") all agree on the one canonical token.
HEARTBEAT_LOG_PREFIX: str = "RECONNECT HEARTBEAT"

#: US-325 / I-025: hard ceiling on the exponentially-backed-off inter-attempt
#: interval -- 900s == 15 minutes.  Once the heartbeat has been failing long
#: enough for ``BASE * 2 ** exponent`` to exceed this, it stops growing.
MAX_BACKOFF_SEC: float = 900.0

#: US-325 / I-025: clamp on the exponent in
#: ``min(BASE * 2 ** min(consecutive_failures, BACKOFF_EXP_CAP), MAX_BACKOFF_SEC)``.
#: With the production BASE (:data:`HEARTBEAT_TICK_INTERVAL_SEC` = 10s) this
#: caps the inter-attempt interval at ``10 * 2 ** 5 = 320s`` (~5.3 min) after
#: >= 5 consecutive failures -- a ~30x reduction in /dev/rfcomm0 churn versus
#: the pre-US-325 fixed cadence, without ever silently giving up.  Callers that
#: pass a larger BASE reach the :data:`MAX_BACKOFF_SEC` ceiling instead.
BACKOFF_EXP_CAP: int = 5


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


# ================================================================================
# US-301 -- PENDING-state heartbeat (Spool 2026-05-08 BUG-1)
# ================================================================================


def _attemptConnectWithCap(
    connectFn: Callable[[], bool],
    timeoutSec: float,
) -> tuple[str, BaseException | None]:
    """Run ``connectFn`` on a daemon thread bounded by ``timeoutSec``.

    Mirrors :meth:`LifecycleMixin._runInitialConnectWithTimeout` shape: dispatch
    on a background daemon thread, ``Event.wait(timeout=timeoutSec)``, classify
    the outcome.  Used per heartbeat tick to keep a single wedged BT pairing
    window from stalling the entire 10s cadence.

    On timeout the daemon thread is left running -- ``daemon=True`` reaps it
    at process exit; the caller has already moved on to the next tick.

    Args:
        connectFn: Zero-arg callable returning bool (True == adapter connected).
        timeoutSec: Wall-clock cap.

    Returns:
        ``(outcome, error)`` tuple.  ``outcome`` is one of
        ``"success"`` / ``"failure"`` / ``"error"`` / ``"timeout"``.  ``error``
        carries the original exception when ``outcome == "error"``.
    """
    doneEvent = threading.Event()
    result: dict[str, Any] = {'value': False, 'error': None}

    def _runInThread() -> None:
        try:
            result['value'] = bool(connectFn())
        except BaseException as exc:  # noqa: BLE001 -- classify, do not crash loop
            result['error'] = exc
        finally:
            doneEvent.set()

    worker = threading.Thread(
        target=_runInThread,
        daemon=True,
        name="heartbeat-connect-attempt",
    )
    worker.start()
    completed = doneEvent.wait(timeout=timeoutSec)

    if not completed:
        return ('timeout', None)
    if result['error'] is not None:
        return ('error', result['error'])
    if result['value']:
        return ('success', None)
    return ('failure', None)


def _nextAttemptInterval(consecutiveFailures: int, baseSec: float) -> float:
    """Exponential-backoff sleep before the next heartbeat connect attempt.

    US-325 / I-025 formula::

        min(baseSec * 2 ** min(consecutive_failures, BACKOFF_EXP_CAP), MAX_BACKOFF_SEC)

    ``consecutiveFailures`` is the count of consecutive failed attempts *so
    far* -- 0 for the first attempt of an outage, so the first inter-attempt
    gap equals ``baseSec`` and the V0.27.1 US-301 fixed cadence is preserved
    for short dropouts.

    Args:
        consecutiveFailures: Non-negative count of consecutive failed attempts.
            Values are clamped to ``[0, BACKOFF_EXP_CAP]`` for the exponent.
        baseSec: Base interval -- the ``tickIntervalSec`` argument of
            :func:`runReconnectHeartbeat` (10s in production).

    Returns:
        Sleep duration in seconds, never exceeding :data:`MAX_BACKOFF_SEC`.
    """
    exponent = min(max(consecutiveFailures, 0), BACKOFF_EXP_CAP)
    return min(baseSec * float(2 ** exponent), MAX_BACKOFF_SEC)


def runReconnectHeartbeat(
    connectFn: Callable[[], bool],
    isConnectedFn: Callable[[], bool],
    *,
    inFlightProbeFn: Callable[[], bool] | None = None,
    sleepFn: Callable[[float], None] | None = None,
    monotonicFn: Callable[[], float] | None = None,
    shutdownEvent: threading.Event | None = None,
    tickIntervalSec: float = HEARTBEAT_TICK_INTERVAL_SEC,
    attemptTimeoutSec: float = HEARTBEAT_ATTEMPT_TIMEOUT_SEC,
    maxTicks: int | None = None,
) -> int:
    """Drive a 10s-cadence reconnect heartbeat for the PENDING-state path.

    Spool 2026-05-08 BUG-1 evidence: across 11 hours of engine-off PENDING
    state, the production journal logged ZERO retry attempts.  The single
    ``initial-obd-connect`` daemon spawned by
    :meth:`LifecycleMixin._runInitialConnectWithTimeout` is the only thread
    trying; if it hangs in BT pairing it never recovers without a manual
    ``systemctl restart``.  CIO 2026-05-08 verbatim mandate:

        *"I do think it should have a heartbeat of every 10 seconds listening
        and looking to see if the OBD Bluetooth is alive or shut off and was
        restarted."*

    Each tick logs the canonical heartbeat at INFO::

        RECONNECT HEARTBEAT | ticks=N | last_attempt_seconds_ago=X | last_attempt_outcome=Y | consecutive_failures=K | next_attempt_in_seconds=Z

    Then dispatches a single ``connectFn()`` call bounded by
    ``attemptTimeoutSec`` (default 30s -- see :data:`HEARTBEAT_ATTEMPT_TIMEOUT_SEC`)
    on a daemon thread.  Loud-bail on every non-success outcome (WARNING level)
    per the V0.24.1 anti-pattern lesson: silent threads + no heartbeat + no
    canary = 9-drain saga.

    US-325 / I-025 -- exponential backoff: the sleep between ticks is
    ``min(tickIntervalSec * 2 ** min(consecutive_failures, BACKOFF_EXP_CAP),
    MAX_BACKOFF_SEC)`` (see :func:`_nextAttemptInterval`).  The FIRST failed
    tick still sleeps ``tickIntervalSec`` (short-outage back-compat); each
    subsequent consecutive failure doubles the interval, up to ``2 ** 5`` x
    base then flat (production: 10 -> 20 -> 40 -> 80 -> 160 -> 320s; never the
    900s ceiling at the 10s base, but a caller passing a larger base reaches
    it).  An ``already_in_flight`` skip is NOT counted as a failure -- the
    counter holds and the cadence stays at the current level.  The counter has
    no explicit reset: a successful connect ends the loop, and the lifecycle
    daemon is re-spawned fresh on the next dropout, so the next outage starts
    at the base interval again (no permanent slowdown).  Motivation: the
    production journal showed ``_performConnect`` retrying at a fixed ~30-60s
    cadence indefinitely while the OBDLink was out of range, and on a Pi 5 the
    continuous BT activity starved the shared WiFi+BT radio.

    Loop exit conditions (any one terminates):

    * ``isConnectedFn()`` returns True (a parallel restoration won the race --
      e.g., the original ``initial-obd-connect`` thread completed).
    * ``connectFn()`` returns True (this tick reconnected the adapter).
    * ``shutdownEvent.is_set()`` -- SIGTERM observed via the orchestrator's
      shared event.
    * ``maxTicks`` reached -- safety net for tests; production passes None.

    Args:
        connectFn: Zero-arg callable that attempts a single connect.  Returns
            True on success, False on failure, may raise on transport error.
            The function is invoked on a worker daemon thread bounded by
            ``attemptTimeoutSec``.
        isConnectedFn: Zero-arg callable returning True when the adapter is
            already connected (e.g., by a parallel thread).  Checked at the
            top of each tick before any side-effect.  Required so the loop
            does not double-attempt against an already-up connection.
        inFlightProbeFn: V0.27.1 optional zero-arg callable returning True
            when another thread is currently inside ``connect()``.  Wires to
            :meth:`ObdConnection.isConnectInFlight` in production so the
            heartbeat does not stack a new connect daemon on top of the
            Sprint 25 leaked ``initial-obd-connect`` daemon (which produced
            "multiple access on port?" pyserial collisions in the engine-on
            test of 2026-05-08).  When the probe returns True, the tick
            logs ``last_attempt_outcome=already_in_flight`` and skips the
            connect spawn -- ``ticks`` increments and ``sleepFn`` is invoked
            for cadence preservation (at the current backoff level), but
            ``connectFn`` is not called and the consecutive-failure counter is
            left unchanged.  When ``None`` (the legacy / pre-V0.27.1 callsites),
            the loop behaves identically to its original US-301 form aside from
            the US-325 backoff.
        sleepFn: Injectable sleep used between ticks.  Defaults to
            :func:`time.sleep`.  Tests pass a :class:`FakeClock`-style fn
            that advances simulated time.
        monotonicFn: Injectable monotonic clock for the ``last_attempt_seconds_ago``
            field.  Defaults to :func:`time.monotonic`.
        shutdownEvent: Optional :class:`threading.Event`; when set, loop exits
            at the next tick boundary.  Wires into orchestrator SIGTERM.
        tickIntervalSec: BASE interval for the US-325 exponential backoff (the
            first failed-tick sleep, and the unit doubled on each subsequent
            consecutive failure).  Defaults to
            :data:`HEARTBEAT_TICK_INTERVAL_SEC` (10s).
        attemptTimeoutSec: Wall-clock cap on each connect attempt.  Defaults
            to :data:`HEARTBEAT_ATTEMPT_TIMEOUT_SEC` (30s).
        maxTicks: Test-only safety net.  Production passes None (run forever).

    Returns:
        Total tick count executed.  Return is informational; call sites that
        spawn this on a daemon thread typically discard it.
    """
    sleepImpl = sleepFn if sleepFn is not None else time.sleep
    monoImpl = monotonicFn if monotonicFn is not None else time.monotonic

    ticks = 0
    lastAttemptAt: float | None = None
    lastAttemptOutcome: str = "never"
    # US-325 / I-025: count of consecutive failed connect attempts.  Drives
    # the exponential backoff via _nextAttemptInterval(); incremented on a
    # failed attempt, NOT on an already_in_flight skip.  A successful connect
    # ends the loop (so no explicit reset is needed -- a re-spawned heartbeat
    # starts a fresh counter on the next dropout).
    consecutiveFailures = 0

    while True:
        if shutdownEvent is not None and shutdownEvent.is_set():
            logger.info(
                "%s | ticks=%d | shutdown observed -- exiting",
                HEARTBEAT_LOG_PREFIX, ticks,
            )
            return ticks
        if isConnectedFn():
            logger.info(
                "%s | ticks=%d | adapter already connected (parallel restore) -- exiting",
                HEARTBEAT_LOG_PREFIX, ticks,
            )
            return ticks
        if maxTicks is not None and ticks >= maxTicks:
            return ticks

        if lastAttemptAt is None:
            secondsAgoStr = "n/a"
        else:
            secondsAgoStr = f"{monoImpl() - lastAttemptAt:.1f}"

        # The sleep that will follow this tick on any non-success outcome,
        # computed from the failure count BEFORE this tick -- so the first
        # failed tick sleeps the base interval (V0.27.1 short-outage
        # back-compat) and the heartbeat line below advertises the same value
        # in next_attempt_in_seconds.
        backoffSec = _nextAttemptInterval(consecutiveFailures, tickIntervalSec)

        # V0.27.1: skip the spawn when another thread is currently inside
        # connect().  The Sprint 25 leaked initial-obd-connect daemon owns
        # the connect() call after an _initializeConnection timeout; the
        # heartbeat must observe + log + skip rather than spawn a competing
        # daemon that collides on /dev/rfcomm0.  ticks increments so
        # cadence + journal continuity are preserved; lastAttemptAt and
        # consecutiveFailures are left unchanged (an in-flight skip is not a
        # failure -- the backoff level holds, it does not advance).
        if inFlightProbeFn is not None and inFlightProbeFn():
            lastAttemptOutcome = "already_in_flight"
            logger.info(
                "%s | ticks=%d | last_attempt_seconds_ago=%s | last_attempt_outcome=already_in_flight "
                "| consecutive_failures=%d | next_attempt_in_seconds=%.1f",
                HEARTBEAT_LOG_PREFIX,
                ticks + 1,
                secondsAgoStr,
                consecutiveFailures,
                backoffSec,
            )
            ticks += 1
            sleepImpl(backoffSec)
            continue

        logger.info(
            "%s | ticks=%d | last_attempt_seconds_ago=%s | last_attempt_outcome=%s "
            "| consecutive_failures=%d | next_attempt_in_seconds=%.1f",
            HEARTBEAT_LOG_PREFIX,
            ticks + 1,
            secondsAgoStr,
            lastAttemptOutcome,
            consecutiveFailures,
            backoffSec,
        )

        outcome, error = _attemptConnectWithCap(connectFn, attemptTimeoutSec)
        lastAttemptAt = monoImpl()
        lastAttemptOutcome = outcome
        ticks += 1

        if outcome == 'success':
            logger.info(
                "Reconnect heartbeat: adapter connected on tick %d", ticks,
            )
            return ticks

        # Loud-bail per V0.24.1 lesson -- every non-success path is WARNING.
        # "next attempt in" reflects the US-325 exponential backoff, not a
        # fixed cadence.
        if outcome == 'failure':
            logger.warning(
                "Reconnect heartbeat tick %d: connectFn returned False "
                "(adapter not yet ready); next attempt in %.1fs",
                ticks, backoffSec,
            )
        elif outcome == 'error':
            logger.warning(
                "Reconnect heartbeat tick %d: connectFn raised %r; "
                "next attempt in %.1fs",
                ticks, error, backoffSec,
            )
        elif outcome == 'timeout':
            logger.warning(
                "Reconnect heartbeat tick %d: connectFn exceeded %.1fs "
                "wall-clock cap; next attempt in %.1fs",
                ticks, attemptTimeoutSec, backoffSec,
            )

        consecutiveFailures += 1
        sleepImpl(backoffSec)
