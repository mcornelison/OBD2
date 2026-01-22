################################################################################
# File Name: __init__.py
# Purpose/Description: OBD module initialization
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation
# ================================================================================
################################################################################

"""
OBD-II module for Eclipse Performance Monitoring System.

This module provides OBD-II specific functionality including:
- Configuration loading and validation
- Bluetooth OBD-II dongle connectivity
- Data acquisition and logging
- Statistical analysis
"""

from .obd_config_loader import (
    ObdConfigError,
    loadObdConfig,
    getConfigSection,
    getActiveProfile,
    getLoggedParameters,
    getStaticParameters,
    getRealtimeParameters,
    getPollingInterval,
    shouldQueryStaticOnFirstConnection,
)

from .obd_parameters import (
    ParameterInfo,
    STATIC_PARAMETERS,
    REALTIME_PARAMETERS,
    ALL_PARAMETERS,
    getParameterInfo,
    getAllParameterNames,
    getStaticParameterNames,
    getRealtimeParameterNames,
    isValidParameter,
    isStaticParameter,
    isRealtimeParameter,
    getParametersByCategory,
    getCategories,
    getDefaultRealtimeConfig,
    getDefaultStaticConfig,
)

from .database import (
    ObdDatabase,
    DatabaseError,
    DatabaseConnectionError,
    DatabaseInitializationError,
    createDatabaseFromConfig,
    initializeDatabase,
)

from .obd_connection import (
    ObdConnection,
    ObdConnectionError,
    ObdConnectionTimeoutError,
    ObdNotAvailableError,
    ObdConnectionFailedError,
    ConnectionState,
    ConnectionStatus,
    createConnectionFromConfig,
    isObdAvailable,
)

from .data_logger import (
    ObdDataLogger,
    DataLoggerError,
    ParameterNotSupportedError,
    ParameterReadError,
    LoggedReading,
    queryParameter,
    logReading,
    verifyDataPersistence,
    createDataLoggerFromConfig,
)

from .shutdown_manager import (
    ShutdownManager,
    createShutdownManager,
    installGlobalShutdownHandler,
)

__all__ = [
    # Config loader
    'ObdConfigError',
    'loadObdConfig',
    'getConfigSection',
    'getActiveProfile',
    'getLoggedParameters',
    'getStaticParameters',
    'getRealtimeParameters',
    'getPollingInterval',
    'shouldQueryStaticOnFirstConnection',
    # Parameter definitions
    'ParameterInfo',
    'STATIC_PARAMETERS',
    'REALTIME_PARAMETERS',
    'ALL_PARAMETERS',
    'getParameterInfo',
    'getAllParameterNames',
    'getStaticParameterNames',
    'getRealtimeParameterNames',
    'isValidParameter',
    'isStaticParameter',
    'isRealtimeParameter',
    'getParametersByCategory',
    'getCategories',
    'getDefaultRealtimeConfig',
    'getDefaultStaticConfig',
    # Database
    'ObdDatabase',
    'DatabaseError',
    'DatabaseConnectionError',
    'DatabaseInitializationError',
    'createDatabaseFromConfig',
    'initializeDatabase',
    # OBD Connection
    'ObdConnection',
    'ObdConnectionError',
    'ObdConnectionTimeoutError',
    'ObdNotAvailableError',
    'ObdConnectionFailedError',
    'ConnectionState',
    'ConnectionStatus',
    'createConnectionFromConfig',
    'isObdAvailable',
    # Data Logger
    'ObdDataLogger',
    'DataLoggerError',
    'ParameterNotSupportedError',
    'ParameterReadError',
    'LoggedReading',
    'queryParameter',
    'logReading',
    'verifyDataPersistence',
    'createDataLoggerFromConfig',
    # Shutdown Manager
    'ShutdownManager',
    'createShutdownManager',
    'installGlobalShutdownHandler',
]
