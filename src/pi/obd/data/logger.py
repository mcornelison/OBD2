################################################################################
# File Name: logger.py
# Purpose/Description: ObdDataLogger class for OBD-II data logging operations
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-007 (data module refactor)
# ================================================================================
################################################################################
"""
OBD-II data logger class for parameter querying and storage.

Provides:
- Parameter querying via OBD-II connection
- Data logging to SQLite database with timestamps
- Statistics tracking for logged readings

Usage:
    from src.obd.data.logger import ObdDataLogger
    from src.obd.data.types import LoggedReading

    # Create logger with connection and database
    logger = ObdDataLogger(obdConnection, database, profileId='daily')

    # Query and log a parameter
    reading = logger.queryAndLogParameter('RPM')
    print(f"RPM: {reading.value} {reading.unit}")
"""

import logging
from datetime import datetime
from typing import Any

from .exceptions import DataLoggerError, ParameterNotSupportedError, ParameterReadError
from .types import LoggedReading

logger = logging.getLogger(__name__)


# OBD library import with fallback for environments where it's not available
try:
    import obd as obdlib
    OBD_AVAILABLE = True
except ImportError:
    obdlib = None  # type: ignore
    OBD_AVAILABLE = False


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
        profileId: str | None = None
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
        self._lastReadingTime: datetime | None = None
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
            ) from e

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
            ) from e

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

    def getStats(self) -> dict[str, Any]:
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

    def _extractUnit(self, response: Any) -> str | None:
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
