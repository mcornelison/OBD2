################################################################################
# File Name: helpers.py
# Purpose/Description: Helper functions for OBD-II data logging
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
Helper functions for OBD-II data logging.

Provides:
- Standalone query and logging functions
- Factory functions for creating loggers
- Data persistence verification

Usage:
    from src.obd.data.helpers import (
        queryParameter,
        logReading,
        verifyDataPersistence,
        createDataLoggerFromConfig,
        createRealtimeLoggerFromConfig
    )

    # Simple query
    reading = queryParameter(conn, 'RPM')
    print(f"RPM: {reading.value}")

    # Verify data exists
    exists = verifyDataPersistence(db, 'RPM')
"""

import logging
from typing import Any, Dict

from .exceptions import DataLoggerError
from .logger import ObdDataLogger
from .realtime import RealtimeDataLogger
from .types import LoggedReading

logger = logging.getLogger(__name__)


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
