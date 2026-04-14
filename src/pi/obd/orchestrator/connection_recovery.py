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

from .types import HealthCheckStats, ShutdownState

# Unified logger name matches the original monolith module so existing tests
# that filter caplog by logger name continue to work unchanged.
logger = logging.getLogger("pi.obd.orchestrator")


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

        Returns:
            True if reconnection successful, False otherwise
        """
        if self._connection is None:
            return False

        try:
            # Check if connection has reconnect method (preferred)
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

        # Note: Data logging remains paused since connection is unavailable
        # The system continues running so user can monitor other aspects
        # or manually intervene

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
