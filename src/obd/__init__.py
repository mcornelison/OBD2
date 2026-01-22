################################################################################
# File Name: __init__.py
# Purpose/Description: OBD module initialization
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation
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
    LoggingState,
    LoggingStats,
    RealtimeDataLogger,
    queryParameter,
    logReading,
    verifyDataPersistence,
    createDataLoggerFromConfig,
    createRealtimeLoggerFromConfig,
)

from .shutdown_manager import (
    ShutdownManager,
    createShutdownManager,
    installGlobalShutdownHandler,
)

from .static_data_collector import (
    StaticDataCollector,
    StaticReading,
    CollectionResult,
    StaticDataError,
    VinNotAvailableError,
    StaticDataStorageError,
    createStaticDataCollectorFromConfig,
    collectStaticDataOnFirstConnection,
    verifyStaticDataExists,
    getStaticDataCount,
)

from .service import (
    ServiceManager,
    ServiceConfig,
    ServiceStatus,
    ServiceError,
    ServiceInstallError,
    ServiceNotInstalledError,
    ServiceCommandError,
    createServiceManagerFromConfig,
    generateInstallScript,
    generateUninstallScript,
)

from .display_manager import (
    DisplayMode,
    DisplayManager,
    StatusInfo,
    AlertInfo,
    BaseDisplayDriver,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
    DeveloperDisplayDriver,
    DisplayError,
    DisplayInitializationError,
    DisplayOutputError,
    createDisplayManagerFromConfig,
    getDisplayModeFromConfig,
    isDisplayAvailable,
)

from .shutdown_command import (
    ShutdownCommand,
    ShutdownConfig,
    ShutdownResult,
    ShutdownState,
    ShutdownCommandError,
    ProcessNotFoundError,
    ShutdownTimeoutError,
    GpioNotAvailableError,
    GpioButtonTrigger,
    generateShutdownScript,
    generateGpioTriggerScript,
    createShutdownCommandFromConfig,
    isGpioAvailable,
    sendShutdownSignal,
    SHUTDOWN_REASON_USER_REQUEST,
    SHUTDOWN_REASON_GPIO_BUTTON,
    SHUTDOWN_REASON_LOW_BATTERY,
    SHUTDOWN_REASON_MAINTENANCE,
    SHUTDOWN_REASON_SYSTEM,
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
    'LoggingState',
    'LoggingStats',
    'RealtimeDataLogger',
    'queryParameter',
    'logReading',
    'verifyDataPersistence',
    'createDataLoggerFromConfig',
    'createRealtimeLoggerFromConfig',
    # Shutdown Manager
    'ShutdownManager',
    'createShutdownManager',
    'installGlobalShutdownHandler',
    # Static Data Collector
    'StaticDataCollector',
    'StaticReading',
    'CollectionResult',
    'StaticDataError',
    'VinNotAvailableError',
    'StaticDataStorageError',
    'createStaticDataCollectorFromConfig',
    'collectStaticDataOnFirstConnection',
    'verifyStaticDataExists',
    'getStaticDataCount',
    # Service Manager
    'ServiceManager',
    'ServiceConfig',
    'ServiceStatus',
    'ServiceError',
    'ServiceInstallError',
    'ServiceNotInstalledError',
    'ServiceCommandError',
    'createServiceManagerFromConfig',
    'generateInstallScript',
    'generateUninstallScript',
    # Display Manager
    'DisplayMode',
    'DisplayManager',
    'StatusInfo',
    'AlertInfo',
    'BaseDisplayDriver',
    'HeadlessDisplayDriver',
    'MinimalDisplayDriver',
    'DeveloperDisplayDriver',
    'DisplayError',
    'DisplayInitializationError',
    'DisplayOutputError',
    'createDisplayManagerFromConfig',
    'getDisplayModeFromConfig',
    'isDisplayAvailable',
    # Shutdown Command
    'ShutdownCommand',
    'ShutdownConfig',
    'ShutdownResult',
    'ShutdownState',
    'ShutdownCommandError',
    'ProcessNotFoundError',
    'ShutdownTimeoutError',
    'GpioNotAvailableError',
    'GpioButtonTrigger',
    'generateShutdownScript',
    'generateGpioTriggerScript',
    'createShutdownCommandFromConfig',
    'isGpioAvailable',
    'sendShutdownSignal',
    'SHUTDOWN_REASON_USER_REQUEST',
    'SHUTDOWN_REASON_GPIO_BUTTON',
    'SHUTDOWN_REASON_LOW_BATTERY',
    'SHUTDOWN_REASON_MAINTENANCE',
    'SHUTDOWN_REASON_SYSTEM',
]
