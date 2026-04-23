################################################################################
# File Name: __init__.py
# Purpose/Description: Power subpackage for power monitoring
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
# 2026-04-23    | Rex (US-223) | TD-031 close: dropped BatteryMonitor +
#                               BatteryMonitorError + Battery-state/constants
#                               (BatteryState, VoltageReading, BatteryStats,
#                               DEFAULT_WARNING_VOLTAGE, DEFAULT_CRITICAL_VOLTAGE,
#                               DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS,
#                               BATTERY_LOG_EVENT_*) + helper factories
#                               (createBatteryMonitorFromConfig,
#                               getBatteryMonitoringConfig,
#                               isBatteryMonitoringEnabled,
#                               getDefaultBatteryConfig, validateBatteryConfig).
#                               BatteryError + BatteryConfigurationError stay --
#                               still raised by voltage readers in readers.py.
# ================================================================================
################################################################################
"""
Power Subpackage.

This subpackage contains power monitoring components:
- Power monitor for AC/battery power source detection
- Voltage readers for different hardware configurations
- Power state types and exceptions

Exports:
    Types and Constants:
        - PowerSource: Enum for power source states (UNKNOWN, AC_POWER, BATTERY)
        - PowerMonitorState: Enum for power monitor states
        - PowerReading: Dataclass for power status readings
        - PowerStats: Dataclass for power monitoring statistics
        - Constants for defaults and event types

    Exceptions:
        - PowerError: Base power exception
        - PowerConfigurationError: Power configuration error
        - PowerMonitorError: Power monitoring operation error
        - BatteryError: Base battery exception (still raised by voltage readers)
        - BatteryConfigurationError: Battery configuration error
          (still raised by voltage readers in readers.py)

    Classes:
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
        - createPowerMonitorFromConfig: Factory for PowerMonitor
        - getPowerMonitoringConfig: Get power config section
        - isPowerMonitoringEnabled: Check if power monitoring is enabled
        - getDefaultPowerConfig: Get default power config
        - validatePowerConfig: Validate power configuration
"""

# Exceptions
from .exceptions import (
    BatteryConfigurationError,
    BatteryError,
    PowerConfigurationError,
    PowerError,
    PowerMonitorError,
)

# Helper functions
from .helpers import (
    createPowerMonitorFromConfig,
    getDefaultPowerConfig,
    getPowerMonitoringConfig,
    isPowerMonitoringEnabled,
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
    DEFAULT_DISPLAY_DIM_PERCENTAGE,
    # Power constants
    DEFAULT_POLLING_INTERVAL_SECONDS,
    DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS,
    MIN_POLLING_INTERVAL_SECONDS,
    POWER_LOG_EVENT_AC_POWER,
    POWER_LOG_EVENT_BATTERY_POWER,
    POWER_LOG_EVENT_POWER_SAVING_DISABLED,
    POWER_LOG_EVENT_POWER_SAVING_ENABLED,
    POWER_LOG_EVENT_TRANSITION_TO_AC,
    POWER_LOG_EVENT_TRANSITION_TO_BATTERY,
    PowerMonitorState,
    # Dataclasses
    PowerReading,
    # Enums
    PowerSource,
    PowerStats,
)

__all__ = [
    # Enums
    'PowerSource',
    'PowerMonitorState',
    # Dataclasses
    'PowerReading',
    'PowerStats',
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
    # Exceptions
    'PowerError',
    'PowerConfigurationError',
    'PowerMonitorError',
    'BatteryError',
    'BatteryConfigurationError',
    # Classes
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
    'createPowerMonitorFromConfig',
    'getPowerMonitoringConfig',
    'isPowerMonitoringEnabled',
    'getDefaultPowerConfig',
    'validatePowerConfig',
]
