################################################################################
# File Name: drive_scenario.py
# Purpose/Description: Drive scenario system for repeatable test cycles
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-037
# ================================================================================
################################################################################

"""
Drive scenario module for the Eclipse OBD-II simulator.

Provides:
- DrivePhase dataclass for individual phase definitions
- DriveScenario dataclass for complete scenario definitions
- DriveScenarioRunner class for executing scenarios on SensorSimulator
- Built-in scenarios: cold_start, city_driving, highway_cruise, full_cycle
- Smooth transitions between phases

Scenarios define sequences of driving phases with target values. The runner
executes these phases, smoothly transitioning the simulator between them.

Usage:
    from obd.simulator.drive_scenario import (
        DriveScenario, DrivePhase, DriveScenarioRunner,
        loadScenario, getBuiltInScenario
    )

    # Load a scenario
    scenario = getBuiltInScenario('city_driving')

    # Create runner with simulator
    runner = DriveScenarioRunner(simulator, scenario)

    # Set up callbacks
    runner.onPhaseStart = lambda phase: print(f"Starting: {phase.name}")
    runner.onPhaseEnd = lambda phase: print(f"Ended: {phase.name}")
    runner.onScenarioComplete = lambda: print("Scenario complete!")

    # Run scenario
    runner.start()
    while runner.isRunning():
        runner.update(0.1)  # Update every 100ms
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .sensor_simulator import SensorSimulator

logger = logging.getLogger(__name__)


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

    def __init__(self, message: str, invalidFields: Optional[List[str]] = None) -> None:
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
    targetRpm: Optional[float] = None
    targetSpeedKph: Optional[float] = None
    targetThrottle: Optional[float] = None
    targetGear: Optional[int] = None
    description: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert phase to dictionary."""
        result: Dict[str, Any] = {
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
    def fromDict(data: Dict[str, Any]) -> "DrivePhase":
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
    phases: List[DrivePhase] = field(default_factory=list)
    loopCount: int = 0

    def toDict(self) -> Dict[str, Any]:
        """Convert scenario to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "phases": [phase.toDict() for phase in self.phases],
            "loopCount": self.loopCount,
        }

    @staticmethod
    def fromDict(data: Dict[str, Any]) -> "DriveScenario":
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

    def validate(self) -> List[str]:
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


# ================================================================================
# DriveScenarioRunner Class
# ================================================================================

class DriveScenarioRunner:
    """
    Executes a DriveScenario on a SensorSimulator.

    Handles phase transitions with smooth interpolation, callbacks for
    phase events, and scenario looping.

    Attributes:
        simulator: The SensorSimulator to control
        scenario: The DriveScenario to execute
        state: Current execution state
        currentPhaseIndex: Index of current phase (0-based)
        phaseElapsedSeconds: Time elapsed in current phase
        totalElapsedSeconds: Total scenario execution time
        loopsCompleted: Number of complete loops executed

    Callbacks:
        onPhaseStart: Called when a phase begins (receives DrivePhase)
        onPhaseEnd: Called when a phase ends (receives DrivePhase)
        onScenarioComplete: Called when entire scenario completes (no args)
        onLoopComplete: Called when one loop completes (receives loop number)

    Example:
        runner = DriveScenarioRunner(simulator, scenario)
        runner.onPhaseStart = lambda p: print(f"Starting: {p.name}")
        runner.start()
        while runner.isRunning():
            runner.update(0.1)
    """

    def __init__(
        self,
        simulator: SensorSimulator,
        scenario: DriveScenario,
        transitionRateRpm: float = DEFAULT_TRANSITION_RATE_RPM_PER_SEC,
        transitionRateSpeed: float = DEFAULT_TRANSITION_RATE_SPEED_PER_SEC,
        transitionRateThrottle: float = DEFAULT_TRANSITION_RATE_THROTTLE_PER_SEC,
    ) -> None:
        """
        Initialize scenario runner.

        Args:
            simulator: SensorSimulator to control
            scenario: DriveScenario to execute
            transitionRateRpm: RPM change rate per second during transitions
            transitionRateSpeed: Speed change rate (km/h per second)
            transitionRateThrottle: Throttle change rate (% per second)
        """
        self.simulator = simulator
        self.scenario = scenario
        self.transitionRateRpm = transitionRateRpm
        self.transitionRateSpeed = transitionRateSpeed
        self.transitionRateThrottle = transitionRateThrottle

        # Execution state
        self.state = ScenarioState.IDLE
        self.currentPhaseIndex = 0
        self.phaseElapsedSeconds = 0.0
        self.totalElapsedSeconds = 0.0
        self.loopsCompleted = 0

        # Current targets for smooth transitions
        self._currentTargetRpm: Optional[float] = None
        self._currentTargetSpeedKph: Optional[float] = None
        self._currentTargetThrottle: Optional[float] = None
        self._currentTargetGear: Optional[int] = None

        # Callbacks
        self.onPhaseStart: Optional[Callable[[DrivePhase], None]] = None
        self.onPhaseEnd: Optional[Callable[[DrivePhase], None]] = None
        self.onScenarioComplete: Optional[Callable[[], None]] = None
        self.onLoopComplete: Optional[Callable[[int], None]] = None

        logger.debug(f"DriveScenarioRunner initialized with scenario: {scenario.name}")

    # ==========================================================================
    # Execution Control
    # ==========================================================================

    def start(self) -> bool:
        """
        Start scenario execution.

        Returns:
            True if started successfully
        """
        if self.state == ScenarioState.RUNNING:
            logger.warning("Scenario already running")
            return False

        if not self.scenario.phases:
            logger.error("Cannot start scenario with no phases")
            self.state = ScenarioState.ERROR
            return False

        # Validate scenario
        errors = self.scenario.validate()
        if errors:
            logger.error(f"Scenario validation failed: {errors}")
            self.state = ScenarioState.ERROR
            return False

        # Ensure engine is running
        if not self.simulator.isRunning():
            self.simulator.startEngine()

        # Reset state
        self.currentPhaseIndex = 0
        self.phaseElapsedSeconds = 0.0
        self.totalElapsedSeconds = 0.0
        self.loopsCompleted = 0
        self.state = ScenarioState.RUNNING

        # Start first phase
        self._beginPhase(0)

        logger.info(f"Started scenario: {self.scenario.name}")
        return True

    def stop(self) -> None:
        """Stop scenario execution."""
        if self.state == ScenarioState.IDLE:
            return

        logger.info(f"Stopping scenario: {self.scenario.name}")
        self.state = ScenarioState.IDLE
        self.currentPhaseIndex = 0
        self.phaseElapsedSeconds = 0.0

    def pause(self) -> None:
        """Pause scenario execution."""
        if self.state == ScenarioState.RUNNING:
            logger.debug("Pausing scenario")
            self.state = ScenarioState.PAUSED

    def resume(self) -> None:
        """Resume paused scenario."""
        if self.state == ScenarioState.PAUSED:
            logger.debug("Resuming scenario")
            self.state = ScenarioState.RUNNING

    def isRunning(self) -> bool:
        """Check if scenario is currently running."""
        return self.state == ScenarioState.RUNNING

    def isPaused(self) -> bool:
        """Check if scenario is paused."""
        return self.state == ScenarioState.PAUSED

    def isCompleted(self) -> bool:
        """Check if scenario has completed."""
        return self.state == ScenarioState.COMPLETED

    # ==========================================================================
    # Update Loop
    # ==========================================================================

    def update(self, deltaSeconds: float) -> None:
        """
        Update scenario execution.

        Call this method regularly (e.g., every 100ms) to advance
        the scenario and update the simulator.

        Args:
            deltaSeconds: Time elapsed since last update
        """
        if self.state != ScenarioState.RUNNING:
            return

        if deltaSeconds <= 0:
            return

        # Update elapsed time
        self.phaseElapsedSeconds += deltaSeconds
        self.totalElapsedSeconds += deltaSeconds

        # Apply smooth transitions
        self._applyTransitions(deltaSeconds)

        # Update simulator
        self.simulator.update(deltaSeconds)

        # Check if current phase is complete
        currentPhase = self.getCurrentPhase()
        if currentPhase and self.phaseElapsedSeconds >= currentPhase.durationSeconds:
            self._endCurrentPhase()

    def _applyTransitions(self, deltaSeconds: float) -> None:
        """Apply smooth transitions toward target values."""
        # Calculate throttle to achieve target RPM/speed
        if self._currentTargetThrottle is not None:
            currentThrottle = self.simulator.state.throttlePercent
            targetThrottle = self._currentTargetThrottle
            maxChange = self.transitionRateThrottle * deltaSeconds
            diff = targetThrottle - currentThrottle
            change = max(-maxChange, min(maxChange, diff))
            newThrottle = currentThrottle + change
            self.simulator.setThrottle(newThrottle)

        # Set gear if specified
        if self._currentTargetGear is not None:
            self.simulator.setGear(self._currentTargetGear)
        else:
            # Auto-select gear based on speed
            self._autoSelectGear()

    def _autoSelectGear(self) -> None:
        """Automatically select gear based on current speed."""
        speed = self.simulator.state.speedKph

        # Simple gear selection based on speed thresholds
        if speed < 15:
            gear = 1
        elif speed < 30:
            gear = 2
        elif speed < 50:
            gear = 3
        elif speed < 80:
            gear = 4
        else:
            gear = 5

        self.simulator.setGear(gear)

    # ==========================================================================
    # Phase Management
    # ==========================================================================

    def _beginPhase(self, phaseIndex: int) -> None:
        """Begin a new phase."""
        if phaseIndex >= len(self.scenario.phases):
            return

        phase = self.scenario.phases[phaseIndex]
        self.currentPhaseIndex = phaseIndex
        self.phaseElapsedSeconds = 0.0

        # Set target values
        self._currentTargetRpm = phase.targetRpm
        self._currentTargetSpeedKph = phase.targetSpeedKph
        self._currentTargetThrottle = phase.targetThrottle
        self._currentTargetGear = phase.targetGear

        # If no explicit throttle but we have RPM target, calculate throttle
        if self._currentTargetThrottle is None and self._currentTargetRpm is not None:
            self._currentTargetThrottle = self._calculateThrottleForRpm(
                self._currentTargetRpm
            )

        # If no explicit throttle but we have speed target, calculate throttle
        if self._currentTargetThrottle is None and self._currentTargetSpeedKph is not None:
            self._currentTargetThrottle = self._calculateThrottleForSpeed(
                self._currentTargetSpeedKph
            )

        logger.debug(f"Beginning phase {phaseIndex}: {phase.name}")

        # Fire callback
        if self.onPhaseStart:
            try:
                self.onPhaseStart(phase)
            except Exception as e:
                logger.error(f"onPhaseStart callback error: {e}")

    def _endCurrentPhase(self) -> None:
        """End the current phase and advance to next."""
        currentPhase = self.getCurrentPhase()
        if not currentPhase:
            return

        logger.debug(f"Ending phase {self.currentPhaseIndex}: {currentPhase.name}")

        # Fire callback
        if self.onPhaseEnd:
            try:
                self.onPhaseEnd(currentPhase)
            except Exception as e:
                logger.error(f"onPhaseEnd callback error: {e}")

        # Move to next phase
        nextIndex = self.currentPhaseIndex + 1

        if nextIndex >= len(self.scenario.phases):
            # End of phases - check for looping
            self._handleLoopEnd()
        else:
            # Continue to next phase
            self._beginPhase(nextIndex)

    def _handleLoopEnd(self) -> None:
        """Handle end of one pass through the scenario."""
        self.loopsCompleted += 1

        # Fire loop complete callback
        if self.onLoopComplete:
            try:
                self.onLoopComplete(self.loopsCompleted)
            except Exception as e:
                logger.error(f"onLoopComplete callback error: {e}")

        # Check if we should loop
        shouldLoop = False
        if self.scenario.loopCount < 0:
            # Infinite loop
            shouldLoop = True
        elif self.scenario.loopCount > 0 and self.loopsCompleted < self.scenario.loopCount:
            # More loops remaining
            shouldLoop = True

        if shouldLoop:
            logger.debug(f"Loop {self.loopsCompleted} complete, starting next loop")
            self._beginPhase(0)
        else:
            # Scenario complete
            self._completeScenario()

    def _completeScenario(self) -> None:
        """Mark scenario as complete."""
        logger.info(f"Scenario complete: {self.scenario.name} "
                    f"({self.loopsCompleted} loops, {self.totalElapsedSeconds:.1f}s)")
        self.state = ScenarioState.COMPLETED

        # Fire callback
        if self.onScenarioComplete:
            try:
                self.onScenarioComplete()
            except Exception as e:
                logger.error(f"onScenarioComplete callback error: {e}")

    def _calculateThrottleForRpm(self, targetRpm: float) -> float:
        """Calculate throttle needed to achieve target RPM."""
        profile = self.simulator.profile
        rpmRange = profile.redlineRpm - profile.idleRpm

        if rpmRange <= 0:
            return 0.0

        # Inverse of RPM calculation in sensor_simulator
        # targetRpm = idleRpm + (rpmRange * throttle * sensitivity)
        # throttle = (targetRpm - idleRpm) / (rpmRange * sensitivity)
        sensitivity = 1.2  # From sensor_simulator
        throttle = ((targetRpm - profile.idleRpm) / (rpmRange * sensitivity)) * 100.0

        return max(0.0, min(100.0, throttle))

    def _calculateThrottleForSpeed(self, targetSpeedKph: float) -> float:
        """Calculate throttle needed to achieve target speed."""
        # Simplified: map speed to throttle linearly
        # Assume max speed at ~80% throttle
        profile = self.simulator.profile
        maxSpeed = profile.maxSpeedKph

        if maxSpeed <= 0:
            return 0.0

        throttle = (targetSpeedKph / maxSpeed) * 80.0
        return max(0.0, min(100.0, throttle))

    # ==========================================================================
    # State Access
    # ==========================================================================

    def getCurrentPhase(self) -> Optional[DrivePhase]:
        """
        Get current phase being executed.

        Returns:
            Current DrivePhase, or None if not running
        """
        if 0 <= self.currentPhaseIndex < len(self.scenario.phases):
            return self.scenario.phases[self.currentPhaseIndex]
        return None

    def getProgress(self) -> float:
        """
        Get overall scenario progress as percentage.

        Returns:
            Progress 0-100 (does not account for loops)
        """
        totalDuration = self.scenario.getTotalDuration()
        if totalDuration <= 0:
            return 0.0

        # Calculate progress through current loop
        completedDuration = sum(
            self.scenario.phases[i].durationSeconds
            for i in range(self.currentPhaseIndex)
        )
        currentPhaseDuration = 0.0
        currentPhase = self.getCurrentPhase()
        if currentPhase:
            currentPhaseDuration = min(
                self.phaseElapsedSeconds,
                currentPhase.durationSeconds
            )

        elapsed = completedDuration + currentPhaseDuration
        return min(100.0, (elapsed / totalDuration) * 100.0)

    def getPhaseProgress(self) -> float:
        """
        Get progress through current phase as percentage.

        Returns:
            Progress 0-100
        """
        currentPhase = self.getCurrentPhase()
        if not currentPhase or currentPhase.durationSeconds <= 0:
            return 0.0

        return min(100.0,
                   (self.phaseElapsedSeconds / currentPhase.durationSeconds) * 100.0)

    def getStatus(self) -> Dict[str, Any]:
        """
        Get comprehensive status of scenario execution.

        Returns:
            Dictionary with execution status
        """
        currentPhase = self.getCurrentPhase()
        return {
            "state": self.state.value,
            "scenarioName": self.scenario.name,
            "currentPhaseIndex": self.currentPhaseIndex,
            "currentPhaseName": currentPhase.name if currentPhase else None,
            "phaseElapsedSeconds": self.phaseElapsedSeconds,
            "totalElapsedSeconds": self.totalElapsedSeconds,
            "loopsCompleted": self.loopsCompleted,
            "overallProgress": self.getProgress(),
            "phaseProgress": self.getPhaseProgress(),
            "totalPhases": len(self.scenario.phases),
        }


# ================================================================================
# Loading Functions
# ================================================================================

def getScenariosDirectory() -> str:
    """
    Get the scenarios directory path.

    Returns:
        Absolute path to scenarios directory
    """
    moduleDir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(moduleDir, SCENARIOS_DIR_NAME)


def loadScenario(path: str) -> DriveScenario:
    """
    Load a scenario from a JSON file.

    Args:
        path: Path to scenario JSON file

    Returns:
        Loaded DriveScenario

    Raises:
        ScenarioLoadError: If file cannot be loaded or parsed
        ScenarioValidationError: If scenario is invalid
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ScenarioLoadError(f"Scenario file not found: {path}")
    except json.JSONDecodeError as e:
        raise ScenarioLoadError(f"Invalid JSON in scenario file: {e}")

    try:
        scenario = DriveScenario.fromDict(data)
    except ScenarioValidationError:
        raise
    except Exception as e:
        raise ScenarioLoadError(f"Failed to parse scenario: {e}")

    # Validate scenario
    errors = scenario.validate()
    if errors:
        raise ScenarioValidationError(
            f"Scenario validation failed: {errors}",
            invalidFields=errors
        )

    logger.debug(f"Loaded scenario '{scenario.name}' from {path}")
    return scenario


def saveScenario(scenario: DriveScenario, path: str) -> None:
    """
    Save a scenario to a JSON file.

    Args:
        scenario: DriveScenario to save
        path: Path to save to
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scenario.toDict(), f, indent=2)
    logger.debug(f"Saved scenario '{scenario.name}' to {path}")


def listAvailableScenarios() -> List[str]:
    """
    List available scenario files in the scenarios directory.

    Returns:
        List of scenario filenames (without .json extension)
    """
    scenariosDir = getScenariosDirectory()
    if not os.path.exists(scenariosDir):
        return []

    scenarios = []
    for filename in os.listdir(scenariosDir):
        if filename.endswith(".json"):
            scenarios.append(filename[:-5])  # Remove .json

    return sorted(scenarios)


def getBuiltInScenario(name: str) -> DriveScenario:
    """
    Get a built-in scenario by name.

    Args:
        name: Scenario name (e.g., 'city_driving', 'highway_cruise')

    Returns:
        DriveScenario instance

    Raises:
        ScenarioLoadError: If scenario not found
    """
    scenariosDir = getScenariosDirectory()
    path = os.path.join(scenariosDir, f"{name}.json")

    if not os.path.exists(path):
        raise ScenarioLoadError(f"Built-in scenario not found: {name}")

    return loadScenario(path)


def createScenarioFromConfig(config: Dict[str, Any]) -> DriveScenario:
    """
    Create a scenario from configuration.

    Args:
        config: Configuration dict, may contain 'simulator.scenarioPath'
                or 'scenarioPath' or inline 'scenario' definition

    Returns:
        DriveScenario instance

    Raises:
        ScenarioLoadError: If scenario cannot be loaded
    """
    # Check for inline scenario definition
    if "scenario" in config:
        return DriveScenario.fromDict(config["scenario"])

    # Check for scenario path in simulator config
    simConfig = config.get("simulator", {})
    scenarioPath = simConfig.get("scenarioPath") or config.get("scenarioPath")

    if scenarioPath:
        return loadScenario(scenarioPath)

    # Return default scenario
    return getDefaultScenario()


def getDefaultScenario() -> DriveScenario:
    """
    Get a simple default scenario.

    Returns:
        DriveScenario with basic warmup/idle/drive/stop phases
    """
    return DriveScenario(
        name="default",
        description="Simple default scenario for testing",
        phases=[
            DrivePhase(
                name="warmup",
                durationSeconds=30.0,
                targetRpm=800,
                targetThrottle=0,
                description="Engine warmup at idle"
            ),
            DrivePhase(
                name="drive",
                durationSeconds=60.0,
                targetRpm=2500,
                targetThrottle=30,
                targetGear=3,
                description="Light driving"
            ),
            DrivePhase(
                name="stop",
                durationSeconds=10.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Return to idle"
            ),
        ],
        loopCount=0,
    )


# ================================================================================
# Built-in Scenario Definitions (used to create JSON files)
# ================================================================================

def getColdStartScenario() -> DriveScenario:
    """Get cold start scenario definition."""
    return DriveScenario(
        name="cold_start",
        description="Simulates cold engine start and warmup cycle",
        phases=[
            DrivePhase(
                name="engine_start",
                durationSeconds=5.0,
                targetRpm=1200,
                targetThrottle=5,
                description="Initial startup with cold fast idle"
            ),
            DrivePhase(
                name="cold_idle",
                durationSeconds=60.0,
                targetRpm=1000,
                targetThrottle=0,
                description="Cold idle warmup - RPM slowly drops as engine warms"
            ),
            DrivePhase(
                name="warm_idle",
                durationSeconds=30.0,
                targetRpm=800,
                targetThrottle=0,
                description="Warmed up idle"
            ),
        ],
        loopCount=0,
    )


def getCityDrivingScenario() -> DriveScenario:
    """Get city driving scenario definition."""
    return DriveScenario(
        name="city_driving",
        description="Simulates typical city driving with stops and acceleration",
        phases=[
            DrivePhase(
                name="idle_start",
                durationSeconds=5.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Stopped at traffic light"
            ),
            DrivePhase(
                name="accelerate_1st",
                durationSeconds=3.0,
                targetRpm=3000,
                targetThrottle=40,
                targetGear=1,
                description="Accelerate from stop in 1st gear"
            ),
            DrivePhase(
                name="shift_2nd",
                durationSeconds=4.0,
                targetRpm=2500,
                targetThrottle=35,
                targetGear=2,
                description="Shift to 2nd, continue accelerating"
            ),
            DrivePhase(
                name="shift_3rd",
                durationSeconds=5.0,
                targetRpm=2500,
                targetThrottle=30,
                targetGear=3,
                description="Shift to 3rd, cruise at city speed"
            ),
            DrivePhase(
                name="cruise",
                durationSeconds=15.0,
                targetRpm=2000,
                targetThrottle=25,
                targetGear=3,
                description="Cruise at ~50 km/h"
            ),
            DrivePhase(
                name="slow_down",
                durationSeconds=5.0,
                targetRpm=1500,
                targetThrottle=5,
                targetGear=2,
                description="Slow for traffic/light"
            ),
            DrivePhase(
                name="stop",
                durationSeconds=10.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Stopped at traffic light"
            ),
        ],
        loopCount=3,  # Repeat 3 times
    )


def getHighwayCruiseScenario() -> DriveScenario:
    """Get highway cruise scenario definition."""
    return DriveScenario(
        name="highway_cruise",
        description="Simulates highway on-ramp and cruise",
        phases=[
            DrivePhase(
                name="on_ramp_entry",
                durationSeconds=5.0,
                targetRpm=3500,
                targetThrottle=60,
                targetGear=3,
                description="Entering on-ramp, accelerating"
            ),
            DrivePhase(
                name="on_ramp_merge",
                durationSeconds=8.0,
                targetRpm=5000,
                targetThrottle=80,
                targetGear=4,
                description="Accelerating to highway speed for merge"
            ),
            DrivePhase(
                name="merge_complete",
                durationSeconds=5.0,
                targetRpm=3500,
                targetThrottle=50,
                targetGear=5,
                description="Shift to 5th, settling into cruise"
            ),
            DrivePhase(
                name="highway_cruise",
                durationSeconds=120.0,
                targetRpm=3000,
                targetThrottle=35,
                targetGear=5,
                description="Steady highway cruise at ~120 km/h"
            ),
            DrivePhase(
                name="exit_decel",
                durationSeconds=10.0,
                targetRpm=2000,
                targetThrottle=10,
                targetGear=4,
                description="Exiting highway, decelerating"
            ),
            DrivePhase(
                name="exit_ramp",
                durationSeconds=8.0,
                targetRpm=1500,
                targetThrottle=15,
                targetGear=3,
                description="On exit ramp"
            ),
        ],
        loopCount=0,
    )


def getFullCycleScenario() -> DriveScenario:
    """Get full cycle scenario (cold start + city + highway)."""
    return DriveScenario(
        name="full_cycle",
        description="Complete drive cycle: cold start, city driving, highway cruise",
        phases=[
            # Cold start
            DrivePhase(
                name="engine_start",
                durationSeconds=5.0,
                targetRpm=1200,
                targetThrottle=5,
                description="Cold engine start"
            ),
            DrivePhase(
                name="cold_warmup",
                durationSeconds=45.0,
                targetRpm=1000,
                targetThrottle=0,
                description="Cold idle warmup"
            ),
            # City portion
            DrivePhase(
                name="city_start",
                durationSeconds=3.0,
                targetRpm=2500,
                targetThrottle=35,
                targetGear=1,
                description="Leave driveway"
            ),
            DrivePhase(
                name="neighborhood",
                durationSeconds=30.0,
                targetRpm=2000,
                targetThrottle=25,
                targetGear=2,
                description="Driving through neighborhood"
            ),
            DrivePhase(
                name="city_street",
                durationSeconds=45.0,
                targetRpm=2500,
                targetThrottle=30,
                targetGear=3,
                description="City street driving"
            ),
            DrivePhase(
                name="traffic_stop",
                durationSeconds=20.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Stopped in traffic"
            ),
            # Highway portion
            DrivePhase(
                name="on_ramp",
                durationSeconds=10.0,
                targetRpm=4500,
                targetThrottle=70,
                targetGear=4,
                description="Highway on-ramp acceleration"
            ),
            DrivePhase(
                name="highway_merge",
                durationSeconds=5.0,
                targetRpm=3500,
                targetThrottle=45,
                targetGear=5,
                description="Merging onto highway"
            ),
            DrivePhase(
                name="highway_cruise",
                durationSeconds=180.0,
                targetRpm=3000,
                targetThrottle=35,
                targetGear=5,
                description="Highway cruise"
            ),
            DrivePhase(
                name="highway_exit",
                durationSeconds=15.0,
                targetRpm=1800,
                targetThrottle=15,
                targetGear=4,
                description="Exiting highway"
            ),
            # Return city portion
            DrivePhase(
                name="return_city",
                durationSeconds=30.0,
                targetRpm=2000,
                targetThrottle=25,
                targetGear=3,
                description="City driving back"
            ),
            DrivePhase(
                name="arrival",
                durationSeconds=15.0,
                targetRpm=1500,
                targetThrottle=15,
                targetGear=2,
                description="Arriving at destination"
            ),
            DrivePhase(
                name="park",
                durationSeconds=10.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Parked, idling"
            ),
        ],
        loopCount=0,
    )


# ================================================================================
# Initialization Functions
# ================================================================================

def ensureScenariosDirectory() -> None:
    """Ensure scenarios directory exists."""
    scenariosDir = getScenariosDirectory()
    if not os.path.exists(scenariosDir):
        os.makedirs(scenariosDir)
        logger.debug(f"Created scenarios directory: {scenariosDir}")


def initializeBuiltInScenarios() -> None:
    """
    Initialize built-in scenario JSON files.

    Creates scenario JSON files if they don't exist.
    """
    ensureScenariosDirectory()
    scenariosDir = getScenariosDirectory()

    scenarios = [
        ("cold_start", getColdStartScenario()),
        ("city_driving", getCityDrivingScenario()),
        ("highway_cruise", getHighwayCruiseScenario()),
        ("full_cycle", getFullCycleScenario()),
    ]

    for name, scenario in scenarios:
        path = os.path.join(scenariosDir, f"{name}.json")
        if not os.path.exists(path):
            saveScenario(scenario, path)
            logger.info(f"Created built-in scenario: {name}")
