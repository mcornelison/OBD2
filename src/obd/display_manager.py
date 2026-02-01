################################################################################
# File Name: display_manager.py
# Purpose/Description: Display mode management for OBD-II monitoring system
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-007
# 2026-01-22    | M. Cornelison | US-008: Added AdafruitDisplayAdapter integration
# 2026-01-22    | Ralph Agent  | US-004: Moved types/exceptions to display subpackage
# 2026-01-22    | Ralph Agent  | US-005: Moved drivers to display/drivers subpackage
# 2026-01-22    | Ralph Agent  | US-006: Moved manager to display/manager.py, re-export
# ================================================================================
################################################################################

"""
Display mode management module.

This module re-exports all display components for backward compatibility.
The actual implementations have been refactored into the display subpackage:

- display.types: DisplayMode, StatusInfo, AlertInfo
- display.exceptions: DisplayError, DisplayInitializationError, DisplayOutputError
- display.drivers: BaseDisplayDriver, HeadlessDisplayDriver, etc.
- display.manager: DisplayManager
- display.helpers: Factory functions

Usage:
    from obd.display_manager import DisplayManager, DisplayMode

    manager = DisplayManager(mode=DisplayMode.HEADLESS)
    manager.showStatus("Connected", details={"RPM": 2500})
    manager.showAlert("High Temp", priority=1)

Or use the new module structure:
    from display import DisplayManager, DisplayMode
"""

import logging

# Re-export drivers from refactored modules
from display.drivers import (
    BaseDisplayDriver,
    DeveloperDisplayDriver,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
    NullDisplayAdapter,
)
from display.exceptions import (
    DisplayError,
    DisplayInitializationError,
    DisplayOutputError,
)

# Re-export helper functions
from display.helpers import (
    createDisplayManagerFromConfig,
    getDisplayModeFromConfig,
    isDisplayAvailable,
)

# Re-export DisplayManager from refactored module
from display.manager import DisplayManager

# Re-export types and exceptions from refactored modules
from display.types import AlertInfo, DisplayMode, StatusInfo

# Backward compatibility alias for internal _NullDisplayAdapter
_NullDisplayAdapter = NullDisplayAdapter

logger = logging.getLogger(__name__)

# Note: This module now serves as a backward compatibility layer.
# New code should import from display directly.

__all__ = [
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
    '_NullDisplayAdapter',
    # Manager
    'DisplayManager',
    # Helpers
    'createDisplayManagerFromConfig',
    'getDisplayModeFromConfig',
    'isDisplayAvailable',
]
