################################################################################
# File Name: simulator_status.py
# Purpose/Description: Simulator status display and monitoring for US-041
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-041
# ================================================================================
################################################################################

"""
Simulator status module for the Eclipse OBD-II simulator.

Provides:
- SimulatorStatus dataclass with current simulator state
- SimulatorStatusProvider class for aggregating status from multiple components
- getSimulatorStatus() function for retrieving current status

The status includes:
- isRunning: Whether simulation is actively running
- currentPhase: Current scenario phase name (if running scenario)
- elapsedSeconds: Total elapsed simulation time
- activeFailures: List of active failure injection types
- vehicleState: Current vehicle state snapshot

Usage:
    from obd.simulator.simulator_status import (
        SimulatorStatus,
        SimulatorStatusProvider,
        getSimulatorStatus,
    )

    # Create provider with simulator components
    provider = SimulatorStatusProvider(
        simulator=simulator,
        scenarioRunner=runner,
        failureInjector=injector,
    )

    # Get current status
    status = provider.getStatus()
    print(f"Running: {status.isRunning}")
    print(f"Phase: {status.currentPhase}")
    print(f"Failures: {status.activeFailures}")
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .sensor_simulator import SensorSimulator, VehicleState

logger = logging.getLogger(__name__)


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class SimulatorStatus:
    """
    Current status of the OBD-II simulator.

    Contains a snapshot of the simulator's current state, including
    scenario execution, failure injections, and vehicle state.

    Attributes:
        isRunning: Whether the simulation is actively running
        currentPhase: Name of current scenario phase (if running scenario)
        elapsedSeconds: Total elapsed simulation time in seconds
        activeFailures: List of active failure type strings
        vehicleState: Current vehicle state snapshot (VehicleState dataclass)
        isSimulationMode: Whether system is in simulation mode
        scenarioName: Name of current scenario (if running)
        scenarioProgress: Progress through current scenario (0-100%)
        loopsCompleted: Number of scenario loops completed
    """

    isRunning: bool = False
    currentPhase: Optional[str] = None
    elapsedSeconds: float = 0.0
    activeFailures: List[str] = field(default_factory=list)
    vehicleState: Optional[VehicleState] = None
    isSimulationMode: bool = False
    scenarioName: Optional[str] = None
    scenarioProgress: float = 0.0
    loopsCompleted: int = 0

    def toDict(self) -> Dict[str, Any]:
        """
        Convert status to dictionary for serialization.

        Returns:
            Dictionary with all status fields
        """
        vehicleDict = None
        if self.vehicleState is not None:
            vehicleDict = {
                "rpm": self.vehicleState.rpm,
                "speedKph": self.vehicleState.speedKph,
                "coolantTempC": self.vehicleState.coolantTempC,
                "throttlePercent": self.vehicleState.throttlePercent,
                "engineLoad": self.vehicleState.engineLoad,
                "fuelLevelPercent": self.vehicleState.fuelLevelPercent,
                "mafGPerSec": self.vehicleState.mafGPerSec,
                "intakeTempC": self.vehicleState.intakeTempC,
                "oilTempC": self.vehicleState.oilTempC,
                "gear": self.vehicleState.gear,
            }

        return {
            "isRunning": self.isRunning,
            "currentPhase": self.currentPhase,
            "elapsedSeconds": self.elapsedSeconds,
            "activeFailures": self.activeFailures,
            "vehicleState": vehicleDict,
            "isSimulationMode": self.isSimulationMode,
            "scenarioName": self.scenarioName,
            "scenarioProgress": self.scenarioProgress,
            "loopsCompleted": self.loopsCompleted,
        }


# ================================================================================
# SimulatorStatusProvider Class
# ================================================================================

class SimulatorStatusProvider:
    """
    Provides aggregated simulator status from multiple components.

    Aggregates status information from:
    - SensorSimulator: Vehicle state and engine running status
    - DriveScenarioRunner: Current phase, progress, elapsed time
    - FailureInjector: Active failure injections

    Example:
        provider = SimulatorStatusProvider(
            simulator=simulator,
            scenarioRunner=runner,
            failureInjector=injector,
        )
        status = provider.getStatus()
    """

    def __init__(
        self,
        simulator: SensorSimulator,
        scenarioRunner: Optional[Any] = None,
        failureInjector: Optional[Any] = None,
    ) -> None:
        """
        Initialize SimulatorStatusProvider.

        Args:
            simulator: SensorSimulator instance (required)
            scenarioRunner: DriveScenarioRunner instance (optional)
            failureInjector: FailureInjector instance (optional)
        """
        self.simulator = simulator
        self.scenarioRunner = scenarioRunner
        self.failureInjector = failureInjector

        logger.debug(
            f"SimulatorStatusProvider initialized | "
            f"hasRunner={scenarioRunner is not None} | "
            f"hasInjector={failureInjector is not None}"
        )

    def getStatus(self) -> SimulatorStatus:
        """
        Get current simulator status.

        Aggregates status from all configured components into a single
        SimulatorStatus object.

        Returns:
            SimulatorStatus with current state
        """
        # Get vehicle state and running status from simulator
        isRunning = self.simulator.isRunning()
        vehicleState = self._captureVehicleState()

        # Get scenario info if runner is available
        currentPhase = None
        scenarioName = None
        scenarioProgress = 0.0
        elapsedSeconds = 0.0
        loopsCompleted = 0

        if self.scenarioRunner is not None:
            # Import ScenarioState locally to avoid circular imports
            from .drive_scenario import ScenarioState

            runnerState = self.scenarioRunner.state
            if runnerState in (ScenarioState.RUNNING, ScenarioState.PAUSED):
                isRunning = True

            currentPhaseObj = self.scenarioRunner.getCurrentPhase()
            if currentPhaseObj is not None:
                currentPhase = currentPhaseObj.name

            scenarioName = self.scenarioRunner.scenario.name
            scenarioProgress = self.scenarioRunner.getProgress()
            elapsedSeconds = self.scenarioRunner.totalElapsedSeconds
            loopsCompleted = self.scenarioRunner.loopsCompleted

        # Get active failures if injector is available
        activeFailures: List[str] = []
        if self.failureInjector is not None:
            activeFailuresDict = self.failureInjector.getActiveFailures()
            activeFailures = list(activeFailuresDict.keys())

        return SimulatorStatus(
            isRunning=isRunning,
            currentPhase=currentPhase,
            elapsedSeconds=elapsedSeconds,
            activeFailures=activeFailures,
            vehicleState=vehicleState,
            isSimulationMode=True,  # Always true when using this provider
            scenarioName=scenarioName,
            scenarioProgress=scenarioProgress,
            loopsCompleted=loopsCompleted,
        )

    def _captureVehicleState(self) -> Optional[VehicleState]:
        """
        Capture current vehicle state from simulator.

        Returns a copy of the current state to avoid mutation issues.

        Returns:
            VehicleState snapshot or None if not available
        """
        if not hasattr(self.simulator, 'state'):
            return None

        state = self.simulator.state

        # Create a copy of the state
        return VehicleState(
            rpm=state.rpm,
            speedKph=state.speedKph,
            coolantTempC=state.coolantTempC,
            throttlePercent=state.throttlePercent,
            engineLoad=state.engineLoad,
            fuelLevelPercent=state.fuelLevelPercent,
            mafGPerSec=state.mafGPerSec,
            intakeTempC=state.intakeTempC,
            oilTempC=state.oilTempC,
            intakePressureKpa=state.intakePressureKpa,
            fuelPressureKpa=state.fuelPressureKpa,
            timingAdvanceDeg=state.timingAdvanceDeg,
            o2Voltage=state.o2Voltage,
            shortFuelTrimPercent=state.shortFuelTrimPercent,
            longFuelTrimPercent=state.longFuelTrimPercent,
            gear=state.gear,
            engineRunTimeSeconds=state.engineRunTimeSeconds,
            controlModuleVoltage=state.controlModuleVoltage,
        )


# ================================================================================
# Helper Functions
# ================================================================================

def getSimulatorStatus(
    simulator: Optional[SensorSimulator] = None,
    scenarioRunner: Optional[Any] = None,
    failureInjector: Optional[Any] = None,
) -> SimulatorStatus:
    """
    Get current simulator status.

    Convenience function that creates a SimulatorStatusProvider and
    returns the current status.

    Args:
        simulator: SensorSimulator instance (required)
        scenarioRunner: DriveScenarioRunner instance (optional)
        failureInjector: FailureInjector instance (optional)

    Returns:
        SimulatorStatus with current state

    Raises:
        ValueError: If simulator is None

    Example:
        status = getSimulatorStatus(
            simulator=simulator,
            scenarioRunner=runner,
            failureInjector=injector,
        )
        print(f"Running: {status.isRunning}")
    """
    if simulator is None:
        raise ValueError("simulator is required")

    provider = SimulatorStatusProvider(
        simulator=simulator,
        scenarioRunner=scenarioRunner,
        failureInjector=failureInjector,
    )

    return provider.getStatus()


def createSimulatorStatusProvider(
    simulator: SensorSimulator,
    scenarioRunner: Optional[Any] = None,
    failureInjector: Optional[Any] = None,
    config: Optional[Dict[str, Any]] = None,
) -> SimulatorStatusProvider:
    """
    Create a SimulatorStatusProvider from configuration.

    Args:
        simulator: SensorSimulator instance (required)
        scenarioRunner: DriveScenarioRunner instance (optional)
        failureInjector: FailureInjector instance (optional)
        config: Configuration dictionary (optional, for future use)

    Returns:
        Configured SimulatorStatusProvider instance

    Example:
        provider = createSimulatorStatusProvider(
            simulator=simulator,
            scenarioRunner=runner,
            failureInjector=injector,
            config={"simulator": {"enabled": True}}
        )
    """
    # Config is available for future extensions (e.g., filtering, caching)
    _ = config

    return SimulatorStatusProvider(
        simulator=simulator,
        scenarioRunner=scenarioRunner,
        failureInjector=failureInjector,
    )
