################################################################################
# File Name: helpers.py
# Purpose/Description: Display helper and factory functions
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | US-006: Extracted from display_manager.py
# ================================================================================
################################################################################

"""
Display helper and factory functions.

Provides convenience functions for creating display components from configuration
and checking display availability.

Usage:
    from display.helpers import (
        createDisplayManagerFromConfig,
        getDisplayModeFromConfig,
        isDisplayAvailable,
        createDisplayDriverFromConfig,
    )

    config = loadConfig()
    manager = createDisplayManagerFromConfig(config)
"""

import logging
from typing import Any

from .drivers import (
    BaseDisplayDriver,
    DeveloperDisplayDriver,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
)
from .manager import DisplayManager
from .types import DisplayMode

logger = logging.getLogger(__name__)


def createDisplayManagerFromConfig(config: dict[str, Any]) -> DisplayManager:
    """
    Create a DisplayManager from configuration.

    Args:
        config: Configuration dictionary with optional 'display' section

    Returns:
        Configured DisplayManager instance

    Example:
        config = {
            'display': {
                'mode': 'developer',
                'useColors': True,
                'showTimestamps': True
            }
        }
        manager = createDisplayManagerFromConfig(config)
    """
    return DisplayManager.fromConfig(config)


def getDisplayModeFromConfig(config: dict[str, Any]) -> DisplayMode:
    """
    Get the display mode from configuration.

    Args:
        config: Configuration dictionary with optional 'display' section

    Returns:
        DisplayMode enum value (defaults to HEADLESS if invalid/missing)

    Example:
        config = {'display': {'mode': 'minimal'}}
        mode = getDisplayModeFromConfig(config)  # DisplayMode.MINIMAL
    """
    modeStr = config.get('display', {}).get('mode', 'headless')
    try:
        return DisplayMode.fromString(modeStr)
    except ValueError:
        logger.warning(f"Invalid display mode '{modeStr}', defaulting to headless")
        return DisplayMode.HEADLESS


def isDisplayAvailable(mode: DisplayMode) -> bool:
    """
    Check if a display mode is available.

    For headless and developer modes, always returns True.
    For minimal mode, checks if display hardware might be available
    (returns True as actual hardware check happens during initialization).

    Args:
        mode: Display mode to check

    Returns:
        True if mode is likely available

    Note:
        This performs a quick availability check. Actual hardware
        availability is verified during initialization.
    """
    # All modes are "available" - actual hardware check happens during init
    return True


def createDisplayDriverFromConfig(config: dict[str, Any]) -> BaseDisplayDriver:
    """
    Create a display driver from configuration.

    Creates the appropriate driver based on the mode specified in config.
    Does not initialize the driver - call driver.initialize() separately.

    Args:
        config: Configuration dictionary with 'display' section

    Returns:
        Appropriate BaseDisplayDriver subclass instance

    Example:
        config = {'display': {'mode': 'developer', 'useColors': False}}
        driver = createDisplayDriverFromConfig(config)
        driver.initialize()
    """
    displayConfig = config.get('display', {})
    mode = getDisplayModeFromConfig(config)

    if mode == DisplayMode.HEADLESS:
        return HeadlessDisplayDriver(displayConfig)
    elif mode == DisplayMode.MINIMAL:
        return MinimalDisplayDriver(displayConfig)
    elif mode == DisplayMode.DEVELOPER:
        return DeveloperDisplayDriver(displayConfig)
    else:
        # Fallback to headless
        logger.warning(f"Unknown mode {mode}, using headless driver")
        return HeadlessDisplayDriver(displayConfig)


def isMinimalDisplayAvailable() -> bool:
    """
    Check if the minimal display hardware/libraries are available.

    This checks for Adafruit libraries availability without actually
    initializing the hardware.

    Returns:
        True if Adafruit display libraries are installed
    """
    try:
        from .adapters.adafruit import ADAFRUIT_AVAILABLE
        return ADAFRUIT_AVAILABLE
    except ImportError:
        return False


def createInitializedDisplayManager(config: dict[str, Any]) -> DisplayManager:
    """
    Create and initialize a DisplayManager from configuration.

    Convenience function that creates the manager and calls initialize().
    Useful for quick setup when you don't need to handle initialization
    separately.

    Args:
        config: Configuration dictionary with optional 'display' section

    Returns:
        Initialized DisplayManager instance

    Raises:
        RuntimeError: If initialization fails

    Example:
        manager = createInitializedDisplayManager(config)
        manager.showStatus(connectionStatus="Connected")
    """
    manager = createDisplayManagerFromConfig(config)
    if not manager.initialize():
        raise RuntimeError(
            f"Failed to initialize display manager in {manager.mode.value} mode"
        )
    return manager


def getDefaultDisplayConfig() -> dict[str, Any]:
    """
    Get the default display configuration.

    Returns:
        Dictionary with default display settings
    """
    return {
        'mode': 'headless',
        'width': 240,
        'height': 240,
        'refreshRateMs': 1000,
        'brightness': 100,
        'useColors': True,
        'showTimestamps': True,
    }


def validateDisplayConfig(config: dict[str, Any]) -> bool:
    """
    Validate display configuration.

    Args:
        config: Configuration dictionary to validate

    Returns:
        True if configuration is valid

    Raises:
        ValueError: If configuration is invalid with details
    """
    displayConfig = config.get('display', {})
    errors = []

    # Validate mode
    modeStr = displayConfig.get('mode', 'headless')
    if not DisplayMode.isValid(modeStr):
        errors.append(
            f"Invalid display mode '{modeStr}'. "
            f"Valid modes: {', '.join(m.value for m in DisplayMode)}"
        )

    # Validate brightness
    brightness = displayConfig.get('brightness', 100)
    if not isinstance(brightness, (int, float)) or brightness < 0 or brightness > 100:
        errors.append(f"Brightness must be 0-100, got {brightness}")

    # Validate refresh rate
    refreshRate = displayConfig.get('refreshRateMs', 1000)
    if not isinstance(refreshRate, (int, float)) or refreshRate < 100:
        errors.append(f"Refresh rate must be at least 100ms, got {refreshRate}")

    if errors:
        raise ValueError("; ".join(errors))

    return True
