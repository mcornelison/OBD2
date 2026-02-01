################################################################################
# File Name: shutdown_manager.py
# Purpose/Description: Graceful shutdown management for OBD-II system
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-005
# ================================================================================
################################################################################

"""
Graceful shutdown management module for the Eclipse OBD-II system.

Provides:
- SIGTERM and SIGINT signal handling
- Clean database connection closure
- OBD-II dongle disconnection
- Pending writes flush before exit
- Shutdown event logging with timestamps
- Callback support for custom cleanup

Usage:
    from obd.shutdown_manager import ShutdownManager, installGlobalShutdownHandler

    # Create and install shutdown handler
    manager = installGlobalShutdownHandler(database=db, connection=conn)

    # Register additional cleanup callbacks
    manager.registerShutdownCallback(cleanupFunction)

    # Check if shutdown was requested
    while not manager.isShutdownRequested():
        # Main application loop
        pass

    # Perform shutdown
    manager.shutdown()
"""

import logging
import signal
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Shutdown event types for database logging
SHUTDOWN_EVENT_TYPE = 'shutdown'
SHUTDOWN_EVENT_SIGTERM = 'shutdown_sigterm'
SHUTDOWN_EVENT_SIGINT = 'shutdown_sigint'
SHUTDOWN_EVENT_GRACEFUL = 'shutdown_graceful'


# ================================================================================
# ShutdownManager Class
# ================================================================================

class ShutdownManager:
    """
    Manages graceful shutdown for the OBD-II system.

    Handles signal registration, component cleanup, and shutdown coordination.
    Supports both immediate components (database, OBD connection) and custom
    callbacks for additional cleanup tasks.

    Attributes:
        _database: Optional ObdDatabase instance
        _connection: Optional ObdConnection instance
        _shutdownRequested: Whether shutdown has been requested
        _shutdownComplete: Whether shutdown has completed

    Example:
        # Create manager with components
        manager = ShutdownManager(database=db, connection=conn)
        manager.installHandlers()

        # Main loop
        while not manager.isShutdownRequested():
            # Do work
            pass

        # Shutdown
        manager.shutdown()
    """

    def __init__(
        self,
        database: Any | None = None,
        connection: Any | None = None
    ):
        """
        Initialize the shutdown manager.

        Args:
            database: Optional ObdDatabase instance to manage
            connection: Optional ObdConnection instance to manage
        """
        self._database = database
        self._connection = connection
        self._shutdownRequested = False
        self._shutdownComplete = False
        self._shutdownCallbacks: list[Callable[[], None]] = []
        self._originalHandlers: dict[int, Any] = {}
        self._signalReceived: int | None = None

    def registerDatabase(self, database: Any) -> None:
        """
        Register a database for shutdown management.

        Args:
            database: ObdDatabase instance to manage
        """
        self._database = database
        logger.debug("Database registered for shutdown management")

    def registerConnection(self, connection: Any) -> None:
        """
        Register an OBD connection for shutdown management.

        Args:
            connection: ObdConnection instance to manage
        """
        self._connection = connection
        logger.debug("Connection registered for shutdown management")

    def registerShutdownCallback(self, callback: Callable[[], None]) -> None:
        """
        Register a callback to be executed during shutdown.

        Callbacks are executed before closing components, in the order they
        were registered. Callbacks that throw exceptions are caught and logged,
        and shutdown continues.

        Args:
            callback: Function to call during shutdown (no arguments, no return)
        """
        self._shutdownCallbacks.append(callback)
        logger.debug(f"Shutdown callback registered | total={len(self._shutdownCallbacks)}")

    def installHandlers(self) -> None:
        """
        Install signal handlers for graceful shutdown.

        Registers handlers for SIGTERM and SIGINT. On the first signal,
        sets the shutdown requested flag. On the second signal, forces
        immediate exit.

        Note: On Windows, SIGTERM may not be available.
        """
        # Store original handlers for restoration
        self._originalHandlers[signal.SIGINT] = signal.signal(
            signal.SIGINT, self._handleSignal
        )

        # SIGTERM may not be available on Windows
        try:
            self._originalHandlers[signal.SIGTERM] = signal.signal(
                signal.SIGTERM, self._handleSignal
            )
            logger.info("Installed shutdown handlers for SIGINT and SIGTERM")
        except (ValueError, OSError):
            logger.info("Installed shutdown handler for SIGINT only (SIGTERM not available)")

    def _handleSignal(self, signum: int, frame: Any) -> None:
        """
        Handle incoming signals.

        First signal sets shutdown requested flag. Second signal forces exit.

        Args:
            signum: Signal number received
            frame: Current stack frame (unused)
        """
        signalName = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)

        if self._shutdownRequested:
            # Second signal - force exit
            logger.warning(f"Received second {signalName} - forcing exit")
            sys.exit(1)

        # First signal - request graceful shutdown
        logger.info(f"Received {signalName} - initiating graceful shutdown")
        self._shutdownRequested = True
        self._signalReceived = signum

    def isShutdownRequested(self) -> bool:
        """
        Check if shutdown has been requested.

        Returns:
            True if shutdown has been requested, False otherwise
        """
        return self._shutdownRequested

    def isShutdownComplete(self) -> bool:
        """
        Check if shutdown has completed.

        Returns:
            True if shutdown has completed, False otherwise
        """
        return self._shutdownComplete

    def shutdown(self) -> None:
        """
        Perform graceful shutdown.

        Executes the following steps in order:
        1. Log shutdown event to database
        2. Execute registered callbacks
        3. Disconnect OBD connection
        4. Flush pending writes (vacuum database)
        5. Set shutdown complete flag

        This method is idempotent - calling it multiple times has no effect
        after the first call.
        """
        if self._shutdownComplete:
            logger.debug("Shutdown already complete - skipping")
            return

        logger.info("Beginning graceful shutdown sequence")
        shutdownStartTime = datetime.now()

        try:
            # Step 1: Log shutdown event to database
            self._logShutdownEvent()

            # Step 2: Execute registered callbacks
            self._executeCallbacks()

            # Step 3: Disconnect OBD connection
            self._disconnectConnection()

            # Step 4: Flush pending writes
            self._flushPendingWrites()

            # Step 5: Restore original signal handlers
            self._restoreHandlers()

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        finally:
            self._shutdownComplete = True
            shutdownDuration = (datetime.now() - shutdownStartTime).total_seconds()
            logger.info(f"Graceful shutdown complete | duration={shutdownDuration:.2f}s")

    def _logShutdownEvent(self) -> None:
        """
        Log shutdown event to database with timestamp.

        Records the shutdown in the connection_log table with the signal
        that triggered it (if any).
        """
        if self._database is None:
            logger.debug("No database registered - skipping shutdown event logging")
            return

        try:
            # Determine event type based on signal
            if self._signalReceived == signal.SIGTERM:
                eventType = SHUTDOWN_EVENT_SIGTERM
            elif self._signalReceived == signal.SIGINT:
                eventType = SHUTDOWN_EVENT_SIGINT
            else:
                eventType = SHUTDOWN_EVENT_GRACEFUL

            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO connection_log
                    (event_type, mac_address, success, error_message, retry_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (eventType, None, 1, None, 0)
                )

            logger.info(f"Logged shutdown event | type={eventType}")

        except Exception as e:
            logger.warning(f"Failed to log shutdown event: {e}")

    def _executeCallbacks(self) -> None:
        """
        Execute all registered shutdown callbacks.

        Callbacks are executed in registration order. Errors are caught
        and logged, allowing subsequent callbacks to execute.
        """
        if not self._shutdownCallbacks:
            return

        logger.info(f"Executing {len(self._shutdownCallbacks)} shutdown callbacks")

        for i, callback in enumerate(self._shutdownCallbacks):
            try:
                callback()
                logger.debug(f"Executed callback {i + 1}/{len(self._shutdownCallbacks)}")
            except Exception as e:
                logger.error(f"Error in shutdown callback {i + 1}: {e}")

    def _disconnectConnection(self) -> None:
        """
        Disconnect from OBD-II dongle.

        Calls disconnect() on the registered connection. Errors are
        caught and logged.
        """
        if self._connection is None:
            logger.debug("No connection registered - skipping disconnect")
            return

        try:
            logger.info("Disconnecting from OBD-II dongle")
            self._connection.disconnect()
            logger.info("OBD-II disconnection complete")
        except Exception as e:
            logger.error(f"Error disconnecting from OBD-II: {e}")

    def _flushPendingWrites(self) -> None:
        """
        Flush any pending writes to the database.

        Calls vacuum() on the database to ensure all writes are persisted.
        Errors are caught and logged.
        """
        if self._database is None:
            logger.debug("No database registered - skipping flush")
            return

        try:
            logger.info("Flushing pending database writes")
            self._database.vacuum()
            logger.info("Database flush complete")
        except Exception as e:
            logger.warning(f"Error flushing database: {e}")

    def _restoreHandlers(self) -> None:
        """
        Restore original signal handlers.

        Restores the signal handlers that were active before installHandlers()
        was called.
        """
        for signum, handler in self._originalHandlers.items():
            try:
                signal.signal(signum, handler)
            except Exception as e:
                logger.warning(f"Error restoring signal handler: {e}")

        self._originalHandlers.clear()
        logger.debug("Original signal handlers restored")

    def getStatus(self) -> dict[str, Any]:
        """
        Get current shutdown manager status.

        Returns:
            Dictionary with status information:
            - shutdownRequested: Whether shutdown was requested
            - shutdownComplete: Whether shutdown has completed
            - hasDatabase: Whether a database is registered
            - hasConnection: Whether a connection is registered
            - callbackCount: Number of registered callbacks
        """
        return {
            'shutdownRequested': self._shutdownRequested,
            'shutdownComplete': self._shutdownComplete,
            'hasDatabase': self._database is not None,
            'hasConnection': self._connection is not None,
            'callbackCount': len(self._shutdownCallbacks)
        }


# ================================================================================
# Helper Functions
# ================================================================================

def createShutdownManager(
    database: Any | None = None,
    connection: Any | None = None
) -> ShutdownManager:
    """
    Create a ShutdownManager instance with the given components.

    Args:
        database: Optional ObdDatabase instance
        connection: Optional ObdConnection instance

    Returns:
        Configured ShutdownManager instance

    Example:
        manager = createShutdownManager(database=db, connection=conn)
    """
    return ShutdownManager(database=database, connection=connection)


def installGlobalShutdownHandler(
    database: Any | None = None,
    connection: Any | None = None
) -> ShutdownManager:
    """
    Create and install a global shutdown handler.

    Convenience function that creates a ShutdownManager and installs
    signal handlers in one step.

    Args:
        database: Optional ObdDatabase instance
        connection: Optional ObdConnection instance

    Returns:
        Configured ShutdownManager with handlers installed

    Example:
        manager = installGlobalShutdownHandler(database=db, connection=conn)

        # Main application loop
        while not manager.isShutdownRequested():
            # Do work
            pass

        manager.shutdown()
    """
    manager = createShutdownManager(database=database, connection=connection)
    manager.installHandlers()
    return manager
