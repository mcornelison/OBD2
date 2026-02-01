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
# 2026-01-22    | Ralph Agent  | US-007 - Refactored to use data subpackage modules
# ================================================================================
################################################################################

"""
OBD-II data logging module for the Eclipse Performance Monitoring System.

This module re-exports from the data subpackage for backward compatibility.
New code should import directly from src.obd.data.

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

# Re-export all public symbols from the data subpackage for backward compatibility
from .data import (
    # Types
    LoggingState,
    LoggedReading,
    LoggingStats,
    # Exceptions
    DataLoggerError,
    ParameterNotSupportedError,
    ParameterReadError,
    # Classes
    ObdDataLogger,
    RealtimeDataLogger,
    # Helper functions
    queryParameter,
    logReading,
    verifyDataPersistence,
    createDataLoggerFromConfig,
    createRealtimeLoggerFromConfig,
)

__all__ = [
    # Types
    'LoggingState',
    'LoggedReading',
    'LoggingStats',
    # Exceptions
    'DataLoggerError',
    'ParameterNotSupportedError',
    'ParameterReadError',
    # Classes
    'ObdDataLogger',
    'RealtimeDataLogger',
    # Helper functions
    'queryParameter',
    'logReading',
    'verifyDataPersistence',
    'createDataLoggerFromConfig',
    'createRealtimeLoggerFromConfig',
]
