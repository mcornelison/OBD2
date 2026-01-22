################################################################################
# File Name: data_logger.py
# Purpose/Description: OBD-II data logging module for reading and storing parameters
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-004
# ================================================================================
################################################################################

"""
OBD-II data logging module for the Eclipse Performance Monitoring System.

Provides:
- Parameter querying via OBD-II connection
- Data logging to SQLite database with timestamps
- Data persistence verification
- Statistics tracking for logged readings

Usage:
    from obd.data_logger import ObdDataLogger, LoggedReading

    # Create logger with connection and database
    logger = ObdDataLogger(obdConnection, database, profileId='daily')

    # Query and log a parameter
    reading = logger.queryAndLogParameter('RPM')
    print(f"RPM: {reading.value} {reading.unit}")

    # Verify data persistence
    from obd.data_logger import verifyDataPersistence
    exists = verifyDataPersistence(database, 'RPM')
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

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
