#!/usr/bin/env python3
################################################################################
# File Name: run_tests_simulator_status.py
# Purpose/Description: Tests for simulator status display functionality (US-041)
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
Tests for simulator status display functionality.

Tests:
- SimulatorStatus dataclass fields and serialization
- getSimulatorStatus() function behavior
- DeveloperDisplayDriver SIM indicator and status display
- Integration with ScenarioRunner and FailureInjector
"""

import io
import sys
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# Add src to path for imports
sys.path.insert(0, "src")

from obd.simulator.simulator_status import (
    SimulatorStatus,
    SimulatorStatusProvider,
    getSimulatorStatus,
    createSimulatorStatusProvider,
)
from obd.simulator.failure_injector import (
    FailureInjector,
    FailureType,
    FailureConfig,
)
from obd.simulator.drive_scenario import (
    DriveScenario,
    DrivePhase,
    DriveScenarioRunner,
    ScenarioState,
)
from obd.simulator.sensor_simulator import (
    SensorSimulator,
    VehicleState,
    EngineState,
)
from obd.simulator.vehicle_profile import getDefaultProfile


class TestSimulatorStatusDataclass(unittest.TestCase):
    """Tests for SimulatorStatus dataclass."""

    def test_defaultValues_areCorrect(self) -> None:
        """Test SimulatorStatus has correct default values."""
        status = SimulatorStatus()

        self.assertFalse(status.isRunning)
        self.assertIsNone(status.currentPhase)
        self.assertEqual(status.elapsedSeconds, 0.0)
        self.assertEqual(status.activeFailures, [])
        self.assertIsNone(status.vehicleState)
        self.assertFalse(status.isSimulationMode)
        self.assertIsNone(status.scenarioName)
        self.assertEqual(status.scenarioProgress, 0.0)
        self.assertEqual(status.loopsCompleted, 0)

    def test_createWithAllFields_setsCorrectly(self) -> None:
        """Test creating SimulatorStatus with all fields."""
        vehicleState = VehicleState(rpm=2500, speedKph=60)
        activeFailures = ["connectionDrop", "sensorFailure"]

        status = SimulatorStatus(
            isRunning=True,
            currentPhase="highway_cruise",
            elapsedSeconds=120.5,
            activeFailures=activeFailures,
            vehicleState=vehicleState,
            isSimulationMode=True,
            scenarioName="full_cycle",
            scenarioProgress=45.5,
            loopsCompleted=2,
        )

        self.assertTrue(status.isRunning)
        self.assertEqual(status.currentPhase, "highway_cruise")
        self.assertEqual(status.elapsedSeconds, 120.5)
        self.assertEqual(status.activeFailures, activeFailures)
        self.assertEqual(status.vehicleState, vehicleState)
        self.assertTrue(status.isSimulationMode)
        self.assertEqual(status.scenarioName, "full_cycle")
        self.assertEqual(status.scenarioProgress, 45.5)
        self.assertEqual(status.loopsCompleted, 2)

    def test_toDict_includesAllFields(self) -> None:
        """Test toDict includes all fields."""
        vehicleState = VehicleState(rpm=3000, speedKph=80, coolantTempC=85)

        status = SimulatorStatus(
            isRunning=True,
            currentPhase="accelerating",
            elapsedSeconds=30.0,
            activeFailures=["dtcCodes"],
            vehicleState=vehicleState,
            isSimulationMode=True,
            scenarioName="test_scenario",
            scenarioProgress=25.0,
            loopsCompleted=1,
        )

        result = status.toDict()

        self.assertTrue(result["isRunning"])
        self.assertEqual(result["currentPhase"], "accelerating")
        self.assertEqual(result["elapsedSeconds"], 30.0)
        self.assertEqual(result["activeFailures"], ["dtcCodes"])
        self.assertIsNotNone(result["vehicleState"])
        self.assertTrue(result["isSimulationMode"])
        self.assertEqual(result["scenarioName"], "test_scenario")
        self.assertEqual(result["scenarioProgress"], 25.0)
        self.assertEqual(result["loopsCompleted"], 1)

    def test_toDict_vehicleStateIncludesKeyFields(self) -> None:
        """Test vehicleState in toDict includes key fields."""
        vehicleState = VehicleState(
            rpm=4000,
            speedKph=100,
            coolantTempC=90,
            throttlePercent=50,
            engineLoad=60,
        )

        status = SimulatorStatus(vehicleState=vehicleState)
        result = status.toDict()

        vehicleDict = result["vehicleState"]
        self.assertEqual(vehicleDict["rpm"], 4000)
        self.assertEqual(vehicleDict["speedKph"], 100)
        self.assertEqual(vehicleDict["coolantTempC"], 90)
        self.assertEqual(vehicleDict["throttlePercent"], 50)
        self.assertEqual(vehicleDict["engineLoad"], 60)

    def test_toDict_withNullVehicleState_returnsNone(self) -> None:
        """Test toDict with null vehicleState returns None."""
        status = SimulatorStatus()
        result = status.toDict()
        self.assertIsNone(result["vehicleState"])


class TestSimulatorStatusProvider(unittest.TestCase):
    """Tests for SimulatorStatusProvider class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.profile = getDefaultProfile()
        self.simulator = SensorSimulator(self.profile)
        self.failureInjector = FailureInjector()

    def tearDown(self) -> None:
        """Clean up after tests."""
        self.failureInjector.stopScheduler()
        self.failureInjector.reset()

    def test_createProvider_withSimulator_succeeds(self) -> None:
        """Test creating provider with simulator."""
        provider = SimulatorStatusProvider(simulator=self.simulator)
        self.assertIsNotNone(provider)

    def test_createProvider_withAllComponents_succeeds(self) -> None:
        """Test creating provider with all components."""
        scenario = DriveScenario(
            name="test",
            description="Test scenario",
            phases=[DrivePhase(name="idle", durationSeconds=10)]
        )
        runner = DriveScenarioRunner(self.simulator, scenario)

        provider = SimulatorStatusProvider(
            simulator=self.simulator,
            scenarioRunner=runner,
            failureInjector=self.failureInjector,
        )

        self.assertIsNotNone(provider)
        self.assertEqual(provider.simulator, self.simulator)
        self.assertEqual(provider.scenarioRunner, runner)
        self.assertEqual(provider.failureInjector, self.failureInjector)

    def test_getStatus_withIdleSimulator_returnsNotRunning(self) -> None:
        """Test getStatus with idle simulator returns not running."""
        provider = SimulatorStatusProvider(simulator=self.simulator)
        status = provider.getStatus()

        self.assertFalse(status.isRunning)
        self.assertIsNone(status.currentPhase)
        self.assertTrue(status.isSimulationMode)

    def test_getStatus_withRunningSimulator_returnsRunning(self) -> None:
        """Test getStatus with running simulator returns running."""
        self.simulator.startEngine()

        provider = SimulatorStatusProvider(simulator=self.simulator)
        status = provider.getStatus()

        self.assertTrue(status.isRunning)
        self.assertTrue(status.isSimulationMode)
        self.assertIsNotNone(status.vehicleState)

    def test_getStatus_includesVehicleState(self) -> None:
        """Test getStatus includes vehicle state."""
        self.simulator.startEngine()
        self.simulator.setThrottle(30)
        self.simulator.update(1.0)

        provider = SimulatorStatusProvider(simulator=self.simulator)
        status = provider.getStatus()

        self.assertIsNotNone(status.vehicleState)
        self.assertGreater(status.vehicleState.rpm, 0)

    def test_getStatus_withScenarioRunner_includesPhase(self) -> None:
        """Test getStatus with scenario runner includes phase info."""
        scenario = DriveScenario(
            name="test_scenario",
            description="Test",
            phases=[
                DrivePhase(name="warmup", durationSeconds=30, targetThrottle=0),
                DrivePhase(name="cruise", durationSeconds=60, targetThrottle=30),
            ]
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        runner.start()

        provider = SimulatorStatusProvider(
            simulator=self.simulator,
            scenarioRunner=runner,
        )
        status = provider.getStatus()

        self.assertEqual(status.currentPhase, "warmup")
        self.assertEqual(status.scenarioName, "test_scenario")
        self.assertTrue(status.isRunning)

    def test_getStatus_withFailureInjector_includesActiveFailures(self) -> None:
        """Test getStatus with failure injector includes active failures."""
        self.failureInjector.injectFailure(FailureType.CONNECTION_DROP)
        self.failureInjector.injectFailure(
            FailureType.SENSOR_FAILURE,
            FailureConfig(sensorNames=["COOLANT_TEMP"])
        )

        provider = SimulatorStatusProvider(
            simulator=self.simulator,
            failureInjector=self.failureInjector,
        )
        status = provider.getStatus()

        self.assertEqual(len(status.activeFailures), 2)
        self.assertIn("connectionDrop", status.activeFailures)
        self.assertIn("sensorFailure", status.activeFailures)

    def test_getStatus_withNoActiveFailures_returnsEmptyList(self) -> None:
        """Test getStatus with no active failures returns empty list."""
        provider = SimulatorStatusProvider(
            simulator=self.simulator,
            failureInjector=self.failureInjector,
        )
        status = provider.getStatus()

        self.assertEqual(status.activeFailures, [])

    def test_getStatus_scenarioProgress_calculatedCorrectly(self) -> None:
        """Test scenario progress is calculated correctly."""
        scenario = DriveScenario(
            name="progress_test",
            description="Test",
            phases=[
                DrivePhase(name="phase1", durationSeconds=10),
                DrivePhase(name="phase2", durationSeconds=10),
            ]
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        runner.start()

        # Simulate 5 seconds into first 10-second phase = 25% progress
        runner.phaseElapsedSeconds = 5.0
        runner.totalElapsedSeconds = 5.0

        provider = SimulatorStatusProvider(
            simulator=self.simulator,
            scenarioRunner=runner,
        )
        status = provider.getStatus()

        self.assertGreater(status.scenarioProgress, 0)
        self.assertLess(status.scenarioProgress, 50)

    def test_getStatus_elapsedSeconds_fromScenarioRunner(self) -> None:
        """Test elapsedSeconds comes from scenario runner when available."""
        scenario = DriveScenario(
            name="elapsed_test",
            description="Test",
            phases=[DrivePhase(name="test", durationSeconds=60)]
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        runner.start()
        runner.totalElapsedSeconds = 45.5

        provider = SimulatorStatusProvider(
            simulator=self.simulator,
            scenarioRunner=runner,
        )
        status = provider.getStatus()

        self.assertEqual(status.elapsedSeconds, 45.5)

    def test_getStatus_loopsCompleted_fromRunner(self) -> None:
        """Test loopsCompleted comes from scenario runner."""
        scenario = DriveScenario(
            name="loop_test",
            description="Test",
            phases=[DrivePhase(name="test", durationSeconds=10)],
            loopCount=5
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        runner.start()
        runner.loopsCompleted = 3

        provider = SimulatorStatusProvider(
            simulator=self.simulator,
            scenarioRunner=runner,
        )
        status = provider.getStatus()

        self.assertEqual(status.loopsCompleted, 3)


class TestGetSimulatorStatusFunction(unittest.TestCase):
    """Tests for getSimulatorStatus() helper function."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.profile = getDefaultProfile()
        self.simulator = SensorSimulator(self.profile)

    def test_getSimulatorStatus_withSimulatorOnly(self) -> None:
        """Test getSimulatorStatus with only simulator."""
        status = getSimulatorStatus(simulator=self.simulator)

        self.assertIsInstance(status, SimulatorStatus)
        self.assertTrue(status.isSimulationMode)

    def test_getSimulatorStatus_withAllComponents(self) -> None:
        """Test getSimulatorStatus with all components."""
        scenario = DriveScenario(
            name="all_components",
            description="Test",
            phases=[DrivePhase(name="test", durationSeconds=30)]
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        injector = FailureInjector()

        try:
            status = getSimulatorStatus(
                simulator=self.simulator,
                scenarioRunner=runner,
                failureInjector=injector,
            )

            self.assertIsInstance(status, SimulatorStatus)
            self.assertTrue(status.isSimulationMode)
        finally:
            injector.stopScheduler()
            injector.reset()

    def test_getSimulatorStatus_withNoneSimulator_raisesError(self) -> None:
        """Test getSimulatorStatus with None simulator raises error."""
        with self.assertRaises(ValueError):
            getSimulatorStatus(simulator=None)


class TestCreateSimulatorStatusProvider(unittest.TestCase):
    """Tests for createSimulatorStatusProvider helper function."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.profile = getDefaultProfile()
        self.simulator = SensorSimulator(self.profile)

    def test_createProvider_fromConfig_succeeds(self) -> None:
        """Test creating provider from config."""
        provider = createSimulatorStatusProvider(
            simulator=self.simulator,
            config={"simulator": {"enabled": True}}
        )

        self.assertIsInstance(provider, SimulatorStatusProvider)

    def test_createProvider_withComponents_setsCorrectly(self) -> None:
        """Test creating provider with explicit components."""
        scenario = DriveScenario(
            name="config_test",
            description="Test",
            phases=[DrivePhase(name="test", durationSeconds=10)]
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        injector = FailureInjector()

        try:
            provider = createSimulatorStatusProvider(
                simulator=self.simulator,
                scenarioRunner=runner,
                failureInjector=injector,
            )

            self.assertEqual(provider.simulator, self.simulator)
            self.assertEqual(provider.scenarioRunner, runner)
            self.assertEqual(provider.failureInjector, injector)
        finally:
            injector.stopScheduler()
            injector.reset()


class TestDeveloperDisplaySimIndicator(unittest.TestCase):
    """Tests for SIM indicator in DeveloperDisplayDriver."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Import here to avoid circular dependency issues
        from obd.display_manager import (
            DeveloperDisplayDriver,
            DisplayManager,
            DisplayMode,
            StatusInfo,
        )
        self.DeveloperDisplayDriver = DeveloperDisplayDriver
        self.DisplayManager = DisplayManager
        self.DisplayMode = DisplayMode
        self.StatusInfo = StatusInfo

    def test_developerDriver_showsSimIndicator_inSimulationMode(self) -> None:
        """Test developer driver shows SIM indicator when in simulation mode."""
        output = io.StringIO()
        driver = self.DeveloperDisplayDriver({"useColors": False})
        driver.setOutputStream(output)
        driver.initialize()

        # Set simulation mode
        driver.setSimulationMode(True)

        status = self.StatusInfo(connectionStatus="Connected", currentRpm=2500)
        driver.showStatus(status)

        outputText = output.getvalue()
        self.assertIn("SIM", outputText)

    def test_developerDriver_noSimIndicator_withoutSimulationMode(self) -> None:
        """Test developer driver doesn't show SIM indicator when not in simulation mode."""
        output = io.StringIO()
        driver = self.DeveloperDisplayDriver({"useColors": False})
        driver.setOutputStream(output)
        driver.initialize()

        # Ensure not in simulation mode (default)
        driver.setSimulationMode(False)

        status = self.StatusInfo(connectionStatus="Connected", currentRpm=2500)
        driver.showStatus(status)

        outputText = output.getvalue()
        # SIM should not appear as an indicator
        # Note: may appear in status line but not as primary indicator
        lines = outputText.split('\n')
        simIndicatorPresent = any(
            line.strip().startswith('[SIM]') or line.strip().startswith('SIM')
            for line in lines
        )
        self.assertFalse(simIndicatorPresent)

    def test_developerDriver_showsCurrentPhase_whenScenarioRunning(self) -> None:
        """Test developer driver shows current phase when scenario is running."""
        output = io.StringIO()
        driver = self.DeveloperDisplayDriver({"useColors": False})
        driver.setOutputStream(output)
        driver.initialize()

        driver.setSimulationMode(True)
        driver.setSimulatorStatus(SimulatorStatus(
            isRunning=True,
            currentPhase="highway_cruise",
            scenarioName="test_drive",
        ))

        status = self.StatusInfo(connectionStatus="Connected", currentRpm=3000)
        driver.showStatus(status)

        outputText = output.getvalue()
        self.assertIn("highway_cruise", outputText)

    def test_developerDriver_showsActiveFailures_whenPresent(self) -> None:
        """Test developer driver shows active failures when present."""
        output = io.StringIO()
        driver = self.DeveloperDisplayDriver({"useColors": False})
        driver.setOutputStream(output)
        driver.initialize()

        driver.setSimulationMode(True)
        driver.setSimulatorStatus(SimulatorStatus(
            isRunning=True,
            activeFailures=["connectionDrop", "sensorFailure"],
        ))

        status = self.StatusInfo(connectionStatus="Connected", currentRpm=2500)
        driver.showStatus(status)

        outputText = output.getvalue()
        self.assertIn("connectionDrop", outputText)
        self.assertIn("sensorFailure", outputText)

    def test_developerDriver_showsScenarioProgress(self) -> None:
        """Test developer driver shows scenario progress."""
        output = io.StringIO()
        driver = self.DeveloperDisplayDriver({"useColors": False})
        driver.setOutputStream(output)
        driver.initialize()

        driver.setSimulationMode(True)
        driver.setSimulatorStatus(SimulatorStatus(
            isRunning=True,
            currentPhase="cruise",
            scenarioName="city_driving",
            scenarioProgress=45.5,
            elapsedSeconds=60.0,
        ))

        status = self.StatusInfo(connectionStatus="Connected", currentRpm=2000)
        driver.showStatus(status)

        outputText = output.getvalue()
        # Should show progress indicator
        self.assertIn("45", outputText)  # Progress percentage

    def test_developerDriver_setSimulatorStatus_updatesState(self) -> None:
        """Test setSimulatorStatus updates internal state."""
        driver = self.DeveloperDisplayDriver({"useColors": False})
        driver.initialize()

        simStatus = SimulatorStatus(
            isRunning=True,
            currentPhase="test_phase",
            activeFailures=["dtcCodes"],
        )
        driver.setSimulatorStatus(simStatus)

        self.assertEqual(driver.getSimulatorStatus(), simStatus)

    def test_developerDriver_getSimulatorStatus_returnsNone_byDefault(self) -> None:
        """Test getSimulatorStatus returns None by default."""
        driver = self.DeveloperDisplayDriver({"useColors": False})
        driver.initialize()

        self.assertIsNone(driver.getSimulatorStatus())


class TestSimulatorStatusIntegration(unittest.TestCase):
    """Integration tests for simulator status with all components."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.profile = getDefaultProfile()
        self.simulator = SensorSimulator(self.profile)
        self.failureInjector = FailureInjector()

    def tearDown(self) -> None:
        """Clean up after tests."""
        self.failureInjector.stopScheduler()
        self.failureInjector.reset()

    def test_fullIntegration_scenarioWithFailures(self) -> None:
        """Test full integration with scenario and failures."""
        scenario = DriveScenario(
            name="integration_test",
            description="Full integration test",
            phases=[
                DrivePhase(name="warmup", durationSeconds=10, targetThrottle=0),
                DrivePhase(name="drive", durationSeconds=20, targetThrottle=40),
            ]
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        runner.start()

        # Inject a failure
        self.failureInjector.injectFailure(
            FailureType.INTERMITTENT_SENSOR,
            FailureConfig(probability=0.5)
        )

        # Get status
        provider = SimulatorStatusProvider(
            simulator=self.simulator,
            scenarioRunner=runner,
            failureInjector=self.failureInjector,
        )
        status = provider.getStatus()

        # Verify all components represented
        self.assertTrue(status.isRunning)
        self.assertTrue(status.isSimulationMode)
        self.assertEqual(status.scenarioName, "integration_test")
        self.assertEqual(status.currentPhase, "warmup")
        self.assertIn("intermittentSensor", status.activeFailures)
        self.assertIsNotNone(status.vehicleState)

    def test_vehicleStateSnapshot_capturesMomentInTime(self) -> None:
        """Test vehicle state is a snapshot at the moment of status retrieval."""
        self.simulator.startEngine()
        self.simulator.setThrottle(50)

        provider = SimulatorStatusProvider(simulator=self.simulator)

        # Get initial status
        status1 = provider.getStatus()
        rpm1 = status1.vehicleState.rpm

        # Update simulator
        self.simulator.update(0.5)

        # Get new status
        status2 = provider.getStatus()
        rpm2 = status2.vehicleState.rpm

        # RPM should have changed
        self.assertNotEqual(rpm1, rpm2)


def suite() -> unittest.TestSuite:
    """Create test suite."""
    testSuite = unittest.TestSuite()
    testSuite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSimulatorStatusDataclass))
    testSuite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSimulatorStatusProvider))
    testSuite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestGetSimulatorStatusFunction))
    testSuite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestCreateSimulatorStatusProvider))
    testSuite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestDeveloperDisplaySimIndicator))
    testSuite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSimulatorStatusIntegration))
    return testSuite


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())
