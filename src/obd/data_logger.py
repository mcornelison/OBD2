################################################################################
# File Name: data_logger.py
# Purpose/Description: OBD-II data logging module for reading and storing parameters
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-004
# 2026-01-22    | M. Cornelison | US-012 - Add RealtimeDataLogger for continuous logging
# ================================================================================
################################################################################

"""
OBD-II data logging module for the Eclipse Performance Monitoring System.

Provides:
- Parameter querying via OBD-II connection
- Data logging to SQLite database with timestamps
- Data persistence verification
- Statistics tracking for logged readings
- Continuous realtime data logging with configurable polling

Usage:
    from obd.data_logger import ObdDataLogger, LoggedReading, RealtimeDataLogger

    # Create logger with connection and database
    logger = ObdDataLogger(obdConnection, database, profileId='daily')

    # Query and log a parameter
    reading = logger.queryAndLogParameter('RPM')
    print(f"RPM: {reading.value} {reading.unit}")

    # Continuous realtime logging
    realtimeLogger = RealtimeDataLogger(config, connection, database)
    realtimeLogger.start()  # Starts logging in background thread
    # ... later ...
    realtimeLogger.stop()   # Stops logging gracefully

    # Verify data persistence
    from obd.data_logger import verifyDataPersistence
    exists = verifyDataPersistence(database, 'RPM')
"""

import logging
import threading
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


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class LoggedReading:
    """
    Represents a logged OBD-II parameter reading.

    Attributes:
        parameterName: Name of the OBD-II parameter (e.g., 'RPM', 'COOLANT_TEMP')
        value: Numeric value of the reading
        unit: Unit of measurement (e.g., 'rpm', 'degC')
        timestamp: When the reading was taken
        profileId: Associated profile ID for data grouping
    """
    parameterName: str
    value: float
    timestamp: datetime
    unit: Optional[str] = None
    profileId: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert reading to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'value': self.value,
            'unit': self.unit,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'profileId': self.profileId
        }


# ================================================================================
# Custom Exceptions
# ================================================================================

class DataLoggerError(Exception):
    """Base exception for data logger errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ParameterNotSupportedError(DataLoggerError):
    """Parameter is not supported by the vehicle."""
    pass


class ParameterReadError(DataLoggerError):
    """Error reading a parameter from the OBD-II interface."""
    pass


# ================================================================================
# OBD Data Logger Class
# ================================================================================

class ObdDataLogger:
    """
    Manages OBD-II data logging operations.

    Provides parameter querying, database storage, and statistics tracking
    for OBD-II data acquisition.

    Attributes:
        connection: ObdConnection instance for communicating with the dongle
        database: ObdDatabase instance for data storage
        profileId: Optional profile ID for data grouping

    Example:
        # Setup
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = ObdConnection(config, db)
        conn.connect()

        # Create logger and log data
        logger = ObdDataLogger(conn, db, profileId='daily')
        reading = logger.queryAndLogParameter('RPM')
        print(f"Logged RPM: {reading.value}")

        # Check stats
        stats = logger.getStats()
        print(f"Total readings: {stats['totalReadings']}")
    """

    def __init__(
        self,
        connection: Any,
        database: Any,
        profileId: Optional[str] = None
    ):
        """
        Initialize the data logger.

        Args:
            connection: ObdConnection instance for OBD-II communication
            database: ObdDatabase instance for data storage
            profileId: Optional profile ID for associating logged data
        """
        self.connection = connection
        self.database = database
        self.profileId = profileId

        # Statistics tracking
        self._totalReadings = 0
        self._totalLogged = 0
        self._lastReadingTime: Optional[datetime] = None
        self._readErrors = 0

    def queryParameter(self, parameterName: str) -> LoggedReading:
        """
        Query a single parameter from the OBD-II interface.

        Args:
            parameterName: Name of the OBD-II parameter (e.g., 'RPM')

        Returns:
            LoggedReading with the parameter value

        Raises:
            DataLoggerError: If not connected to OBD-II
            ParameterReadError: If parameter cannot be read
            ParameterNotSupportedError: If parameter is not supported
        """
        if not self.connection.isConnected():
            raise DataLoggerError(
                "Not connected to OBD-II",
                details={'parameter': parameterName}
            )

        try:
            # Get the OBD command for this parameter
            cmd = self._getObdCommand(parameterName)

            # Query the parameter - cmd may be the command object or the name
            response = self.connection.obd.query(cmd)

            # Check if response is valid
            if response.is_null():
                self._readErrors += 1
                raise ParameterReadError(
                    f"Parameter '{parameterName}' returned null response",
                    details={'parameter': parameterName}
                )

            # Extract value and unit
            value = self._extractValue(response)
            unit = self._extractUnit(response)

            # Create reading
            timestamp = datetime.now()
            reading = LoggedReading(
                parameterName=parameterName,
                value=value,
                unit=unit,
                timestamp=timestamp,
                profileId=self.profileId
            )

            # Update stats
            self._totalReadings += 1
            self._lastReadingTime = timestamp

            logger.debug(
                f"Read parameter | name={parameterName} | value={value} | unit={unit}"
            )

            return reading

        except (ParameterReadError, ParameterNotSupportedError):
            raise
        except Exception as e:
            self._readErrors += 1
            raise ParameterReadError(
                f"Failed to read parameter '{parameterName}': {e}",
                details={'parameter': parameterName, 'error': str(e)}
            )

    def logReading(self, reading: LoggedReading) -> bool:
        """
        Log a reading to the database.

        Args:
            reading: LoggedReading to store

        Returns:
            True if logged successfully

        Raises:
            DataLoggerError: If database operation fails
        """
        try:
            # Use profile from reading or fall back to logger's profile
            profileId = reading.profileId or self.profileId

            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO realtime_data
                    (timestamp, parameter_name, value, unit, profile_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        reading.timestamp,
                        reading.parameterName,
                        reading.value,
                        reading.unit,
                        profileId
                    )
                )

            self._totalLogged += 1

            logger.debug(
                f"Logged reading | parameter={reading.parameterName} | "
                f"value={reading.value} | profile={profileId}"
            )

            return True

        except Exception as e:
            raise DataLoggerError(
                f"Failed to log reading: {e}",
                details={'reading': reading.toDict(), 'error': str(e)}
            )

    def queryAndLogParameter(self, parameterName: str) -> LoggedReading:
        """
        Query a parameter and immediately log it to the database.

        Convenience method that combines queryParameter and logReading.

        Args:
            parameterName: Name of the OBD-II parameter

        Returns:
            LoggedReading with the logged data

        Raises:
            DataLoggerError: If query or logging fails
        """
        reading = self.queryParameter(parameterName)
        self.logReading(reading)
        return reading

    def getStats(self) -> Dict[str, Any]:
        """
        Get statistics about logged data.

        Returns:
            Dictionary with stats:
            - totalReadings: Number of parameter reads
            - totalLogged: Number of readings logged to database
            - lastReadingTime: Timestamp of last reading
            - readErrors: Number of read errors encountered
        """
        return {
            'totalReadings': self._totalReadings,
            'totalLogged': self._totalLogged,
            'lastReadingTime': (
                self._lastReadingTime.isoformat()
                if self._lastReadingTime else None
            ),
            'readErrors': self._readErrors
        }

    def _getObdCommand(self, parameterName: str) -> Any:
        """
        Get the OBD command object for a parameter name.

        Args:
            parameterName: Name of the parameter (e.g., 'RPM')

        Returns:
            OBD command object or parameter name string for mocked connections

        Raises:
            ParameterNotSupportedError: If parameter is not recognized
        """
        # Try to get command from python-OBD library if available
        if obdlib is not None and hasattr(obdlib, 'commands'):
            cmd = getattr(obdlib.commands, parameterName, None)
            if cmd is not None:
                return cmd

        # For mocked connections or when OBD library doesn't have the command,
        # return the parameter name string. The mock's query() method will
        # handle it appropriately.
        return parameterName

    def _extractValue(self, response: Any) -> float:
        """
        Extract numeric value from OBD response.

        Handles both pint Quantity objects and plain values.

        Args:
            response: OBD response object

        Returns:
            Numeric value as float
        """
        value = response.value

        # Handle pint Quantity objects (have magnitude attribute)
        if hasattr(value, 'magnitude'):
            return float(value.magnitude)

        # Handle plain numeric values
        return float(value)

    def _extractUnit(self, response: Any) -> Optional[str]:
        """
        Extract unit string from OBD response.

        Args:
            response: OBD response object

        Returns:
            Unit string or None
        """
        if hasattr(response, 'unit') and response.unit is not None:
            return str(response.unit)
        return None


# ================================================================================
# Realtime Data Logger Enums and Data Classes
# ================================================================================

class LoggingState(Enum):
    """Logging state enumeration."""
    STOPPED = 'stopped'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'
    ERROR = 'error'


@dataclass
class LoggingStats:
    """
    Statistics for realtime logging session.

    Attributes:
        startTime: When logging started
        endTime: When logging stopped
        totalCycles: Number of complete polling cycles
        totalReadings: Total successful readings
        totalLogged: Total readings logged to database
        totalErrors: Total errors encountered
        parametersLogged: Count per parameter name
        errorsByParameter: Errors by parameter name
        lastCycleTime: Duration of last polling cycle in ms
        averageCycleTimeMs: Average cycle duration in ms
    """
    startTime: Optional[datetime] = None
    endTime: Optional[datetime] = None
    totalCycles: int = 0
    totalReadings: int = 0
    totalLogged: int = 0
    totalErrors: int = 0
    parametersLogged: Dict[str, int] = field(default_factory=dict)
    errorsByParameter: Dict[str, int] = field(default_factory=dict)
    lastCycleTimeMs: float = 0.0
    averageCycleTimeMs: float = 0.0

    def toDict(self) -> Dict[str, Any]:
        """Convert stats to dictionary for serialization."""
        return {
            'startTime': self.startTime.isoformat() if self.startTime else None,
            'endTime': self.endTime.isoformat() if self.endTime else None,
            'totalCycles': self.totalCycles,
            'totalReadings': self.totalReadings,
            'totalLogged': self.totalLogged,
            'totalErrors': self.totalErrors,
            'parametersLogged': dict(self.parametersLogged),
            'errorsByParameter': dict(self.errorsByParameter),
            'lastCycleTimeMs': self.lastCycleTimeMs,
            'averageCycleTimeMs': self.averageCycleTimeMs
        }


# ================================================================================
# Realtime Data Logger Class
# ================================================================================

class RealtimeDataLogger:
    """
    Manages continuous realtime OBD-II data logging.

    Provides a background thread that polls configured parameters at a specified
    interval and logs readings to the database. Only parameters with logData=True
    in the configuration are logged.

    Features:
    - Configurable polling interval (default: 1000ms)
    - Only logs parameters with logData=True
    - Millisecond timestamp precision
    - Graceful handling of unavailable parameters
    - Profile-associated data logging
    - Thread-safe start/stop control
    - Comprehensive statistics tracking

    Attributes:
        config: Configuration dictionary with realtimeData settings
        connection: ObdConnection instance
        database: ObdDatabase instance for data storage
        state: Current logging state

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)
        conn.connect()

        rtLogger = RealtimeDataLogger(config, conn, db)
        rtLogger.start()

        # ... let it run for a while ...

        rtLogger.stop()
        stats = rtLogger.getStats()
        print(f"Logged {stats.totalLogged} readings")
    """

    def __init__(
        self,
        config: Dict[str, Any],
        connection: Any,
        database: Any,
        profileId: Optional[str] = None
    ):
        """
        Initialize the realtime data logger.

        Args:
            config: Configuration dictionary with 'realtimeData' and 'profiles' sections
            connection: ObdConnection instance for OBD-II communication
            database: ObdDatabase instance for data storage
            profileId: Optional profile ID (defaults to active profile from config)
        """
        self.config = config
        self.connection = connection
        self.database = database

        # Determine profile ID
        if profileId is not None:
            self.profileId = profileId
        else:
            profiles = config.get('profiles', {})
            self.profileId = profiles.get('activeProfile')  # None if not specified

        # Extract logging configuration
        realtimeConfig = config.get('realtimeData', {})
        self._pollingIntervalMs = self._getPollingInterval()
        self._parameters = self._getLoggedParameterNames()

        # Thread control
        self._state = LoggingState.STOPPED
        self._stopEvent = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Statistics
        self._stats = LoggingStats()
        self._cycleTimes: List[float] = []

        # Internal data logger for actual queries
        self._dataLogger = ObdDataLogger(connection, database, profileId=self.profileId)

        # Callbacks
        self._onReading: Optional[Callable[[LoggedReading], None]] = None
        self._onError: Optional[Callable[[str, Exception], None]] = None
        self._onCycleComplete: Optional[Callable[[int], None]] = None

    @property
    def state(self) -> LoggingState:
        """Get current logging state."""
        return self._state

    @property
    def isRunning(self) -> bool:
        """Check if logger is currently running."""
        return self._state == LoggingState.RUNNING

    def _getPollingInterval(self) -> int:
        """
        Get the polling interval from configuration.

        Checks active profile first, then falls back to global setting.

        Returns:
            Polling interval in milliseconds
        """
        # Check active profile first
        profiles = self.config.get('profiles', {})
        activeProfileId = profiles.get('activeProfile', 'daily')
        availableProfiles = profiles.get('availableProfiles', [])

        for profile in availableProfiles:
            if profile.get('id') == activeProfileId:
                if 'pollingIntervalMs' in profile:
                    return profile['pollingIntervalMs']
                break

        # Fall back to global realtime setting
        return self.config.get('realtimeData', {}).get('pollingIntervalMs', 1000)

    def _getLoggedParameterNames(self) -> List[str]:
        """
        Get list of parameter names that should be logged.

        Only returns parameters with logData=True.

        Returns:
            List of parameter names to log
        """
        parameters = self.config.get('realtimeData', {}).get('parameters', [])
        loggedParams = []

        for param in parameters:
            if isinstance(param, dict):
                if param.get('logData', False):
                    name = param.get('name', '')
                    if name:
                        loggedParams.append(name)
            elif isinstance(param, str):
                # String parameters default to being logged
                loggedParams.append(param)

        return loggedParams

    def setPollingInterval(self, intervalMs: int) -> None:
        """
        Update the polling interval.

        Can be called while running - takes effect on next cycle.

        Args:
            intervalMs: New polling interval in milliseconds (minimum 100ms)

        Raises:
            ValueError: If interval is less than 100ms
        """
        if intervalMs < 100:
            raise ValueError("Polling interval must be at least 100ms")

        with self._lock:
            self._pollingIntervalMs = intervalMs
            logger.info(f"Polling interval updated to {intervalMs}ms")

    def registerCallbacks(
        self,
        onReading: Optional[Callable[[LoggedReading], None]] = None,
        onError: Optional[Callable[[str, Exception], None]] = None,
        onCycleComplete: Optional[Callable[[int], None]] = None
    ) -> None:
        """
        Register callbacks for logging events.

        Args:
            onReading: Called for each successful reading
            onError: Called when a parameter read fails (paramName, exception)
            onCycleComplete: Called after each polling cycle (cycle number)
        """
        self._onReading = onReading
        self._onError = onError
        self._onCycleComplete = onCycleComplete

    def start(self) -> bool:
        """
        Start continuous realtime logging in a background thread.

        Returns:
            True if started successfully, False if already running or error

        Raises:
            DataLoggerError: If not connected to OBD-II
        """
        with self._lock:
            if self._state in (LoggingState.RUNNING, LoggingState.STARTING):
                logger.warning("Realtime logger already running")
                return False

            if not self.connection.isConnected():
                raise DataLoggerError(
                    "Cannot start realtime logging - not connected to OBD-II"
                )

            if not self._parameters:
                raise DataLoggerError(
                    "No parameters configured for logging. "
                    "Check realtimeData.parameters in config with logData=True"
                )

            self._state = LoggingState.STARTING
            self._stopEvent.clear()

            # Reset statistics
            self._stats = LoggingStats()
            self._stats.startTime = datetime.now()
            self._cycleTimes = []

            # Start background thread
            self._thread = threading.Thread(
                target=self._loggingLoop,
                name='RealtimeDataLogger',
                daemon=True
            )
            self._thread.start()

            logger.info(
                f"Realtime logging started | "
                f"parameters={len(self._parameters)} | "
                f"interval={self._pollingIntervalMs}ms | "
                f"profile={self.profileId}"
            )

            return True

    def stop(self, timeout: float = 5.0) -> bool:
        """
        Stop realtime logging gracefully.

        Args:
            timeout: Maximum time to wait for thread to stop in seconds

        Returns:
            True if stopped successfully, False if timeout
        """
        with self._lock:
            if self._state == LoggingState.STOPPED:
                return True

            self._state = LoggingState.STOPPING

        # Signal thread to stop
        self._stopEvent.set()

        # Wait for thread to finish
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

            if self._thread.is_alive():
                logger.warning("Realtime logging thread did not stop within timeout")
                return False

        with self._lock:
            self._state = LoggingState.STOPPED
            self._stats.endTime = datetime.now()

        logger.info(
            f"Realtime logging stopped | "
            f"cycles={self._stats.totalCycles} | "
            f"logged={self._stats.totalLogged} | "
            f"errors={self._stats.totalErrors}"
        )

        return True

    def _loggingLoop(self) -> None:
        """
        Main logging loop that runs in background thread.

        Polls parameters at configured interval, logs readings to database,
        and handles errors gracefully.
        """
        with self._lock:
            self._state = LoggingState.RUNNING

        while not self._stopEvent.is_set():
            cycleStartTime = time.perf_counter()

            try:
                self._pollCycle()
            except Exception as e:
                logger.error(f"Error in logging cycle: {e}")
                self._stats.totalErrors += 1

            # Calculate cycle duration
            cycleEndTime = time.perf_counter()
            cycleDurationMs = (cycleEndTime - cycleStartTime) * 1000
            self._cycleTimes.append(cycleDurationMs)
            self._stats.lastCycleTimeMs = cycleDurationMs

            # Update average (keep last 100 cycles for average)
            if len(self._cycleTimes) > 100:
                self._cycleTimes = self._cycleTimes[-100:]
            self._stats.averageCycleTimeMs = sum(self._cycleTimes) / len(self._cycleTimes)

            self._stats.totalCycles += 1

            # Callback for cycle complete
            if self._onCycleComplete:
                try:
                    self._onCycleComplete(self._stats.totalCycles)
                except Exception as e:
                    logger.warning(f"onCycleComplete callback error: {e}")

            # Calculate sleep time to maintain polling interval
            sleepTimeMs = self._pollingIntervalMs - cycleDurationMs
            if sleepTimeMs > 0:
                # Sleep in small intervals to allow for quick stop
                sleepTimeSec = sleepTimeMs / 1000.0
                sleepInterval = min(sleepTimeSec, 0.1)  # Check every 100ms max

                remaining = sleepTimeSec
                while remaining > 0 and not self._stopEvent.is_set():
                    time.sleep(min(remaining, sleepInterval))
                    remaining -= sleepInterval

    def _pollCycle(self) -> None:
        """
        Execute one polling cycle - read all configured parameters.

        Logs each parameter and handles errors per-parameter without
        stopping the entire cycle.
        """
        for paramName in self._parameters:
            if self._stopEvent.is_set():
                break

            try:
                # Query the parameter - use high-precision timestamp
                timestamp = datetime.now()  # Includes microseconds

                reading = self._queryParameterSafe(paramName)

                if reading is not None:
                    # Override timestamp for millisecond precision
                    reading.timestamp = timestamp

                    # Log to database
                    self._logReadingSafe(reading)

                    # Update stats
                    self._stats.totalReadings += 1
                    self._stats.parametersLogged[paramName] = \
                        self._stats.parametersLogged.get(paramName, 0) + 1

                    # Callback
                    if self._onReading:
                        try:
                            self._onReading(reading)
                        except Exception as e:
                            logger.warning(f"onReading callback error: {e}")

            except Exception as e:
                self._handleParameterError(paramName, e)

    def _queryParameterSafe(self, parameterName: str) -> Optional[LoggedReading]:
        """
        Query a parameter safely, catching and handling errors.

        Args:
            parameterName: Name of the parameter to query

        Returns:
            LoggedReading if successful, None if parameter unavailable
        """
        try:
            return self._dataLogger.queryParameter(parameterName)
        except ParameterNotSupportedError:
            # Parameter not supported by vehicle - log once and skip
            logger.debug(f"Parameter '{parameterName}' not supported - skipping")
            return None
        except ParameterReadError as e:
            # Null response - parameter may be temporarily unavailable
            logger.debug(f"Parameter '{parameterName}' returned null: {e}")
            return None

    def _logReadingSafe(self, reading: LoggedReading) -> bool:
        """
        Log a reading safely, catching database errors.

        Args:
            reading: LoggedReading to store

        Returns:
            True if logged successfully
        """
        try:
            self._dataLogger.logReading(reading)
            self._stats.totalLogged += 1
            return True
        except Exception as e:
            logger.warning(f"Failed to log reading: {e}")
            self._stats.totalErrors += 1
            return False

    def _handleParameterError(self, paramName: str, error: Exception) -> None:
        """
        Handle an error reading a parameter.

        Args:
            paramName: Name of the parameter that failed
            error: The exception that occurred
        """
        self._stats.totalErrors += 1
        self._stats.errorsByParameter[paramName] = \
            self._stats.errorsByParameter.get(paramName, 0) + 1

        logger.debug(f"Error reading parameter '{paramName}': {error}")

        # Callback
        if self._onError:
            try:
                self._onError(paramName, error)
            except Exception as e:
                logger.warning(f"onError callback error: {e}")

    def getStats(self) -> LoggingStats:
        """
        Get current logging statistics.

        Returns:
            LoggingStats with current session statistics
        """
        return self._stats

    def getParameters(self) -> List[str]:
        """
        Get list of parameters being logged.

        Returns:
            List of parameter names
        """
        return list(self._parameters)

    def getPollingIntervalMs(self) -> int:
        """
        Get current polling interval.

        Returns:
            Polling interval in milliseconds
        """
        return self._pollingIntervalMs


# ================================================================================
# Helper Functions
# ================================================================================

def queryParameter(connection: Any, parameterName: str) -> LoggedReading:
    """
    Query a parameter from an OBD-II connection.

    Standalone helper function for simple one-off queries.

    Args:
        connection: ObdConnection instance
        parameterName: Name of the OBD-II parameter

    Returns:
        LoggedReading with the parameter value

    Example:
        reading = queryParameter(conn, 'RPM')
        print(f"RPM: {reading.value}")
    """
    # Create a temporary logger without database
    tempLogger = ObdDataLogger(connection, None)
    return tempLogger.queryParameter(parameterName)


def logReading(database: Any, reading: LoggedReading) -> bool:
    """
    Log a reading to the database.

    Standalone helper function for simple logging operations.

    Args:
        database: ObdDatabase instance
        reading: LoggedReading to store

    Returns:
        True if logged successfully

    Example:
        reading = LoggedReading('RPM', 3500.0, 'rpm', datetime.now())
        logReading(db, reading)
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO realtime_data
                (timestamp, parameter_name, value, unit, profile_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    reading.timestamp,
                    reading.parameterName,
                    reading.value,
                    reading.unit,
                    reading.profileId
                )
            )
        return True
    except Exception as e:
        logger.error(f"Failed to log reading: {e}")
        raise DataLoggerError(f"Failed to log reading: {e}")


def verifyDataPersistence(database: Any, parameterName: str) -> bool:
    """
    Verify that data for a parameter exists in the database.

    Useful for testing that data persists across application restarts.

    Args:
        database: ObdDatabase instance
        parameterName: Name of the parameter to check

    Returns:
        True if data exists, False otherwise

    Example:
        exists = verifyDataPersistence(db, 'RPM')
        if exists:
            print("RPM data found in database")
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM realtime_data
                WHERE parameter_name = ?
                """,
                (parameterName,)
            )
            count = cursor.fetchone()[0]
            return count > 0
    except Exception as e:
        logger.error(f"Failed to verify data persistence: {e}")
        return False


def createDataLoggerFromConfig(
    config: Dict[str, Any],
    connection: Any,
    database: Any
) -> ObdDataLogger:
    """
    Create an ObdDataLogger from configuration.

    Args:
        config: Configuration dictionary with 'profiles' section
        connection: ObdConnection instance
        database: ObdDatabase instance

    Returns:
        Configured ObdDataLogger instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)
        logger = createDataLoggerFromConfig(config, conn, db)
    """
    # Get active profile from config
    profilesConfig = config.get('profiles', {})
    activeProfile = profilesConfig.get('activeProfile', None)

    return ObdDataLogger(connection, database, profileId=activeProfile)


def createRealtimeLoggerFromConfig(
    config: Dict[str, Any],
    connection: Any,
    database: Any
) -> RealtimeDataLogger:
    """
    Create a RealtimeDataLogger from configuration.

    Args:
        config: Configuration dictionary with 'realtimeData' and 'profiles' sections
        connection: ObdConnection instance
        database: ObdDatabase instance

    Returns:
        Configured RealtimeDataLogger instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)
        conn.connect()

        rtLogger = createRealtimeLoggerFromConfig(config, conn, db)
        rtLogger.start()
    """
    # Get active profile from config
    profilesConfig = config.get('profiles', {})
    activeProfile = profilesConfig.get('activeProfile', None)

    return RealtimeDataLogger(config, connection, database, profileId=activeProfile)
