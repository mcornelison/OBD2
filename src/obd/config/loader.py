################################################################################
# File Name: loader.py
# Purpose/Description: OBD-II configuration loading and validation
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation (US-003)
# ================================================================================
################################################################################

"""
OBD-II Configuration loader module.

Provides configuration loading and validation specific to the Eclipse OBD-II
Performance Monitoring System. Validates required fields, applies defaults,
and ensures graceful failure with clear error messages.

Usage:
    from src.obd.config.loader import loadObdConfig, OBD_DEFAULTS

    try:
        config = loadObdConfig('path/to/obd_config.json')
    except ObdConfigError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
"""

import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Add parent directory to path for imports
srcPath = Path(__file__).parent.parent.parent
if str(srcPath) not in sys.path:
    sys.path.insert(0, str(srcPath))

from common.config_validator import ConfigValidator, ConfigValidationError
from common.secrets_loader import resolveSecrets, loadEnvFile

from .exceptions import ObdConfigError

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Required configuration fields for OBD-II system
OBD_REQUIRED_FIELDS: List[str] = [
    'database.path',
    'bluetooth.macAddress',
    'display.mode',
    'realtimeData.parameters',
]

# Valid display modes
VALID_DISPLAY_MODES = ['headless', 'minimal', 'developer']

# Default values for optional OBD-II settings
OBD_DEFAULTS: Dict[str, Any] = {
    # Application
    'application.name': 'Eclipse OBD-II Performance Monitor',
    'application.version': '1.0.0',
    'application.environment': 'production',

    # Database
    'database.walMode': True,
    'database.vacuumOnStartup': False,
    'database.backupOnShutdown': True,

    # Bluetooth
    'bluetooth.retryDelays': [1, 2, 4, 8, 16],
    'bluetooth.maxRetries': 5,
    'bluetooth.connectionTimeoutSeconds': 30,

    # VIN Decoder
    'vinDecoder.enabled': True,
    'vinDecoder.apiBaseUrl': 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues',
    'vinDecoder.apiTimeoutSeconds': 30,
    'vinDecoder.cacheVinData': True,

    # Display
    'display.width': 240,
    'display.height': 240,
    'display.refreshRateMs': 1000,
    'display.brightness': 100,
    'display.showOnStartup': True,

    # Auto-start
    'autoStart.enabled': True,
    'autoStart.startDelaySeconds': 5,
    'autoStart.maxRestartAttempts': 5,
    'autoStart.restartDelaySeconds': 10,

    # Static data
    'staticData.queryOnFirstConnection': True,

    # Realtime data
    'realtimeData.pollingIntervalMs': 1000,

    # Analysis
    'analysis.triggerAfterDrive': True,
    'analysis.driveStartRpmThreshold': 500,
    'analysis.driveStartDurationSeconds': 10,
    'analysis.driveEndRpmThreshold': 0,
    'analysis.driveEndDurationSeconds': 60,

    # AI Analysis
    'aiAnalysis.enabled': False,
    'aiAnalysis.model': 'gemma2:2b',
    'aiAnalysis.ollamaBaseUrl': 'http://localhost:11434',
    'aiAnalysis.maxAnalysesPerDrive': 1,

    # Profiles
    'profiles.activeProfile': 'daily',

    # Calibration
    'calibration.mode': False,
    'calibration.logAllParameters': True,
    'calibration.sessionNotesRequired': False,

    # Alerts
    'alerts.enabled': True,
    'alerts.cooldownSeconds': 30,
    'alerts.visualAlerts': True,
    'alerts.audioAlerts': False,
    'alerts.logAlerts': True,

    # Data retention
    'dataRetention.realtimeDataDays': 7,
    'dataRetention.statisticsRetentionDays': -1,
    'dataRetention.vacuumAfterCleanup': True,
    'dataRetention.cleanupTimeHour': 3,

    # Battery monitoring
    'batteryMonitoring.enabled': False,
    'batteryMonitoring.warningVoltage': 11.5,
    'batteryMonitoring.criticalVoltage': 11.0,
    'batteryMonitoring.pollingIntervalSeconds': 60,

    # Logging
    'logging.level': 'INFO',
    'logging.format': '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    'logging.maskPII': True,

    # Simulator
    'simulator.enabled': False,
    'simulator.profilePath': './src/obd/simulator/profiles/default.json',
    'simulator.scenarioPath': '',
    'simulator.connectionDelaySeconds': 2,
    'simulator.updateIntervalMs': 100,
    'simulator.failures.connectionDrop.enabled': False,
    'simulator.failures.connectionDrop.probability': 0.0,
    'simulator.failures.connectionDrop.durationSeconds': 5,
    'simulator.failures.sensorFailure.enabled': False,
    'simulator.failures.sensorFailure.sensors': [],
    'simulator.failures.sensorFailure.probability': 0.0,
    'simulator.failures.intermittentSensor.enabled': False,
    'simulator.failures.intermittentSensor.sensors': [],
    'simulator.failures.intermittentSensor.probability': 0.1,
    'simulator.failures.outOfRange.enabled': False,
    'simulator.failures.outOfRange.sensors': [],
    'simulator.failures.outOfRange.multiplier': 2.0,
    'simulator.failures.dtcCodes.enabled': False,
    'simulator.failures.dtcCodes.codes': [],
}


# =============================================================================
# Public API
# =============================================================================

def loadObdConfig(
    configPath: str,
    envFilePath: Optional[str] = None
) -> Dict[str, Any]:
    """
    Load and validate OBD-II configuration from file.

    Performs the following operations:
    1. Load environment variables from .env file (if provided)
    2. Load configuration JSON file
    3. Resolve secret placeholders (${VAR} syntax)
    4. Validate required fields
    5. Apply default values
    6. Validate field types and values

    Args:
        configPath: Path to the OBD configuration JSON file
        envFilePath: Optional path to .env file for secrets

    Returns:
        Validated configuration dictionary with defaults applied

    Raises:
        ObdConfigError: If configuration file cannot be loaded or validation fails
    """
    logger.info(f"Loading OBD configuration from: {configPath}")

    # Load environment variables if .env file provided
    if envFilePath and os.path.exists(envFilePath):
        logger.debug(f"Loading environment from: {envFilePath}")
        loadEnvFile(envFilePath)

    # Load configuration file
    config = _loadConfigFile(configPath)

    # Resolve secret placeholders
    config = resolveSecrets(config)

    # Validate configuration
    config = validateObdConfig(config)

    logger.info("OBD configuration loaded and validated successfully")
    return config


def validateObdConfig(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate OBD-II configuration and apply defaults.

    Args:
        config: Raw configuration dictionary

    Returns:
        Validated configuration with defaults applied

    Raises:
        ObdConfigError: If validation fails
    """
    # Use the ConfigValidator with OBD-specific settings
    validator = ConfigValidator(
        requiredKeys=OBD_REQUIRED_FIELDS,
        defaults=OBD_DEFAULTS
    )

    try:
        config = validator.validate(config)
    except ConfigValidationError as e:
        raise ObdConfigError(
            f"Configuration validation failed: {e}",
            missingFields=e.missingFields
        )

    # Perform OBD-specific validation
    _validateDisplayMode(config)
    _validateProfilesConfig(config)
    _validateRealtimeParameters(config)
    _validateAlertThresholds(config)
    _validateSimulatorConfig(config)

    return config


# =============================================================================
# Private Helpers
# =============================================================================

def _loadConfigFile(configPath: str) -> Dict[str, Any]:
    """
    Load configuration from JSON file.

    Args:
        configPath: Path to configuration file

    Returns:
        Configuration dictionary

    Raises:
        ObdConfigError: If file cannot be loaded or parsed
    """
    configPath = os.path.abspath(configPath)

    if not os.path.exists(configPath):
        raise ObdConfigError(
            f"Configuration file not found: {configPath}",
            missingFields=['configFile']
        )

    try:
        with open(configPath, 'r', encoding='utf-8') as f:
            config = json.load(f)
            logger.debug(f"Configuration file loaded: {configPath}")
            return config
    except json.JSONDecodeError as e:
        raise ObdConfigError(
            f"Invalid JSON in configuration file: {configPath}\n"
            f"Parse error: {e.msg} at line {e.lineno}, column {e.colno}",
            invalidFields=['configFile']
        )
    except IOError as e:
        raise ObdConfigError(
            f"Cannot read configuration file: {configPath}\nError: {e}",
            missingFields=['configFile']
        )


def _validateDisplayMode(config: Dict[str, Any]) -> None:
    """
    Validate display mode is one of the allowed values.

    Args:
        config: Configuration dictionary

    Raises:
        ObdConfigError: If display mode is invalid
    """
    displayMode = config.get('display', {}).get('mode', '')

    if displayMode not in VALID_DISPLAY_MODES:
        raise ObdConfigError(
            f"Invalid display mode: '{displayMode}'. "
            f"Must be one of: {', '.join(VALID_DISPLAY_MODES)}",
            invalidFields=['display.mode']
        )


def _validateProfilesConfig(config: Dict[str, Any]) -> None:
    """
    Validate profiles configuration.

    Args:
        config: Configuration dictionary

    Raises:
        ObdConfigError: If profiles config is invalid
    """
    profiles = config.get('profiles', {})
    activeProfile = profiles.get('activeProfile', '')
    availableProfiles = profiles.get('availableProfiles', [])

    # Check if at least one profile exists
    if not availableProfiles:
        # Create default 'daily' profile if none exist
        config['profiles']['availableProfiles'] = [{
            'id': 'daily',
            'name': 'Daily',
            'description': 'Default daily driving profile',
            'alertThresholds': {
                'rpmRedline': 6500,
                'coolantTempCritical': 110
            },
            'pollingIntervalMs': 1000
        }]
        availableProfiles = config['profiles']['availableProfiles']
        logger.info("Created default 'daily' profile")

    # Verify active profile exists
    profileIds = [p.get('id', '') for p in availableProfiles]
    if activeProfile and activeProfile not in profileIds:
        raise ObdConfigError(
            f"Active profile '{activeProfile}' not found in available profiles: "
            f"{', '.join(profileIds)}",
            invalidFields=['profiles.activeProfile']
        )

    # Validate each profile has required fields
    for i, profile in enumerate(availableProfiles):
        if 'id' not in profile:
            raise ObdConfigError(
                f"Profile at index {i} missing required 'id' field",
                missingFields=[f'profiles.availableProfiles[{i}].id']
            )
        if 'name' not in profile:
            raise ObdConfigError(
                f"Profile '{profile.get('id', i)}' missing required 'name' field",
                missingFields=[f'profiles.availableProfiles[{i}].name']
            )


def _validateRealtimeParameters(config: Dict[str, Any]) -> None:
    """
    Validate realtime data parameters configuration.

    Args:
        config: Configuration dictionary

    Raises:
        ObdConfigError: If realtime parameters config is invalid
    """
    parameters = config.get('realtimeData', {}).get('parameters', [])

    if not parameters:
        raise ObdConfigError(
            "No realtime data parameters configured. "
            "At least one parameter must be defined.",
            missingFields=['realtimeData.parameters']
        )

    invalidParams = []
    for i, param in enumerate(parameters):
        if isinstance(param, dict):
            if 'name' not in param:
                invalidParams.append(f'realtimeData.parameters[{i}].name')
            if 'logData' not in param:
                # Set default for logData
                param['logData'] = False
        elif isinstance(param, str):
            # Convert string to dict format
            parameters[i] = {'name': param, 'logData': True, 'displayOnDashboard': False}
        else:
            invalidParams.append(f'realtimeData.parameters[{i}]')

    if invalidParams:
        raise ObdConfigError(
            f"Invalid realtime parameter configuration: {', '.join(invalidParams)}",
            invalidFields=invalidParams
        )


def _validateAlertThresholds(config: Dict[str, Any]) -> None:
    """
    Validate alert threshold values are reasonable.

    Args:
        config: Configuration dictionary

    Raises:
        ObdConfigError: If alert thresholds are invalid
    """
    profiles = config.get('profiles', {}).get('availableProfiles', [])

    for profile in profiles:
        thresholds = profile.get('alertThresholds', {})
        profileId = profile.get('id', 'unknown')

        # Validate RPM redline (should be positive and reasonable)
        rpmRedline = thresholds.get('rpmRedline')
        if rpmRedline is not None:
            if not isinstance(rpmRedline, (int, float)) or rpmRedline <= 0:
                raise ObdConfigError(
                    f"Profile '{profileId}': rpmRedline must be a positive number",
                    invalidFields=[f'profiles.{profileId}.alertThresholds.rpmRedline']
                )
            if rpmRedline > 15000:
                logger.warning(
                    f"Profile '{profileId}': rpmRedline {rpmRedline} seems unusually high"
                )

        # Validate coolant temp (should be positive)
        coolantTemp = thresholds.get('coolantTempCritical')
        if coolantTemp is not None:
            if not isinstance(coolantTemp, (int, float)) or coolantTemp <= 0:
                raise ObdConfigError(
                    f"Profile '{profileId}': coolantTempCritical must be a positive number",
                    invalidFields=[f'profiles.{profileId}.alertThresholds.coolantTempCritical']
                )


def _validateSimulatorConfig(config: Dict[str, Any]) -> None:
    """
    Validate simulator configuration values.

    Validates that simulator settings have correct types and reasonable values.
    Does not require simulator section to exist (defaults will be applied).

    Args:
        config: Configuration dictionary

    Raises:
        ObdConfigError: If simulator configuration is invalid
    """
    simulator = config.get('simulator', {})

    # If simulator section doesn't exist, nothing to validate
    if not simulator:
        return

    invalidFields = []

    # Validate enabled is boolean
    enabled = simulator.get('enabled')
    if enabled is not None and not isinstance(enabled, bool):
        invalidFields.append('simulator.enabled')

    # Validate connectionDelaySeconds (must be non-negative number)
    connectionDelay = simulator.get('connectionDelaySeconds')
    if connectionDelay is not None:
        if not isinstance(connectionDelay, (int, float)) or connectionDelay < 0:
            invalidFields.append('simulator.connectionDelaySeconds')

    # Validate updateIntervalMs (must be positive integer)
    updateInterval = simulator.get('updateIntervalMs')
    if updateInterval is not None:
        if not isinstance(updateInterval, (int, float)) or updateInterval <= 0:
            invalidFields.append('simulator.updateIntervalMs')

    # Validate failures subsection
    failures = simulator.get('failures', {})
    if failures:
        # Validate connectionDrop
        connDrop = failures.get('connectionDrop', {})
        if connDrop:
            _validateFailureConfig(
                connDrop, 'simulator.failures.connectionDrop', invalidFields
            )
            durationSeconds = connDrop.get('durationSeconds')
            if durationSeconds is not None:
                if not isinstance(durationSeconds, (int, float)) or durationSeconds < 0:
                    invalidFields.append('simulator.failures.connectionDrop.durationSeconds')

        # Validate sensorFailure
        sensorFail = failures.get('sensorFailure', {})
        if sensorFail:
            _validateFailureConfig(
                sensorFail, 'simulator.failures.sensorFailure', invalidFields
            )
            sensors = sensorFail.get('sensors')
            if sensors is not None and not isinstance(sensors, list):
                invalidFields.append('simulator.failures.sensorFailure.sensors')

        # Validate intermittentSensor
        intermittent = failures.get('intermittentSensor', {})
        if intermittent:
            _validateFailureConfig(
                intermittent, 'simulator.failures.intermittentSensor', invalidFields
            )
            sensors = intermittent.get('sensors')
            if sensors is not None and not isinstance(sensors, list):
                invalidFields.append('simulator.failures.intermittentSensor.sensors')

        # Validate outOfRange
        outOfRange = failures.get('outOfRange', {})
        if outOfRange:
            enabled = outOfRange.get('enabled')
            if enabled is not None and not isinstance(enabled, bool):
                invalidFields.append('simulator.failures.outOfRange.enabled')
            sensors = outOfRange.get('sensors')
            if sensors is not None and not isinstance(sensors, list):
                invalidFields.append('simulator.failures.outOfRange.sensors')
            multiplier = outOfRange.get('multiplier')
            if multiplier is not None:
                if not isinstance(multiplier, (int, float)) or multiplier <= 0:
                    invalidFields.append('simulator.failures.outOfRange.multiplier')

        # Validate dtcCodes
        dtcCodes = failures.get('dtcCodes', {})
        if dtcCodes:
            enabled = dtcCodes.get('enabled')
            if enabled is not None and not isinstance(enabled, bool):
                invalidFields.append('simulator.failures.dtcCodes.enabled')
            codes = dtcCodes.get('codes')
            if codes is not None and not isinstance(codes, list):
                invalidFields.append('simulator.failures.dtcCodes.codes')

    if invalidFields:
        raise ObdConfigError(
            f"Invalid simulator configuration: {', '.join(invalidFields)}. "
            f"Check that values have correct types (boolean for enabled, "
            f"positive numbers for intervals, arrays for sensor lists).",
            invalidFields=invalidFields
        )


def _validateFailureConfig(
    failureConfig: Dict[str, Any],
    prefix: str,
    invalidFields: List[str]
) -> None:
    """
    Validate a failure injection configuration section.

    Args:
        failureConfig: Failure configuration dictionary
        prefix: Config path prefix for error messages
        invalidFields: List to append invalid field paths to
    """
    enabled = failureConfig.get('enabled')
    if enabled is not None and not isinstance(enabled, bool):
        invalidFields.append(f'{prefix}.enabled')

    probability = failureConfig.get('probability')
    if probability is not None:
        if not isinstance(probability, (int, float)) or probability < 0.0 or probability > 1.0:
            invalidFields.append(f'{prefix}.probability')
