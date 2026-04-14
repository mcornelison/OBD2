################################################################################
# File Name: __init__.py
# Purpose/Description: Display subpackage for display drivers and management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | US-005: Added driver exports
# 2026-01-22    | Ralph Agent  | US-006: Added manager, adapters, helpers exports
# ================================================================================
################################################################################
"""
Display Subpackage.

This subpackage contains display components:
- DisplayManager: Main display coordination class
- Display drivers (headless, minimal, developer)
- Adafruit hardware adapters
- Display types and exceptions
- Helper and factory functions

Usage:
    from display import (
        DisplayManager,
        DisplayMode,
        StatusInfo,
        AlertInfo,
        createDisplayManagerFromConfig,
    )

    manager = DisplayManager(mode=DisplayMode.DEVELOPER)
    manager.initialize()
    manager.showStatus(connectionStatus="Connected")
"""

# Import adapters subpackage exports
from .adapters import (
    ADAFRUIT_AVAILABLE,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    AdafruitDisplayAdapter,
    Colors,
    DisplayAdapterError,
    DisplayRenderError,
    createAdafruitAdapter,
    isDisplayHardwareAvailable,
)

# Rename adapter's DisplayInitializationError to avoid collision
from .adapters import DisplayInitializationError as AdapterInitializationError
from .drivers import (
    BaseDisplayDriver,
    DeveloperDisplayDriver,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
    NullDisplayAdapter,
)
from .exceptions import (
    DisplayError,
    DisplayInitializationError,
    DisplayOutputError,
)
from .helpers import (
    createDisplayDriverFromConfig,
    createDisplayManagerFromConfig,
    createInitializedDisplayManager,
    getDefaultDisplayConfig,
    getDisplayModeFromConfig,
    isDisplayAvailable,
    isMinimalDisplayAvailable,
    validateDisplayConfig,
)
from .manager import DisplayManager
from .types import (
    AlertInfo,
    DisplayMode,
    StatusInfo,
)

__all__: list[str] = [
    # Types
    'DisplayMode',
    'StatusInfo',
    'AlertInfo',
    # Exceptions
    'DisplayError',
    'DisplayInitializationError',
    'DisplayOutputError',
    # Drivers
    'BaseDisplayDriver',
    'HeadlessDisplayDriver',
    'MinimalDisplayDriver',
    'DeveloperDisplayDriver',
    'NullDisplayAdapter',
    # Manager
    'DisplayManager',
    # Helpers
    'createDisplayManagerFromConfig',
    'getDisplayModeFromConfig',
    'isDisplayAvailable',
    'createDisplayDriverFromConfig',
    'isMinimalDisplayAvailable',
    'createInitializedDisplayManager',
    'getDefaultDisplayConfig',
    'validateDisplayConfig',
    # Adapters
    'AdafruitDisplayAdapter',
    'Colors',
    'DisplayAdapterError',
    'AdapterInitializationError',
    'DisplayRenderError',
    'DISPLAY_WIDTH',
    'DISPLAY_HEIGHT',
    'ADAFRUIT_AVAILABLE',
    'isDisplayHardwareAvailable',
    'createAdafruitAdapter',
]
