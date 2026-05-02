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
# 2026-04-23    | Rex (US-223) | TD-031 close: dropped Battery-specific symbols
#                               (BatteryState, VoltageReading, BatteryStats,
#                               DEFAULT_WARNING_VOLTAGE, DEFAULT_CRITICAL_VOLTAGE,
#                               DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS,
#                               BATTERY_LOG_EVENT_*) -- sole consumer was the
#                               deleted BatteryMonitor class.
# 2026-05-01    | Rex (US-252) | Added staged-shutdown event_type constants
#                               POWER_LOG_EVENT_STAGE_WARNING/IMMINENT/TRIGGER
#                               for the PowerDownOrchestrator -> power_log
#                               write path (forensic data trail companion
#                               to battery_health_log).
# ================================================================================
################################################################################
"""
Power monitoring types, enums, and dataclasses.

This module contains all type definitions for power monitoring:
- PowerSource enum for power source states
- PowerMonitorState enum for power monitor states
- PowerReading dataclass for power status readings
- PowerStats dataclass for power statistics

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

# US-252: PowerDownOrchestrator stage-transition event types.  These rows
# carry the LiPo cell voltage at threshold crossing in the ``vcell`` column
# so a post-mortem can reconstruct the drain trajectory without consulting
# the telemetry log.
POWER_LOG_EVENT_STAGE_WARNING = "stage_warning"
POWER_LOG_EVENT_STAGE_IMMINENT = "stage_imminent"
POWER_LOG_EVENT_STAGE_TRIGGER = "stage_trigger"


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


