################################################################################
# File Name: power_monitor.py
# Purpose/Description: 12V adapter disconnect detection and power source monitoring
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-023
# 2026-01-22    | Ralph Agent   | Refactored to re-export from power subpackage (US-012)
# ================================================================================
################################################################################
"""
12V adapter disconnect detection and power source monitoring module.

This module re-exports all components from the obd.power subpackage
for backward compatibility. New code should import directly from obd.power.

Provides:
- Primary power status monitoring via GPIO or power management HAT
- Power transition event logging (AC→Battery, Battery→AC)
- Power source display on status screen
- Power saving mode when on battery (lower polling rate, dim display)
- Database logging of power events
- Statistics tracking

Usage:
    # For backward compatibility (still works):
    from obd.power_monitor import PowerMonitor, createPowerMonitorFromConfig

    # Preferred (new code should use):
    from obd.power import PowerMonitor, createPowerMonitorFromConfig
"""

# Re-export all power-related components from the power subpackage
from obd.power import (
    # Enums
    PowerSource,
    PowerMonitorState,
    # Dataclasses
    PowerReading,
    PowerStats,
    # Constants
    DEFAULT_POLLING_INTERVAL_SECONDS,
    DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS,
    MIN_POLLING_INTERVAL_SECONDS,
    DEFAULT_DISPLAY_DIM_PERCENTAGE,
    POWER_LOG_EVENT_AC_POWER,
    POWER_LOG_EVENT_BATTERY_POWER,
    POWER_LOG_EVENT_TRANSITION_TO_BATTERY,
    POWER_LOG_EVENT_TRANSITION_TO_AC,
    POWER_LOG_EVENT_POWER_SAVING_ENABLED,
    POWER_LOG_EVENT_POWER_SAVING_DISABLED,
    # Exceptions
    PowerError,
    PowerConfigurationError,
    # Classes
    PowerMonitor,
    # Reader factory functions
    createGpioPowerStatusReader,
    createI2cPowerStatusReader,
    createMockPowerStatusReader,
    # Helper functions
    createPowerMonitorFromConfig,
    getPowerMonitoringConfig,
    isPowerMonitoringEnabled,
)

__all__ = [
    # Enums
    'PowerSource',
    'PowerMonitorState',
    # Dataclasses
    'PowerReading',
    'PowerStats',
    # Constants
    'DEFAULT_POLLING_INTERVAL_SECONDS',
    'DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS',
    'MIN_POLLING_INTERVAL_SECONDS',
    'DEFAULT_DISPLAY_DIM_PERCENTAGE',
    'POWER_LOG_EVENT_AC_POWER',
    'POWER_LOG_EVENT_BATTERY_POWER',
    'POWER_LOG_EVENT_TRANSITION_TO_BATTERY',
    'POWER_LOG_EVENT_TRANSITION_TO_AC',
    'POWER_LOG_EVENT_POWER_SAVING_ENABLED',
    'POWER_LOG_EVENT_POWER_SAVING_DISABLED',
    # Exceptions
    'PowerError',
    'PowerConfigurationError',
    # Classes
    'PowerMonitor',
    # Reader factory functions
    'createGpioPowerStatusReader',
    'createI2cPowerStatusReader',
    'createMockPowerStatusReader',
    # Helper functions
    'createPowerMonitorFromConfig',
    'getPowerMonitoringConfig',
    'isPowerMonitoringEnabled',
]
