################################################################################
# File Name: adafruit_display.py
# Purpose/Description: Adafruit ST7789 1.3" 240x240 TFT display adapter
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-008
# 2026-01-22    | Ralph Agent  | US-006: Moved to display/adapters/adafruit.py, re-export
# ================================================================================
################################################################################

"""
Adafruit ST7789 1.3" 240x240 TFT display adapter.

This module re-exports all Adafruit display components for backward compatibility.
The actual implementation has been moved to obd.display.adapters.adafruit.

Usage:
    from obd.adafruit_display import AdafruitDisplayAdapter, isDisplayHardwareAvailable

    if isDisplayHardwareAvailable():
        adapter = AdafruitDisplayAdapter()
        adapter.initialize()
        adapter.drawText(10, 10, "Hello World")
        adapter.refresh()
        adapter.shutdown()

Or use the new module structure:
    from obd.display.adapters import AdafruitDisplayAdapter, isDisplayHardwareAvailable
"""

# Re-export all components from the new location
from obd.display.adapters.adafruit import (
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

# Note: This module now serves as a backward compatibility layer.
# New code should import from obd.display.adapters directly.

__all__ = [
    'AdafruitDisplayAdapter',
    'Colors',
    'DisplayAdapterError',
    'DisplayInitializationError',
    'DisplayRenderError',
    'DISPLAY_WIDTH',
    'DISPLAY_HEIGHT',
    'ADAFRUIT_AVAILABLE',
    'isDisplayHardwareAvailable',
    'createAdafruitAdapter',
]
