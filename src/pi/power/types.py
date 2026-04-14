################################################################################
# File Name: types.py
# Purpose/Description: Power monitoring types, enums, and dataclasses
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-012
# ================================================================================
################################################################################
"""
Power monitoring types, enums, and dataclasses.

This module contains all type definitions for power and battery monitoring:
- PowerSource enum for power source states
- PowerMonitorState enum for power monitor states
- BatteryState enum for battery monitor states
- PowerReading dataclass for power status readings
- PowerStats dataclass for power statistics
- VoltageReading dataclass for voltage readings
- BatteryStats dataclass for battery statistics

All types have zero project dependencies (stdlib only) to avoid circular imports.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

# ================================================================================
# Power Constants
# ================================================================================

# Default polling interval in seconds (when on AC power)
DEFAULT_POLLING_INTERVAL_SECONDS = 5

# Default reduced polling interval in seconds (when on battery)
DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS = 30

# Minimum polling interval (1 second)
MIN_POLLING_INTERVAL_SECONDS = 1

# Default display dim percentage when on battery
DEFAULT_DISPLAY_DIM_PERCENTAGE = 30

# Database event types for power
POWER_LOG_EVENT_AC_POWER = "ac_power"
POWER_LOG_EVENT_BATTERY_POWER = "battery_power"
POWER_LOG_EVENT_TRANSITION_TO_BATTERY = "transition_to_battery"
POWER_LOG_EVENT_TRANSITION_TO_AC = "transition_to_ac"
POWER_LOG_EVENT_POWER_SAVING_ENABLED = "power_saving_enabled"
POWER_LOG_EVENT_POWER_SAVING_DISABLED = "power_saving_disabled"


# ================================================================================
# Battery Constants
# ================================================================================

# Default voltage thresholds (12V automotive battery)
DEFAULT_WARNING_VOLTAGE = 11.5
DEFAULT_CRITICAL_VOLTAGE = 11.0

# Default battery polling interval in seconds
DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS = 60

# Database event types for battery
BATTERY_LOG_EVENT_VOLTAGE = "voltage_reading"
BATTERY_LOG_EVENT_WARNING = "voltage_warning"
BATTERY_LOG_EVENT_CRITICAL = "voltage_critical"
BATTERY_LOG_EVENT_SHUTDOWN = "voltage_shutdown"


# ================================================================================
# Power Enums
# ================================================================================

class PowerSource(Enum):
    """
    Current power source for the system.

    Values:
        UNKNOWN: Power source has not been determined yet
        AC_POWER: Running on AC/12V adapter power
        BATTERY: Running on battery backup
    """

    UNKNOWN = "unknown"
    AC_POWER = "ac_power"
    BATTERY = "battery"


class PowerMonitorState(Enum):
    """
    State of the power monitor.

    Values:
        STOPPED: Monitor is not running
        RUNNING: Monitor is actively polling on AC power
        POWER_SAVING: Monitor is in power saving mode (on battery)
        ERROR: Monitor encountered an error
    """

    STOPPED = "stopped"
    RUNNING = "running"
    POWER_SAVING = "power_saving"
    ERROR = "error"


# ================================================================================
# Battery Enums
# ================================================================================

class BatteryState(Enum):
    """
    State of the battery monitor.

    Values:
        STOPPED: Monitor is not running
        RUNNING: Monitor is actively polling, voltage is normal
        WARNING: Voltage is at or below warning threshold
        CRITICAL: Voltage is at or below critical threshold
        ERROR: Monitor encountered an error
    """

    STOPPED = "stopped"
    RUNNING = "running"
    WARNING = "warning"
    CRITICAL = "critical"
    ERROR = "error"


# ================================================================================
# Power Data Classes
# ================================================================================

@dataclass
class PowerReading:
    """
    Represents a power status reading.

    Attributes:
        powerSource: Current power source (AC or Battery)
        onAcPower: True if on AC power, False if on battery
        timestamp: When the reading was taken
    """

    powerSource: PowerSource
    onAcPower: bool
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def toDict(self) -> dict[str, Any]:
        """
        Convert to dictionary for logging/serialization.

        Returns:
            Dictionary representation of the reading
        """
        return {
            'powerSource': self.powerSource.value,
            'onAcPower': self.onAcPower,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class PowerStats:
    """
    Statistics about power monitoring.

    Attributes:
        totalReadings: Total number of power status readings
        acPowerReadings: Number of readings while on AC power
        batteryReadings: Number of readings while on battery
        transitionsToBattery: Number of AC→Battery transitions
        transitionsToAc: Number of Battery→AC transitions
        lastTransitionTime: Time of last power transition
        totalBatteryTimeSeconds: Total time spent on battery
        lastReading: Most recent power reading
        batteryStartTime: When current battery session started (if on battery)
    """

    totalReadings: int = 0
    acPowerReadings: int = 0
    batteryReadings: int = 0
    transitionsToBattery: int = 0
    transitionsToAc: int = 0
    lastTransitionTime: datetime | None = None
    totalBatteryTimeSeconds: float = 0.0
    lastReading: PowerSource | None = None
    batteryStartTime: datetime | None = None

    def toDict(self) -> dict[str, Any]:
        """
        Convert to dictionary for logging/serialization.

        Returns:
            Dictionary representation of the statistics
        """
        return {
            'totalReadings': self.totalReadings,
            'acPowerReadings': self.acPowerReadings,
            'batteryReadings': self.batteryReadings,
            'transitionsToBattery': self.transitionsToBattery,
            'transitionsToAc': self.transitionsToAc,
            'lastTransitionTime': self.lastTransitionTime.isoformat() if self.lastTransitionTime else None,
            'totalBatteryTimeSeconds': self.totalBatteryTimeSeconds,
            'lastReading': self.lastReading.value if self.lastReading else None,
        }


# ================================================================================
# Battery Data Classes
# ================================================================================

@dataclass
class VoltageReading:
    """
    Represents a voltage reading from the battery.

    Attributes:
        voltage: Voltage value in volts
        timestamp: When the reading was taken
    """

    voltage: float
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def toDict(self) -> dict[str, Any]:
        """
        Convert to dictionary for logging/serialization.

        Returns:
            Dictionary representation of the reading
        """
        return {
            'voltage': self.voltage,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }

    def isWarning(self, warningThreshold: float) -> bool:
        """
        Check if voltage is at warning level.

        Args:
            warningThreshold: Warning voltage threshold

        Returns:
            True if voltage is at or below warning threshold
        """
        return self.voltage <= warningThreshold

    def isCritical(self, criticalThreshold: float) -> bool:
        """
        Check if voltage is at critical level.

        Args:
            criticalThreshold: Critical voltage threshold

        Returns:
            True if voltage is at or below critical threshold
        """
        return self.voltage <= criticalThreshold

    def isNormal(self, warningThreshold: float, criticalThreshold: float) -> bool:
        """
        Check if voltage is at normal level.

        Args:
            warningThreshold: Warning voltage threshold
            criticalThreshold: Critical voltage threshold (unused but kept for symmetry)

        Returns:
            True if voltage is above warning threshold
        """
        return self.voltage > warningThreshold


@dataclass
class BatteryStats:
    """
    Statistics about battery monitoring.

    Attributes:
        totalReadings: Total number of voltage readings taken
        warningCount: Number of warning events
        criticalCount: Number of critical events
        lastReading: Most recent voltage reading
        minVoltage: Minimum voltage observed
        maxVoltage: Maximum voltage observed
        lastWarningTime: Time of last warning
        lastCriticalTime: Time of last critical
    """

    totalReadings: int = 0
    warningCount: int = 0
    criticalCount: int = 0
    lastReading: float | None = None
    minVoltage: float | None = None
    maxVoltage: float | None = None
    lastWarningTime: datetime | None = None
    lastCriticalTime: datetime | None = None

    def toDict(self) -> dict[str, Any]:
        """
        Convert to dictionary for logging/serialization.

        Returns:
            Dictionary representation of the statistics
        """
        return {
            'totalReadings': self.totalReadings,
            'warningCount': self.warningCount,
            'criticalCount': self.criticalCount,
            'lastReading': self.lastReading,
            'minVoltage': self.minVoltage,
            'maxVoltage': self.maxVoltage,
            'lastWarningTime': self.lastWarningTime.isoformat() if self.lastWarningTime else None,
            'lastCriticalTime': self.lastCriticalTime.isoformat() if self.lastCriticalTime else None,
        }
