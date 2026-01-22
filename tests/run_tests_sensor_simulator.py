################################################################################
# File Name: run_tests_sensor_simulator.py
# Purpose/Description: Tests for SensorSimulator class
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-036
# ================================================================================
################################################################################

"""
Tests for the SensorSimulator class.

Tests verify:
- Internal state management
- Physics-based simulation rules
- Value retrieval with noise
- Engine start/stop lifecycle
- State progression over time
"""

import math
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.simulator.sensor_simulator import (
    SensorSimulator,
    VehicleState,
    EngineState,
    createSensorSimulatorFromConfig,
    getDefaultSensorSimulator,
    COOLANT_AMBIENT_TEMP_C,
    NOISE_LEVEL_DEFAULT,
    NOISE_LEVEL_LOW,
    NOISE_LEVEL_HIGH,
)
from obd.simulator.vehicle_profile import VehicleProfile, getDefaultProfile


class TestVehicleState(unittest.TestCase):
    """Tests for VehicleState dataclass."""

    def test_init_defaultValues(self):
        """
        Given: No arguments
        When: VehicleState is created
        Then: All fields have sensible defaults
        """
        state = VehicleState()

        self.assertEqual(state.rpm, 0.0)
        self.assertEqual(state.speedKph, 0.0)
        self.assertEqual(state.coolantTempC, COOLANT_AMBIENT_TEMP_C)
        self.assertEqual(state.throttlePercent, 0.0)
        self.assertEqual(state.engineLoad, 0.0)
        self.assertEqual(state.fuelLevelPercent, 75.0)
        self.assertEqual(state.gear, 0)

    def test_toDict_returnsAllFields(self):
        """
        Given: A VehicleState with values
        When: toDict() is called
        Then: All fields are in the dictionary
        """
        state = VehicleState(rpm=3000.0, speedKph=80.0, gear=3)
        result = state.toDict()

        self.assertEqual(result["rpm"], 3000.0)
        self.assertEqual(result["speedKph"], 80.0)
        self.assertEqual(result["gear"], 3)
        self.assertIn("coolantTempC", result)
        self.assertIn("engineLoad", result)


class TestSensorSimulatorInit(unittest.TestCase):
    """Tests for SensorSimulator initialization."""

    def test_init_noProfile_usesDefault(self):
        """
        Given: No profile argument
        When: SensorSimulator is created
        Then: Default profile is used
        """
        simulator = SensorSimulator()

        self.assertIsNotNone(simulator.profile)
        self.assertEqual(simulator.profile.make, "Generic")

    def test_init_withProfile_usesProvided(self):
        """
        Given: A custom profile
        When: SensorSimulator is created
        Then: Custom profile is used
        """
        profile = VehicleProfile(
            vin="1HGBH41JXMN109186",
            make="Honda",
            model="Accord"
        )
        simulator = SensorSimulator(profile=profile)

        self.assertEqual(simulator.profile.make, "Honda")
        self.assertEqual(simulator.profile.model, "Accord")

    def test_init_engineOff(self):
        """
        Given: New simulator
        When: Initialized
        Then: Engine is off
        """
        simulator = SensorSimulator()

        self.assertEqual(simulator.engineState, EngineState.OFF)
        self.assertFalse(simulator.isRunning())

    def test_init_noiseEnabled_default(self):
        """
        Given: No noise argument
        When: SensorSimulator is created
        Then: Noise is enabled by default
        """
        simulator = SensorSimulator()
        self.assertTrue(simulator.noiseEnabled)

    def test_init_noiseDisabled(self):
        """
        Given: noiseEnabled=False
        When: SensorSimulator is created
        Then: Noise is disabled
        """
        simulator = SensorSimulator(noiseEnabled=False)
        self.assertFalse(simulator.noiseEnabled)


class TestEngineLifecycle(unittest.TestCase):
    """Tests for engine start/stop lifecycle."""

    def test_startEngine_engagesCranking(self):
        """
        Given: Engine is off
        When: startEngine() is called
        Then: Engine transitions to running
        """
        simulator = SensorSimulator()

        result = simulator.startEngine()

        self.assertTrue(result)
        self.assertEqual(simulator.engineState, EngineState.RUNNING)
        self.assertTrue(simulator.isRunning())

    def test_startEngine_setsIdleRpm(self):
        """
        Given: Engine is off
        When: startEngine() is called
        Then: RPM is at idle
        """
        simulator = SensorSimulator()
        simulator.startEngine()

        self.assertEqual(simulator.state.rpm, float(simulator.profile.idleRpm))

    def test_startEngine_alreadyRunning_returnsTrue(self):
        """
        Given: Engine is already running
        When: startEngine() is called again
        Then: Returns True (no error)
        """
        simulator = SensorSimulator()
        simulator.startEngine()

        result = simulator.startEngine()

        self.assertTrue(result)
        self.assertTrue(simulator.isRunning())

    def test_stopEngine_stopsRunning(self):
        """
        Given: Engine is running
        When: stopEngine() is called
        Then: Engine is off
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.stopEngine()

        self.assertEqual(simulator.engineState, EngineState.OFF)
        self.assertFalse(simulator.isRunning())

    def test_stopEngine_resetsRpm(self):
        """
        Given: Engine is running with RPM
        When: stopEngine() is called
        Then: RPM is zero
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setThrottle(50)
        simulator.update(1.0)
        simulator.stopEngine()

        self.assertEqual(simulator.state.rpm, 0.0)

    def test_stopEngine_resetsSpeed(self):
        """
        Given: Vehicle is moving
        When: stopEngine() is called
        Then: Speed is zero
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setThrottle(50)
        simulator.setGear(2)
        simulator.update(2.0)
        simulator.stopEngine()

        self.assertEqual(simulator.state.speedKph, 0.0)


class TestInputControls(unittest.TestCase):
    """Tests for input control methods."""

    def test_setThrottle_validRange(self):
        """
        Given: Valid throttle value
        When: setThrottle() is called
        Then: Throttle is set correctly
        """
        simulator = SensorSimulator()
        simulator.setThrottle(50.0)

        self.assertEqual(simulator.state.throttlePercent, 50.0)

    def test_setThrottle_clampsLow(self):
        """
        Given: Negative throttle value
        When: setThrottle() is called
        Then: Throttle is clamped to 0
        """
        simulator = SensorSimulator()
        simulator.setThrottle(-10.0)

        self.assertEqual(simulator.state.throttlePercent, 0.0)

    def test_setThrottle_clampsHigh(self):
        """
        Given: Throttle > 100
        When: setThrottle() is called
        Then: Throttle is clamped to 100
        """
        simulator = SensorSimulator()
        simulator.setThrottle(150.0)

        self.assertEqual(simulator.state.throttlePercent, 100.0)

    def test_setGear_validRange(self):
        """
        Given: Valid gear value
        When: setGear() is called
        Then: Gear is set correctly
        """
        simulator = SensorSimulator()
        simulator.setGear(3)

        self.assertEqual(simulator.state.gear, 3)

    def test_setGear_clampsLow(self):
        """
        Given: Negative gear value
        When: setGear() is called
        Then: Gear is clamped to 0
        """
        simulator = SensorSimulator()
        simulator.setGear(-1)

        self.assertEqual(simulator.state.gear, 0)

    def test_setGear_clampsHigh(self):
        """
        Given: Gear > max gears
        When: setGear() is called
        Then: Gear is clamped to max
        """
        simulator = SensorSimulator()
        simulator.setGear(10)

        # Max gear is 5 (index 5 in GEAR_RATIOS)
        self.assertEqual(simulator.state.gear, 5)

    def test_setFuelLevel_validRange(self):
        """
        Given: Valid fuel level
        When: setFuelLevel() is called
        Then: Fuel level is set
        """
        simulator = SensorSimulator()
        simulator.setFuelLevel(50.0)

        self.assertEqual(simulator.state.fuelLevelPercent, 50.0)

    def test_setFuelLevel_clampsRange(self):
        """
        Given: Out of range fuel level
        When: setFuelLevel() is called
        Then: Fuel level is clamped
        """
        simulator = SensorSimulator()
        simulator.setFuelLevel(120.0)
        self.assertEqual(simulator.state.fuelLevelPercent, 100.0)

        simulator.setFuelLevel(-10.0)
        self.assertEqual(simulator.state.fuelLevelPercent, 0.0)


class TestUpdatePhysics(unittest.TestCase):
    """Tests for update() physics simulation."""

    def test_update_engineOff_noChange(self):
        """
        Given: Engine is off
        When: update() is called
        Then: State doesn't change
        """
        simulator = SensorSimulator()
        initialRpm = simulator.state.rpm
        simulator.update(1.0)

        self.assertEqual(simulator.state.rpm, initialRpm)

    def test_update_zeroDelta_noChange(self):
        """
        Given: Delta is zero
        When: update() is called
        Then: State doesn't change
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        initialRunTime = simulator.state.engineRunTimeSeconds
        simulator.update(0.0)

        self.assertEqual(simulator.state.engineRunTimeSeconds, initialRunTime)

    def test_update_negativeDelta_noChange(self):
        """
        Given: Delta is negative
        When: update() is called
        Then: State doesn't change
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        initialRunTime = simulator.state.engineRunTimeSeconds
        simulator.update(-1.0)

        self.assertEqual(simulator.state.engineRunTimeSeconds, initialRunTime)

    def test_update_updatesRunTime(self):
        """
        Given: Engine is running
        When: update() is called
        Then: Run time increases
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.update(1.0)

        self.assertEqual(simulator.state.engineRunTimeSeconds, 1.0)

    def test_update_rpmRespondsToThrottle(self):
        """
        Given: Throttle is applied
        When: update() is called
        Then: RPM increases toward target
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        idleRpm = simulator.state.rpm
        simulator.setThrottle(50.0)
        simulator.update(0.5)

        self.assertGreater(simulator.state.rpm, idleRpm)

    def test_update_rpmStaysAboveIdle(self):
        """
        Given: Engine is running at idle
        When: update() is called with no throttle
        Then: RPM stays at idle minimum
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setThrottle(0.0)
        simulator.update(2.0)

        self.assertGreaterEqual(
            simulator.state.rpm,
            float(simulator.profile.idleRpm)
        )

    def test_update_rpmLimitedByMax(self):
        """
        Given: Full throttle for extended time
        When: update() is called repeatedly
        Then: RPM doesn't exceed max
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setThrottle(100.0)

        # Simulate many updates
        for _ in range(100):
            simulator.update(0.1)

        self.assertLessEqual(simulator.state.rpm, simulator.profile.maxRpm)


class TestSpeedPhysics(unittest.TestCase):
    """Tests for speed calculation physics."""

    def test_update_neutralGear_coastsDown(self):
        """
        Given: Vehicle in neutral with speed
        When: update() is called
        Then: Speed decreases (coasting)
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.state.speedKph = 50.0  # Set initial speed
        simulator.setGear(0)  # Neutral
        simulator.update(1.0)

        self.assertLess(simulator.state.speedKph, 50.0)

    def test_update_inGear_speedIncreasesWithRpm(self):
        """
        Given: Vehicle in gear with throttle
        When: update() is called
        Then: Speed increases
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setThrottle(50.0)
        simulator.setGear(2)
        simulator.update(1.0)

        self.assertGreater(simulator.state.speedKph, 0.0)

    def test_update_speedLimitedByMax(self):
        """
        Given: Full throttle in high gear
        When: update() is called repeatedly
        Then: Speed doesn't exceed vehicle max
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setThrottle(100.0)
        simulator.setGear(5)

        # Simulate many updates
        for _ in range(1000):
            simulator.update(0.1)

        self.assertLessEqual(
            simulator.state.speedKph,
            simulator.profile.maxSpeedKph
        )


class TestCoolantPhysics(unittest.TestCase):
    """Tests for coolant temperature physics."""

    def test_update_coolantWarmsUp(self):
        """
        Given: Cold engine running
        When: update() is called
        Then: Coolant temperature rises
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        initialTemp = simulator.state.coolantTempC
        simulator.update(10.0)

        self.assertGreater(simulator.state.coolantTempC, initialTemp)

    def test_update_coolantReachesNormal(self):
        """
        Given: Engine running for long time
        When: update() is called repeatedly
        Then: Coolant reaches normal operating temp
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setThrottle(30.0)

        # Simulate warmup
        for _ in range(1000):
            simulator.update(0.5)

        self.assertAlmostEqual(
            simulator.state.coolantTempC,
            float(simulator.profile.normalCoolantTempC),
            delta=1.0
        )

    def test_update_loadAffectsWarmup(self):
        """
        Given: Two simulators at different loads
        When: update() is called
        Then: Higher load warms faster
        """
        simLow = SensorSimulator(noiseEnabled=False)
        simHigh = SensorSimulator(noiseEnabled=False)

        simLow.startEngine()
        simHigh.startEngine()

        simLow.setThrottle(10.0)
        simHigh.setThrottle(70.0)

        simLow.update(1.0)
        simHigh.update(1.0)

        # Update load calculation (needs update call)
        simLow._updateEngineLoad()
        simHigh._updateEngineLoad()

        simLow.update(5.0)
        simHigh.update(5.0)

        # Higher load should have warmer coolant
        self.assertGreater(
            simHigh.state.coolantTempC,
            simLow.state.coolantTempC
        )


class TestEngineLoadPhysics(unittest.TestCase):
    """Tests for engine load calculation."""

    def test_update_loadCorrelatesWithThrottle(self):
        """
        Given: Different throttle positions
        When: update() is called
        Then: Load correlates with throttle
        """
        simLow = SensorSimulator(noiseEnabled=False)
        simHigh = SensorSimulator(noiseEnabled=False)

        simLow.startEngine()
        simHigh.startEngine()

        simLow.setThrottle(20.0)
        simHigh.setThrottle(80.0)

        simLow.update(0.1)
        simHigh.update(0.1)

        self.assertGreater(simHigh.state.engineLoad, simLow.state.engineLoad)

    def test_update_loadWithinBounds(self):
        """
        Given: Any throttle position
        When: update() is called
        Then: Load is between 0-100
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setThrottle(100.0)
        simulator.update(1.0)

        self.assertGreaterEqual(simulator.state.engineLoad, 0.0)
        self.assertLessEqual(simulator.state.engineLoad, 100.0)


class TestMafPhysics(unittest.TestCase):
    """Tests for MAF calculation."""

    def test_update_mafCorrelatesWithRpmAndThrottle(self):
        """
        Given: Different RPM/throttle combinations
        When: update() is called
        Then: MAF correlates with both
        """
        simLow = SensorSimulator(noiseEnabled=False)
        simHigh = SensorSimulator(noiseEnabled=False)

        simLow.startEngine()
        simHigh.startEngine()

        simLow.setThrottle(20.0)
        simHigh.setThrottle(80.0)

        # Allow RPM to respond
        for _ in range(10):
            simLow.update(0.1)
            simHigh.update(0.1)

        self.assertGreater(simHigh.state.mafGPerSec, simLow.state.mafGPerSec)


class TestFuelConsumption(unittest.TestCase):
    """Tests for fuel consumption."""

    def test_update_fuelDecreases(self):
        """
        Given: Engine running
        When: update() is called
        Then: Fuel level decreases
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        initialFuel = simulator.state.fuelLevelPercent
        simulator.setThrottle(50.0)
        simulator.update(60.0)  # 1 minute

        self.assertLess(simulator.state.fuelLevelPercent, initialFuel)

    def test_update_fuelDecreaseFasterUnderLoad(self):
        """
        Given: Two simulators at different loads
        When: update() is called
        Then: Higher load consumes more fuel
        """
        simLow = SensorSimulator(noiseEnabled=False)
        simHigh = SensorSimulator(noiseEnabled=False)

        simLow.startEngine()
        simHigh.startEngine()

        simLow.setThrottle(10.0)
        simHigh.setThrottle(90.0)

        simLow.update(1.0)
        simHigh.update(1.0)

        # Simulate for some time
        simLow.update(60.0)
        simHigh.update(60.0)

        self.assertGreater(
            simLow.state.fuelLevelPercent,
            simHigh.state.fuelLevelPercent
        )

    def test_update_fuelNeverNegative(self):
        """
        Given: Low fuel
        When: update() is called many times
        Then: Fuel stays >= 0
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setFuelLevel(0.001)
        simulator.setThrottle(100.0)
        simulator.update(3600.0)  # 1 hour

        self.assertGreaterEqual(simulator.state.fuelLevelPercent, 0.0)


class TestGetValue(unittest.TestCase):
    """Tests for getValue() method."""

    def test_getValue_rpm_returnsValue(self):
        """
        Given: Engine running
        When: getValue('RPM') is called
        Then: RPM value is returned
        """
        simulator = SensorSimulator(noiseEnabled=False)
        simulator.startEngine()

        rpm = simulator.getValue('RPM')

        self.assertIsNotNone(rpm)
        self.assertAlmostEqual(
            rpm,
            float(simulator.profile.idleRpm),
            delta=10
        )

    def test_getValue_caseInsensitive(self):
        """
        Given: Parameter name in different cases
        When: getValue() is called
        Then: Same value returned
        """
        simulator = SensorSimulator(noiseEnabled=False)
        simulator.startEngine()

        rpm1 = simulator.getValue('RPM')
        rpm2 = simulator.getValue('rpm')
        rpm3 = simulator.getValue('Rpm')

        self.assertEqual(rpm1, rpm2)
        self.assertEqual(rpm2, rpm3)

    def test_getValue_unknownParameter_returnsNone(self):
        """
        Given: Unknown parameter name
        When: getValue() is called
        Then: None is returned
        """
        simulator = SensorSimulator()
        result = simulator.getValue('UNKNOWN_PARAM')

        self.assertIsNone(result)

    def test_getValue_withNoise_varies(self):
        """
        Given: Noise enabled
        When: getValue() is called multiple times
        Then: Values vary
        """
        simulator = SensorSimulator(noiseEnabled=True)
        simulator.startEngine()
        simulator.setThrottle(50.0)
        simulator.update(1.0)

        values = [simulator.getValue('RPM') for _ in range(10)]

        # Values should not all be identical
        self.assertGreater(len(set(values)), 1)

    def test_getValue_withoutNoise_consistent(self):
        """
        Given: Noise disabled
        When: getValue() is called multiple times
        Then: Values are consistent
        """
        simulator = SensorSimulator(noiseEnabled=False)
        simulator.startEngine()

        values = [simulator.getValue('RPM') for _ in range(10)]

        # All values should be identical
        self.assertEqual(len(set(values)), 1)

    def test_getValue_allCoreParameters(self):
        """
        Given: Engine running
        When: getValue() is called for all core parameters
        Then: All return values
        """
        simulator = SensorSimulator(noiseEnabled=False)
        simulator.startEngine()
        simulator.setThrottle(50.0)
        simulator.setGear(3)
        simulator.update(1.0)

        coreParams = [
            'RPM', 'SPEED', 'COOLANT_TEMP', 'THROTTLE_POS', 'ENGINE_LOAD',
            'MAF', 'INTAKE_TEMP', 'OIL_TEMP', 'INTAKE_PRESSURE', 'FUEL_PRESSURE',
            'TIMING_ADVANCE', 'O2_B1S1', 'SHORT_FUEL_TRIM_1', 'LONG_FUEL_TRIM_1',
            'RUN_TIME', 'CONTROL_MODULE_VOLTAGE', 'FUEL_RATE'
        ]

        for param in coreParams:
            value = simulator.getValue(param)
            self.assertIsNotNone(value, f"{param} should not be None")


class TestDerivedValues(unittest.TestCase):
    """Tests for derived sensor values."""

    def test_intakeTemp_affectedByLoad(self):
        """
        Given: Different engine loads
        When: update() is called
        Then: Intake temp varies with load
        """
        simLow = SensorSimulator(noiseEnabled=False)
        simHigh = SensorSimulator(noiseEnabled=False)

        simLow.startEngine()
        simHigh.startEngine()

        simLow.setThrottle(10.0)
        simHigh.setThrottle(90.0)

        simLow.update(0.5)
        simHigh.update(0.5)

        lowIntake = simLow.getValue('INTAKE_TEMP')
        highIntake = simHigh.getValue('INTAKE_TEMP')

        self.assertGreater(highIntake, lowIntake)

    def test_oilTemp_tracksLantTemp(self):
        """
        Given: Warmed up engine
        When: getValue() is called
        Then: Oil temp is higher than coolant
        """
        simulator = SensorSimulator(noiseEnabled=False)
        simulator.startEngine()
        simulator.setThrottle(30.0)

        # Warm up
        for _ in range(100):
            simulator.update(1.0)

        coolant = simulator.getValue('COOLANT_TEMP')
        oil = simulator.getValue('OIL_TEMP')

        self.assertGreater(oil, coolant)

    def test_timingAdvance_variesWithConditions(self):
        """
        Given: Different RPM and load
        When: getValue() is called
        Then: Timing advance varies
        """
        simLow = SensorSimulator(noiseEnabled=False)
        simHigh = SensorSimulator(noiseEnabled=False)

        simLow.startEngine()
        simHigh.startEngine()

        simLow.setThrottle(20.0)
        simHigh.setThrottle(80.0)

        for _ in range(10):
            simLow.update(0.1)
            simHigh.update(0.1)

        lowTiming = simLow.getValue('TIMING_ADVANCE')
        highTiming = simHigh.getValue('TIMING_ADVANCE')

        # Values should be different
        self.assertNotEqual(lowTiming, highTiming)


class TestNoiseConfiguration(unittest.TestCase):
    """Tests for noise configuration."""

    def test_setNoiseEnabled_togglesNoise(self):
        """
        Given: Noise initially enabled
        When: setNoiseEnabled(False) is called
        Then: Noise is disabled
        """
        simulator = SensorSimulator(noiseEnabled=True)
        simulator.setNoiseEnabled(False)

        self.assertFalse(simulator.noiseEnabled)

    def test_getNoiseLevel_lowNoiseParams(self):
        """
        Given: Low noise parameter
        When: _getNoiseLevel() is called
        Then: Low noise level returned
        """
        simulator = SensorSimulator()
        level = simulator._getNoiseLevel('CONTROL_MODULE_VOLTAGE')

        self.assertEqual(level, NOISE_LEVEL_LOW)

    def test_getNoiseLevel_highNoiseParams(self):
        """
        Given: High noise parameter
        When: _getNoiseLevel() is called
        Then: High noise level returned
        """
        simulator = SensorSimulator()
        level = simulator._getNoiseLevel('O2_B1S1')

        self.assertEqual(level, NOISE_LEVEL_HIGH)

    def test_getNoiseLevel_defaultParams(self):
        """
        Given: Default noise parameter
        When: _getNoiseLevel() is called
        Then: Default noise level returned
        """
        simulator = SensorSimulator()
        level = simulator._getNoiseLevel('RPM')

        self.assertEqual(level, NOISE_LEVEL_DEFAULT)


class TestStateAccess(unittest.TestCase):
    """Tests for state access methods."""

    def test_getState_returnsState(self):
        """
        Given: Simulator with state
        When: getState() is called
        Then: State object returned
        """
        simulator = SensorSimulator()
        simulator.startEngine()

        state = simulator.getState()

        self.assertIsInstance(state, VehicleState)
        self.assertEqual(state.rpm, simulator.state.rpm)

    def test_getEngineState_returnsEngineState(self):
        """
        Given: Simulator with engine state
        When: getEngineState() is called
        Then: EngineState enum returned
        """
        simulator = SensorSimulator()
        self.assertEqual(simulator.getEngineState(), EngineState.OFF)

        simulator.startEngine()
        self.assertEqual(simulator.getEngineState(), EngineState.RUNNING)

    def test_reset_restorestInitialState(self):
        """
        Given: Simulator with modified state
        When: reset() is called
        Then: State is restored to initial
        """
        simulator = SensorSimulator()
        simulator.startEngine()
        simulator.setThrottle(50.0)
        simulator.update(10.0)

        simulator.reset()

        self.assertEqual(simulator.engineState, EngineState.OFF)
        self.assertEqual(simulator.state.rpm, 0.0)
        self.assertEqual(simulator.state.speedKph, 0.0)
        self.assertEqual(simulator.state.throttlePercent, 0.0)


class TestHelperFunctions(unittest.TestCase):
    """Tests for helper functions."""

    def test_createSensorSimulatorFromConfig_withProfile(self):
        """
        Given: Config with profile data
        When: createSensorSimulatorFromConfig() is called
        Then: Simulator with profile is created
        """
        config = {
            "simulator": {
                "profile": {
                    "make": "Toyota",
                    "model": "Supra"
                },
                "noiseEnabled": False
            }
        }

        simulator = createSensorSimulatorFromConfig(config)

        self.assertEqual(simulator.profile.make, "Toyota")
        self.assertEqual(simulator.profile.model, "Supra")
        self.assertFalse(simulator.noiseEnabled)

    def test_createSensorSimulatorFromConfig_noProfile(self):
        """
        Given: Config without profile
        When: createSensorSimulatorFromConfig() is called
        Then: Default profile is used
        """
        config = {}

        simulator = createSensorSimulatorFromConfig(config)

        self.assertEqual(simulator.profile.make, "Generic")

    def test_getDefaultSensorSimulator_returnsSimulator(self):
        """
        Given: No arguments
        When: getDefaultSensorSimulator() is called
        Then: Simulator with defaults is returned
        """
        simulator = getDefaultSensorSimulator()

        self.assertIsInstance(simulator, SensorSimulator)
        self.assertEqual(simulator.profile.make, "Generic")


class TestPhysicsRealism(unittest.TestCase):
    """Integration tests for realistic physics behavior."""

    def test_fullDriveCycle_realisticBehavior(self):
        """
        Given: Full drive cycle simulation
        When: Various inputs over time
        Then: Behavior is realistic
        """
        simulator = SensorSimulator(noiseEnabled=False)

        # Start cold
        self.assertLess(simulator.state.coolantTempC, 30.0)

        # Start engine
        simulator.startEngine()
        self.assertTrue(simulator.isRunning())

        # Idle for warmup
        for _ in range(60):
            simulator.update(1.0)

        # Should have warmed up somewhat
        warmupTemp = simulator.state.coolantTempC
        self.assertGreater(warmupTemp, COOLANT_AMBIENT_TEMP_C + 5.0)

        # Accelerate
        simulator.setThrottle(60.0)
        simulator.setGear(1)
        for _ in range(20):
            simulator.update(0.1)

        # RPM should have increased
        self.assertGreater(simulator.state.rpm, simulator.profile.idleRpm)

        # Should have some speed
        self.assertGreater(simulator.state.speedKph, 0.0)

        # Shift to higher gear
        simulator.setGear(3)
        for _ in range(50):
            simulator.update(0.1)

        # Stop
        simulator.setThrottle(0.0)
        simulator.setGear(0)
        for _ in range(50):
            simulator.update(0.1)

        # RPM should return toward idle
        self.assertLess(
            simulator.state.rpm,
            simulator.profile.idleRpm + 500
        )

    def test_correlatedSensors_makeSense(self):
        """
        Given: Running engine
        When: Sensor values retrieved
        Then: Values correlate correctly
        """
        simulator = SensorSimulator(noiseEnabled=False)
        simulator.startEngine()
        simulator.setThrottle(70.0)
        simulator.setGear(3)

        # Run for a bit
        for _ in range(50):
            simulator.update(0.1)

        rpm = simulator.getValue('RPM')
        load = simulator.getValue('ENGINE_LOAD')
        maf = simulator.getValue('MAF')
        throttle = simulator.getValue('THROTTLE_POS')

        # With high throttle, should have:
        # - RPM above idle
        self.assertGreater(rpm, simulator.profile.idleRpm)

        # - Significant load
        self.assertGreater(load, 30.0)

        # - MAF above idle
        self.assertGreater(maf, 3.0)

        # - Throttle matches input
        self.assertAlmostEqual(throttle, 70.0, delta=1.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
