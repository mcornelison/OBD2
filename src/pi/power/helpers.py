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
# 2026-04-23    | Rex (US-223) | TD-031 close: dropped BatteryMonitor helpers
#                               (createBatteryMonitorFromConfig,
#                               getBatteryMonitoringConfig,
#                               isBatteryMonitoringEnabled,
#                               getDefaultBatteryConfig, validateBatteryConfig)
#                               with the BatteryMonitor class itself.
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
        createPowerMonitorFromConfig,
        isPowerMonitoringEnabled,
    )

    # Create monitor from config
    powerMonitor = createPowerMonitorFromConfig(config, db, display)
"""

import logging
from typing import Any

from .power import PowerMonitor
from .types import (
    DEFAULT_DISPLAY_DIM_PERCENTAGE,
    DEFAULT_POLLING_INTERVAL_SECONDS,
    DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)


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
        batteryMonitor: Optional hook for a battery-level monitor instance.
            Historical parameter kept for caller compatibility; BatteryMonitor
            itself was deleted in US-223 (TD-031).  PowerMonitor accepts any
            object exposing ``getState()`` / ``getStats()`` but no caller in
            production supplies one today.

    Returns:
        Configured PowerMonitor instance
    """
    powerConfig = config.get('pi', {}).get('powerMonitoring', {})

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
    return config.get('pi', {}).get('powerMonitoring', {})


def isPowerMonitoringEnabled(config: dict[str, Any]) -> bool:
    """
    Check if power monitoring is enabled in config.

    Args:
        config: Configuration dictionary

    Returns:
        True if power monitoring is enabled
    """
    return config.get('pi', {}).get('powerMonitoring', {}).get('enabled', False)


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
    powerConfig = config.get('pi', {}).get('powerMonitoring', {})

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
