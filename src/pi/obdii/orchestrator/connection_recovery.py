################################################################################
# File Name: connection_recovery.py
# Purpose/Description: OBD connection recovery with exponential backoff mixin
# Author: Ralph Agent
# Creation Date: 2026-04-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-14    | Ralph Agent  | Sweep 5 Task 2: extracted from orchestrator.py
#               |              | (exponential backoff preserved byte-for-byte)
# 2026-05-13    | Rex (US-338) | I-033: _handleReconnectionFailure was a silent
#               |              | dead-end after the bounded [1,2,4,8,16]s x 5-
#               |              | attempt budget exhausted -- nothing tried
#               |              | connect() again until process restart, so the
#               |              | post-pharmacy-stop engine-on of drive 12
#               |              | (2026-05-13 19:10:24Z drive_end) never minted
#               |              | drive 13.  Failure handler now spawns a daemon
#               |              | thread running runReconnectHeartbeat (the
#               |              | US-301 / V0.27.1 / US-325 heartbeat) which
#               |              | retries forever with exponential backoff up to
#               |              | 15-min ceiling.  When the adapter returns, the
#               |              | heartbeat connect() succeeds and the main
#               |              | runLoop's _checkConnectionStatus() detects the
#               |              | False->True transition naturally, firing
#               |              | _handleConnectionRestored() + the US-302 data
#               |              | logger restart.  Idempotent: re-firing the
#               |              | handler while a heartbeat is alive is a no-op.
# 2026-09-14    | Rex (US-690) | One retry authority.  (1) _attemptReconnection
#               |              | makes ONE port attempt (reconnectOnce) -- it used
#               |              | to call reconnect() -> connect(), a 6-attempt
#               |              | loop, so "attempt 1/5" was up to 6 attempts with
#               |              | a backoff of their own and the 5-attempt ceiling
#               |              | was really 30.  (2) At most one retry loop is
#               |              | live: _startReconnection and the post-failure
#               |              | spawn both stand down while another retry thread
#               |              | is alive.  (3) The post-failure heartbeat is
#               |              | wired with cancelFn so its cap cancels.
# 2026-09-14    | Rex (US-751) | requestObdLinkWake(): the one entry point that
#               |              | cuts a heartbeat backoff short.  The post-failure
#               |              | heartbeat is wired with the orchestrator's
#               |              | _obdWakeEvent.
# ================================================================================
################################################################################

"""
Connection recovery mixin for ApplicationOrchestrator.

Runs automatic reconnection in a background thread using exponential
backoff, pauses and resumes data logging around reconnection, and emits
success/failure events. Preserves the byte-for-byte behavior from TD-003.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..reconnect_loop import runReconnectHeartbeat
from .types import HealthCheckStats, ShutdownState

# Unified logger name matches the original monolith module so existing tests
# that filter caplog by logger name continue to work unchanged.
logger = logging.getLogger("pi.obdii.orchestrator")


class ConnectionRecoveryMixin:
    """
    Mixin providing connection recovery with exponential backoff.

    Assumes the composing class has:
        _connection: Any | None
        _dataLogger: Any | None
        _displayManager: Any | None
        _isReconnecting: bool
        _reconnectAttempt: int
        _maxReconnectAttempts: int
        _reconnectDelays: list[int]
        _reconnectThread: threading.Thread | None
        _dataLoggerPausedForReconnect: bool
        _alertsPausedForReconnect: bool
        _shutdownState: ShutdownState
        _healthCheckStats: HealthCheckStats
        _onConnectionRestored: Callable | None
    """

    _connection: Any | None
    _dataLogger: Any | None
    _displayManager: Any | None
    _isReconnecting: bool
    _reconnectAttempt: int
    _maxReconnectAttempts: int
    _reconnectDelays: list[int]
    _reconnectThread: threading.Thread | None
    _dataLoggerPausedForReconnect: bool
    _alertsPausedForReconnect: bool
    _shutdownState: ShutdownState
    _healthCheckStats: HealthCheckStats
    _onConnectionRestored: Callable[[], None] | None
    _lastConnectionCheckTime: datetime | None
    # US-338 / I-033: post-failure long-lived heartbeat (lazy-initialized
    # on the first failure; tracked here so the spawn is idempotent and
    # subsequent failure-handler invocations skip re-spawning while the
    # thread is still alive).
    _postFailureReconnectHeartbeatThread: threading.Thread | None

    def _checkConnectionStatus(self) -> bool:
        """
        Check if OBD connection is currently connected.

        Returns:
            True if connected, False otherwise
        """
        if self._connection is None:
            return False

        try:
            if hasattr(self._connection, 'isConnected'):
                return self._connection.isConnected()
            return False
        except Exception:
            return False

    def _startReconnection(self) -> None:
        """
        Start the reconnection process in a background thread.

        Called when connection loss is detected. Initiates automatic reconnection
        with exponential backoff delays.
        """
        if self._isReconnecting:
            logger.debug("Reconnection already in progress")
            return

        if self._connection is None:
            logger.warning("Cannot reconnect - no connection object available")
            return

        # US-690: a heartbeat that is still alive already owns the retry.  A
        # second loop beside it is the two-authorities defect -- each with its
        # own counter and backoff, interleaving attempts on one port.
        liveAuthority = self._liveRetryAuthorityName()
        if liveAuthority is not None:
            logger.info(
                "Connection recovery not started -- retry authority %r is "
                "already live and owns the reconnect (US-690)",
                liveAuthority,
            )
            return

        self._isReconnecting = True
        self._reconnectAttempt = 0

        # Pause data logging and alerts during reconnection
        self._pauseDataLogging()
        self._alertsPausedForReconnect = True

        # Start reconnection in background thread
        self._reconnectThread = threading.Thread(
            target=self._reconnectionLoop,
            daemon=True,
            name="connection-recovery"
        )
        self._reconnectThread.start()
        logger.info("Connection recovery started")

    def _reconnectionLoop(self) -> None:
        """
        Reconnection loop with exponential backoff.

        Attempts to reconnect to the OBD-II dongle using the configured
        retry delays. Runs in a background thread.
        """
        while (
            self._isReconnecting
            and self._reconnectAttempt < self._maxReconnectAttempts
            and self._shutdownState == ShutdownState.RUNNING
        ):
            self._reconnectAttempt += 1

            # Get delay for this attempt
            if self._reconnectDelays:
                delayIndex = min(
                    self._reconnectAttempt - 1,
                    len(self._reconnectDelays) - 1
                )
                delay = self._reconnectDelays[delayIndex]
            else:
                delay = 0

            logger.info(
                f"Reconnection attempt {self._reconnectAttempt}/{self._maxReconnectAttempts} "
                f"in {delay}s..."
            )

            # Wait before attempting reconnection
            if delay > 0:
                # Use small sleep increments to allow for shutdown during wait
                for _ in range(int(delay * 10)):
                    if (
                        self._shutdownState != ShutdownState.RUNNING
                        or not self._isReconnecting
                    ):
                        logger.debug("Reconnection cancelled during backoff wait")
                        return
                    time.sleep(0.1)

            # Attempt reconnection
            try:
                if self._attemptReconnection():
                    self._handleReconnectionSuccess()
                    return
            except Exception as e:
                logger.warning(f"Reconnection attempt failed: {e}")

        # Max retries exceeded
        if self._reconnectAttempt >= self._maxReconnectAttempts:
            self._handleReconnectionFailure()

    def _attemptReconnection(self) -> bool:
        """
        Attempt a single reconnection to the OBD-II dongle.

        US-690: "single" is now literal.  ``reconnectOnce()`` resets the
        transport and makes ONE port attempt, so :meth:`_reconnectionLoop` is
        the only thing counting and the only thing backing off.  ``reconnect()``
        ends in ``connect()``, a retry loop of its own; it remains only as the
        fallback for duck-typed connections (the simulator) that lack the seam.

        Returns:
            True if reconnection successful, False otherwise
        """
        if self._connection is None:
            return False

        try:
            reconnectOnce = getattr(self._connection, 'reconnectOnce', None)
            if reconnectOnce is not None:
                return bool(reconnectOnce())

            # Fallback: connections without the single-attempt seam
            if hasattr(self._connection, 'reconnect'):
                return self._connection.reconnect()

            # Fall back to disconnect + connect pattern
            if hasattr(self._connection, 'disconnect'):
                self._connection.disconnect()

            if hasattr(self._connection, 'connect'):
                return self._connection.connect()

            return False

        except Exception as e:
            logger.debug(f"Reconnection attempt error: {e}")
            return False

    def _handleReconnectionSuccess(self) -> None:
        """
        Handle successful reconnection.

        Resumes data logging and updates connection state.
        """
        logger.info(
            f"Connection recovered successfully after "
            f"{self._reconnectAttempt} attempt(s)"
        )

        self._isReconnecting = False
        self._reconnectAttempt = 0

        # Update connection status
        self._healthCheckStats.connectionStatus = "connected"
        self._healthCheckStats.connectionConnected = True

        # Resume data logging and alerts
        self._resumeDataLogging()
        self._alertsPausedForReconnect = False

        # Update display
        if self._displayManager is not None:
            try:
                if hasattr(self._displayManager, 'showConnectionStatus'):
                    self._displayManager.showConnectionStatus('Connected')
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # Call external callback
        if self._onConnectionRestored is not None:
            try:
                self._onConnectionRestored()
            except Exception as e:
                logger.warning(f"onConnectionRestored callback error: {e}")

    def _handleReconnectionFailure(self) -> None:
        """
        Handle reconnection failure after max retries exceeded.

        Logs the error but allows the system to continue running.
        Data logging remains paused since connection is unavailable.

        US-338 / I-033 (2026-05-13): after the synchronous failure
        bookkeeping, spawn a long-lived daemon thread running
        :func:`runReconnectHeartbeat` so a returning adapter (engine-on
        for the next leg of a multi-leg trip) is eventually caught.
        Pre-fix, this method was a silent dead-end -- nothing in the
        process re-attempted ``connect()`` until restart.
        """
        logger.error(
            f"Connection recovery failed after {self._maxReconnectAttempts} attempts. "
            f"System will continue running without OBD connection."
        )

        self._isReconnecting = False

        # Update connection status
        self._healthCheckStats.connectionStatus = "disconnected"
        self._healthCheckStats.connectionConnected = False
        self._healthCheckStats.totalErrors += 1

        # Update display to show connection failed state
        if self._displayManager is not None:
            try:
                if hasattr(self._displayManager, 'showConnectionStatus'):
                    self._displayManager.showConnectionStatus('Connection Failed')
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # US-338 / I-033: spawn post-failure heartbeat so a returning
        # adapter is eventually re-connected without process restart.
        # Idempotent -- spawn is skipped when an earlier thread is alive.
        self._spawnPostFailureReconnectHeartbeat()

        # Note: Data logging remains paused since connection is unavailable.
        # When the post-failure heartbeat eventually re-connects the
        # adapter, the main runLoop's _checkConnectionStatus() picks up
        # the False->True transition and fires _handleConnectionRestored,
        # which in turn (via US-302) re-starts the data logger.

    def _spawnPostFailureReconnectHeartbeat(self) -> None:
        """Spawn a daemon thread that runs :func:`runReconnectHeartbeat`.

        US-338 / I-033.  Bridges the gap between the bounded
        :meth:`_reconnectionLoop` (5 attempts then give up) and the main
        :meth:`runLoop`'s state-transition detector.  The heartbeat keeps
        invoking the connection's ``connect()`` with exponential backoff
        up to :data:`reconnect_loop.MAX_BACKOFF_SEC` (15 min); when an
        attempt succeeds, the heartbeat exits and the main loop's next
        :meth:`_checkConnectionStatus` pass returns True, firing
        :meth:`_handleConnectionRestored` (which re-starts the data
        logger per US-302).

        Idempotent: if a heartbeat thread spawned by a previous failure
        is still alive, this is a no-op so the failure handler can be
        re-entered without thread churn or competing connect attempts.

        Requires the composing class to have a non-None ``self._connection``
        with at least ``connect()`` and ``isConnected()`` methods.  Optional
        seams: ``isConnectInFlight()`` (wired as ``inFlightProbeFn`` so the
        heartbeat skips when another thread holds the V0.27.1 connect lock)
        and ``self._shutdownEvent`` (a :class:`threading.Event` that aborts
        the heartbeat at SIGTERM).
        """
        # Idempotency guard -- never let the failure handler fire two
        # heartbeats at once.  A second heartbeat would race the first
        # against the connection's _connectLock and produce
        # already_in_flight skip-storms in the journal.
        existing = getattr(self, '_postFailureReconnectHeartbeatThread', None)
        if existing is not None and existing.is_alive():
            logger.debug(
                "US-338 post-failure reconnect heartbeat already alive; "
                "skipping spawn"
            )
            return

        # US-690: nor may it start beside a DIFFERENT live retry thread.
        liveAuthority = self._liveRetryAuthorityName()
        if liveAuthority is not None:
            logger.info(
                "US-338 post-failure reconnect heartbeat not spawned -- retry "
                "authority %r is already live (US-690)",
                liveAuthority,
            )
            return

        if self._connection is None:
            logger.debug(
                "US-338 post-failure reconnect heartbeat: no _connection; "
                "skipping spawn"
            )
            return

        # US-673: one attempt per tick, not a six-attempt burst.  `connect()`
        # is itself a retry loop, so every heartbeat tick that called it spent
        # 31s doing six rfcomm binds -- multiplying this heartbeat's ceilinged
        # idle cadence by 6.  `connectOnce` hands the cadence back to the
        # heartbeat, which is where US-325 / I-025 put it.  Duck-typed
        # connections without the seam fall back to `connect()` unchanged.
        connectFn = getattr(self._connection, 'connectOnce', None)
        if connectFn is None:
            connectFn = getattr(self._connection, 'connect', None)
        isConnectedFn = getattr(self._connection, 'isConnected', None)
        if connectFn is None or isConnectedFn is None:
            logger.debug(
                "US-338 post-failure reconnect heartbeat: _connection "
                "lacks connect/isConnected; skipping spawn"
            )
            return

        inFlightProbeFn = getattr(self._connection, 'isConnectInFlight', None)
        # US-690: the per-tick cap cancels what it abandons.
        cancelFn = getattr(self._connection, 'cancelPendingConnects', None)
        shutdownEvent = getattr(self, '_shutdownEvent', None)
        # US-751: a wake cuts this heartbeat's backoff short.
        wakeEvent = getattr(self, '_obdWakeEvent', None)

        def _runHeartbeat() -> None:
            try:
                runReconnectHeartbeat(
                    connectFn=connectFn,
                    isConnectedFn=isConnectedFn,
                    inFlightProbeFn=inFlightProbeFn,
                    cancelFn=cancelFn,
                    shutdownEvent=shutdownEvent,
                    wakeEvent=wakeEvent,
                )
            except Exception:  # noqa: BLE001 -- daemon must not crash silently
                logger.exception(
                    "US-338 post-failure reconnect heartbeat crashed; "
                    "adapter will not be retried until process restart"
                )

        thread = threading.Thread(
            target=_runHeartbeat,
            daemon=True,
            name="us338-post-failure-reconnect-heartbeat",
        )
        thread.start()
        self._postFailureReconnectHeartbeatThread = thread
        logger.warning(
            "US-338: spawned post-failure reconnect heartbeat (adapter "
            "will be retried with exponential backoff up to 15 min "
            "ceiling until reachable)"
        )

    def requestObdLinkWake(self, reason: str) -> None:
        """Tell the live reconnect heartbeat the car may have just woken (US-751).

        The key-on delay measured on 2026-09-14 was backoff latency: the Pi was
        retrying all night, sitting at the 320 s ceiling, and a key-on waited
        out whatever was left of it.  A wake cuts that sleep short and restarts
        the ladder at the base interval, so wake -> next attempt is bounded by
        at most one in-flight attempt.

        This is a SEAM, deliberately not wired to a physical signal: which
        signal means "key-on" on this install is an open question (see the
        US-751 blocker).  It never touches the port -- the heartbeat's next
        attempt goes through the connection's single ``_ioLock`` owner as
        always, so no second serial owner exists (A-17).  With no heartbeat
        alive it is a harmless no-op beyond the log line: the flag is cleared
        by the next heartbeat's first tick, which attempts immediately anyway.

        Args:
            reason: Short label for the journal, e.g. ``"power_restored"``.
        """
        wakeEvent = getattr(self, '_obdWakeEvent', None)
        if wakeEvent is None:
            logger.debug("OBD link wake (%s) ignored -- no wake event wired", reason)
            return
        logger.info(
            "OBD link wake requested (%s) -- reconnect backoff will be cut "
            "short (US-751)",
            reason,
        )
        wakeEvent.set()

    def _liveRetryAuthorityName(self) -> str | None:
        """Name the retry thread that currently owns reconnection, if any (US-690).

        The orchestrator has three retry threads -- the US-301 PENDING
        heartbeat, this mixin's recovery loop, and the US-338 post-failure
        heartbeat.  Each used to guard only against ANOTHER COPY OF ITSELF, so
        two different ones could run at once against the one port, each with
        its own counter and backoff.  This is the one check all spawn points
        share.

        The calling thread is excluded: the recovery loop hands off to the
        post-failure heartbeat from inside its own thread, and must not see
        itself as the authority blocking that handoff.

        Returns:
            The live thread's name, or None when no retry thread is alive.
        """
        current = threading.current_thread()
        candidates = (
            getattr(self, '_reconnectHeartbeatThread', None),
            getattr(self, '_reconnectThread', None),
            getattr(self, '_postFailureReconnectHeartbeatThread', None),
        )
        for thread in candidates:
            if thread is None or thread is current:
                continue
            if thread.is_alive():
                return str(thread.name)
        return None

    def _pauseDataLogging(self) -> None:
        """
        Pause data logging during reconnection.

        Stops the data logger polling to prevent errors while connection
        is unavailable.
        """
        if self._dataLogger is None or self._dataLoggerPausedForReconnect:
            return

        try:
            if hasattr(self._dataLogger, 'stop'):
                self._dataLogger.stop()
                self._dataLoggerPausedForReconnect = True
                logger.info("Data logging paused during reconnection")
        except Exception as e:
            logger.warning(f"Failed to pause data logging: {e}")

    def _resumeDataLogging(self) -> None:
        """
        Resume data logging after successful reconnection.

        Restarts the data logger if it was paused for reconnection.
        """
        if self._dataLogger is None or not self._dataLoggerPausedForReconnect:
            return

        try:
            if hasattr(self._dataLogger, 'start'):
                self._dataLogger.start()
                self._dataLoggerPausedForReconnect = False
                logger.info("Data logging resumed after reconnection")
        except Exception as e:
            logger.warning(f"Failed to resume data logging: {e}")


__all__ = ['ConnectionRecoveryMixin']
