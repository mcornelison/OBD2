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

# Try to import Adafruit display adapter - may fail on non-Raspberry Pi platforms
try:
    from .adafruit_display import (
        AdafruitDisplayAdapter,
        Colors,
        DisplayAdapterError,
        DisplayInitializationError as AdafruitDisplayInitializationError,
        DisplayRenderError,
        isDisplayHardwareAvailable,
        createAdafruitAdapter,
        DISPLAY_WIDTH,
        DISPLAY_HEIGHT,
    )
except (ImportError, NotImplementedError, RuntimeError):
    # Provide fallback implementations for non-Raspberry Pi platforms
    AdafruitDisplayAdapter = None  # type: ignore
    Colors = None  # type: ignore
    DisplayAdapterError = Exception  # type: ignore
    AdafruitDisplayInitializationError = Exception  # type: ignore
    DisplayRenderError = Exception  # type: ignore
    DISPLAY_WIDTH = 240
    DISPLAY_HEIGHT = 240

    def isDisplayHardwareAvailable() -> bool:
        return False

    def createAdafruitAdapter(config=None):
        return None

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

from .vin_decoder import (
    VinDecoder,
    VinDecodeResult,
    ApiCallResult,
    VinDecoderError,
    VinValidationError,
    VinApiError,
    VinApiTimeoutError,
    VinStorageError,
    createVinDecoderFromConfig,
    decodeVinOnFirstConnection,
    isVinDecoderEnabled,
    getVehicleInfo,
    validateVinFormat,
    NHTSA_API_BASE_URL,
    DEFAULT_API_TIMEOUT,
    NHTSA_FIELD_MAPPING,
)

from .statistics_engine import (
    StatisticsEngine,
    ParameterStatistics,
    AnalysisResult,
    AnalysisState,
    EngineStats,
    StatisticsError,
    StatisticsCalculationError,
    StatisticsStorageError,
    InsufficientDataError,
    calculateMean,
    calculateMode,
    calculateStandardDeviation,
    calculateOutlierBounds,
    calculateParameterStatistics,
    createStatisticsEngineFromConfig,
    calculateStatisticsForDrive,
    getStatisticsSummary,
)

from .profile_statistics import (
    ProfileStatisticsManager,
    ProfileComparison,
    ProfileComparisonResult,
    ParameterComparison,
    ProfileStatisticsReport,
    ProfileStatisticsError,
    createProfileStatisticsManager,
    compareProfiles,
    generateProfileReport,
    getProfileStatisticsSummary,
    getAllProfilesStatistics,
    SIGNIFICANCE_THRESHOLD,
)

from .alert_manager import (
    AlertManager,
    AlertThreshold,
    AlertEvent,
    AlertStats,
    AlertDirection,
    AlertState,
    AlertError,
    AlertConfigurationError,
    AlertDatabaseError,
    createAlertManagerFromConfig,
    getAlertThresholdsForProfile,
    isAlertingEnabled,
    getDefaultThresholds,
    checkThresholdValue,
    ALERT_TYPE_RPM_REDLINE,
    ALERT_TYPE_COOLANT_TEMP_CRITICAL,
    ALERT_TYPE_BOOST_PRESSURE_MAX,
    ALERT_TYPE_OIL_PRESSURE_LOW,
    DEFAULT_COOLDOWN_SECONDS,
)

from .drive_detector import (
    DriveDetector,
    DriveState,
    DetectorState,
    DriveSession,
    DetectorConfig,
    DetectorStats,
    DriveDetectorError,
    DriveDetectorConfigError,
    DriveDetectorStateError,
    createDriveDetectorFromConfig,
    isDriveDetectionEnabled,
    getDriveDetectionConfig,
    getDefaultDriveDetectionConfig,
    DEFAULT_DRIVE_START_RPM_THRESHOLD,
    DEFAULT_DRIVE_START_DURATION_SECONDS,
    DEFAULT_DRIVE_END_RPM_THRESHOLD,
    DEFAULT_DRIVE_END_DURATION_SECONDS,
    DRIVE_DETECTION_PARAMETERS,
)

from .simulator_integration import (
    SimulatorIntegration,
    IntegrationState,
    IntegrationConfig,
    IntegrationStats,
    SimulatorIntegrationError,
    SimulatorConfigurationError,
    SimulatorConnectionError,
    createIntegratedConnection,
    isSimulationModeActive,
    createSimulatorIntegrationFromConfig,
)

from .orchestrator import (
    ApplicationOrchestrator,
    OrchestratorError,
    ComponentInitializationError,
    ComponentStartError,
    ComponentStopError,
    createOrchestratorFromConfig,
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
    # Adafruit Display Adapter
    'AdafruitDisplayAdapter',
    'Colors',
    'DisplayAdapterError',
    'AdafruitDisplayInitializationError',
    'DisplayRenderError',
    'isDisplayHardwareAvailable',
    'createAdafruitAdapter',
    'DISPLAY_WIDTH',
    'DISPLAY_HEIGHT',
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
    # VIN Decoder
    'VinDecoder',
    'VinDecodeResult',
    'ApiCallResult',
    'VinDecoderError',
    'VinValidationError',
    'VinApiError',
    'VinApiTimeoutError',
    'VinStorageError',
    'createVinDecoderFromConfig',
    'decodeVinOnFirstConnection',
    'isVinDecoderEnabled',
    'getVehicleInfo',
    'validateVinFormat',
    'NHTSA_API_BASE_URL',
    'DEFAULT_API_TIMEOUT',
    'NHTSA_FIELD_MAPPING',
    # Statistics Engine
    'StatisticsEngine',
    'ParameterStatistics',
    'AnalysisResult',
    'AnalysisState',
    'EngineStats',
    'StatisticsError',
    'StatisticsCalculationError',
    'StatisticsStorageError',
    'InsufficientDataError',
    'calculateMean',
    'calculateMode',
    'calculateStandardDeviation',
    'calculateOutlierBounds',
    'calculateParameterStatistics',
    'createStatisticsEngineFromConfig',
    'calculateStatisticsForDrive',
    'getStatisticsSummary',
    # Alert Manager
    'AlertManager',
    'AlertThreshold',
    'AlertEvent',
    'AlertStats',
    'AlertDirection',
    'AlertState',
    'AlertError',
    'AlertConfigurationError',
    'AlertDatabaseError',
    'createAlertManagerFromConfig',
    'getAlertThresholdsForProfile',
    'isAlertingEnabled',
    'getDefaultThresholds',
    'checkThresholdValue',
    'ALERT_TYPE_RPM_REDLINE',
    'ALERT_TYPE_COOLANT_TEMP_CRITICAL',
    'ALERT_TYPE_BOOST_PRESSURE_MAX',
    'ALERT_TYPE_OIL_PRESSURE_LOW',
    'DEFAULT_COOLDOWN_SECONDS',
    # Drive Detector
    'DriveDetector',
    'DriveState',
    'DetectorState',
    'DriveSession',
    'DetectorConfig',
    'DetectorStats',
    'DriveDetectorError',
    'DriveDetectorConfigError',
    'DriveDetectorStateError',
    'createDriveDetectorFromConfig',
    'isDriveDetectionEnabled',
    'getDriveDetectionConfig',
    'getDefaultDriveDetectionConfig',
    'DEFAULT_DRIVE_START_RPM_THRESHOLD',
    'DEFAULT_DRIVE_START_DURATION_SECONDS',
    'DEFAULT_DRIVE_END_RPM_THRESHOLD',
    'DEFAULT_DRIVE_END_DURATION_SECONDS',
    'DRIVE_DETECTION_PARAMETERS',
    # Profile Statistics
    'ProfileStatisticsManager',
    'ProfileComparison',
    'ProfileComparisonResult',
    'ParameterComparison',
    'ProfileStatisticsReport',
    'ProfileStatisticsError',
    'createProfileStatisticsManager',
    'compareProfiles',
    'generateProfileReport',
    'getProfileStatisticsSummary',
    'getAllProfilesStatistics',
    'SIGNIFICANCE_THRESHOLD',
    # Simulator Integration
    'SimulatorIntegration',
    'IntegrationState',
    'IntegrationConfig',
    'IntegrationStats',
    'SimulatorIntegrationError',
    'SimulatorConfigurationError',
    'SimulatorConnectionError',
    'createIntegratedConnection',
    'isSimulationModeActive',
    'createSimulatorIntegrationFromConfig',
    # Application Orchestrator
    'ApplicationOrchestrator',
    'OrchestratorError',
    'ComponentInitializationError',
    'ComponentStartError',
    'ComponentStopError',
    'createOrchestratorFromConfig',
]
