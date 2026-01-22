################################################################################
# File Name: sensor_simulator.py
# Purpose/Description: Physics-based sensor simulator for OBD-II testing
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-036
# ================================================================================
################################################################################

"""
Sensor simulator module for the Eclipse OBD-II simulator.

Provides:
- SensorSimulator class with physics-based sensor value simulation
- Internal vehicle state tracking (RPM, speed, coolant temp, etc.)
- Realistic noise/variation in sensor values
- Time-based state progression via update()

The simulator maintains internal vehicle state and uses physics rules to
produce realistic OBD-II sensor values that correlate with each other:
- RPM affects speed (via gear ratios)
- Coolant temp rises over time toward operating temperature
- Engine load correlates with throttle position
- Fuel level decreases based on load
- MAF correlates with RPM and throttle

Usage:
    from obd.simulator.sensor_simulator import SensorSimulator
    from obd.simulator.vehicle_profile import getDefaultProfile

    # Create simulator with vehicle profile
    profile = getDefaultProfile()
    simulator = SensorSimulator(profile)

    # Update simulation state
    simulator.setThrottle(0.5)  # 50% throttle
    simulator.update(0.1)  # Advance 100ms

    # Get current sensor values
    rpm = simulator.getValue('RPM')
    speed = simulator.getValue('SPEED')
    coolant = simulator.getValue('COOLANT_TEMP')
"""

import logging
import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

from .vehicle_profile import VehicleProfile, getDefaultProfile

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Physics constants
IDLE_THROTTLE_LOAD = 0.15  # Engine load at idle
MAX_THROTTLE_LOAD = 0.95  # Max engine load at WOT
COOLANT_WARMUP_RATE_C_PER_SEC = 0.3  # Coolant warmup rate in C/sec
COOLANT_AMBIENT_TEMP_C = 20.0  # Ambient temperature in Celsius
FUEL_CONSUMPTION_BASE_L_PER_H = 0.8  # Idle fuel consumption L/h
FUEL_CONSUMPTION_LOAD_FACTOR = 15.0  # Additional L/h at full load
FUEL_TANK_SIZE_L = 60.0  # Default fuel tank size
MAF_IDLE_G_PER_SEC = 3.0  # MAF at idle (grams/sec)
MAF_MAX_G_PER_SEC = 250.0  # MAF at max (grams/sec)

# RPM response characteristics
RPM_RESPONSE_RATE = 5000.0  # RPM change per second at max rate
RPM_THROTTLE_SENSITIVITY = 1.2  # How sensitive RPM is to throttle

# Speed/gear characteristics
GEAR_RATIOS = [0, 3.5, 2.1, 1.4, 1.0, 0.8]  # Neutral + 5 gears
FINAL_DRIVE_RATIO = 4.0
TIRE_CIRCUMFERENCE_M = 2.0  # Typical tire circumference

# Temperature constants
INTAKE_TEMP_BASE_C = 25.0  # Base intake temp
INTAKE_TEMP_LOAD_FACTOR = 15.0  # Additional temp from load
OIL_TEMP_FACTOR = 1.1  # Oil temp = coolant * factor

# Noise levels (percentage of value)
NOISE_LEVEL_DEFAULT = 0.02  # 2% noise
NOISE_LEVEL_LOW = 0.01  # 1% noise for stable sensors
NOISE_LEVEL_HIGH = 0.05  # 5% noise for variable sensors


# ================================================================================
# Enums
# ================================================================================

class EngineState(Enum):
    """Engine operating state."""

    OFF = "off"
    CRANKING = "cranking"
    RUNNING = "running"
    STALLED = "stalled"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class VehicleState:
    """
    Internal vehicle state for simulation.

    Attributes:
        rpm: Current engine RPM
        speedKph: Vehicle speed in km/h
        coolantTempC: Engine coolant temperature in Celsius
        throttlePercent: Throttle position (0-100)
        engineLoad: Calculated engine load (0-100)
        fuelLevelPercent: Fuel tank level (0-100)
        mafGPerSec: Mass air flow in grams/second
        intakeTempC: Intake air temperature in Celsius
        oilTempC: Engine oil temperature in Celsius
        intakePressureKpa: Intake manifold pressure in kPa
        fuelPressureKpa: Fuel pressure in kPa
        timingAdvanceDeg: Ignition timing advance in degrees
        o2Voltage: Oxygen sensor voltage
        shortFuelTrimPercent: Short term fuel trim percentage
        longFuelTrimPercent: Long term fuel trim percentage
        gear: Current gear (0 = neutral)
        engineRunTimeSeconds: Time engine has been running
        controlModuleVoltage: ECU voltage
    """

    rpm: float = 0.0
    speedKph: float = 0.0
    coolantTempC: float = COOLANT_AMBIENT_TEMP_C
    throttlePercent: float = 0.0
    engineLoad: float = 0.0
    fuelLevelPercent: float = 75.0
    mafGPerSec: float = 0.0
    intakeTempC: float = INTAKE_TEMP_BASE_C
    oilTempC: float = COOLANT_AMBIENT_TEMP_C
    intakePressureKpa: float = 101.0  # Atmospheric
    fuelPressureKpa: float = 380.0  # Typical fuel rail pressure
    timingAdvanceDeg: float = 10.0
    o2Voltage: float = 0.45  # Stoichiometric point
    shortFuelTrimPercent: float = 0.0
    longFuelTrimPercent: float = 0.0
    gear: int = 0
    engineRunTimeSeconds: float = 0.0
    controlModuleVoltage: float = 14.2

    def toDict(self) -> Dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "rpm": self.rpm,
            "speedKph": self.speedKph,
            "coolantTempC": self.coolantTempC,
            "throttlePercent": self.throttlePercent,
            "engineLoad": self.engineLoad,
            "fuelLevelPercent": self.fuelLevelPercent,
            "mafGPerSec": self.mafGPerSec,
            "intakeTempC": self.intakeTempC,
            "oilTempC": self.oilTempC,
            "intakePressureKpa": self.intakePressureKpa,
            "fuelPressureKpa": self.fuelPressureKpa,
            "timingAdvanceDeg": self.timingAdvanceDeg,
            "o2Voltage": self.o2Voltage,
            "shortFuelTrimPercent": self.shortFuelTrimPercent,
            "longFuelTrimPercent": self.longFuelTrimPercent,
            "gear": self.gear,
            "engineRunTimeSeconds": self.engineRunTimeSeconds,
            "controlModuleVoltage": self.controlModuleVoltage,
        }


# ================================================================================
# SensorSimulator Class
# ================================================================================

class SensorSimulator:
    """
    Physics-based sensor simulator for OBD-II testing.

    Maintains internal vehicle state and produces realistic sensor values
    that correlate with each other through physics rules.

    Attributes:
        profile: Vehicle profile with specifications
        state: Current vehicle state
        engineState: Current engine operating state
        noiseEnabled: Whether to add realistic noise to values

    Example:
        simulator = SensorSimulator(getDefaultProfile())
        simulator.startEngine()
        simulator.setThrottle(50)  # 50% throttle
        simulator.update(1.0)  # Advance 1 second
        print(f"RPM: {simulator.getValue('RPM')}")
    """

    def __init__(
        self,
        profile: Optional[VehicleProfile] = None,
        noiseEnabled: bool = True
    ) -> None:
        """
        Initialize sensor simulator.

        Args:
            profile: Vehicle profile (uses default if None)
            noiseEnabled: Whether to add realistic noise to values
        """
        self.profile = profile or getDefaultProfile()
        self.state = VehicleState()
        self.engineState = EngineState.OFF
        self.noiseEnabled = noiseEnabled
        self._noiseGenerator: Callable[[], float] = random.gauss
        self._targetRpm: float = 0.0
        self._targetSpeed: float = 0.0

        logger.debug(f"SensorSimulator initialized with profile: {self.profile}")

    # ==========================================================================
    # Engine Control
    # ==========================================================================

    def startEngine(self) -> bool:
        """
        Start the engine.

        Returns:
            True if engine started successfully
        """
        if self.engineState == EngineState.RUNNING:
            return True

        logger.debug("Starting engine...")
        self.engineState = EngineState.CRANKING

        # Cranking RPM
        self.state.rpm = 200.0
        self._targetRpm = float(self.profile.idleRpm)

        # After brief crank, engine running
        self.engineState = EngineState.RUNNING
        self.state.rpm = float(self.profile.idleRpm)
        self.state.engineRunTimeSeconds = 0.0

        logger.info("Engine started")
        return True

    def stopEngine(self) -> None:
        """Stop the engine."""
        logger.debug("Stopping engine...")
        self.engineState = EngineState.OFF
        self.state.rpm = 0.0
        self.state.speedKph = 0.0
        self.state.mafGPerSec = 0.0
        self.state.engineLoad = 0.0
        self._targetRpm = 0.0
        self._targetSpeed = 0.0
        logger.info("Engine stopped")

    def isRunning(self) -> bool:
        """Check if engine is running."""
        return self.engineState == EngineState.RUNNING

    # ==========================================================================
    # Input Controls
    # ==========================================================================

    def setThrottle(self, percent: float) -> None:
        """
        Set throttle position.

        Args:
            percent: Throttle position (0-100)
        """
        self.state.throttlePercent = max(0.0, min(100.0, percent))

    def setGear(self, gear: int) -> None:
        """
        Set transmission gear.

        Args:
            gear: Gear number (0=neutral, 1-5=forward gears)
        """
        maxGear = len(GEAR_RATIOS) - 1
        self.state.gear = max(0, min(maxGear, gear))

    def setFuelLevel(self, percent: float) -> None:
        """
        Set fuel tank level.

        Args:
            percent: Fuel level (0-100)
        """
        self.state.fuelLevelPercent = max(0.0, min(100.0, percent))

    # ==========================================================================
    # Simulation Update
    # ==========================================================================

    def update(self, deltaSeconds: float) -> None:
        """
        Advance simulation by time delta.

        Updates all vehicle state based on physics rules:
        - RPM responds to throttle
        - Speed calculated from RPM and gear
        - Coolant temp rises toward operating temp
        - Load correlates with throttle
        - Fuel decreases based on load
        - MAF correlates with RPM/throttle

        Args:
            deltaSeconds: Time delta in seconds
        """
        if deltaSeconds <= 0:
            return

        if self.engineState != EngineState.RUNNING:
            return

        # Update engine run time
        self.state.engineRunTimeSeconds += deltaSeconds

        # Update RPM based on throttle
        self._updateRpm(deltaSeconds)

        # Update speed based on RPM and gear
        self._updateSpeed(deltaSeconds)

        # Update coolant temperature
        self._updateCoolantTemp(deltaSeconds)

        # Update engine load
        self._updateEngineLoad()

        # Update MAF
        self._updateMaf()

        # Update fuel consumption
        self._updateFuel(deltaSeconds)

        # Update derived values
        self._updateDerivedValues()

    def _updateRpm(self, deltaSeconds: float) -> None:
        """Update RPM based on throttle input."""
        # Calculate target RPM based on throttle
        throttleFraction = self.state.throttlePercent / 100.0
        rpmRange = self.profile.redlineRpm - self.profile.idleRpm
        self._targetRpm = self.profile.idleRpm + (rpmRange * throttleFraction *
                                                   RPM_THROTTLE_SENSITIVITY)
        self._targetRpm = min(self._targetRpm, float(self.profile.maxRpm))

        # Smoothly approach target RPM
        rpmDiff = self._targetRpm - self.state.rpm
        maxChange = RPM_RESPONSE_RATE * deltaSeconds
        change = max(-maxChange, min(maxChange, rpmDiff))
        self.state.rpm += change

        # Ensure idle minimum when engine running
        self.state.rpm = max(float(self.profile.idleRpm), self.state.rpm)

    def _updateSpeed(self, deltaSeconds: float) -> None:
        """Update speed based on RPM and gear."""
        if self.state.gear == 0:
            # In neutral, coast down
            self.state.speedKph = max(0.0, self.state.speedKph - 5.0 * deltaSeconds)
            return

        # Calculate theoretical speed from RPM and gear
        gearRatio = GEAR_RATIOS[self.state.gear]
        # wheel_rpm = engine_rpm / (gear_ratio * final_drive)
        wheelRpm = self.state.rpm / (gearRatio * FINAL_DRIVE_RATIO)
        # speed = wheel_rpm * tire_circumference * 60 / 1000 (m/min to km/h)
        theoreticalSpeed = wheelRpm * TIRE_CIRCUMFERENCE_M * 60.0 / 1000.0

        # Smoothly approach theoretical speed (simulating drivetrain lag)
        speedDiff = theoreticalSpeed - self.state.speedKph
        maxSpeedChange = 20.0 * deltaSeconds  # Max 20 km/h change per second
        change = max(-maxSpeedChange, min(maxSpeedChange, speedDiff))
        self.state.speedKph += change

        # Clamp speed
        self.state.speedKph = max(0.0, min(float(self.profile.maxSpeedKph),
                                           self.state.speedKph))

    def _updateCoolantTemp(self, deltaSeconds: float) -> None:
        """Update coolant temperature toward operating temp."""
        if self.state.coolantTempC < self.profile.normalCoolantTempC:
            # Warming up
            warmupRate = COOLANT_WARMUP_RATE_C_PER_SEC
            # Faster warmup under load
            loadFactor = 1.0 + (self.state.engineLoad / 100.0)
            self.state.coolantTempC += warmupRate * loadFactor * deltaSeconds
            self.state.coolantTempC = min(
                self.state.coolantTempC,
                float(self.profile.normalCoolantTempC)
            )
        elif self.state.coolantTempC > self.profile.normalCoolantTempC:
            # Cooling down (thermostat working)
            self.state.coolantTempC -= COOLANT_WARMUP_RATE_C_PER_SEC * 0.5 * deltaSeconds
            self.state.coolantTempC = max(
                self.state.coolantTempC,
                float(self.profile.normalCoolantTempC)
            )

    def _updateEngineLoad(self) -> None:
        """Update engine load based on throttle and speed."""
        throttleFraction = self.state.throttlePercent / 100.0

        # Base load from throttle
        loadFromThrottle = IDLE_THROTTLE_LOAD + (
            (MAX_THROTTLE_LOAD - IDLE_THROTTLE_LOAD) * throttleFraction
        )

        # Additional load from speed (air resistance)
        speedFraction = self.state.speedKph / max(1.0, self.profile.maxSpeedKph)
        loadFromSpeed = speedFraction * 0.2

        # Calculate final load percentage
        self.state.engineLoad = (loadFromThrottle + loadFromSpeed) * 100.0
        self.state.engineLoad = min(100.0, self.state.engineLoad)

    def _updateMaf(self) -> None:
        """Update MAF based on RPM and throttle."""
        # MAF correlates with RPM and throttle
        rpmFraction = self.state.rpm / self.profile.maxRpm
        throttleFraction = self.state.throttlePercent / 100.0

        # Combined factor (RPM dominant, throttle modifies)
        combinedFactor = rpmFraction * (0.3 + 0.7 * throttleFraction)

        # Calculate MAF
        self.state.mafGPerSec = MAF_IDLE_G_PER_SEC + (
            (MAF_MAX_G_PER_SEC - MAF_IDLE_G_PER_SEC) * combinedFactor
        )

    def _updateFuel(self, deltaSeconds: float) -> None:
        """Update fuel consumption based on load."""
        if self.state.fuelLevelPercent <= 0:
            return

        # Calculate consumption rate (L/h)
        loadFraction = self.state.engineLoad / 100.0
        consumptionRate = FUEL_CONSUMPTION_BASE_L_PER_H + (
            FUEL_CONSUMPTION_LOAD_FACTOR * loadFraction
        )

        # Convert to percentage of tank per second
        consumptionPercent = (consumptionRate / FUEL_TANK_SIZE_L) * (
            deltaSeconds / 3600.0
        ) * 100.0

        self.state.fuelLevelPercent -= consumptionPercent
        self.state.fuelLevelPercent = max(0.0, self.state.fuelLevelPercent)

    def _updateDerivedValues(self) -> None:
        """Update derived sensor values."""
        # Intake temperature
        loadFactor = self.state.engineLoad / 100.0
        self.state.intakeTempC = INTAKE_TEMP_BASE_C + (
            INTAKE_TEMP_LOAD_FACTOR * loadFactor
        )

        # Oil temperature tracks coolant but slightly higher
        self.state.oilTempC = self.state.coolantTempC * OIL_TEMP_FACTOR

        # Intake pressure (vacuum at idle, higher under load)
        vacuumAtIdle = 30.0  # kPa below atmospheric
        loadFactor = self.state.engineLoad / 100.0
        self.state.intakePressureKpa = 101.0 - vacuumAtIdle * (1.0 - loadFactor)

        # Timing advance (varies with RPM and load)
        rpmFactor = self.state.rpm / self.profile.maxRpm
        loadFactor = self.state.engineLoad / 100.0
        baseAdvance = 10.0
        rpmAdvance = 20.0 * rpmFactor
        loadRetard = 10.0 * loadFactor
        self.state.timingAdvanceDeg = baseAdvance + rpmAdvance - loadRetard

        # O2 sensor (fluctuates around stoichiometric)
        # Rich under heavy load, lean under light load
        loadFactor = self.state.engineLoad / 100.0
        self.state.o2Voltage = 0.45 + (loadFactor - 0.5) * 0.4

        # Fuel trims (small variations)
        self.state.shortFuelTrimPercent = (loadFactor - 0.5) * 5.0
        self.state.longFuelTrimPercent = 0.0  # Stable in simulation

    # ==========================================================================
    # Value Retrieval
    # ==========================================================================

    def getValue(self, parameterName: str) -> Optional[float]:
        """
        Get current simulated value for an OBD-II parameter.

        Args:
            parameterName: OBD-II parameter name (e.g., 'RPM', 'SPEED')

        Returns:
            Current simulated value, or None if parameter not supported
        """
        value = self._getRawValue(parameterName)

        if value is None:
            return None

        # Add noise if enabled
        if self.noiseEnabled:
            value = self._addNoise(value, parameterName)

        return value

    def _getRawValue(self, parameterName: str) -> Optional[float]:
        """Get raw value without noise."""
        param = parameterName.upper()

        # Map parameter names to state values
        parameterMap: Dict[str, float] = {
            "RPM": self.state.rpm,
            "SPEED": self.state.speedKph,
            "COOLANT_TEMP": self.state.coolantTempC,
            "THROTTLE_POS": self.state.throttlePercent,
            "ENGINE_LOAD": self.state.engineLoad,
            "MAF": self.state.mafGPerSec,
            "INTAKE_TEMP": self.state.intakeTempC,
            "OIL_TEMP": self.state.oilTempC,
            "INTAKE_PRESSURE": self.state.intakePressureKpa,
            "FUEL_PRESSURE": self.state.fuelPressureKpa,
            "TIMING_ADVANCE": self.state.timingAdvanceDeg,
            "O2_B1S1": self.state.o2Voltage,
            "O2_B1S2": self.state.o2Voltage * 0.95,  # Slightly different
            "O2_B2S1": self.state.o2Voltage * 0.98,
            "O2_B2S2": self.state.o2Voltage * 0.93,
            "SHORT_FUEL_TRIM_1": self.state.shortFuelTrimPercent,
            "LONG_FUEL_TRIM_1": self.state.longFuelTrimPercent,
            "SHORT_FUEL_TRIM_2": self.state.shortFuelTrimPercent * 0.9,
            "LONG_FUEL_TRIM_2": self.state.longFuelTrimPercent,
            "RUN_TIME": self.state.engineRunTimeSeconds,
            "CONTROL_MODULE_VOLTAGE": self.state.controlModuleVoltage,
            "BAROMETRIC_PRESSURE": 101.0,  # Constant
            "AMBIANT_AIR_TEMP": COOLANT_AMBIENT_TEMP_C,  # Constant
            "FUEL_RATE": self._calculateFuelRate(),
            "COMMANDED_EQUIV_RATIO": 1.0 + (self.state.shortFuelTrimPercent / 100.0),
            "RELATIVE_THROTTLE_POS": self.state.throttlePercent,
            "THROTTLE_ACTUATOR": self.state.throttlePercent,
            "ACCELERATOR_POS_D": self.state.throttlePercent,
            "ACCELERATOR_POS_E": self.state.throttlePercent * 0.95,
            "ABS_LOAD": self.state.engineLoad * 2.55 / 100.0 * 100.0,  # Scaled
            "COMMANDED_THROTTLE_ACTUATOR": self.state.throttlePercent,
            "COMMANDED_EGR": self.state.engineLoad * 0.3,  # Proportional to load
            "EGR_ERROR": 0.0,  # No error in simulation
            "EVAPORATIVE_PURGE": self.state.engineLoad * 0.5,  # Proportional
            "CATALYST_TEMP_B1S1": self.state.coolantTempC * 4.0,  # Much hotter
            "CATALYST_TEMP_B2S1": self.state.coolantTempC * 3.9,
            "CATALYST_TEMP_B1S2": self.state.coolantTempC * 3.5,
            "CATALYST_TEMP_B2S2": self.state.coolantTempC * 3.4,
            "HYBRID_BATTERY_REMAINING": 75.0,  # Constant for simulation
            "ETHANOL_PERCENT": 10.0,  # E10 fuel
        }

        return parameterMap.get(param)

    def _calculateFuelRate(self) -> float:
        """Calculate fuel rate in L/h."""
        loadFraction = self.state.engineLoad / 100.0
        return FUEL_CONSUMPTION_BASE_L_PER_H + (
            FUEL_CONSUMPTION_LOAD_FACTOR * loadFraction
        )

    def _addNoise(self, value: float, parameterName: str) -> float:
        """Add realistic noise to a value."""
        # Determine noise level based on parameter
        noiseLevel = self._getNoiseLevel(parameterName)

        if noiseLevel == 0.0 or value == 0.0:
            return value

        # Generate gaussian noise
        noise = self._noiseGenerator(0, noiseLevel * abs(value))
        return value + noise

    def _getNoiseLevel(self, parameterName: str) -> float:
        """Get noise level for a parameter."""
        param = parameterName.upper()

        # Low noise parameters (stable sensors)
        lowNoiseParams = {
            "CONTROL_MODULE_VOLTAGE", "BAROMETRIC_PRESSURE", "RUN_TIME",
            "FUEL_PRESSURE", "LONG_FUEL_TRIM_1", "LONG_FUEL_TRIM_2"
        }

        # High noise parameters (variable sensors)
        highNoiseParams = {
            "O2_B1S1", "O2_B1S2", "O2_B2S1", "O2_B2S2",
            "SHORT_FUEL_TRIM_1", "SHORT_FUEL_TRIM_2", "MAF"
        }

        if param in lowNoiseParams:
            return NOISE_LEVEL_LOW
        elif param in highNoiseParams:
            return NOISE_LEVEL_HIGH
        else:
            return NOISE_LEVEL_DEFAULT

    # ==========================================================================
    # State Access
    # ==========================================================================

    def getState(self) -> VehicleState:
        """
        Get current vehicle state.

        Returns:
            VehicleState dataclass with all state values
        """
        return self.state

    def getEngineState(self) -> EngineState:
        """
        Get current engine state.

        Returns:
            EngineState enum value
        """
        return self.engineState

    def setNoiseEnabled(self, enabled: bool) -> None:
        """
        Enable or disable noise on sensor values.

        Args:
            enabled: Whether to add noise to values
        """
        self.noiseEnabled = enabled

    def reset(self) -> None:
        """Reset simulator to initial state."""
        self.state = VehicleState()
        self.engineState = EngineState.OFF
        self._targetRpm = 0.0
        self._targetSpeed = 0.0
        logger.debug("Simulator reset to initial state")


# ================================================================================
# Helper Functions
# ================================================================================

def createSensorSimulatorFromConfig(
    config: Dict[str, Any]
) -> SensorSimulator:
    """
    Create a SensorSimulator from a config dictionary.

    Args:
        config: Configuration dictionary, may contain 'simulator.profile'
                or 'profile' nested data

    Returns:
        Configured SensorSimulator instance
    """
    from .vehicle_profile import createProfileFromConfig

    profile = createProfileFromConfig(config)
    noiseEnabled = config.get("simulator", {}).get("noiseEnabled", True)

    return SensorSimulator(profile=profile, noiseEnabled=noiseEnabled)


def getDefaultSensorSimulator() -> SensorSimulator:
    """
    Get a sensor simulator with default profile.

    Returns:
        SensorSimulator with default vehicle profile
    """
    return SensorSimulator()
