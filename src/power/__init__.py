################################################################################
# File Name: __init__.py
# Purpose/Description: Power subpackage for power and battery monitoring
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | Added all exports for US-012
# ================================================================================
################################################################################
"""
Power Subpackage.

This subpackage contains power monitoring components:
- Battery monitor for voltage monitoring and threshold handling
- Power monitor for AC/battery power source detection
- Voltage readers for different hardware configurations
- Power state types and exceptions

Exports:
    Types and Constants:
        - PowerSource: Enum for power source states (UNKNOWN, AC_POWER, BATTERY)
        - PowerMonitorState: Enum for power monitor states
        - BatteryState: Enum for battery monitor states
        - PowerReading: Dataclass for power status readings
        - PowerStats: Dataclass for power monitoring statistics
        - VoltageReading: Dataclass for voltage readings
        - BatteryStats: Dataclass for battery monitoring statistics
        - Constants for defaults and event types

    Exceptions:
        - PowerError: Base power exception
        - PowerConfigurationError: Power configuration error
        - PowerMonitorError: Power monitoring operation error
        - BatteryError: Base battery exception
        - BatteryConfigurationError: Battery configuration error
        - BatteryMonitorError: Battery monitoring operation error

    Classes:
        - BatteryMonitor: Battery voltage monitoring class
        - PowerMonitor: Power source monitoring class

    Reader Factory Functions:
        - createAdcVoltageReader: Create ADC-based voltage reader
        - createI2cVoltageReader: Create I2C-based voltage reader
        - createMockVoltageReader: Create mock voltage reader for testing
        - createGpioPowerStatusReader: Create GPIO power status reader
        - createI2cPowerStatusReader: Create I2C power status reader
        - createMockPowerStatusReader: Create mock power status reader
        - createVariableVoltageReader: Create delegating voltage reader
        - createVariablePowerStatusReader: Create delegating power status reader

    Helper Functions:
        - createBatteryMonitorFromConfig: Factory for BatteryMonitor
        - getBatteryMonitoringConfig: Get battery config section
        - isBatteryMonitoringEnabled: Check if battery monitoring is enabled
        - getDefaultBatteryConfig: Get default battery config
        - validateBatteryConfig: Validate battery configuration
        - createPowerMonitorFromConfig: Factory for PowerMonitor
        - getPowerMonitoringConfig: Get power config section
        - isPowerMonitoringEnabled: Check if power monitoring is enabled
        - getDefaultPowerConfig: Get default power config
        - validatePowerConfig: Validate power configuration
"""

# Types and constants
# Classes
from .battery import BatteryMonitor

# Exceptions
from .exceptions import (
    BatteryConfigurationError,
    BatteryError,
    BatteryMonitorError,
    PowerConfigurationError,
    PowerError,
    PowerMonitorError,
)

# Helper functions
from .helpers import (
    createBatteryMonitorFromConfig,
    createPowerMonitorFromConfig,
    getBatteryMonitoringConfig,
    getDefaultBatteryConfig,
    getDefaultPowerConfig,
    getPowerMonitoringConfig,
    isBatteryMonitoringEnabled,
    isPowerMonitoringEnabled,
    validateBatteryConfig,
    validatePowerConfig,
)
from .power import PowerMonitor

# Reader factory functions
from .readers import (
    createAdcVoltageReader,
    createGpioPowerStatusReader,
    createI2cPowerStatusReader,
    createI2cVoltageReader,
    createMockPowerStatusReader,
    createMockVoltageReader,
    createVariablePowerStatusReader,
    createVariableVoltageReader,
)
from .types import (
    BATTERY_LOG_EVENT_CRITICAL,
    BATTERY_LOG_EVENT_SHUTDOWN,
    BATTERY_LOG_EVENT_VOLTAGE,
    BATTERY_LOG_EVENT_WARNING,
    DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS,
    DEFAULT_CRITICAL_VOLTAGE,
    DEFAULT_DISPLAY_DIM_PERCENTAGE,
    # Power constants
    DEFAULT_POLLING_INTERVAL_SECONDS,
    DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS,
    # Battery constants
    DEFAULT_WARNING_VOLTAGE,
    MIN_POLLING_INTERVAL_SECONDS,
    POWER_LOG_EVENT_AC_POWER,
    POWER_LOG_EVENT_BATTERY_POWER,
    POWER_LOG_EVENT_POWER_SAVING_DISABLED,
    POWER_LOG_EVENT_POWER_SAVING_ENABLED,
    POWER_LOG_EVENT_TRANSITION_TO_AC,
    POWER_LOG_EVENT_TRANSITION_TO_BATTERY,
    BatteryState,
    BatteryStats,
    PowerMonitorState,
    # Dataclasses
    PowerReading,
    # Enums
    PowerSource,
    PowerStats,
    VoltageReading,
)

__all__ = [
    # Enums
    'PowerSource',
    'PowerMonitorState',
    'BatteryState',
    # Dataclasses
    'PowerReading',
    'PowerStats',
    'VoltageReading',
    'BatteryStats',
    # Power constants
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
    # Battery constants
    'DEFAULT_WARNING_VOLTAGE',
    'DEFAULT_CRITICAL_VOLTAGE',
    'DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS',
    'BATTERY_LOG_EVENT_VOLTAGE',
    'BATTERY_LOG_EVENT_WARNING',
    'BATTERY_LOG_EVENT_CRITICAL',
    'BATTERY_LOG_EVENT_SHUTDOWN',
    # Exceptions
    'PowerError',
    'PowerConfigurationError',
    'PowerMonitorError',
    'BatteryError',
    'BatteryConfigurationError',
    'BatteryMonitorError',
    # Classes
    'BatteryMonitor',
    'PowerMonitor',
    # Reader factory functions
    'createAdcVoltageReader',
    'createI2cVoltageReader',
    'createMockVoltageReader',
    'createGpioPowerStatusReader',
    'createI2cPowerStatusReader',
    'createMockPowerStatusReader',
    'createVariableVoltageReader',
    'createVariablePowerStatusReader',
    # Helper functions
    'createBatteryMonitorFromConfig',
    'getBatteryMonitoringConfig',
    'isBatteryMonitoringEnabled',
    'getDefaultBatteryConfig',
    'validateBatteryConfig',
    'createPowerMonitorFromConfig',
    'getPowerMonitoringConfig',
    'isPowerMonitoringEnabled',
    'getDefaultPowerConfig',
    'validatePowerConfig',
]
