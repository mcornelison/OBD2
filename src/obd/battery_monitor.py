################################################################################
# File Name: battery_monitor.py
# Purpose/Description: Battery backup voltage monitoring for Raspberry Pi
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-022
# 2026-01-22    | Ralph Agent   | Refactored to re-export from power subpackage (US-012)
# ================================================================================
################################################################################
"""
Battery backup voltage monitoring module for the Eclipse OBD-II system.

This module re-exports all components from the power subpackage
for backward compatibility. New code should import directly from power.

Provides:
- Voltage monitoring via GPIO ADC or I2C power monitor
- Configurable warning and critical voltage thresholds
- Visual alert integration with DisplayManager
- Graceful shutdown trigger on critical voltage
- Database logging of voltage readings every 60 seconds
- Statistics tracking

Usage:
    # For backward compatibility (still works):
    from obd.battery_monitor import BatteryMonitor, createBatteryMonitorFromConfig

    # Preferred (new code should use):
    from power import BatteryMonitor, createBatteryMonitorFromConfig
"""

# Re-export all battery-related components from the power subpackage
from power import (
    BATTERY_LOG_EVENT_CRITICAL,
    BATTERY_LOG_EVENT_SHUTDOWN,
    BATTERY_LOG_EVENT_VOLTAGE,
    BATTERY_LOG_EVENT_WARNING,
    DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS,
    DEFAULT_CRITICAL_VOLTAGE,
    # Constants
    DEFAULT_WARNING_VOLTAGE,
    MIN_POLLING_INTERVAL_SECONDS,
    BatteryConfigurationError,
    # Exceptions
    BatteryError,
    # Classes
    BatteryMonitor,
    # Enums
    BatteryState,
    BatteryStats,
    # Dataclasses
    VoltageReading,
    # Reader factory functions
    createAdcVoltageReader,
    # Helper functions
    createBatteryMonitorFromConfig,
    createMockVoltageReader,
    getBatteryMonitoringConfig,
    isBatteryMonitoringEnabled,
)

# Alias for backward compatibility
DEFAULT_POLLING_INTERVAL_SECONDS = DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS

__all__ = [
    # Enums
    'BatteryState',
    # Dataclasses
    'VoltageReading',
    'BatteryStats',
    # Constants
    'DEFAULT_WARNING_VOLTAGE',
    'DEFAULT_CRITICAL_VOLTAGE',
    'DEFAULT_POLLING_INTERVAL_SECONDS',
    'MIN_POLLING_INTERVAL_SECONDS',
    'BATTERY_LOG_EVENT_VOLTAGE',
    'BATTERY_LOG_EVENT_WARNING',
    'BATTERY_LOG_EVENT_CRITICAL',
    'BATTERY_LOG_EVENT_SHUTDOWN',
    # Exceptions
    'BatteryError',
    'BatteryConfigurationError',
    # Classes
    'BatteryMonitor',
    # Reader factory functions
    'createAdcVoltageReader',
    'createMockVoltageReader',
    # Helper functions
    'createBatteryMonitorFromConfig',
    'getBatteryMonitoringConfig',
    'isBatteryMonitoringEnabled',
]
