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
# 2026-05-18    | Plan (P2-T9) | Relocated PowerLogWriter type alias here from
#                               the deleted power/orchestrator.py so the kept
#                               power_log writer path keeps its type surface.
# 2026-08-29    | Rex (US-626) | Added PowerObservation (the honest three-state
#                               power-source reading), POWER_OBSERVER_PLD_GPIO6,
#                               OBSERVER_STATE_PRESENT/_LOST/_UNKNOWN and
#                               POWER_LOG_EVENT_OBSERVER_SESSION_START, so a
#                               power_log row records WHICH instrument saw it
#                               and whether that instrument could see at all.
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

from collections.abc import Callable
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

# US-626: the observer opened a watch on the power-source fact.  Written once
# per bridge start.  Its ONLY job is to make a quiet log legible: with it, "no
# transitions occurred" is a positive statement; without it, an empty log and
# a never-started observer are the same result -- which is how ten power
# losses went unrecorded across ten boots.
POWER_LOG_EVENT_OBSERVER_SESSION_START = "observer_session_start"

# US-626: which instrument witnessed a row.  power_log rows are written from
# more than one domain, and a disagreement between observers is only visible
# if each row says who saw it.
POWER_OBSERVER_PLD_GPIO6 = "pld_gpio6"

# US-626: the HONEST three-state power-source read.  PldSensor deliberately
# collapses "unreadable" into "power present" -- the correct non-bricking
# direction for the SHUTDOWN path, and a confident lie in a FORENSIC log.
# PowerSourceProvider.isAvailable already documents that a display consumer
# must not take that collapse at face value (US-502); power_log is such a
# consumer.  These three keep "the line said AC" distinct from "the line said
# nothing and we defaulted to AC".
OBSERVER_STATE_PRESENT = "present"
OBSERVER_STATE_LOST = "lost"
OBSERVER_STATE_UNKNOWN = "unknown"


# ================================================================================
# Type Aliases
# ================================================================================

# (eventType, vcell) -> None.  obdii/orchestrator/lifecycle._createPowerLogWriter
# builds a closure over the power_log writer and hands it to HardwareManager so
# each power event leaves a forensic row in ``power_log``.  Relocated here from
# the deleted power/orchestrator.py (P2-T9) -- this is data-collection plumbing,
# independent of the (now removed) in-app shutdown ladder.
PowerLogWriter = Callable[[str, float], None]


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


@dataclass(frozen=True)
class PowerObservation:
    """US-626: one honest reading of the power-source fact.

    Carries BOTH renderings of the same read, deliberately:

    * ``state`` -- the three-state forensic truth (present / lost / unknown).
      This is what a power_log row records, so an unreadable instrument can
      never be written down as a confident "AC power".
    * ``onAcPower`` -- the two-state bool the status surface consumes.
      ``unknown`` resolves here to True, preserving the existing
      "uncertain => do NOT shut down" safe direction.  Changing that bool is
      a different failure domain (the T5 smoothing loop) and explicitly not
      this story's business.

    Attributes:
        observedBy: Identity of the instrument that took the reading (e.g.
            ``POWER_OBSERVER_PLD_GPIO6``), so a disagreement between two
            observers is visible in the log rather than inferred.
        state: One of OBSERVER_STATE_PRESENT / _LOST / _UNKNOWN.
        onAcPower: The safe-direction bool for status consumers.
    """

    observedBy: str
    state: str
    onAcPower: bool

    @classmethod
    def fromProvider(cls, provider: Any, *, observedBy: str) -> "PowerObservation":
        """Take one honest reading from a PowerSourceProvider-shaped object.

        Readability is consulted FIRST and independently of presence.  The
        underlying ``PldSensor.isExternalPowerPresent()`` returns True both
        for "the line says power is present" and for "the line could not be
        read at all"; asking ``isAvailable`` separately is the only way to
        tell those apart, and conflating them is the defect that let a dead
        or contended GPIO6 report AC power across ten boots.

        A provider that does not implement ``isAvailable`` at all is treated as
        READABLE, and that default is deliberate.  The minimal provider shape
        the bridge documents is ``isExternalPowerPresent()`` alone;
        ``isAvailable`` is an enhancement.  Defaulting a non-reporting object
        to blind would make it permanently UNKNOWN, suppressing every
        transition record -- the exact opposite of AC-5 ("a power loss with no
        corresponding row must be impossible by construction").  Note this is
        the OPPOSITE default to ``PowerSourceProvider.isAvailable``, which
        resolves a non-reporting *PldSensor* to False: that sits at the
        hardware boundary where "unknown beats assumed-good" governs a
        SHUTDOWN decision.  Here we are one layer up, choosing between
        recording a transition and recording nothing at all.

        Args:
            provider: Object exposing ``isExternalPowerPresent()`` and,
                optionally, ``isAvailable``.
            observedBy: Identity to stamp on the reading.

        Returns:
            A PowerObservation.  Never raises: a provider that blows up is an
            UNKNOWN reading, which is a fact worth recording, not an error to
            propagate into a status surface.
        """
        try:
            available = bool(getattr(provider, "isAvailable", True))
            if not available:
                return cls(observedBy, OBSERVER_STATE_UNKNOWN, True)
            present = bool(provider.isExternalPowerPresent())
        except Exception:  # noqa: BLE001 -- an unreadable instrument is a fact
            return cls(observedBy, OBSERVER_STATE_UNKNOWN, True)

        return cls(
            observedBy,
            OBSERVER_STATE_PRESENT if present else OBSERVER_STATE_LOST,
            present,
        )

    @property
    def powerSource(self) -> PowerSource:
        """The PowerSource this reading implies for the row's own columns."""
        return PowerSource.AC_POWER if self.onAcPower else PowerSource.BATTERY


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


