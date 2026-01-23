################################################################################
# File Name: __init__.py
# Purpose/Description: Display adapters subpackage for hardware display adapters
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | US-006: Initial subpackage creation
# ================================================================================
################################################################################
"""
Display Adapters Subpackage.

This subpackage contains hardware display adapter implementations:
- AdafruitDisplayAdapter: Adafruit ST7789 1.3" 240x240 TFT display adapter
- Colors: Color constants for display rendering

Usage:
    from display.adapters import (
        AdafruitDisplayAdapter,
        Colors,
        isDisplayHardwareAvailable,
        createAdafruitAdapter,
    )
"""

from .adafruit import (
    AdafruitDisplayAdapter,
    Colors,
    DisplayAdapterError,
    DisplayInitializationError,
    DisplayRenderError,
    DISPLAY_WIDTH,
    DISPLAY_HEIGHT,
    ADAFRUIT_AVAILABLE,
    isDisplayHardwareAvailable,
    createAdafruitAdapter,
)

__all__: list[str] = [
    # Adapters
    'AdafruitDisplayAdapter',
    # Types
    'Colors',
    # Exceptions
    'DisplayAdapterError',
    'DisplayInitializationError',
    'DisplayRenderError',
    # Constants
    'DISPLAY_WIDTH',
    'DISPLAY_HEIGHT',
    'ADAFRUIT_AVAILABLE',
    # Factory functions
    'isDisplayHardwareAvailable',
    'createAdafruitAdapter',
]
