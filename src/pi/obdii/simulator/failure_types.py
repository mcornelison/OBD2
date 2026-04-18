################################################################################
# File Name: failure_types.py
# Purpose/Description: Shared types for failure injection system (enums, dataclasses, constants)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-038
# 2026-04-14    | Sweep 5       | Extracted from failure_injector.py (task 4 split)
# ================================================================================
################################################################################

"""
Shared types for the failure injection subsystem.

Provides:
- FailureType enum (connectionDrop, sensorFailure, intermittentSensor, outOfRange, dtcCodes)
- FailureState enum
- FailureConfig dataclass
- ScheduledFailure dataclass with isActive/isExpired helpers
- ActiveFailure dataclass
- InjectorStatus dataclass
- Common constants (default probabilities, COMMON_DTC_CODES)
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ================================================================================
# Constants
# ================================================================================

# Default intermittent failure probability (30% chance of failure)
DEFAULT_INTERMITTENT_PROBABILITY = 0.3

# Default out-of-range deviation factor
DEFAULT_OUT_OF_RANGE_FACTOR = 3.0

# Common DTC codes for testing
COMMON_DTC_CODES = [
    "P0300",  # Random/Multiple Cylinder Misfire Detected
    "P0171",  # System Too Lean (Bank 1)
    "P0172",  # System Too Rich (Bank 1)
    "P0420",  # Catalyst System Efficiency Below Threshold (Bank 1)
    "P0440",  # Evaporative Emission System Malfunction
    "P0500",  # Vehicle Speed Sensor Malfunction
    "P0128",  # Coolant Thermostat (Coolant Temperature Below Thermostat Regulating Temperature)
    "P0340",  # Camshaft Position Sensor Circuit Malfunction
]


# ================================================================================
# Enums
# ================================================================================

class FailureType(Enum):
    """
    Available failure injection types.

    Attributes:
        CONNECTION_DROP: Simulates loss of OBD-II connection
        SENSOR_FAILURE: Makes specific sensor(s) return null/error
        INTERMITTENT_SENSOR: Sensors randomly fail/succeed
        OUT_OF_RANGE: Sensors return values outside normal range
        DTC_CODES: Simulates diagnostic trouble codes being set
    """

    CONNECTION_DROP = "connectionDrop"
    SENSOR_FAILURE = "sensorFailure"
    INTERMITTENT_SENSOR = "intermittentSensor"
    OUT_OF_RANGE = "outOfRange"
    DTC_CODES = "dtcCodes"

    @classmethod
    def fromString(cls, value: str) -> Optional["FailureType"]:
        """
        Convert string to FailureType enum.

        Args:
            value: String representation of failure type

        Returns:
            FailureType enum or None if not found
        """
        # Normalize input (lowercase, handle both camelCase and snake_case)
        normalized = value.lower().replace("_", "").replace("-", "")

        for failureType in cls:
            if failureType.value.lower().replace("_", "") == normalized:
                return failureType

        return None


class FailureState(Enum):
    """Failure injection state."""

    INACTIVE = "inactive"
    ACTIVE = "active"
    SCHEDULED = "scheduled"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class FailureConfig:
    """
    Configuration for a failure injection.

    Attributes:
        sensorNames: List of sensor names affected (for sensor-specific failures)
        probability: Probability of failure occurring (0.0-1.0, for intermittent)
        outOfRangeFactor: Factor by which to exceed normal range (for out_of_range)
        outOfRangeDirection: Direction of out-of-range: 'high', 'low', or 'random'
        dtcCodes: List of DTC codes to report (for dtc_codes)
        customValue: Custom value to return instead of simulated value
        affectsAllSensors: If True, affects all sensors (not just sensorNames)
    """

    sensorNames: list[str] = field(default_factory=list)
    probability: float = DEFAULT_INTERMITTENT_PROBABILITY
    outOfRangeFactor: float = DEFAULT_OUT_OF_RANGE_FACTOR
    outOfRangeDirection: str = "random"  # 'high', 'low', or 'random'
    dtcCodes: list[str] = field(default_factory=list)
    customValue: float | None = None
    affectsAllSensors: bool = False

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Normalize sensor names to uppercase
        self.sensorNames = [s.upper() for s in self.sensorNames]

        # Clamp probability to valid range
        self.probability = max(0.0, min(1.0, self.probability))

        # Validate out-of-range direction
        validDirections = {"high", "low", "random"}
        if self.outOfRangeDirection not in validDirections:
            self.outOfRangeDirection = "random"

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sensorNames": self.sensorNames,
            "probability": self.probability,
            "outOfRangeFactor": self.outOfRangeFactor,
            "outOfRangeDirection": self.outOfRangeDirection,
            "dtcCodes": self.dtcCodes,
            "customValue": self.customValue,
            "affectsAllSensors": self.affectsAllSensors,
        }

    @classmethod
    def fromDict(cls, data: dict[str, Any]) -> "FailureConfig":
        """Create from dictionary."""
        return cls(
            sensorNames=data.get("sensorNames", []),
            probability=data.get("probability", DEFAULT_INTERMITTENT_PROBABILITY),
            outOfRangeFactor=data.get("outOfRangeFactor", DEFAULT_OUT_OF_RANGE_FACTOR),
            outOfRangeDirection=data.get("outOfRangeDirection", "random"),
            dtcCodes=data.get("dtcCodes", []),
            customValue=data.get("customValue"),
            affectsAllSensors=data.get("affectsAllSensors", False),
        )


@dataclass
class ScheduledFailure:
    """
    A scheduled failure injection.

    Attributes:
        failureType: Type of failure to inject
        config: Configuration for the failure
        startSeconds: Seconds from now to start the failure
        durationSeconds: How long the failure should last (None = permanent)
        startTime: Actual start time (set when scheduled)
        endTime: Actual end time (set when scheduled)
        id: Unique identifier for this scheduled failure
    """

    failureType: FailureType
    config: FailureConfig
    startSeconds: float
    durationSeconds: float | None
    startTime: float | None = None
    endTime: float | None = None
    id: str = ""

    def __post_init__(self) -> None:
        """Set start and end times."""
        if not self.id:
            self.id = f"{self.failureType.value}_{id(self)}"

        currentTime = time.time()
        self.startTime = currentTime + self.startSeconds

        if self.durationSeconds is not None:
            self.endTime = self.startTime + self.durationSeconds
        else:
            self.endTime = None

    def isActive(self, currentTime: float | None = None) -> bool:
        """Check if this scheduled failure is currently active."""
        if currentTime is None:
            currentTime = time.time()

        if self.startTime is None:
            return False

        if currentTime < self.startTime:
            return False  # Not started yet

        if self.endTime is None:
            return True  # Permanent after start

        return currentTime < self.endTime

    def isExpired(self, currentTime: float | None = None) -> bool:
        """Check if this scheduled failure has expired."""
        if currentTime is None:
            currentTime = time.time()

        if self.endTime is None:
            return False  # Never expires

        return currentTime >= self.endTime

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "failureType": self.failureType.value,
            "config": self.config.toDict(),
            "startSeconds": self.startSeconds,
            "durationSeconds": self.durationSeconds,
            "startTime": self.startTime,
            "endTime": self.endTime,
            "id": self.id,
        }


@dataclass
class ActiveFailure:
    """
    An active failure injection.

    Attributes:
        failureType: Type of failure
        config: Configuration for the failure
        activatedAt: When the failure was activated
        scheduledFailure: Reference to scheduled failure if applicable
    """

    failureType: FailureType
    config: FailureConfig
    activatedAt: float = field(default_factory=time.time)
    scheduledFailure: ScheduledFailure | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "failureType": self.failureType.value,
            "config": self.config.toDict(),
            "activatedAt": self.activatedAt,
            "scheduledFailureId": (
                self.scheduledFailure.id if self.scheduledFailure else None
            ),
        }


@dataclass
class InjectorStatus:
    """
    Status of the failure injector.

    Attributes:
        isActive: Whether any failures are currently active
        activeFailures: List of currently active failure types
        scheduledFailures: Number of scheduled failures pending
        totalInjected: Total number of failures ever injected
        dtcCodes: Currently active DTC codes
    """

    isActive: bool = False
    activeFailures: list[str] = field(default_factory=list)
    scheduledFailures: int = 0
    totalInjected: int = 0
    dtcCodes: list[str] = field(default_factory=list)

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "isActive": self.isActive,
            "activeFailures": self.activeFailures,
            "scheduledFailures": self.scheduledFailures,
            "totalInjected": self.totalInjected,
            "dtcCodes": self.dtcCodes,
        }
