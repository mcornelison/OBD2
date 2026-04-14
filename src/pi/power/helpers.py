################################################################################
# File Name: helpers.py
# Purpose/Description: Power monitoring configuration helpers and factory functions
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-012
# ================================================================================
################################################################################
"""
Power monitoring configuration helpers and factory functions.

This module provides helper functions for working with power monitoring:
- Factory functions to create monitors from configuration
- Configuration extraction functions
- Enabled checks

Usage:
    from power.helpers import (
        createBatteryMonitorFromConfig,
        createPowerMonitorFromConfig,
        isPowerMonitoringEnabled,
        isBatteryMonitoringEnabled,
    )

    # Create monitors from config
    batteryMonitor = createBatteryMonitorFromConfig(config, db, display, shutdown)
    powerMonitor = createPowerMonitorFromConfig(config, db, display, batteryMonitor)
"""

import logging
from typing import Any

from .battery import BatteryMonitor
from .power import PowerMonitor
from .types import (
    DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS,
    DEFAULT_CRITICAL_VOLTAGE,
    DEFAULT_DISPLAY_DIM_PERCENTAGE,
    DEFAULT_POLLING_INTERVAL_SECONDS,
    DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS,
    DEFAULT_WARNING_VOLTAGE,
)

logger = logging.getLogger(__name__)


# ================================================================================
# Battery Monitor Helpers
# ================================================================================

def createBatteryMonitorFromConfig(
    config: dict[str, Any],
    database: Any | None = None,
    displayManager: Any | None = None,
    shutdownManager: Any | None = None,
) -> BatteryMonitor:
    """
    Create a BatteryMonitor from configuration.

    Args:
        config: Configuration dictionary with 'batteryMonitoring' section
        database: ObdDatabase instance (optional)
        displayManager: DisplayManager instance (optional)
        shutdownManager: ShutdownManager instance (optional)

    Returns:
        Configured BatteryMonitor instance
    """
    batteryConfig = config.get('batteryMonitoring', {})

    enabled = batteryConfig.get('enabled', False)
    warningVoltage = batteryConfig.get('warningVoltage', DEFAULT_WARNING_VOLTAGE)
    criticalVoltage = batteryConfig.get('criticalVoltage', DEFAULT_CRITICAL_VOLTAGE)
    pollingIntervalSeconds = batteryConfig.get(
        'pollingIntervalSeconds', DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS
    )

    monitor = BatteryMonitor(
        database=database,
        displayManager=displayManager,
        shutdownManager=shutdownManager,
        warningVoltage=warningVoltage,
        criticalVoltage=criticalVoltage,
        pollingIntervalSeconds=pollingIntervalSeconds,
        enabled=enabled,
    )

    logger.info(
        f"BatteryMonitor created from config | enabled={enabled}, "
        f"warning={warningVoltage}V, critical={criticalVoltage}V, "
        f"interval={pollingIntervalSeconds}s"
    )

    return monitor


def getBatteryMonitoringConfig(config: dict[str, Any]) -> dict[str, Any]:
    """
    Get battery monitoring configuration section.

    Args:
        config: Configuration dictionary

    Returns:
        Battery monitoring configuration section
    """
    return config.get('batteryMonitoring', {})


def isBatteryMonitoringEnabled(config: dict[str, Any]) -> bool:
    """
    Check if battery monitoring is enabled in config.

    Args:
        config: Configuration dictionary

    Returns:
        True if battery monitoring is enabled
    """
    return config.get('batteryMonitoring', {}).get('enabled', False)


def getDefaultBatteryConfig() -> dict[str, Any]:
    """
    Get default battery monitoring configuration.

    Returns:
        Dictionary with default battery monitoring settings
    """
    return {
        'enabled': False,
        'warningVoltage': DEFAULT_WARNING_VOLTAGE,
        'criticalVoltage': DEFAULT_CRITICAL_VOLTAGE,
        'pollingIntervalSeconds': DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS,
    }


def validateBatteryConfig(config: dict[str, Any]) -> bool:
    """
    Validate battery monitoring configuration.

    Args:
        config: Configuration dictionary

    Returns:
        True if configuration is valid

    Raises:
        ValueError: If configuration is invalid
    """
    batteryConfig = config.get('batteryMonitoring', {})

    warningVoltage = batteryConfig.get('warningVoltage', DEFAULT_WARNING_VOLTAGE)
    criticalVoltage = batteryConfig.get('criticalVoltage', DEFAULT_CRITICAL_VOLTAGE)
    pollingIntervalSeconds = batteryConfig.get(
        'pollingIntervalSeconds', DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS
    )

    if warningVoltage <= 0:
        raise ValueError(f"Warning voltage must be positive: {warningVoltage}")

    if criticalVoltage <= 0:
        raise ValueError(f"Critical voltage must be positive: {criticalVoltage}")

    if criticalVoltage >= warningVoltage:
        raise ValueError(
            f"Critical voltage ({criticalVoltage}) must be less than "
            f"warning voltage ({warningVoltage})"
        )

    if pollingIntervalSeconds < 1:
        raise ValueError(
            f"Polling interval must be at least 1 second: {pollingIntervalSeconds}"
        )

    return True


# ================================================================================
# Power Monitor Helpers
# ================================================================================

def createPowerMonitorFromConfig(
    config: dict[str, Any],
    database: Any | None = None,
    displayManager: Any | None = None,
    batteryMonitor: Any | None = None,
) -> PowerMonitor:
    """
    Create a PowerMonitor from configuration.

    Args:
        config: Configuration dictionary with 'powerMonitoring' section
        database: ObdDatabase instance (optional)
        displayManager: DisplayManager instance (optional)
        batteryMonitor: BatteryMonitor instance (optional)

    Returns:
        Configured PowerMonitor instance
    """
    powerConfig = config.get('powerMonitoring', {})

    enabled = powerConfig.get('enabled', False)
    pollingIntervalSeconds = powerConfig.get(
        'pollingIntervalSeconds', DEFAULT_POLLING_INTERVAL_SECONDS
    )
    reducedPollingIntervalSeconds = powerConfig.get(
        'reducedPollingIntervalSeconds', DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS
    )
    displayDimPercentage = powerConfig.get(
        'displayDimPercentage', DEFAULT_DISPLAY_DIM_PERCENTAGE
    )

    monitor = PowerMonitor(
        database=database,
        displayManager=displayManager,
        batteryMonitor=batteryMonitor,
        pollingIntervalSeconds=pollingIntervalSeconds,
        reducedPollingIntervalSeconds=reducedPollingIntervalSeconds,
        displayDimPercentage=displayDimPercentage,
        enabled=enabled,
    )

    logger.info(
        f"PowerMonitor created from config | enabled={enabled}, "
        f"polling={pollingIntervalSeconds}s, reduced={reducedPollingIntervalSeconds}s, "
        f"dim={displayDimPercentage}%"
    )

    return monitor


def getPowerMonitoringConfig(config: dict[str, Any]) -> dict[str, Any]:
    """
    Get power monitoring configuration section.

    Args:
        config: Configuration dictionary

    Returns:
        Power monitoring configuration section
    """
    return config.get('powerMonitoring', {})


def isPowerMonitoringEnabled(config: dict[str, Any]) -> bool:
    """
    Check if power monitoring is enabled in config.

    Args:
        config: Configuration dictionary

    Returns:
        True if power monitoring is enabled
    """
    return config.get('powerMonitoring', {}).get('enabled', False)


def getDefaultPowerConfig() -> dict[str, Any]:
    """
    Get default power monitoring configuration.

    Returns:
        Dictionary with default power monitoring settings
    """
    return {
        'enabled': False,
        'pollingIntervalSeconds': DEFAULT_POLLING_INTERVAL_SECONDS,
        'reducedPollingIntervalSeconds': DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS,
        'displayDimPercentage': DEFAULT_DISPLAY_DIM_PERCENTAGE,
    }


def validatePowerConfig(config: dict[str, Any]) -> bool:
    """
    Validate power monitoring configuration.

    Args:
        config: Configuration dictionary

    Returns:
        True if configuration is valid

    Raises:
        ValueError: If configuration is invalid
    """
    powerConfig = config.get('powerMonitoring', {})

    pollingIntervalSeconds = powerConfig.get(
        'pollingIntervalSeconds', DEFAULT_POLLING_INTERVAL_SECONDS
    )
    reducedPollingIntervalSeconds = powerConfig.get(
        'reducedPollingIntervalSeconds', DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS
    )
    displayDimPercentage = powerConfig.get(
        'displayDimPercentage', DEFAULT_DISPLAY_DIM_PERCENTAGE
    )

    if pollingIntervalSeconds < 1:
        raise ValueError(
            f"Polling interval must be at least 1 second: {pollingIntervalSeconds}"
        )

    if reducedPollingIntervalSeconds < 1:
        raise ValueError(
            f"Reduced polling interval must be at least 1 second: {reducedPollingIntervalSeconds}"
        )

    if displayDimPercentage < 0 or displayDimPercentage > 100:
        raise ValueError(
            f"Display dim percentage must be 0-100: {displayDimPercentage}"
        )

    return True
