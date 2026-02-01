################################################################################
# File Name: helpers.py
# Purpose/Description: Helper functions for alert management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-011
# ================================================================================
################################################################################
"""
Helper functions for alert management.

Provides factory functions and configuration helpers for the AlertManager.
"""

import logging
from typing import Any

from .manager import AlertManager
from .types import DEFAULT_COOLDOWN_SECONDS

logger = logging.getLogger(__name__)


def createAlertManagerFromConfig(
    config: dict[str, Any],
    database: Any | None = None,
    displayManager: Any | None = None
) -> AlertManager:
    """
    Create an AlertManager from configuration.

    Args:
        config: Configuration dictionary
        database: ObdDatabase instance (optional)
        displayManager: DisplayManager instance (optional)

    Returns:
        Configured AlertManager instance
    """
    alertsConfig = config.get('alerts', {})

    enabled = alertsConfig.get('enabled', True)
    cooldownSeconds = alertsConfig.get('cooldownSeconds', DEFAULT_COOLDOWN_SECONDS)
    visualAlerts = alertsConfig.get('visualAlerts', True)
    logAlerts = alertsConfig.get('logAlerts', True)

    manager = AlertManager(
        database=database,
        displayManager=displayManager,
        cooldownSeconds=cooldownSeconds,
        enabled=enabled,
        visualAlerts=visualAlerts,
        logAlerts=logAlerts,
    )

    # Load profile thresholds
    profilesConfig = config.get('profiles', {})
    activeProfile = profilesConfig.get('activeProfile', 'daily')

    for profile in profilesConfig.get('availableProfiles', []):
        profileId = profile.get('id')
        thresholds = profile.get('alertThresholds', {})
        if profileId and thresholds:
            manager.setProfileThresholds(profileId, thresholds)

    manager.setActiveProfile(activeProfile)

    logger.info(
        f"AlertManager created from config: enabled={enabled}, "
        f"cooldown={cooldownSeconds}s, visual={visualAlerts}, log={logAlerts}"
    )

    return manager


def getAlertThresholdsForProfile(
    config: dict[str, Any],
    profileId: str
) -> dict[str, float]:
    """
    Get alert thresholds for a specific profile from config.

    Args:
        config: Configuration dictionary
        profileId: Profile ID to get thresholds for

    Returns:
        Dictionary of threshold key to value
    """
    profilesConfig = config.get('profiles', {})

    for profile in profilesConfig.get('availableProfiles', []):
        if profile.get('id') == profileId:
            return profile.get('alertThresholds', {})

    return {}


def isAlertingEnabled(config: dict[str, Any]) -> bool:
    """
    Check if alerting is enabled in config.

    Args:
        config: Configuration dictionary

    Returns:
        True if alerting is enabled
    """
    return config.get('alerts', {}).get('enabled', True)


def getAlertConfig(config: dict[str, Any]) -> dict[str, Any]:
    """
    Get alert configuration section.

    Args:
        config: Full configuration dictionary

    Returns:
        Alert configuration section
    """
    return config.get('alerts', {})


def getDefaultAlertConfig() -> dict[str, Any]:
    """
    Get default alert configuration.

    Returns:
        Default alert config dictionary
    """
    return {
        'enabled': True,
        'cooldownSeconds': DEFAULT_COOLDOWN_SECONDS,
        'visualAlerts': True,
        'logAlerts': True,
    }


def validateAlertConfig(config: dict[str, Any]) -> list[str]:
    """
    Validate alert configuration.

    Args:
        config: Alert configuration dictionary

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    alertsConfig = config.get('alerts', {})

    if 'cooldownSeconds' in alertsConfig:
        cooldown = alertsConfig['cooldownSeconds']
        if not isinstance(cooldown, (int, float)):
            errors.append("cooldownSeconds must be a number")
        elif cooldown < 1:
            errors.append("cooldownSeconds must be at least 1")

    if 'enabled' in alertsConfig:
        if not isinstance(alertsConfig['enabled'], bool):
            errors.append("enabled must be a boolean")

    if 'visualAlerts' in alertsConfig:
        if not isinstance(alertsConfig['visualAlerts'], bool):
            errors.append("visualAlerts must be a boolean")

    if 'logAlerts' in alertsConfig:
        if not isinstance(alertsConfig['logAlerts'], bool):
            errors.append("logAlerts must be a boolean")

    return errors
