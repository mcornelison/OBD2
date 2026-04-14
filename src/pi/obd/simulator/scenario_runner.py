################################################################################
# File Name: scenario_runner.py
# Purpose/Description: DriveScenarioRunner class — executes a scenario on a SensorSimulator
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
DriveScenarioRunner — executes a DriveScenario on a SensorSimulator with
smooth phase transitions, callbacks for phase events, and optional looping.
"""

import logging
from collections.abc import Callable
from typing import Any

from .scenario_types import (
    DEFAULT_TRANSITION_RATE_RPM_PER_SEC,
    DEFAULT_TRANSITION_RATE_SPEED_PER_SEC,
    DEFAULT_TRANSITION_RATE_THROTTLE_PER_SEC,
    DrivePhase,
    DriveScenario,
    ScenarioState,
)
from .sensor_simulator import SensorSimulator

logger = logging.getLogger(__name__)


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
        self._currentTargetRpm: float | None = None
        self._currentTargetSpeedKph: float | None = None
        self._currentTargetThrottle: float | None = None
        self._currentTargetGear: int | None = None

        # Callbacks
        self.onPhaseStart: Callable[[DrivePhase], None] | None = None
        self.onPhaseEnd: Callable[[DrivePhase], None] | None = None
        self.onScenarioComplete: Callable[[], None] | None = None
        self.onLoopComplete: Callable[[int], None] | None = None

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

    def getCurrentPhase(self) -> DrivePhase | None:
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

    def getStatus(self) -> dict[str, Any]:
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
