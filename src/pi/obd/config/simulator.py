################################################################################
# File Name: simulator.py
# Purpose/Description: OBD-II simulator configuration helpers
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
OBD-II Simulator configuration helpers.

Provides helper functions for accessing simulator configuration settings.
Includes functions for checking if simulation is enabled, getting profile
paths, scenario paths, connection delays, and failure injection settings.

Usage:
    from src.obd.config.simulator import (
        isSimulatorEnabled,
        getSimulatorConfig,
        getSimulatorProfilePath,
        getSimulatorFailures
    )

    # Check if simulation mode is enabled
    if isSimulatorEnabled(config, args.simulate):
        profile = getSimulatorProfilePath(config)
"""

from typing import Any

from .loader import OBD_DEFAULTS

# =============================================================================
# Simulator Configuration Functions
# =============================================================================

def getSimulatorConfig(config: dict[str, Any]) -> dict[str, Any]:
    """
    Get the simulator configuration section.

    Args:
        config: Configuration dictionary

    Returns:
        Simulator configuration dictionary with defaults applied
    """
    simulator = config.get('simulator', {})

    # Ensure defaults are applied for missing keys
    result = {
        'enabled': simulator.get('enabled', OBD_DEFAULTS.get('simulator.enabled', False)),
        'profilePath': simulator.get(
            'profilePath',
            OBD_DEFAULTS.get('simulator.profilePath', './src/obd/simulator/profiles/default.json')
        ),
        'scenarioPath': simulator.get(
            'scenarioPath',
            OBD_DEFAULTS.get('simulator.scenarioPath', '')
        ),
        'connectionDelaySeconds': simulator.get(
            'connectionDelaySeconds',
            OBD_DEFAULTS.get('simulator.connectionDelaySeconds', 2)
        ),
        'updateIntervalMs': simulator.get(
            'updateIntervalMs',
            OBD_DEFAULTS.get('simulator.updateIntervalMs', 100)
        ),
        'failures': simulator.get('failures', {})
    }

    return result


def isSimulatorEnabled(config: dict[str, Any], simulateFlag: bool = False) -> bool:
    """
    Check if simulation mode is enabled.

    The --simulate CLI flag overrides the config setting.

    Args:
        config: Configuration dictionary
        simulateFlag: True if --simulate CLI flag was passed

    Returns:
        True if simulator should be used
    """
    if simulateFlag:
        return True

    return config.get('simulator', {}).get(
        'enabled',
        OBD_DEFAULTS.get('simulator.enabled', False)
    )


def getSimulatorProfilePath(config: dict[str, Any]) -> str:
    """
    Get the path to the vehicle profile JSON file.

    Args:
        config: Configuration dictionary

    Returns:
        Path to the vehicle profile file
    """
    return config.get('simulator', {}).get(
        'profilePath',
        OBD_DEFAULTS.get('simulator.profilePath', './src/obd/simulator/profiles/default.json')
    )


def getSimulatorScenarioPath(config: dict[str, Any]) -> str | None:
    """
    Get the path to the drive scenario JSON file.

    Args:
        config: Configuration dictionary

    Returns:
        Path to the scenario file, or None if not configured
    """
    scenarioPath = config.get('simulator', {}).get(
        'scenarioPath',
        OBD_DEFAULTS.get('simulator.scenarioPath', '')
    )

    return scenarioPath if scenarioPath else None


def getSimulatorConnectionDelay(config: dict[str, Any]) -> float:
    """
    Get the simulated connection delay in seconds.

    Args:
        config: Configuration dictionary

    Returns:
        Connection delay in seconds
    """
    return config.get('simulator', {}).get(
        'connectionDelaySeconds',
        OBD_DEFAULTS.get('simulator.connectionDelaySeconds', 2)
    )


def getSimulatorUpdateInterval(config: dict[str, Any]) -> int:
    """
    Get the simulator update interval in milliseconds.

    Args:
        config: Configuration dictionary

    Returns:
        Update interval in milliseconds
    """
    return config.get('simulator', {}).get(
        'updateIntervalMs',
        OBD_DEFAULTS.get('simulator.updateIntervalMs', 100)
    )


def getSimulatorFailures(config: dict[str, Any]) -> dict[str, Any]:
    """
    Get the configured failure injection settings.

    Args:
        config: Configuration dictionary

    Returns:
        Dictionary of failure configurations
    """
    return config.get('simulator', {}).get('failures', {})
