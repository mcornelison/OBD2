################################################################################
# File Name: run_tests_drive_scenario.py
# Purpose/Description: Tests for DriveScenario system
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
Tests for the drive scenario module.

Covers:
- DrivePhase dataclass creation and serialization
- DriveScenario dataclass creation and validation
- DriveScenarioRunner execution and callbacks
- Scenario loading from JSON files
- Built-in scenario availability
- Phase transitions and looping
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from obd.simulator.drive_scenario import (
    DrivePhase,
    DriveScenario,
    DriveScenarioError,
    DriveScenarioRunner,
    ScenarioLoadError,
    ScenarioState,
    ScenarioValidationError,
    createScenarioFromConfig,
    getBuiltInScenario,
    getCityDrivingScenario,
    getColdStartScenario,
    getDefaultScenario,
    getFullCycleScenario,
    getHighwayCruiseScenario,
    getScenariosDirectory,
    listAvailableScenarios,
    loadScenario,
    saveScenario,
)
from obd.simulator.sensor_simulator import SensorSimulator
from obd.simulator.vehicle_profile import getDefaultProfile


# ================================================================================
# DrivePhase Tests
# ================================================================================


class TestDrivePhase(unittest.TestCase):
    """Tests for DrivePhase dataclass."""

    def test_create_minimalPhase_hasDefaults(self):
        """
        Given: Minimal phase parameters
        When: DrivePhase is created
        Then: Optional fields have None defaults
        """
        # Arrange & Act
        phase = DrivePhase(name="test", durationSeconds=10.0)

        # Assert
        self.assertEqual(phase.name, "test")
        self.assertEqual(phase.durationSeconds, 10.0)
        self.assertIsNone(phase.targetRpm)
        self.assertIsNone(phase.targetSpeedKph)
        self.assertIsNone(phase.targetThrottle)
        self.assertIsNone(phase.targetGear)
        self.assertIsNone(phase.description)

    def test_create_fullPhase_allFieldsSet(self):
        """
        Given: All phase parameters provided
        When: DrivePhase is created
        Then: All fields are set correctly
        """
        # Arrange & Act
        phase = DrivePhase(
            name="acceleration",
            durationSeconds=5.0,
            targetRpm=3000,
            targetSpeedKph=60,
            targetThrottle=40,
            targetGear=3,
            description="Accelerating in 3rd gear",
        )

        # Assert
        self.assertEqual(phase.name, "acceleration")
        self.assertEqual(phase.durationSeconds, 5.0)
        self.assertEqual(phase.targetRpm, 3000)
        self.assertEqual(phase.targetSpeedKph, 60)
        self.assertEqual(phase.targetThrottle, 40)
        self.assertEqual(phase.targetGear, 3)
        self.assertEqual(phase.description, "Accelerating in 3rd gear")

    def test_toDict_minimalPhase_onlyRequiredFields(self):
        """
        Given: Minimal phase
        When: toDict is called
        Then: Only required fields are in dict
        """
        # Arrange
        phase = DrivePhase(name="test", durationSeconds=10.0)

        # Act
        result = phase.toDict()

        # Assert
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["durationSeconds"], 10.0)
        self.assertNotIn("targetRpm", result)
        self.assertNotIn("targetSpeedKph", result)

    def test_toDict_fullPhase_allFieldsIncluded(self):
        """
        Given: Phase with all optional fields
        When: toDict is called
        Then: All fields are in dict
        """
        # Arrange
        phase = DrivePhase(
            name="test",
            durationSeconds=10.0,
            targetRpm=2000,
            targetSpeedKph=50,
            targetThrottle=30,
            targetGear=3,
            description="Test phase",
        )

        # Act
        result = phase.toDict()

        # Assert
        self.assertEqual(result["targetRpm"], 2000)
        self.assertEqual(result["targetSpeedKph"], 50)
        self.assertEqual(result["targetThrottle"], 30)
        self.assertEqual(result["targetGear"], 3)
        self.assertEqual(result["description"], "Test phase")

    def test_fromDict_validDict_createsPhase(self):
        """
        Given: Valid phase dictionary
        When: fromDict is called
        Then: DrivePhase is created correctly
        """
        # Arrange
        data = {
            "name": "test",
            "durationSeconds": 10.0,
            "targetRpm": 2000,
            "targetThrottle": 30,
        }

        # Act
        phase = DrivePhase.fromDict(data)

        # Assert
        self.assertEqual(phase.name, "test")
        self.assertEqual(phase.durationSeconds, 10.0)
        self.assertEqual(phase.targetRpm, 2000)
        self.assertEqual(phase.targetThrottle, 30)
        self.assertIsNone(phase.targetSpeedKph)

    def test_fromDict_missingName_raisesValidationError(self):
        """
        Given: Dict missing 'name' field
        When: fromDict is called
        Then: ScenarioValidationError is raised
        """
        # Arrange
        data = {"durationSeconds": 10.0}

        # Act & Assert
        with self.assertRaises(ScenarioValidationError) as ctx:
            DrivePhase.fromDict(data)

        self.assertIn("name", ctx.exception.invalidFields)

    def test_fromDict_missingDuration_raisesValidationError(self):
        """
        Given: Dict missing 'durationSeconds' field
        When: fromDict is called
        Then: ScenarioValidationError is raised
        """
        # Arrange
        data = {"name": "test"}

        # Act & Assert
        with self.assertRaises(ScenarioValidationError) as ctx:
            DrivePhase.fromDict(data)

        self.assertIn("durationSeconds", ctx.exception.invalidFields)


# ================================================================================
# DriveScenario Tests
# ================================================================================


class TestDriveScenario(unittest.TestCase):
    """Tests for DriveScenario dataclass."""

    def test_create_emptyScenario_hasEmptyPhases(self):
        """
        Given: Scenario with no phases
        When: DriveScenario is created
        Then: phases is empty list
        """
        # Arrange & Act
        scenario = DriveScenario(
            name="test",
            description="Test scenario",
        )

        # Assert
        self.assertEqual(scenario.phases, [])
        self.assertEqual(scenario.loopCount, 0)

    def test_create_scenarioWithPhases_phasesStored(self):
        """
        Given: Scenario with phases
        When: DriveScenario is created
        Then: phases are stored correctly
        """
        # Arrange
        phases = [
            DrivePhase(name="start", durationSeconds=5.0),
            DrivePhase(name="drive", durationSeconds=30.0),
            DrivePhase(name="stop", durationSeconds=5.0),
        ]

        # Act
        scenario = DriveScenario(
            name="test",
            description="Test scenario",
            phases=phases,
        )

        # Assert
        self.assertEqual(len(scenario.phases), 3)
        self.assertEqual(scenario.phases[0].name, "start")
        self.assertEqual(scenario.phases[1].name, "drive")
        self.assertEqual(scenario.phases[2].name, "stop")

    def test_getTotalDuration_calculatesSum(self):
        """
        Given: Scenario with multiple phases
        When: getTotalDuration is called
        Then: Returns sum of phase durations
        """
        # Arrange
        phases = [
            DrivePhase(name="start", durationSeconds=5.0),
            DrivePhase(name="drive", durationSeconds=30.0),
            DrivePhase(name="stop", durationSeconds=10.0),
        ]
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=phases,
        )

        # Act
        duration = scenario.getTotalDuration()

        # Assert
        self.assertEqual(duration, 45.0)

    def test_getTotalDuration_emptyScenario_returnsZero(self):
        """
        Given: Scenario with no phases
        When: getTotalDuration is called
        Then: Returns 0
        """
        # Arrange
        scenario = DriveScenario(name="test", description="Test")

        # Act
        duration = scenario.getTotalDuration()

        # Assert
        self.assertEqual(duration, 0.0)

    def test_validate_validScenario_returnsEmptyList(self):
        """
        Given: Valid scenario
        When: validate is called
        Then: Returns empty list
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test scenario",
            phases=[DrivePhase(name="idle", durationSeconds=10.0)],
        )

        # Act
        errors = scenario.validate()

        # Assert
        self.assertEqual(errors, [])

    def test_validate_emptyName_returnsError(self):
        """
        Given: Scenario with empty name
        When: validate is called
        Then: Returns error about name
        """
        # Arrange
        scenario = DriveScenario(
            name="",
            description="Test",
            phases=[DrivePhase(name="idle", durationSeconds=10.0)],
        )

        # Act
        errors = scenario.validate()

        # Assert
        self.assertIn("Scenario name is required", errors)

    def test_validate_noPhases_returnsError(self):
        """
        Given: Scenario with no phases
        When: validate is called
        Then: Returns error about phases
        """
        # Arrange
        scenario = DriveScenario(name="test", description="Test", phases=[])

        # Act
        errors = scenario.validate()

        # Assert
        self.assertIn("Scenario must have at least one phase", errors)

    def test_validate_negativeDuration_returnsError(self):
        """
        Given: Phase with negative duration
        When: validate is called
        Then: Returns error about duration
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[DrivePhase(name="bad", durationSeconds=-5.0)],
        )

        # Act
        errors = scenario.validate()

        # Assert
        self.assertTrue(any("duration must be positive" in e for e in errors))

    def test_validate_throttleOutOfRange_returnsError(self):
        """
        Given: Phase with throttle > 100
        When: validate is called
        Then: Returns error about throttle range
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[
                DrivePhase(name="bad", durationSeconds=10.0, targetThrottle=150)
            ],
        )

        # Act
        errors = scenario.validate()

        # Assert
        self.assertTrue(any("targetThrottle must be 0-100" in e for e in errors))

    def test_toDict_roundTrip_preservesData(self):
        """
        Given: Complete scenario
        When: toDict then fromDict
        Then: Data is preserved
        """
        # Arrange
        original = DriveScenario(
            name="test",
            description="Test scenario",
            phases=[
                DrivePhase(name="start", durationSeconds=5.0, targetRpm=800),
                DrivePhase(name="drive", durationSeconds=30.0, targetThrottle=30),
            ],
            loopCount=2,
        )

        # Act
        data = original.toDict()
        restored = DriveScenario.fromDict(data)

        # Assert
        self.assertEqual(restored.name, original.name)
        self.assertEqual(restored.description, original.description)
        self.assertEqual(restored.loopCount, original.loopCount)
        self.assertEqual(len(restored.phases), len(original.phases))
        self.assertEqual(restored.phases[0].name, "start")
        self.assertEqual(restored.phases[0].targetRpm, 800)

    def test_fromDict_missingFields_raisesValidationError(self):
        """
        Given: Dict missing required fields
        When: fromDict is called
        Then: ScenarioValidationError is raised
        """
        # Arrange
        data = {"name": "test"}  # Missing description and phases

        # Act & Assert
        with self.assertRaises(ScenarioValidationError) as ctx:
            DriveScenario.fromDict(data)

        self.assertIn("description", ctx.exception.invalidFields)
        self.assertIn("phases", ctx.exception.invalidFields)


# ================================================================================
# DriveScenarioRunner Tests
# ================================================================================


class TestDriveScenarioRunner(unittest.TestCase):
    """Tests for DriveScenarioRunner class."""

    def setUp(self):
        """Set up test fixtures."""
        self.profile = getDefaultProfile()
        self.simulator = SensorSimulator(self.profile, noiseEnabled=False)
        self.scenario = DriveScenario(
            name="test",
            description="Test scenario",
            phases=[
                DrivePhase(name="idle", durationSeconds=2.0, targetThrottle=0),
                DrivePhase(name="drive", durationSeconds=3.0, targetThrottle=30),
                DrivePhase(name="stop", durationSeconds=1.0, targetThrottle=0),
            ],
        )

    def test_create_runner_initialStateIdle(self):
        """
        Given: New runner
        When: Created
        Then: State is IDLE
        """
        # Arrange & Act
        runner = DriveScenarioRunner(self.simulator, self.scenario)

        # Assert
        self.assertEqual(runner.state, ScenarioState.IDLE)
        self.assertFalse(runner.isRunning())

    def test_start_validScenario_startsExecution(self):
        """
        Given: Valid scenario
        When: start is called
        Then: Runner begins execution
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)

        # Act
        result = runner.start()

        # Assert
        self.assertTrue(result)
        self.assertTrue(runner.isRunning())
        self.assertEqual(runner.state, ScenarioState.RUNNING)
        self.assertEqual(runner.currentPhaseIndex, 0)

    def test_start_emptyScenario_returnsFalse(self):
        """
        Given: Scenario with no phases
        When: start is called
        Then: Returns False and sets ERROR state
        """
        # Arrange
        emptyScenario = DriveScenario(name="empty", description="Empty", phases=[])
        runner = DriveScenarioRunner(self.simulator, emptyScenario)

        # Act
        result = runner.start()

        # Assert
        self.assertFalse(result)
        self.assertEqual(runner.state, ScenarioState.ERROR)

    def test_start_startsEngine(self):
        """
        Given: Engine not running
        When: start is called
        Then: Engine is started
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        self.assertFalse(self.simulator.isRunning())

        # Act
        runner.start()

        # Assert
        self.assertTrue(self.simulator.isRunning())

    def test_stop_runningScenario_stopsExecution(self):
        """
        Given: Running scenario
        When: stop is called
        Then: Execution stops
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()

        # Act
        runner.stop()

        # Assert
        self.assertFalse(runner.isRunning())
        self.assertEqual(runner.state, ScenarioState.IDLE)

    def test_pause_runningScenario_pausesExecution(self):
        """
        Given: Running scenario
        When: pause is called
        Then: State is PAUSED
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()

        # Act
        runner.pause()

        # Assert
        self.assertTrue(runner.isPaused())
        self.assertEqual(runner.state, ScenarioState.PAUSED)

    def test_resume_pausedScenario_resumesExecution(self):
        """
        Given: Paused scenario
        When: resume is called
        Then: State returns to RUNNING
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()
        runner.pause()

        # Act
        runner.resume()

        # Assert
        self.assertTrue(runner.isRunning())
        self.assertEqual(runner.state, ScenarioState.RUNNING)

    def test_update_advancesTime(self):
        """
        Given: Running scenario
        When: update is called
        Then: Time advances
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()

        # Act
        runner.update(0.5)

        # Assert
        self.assertEqual(runner.phaseElapsedSeconds, 0.5)
        self.assertEqual(runner.totalElapsedSeconds, 0.5)

    def test_update_phaseComplete_advancesToNextPhase(self):
        """
        Given: Phase duration exceeded
        When: update is called
        Then: Advances to next phase
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()
        self.assertEqual(runner.currentPhaseIndex, 0)

        # Act - advance past first phase (2 seconds)
        runner.update(2.5)

        # Assert
        self.assertEqual(runner.currentPhaseIndex, 1)

    def test_update_allPhasesComplete_scenarioCompleted(self):
        """
        Given: All phases completed
        When: update finishes last phase
        Then: Scenario is completed
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()

        # Act - advance past all phases (total 6 seconds)
        runner.update(2.5)  # Past phase 0
        runner.update(3.5)  # Past phase 1
        runner.update(1.5)  # Past phase 2

        # Assert
        self.assertTrue(runner.isCompleted())
        self.assertEqual(runner.state, ScenarioState.COMPLETED)

    def test_update_paused_doesNotAdvance(self):
        """
        Given: Paused scenario
        When: update is called
        Then: Time does not advance
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()
        runner.update(0.5)
        runner.pause()

        # Act
        runner.update(1.0)

        # Assert
        self.assertEqual(runner.phaseElapsedSeconds, 0.5)

    def test_getCurrentPhase_returnsCurrentPhase(self):
        """
        Given: Running scenario
        When: getCurrentPhase is called
        Then: Returns current phase
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()

        # Act
        phase = runner.getCurrentPhase()

        # Assert
        self.assertIsNotNone(phase)
        self.assertEqual(phase.name, "idle")

    def test_getProgress_calculatesCorrectly(self):
        """
        Given: Running scenario partway through
        When: getProgress is called
        Then: Returns expected progress percentage
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()

        # Total duration is 6 seconds (2+3+1)
        # First phase is 2 seconds, update with less than that
        runner.update(1.0)  # 1s into first phase (2s duration)

        # Act
        progress = runner.getProgress()

        # Assert - should be about 16.67% (1 / 6)
        expectedProgress = 1.0 / 6.0 * 100.0
        self.assertAlmostEqual(progress, expectedProgress, delta=2.0)

    def test_getPhaseProgress_calculatesCorrectly(self):
        """
        Given: Running scenario halfway through phase
        When: getPhaseProgress is called
        Then: Returns approximately 50%
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()
        # First phase is 2 seconds
        runner.update(1.0)  # 50% through

        # Act
        progress = runner.getPhaseProgress()

        # Assert
        self.assertAlmostEqual(progress, 50.0, delta=1.0)

    def test_getStatus_returnsComprehensiveStatus(self):
        """
        Given: Running scenario
        When: getStatus is called
        Then: Returns status dict with all fields
        """
        # Arrange
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.start()
        runner.update(1.0)

        # Act
        status = runner.getStatus()

        # Assert
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["scenarioName"], "test")
        self.assertEqual(status["currentPhaseIndex"], 0)
        self.assertEqual(status["currentPhaseName"], "idle")
        self.assertAlmostEqual(status["phaseElapsedSeconds"], 1.0, delta=0.01)
        self.assertEqual(status["totalPhases"], 3)


# ================================================================================
# Callback Tests
# ================================================================================


class TestDriveScenarioRunnerCallbacks(unittest.TestCase):
    """Tests for DriveScenarioRunner callbacks."""

    def setUp(self):
        """Set up test fixtures."""
        self.profile = getDefaultProfile()
        self.simulator = SensorSimulator(self.profile, noiseEnabled=False)
        self.scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[
                DrivePhase(name="phase1", durationSeconds=1.0, targetThrottle=0),
                DrivePhase(name="phase2", durationSeconds=1.0, targetThrottle=30),
            ],
        )

    def test_onPhaseStart_calledAtStart(self):
        """
        Given: onPhaseStart callback set
        When: Scenario starts
        Then: Callback is called with first phase
        """
        # Arrange
        callback = MagicMock()
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.onPhaseStart = callback

        # Act
        runner.start()

        # Assert
        callback.assert_called_once()
        self.assertEqual(callback.call_args[0][0].name, "phase1")

    def test_onPhaseStart_calledOnPhaseTransition(self):
        """
        Given: onPhaseStart callback set
        When: Phase transitions
        Then: Callback is called with new phase
        """
        # Arrange
        callback = MagicMock()
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.onPhaseStart = callback
        runner.start()
        callback.reset_mock()

        # Act - advance past first phase
        runner.update(1.5)

        # Assert
        callback.assert_called_once()
        self.assertEqual(callback.call_args[0][0].name, "phase2")

    def test_onPhaseEnd_calledOnPhaseComplete(self):
        """
        Given: onPhaseEnd callback set
        When: Phase completes
        Then: Callback is called
        """
        # Arrange
        callback = MagicMock()
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.onPhaseEnd = callback
        runner.start()

        # Act - advance past first phase
        runner.update(1.5)

        # Assert
        callback.assert_called_once()
        self.assertEqual(callback.call_args[0][0].name, "phase1")

    def test_onScenarioComplete_calledOnCompletion(self):
        """
        Given: onScenarioComplete callback set
        When: Scenario completes
        Then: Callback is called
        """
        # Arrange
        callback = MagicMock()
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.onScenarioComplete = callback
        runner.start()

        # Act - advance past all phases
        runner.update(1.5)  # Past phase 1
        runner.update(1.5)  # Past phase 2

        # Assert
        callback.assert_called_once()

    def test_onLoopComplete_calledOnLoopEnd(self):
        """
        Given: Scenario with loopCount > 0
        When: One loop completes
        Then: onLoopComplete callback is called
        """
        # Arrange
        self.scenario.loopCount = 2
        callback = MagicMock()
        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.onLoopComplete = callback
        runner.start()

        # Act - complete one loop
        runner.update(1.5)  # Past phase 1
        runner.update(1.5)  # Past phase 2

        # Assert
        callback.assert_called_once_with(1)

    def test_callbackException_doesNotCrashRunner(self):
        """
        Given: Callback raises exception
        When: Callback is invoked
        Then: Runner continues without crashing
        """
        # Arrange

        def badCallback(phase):
            raise RuntimeError("Callback error")

        runner = DriveScenarioRunner(self.simulator, self.scenario)
        runner.onPhaseStart = badCallback
        runner.onPhaseEnd = badCallback

        # Act & Assert - should not raise
        runner.start()
        runner.update(1.5)


# ================================================================================
# Looping Tests
# ================================================================================


class TestDriveScenarioLooping(unittest.TestCase):
    """Tests for scenario looping behavior."""

    def setUp(self):
        """Set up test fixtures."""
        self.profile = getDefaultProfile()
        self.simulator = SensorSimulator(self.profile, noiseEnabled=False)

    def test_loopCountZero_noLooping(self):
        """
        Given: loopCount = 0
        When: Scenario completes
        Then: Does not restart
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[DrivePhase(name="only", durationSeconds=1.0)],
            loopCount=0,
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        runner.start()

        # Act
        runner.update(1.5)

        # Assert
        self.assertTrue(runner.isCompleted())
        self.assertEqual(runner.loopsCompleted, 1)

    def test_loopCountPositive_loopsSpecifiedTimes(self):
        """
        Given: loopCount = 2
        When: Scenario runs
        Then: Loops exactly 2 times
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[DrivePhase(name="only", durationSeconds=1.0)],
            loopCount=2,
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        loopCallback = MagicMock()
        runner.onLoopComplete = loopCallback
        runner.start()

        # Act - run through 2 loops
        runner.update(1.5)  # Loop 1
        runner.update(1.5)  # Loop 2

        # Assert
        self.assertTrue(runner.isCompleted())
        self.assertEqual(runner.loopsCompleted, 2)
        self.assertEqual(loopCallback.call_count, 2)

    def test_loopCountNegative_loopsIndefinitely(self):
        """
        Given: loopCount = -1 (infinite)
        When: Multiple loops complete
        Then: Continues looping
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[DrivePhase(name="only", durationSeconds=1.0)],
            loopCount=-1,  # Infinite
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        runner.start()

        # Act - run through 5 loops
        for _ in range(5):
            runner.update(1.5)

        # Assert - still running (not completed)
        self.assertTrue(runner.isRunning())
        self.assertEqual(runner.loopsCompleted, 5)

    def test_looping_resetsToFirstPhase(self):
        """
        Given: Scenario with multiple phases and loopCount > 0
        When: Loop completes
        Then: Returns to first phase
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[
                DrivePhase(name="first", durationSeconds=1.0),
                DrivePhase(name="second", durationSeconds=1.0),
            ],
            loopCount=2,
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        runner.start()

        # Act - complete first loop
        runner.update(1.5)  # Past first phase
        runner.update(1.5)  # Past second phase (loop 1 complete)

        # Assert - back at first phase
        self.assertEqual(runner.currentPhaseIndex, 0)
        self.assertEqual(runner.getCurrentPhase().name, "first")


# ================================================================================
# File Loading Tests
# ================================================================================


class TestScenarioLoading(unittest.TestCase):
    """Tests for scenario file loading."""

    def test_loadScenario_validFile_loadsCorrectly(self):
        """
        Given: Valid scenario JSON file
        When: loadScenario is called
        Then: Scenario is loaded correctly
        """
        # Arrange
        scenarioData = {
            "name": "test",
            "description": "Test scenario",
            "phases": [{"name": "idle", "durationSeconds": 10.0}],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(scenarioData, f)
            tempPath = f.name

        try:
            # Act
            scenario = loadScenario(tempPath)

            # Assert
            self.assertEqual(scenario.name, "test")
            self.assertEqual(len(scenario.phases), 1)
        finally:
            os.unlink(tempPath)

    def test_loadScenario_fileNotFound_raisesError(self):
        """
        Given: Non-existent file path
        When: loadScenario is called
        Then: ScenarioLoadError is raised
        """
        # Act & Assert
        with self.assertRaises(ScenarioLoadError) as ctx:
            loadScenario("/nonexistent/path.json")

        self.assertIn("not found", str(ctx.exception))

    def test_loadScenario_invalidJson_raisesError(self):
        """
        Given: File with invalid JSON
        When: loadScenario is called
        Then: ScenarioLoadError is raised
        """
        # Arrange
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("{invalid json")
            tempPath = f.name

        try:
            # Act & Assert
            with self.assertRaises(ScenarioLoadError) as ctx:
                loadScenario(tempPath)

            self.assertIn("Invalid JSON", str(ctx.exception))
        finally:
            os.unlink(tempPath)

    def test_loadScenario_invalidScenario_raisesValidationError(self):
        """
        Given: JSON file with invalid scenario (negative duration)
        When: loadScenario is called
        Then: ScenarioValidationError is raised
        """
        # Arrange
        scenarioData = {
            "name": "test",
            "description": "Test",
            "phases": [{"name": "bad", "durationSeconds": -5.0}],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(scenarioData, f)
            tempPath = f.name

        try:
            # Act & Assert
            with self.assertRaises(ScenarioValidationError):
                loadScenario(tempPath)
        finally:
            os.unlink(tempPath)

    def test_saveScenario_createsFile(self):
        """
        Given: Valid scenario
        When: saveScenario is called
        Then: JSON file is created
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[DrivePhase(name="idle", durationSeconds=10.0)],
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            tempPath = f.name

        try:
            # Act
            saveScenario(scenario, tempPath)

            # Assert
            with open(tempPath, "r") as f:
                data = json.load(f)
            self.assertEqual(data["name"], "test")
            self.assertEqual(len(data["phases"]), 1)
        finally:
            os.unlink(tempPath)


# ================================================================================
# Built-in Scenario Tests
# ================================================================================


class TestBuiltInScenarios(unittest.TestCase):
    """Tests for built-in scenarios."""

    def test_getDefaultScenario_returnsValidScenario(self):
        """
        Given: Nothing
        When: getDefaultScenario is called
        Then: Returns a valid scenario
        """
        # Act
        scenario = getDefaultScenario()

        # Assert
        self.assertEqual(scenario.name, "default")
        self.assertGreater(len(scenario.phases), 0)
        self.assertEqual(scenario.validate(), [])

    def test_getColdStartScenario_returnsValidScenario(self):
        """
        Given: Nothing
        When: getColdStartScenario is called
        Then: Returns valid cold start scenario
        """
        # Act
        scenario = getColdStartScenario()

        # Assert
        self.assertEqual(scenario.name, "cold_start")
        self.assertGreater(len(scenario.phases), 0)
        self.assertEqual(scenario.validate(), [])

    def test_getCityDrivingScenario_returnsValidScenario(self):
        """
        Given: Nothing
        When: getCityDrivingScenario is called
        Then: Returns valid city driving scenario
        """
        # Act
        scenario = getCityDrivingScenario()

        # Assert
        self.assertEqual(scenario.name, "city_driving")
        self.assertGreater(len(scenario.phases), 0)
        self.assertEqual(scenario.validate(), [])

    def test_getHighwayCruiseScenario_returnsValidScenario(self):
        """
        Given: Nothing
        When: getHighwayCruiseScenario is called
        Then: Returns valid highway cruise scenario
        """
        # Act
        scenario = getHighwayCruiseScenario()

        # Assert
        self.assertEqual(scenario.name, "highway_cruise")
        self.assertGreater(len(scenario.phases), 0)
        self.assertEqual(scenario.validate(), [])

    def test_getFullCycleScenario_returnsValidScenario(self):
        """
        Given: Nothing
        When: getFullCycleScenario is called
        Then: Returns valid full cycle scenario
        """
        # Act
        scenario = getFullCycleScenario()

        # Assert
        self.assertEqual(scenario.name, "full_cycle")
        self.assertGreater(len(scenario.phases), 0)
        self.assertEqual(scenario.validate(), [])

    def test_listAvailableScenarios_returnsBuiltIns(self):
        """
        Given: Scenarios directory exists with files
        When: listAvailableScenarios is called
        Then: Returns list of scenario names
        """
        # Act
        scenarios = listAvailableScenarios()

        # Assert
        self.assertIn("cold_start", scenarios)
        self.assertIn("city_driving", scenarios)
        self.assertIn("highway_cruise", scenarios)
        self.assertIn("full_cycle", scenarios)

    def test_getBuiltInScenario_loadsFromFile(self):
        """
        Given: Built-in scenario exists
        When: getBuiltInScenario is called
        Then: Loads scenario from JSON file
        """
        # Act
        scenario = getBuiltInScenario("city_driving")

        # Assert
        self.assertEqual(scenario.name, "city_driving")
        self.assertGreater(len(scenario.phases), 0)

    def test_getBuiltInScenario_notFound_raisesError(self):
        """
        Given: Non-existent scenario name
        When: getBuiltInScenario is called
        Then: ScenarioLoadError is raised
        """
        # Act & Assert
        with self.assertRaises(ScenarioLoadError):
            getBuiltInScenario("nonexistent_scenario")

    def test_getScenariosDirectory_returnsPath(self):
        """
        Given: Module is installed
        When: getScenariosDirectory is called
        Then: Returns valid directory path
        """
        # Act
        scenariosDir = getScenariosDirectory()

        # Assert
        self.assertTrue(os.path.isdir(scenariosDir))


# ================================================================================
# Config-based Creation Tests
# ================================================================================


class TestCreateScenarioFromConfig(unittest.TestCase):
    """Tests for creating scenarios from config."""

    def test_createScenarioFromConfig_inlineScenario_createsFromDict(self):
        """
        Given: Config with inline scenario definition
        When: createScenarioFromConfig is called
        Then: Creates scenario from inline definition
        """
        # Arrange
        config = {
            "scenario": {
                "name": "inline_test",
                "description": "Inline test scenario",
                "phases": [{"name": "idle", "durationSeconds": 5.0}],
            }
        }

        # Act
        scenario = createScenarioFromConfig(config)

        # Assert
        self.assertEqual(scenario.name, "inline_test")

    def test_createScenarioFromConfig_noScenario_returnsDefault(self):
        """
        Given: Config with no scenario definition
        When: createScenarioFromConfig is called
        Then: Returns default scenario
        """
        # Arrange
        config = {}

        # Act
        scenario = createScenarioFromConfig(config)

        # Assert
        self.assertEqual(scenario.name, "default")

    def test_createScenarioFromConfig_scenarioPath_loadsFromFile(self):
        """
        Given: Config with scenarioPath
        When: createScenarioFromConfig is called
        Then: Loads scenario from file
        """
        # Arrange
        scenarioData = {
            "name": "from_path",
            "description": "From path",
            "phases": [{"name": "idle", "durationSeconds": 5.0}],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(scenarioData, f)
            tempPath = f.name

        config = {"simulator": {"scenarioPath": tempPath}}

        try:
            # Act
            scenario = createScenarioFromConfig(config)

            # Assert
            self.assertEqual(scenario.name, "from_path")
        finally:
            os.unlink(tempPath)


# ================================================================================
# Transition Tests
# ================================================================================


class TestSmoothTransitions(unittest.TestCase):
    """Tests for smooth phase transitions."""

    def setUp(self):
        """Set up test fixtures."""
        self.profile = getDefaultProfile()
        self.simulator = SensorSimulator(self.profile, noiseEnabled=False)

    def test_throttleTransition_smoothChange(self):
        """
        Given: Phase with target throttle
        When: Multiple updates
        Then: Throttle changes smoothly toward target
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[
                DrivePhase(
                    name="accelerate", durationSeconds=5.0, targetThrottle=50
                )
            ],
        )
        runner = DriveScenarioRunner(
            self.simulator, scenario, transitionRateThrottle=20.0  # 20%/sec
        )
        runner.start()
        self.simulator.setThrottle(0)  # Start at 0

        # Act - update for 1 second
        runner.update(1.0)

        # Assert - throttle should have increased but not reached 50 yet
        throttle = self.simulator.state.throttlePercent
        self.assertGreater(throttle, 0)
        self.assertLess(throttle, 50)

    def test_autoGearSelection_basedOnSpeed(self):
        """
        Given: Phase without explicit gear
        When: Speed changes
        Then: Gear is selected automatically
        """
        # Arrange
        scenario = DriveScenario(
            name="test",
            description="Test",
            phases=[
                DrivePhase(
                    name="drive",
                    durationSeconds=10.0,
                    targetThrottle=30,
                    # No targetGear - auto-select
                )
            ],
        )
        runner = DriveScenarioRunner(self.simulator, scenario)
        runner.start()

        # Act - update multiple times
        for _ in range(10):
            runner.update(0.5)

        # Assert - gear should be selected (not 0)
        gear = self.simulator.state.gear
        self.assertGreater(gear, 0)


# ================================================================================
# Main
# ================================================================================


if __name__ == "__main__":
    unittest.main()
