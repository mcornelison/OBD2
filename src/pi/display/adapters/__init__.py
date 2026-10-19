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
# 2026-10-18    | Atlas        | US-872: ADAFRUIT_AVAILABLE forwarded lazily
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
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    AdafruitDisplayAdapter,
    Colors,
    DisplayAdapterError,
    DisplayInitializationError,
    DisplayRenderError,
    createAdafruitAdapter,
    isDisplayHardwareAvailable,
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


def __getattr__(name: str) -> object:
    """US-872: forward ADAFRUIT_AVAILABLE lazily (PEP 562).

    Reading it loads the Adafruit hardware stack (and with it lgpio), so it
    must not be bound at import time; see adapters/adafruit.py.
    """
    if name == 'ADAFRUIT_AVAILABLE':
        from .adafruit import ADAFRUIT_AVAILABLE
        return ADAFRUIT_AVAILABLE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
