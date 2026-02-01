################################################################################
# File Name: platform_utils.py
# Purpose/Description: Platform detection utilities for Raspberry Pi hardware
# Author: Ralph Agent
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Ralph Agent  | Initial implementation for US-RPI-003
# ================================================================================
################################################################################

"""
Platform detection utilities for Raspberry Pi hardware.

This module provides functions to detect whether the code is running on
a Raspberry Pi and to gather platform information. It handles graceful
fallback on non-Pi systems.

Usage:
    from hardware.platform_utils import isRaspberryPi, getPlatformInfo

    if isRaspberryPi():
        # Enable Pi-specific features
        initializeGpio()

    info = getPlatformInfo()
    print(f"Running on {info['os']} ({info['architecture']})")
"""

import logging
import os
import platform
from typing import Any

logger = logging.getLogger(__name__)

# Path to the device tree model file on Linux systems
DEVICE_TREE_MODEL_PATH = '/proc/device-tree/model'


def isRaspberryPi() -> bool:
    """
    Detect whether the code is running on a Raspberry Pi.

    Checks for Raspberry Pi hardware by reading the device tree model file
    on Linux systems. Returns False gracefully on non-Pi systems.

    Returns:
        True if running on Raspberry Pi, False otherwise.

    Example:
        >>> if isRaspberryPi():
        ...     print("Running on Pi!")
        ... else:
        ...     print("Not a Pi")
    """
    try:
        # Only Raspberry Pi uses this detection method (Linux)
        if platform.system() != 'Linux':
            return False

        # Check if the device tree model file exists
        if not os.path.exists(DEVICE_TREE_MODEL_PATH):
            return False

        # Read the model string
        with open(DEVICE_TREE_MODEL_PATH) as f:
            modelString = f.read()

        # Check for Raspberry Pi in the model string
        # The model string contains null bytes, so strip them
        modelString = modelString.strip('\x00').strip()
        isPi = 'Raspberry Pi' in modelString

        if isPi:
            logger.debug(f"Detected Raspberry Pi: {modelString}")

        return isPi

    except OSError as e:
        # File read errors - gracefully return False
        logger.debug(f"Could not read device tree model: {e}")
        return False
    except Exception as e:
        # Any other unexpected error - gracefully return False
        logger.warning(f"Unexpected error during Pi detection: {e}")
        return False


def _readPiModel() -> str | None:
    """
    Read the Raspberry Pi model string from the device tree.

    Returns:
        The model string (e.g., "Raspberry Pi 5 Model B Rev 1.0")
        or None if not available.
    """
    try:
        if platform.system() != 'Linux':
            return None

        if not os.path.exists(DEVICE_TREE_MODEL_PATH):
            return None

        with open(DEVICE_TREE_MODEL_PATH) as f:
            modelString = f.read()

        # Strip null bytes and whitespace
        modelString = modelString.strip('\x00').strip()

        if modelString:
            return modelString
        return None

    except OSError:
        return None
    except Exception:
        return None


def getPlatformInfo() -> dict[str, Any]:
    """
    Get comprehensive platform information.

    Returns a dictionary with information about the current system,
    including OS, architecture, Raspberry Pi model (if applicable),
    and whether the system is a Raspberry Pi.

    Returns:
        Dictionary with keys:
            - os: Operating system name (e.g., 'Linux', 'Windows', 'Darwin')
            - architecture: CPU architecture (e.g., 'aarch64', 'AMD64', 'x86_64')
            - model: Raspberry Pi model string or None
            - isRaspberryPi: Boolean indicating if running on Pi

    Example:
        >>> info = getPlatformInfo()
        >>> print(f"OS: {info['os']}, Arch: {info['architecture']}")
        OS: Linux, Arch: aarch64
    """
    try:
        osName = platform.system()
        architecture = platform.machine()
        model = _readPiModel()
        isPi = isRaspberryPi()

        return {
            'os': osName,
            'architecture': architecture,
            'model': model,
            'isRaspberryPi': isPi
        }

    except Exception as e:
        # Graceful fallback on any error
        logger.warning(f"Error getting platform info: {e}")
        return {
            'os': 'Unknown',
            'architecture': 'Unknown',
            'model': None,
            'isRaspberryPi': False
        }
