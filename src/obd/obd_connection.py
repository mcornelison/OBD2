################################################################################
# File Name: obd_connection.py
# Purpose/Description: Bluetooth OBD-II dongle connection management
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-003
# ================================================================================
################################################################################

"""
Bluetooth OBD-II connection management module.

Provides:
- Bluetooth OBD-II dongle connectivity using python-OBD library
- Retry logic with configurable exponential backoff
- Connection status monitoring
- Connection attempt logging to database

Usage:
    from obd.obd_connection import ObdConnection

    # Create connection manager
    conn = ObdConnection(config, database)

    # Connect with retry
    if conn.connect():
        status = conn.getStatus()
        # Use conn.obd for OBD commands
        rpm = conn.obd.query(obd.commands.RPM)

    # Disconnect
    conn.disconnect()
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# OBD library import with fallback for environments where it's not available
try:
    import obd as obdlib
    OBD_AVAILABLE = True
except ImportError:
    obdlib = None  # type: ignore
    OBD_AVAILABLE = False
    logger.warning("python-OBD library not available - OBD functionality disabled")


# ================================================================================
# Constants
# ================================================================================

# Default retry delays in seconds (exponential backoff)
DEFAULT_RETRY_DELAYS = [1, 2, 4, 8, 16]

# Default connection timeout in seconds
DEFAULT_CONNECTION_TIMEOUT = 30

# Connection event types for logging
EVENT_TYPE_CONNECT_ATTEMPT = 'connect_attempt'
EVENT_TYPE_CONNECT_SUCCESS = 'connect_success'
EVENT_TYPE_CONNECT_FAILURE = 'connect_failure'
EVENT_TYPE_DISCONNECT = 'disconnect'
EVENT_TYPE_RECONNECT = 'reconnect'


# ================================================================================
# Enums and Data Classes
# ================================================================================

class ConnectionState(Enum):
    """Connection state enumeration."""
    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    RECONNECTING = 'reconnecting'
    ERROR = 'error'


@dataclass
class ConnectionStatus:
    """
    Connection status information for monitoring.

    Attributes:
        state: Current connection state
        macAddress: Bluetooth MAC address of the dongle
        connected: Whether connection is active
        lastConnectTime: Timestamp of last successful connection
        lastErrorTime: Timestamp of last error
        lastError: Last error message
        retryCount: Number of retry attempts for current connection
        totalConnections: Total successful connections in session
        totalErrors: Total connection errors in session
    """
    state: ConnectionState = ConnectionState.DISCONNECTED
    macAddress: Optional[str] = None
    connected: bool = False
    lastConnectTime: Optional[datetime] = None
    lastErrorTime: Optional[datetime] = None
    lastError: Optional[str] = None
    retryCount: int = 0
    totalConnections: int = 0
    totalErrors: int = 0

    def toDict(self) -> Dict[str, Any]:
        """Convert status to dictionary for logging/serialization."""
        return {
            'state': self.state.value,
            'macAddress': self.macAddress,
            'connected': self.connected,
            'lastConnectTime': self.lastConnectTime.isoformat() if self.lastConnectTime else None,
            'lastErrorTime': self.lastErrorTime.isoformat() if self.lastErrorTime else None,
            'lastError': self.lastError,
            'retryCount': self.retryCount,
            'totalConnections': self.totalConnections,
            'totalErrors': self.totalErrors
        }


# ================================================================================
# Custom Exceptions
# ================================================================================

class ObdConnectionError(Exception):
    """Base exception for OBD connection errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ObdConnectionTimeoutError(ObdConnectionError):
    """Timeout during OBD connection attempt."""
    pass


class ObdNotAvailableError(ObdConnectionError):
    """python-OBD library not available."""
    pass


class ObdConnectionFailedError(ObdConnectionError):
    """Connection to OBD dongle failed after all retries."""
    pass


# ================================================================================
# OBD Connection Class
# ================================================================================

class ObdConnection:
    """
    Manages Bluetooth OBD-II dongle connections.

    Provides connection management with exponential backoff retry logic,
    connection status monitoring, and database logging of connection events.

    Attributes:
        config: Configuration dictionary with bluetooth settings
        database: Optional ObdDatabase instance for logging
        obd: The underlying OBD connection object (when connected)

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)

        conn = ObdConnection(config, db)
        if conn.connect():
            response = conn.obd.query(obd.commands.RPM)
            print(f"RPM: {response.value}")
        conn.disconnect()
    """

    def __init__(
        self,
        config: Dict[str, Any],
        database: Optional[Any] = None,
        obdFactory: Optional[Callable[..., Any]] = None
    ):
        """
        Initialize OBD connection manager.

        Args:
            config: Configuration dictionary with 'bluetooth' section
            database: Optional ObdDatabase instance for logging connection events
            obdFactory: Optional factory for creating OBD connections (for testing)
        """
        self.config = config
        self.database = database
        self._obdFactory = obdFactory

        # Extract bluetooth configuration
        btConfig = config.get('bluetooth', {})
        self.macAddress = btConfig.get('macAddress', '')
        self.retryDelays = btConfig.get('retryDelays', DEFAULT_RETRY_DELAYS)
        self.maxRetries = btConfig.get('maxRetries', len(self.retryDelays))
        self.connectionTimeout = btConfig.get('connectionTimeoutSeconds', DEFAULT_CONNECTION_TIMEOUT)

        # Connection state
        self.obd: Optional[Any] = None
        self._status = ConnectionStatus(macAddress=self.macAddress)

    def getStatus(self) -> ConnectionStatus:
        """
        Get current connection status.

        Returns:
            ConnectionStatus with current state information
        """
        # Update connected state from OBD object if available
        if self.obd is not None:
            self._status.connected = self._isConnected()
            if not self._status.connected:
                self._status.state = ConnectionState.DISCONNECTED
        return self._status

    def isConnected(self) -> bool:
        """
        Check if OBD connection is active.

        Returns:
            True if connected, False otherwise
        """
        return self._isConnected()

    def _isConnected(self) -> bool:
        """Internal connection check."""
        if self.obd is None:
            return False
        try:
            # Check if OBD connection is active
            return self.obd.is_connected()
        except Exception:
            return False

    def connect(self) -> bool:
        """
        Connect to OBD-II dongle with retry logic.

        Attempts to connect using exponential backoff retry delays.
        Logs all connection attempts to database if available.

        Returns:
            True if connection successful, False otherwise

        Raises:
            ObdNotAvailableError: If python-OBD library not available
        """
        if not OBD_AVAILABLE and self._obdFactory is None:
            error = "python-OBD library not available"
            self._logConnectionEvent(EVENT_TYPE_CONNECT_FAILURE, success=False, errorMessage=error)
            raise ObdNotAvailableError(error)

        self._status.state = ConnectionState.CONNECTING
        self._status.retryCount = 0

        logger.info(f"Connecting to OBD-II dongle | mac={self.macAddress}")

        # Attempt connection with retries
        for attempt in range(self.maxRetries + 1):
            try:
                self._logConnectionEvent(
                    EVENT_TYPE_CONNECT_ATTEMPT,
                    retryCount=attempt
                )

                # Create OBD connection
                if self._obdFactory is not None:
                    self.obd = self._obdFactory(self.macAddress, self.connectionTimeout)
                else:
                    self.obd = self._createObdConnection()

                # Check if connection was successful
                if self._isConnected():
                    self._status.state = ConnectionState.CONNECTED
                    self._status.connected = True
                    self._status.lastConnectTime = datetime.now()
                    self._status.totalConnections += 1
                    self._status.retryCount = attempt

                    self._logConnectionEvent(
                        EVENT_TYPE_CONNECT_SUCCESS,
                        success=True,
                        retryCount=attempt
                    )

                    logger.info(f"Connected to OBD-II dongle | mac={self.macAddress} | attempts={attempt + 1}")
                    return True
                else:
                    # Connection object created but not connected
                    raise ObdConnectionError("OBD connection not active after creation")

            except Exception as e:
                self._status.lastError = str(e)
                self._status.lastErrorTime = datetime.now()
                self._status.totalErrors += 1

                logger.warning(
                    f"Connection attempt {attempt + 1}/{self.maxRetries + 1} failed | "
                    f"mac={self.macAddress} | error={e}"
                )

                # Check if we should retry
                if attempt < self.maxRetries:
                    # Get delay for this attempt (use last delay if index out of range)
                    delayIndex = min(attempt, len(self.retryDelays) - 1)
                    delay = self.retryDelays[delayIndex]

                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                    self._status.retryCount = attempt + 1
                else:
                    # All retries exhausted
                    self._status.state = ConnectionState.ERROR
                    self._logConnectionEvent(
                        EVENT_TYPE_CONNECT_FAILURE,
                        success=False,
                        errorMessage=str(e),
                        retryCount=attempt
                    )
                    logger.error(
                        f"Failed to connect after {self.maxRetries + 1} attempts | "
                        f"mac={self.macAddress}"
                    )

        return False

    def _createObdConnection(self) -> Any:
        """
        Create the underlying OBD connection.

        Returns:
            obd.OBD connection object

        Raises:
            ObdConnectionError: If connection creation fails
        """
        if obdlib is None:
            raise ObdNotAvailableError("python-OBD library not available")

        try:
            # Configure port name based on MAC address
            # On Linux/Raspberry Pi, Bluetooth serial port is typically /dev/rfcomm0
            # The MAC address is used for Bluetooth pairing
            portName = self.macAddress if self.macAddress else None

            # Create OBD connection
            # fast=False allows for more compatible but slower connection
            # timeout controls command timeout
            connection = obdlib.OBD(
                portstr=portName,
                fast=False,
                timeout=self.connectionTimeout
            )

            return connection

        except Exception as e:
            raise ObdConnectionError(
                f"Failed to create OBD connection: {e}",
                details={'macAddress': self.macAddress, 'error': str(e)}
            )

    def disconnect(self) -> None:
        """
        Disconnect from OBD-II dongle.

        Cleanly closes the OBD connection and logs the event.
        """
        if self.obd is not None:
            try:
                logger.info(f"Disconnecting from OBD-II dongle | mac={self.macAddress}")
                self.obd.close()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self.obd = None

        self._status.state = ConnectionState.DISCONNECTED
        self._status.connected = False

        self._logConnectionEvent(EVENT_TYPE_DISCONNECT)

    def reconnect(self) -> bool:
        """
        Reconnect to OBD-II dongle.

        Disconnects if connected, then attempts to connect again.

        Returns:
            True if reconnection successful, False otherwise
        """
        logger.info("Attempting reconnection to OBD-II dongle")
        self._status.state = ConnectionState.RECONNECTING

        self._logConnectionEvent(EVENT_TYPE_RECONNECT)

        self.disconnect()
        return self.connect()

    def _logConnectionEvent(
        self,
        eventType: str,
        success: bool = False,
        errorMessage: Optional[str] = None,
        retryCount: int = 0
    ) -> None:
        """
        Log connection event to database.

        Args:
            eventType: Type of connection event
            success: Whether the event was successful
            errorMessage: Error message if failed
            retryCount: Number of retry attempts
        """
        if self.database is None:
            return

        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO connection_log
                    (event_type, mac_address, success, error_message, retry_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (eventType, self.macAddress, 1 if success else 0, errorMessage, retryCount)
                )
        except Exception as e:
            logger.warning(f"Failed to log connection event: {e}")


# ================================================================================
# Helper Functions
# ================================================================================

def createConnectionFromConfig(
    config: Dict[str, Any],
    database: Optional[Any] = None
) -> ObdConnection:
    """
    Create an ObdConnection instance from configuration.

    Args:
        config: Configuration dictionary with 'bluetooth' section
        database: Optional ObdDatabase instance for logging

    Returns:
        Configured ObdConnection instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)
    """
    return ObdConnection(config, database)


def isObdAvailable() -> bool:
    """
    Check if python-OBD library is available.

    Returns:
        True if library is installed and importable
    """
    return OBD_AVAILABLE
