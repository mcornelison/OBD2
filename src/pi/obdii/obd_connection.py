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
# 2026-04-23    | Rex (US-232)  | TD-035 close: accept shutdownEvent; retry
#                |              | loop uses Event.wait() for backoff so
#                |              | SIGTERM wakes mid-sleep within ~ms.
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
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from . import bluetooth_helper

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

# Default rfcomm device index and channel for OBDLink LX.
# Channel 1 is the SPP channel confirmed via sdptool browse during Session 23.
DEFAULT_RFCOMM_DEVICE = 0
DEFAULT_RFCOMM_CHANNEL = 1

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
    macAddress: str | None = None
    connected: bool = False
    lastConnectTime: datetime | None = None
    lastErrorTime: datetime | None = None
    lastError: str | None = None
    retryCount: int = 0
    totalConnections: int = 0
    totalErrors: int = 0

    def toDict(self) -> dict[str, Any]:
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

    def __init__(self, message: str, details: dict[str, Any] | None = None):
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
        config: dict[str, Any],
        database: Any | None = None,
        obdFactory: Callable[..., Any] | None = None,
        shutdownEvent: threading.Event | None = None,
    ):
        """
        Initialize OBD connection manager.

        Args:
            config: Configuration dictionary with 'bluetooth' section
            database: Optional ObdDatabase instance for logging connection events
            obdFactory: Optional factory for creating OBD connections (for testing)
            shutdownEvent: Optional :class:`threading.Event` used by the retry
                loop to abort early when SIGTERM/SIGINT arrives (US-232 /
                TD-035). When ``set()`` mid-backoff, ``connect()`` returns
                ``False`` within a few ms instead of sleeping the full
                ``retryDelays`` entry (worst case ~90s). Main-thread signal
                handlers installed by the orchestrator set the event.
        """
        self.config = config
        self.database = database
        self._obdFactory = obdFactory
        self.shutdownEvent = shutdownEvent

        # Extract bluetooth configuration
        btConfig = config.get('pi', {}).get('bluetooth', {})
        self.macAddress = btConfig.get('macAddress', '')
        self.retryDelays = btConfig.get('retryDelays', DEFAULT_RETRY_DELAYS)
        self.maxRetries = btConfig.get('maxRetries', len(self.retryDelays))
        self.connectionTimeout = btConfig.get('connectionTimeoutSeconds', DEFAULT_CONNECTION_TIMEOUT)
        self.rfcommDevice = btConfig.get('rfcommDevice', DEFAULT_RFCOMM_DEVICE)
        self.rfcommChannel = btConfig.get('rfcommChannel', DEFAULT_RFCOMM_CHANNEL)

        # Connection state
        self.obd: Any | None = None
        self._status = ConnectionStatus(macAddress=self.macAddress)
        # Set True once this instance performed the rfcomm bind, so
        # disconnect() knows whether to call releaseRfcomm. When the caller
        # configured a literal /dev/rfcommN path (BC), we never bind and
        # must not release.
        self._boundRfcomm: bool = False
        # US-199: Supported-PID probe result cached at connection-open time.
        # None until connect() runs the probe. Consumers (ObdDataLogger) use
        # it to silent-skip unsupported PIDs before dispatching a K-line query.
        self.supportedPids: Any | None = None

    def getStatus(self) -> ConnectionStatus:
        """
        Get current connection status.

        Returns:
            ConnectionStatus with current state information
        """
        # Update connected state from OBD object if available
        if self.obd is not None:
            self._status.connected = self._isConnected()
            if not self._status.connected and self._status.state != ConnectionState.ERROR:
                # Only reset to DISCONNECTED if not in ERROR state (preserve error state)
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
            # US-232 / TD-035: honor an already-set shutdown event before
            # even dispatching the next attempt. Covers the pre-set path
            # (SIGTERM arrived while we were preparing for the next retry).
            if self.shutdownEvent is not None and self.shutdownEvent.is_set():
                logger.info(
                    "Connect retry loop exiting -- shutdown signaled "
                    "before attempt %d",
                    attempt + 1,
                )
                self._status.state = ConnectionState.DISCONNECTED
                return False

            try:
                self._logConnectionEvent(
                    EVENT_TYPE_CONNECT_ATTEMPT,
                    retryCount=attempt
                )

                # Resolve MAC -> /dev/rfcommN if needed. When the caller
                # passed a literal device path (or left config empty) we
                # pass it through unchanged for backwards compatibility.
                serialPort = self._resolvePort()

                # Create OBD connection
                if self._obdFactory is not None:
                    self.obd = self._obdFactory(serialPort, self.connectionTimeout)
                else:
                    self.obd = self._createObdConnection(serialPort)

                # Check if connection was successful
                if self._isConnected():
                    self._status.state = ConnectionState.CONNECTED
                    self._status.connected = True
                    self._status.lastConnectTime = datetime.now()
                    self._status.totalConnections += 1
                    self._status.retryCount = attempt

                    # US-199: one-shot supported-PID probe so the realtime
                    # logger can silent-skip unsupported PIDs (0x42/0x0B/0x15
                    # candidates on 2G). Best-effort — probe failure never
                    # fails the connection itself.
                    self._runSupportedPidProbe()

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
                    # Get delay for this attempt (use 0 if empty, else last delay if index out of range)
                    if not self.retryDelays:
                        delay = 0
                    else:
                        delayIndex = min(attempt, len(self.retryDelays) - 1)
                        delay = self.retryDelays[delayIndex]

                    logger.info(f"Retrying in {delay}s...")
                    # US-232 / TD-035: use event.wait() when a shutdown event
                    # is plumbed in so a signal handler set() wakes us mid-
                    # backoff. Returns True when the event fired; return
                    # False to abort the retry loop cleanly. When no event
                    # is plumbed in, fall back to legacy time.sleep so the
                    # behavior is unchanged for any caller that didn't
                    # opt into the responsiveness seam.
                    if delay > 0:
                        if self.shutdownEvent is not None:
                            if self.shutdownEvent.wait(timeout=delay):
                                logger.info(
                                    "Connect retry loop exiting -- shutdown "
                                    "signaled during backoff (attempt %d/%d)",
                                    attempt + 1,
                                    self.maxRetries + 1,
                                )
                                self._status.state = ConnectionState.DISCONNECTED
                                return False
                        else:
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

    def _runSupportedPidProbe(self) -> None:
        """Populate :attr:`supportedPids` from python-obd's auto-probed commands.

        Never raises — probe failures fall back to always-supported so the
        poll loop still dispatches every configured PID (null-response
        silent-skip remains the fallback safety net).
        """
        try:
            # Imported lazily to avoid coupling ObdConnection to pid_probe at
            # module import time (keeps the legacy import graph clean).
            from .pid_probe import SupportedPidSet, probeSupportedPids

            probed = probeSupportedPids(self)
            self.supportedPids = probed
            logger.info(
                "Supported-PID probe | discovered=%d | fallbackAllowAll=%s",
                len(probed),
                probed.fallbackAllowAll,
            )
        except Exception as exc:  # noqa: BLE001
            from .pid_probe import SupportedPidSet
            logger.warning("Supported-PID probe failed (%s) — falling back to always-supported", exc)
            self.supportedPids = SupportedPidSet.alwaysSupported()

    def _resolvePort(self) -> str | None:
        """
        Resolve the configured port value to a serial device path.

        If ``self.macAddress`` looks like a Bluetooth MAC, idempotently bind
        it via rfcomm and return the resulting ``/dev/rfcommN`` path. If it
        already looks like a path (or is empty), return it unchanged.

        Returns:
            The serial port path ``obd.OBD(portstr=...)`` should open,
            or ``None`` when no port is configured at all.

        Raises:
            ObdConnectionError: On rfcomm bind failure; stderr is surfaced.
        """
        port = self.macAddress
        if not port:
            return None

        if not bluetooth_helper.isMacAddress(port):
            # Literal path (e.g. /dev/rfcomm0) — pass through unchanged.
            return port

        try:
            resolved = bluetooth_helper.bindRfcomm(
                macAddress=port,
                device=self.rfcommDevice,
                channel=self.rfcommChannel,
            )
        except bluetooth_helper.BluetoothHelperError as exc:
            # Surface stderr + exact invocation into the warning log per invariant.
            logger.warning("rfcomm bind failed | %s", exc)
            raise ObdConnectionError(
                f"Failed to bind rfcomm for MAC {port}: {exc}",
                details={'macAddress': port, 'error': str(exc)},
            ) from exc

        self._boundRfcomm = True
        return resolved

    def _createObdConnection(self, serialPort: str | None = None) -> Any:
        """
        Create the underlying OBD connection.

        Args:
            serialPort: Pre-resolved serial device path (e.g. /dev/rfcomm0).
                        Caller is expected to have run :meth:`_resolvePort`.
                        When ``None`` we fall back to the configured port.

        Returns:
            obd.OBD connection object

        Raises:
            ObdConnectionError: If connection creation fails
        """
        if obdlib is None:
            raise ObdNotAvailableError("python-OBD library not available")

        portName = serialPort if serialPort is not None else (self.macAddress or None)

        try:
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
                details={'macAddress': self.macAddress, 'portstr': portName, 'error': str(e)}
            ) from e

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

        # Release the rfcomm device we bound so the next connect() is idempotent
        # and the kernel slot is free for reuse. Path-style BC (self._boundRfcomm
        # is False) skips this — someone else owns the bind.
        if self._boundRfcomm:
            try:
                bluetooth_helper.releaseRfcomm(device=self.rfcommDevice)
            except bluetooth_helper.BluetoothHelperError as exc:
                logger.warning("rfcomm release during disconnect failed | %s", exc)
            finally:
                self._boundRfcomm = False

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
        errorMessage: str | None = None,
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
    config: dict[str, Any],
    database: Any | None = None,
    simulateFlag: bool = False,
    shutdownEvent: threading.Event | None = None,
) -> Any:
    """
    Create an OBD connection instance from configuration.

    When simulation mode is enabled (via config or --simulate flag), returns
    a SimulatedObdConnection. Otherwise returns a real ObdConnection.

    Args:
        config: Configuration dictionary with 'bluetooth' section
        database: Optional ObdDatabase instance for logging
        simulateFlag: True if --simulate CLI flag was passed (overrides config)
        shutdownEvent: Optional :class:`threading.Event` plumbed into the real
            :class:`ObdConnection` so its retry-loop backoff is
            interruptible by a SIGTERM-set event (US-232 / TD-035). Ignored
            by the SimulatedObdConnection path (no retries to interrupt).

    Returns:
        ObdConnection or SimulatedObdConnection based on simulation mode

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)

        # Real connection
        conn = createConnectionFromConfig(config, db)

        # Simulated connection (via flag)
        simConn = createConnectionFromConfig(config, db, simulateFlag=True)
    """
    # Import here to avoid circular imports
    from .config import isSimulatorEnabled

    # Check if simulation mode is enabled
    if isSimulatorEnabled(config, simulateFlag):
        from .config import getSimulatorConfig
        from .simulator import (
            SimulatedObdConnection,
            loadProfile,
        )

        logger.info("Creating SimulatedObdConnection (simulation mode enabled)")

        simConfig = getSimulatorConfig(config)

        # Load vehicle profile if specified
        profile = None
        profilePath = simConfig.get('profilePath', '')
        if profilePath:
            try:
                profile = loadProfile(profilePath)
                logger.info(f"Loaded vehicle profile: {profilePath}")
            except Exception as e:
                logger.warning(f"Failed to load vehicle profile '{profilePath}': {e}")
                logger.info("Using default vehicle profile")

        return SimulatedObdConnection(
            profile=profile,
            connectionDelaySeconds=simConfig.get('connectionDelaySeconds', 2.0),
            config=config,
            database=database
        )

    # Return real connection
    logger.info("Creating real ObdConnection")
    return ObdConnection(config, database, shutdownEvent=shutdownEvent)


def isObdAvailable() -> bool:
    """
    Check if python-OBD library is available.

    Returns:
        True if library is installed and importable
    """
    return OBD_AVAILABLE
