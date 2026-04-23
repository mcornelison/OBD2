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
# 2026-04-19    | Rex (US-203) | TD-027 sweep: logReading() routes timestamp
#                               through utcIsoNow at the DB-write boundary.
# 2026-04-21    | Rex (US-212) | logReading() accepts a dataSource keyword
#                               so non-live-OBD callers (fixture seeders,
#                               replay tools) tag rows explicitly instead
#                               of silently inheriting the schema DEFAULT.
#                               Factory helpers thread dataSource through
#                               to ObdDataLogger / RealtimeDataLogger.
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
from typing import Any

from common.time.helper import utcIsoNow

from ..data_source import DATA_SOURCE_DEFAULT, DATA_SOURCE_VALUES
from ..drive_id import getCurrentDriveId
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


def logReading(
    database: Any,
    reading: LoggedReading,
    dataSource: str = DATA_SOURCE_DEFAULT,
) -> bool:
    """
    Log a reading to the database.

    Standalone helper function for simple logging operations.  Live-OBD
    callers (the Pi collector) should omit ``dataSource`` and inherit
    the ``'real'`` default.  Non-live callers (fixture seeders, replay
    harnesses, developer scripts) MUST pass ``dataSource`` explicitly
    so rows are tagged correctly at the call site rather than silently
    defaulting to ``'real'`` (see US-212).

    Args:
        database: ObdDatabase instance.
        reading: LoggedReading to store.
        dataSource: Origin tag for the row; must be one of
            :data:`DATA_SOURCE_VALUES`.  Defaults to
            :data:`DATA_SOURCE_DEFAULT` (``'real'``) to match the
            live-OBD collector path.

    Returns:
        True if logged successfully.

    Raises:
        ValueError: If ``dataSource`` is not a known enum value.

    Example:
        reading = LoggedReading('RPM', 3500.0, 'rpm', datetime.now())
        logReading(db, reading)                       # live-OBD path
        logReading(db, reading, dataSource='fixture') # regression seed
    """
    if dataSource not in DATA_SOURCE_VALUES:
        raise ValueError(
            f"invalid data_source {dataSource!r}; "
            f"must be one of {DATA_SOURCE_VALUES}"
        )
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            # TD-027 / US-203: canonical ISO-8601 UTC via the shared helper.
            # reading.timestamp may be naive local-time; capture rows must be
            # canonical UTC so time-window queries (US-195 / US-197) line up.
            # US-200: stamp the active drive_id (or NULL if no drive).
            # US-212: pass dataSource explicitly instead of inheriting the
            # schema DEFAULT so callers cannot accidentally mis-tag.
            cursor.execute(
                """
                INSERT INTO realtime_data
                (timestamp, parameter_name, value, unit, profile_id,
                 drive_id, data_source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utcIsoNow(),
                    reading.parameterName,
                    reading.value,
                    reading.unit,
                    reading.profileId,
                    getCurrentDriveId(),
                    dataSource,
                )
            )
        return True
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Failed to log reading: {e}")
        raise DataLoggerError(f"Failed to log reading: {e}") from e


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
    config: dict[str, Any],
    connection: Any,
    database: Any,
    dataSource: str | None = None,
) -> ObdDataLogger:
    """
    Create an ObdDataLogger from configuration.

    Args:
        config: Configuration dictionary with 'profiles' section.
        connection: ObdConnection instance.
        database: ObdDatabase instance.
        dataSource: Optional origin tag forwarded to ``ObdDataLogger``.
            When omitted the logger derives the tag from
            ``connection.isSimulated`` (US-212).

    Returns:
        Configured ObdDataLogger instance.

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)
        logger = createDataLoggerFromConfig(config, conn, db)
    """
    # Get active profile from config
    profilesConfig = config.get('pi', {}).get('profiles', {})
    activeProfile = profilesConfig.get('activeProfile', None)

    return ObdDataLogger(
        connection, database, profileId=activeProfile, dataSource=dataSource,
    )


def createRealtimeLoggerFromConfig(
    config: dict[str, Any],
    connection: Any,
    database: Any,
    dataSource: str | None = None,
) -> RealtimeDataLogger:
    """
    Create a RealtimeDataLogger from configuration.

    Args:
        config: Configuration dictionary with 'realtimeData' and
            'profiles' sections.
        connection: ObdConnection instance.
        database: ObdDatabase instance.
        dataSource: Optional origin tag forwarded to the inner
            ``ObdDataLogger``.  When omitted the tag is derived from
            ``connection.isSimulated`` (US-212).

    Returns:
        Configured RealtimeDataLogger instance.

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)
        conn.connect()

        rtLogger = createRealtimeLoggerFromConfig(config, conn, db)
        rtLogger.start()
    """
    # Get active profile from config
    profilesConfig = config.get('pi', {}).get('profiles', {})
    activeProfile = profilesConfig.get('activeProfile', None)

    return RealtimeDataLogger(
        config, connection, database,
        profileId=activeProfile, dataSource=dataSource,
    )
