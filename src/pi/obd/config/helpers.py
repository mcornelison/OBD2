################################################################################
# File Name: helpers.py
# Purpose/Description: OBD-II configuration helper functions for parameter lookup
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
OBD-II Configuration helper functions.

Provides helper functions for parameter lookup and configuration access.
Includes functions for retrieving parameter information, active profiles,
logged parameters, and polling intervals.

Usage:
    from src.obd.config.helpers import (
        getParameterInfo,
        getAllParameterNames,
        getActiveProfile,
        getLoggedParameters
    )

    # Get info about a specific parameter
    info = getParameterInfo('RPM')

    # Get all available parameter names
    allParams = getAllParameterNames()

    # Get active profile from config
    profile = getActiveProfile(config)
"""

from typing import Any

from .loader import OBD_DEFAULTS
from .parameters import ALL_PARAMETERS, REALTIME_PARAMETERS, STATIC_PARAMETERS
from .types import ParameterInfo

# =============================================================================
# Parameter Lookup Functions
# =============================================================================

def getParameterInfo(name: str) -> ParameterInfo | None:
    """
    Get information about a specific OBD-II parameter.

    Args:
        name: Parameter name (e.g., 'RPM', 'COOLANT_TEMP')

    Returns:
        ParameterInfo object or None if parameter not found
    """
    return ALL_PARAMETERS.get(name.upper())


def getAllParameterNames() -> list[str]:
    """
    Get list of all available OBD-II parameter names.

    Returns:
        List of parameter names
    """
    return sorted(ALL_PARAMETERS.keys())


def getStaticParameterNames() -> list[str]:
    """
    Get list of static (one-time query) parameter names.

    Returns:
        List of static parameter names
    """
    return sorted(STATIC_PARAMETERS.keys())


def getRealtimeParameterNames() -> list[str]:
    """
    Get list of realtime (continuous monitoring) parameter names.

    Returns:
        List of realtime parameter names
    """
    return sorted(REALTIME_PARAMETERS.keys())


def isValidParameter(name: str) -> bool:
    """
    Check if a parameter name is valid.

    Args:
        name: Parameter name to check

    Returns:
        True if valid parameter, False otherwise
    """
    return name.upper() in ALL_PARAMETERS


def isStaticParameter(name: str) -> bool:
    """
    Check if a parameter is a static (one-time query) parameter.

    Args:
        name: Parameter name to check

    Returns:
        True if static parameter, False otherwise
    """
    return name.upper() in STATIC_PARAMETERS


def isRealtimeParameter(name: str) -> bool:
    """
    Check if a parameter is a realtime (continuous monitoring) parameter.

    Args:
        name: Parameter name to check

    Returns:
        True if realtime parameter, False otherwise
    """
    return name.upper() in REALTIME_PARAMETERS


def getParametersByCategory(category: str) -> list[str]:
    """
    Get list of parameter names in a specific category.

    Args:
        category: Category name (e.g., 'engine', 'temperature', 'pressure')

    Returns:
        List of parameter names in the category
    """
    return sorted([
        name for name, info in ALL_PARAMETERS.items()
        if info.category == category.lower()
    ])


def getCategories() -> list[str]:
    """
    Get list of all parameter categories.

    Returns:
        Sorted list of unique category names
    """
    return sorted({info.category for info in ALL_PARAMETERS.values()})


def getDefaultRealtimeConfig() -> list[dict]:
    """
    Get default realtime parameter configuration.

    Returns a list of parameter config objects with recommended defaults
    for common monitoring scenarios.

    Returns:
        List of parameter config dictionaries
    """
    defaultParams = []
    for name, info in REALTIME_PARAMETERS.items():
        if info.defaultLogData:
            defaultParams.append({
                'name': name,
                'logData': True,
                'displayOnDashboard': name in ['RPM', 'SPEED', 'COOLANT_TEMP']
            })
    return defaultParams


def getDefaultStaticConfig() -> list[str]:
    """
    Get default static parameter configuration.

    Returns a list of static parameter names that should be queried
    on first connection by default.

    Returns:
        List of static parameter names
    """
    return [
        name for name, info in STATIC_PARAMETERS.items()
        if info.defaultLogData
    ]


# =============================================================================
# Config Section Access Functions
# =============================================================================

def getConfigSection(
    config: dict[str, Any],
    section: str
) -> dict[str, Any]:
    """
    Get a specific section from the configuration.

    Args:
        config: Configuration dictionary
        section: Section name (e.g., 'database', 'bluetooth')

    Returns:
        Section dictionary or empty dict if not found
    """
    return config.get(section, {})


def getActiveProfile(config: dict[str, Any]) -> dict[str, Any] | None:
    """
    Get the currently active profile configuration.

    Args:
        config: Configuration dictionary

    Returns:
        Active profile dict or None if not found
    """
    profiles = config.get('profiles', {})
    activeProfileId = profiles.get('activeProfile', 'daily')
    availableProfiles = profiles.get('availableProfiles', [])

    for profile in availableProfiles:
        if profile.get('id') == activeProfileId:
            return profile

    # Return first profile as fallback
    if availableProfiles:
        return availableProfiles[0]

    return None


def getLoggedParameters(config: dict[str, Any]) -> list[str]:
    """
    Get list of parameter names that should be logged to database.

    Args:
        config: Configuration dictionary

    Returns:
        List of parameter names with logData=true
    """
    parameters = config.get('realtimeData', {}).get('parameters', [])
    loggedParams = []

    for param in parameters:
        if isinstance(param, dict):
            if param.get('logData', False):
                loggedParams.append(param.get('name', ''))
        elif isinstance(param, str):
            loggedParams.append(param)

    return [p for p in loggedParams if p]


def getStaticParameters(config: dict[str, Any]) -> list[str]:
    """
    Get list of static parameter names to query once on first connection.

    Args:
        config: Configuration dictionary

    Returns:
        List of static parameter names configured for one-time query
    """
    staticData = config.get('staticData', {})
    parameters = staticData.get('parameters', [])

    return [p for p in parameters if p]


def getRealtimeParameters(config: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Get list of realtime parameter configurations.

    Returns the full parameter configuration objects (not just names)
    so callers can access logData and displayOnDashboard flags.

    Args:
        config: Configuration dictionary

    Returns:
        List of parameter configuration dictionaries
    """
    parameters = config.get('realtimeData', {}).get('parameters', [])
    result = []

    for param in parameters:
        if isinstance(param, dict):
            result.append(param)
        elif isinstance(param, str):
            # Normalize string to dict format
            result.append({
                'name': param,
                'logData': True,
                'displayOnDashboard': False
            })

    return result


def getPollingInterval(config: dict[str, Any]) -> int:
    """
    Get the polling interval for realtime data in milliseconds.

    If an active profile is set and has a custom polling interval,
    that takes precedence over the global setting.

    Args:
        config: Configuration dictionary

    Returns:
        Polling interval in milliseconds
    """
    # Check active profile first
    activeProfile = getActiveProfile(config)
    if activeProfile and 'pollingIntervalMs' in activeProfile:
        return activeProfile['pollingIntervalMs']

    # Fall back to global realtime setting
    return config.get('realtimeData', {}).get(
        'pollingIntervalMs',
        OBD_DEFAULTS.get('realtimeData.pollingIntervalMs', 1000)
    )


def shouldQueryStaticOnFirstConnection(config: dict[str, Any]) -> bool:
    """
    Check if static data should be queried on first connection.

    Args:
        config: Configuration dictionary

    Returns:
        True if static data should be queried on first connection
    """
    return config.get('staticData', {}).get('queryOnFirstConnection', True)
