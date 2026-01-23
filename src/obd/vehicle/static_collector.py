################################################################################
# File Name: static_collector.py
# Purpose/Description: Static data collection and storage on first connection
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Refactored from obd/static_data_collector.py (US-008)
# ================================================================================
################################################################################

"""
Static data collection module for the Eclipse OBD-II system.

Provides:
- Static parameter querying on first connection
- VIN-based existence checking to avoid duplicate queries
- Storage in static_data table with VIN as foreign key
- Graceful handling of unavailable parameters (stored as NULL)

Usage:
    from obd.vehicle import StaticDataCollector

    # Create collector with connection and database
    collector = StaticDataCollector(config, connection, database)

    # Collect static data (checks VIN first)
    result = collector.collectStaticData()

    # Or check and collect only if new
    if collector.shouldCollectStaticData():
        collector.collectStaticData()
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .types import StaticReading, CollectionResult
from .exceptions import VinNotAvailableError, StaticDataStorageError

logger = logging.getLogger(__name__)


# OBD library import with fallback
try:
    import obd as obdlib
    OBD_AVAILABLE = True
except ImportError:
    obdlib = None  # type: ignore
    OBD_AVAILABLE = False


# ================================================================================
# Static Data Collector Class
# ================================================================================

class StaticDataCollector:
    """
    Manages static OBD-II data collection and storage.

    Queries static parameters on first connection and stores them in the
    database with the VIN as a foreign key. Checks if VIN already exists
    to avoid duplicate queries.

    Features:
    - VIN-based existence checking
    - Graceful handling of unavailable parameters
    - Automatic vehicle_info record creation
    - Static data storage with proper foreign key relationships

    Attributes:
        config: Configuration dictionary
        connection: ObdConnection instance
        database: ObdDatabase instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)
        conn.connect()

        collector = StaticDataCollector(config, conn, db)

        # Check if we should collect
        if collector.shouldCollectStaticData():
            result = collector.collectStaticData()
            print(f"Collected {result.parametersCollected} parameters")
    """

    def __init__(
        self,
        config: Dict[str, Any],
        connection: Any,
        database: Any
    ):
        """
        Initialize the static data collector.

        Args:
            config: Configuration dictionary with 'staticData' section
            connection: ObdConnection instance for OBD-II communication
            database: ObdDatabase instance for data storage
        """
        self.config = config
        self.connection = connection
        self.database = database

        # Extract static data configuration
        staticDataConfig = config.get('staticData', {})
        self._parameters = staticDataConfig.get('parameters', [])
        self._queryOnFirstConnection = staticDataConfig.get('queryOnFirstConnection', True)

        # Cached VIN
        self._cachedVin: Optional[str] = None

    def shouldCollectStaticData(self) -> bool:
        """
        Check if static data should be collected.

        Returns True if:
        - queryOnFirstConnection is enabled in config
        - Connection is active
        - VIN can be read from vehicle
        - VIN does not already exist in database

        Returns:
            True if static data should be collected
        """
        # Check config flag
        if not self._queryOnFirstConnection:
            logger.debug("Static data collection disabled in config")
            return False

        # Check connection
        if not self.connection.isConnected():
            logger.debug("Not connected - cannot check for static data collection")
            return False

        # Try to get VIN
        try:
            vin = self._queryVin()
            if not vin:
                logger.warning("VIN not available - cannot collect static data")
                return False
        except Exception as e:
            logger.warning(f"Error querying VIN: {e}")
            return False

        # Check if VIN already exists
        if self.vinExistsInDatabase(vin):
            logger.info(f"VIN {vin} already exists in database - skipping static data collection")
            return False

        return True

    def vinExistsInDatabase(self, vin: str) -> bool:
        """
        Check if a VIN already exists in the database.

        Args:
            vin: Vehicle Identification Number to check

        Returns:
            True if VIN exists in vehicle_info or static_data tables
        """
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                # Check vehicle_info table first
                cursor.execute(
                    "SELECT COUNT(*) FROM vehicle_info WHERE vin = ?",
                    (vin,)
                )
                count = cursor.fetchone()[0]
                if count > 0:
                    return True

                # Also check static_data table for any existing records
                cursor.execute(
                    "SELECT COUNT(*) FROM static_data WHERE vin = ?",
                    (vin,)
                )
                count = cursor.fetchone()[0]
                return count > 0

        except Exception as e:
            logger.warning(f"Error checking VIN existence: {e}")
            return False

    def collectStaticData(self, forceCollect: bool = False) -> CollectionResult:
        """
        Collect and store static data from the vehicle.

        Queries all configured static parameters and stores them in the
        database. Creates vehicle_info record first, then stores each
        parameter in static_data table.

        Args:
            forceCollect: If True, collect even if VIN already exists

        Returns:
            CollectionResult with details about the collection

        Raises:
            StaticDataError: If not connected or VIN unavailable
        """
        result = CollectionResult()

        # Check connection
        if not self.connection.isConnected():
            result.errorMessage = "Not connected to OBD-II"
            return result

        # Query VIN first - required for foreign key
        try:
            vin = self._queryVin()
            if not vin:
                raise VinNotAvailableError("VIN not available from vehicle")
            result.vin = vin
            self._cachedVin = vin
        except Exception as e:
            result.errorMessage = f"Failed to read VIN: {e}"
            logger.error(result.errorMessage)
            return result

        # Check if VIN already exists (unless forcing)
        if not forceCollect and self.vinExistsInDatabase(vin):
            result.success = True
            result.wasSkipped = True
            logger.info(f"VIN {vin} already exists - static data collection skipped")
            return result

        logger.info(f"Collecting static data for VIN: {vin}")

        # Ensure vehicle_info record exists
        try:
            self._ensureVehicleInfoRecord(vin)
        except Exception as e:
            result.errorMessage = f"Failed to create vehicle_info record: {e}"
            logger.error(result.errorMessage)
            return result

        # Query and store each configured static parameter
        for paramName in self._parameters:
            reading = self._queryStaticParameter(paramName)
            result.readings.append(reading)

            if reading.value is not None:
                result.parametersCollected += 1
            else:
                result.parametersUnavailable += 1

            # Store in database
            try:
                self._storeStaticReading(vin, reading)
            except Exception as e:
                logger.warning(f"Failed to store parameter '{paramName}': {e}")

        result.success = True
        logger.info(
            f"Static data collection complete | "
            f"vin={vin} | "
            f"collected={result.parametersCollected} | "
            f"unavailable={result.parametersUnavailable}"
        )

        return result

    def getStaticDataForVin(self, vin: str) -> List[StaticReading]:
        """
        Get all stored static data for a VIN.

        Args:
            vin: Vehicle Identification Number

        Returns:
            List of StaticReading objects
        """
        readings = []

        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT parameter_name, value, unit, queried_at
                    FROM static_data
                    WHERE vin = ?
                    ORDER BY parameter_name
                    """,
                    (vin,)
                )

                for row in cursor.fetchall():
                    queriedAt = row[3]
                    if isinstance(queriedAt, str):
                        queriedAt = datetime.fromisoformat(queriedAt)

                    readings.append(StaticReading(
                        parameterName=row[0],
                        value=row[1],
                        unit=row[2],
                        queriedAt=queriedAt
                    ))

        except Exception as e:
            logger.error(f"Error reading static data for VIN {vin}: {e}")

        return readings

    def _queryVin(self) -> Optional[str]:
        """
        Query the VIN from the vehicle.

        Returns:
            VIN string or None if unavailable
        """
        # Return cached VIN if available
        if self._cachedVin:
            return self._cachedVin

        try:
            # Get VIN command
            cmd = self._getObdCommand('VIN')

            # Query VIN
            response = self.connection.obd.query(cmd)

            # Check if response is valid
            if response.is_null():
                logger.warning("VIN query returned null response")
                return None

            # Extract VIN value
            vin = self._extractStringValue(response)

            if vin:
                logger.debug(f"VIN queried successfully: {vin}")
                self._cachedVin = vin

            return vin

        except Exception as e:
            logger.warning(f"Error querying VIN: {e}")
            return None

    def _queryStaticParameter(self, parameterName: str) -> StaticReading:
        """
        Query a single static parameter from the vehicle.

        Args:
            parameterName: Name of the parameter to query

        Returns:
            StaticReading with value (or None if unavailable)
        """
        timestamp = datetime.now()

        try:
            # Get OBD command for this parameter
            cmd = self._getObdCommand(parameterName)

            # Query the parameter
            response = self.connection.obd.query(cmd)

            # Check if response is valid
            if response.is_null():
                logger.debug(f"Parameter '{parameterName}' returned null response")
                return StaticReading(
                    parameterName=parameterName,
                    value=None,
                    queriedAt=timestamp
                )

            # Extract value and unit
            value = self._extractStringValue(response)
            unit = self._extractUnit(response)

            logger.debug(f"Static parameter read | name={parameterName} | value={value}")

            return StaticReading(
                parameterName=parameterName,
                value=value,
                unit=unit,
                queriedAt=timestamp
            )

        except Exception as e:
            logger.warning(f"Error reading static parameter '{parameterName}': {e}")
            return StaticReading(
                parameterName=parameterName,
                value=None,
                queriedAt=timestamp
            )

    def _getObdCommand(self, parameterName: str) -> Any:
        """
        Get the OBD command object for a parameter name.

        Args:
            parameterName: Name of the parameter

        Returns:
            OBD command object or parameter name string
        """
        # Try to get command from python-OBD library
        if obdlib is not None and hasattr(obdlib, 'commands'):
            cmd = getattr(obdlib.commands, parameterName, None)
            if cmd is not None:
                return cmd

        # For mocked connections, return the parameter name string
        return parameterName

    def _extractStringValue(self, response: Any) -> Optional[str]:
        """
        Extract string value from OBD response.

        Handles various response types from python-OBD.

        Args:
            response: OBD response object

        Returns:
            String value or None
        """
        value = response.value

        if value is None:
            return None

        # Handle pint Quantity objects
        if hasattr(value, 'magnitude'):
            return str(value.magnitude)

        # Handle tuples (some commands return tuples)
        if isinstance(value, tuple):
            # Join non-empty values
            strValues = [str(v) for v in value if v is not None]
            return ', '.join(strValues) if strValues else None

        # Handle lists
        if isinstance(value, list):
            strValues = [str(v) for v in value if v is not None]
            return ', '.join(strValues) if strValues else None

        # Handle strings and other types
        return str(value)

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

    def _ensureVehicleInfoRecord(self, vin: str) -> None:
        """
        Ensure a vehicle_info record exists for the VIN.

        Creates the record if it doesn't exist.

        Args:
            vin: Vehicle Identification Number
        """
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                # Check if record exists
                cursor.execute(
                    "SELECT COUNT(*) FROM vehicle_info WHERE vin = ?",
                    (vin,)
                )
                count = cursor.fetchone()[0]

                if count == 0:
                    # Create new record
                    cursor.execute(
                        """
                        INSERT INTO vehicle_info (vin, created_at, updated_at)
                        VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        (vin,)
                    )
                    logger.info(f"Created vehicle_info record for VIN: {vin}")

        except Exception as e:
            raise StaticDataStorageError(
                f"Failed to create vehicle_info record: {e}",
                details={'vin': vin, 'error': str(e)}
            )

    def _storeStaticReading(self, vin: str, reading: StaticReading) -> None:
        """
        Store a static reading in the database.

        Args:
            vin: Vehicle Identification Number (foreign key)
            reading: StaticReading to store
        """
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO static_data
                    (vin, parameter_name, value, unit, queried_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        vin,
                        reading.parameterName,
                        reading.value,
                        reading.unit,
                        reading.queriedAt
                    )
                )

            logger.debug(
                f"Stored static reading | "
                f"vin={vin} | "
                f"param={reading.parameterName} | "
                f"value={reading.value}"
            )

        except Exception as e:
            raise StaticDataStorageError(
                f"Failed to store static reading: {e}",
                details={
                    'vin': vin,
                    'parameter': reading.parameterName,
                    'error': str(e)
                }
            )

    def getConfiguredParameters(self) -> List[str]:
        """
        Get list of configured static parameters.

        Returns:
            List of parameter names
        """
        return list(self._parameters)

    def getCachedVin(self) -> Optional[str]:
        """
        Get the cached VIN (if previously queried).

        Returns:
            Cached VIN or None
        """
        return self._cachedVin

    def clearCachedVin(self) -> None:
        """Clear the cached VIN."""
        self._cachedVin = None
