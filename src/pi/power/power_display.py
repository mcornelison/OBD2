################################################################################
# File Name: power_display.py
# Purpose/Description: Display driver helpers for power saving mode + status updates
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-012
# 2026-04-14    | Sweep 5      | Extracted from power.py (task 4 split)
# ================================================================================
################################################################################

"""
Display helpers used by PowerMonitor to dim, restore brightness, and
surface power-source alerts. Stateless — PowerMonitor passes in the
display manager and reads the returned "original brightness" on dim.
"""

import logging
from typing import Any

from .types import PowerSource

logger = logging.getLogger(__name__)


def dimDisplay(displayManager: Any | None, dimPercentage: int) -> int | None:
    """
    Dim the display for power saving.

    Args:
        displayManager: DisplayManager instance (or None)
        dimPercentage: Target brightness percentage (0-100)

    Returns:
        Original brightness (for later restore), or None if unknown
    """
    if not displayManager:
        return None

    originalBrightness: int | None = None

    if hasattr(displayManager, '_driver'):
        driver = displayManager._driver
        if hasattr(driver, '_brightness'):
            originalBrightness = driver._brightness

        # Set dim brightness
        if hasattr(driver, 'setBrightness'):
            try:
                driver.setBrightness(dimPercentage)
                logger.debug(f"Display dimmed to {dimPercentage}%")
            except Exception as e:
                logger.error(f"Error dimming display: {e}")
        elif hasattr(driver, '_displayAdapter') and driver._displayAdapter:
            adapter = driver._displayAdapter
            if hasattr(adapter, 'setBrightness'):
                try:
                    adapter.setBrightness(dimPercentage)
                    logger.debug(f"Display dimmed to {dimPercentage}%")
                except Exception as e:
                    logger.error(f"Error dimming display via adapter: {e}")

    return originalBrightness


def restoreDisplayBrightness(
    displayManager: Any | None,
    originalBrightness: int | None,
) -> None:
    """
    Restore display brightness after power saving mode.

    Args:
        displayManager: DisplayManager instance (or None)
        originalBrightness: Brightness value to restore (or None → no-op)
    """
    if not displayManager or originalBrightness is None:
        return

    if hasattr(displayManager, '_driver'):
        driver = displayManager._driver
        if hasattr(driver, 'setBrightness'):
            try:
                driver.setBrightness(originalBrightness)
                logger.debug(f"Display brightness restored to {originalBrightness}%")
            except Exception as e:
                logger.error(f"Error restoring display brightness: {e}")
        elif hasattr(driver, '_displayAdapter') and driver._displayAdapter:
            adapter = driver._displayAdapter
            if hasattr(adapter, 'setBrightness'):
                try:
                    adapter.setBrightness(originalBrightness)
                    logger.debug(f"Display brightness restored to {originalBrightness}%")
                except Exception as e:
                    logger.error(f"Error restoring display brightness via adapter: {e}")


def updateDisplayPowerSource(
    displayManager: Any | None,
    powerSource: PowerSource,
) -> None:
    """
    Update display with current power source (shows battery alert).

    Args:
        displayManager: DisplayManager instance (or None)
        powerSource: Current power source
    """
    if not displayManager:
        return

    # Show alert for power transitions if display supports it
    if hasattr(displayManager, 'showAlert'):
        if powerSource == PowerSource.BATTERY:
            try:
                displayManager.showAlert(
                    message="ON BATTERY POWER",
                    priority=3,
                )
            except Exception as e:
                logger.error(f"Error showing battery alert: {e}")
