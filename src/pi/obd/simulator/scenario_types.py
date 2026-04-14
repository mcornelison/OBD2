################################################################################
# File Name: scenario_types.py
# Purpose/Description: Shared types for drive scenario system (enums, exceptions, dataclasses)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-037
# 2026-04-14    | Sweep 5       | Extracted from drive_scenario.py (task 4 split)
# ================================================================================
################################################################################

"""
Shared types for the drive scenario subpackage.

Provides:
- ScenarioState enum
- DriveScenarioError, ScenarioLoadError, ScenarioValidationError exceptions
- DrivePhase dataclass (single phase target)
- DriveScenario dataclass (ordered list of phases with optional looping)
- Scenario-level constants (transition rates, directory name)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ================================================================================
# Constants
# ================================================================================

# Transition smoothing
DEFAULT_TRANSITION_RATE_RPM_PER_SEC = 2000.0  # RPM change rate during transitions
DEFAULT_TRANSITION_RATE_SPEED_PER_SEC = 30.0  # km/h change rate
DEFAULT_TRANSITION_RATE_THROTTLE_PER_SEC = 50.0  # % change rate

# Scenarios directory
SCENARIOS_DIR_NAME = "scenarios"


# ================================================================================
# Enums
# ================================================================================

class ScenarioState(Enum):
    """State of scenario execution."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


# ================================================================================
# Exceptions
# ================================================================================

class DriveScenarioError(Exception):
    """Base exception for drive scenario errors."""

    pass


class ScenarioLoadError(DriveScenarioError):
    """Error loading scenario from file."""

    pass


class ScenarioValidationError(DriveScenarioError):
    """Scenario validation failed."""

    def __init__(self, message: str, invalidFields: list[str] | None = None) -> None:
        super().__init__(message)
        self.invalidFields = invalidFields or []


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class DrivePhase:
    """
    A single phase within a drive scenario.

    Represents a target state for the vehicle to reach and maintain
    for a specified duration.

    Attributes:
        name: Human-readable name for the phase
        durationSeconds: How long to maintain this phase
        targetRpm: Target engine RPM (None = don't change)
        targetSpeedKph: Target speed in km/h (None = don't change)
        targetThrottle: Target throttle percentage 0-100 (None = don't change)
        targetGear: Target gear (None = automatic based on speed)
        description: Optional longer description of the phase
    """

    name: str
    durationSeconds: float
    targetRpm: float | None = None
    targetSpeedKph: float | None = None
    targetThrottle: float | None = None
    targetGear: int | None = None
    description: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert phase to dictionary."""
        result: dict[str, Any] = {
            "name": self.name,
            "durationSeconds": self.durationSeconds,
        }
        if self.targetRpm is not None:
            result["targetRpm"] = self.targetRpm
        if self.targetSpeedKph is not None:
            result["targetSpeedKph"] = self.targetSpeedKph
        if self.targetThrottle is not None:
            result["targetThrottle"] = self.targetThrottle
        if self.targetGear is not None:
            result["targetGear"] = self.targetGear
        if self.description is not None:
            result["description"] = self.description
        return result

    @staticmethod
    def fromDict(data: dict[str, Any]) -> "DrivePhase":
        """
        Create DrivePhase from dictionary.

        Args:
            data: Dictionary with phase fields

        Returns:
            DrivePhase instance

        Raises:
            ScenarioValidationError: If required fields are missing
        """
        invalidFields = []
        if "name" not in data:
            invalidFields.append("name")
        if "durationSeconds" not in data:
            invalidFields.append("durationSeconds")

        if invalidFields:
            raise ScenarioValidationError(
                f"Missing required fields in phase: {invalidFields}",
                invalidFields=invalidFields
            )

        return DrivePhase(
            name=data["name"],
            durationSeconds=float(data["durationSeconds"]),
            targetRpm=data.get("targetRpm"),
            targetSpeedKph=data.get("targetSpeedKph"),
            targetThrottle=data.get("targetThrottle"),
            targetGear=data.get("targetGear"),
            description=data.get("description"),
        )


@dataclass
class DriveScenario:
    """
    A complete drive scenario consisting of multiple phases.

    Attributes:
        name: Human-readable name for the scenario
        description: Longer description of what the scenario represents
        phases: Ordered list of phases to execute
        loopCount: Number of times to loop (0 = don't loop, -1 = infinite)
    """

    name: str
    description: str
    phases: list[DrivePhase] = field(default_factory=list)
    loopCount: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert scenario to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "phases": [phase.toDict() for phase in self.phases],
            "loopCount": self.loopCount,
        }

    @staticmethod
    def fromDict(data: dict[str, Any]) -> "DriveScenario":
        """
        Create DriveScenario from dictionary.

        Args:
            data: Dictionary with scenario fields

        Returns:
            DriveScenario instance

        Raises:
            ScenarioValidationError: If required fields are missing
        """
        invalidFields = []
        if "name" not in data:
            invalidFields.append("name")
        if "description" not in data:
            invalidFields.append("description")
        if "phases" not in data:
            invalidFields.append("phases")

        if invalidFields:
            raise ScenarioValidationError(
                f"Missing required fields in scenario: {invalidFields}",
                invalidFields=invalidFields
            )

        phases = [DrivePhase.fromDict(p) for p in data["phases"]]

        return DriveScenario(
            name=data["name"],
            description=data["description"],
            phases=phases,
            loopCount=data.get("loopCount", 0),
        )

    def getTotalDuration(self) -> float:
        """
        Get total duration of one pass through the scenario.

        Returns:
            Total duration in seconds
        """
        return sum(phase.durationSeconds for phase in self.phases)

    def validate(self) -> list[str]:
        """
        Validate the scenario.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.name:
            errors.append("Scenario name is required")
        if not self.description:
            errors.append("Scenario description is required")
        if not self.phases:
            errors.append("Scenario must have at least one phase")

        for i, phase in enumerate(self.phases):
            if phase.durationSeconds <= 0:
                errors.append(f"Phase {i} ({phase.name}): duration must be positive")
            if phase.targetRpm is not None and phase.targetRpm < 0:
                errors.append(f"Phase {i} ({phase.name}): targetRpm cannot be negative")
            if phase.targetSpeedKph is not None and phase.targetSpeedKph < 0:
                errors.append(f"Phase {i} ({phase.name}): targetSpeedKph cannot be negative")
            if phase.targetThrottle is not None and not (0 <= phase.targetThrottle <= 100):
                errors.append(f"Phase {i} ({phase.name}): targetThrottle must be 0-100")
            if phase.targetGear is not None and phase.targetGear < 0:
                errors.append(f"Phase {i} ({phase.name}): targetGear cannot be negative")

        return errors
