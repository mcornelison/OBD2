################################################################################
# File Name: run_tests_simulator_cli.py
# Purpose/Description: Tests for simulator CLI commands module
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-043
# ================================================================================
################################################################################

"""
Tests for the simulator CLI commands module.

Tests cover:
- CLI initialization and lifecycle
- Command processing (pause, status, clear, quit, help)
- Failure injection via CLI
- Callback support
- Integration with simulator components
- Non-blocking input handling
"""

import io
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

# Add src to path for imports
sys.path.insert(0, 'src')

from obd.simulator.simulator_cli import (
    SimulatorCli,
    CliState,
    CommandType,
    CommandResult,
    createSimulatorCli,
    createSimulatorCliFromConfig,
    COMMAND_PAUSE,
    COMMAND_FAILURE,
    COMMAND_CLEAR,
    COMMAND_STATUS,
    COMMAND_QUIT,
    COMMAND_HELP,
    VALID_COMMANDS,
)
from obd.simulator.sensor_simulator import SensorSimulator, VehicleState
from obd.simulator.failure_injector import FailureInjector, FailureType


class TestCliState(unittest.TestCase):
    """Tests for CliState enum."""

    def test_cliState_hasExpectedValues(self):
        """
        Given: CliState enum
        When: Accessing values
        Then: All expected states should exist
        """
        # Assert
        self.assertEqual(CliState.STOPPED.value, "stopped")
        self.assertEqual(CliState.RUNNING.value, "running")
        self.assertEqual(CliState.AWAITING_FAILURE_TYPE.value, "awaiting_failure_type")
        self.assertEqual(CliState.PAUSED.value, "paused")


class TestCommandType(unittest.TestCase):
    """Tests for CommandType enum."""

    def test_commandType_hasExpectedValues(self):
        """
        Given: CommandType enum
        When: Accessing values
        Then: All expected command types should exist
        """
        # Assert
        self.assertEqual(CommandType.PAUSE.value, "pause")
        self.assertEqual(CommandType.RESUME.value, "resume")
        self.assertEqual(CommandType.INJECT_FAILURE.value, "inject_failure")
        self.assertEqual(CommandType.CLEAR_FAILURES.value, "clear_failures")
        self.assertEqual(CommandType.STATUS.value, "status")
        self.assertEqual(CommandType.QUIT.value, "quit")
        self.assertEqual(CommandType.HELP.value, "help")
        self.assertEqual(CommandType.UNKNOWN.value, "unknown")


class TestCommandResult(unittest.TestCase):
    """Tests for CommandResult dataclass."""

    def test_commandResult_creation(self):
        """
        Given: CommandResult parameters
        When: Creating CommandResult
        Then: All fields should be set correctly
        """
        # Act
        result = CommandResult(
            command=CommandType.STATUS,
            success=True,
            message="Status displayed",
            details={"key": "value"},
        )

        # Assert
        self.assertEqual(result.command, CommandType.STATUS)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Status displayed")
        self.assertEqual(result.details, {"key": "value"})

    def test_commandResult_defaultDetails(self):
        """
        Given: CommandResult without details
        When: Creating CommandResult
        Then: Details should default to empty dict
        """
        # Act
        result = CommandResult(
            command=CommandType.PAUSE,
            success=True,
            message="Paused",
        )

        # Assert
        self.assertEqual(result.details, {})

    def test_commandResult_toDict(self):
        """
        Given: CommandResult
        When: Converting to dict
        Then: All fields should be included
        """
        # Arrange
        result = CommandResult(
            command=CommandType.QUIT,
            success=True,
            message="Quit requested",
            details={"reason": "user"},
        )

        # Act
        asDict = result.toDict()

        # Assert
        self.assertEqual(asDict["command"], "quit")
        self.assertTrue(asDict["success"])
        self.assertEqual(asDict["message"], "Quit requested")
        self.assertEqual(asDict["details"], {"reason": "user"})


class TestSimulatorCliInitialization(unittest.TestCase):
    """Tests for SimulatorCli initialization."""

    def test_init_withDefaultParameters(self):
        """
        Given: No parameters
        When: Creating SimulatorCli
        Then: Should initialize with default values
        """
        # Act
        cli = SimulatorCli()

        # Assert
        self.assertIsNone(cli.simulator)
        self.assertIsNone(cli.scenarioRunner)
        self.assertIsNone(cli.failureInjector)
        self.assertEqual(cli.state, CliState.STOPPED)
        self.assertFalse(cli.shouldQuit())
        self.assertFalse(cli.isPaused())
        self.assertFalse(cli.isRunning)

    def test_init_withSimulator(self):
        """
        Given: SensorSimulator instance
        When: Creating SimulatorCli with simulator
        Then: Simulator should be stored
        """
        # Arrange
        simulator = MagicMock()

        # Act
        cli = SimulatorCli(simulator=simulator)

        # Assert
        self.assertEqual(cli.simulator, simulator)

    def test_init_withFailureInjector(self):
        """
        Given: FailureInjector instance
        When: Creating SimulatorCli with failureInjector
        Then: Injector should be stored
        """
        # Arrange
        injector = FailureInjector()

        # Act
        cli = SimulatorCli(failureInjector=injector)

        # Assert
        self.assertEqual(cli.failureInjector, injector)

    def test_init_withOutputStream(self):
        """
        Given: Custom output stream
        When: Creating SimulatorCli
        Then: Output should go to custom stream
        """
        # Arrange
        output = io.StringIO()

        # Act
        cli = SimulatorCli(outputStream=output)
        cli.executeCommand(COMMAND_HELP)

        # Assert
        outputText = output.getvalue()
        self.assertIn("SIMULATOR COMMANDS", outputText)


class TestSimulatorCliLifecycle(unittest.TestCase):
    """Tests for SimulatorCli start/stop lifecycle."""

    def test_start_changesStateToRunning(self):
        """
        Given: Stopped CLI
        When: Calling start()
        Then: State should change to RUNNING
        """
        # Arrange
        output = io.StringIO()
        cli = SimulatorCli(outputStream=output)

        # Act
        result = cli.start()

        # Assert
        self.assertTrue(result)
        self.assertEqual(cli.state, CliState.RUNNING)
        self.assertTrue(cli.isRunning)

        # Cleanup
        cli.stop()

    def test_start_alreadyRunning_returnsFalse(self):
        """
        Given: Running CLI
        When: Calling start() again
        Then: Should return False
        """
        # Arrange
        output = io.StringIO()
        cli = SimulatorCli(outputStream=output)
        cli.start()

        # Act
        result = cli.start()

        # Assert
        self.assertFalse(result)

        # Cleanup
        cli.stop()

    def test_stop_changesStateToStopped(self):
        """
        Given: Running CLI
        When: Calling stop()
        Then: State should change to STOPPED
        """
        # Arrange
        output = io.StringIO()
        cli = SimulatorCli(outputStream=output)
        cli.start()

        # Act
        cli.stop()

        # Assert
        self.assertEqual(cli.state, CliState.STOPPED)
        self.assertFalse(cli.isRunning)

    def test_stop_alreadyStopped_noError(self):
        """
        Given: Already stopped CLI
        When: Calling stop()
        Then: Should not raise error
        """
        # Arrange
        cli = SimulatorCli()

        # Act & Assert - should not raise
        cli.stop()


class TestSimulatorCliCommands(unittest.TestCase):
    """Tests for SimulatorCli command execution."""

    def setUp(self):
        """Set up test fixtures."""
        self.output = io.StringIO()
        self.cli = SimulatorCli(outputStream=self.output)

    def tearDown(self):
        """Clean up after tests."""
        self.cli.stop()

    def test_executeCommand_pause_togglesPauseState(self):
        """
        Given: CLI not paused
        When: Executing pause command
        Then: Should toggle pause state
        """
        # Act
        result = self.cli.executeCommand(COMMAND_PAUSE)

        # Assert
        self.assertEqual(result.command, CommandType.PAUSE)
        self.assertTrue(result.success)
        self.assertTrue(self.cli.isPaused())

    def test_executeCommand_pause_togglesTwice(self):
        """
        Given: CLI paused
        When: Executing pause command again
        Then: Should resume (unpause)
        """
        # Arrange
        self.cli.executeCommand(COMMAND_PAUSE)  # Pause

        # Act
        result = self.cli.executeCommand(COMMAND_PAUSE)  # Resume

        # Assert
        self.assertEqual(result.command, CommandType.RESUME)
        self.assertTrue(result.success)
        self.assertFalse(self.cli.isPaused())

    def test_executeCommand_status_showsStatus(self):
        """
        Given: CLI with no components
        When: Executing status command
        Then: Should show basic status
        """
        # Act
        result = self.cli.executeCommand(COMMAND_STATUS)

        # Assert
        self.assertEqual(result.command, CommandType.STATUS)
        self.assertTrue(result.success)
        outputText = self.output.getvalue()
        self.assertIn("SIMULATOR STATUS", outputText)
        self.assertIn("State:", outputText)

    def test_executeCommand_help_showsHelp(self):
        """
        Given: CLI
        When: Executing help command
        Then: Should show help message
        """
        # Act
        result = self.cli.executeCommand(COMMAND_HELP)

        # Assert
        self.assertEqual(result.command, CommandType.HELP)
        self.assertTrue(result.success)
        outputText = self.output.getvalue()
        self.assertIn("SIMULATOR COMMANDS", outputText)
        self.assertIn("p - Pause", outputText)
        self.assertIn("q - Quit", outputText)

    def test_executeCommand_quit_setsQuitFlag(self):
        """
        Given: CLI
        When: Executing quit command
        Then: Should set quit flag
        """
        # Act
        result = self.cli.executeCommand(COMMAND_QUIT)

        # Assert
        self.assertEqual(result.command, CommandType.QUIT)
        self.assertTrue(result.success)
        self.assertTrue(self.cli.shouldQuit())

    def test_executeCommand_clear_withoutInjector(self):
        """
        Given: CLI without failure injector
        When: Executing clear command
        Then: Should return failure
        """
        # Act
        result = self.cli.executeCommand(COMMAND_CLEAR)

        # Assert
        self.assertEqual(result.command, CommandType.CLEAR_FAILURES)
        self.assertFalse(result.success)
        self.assertIn("No failure injector", result.message)

    def test_executeCommand_unknownCommand(self):
        """
        Given: CLI
        When: Executing unknown command
        Then: Should return failure
        """
        # Act
        result = self.cli.executeCommand('z')

        # Assert
        self.assertEqual(result.command, CommandType.UNKNOWN)
        self.assertFalse(result.success)

    def test_executeCommand_failure_promptsForType(self):
        """
        Given: CLI
        When: Executing failure command
        Then: Should prompt for failure type
        """
        # Act
        result = self.cli.executeCommand(COMMAND_FAILURE)

        # Assert
        self.assertEqual(result.command, CommandType.INJECT_FAILURE)
        self.assertTrue(result.success)
        outputText = self.output.getvalue()
        self.assertIn("Select failure type", outputText)
        self.assertIn("Connection Drop", outputText)


class TestSimulatorCliWithFailureInjector(unittest.TestCase):
    """Tests for SimulatorCli with FailureInjector."""

    def setUp(self):
        """Set up test fixtures."""
        self.output = io.StringIO()
        self.injector = FailureInjector()
        self.cli = SimulatorCli(
            outputStream=self.output,
            failureInjector=self.injector,
        )

    def tearDown(self):
        """Clean up after tests."""
        self.cli.stop()
        self.injector.reset()

    def test_injectFailureByType_connectionDrop(self):
        """
        Given: CLI with failure injector
        When: Injecting connection drop failure
        Then: Failure should be active
        """
        # Act
        result = self.cli.injectFailureByType('connectionDrop')

        # Assert
        self.assertTrue(result.success)
        self.assertTrue(self.injector.isConnectionDropped)

    def test_injectFailureByType_sensorFailure(self):
        """
        Given: CLI with failure injector
        When: Injecting sensor failure
        Then: Failure should be active
        """
        # Act
        result = self.cli.injectFailureByType('sensorFailure')

        # Assert
        self.assertTrue(result.success)
        self.assertTrue(self.injector.isFailureActive(FailureType.SENSOR_FAILURE))

    def test_injectFailureByType_alreadyActive(self):
        """
        Given: CLI with active failure
        When: Injecting same failure again
        Then: Should return failure
        """
        # Arrange
        self.cli.injectFailureByType('connectionDrop')

        # Act
        result = self.cli.injectFailureByType('connectionDrop')

        # Assert
        self.assertFalse(result.success)
        self.assertIn("already active", result.message)

    def test_injectFailureByType_unknownType(self):
        """
        Given: CLI with failure injector
        When: Injecting unknown failure type
        Then: Should return failure
        """
        # Act
        result = self.cli.injectFailureByType('unknownType')

        # Assert
        self.assertFalse(result.success)
        self.assertIn("Unknown failure type", result.message)

    def test_clearCommand_clearsAllFailures(self):
        """
        Given: CLI with active failures
        When: Executing clear command
        Then: All failures should be cleared
        """
        # Arrange
        self.injector.injectFailure(FailureType.CONNECTION_DROP)
        self.injector.injectFailure(FailureType.SENSOR_FAILURE)

        # Act
        result = self.cli.executeCommand(COMMAND_CLEAR)

        # Assert
        self.assertTrue(result.success)
        self.assertFalse(self.injector.isConnectionDropped)
        self.assertFalse(self.injector.isFailureActive(FailureType.SENSOR_FAILURE))
        self.assertIn("Cleared 2", result.message)


class TestSimulatorCliWithSimulator(unittest.TestCase):
    """Tests for SimulatorCli with SensorSimulator."""

    def setUp(self):
        """Set up test fixtures."""
        self.output = io.StringIO()
        self.simulator = MagicMock()
        self.simulator.state = VehicleState(
            rpm=2500.0,
            speedKph=60.0,
            coolantTempC=85.0,
            throttlePercent=25.0,
            gear=3,
        )
        self.cli = SimulatorCli(
            outputStream=self.output,
            simulator=self.simulator,
        )

    def tearDown(self):
        """Clean up after tests."""
        self.cli.stop()

    def test_status_showsVehicleState(self):
        """
        Given: CLI with simulator
        When: Executing status command
        Then: Vehicle state should be shown
        """
        # Act
        self.cli.executeCommand(COMMAND_STATUS)

        # Assert
        outputText = self.output.getvalue()
        self.assertIn("RPM: 2500", outputText)
        self.assertIn("Speed: 60.0", outputText)
        self.assertIn("Coolant: 85.0", outputText)
        self.assertIn("Gear: 3", outputText)


class TestSimulatorCliWithScenarioRunner(unittest.TestCase):
    """Tests for SimulatorCli with DriveScenarioRunner."""

    def setUp(self):
        """Set up test fixtures."""
        self.output = io.StringIO()
        self.runner = MagicMock()
        self.runner.scenario.name = "city_driving"
        self.runner.getCurrentPhase.return_value = MagicMock(name="Accelerate")
        self.runner.getCurrentPhase.return_value.name = "Accelerate"
        self.runner.getProgress.return_value = 45.5
        self.cli = SimulatorCli(
            outputStream=self.output,
            scenarioRunner=self.runner,
        )

    def tearDown(self):
        """Clean up after tests."""
        self.cli.stop()

    def test_status_showsScenarioInfo(self):
        """
        Given: CLI with scenario runner
        When: Executing status command
        Then: Scenario info should be shown
        """
        # Act
        self.cli.executeCommand(COMMAND_STATUS)

        # Assert
        outputText = self.output.getvalue()
        self.assertIn("Scenario: city_driving", outputText)
        self.assertIn("Phase: Accelerate", outputText)
        self.assertIn("Progress: 45.5%", outputText)

    def test_pause_pausesScenarioRunner(self):
        """
        Given: CLI with scenario runner
        When: Executing pause command
        Then: Scenario runner should be paused
        """
        # Act
        self.cli.executeCommand(COMMAND_PAUSE)

        # Assert
        self.runner.pause.assert_called_once()

    def test_resume_resumesScenarioRunner(self):
        """
        Given: Paused CLI with scenario runner
        When: Executing pause command again
        Then: Scenario runner should be resumed
        """
        # Arrange
        self.cli.executeCommand(COMMAND_PAUSE)  # Pause

        # Act
        self.cli.executeCommand(COMMAND_PAUSE)  # Resume

        # Assert
        self.runner.resume.assert_called_once()


class TestSimulatorCliCallbacks(unittest.TestCase):
    """Tests for SimulatorCli callbacks."""

    def setUp(self):
        """Set up test fixtures."""
        self.output = io.StringIO()
        self.cli = SimulatorCli(outputStream=self.output)
        self.commandCallback = Mock()
        self.quitCallback = Mock()
        self.pauseCallback = Mock()

    def tearDown(self):
        """Clean up after tests."""
        self.cli.stop()

    def test_onCommandCallback_called(self):
        """
        Given: CLI with command callback
        When: Executing command
        Then: Callback should be called
        """
        # Arrange
        self.cli.setOnCommandCallback(self.commandCallback)

        # Act
        self.cli.executeCommand(COMMAND_STATUS)

        # Assert
        self.commandCallback.assert_called_once()
        args = self.commandCallback.call_args[0]
        self.assertEqual(args[0], CommandType.STATUS)
        self.assertIsInstance(args[1], CommandResult)

    def test_onQuitCallback_calledOnQuit(self):
        """
        Given: CLI with quit callback
        When: Executing quit command
        Then: Quit callback should be called
        """
        # Arrange
        self.cli.setOnQuitCallback(self.quitCallback)

        # Act
        self.cli.executeCommand(COMMAND_QUIT)

        # Assert
        self.quitCallback.assert_called_once()

    def test_onPauseCallback_calledOnPause(self):
        """
        Given: CLI with pause callback
        When: Executing pause command
        Then: Pause callback should be called with True
        """
        # Arrange
        self.cli.setOnPauseCallback(self.pauseCallback)

        # Act
        self.cli.executeCommand(COMMAND_PAUSE)

        # Assert
        self.pauseCallback.assert_called_once_with(True)

    def test_onPauseCallback_calledOnResume(self):
        """
        Given: Paused CLI with pause callback
        When: Executing pause command again (resume)
        Then: Pause callback should be called with False
        """
        # Arrange
        self.cli.setOnPauseCallback(self.pauseCallback)
        self.cli.executeCommand(COMMAND_PAUSE)  # Pause
        self.pauseCallback.reset_mock()

        # Act
        self.cli.executeCommand(COMMAND_PAUSE)  # Resume

        # Assert
        self.pauseCallback.assert_called_once_with(False)

    def test_callback_exception_doesNotCrash(self):
        """
        Given: CLI with failing callback
        When: Executing command
        Then: Should not raise exception
        """
        # Arrange
        self.cli.setOnCommandCallback(Mock(side_effect=ValueError("Test error")))

        # Act & Assert - should not raise
        result = self.cli.executeCommand(COMMAND_STATUS)
        self.assertTrue(result.success)


class TestSimulatorCliStatistics(unittest.TestCase):
    """Tests for SimulatorCli statistics tracking."""

    def test_getCommandCount_tracksCommands(self):
        """
        Given: CLI
        When: Executing multiple commands
        Then: Command count should be tracked
        """
        # Arrange
        output = io.StringIO()
        cli = SimulatorCli(outputStream=output)

        # Act
        cli.executeCommand(COMMAND_STATUS)
        cli.executeCommand(COMMAND_HELP)
        cli.executeCommand(COMMAND_STATUS)

        # Assert
        self.assertEqual(cli.getCommandCount(), 3)

    def test_getUptime_tracksUptime(self):
        """
        Given: Running CLI
        When: Getting uptime after some time
        Then: Should return positive duration
        """
        # Arrange
        output = io.StringIO()
        cli = SimulatorCli(outputStream=output)
        cli.start()

        # Act
        time.sleep(0.1)
        uptime = cli.getUptime()

        # Assert
        self.assertGreater(uptime, 0.0)

        # Cleanup
        cli.stop()

    def test_getUptime_notStarted_returnsZero(self):
        """
        Given: CLI that hasn't started
        When: Getting uptime
        Then: Should return 0
        """
        # Arrange
        cli = SimulatorCli()

        # Act
        uptime = cli.getUptime()

        # Assert
        self.assertEqual(uptime, 0.0)


class TestSimulatorCliHelperFunctions(unittest.TestCase):
    """Tests for helper functions."""

    def test_createSimulatorCli_basic(self):
        """
        Given: No parameters
        When: Creating CLI via helper
        Then: Should create valid CLI
        """
        # Act
        cli = createSimulatorCli()

        # Assert
        self.assertIsInstance(cli, SimulatorCli)
        self.assertIsNone(cli.simulator)

    def test_createSimulatorCli_withComponents(self):
        """
        Given: Simulator components
        When: Creating CLI via helper
        Then: Components should be stored
        """
        # Arrange
        simulator = MagicMock()
        injector = FailureInjector()

        # Act
        cli = createSimulatorCli(
            simulator=simulator,
            failureInjector=injector,
        )

        # Assert
        self.assertEqual(cli.simulator, simulator)
        self.assertEqual(cli.failureInjector, injector)

    def test_createSimulatorCliFromConfig(self):
        """
        Given: Configuration dictionary
        When: Creating CLI from config
        Then: Should create valid CLI
        """
        # Arrange
        config = {"simulator": {"enabled": True}}
        simulator = MagicMock()

        # Act
        cli = createSimulatorCliFromConfig(config, simulator=simulator)

        # Assert
        self.assertIsInstance(cli, SimulatorCli)
        self.assertEqual(cli.simulator, simulator)


class TestValidCommands(unittest.TestCase):
    """Tests for VALID_COMMANDS constant."""

    def test_validCommands_containsAllCommands(self):
        """
        Given: VALID_COMMANDS set
        When: Checking contents
        Then: All expected commands should be present
        """
        # Assert
        self.assertIn(COMMAND_PAUSE, VALID_COMMANDS)
        self.assertIn(COMMAND_FAILURE, VALID_COMMANDS)
        self.assertIn(COMMAND_CLEAR, VALID_COMMANDS)
        self.assertIn(COMMAND_STATUS, VALID_COMMANDS)
        self.assertIn(COMMAND_QUIT, VALID_COMMANDS)
        self.assertIn(COMMAND_HELP, VALID_COMMANDS)

    def test_commandConstants_haveSingleCharValues(self):
        """
        Given: Command constants
        When: Checking values
        Then: All should be single characters
        """
        # Assert
        self.assertEqual(len(COMMAND_PAUSE), 1)
        self.assertEqual(len(COMMAND_FAILURE), 1)
        self.assertEqual(len(COMMAND_CLEAR), 1)
        self.assertEqual(len(COMMAND_STATUS), 1)
        self.assertEqual(len(COMMAND_QUIT), 1)
        self.assertEqual(len(COMMAND_HELP), 1)


class TestSimulatorCliIntegration(unittest.TestCase):
    """Integration tests for SimulatorCli."""

    def test_fullWorkflow_pauseInjectClearQuit(self):
        """
        Given: CLI with failure injector
        When: Executing full workflow
        Then: All operations should succeed
        """
        # Arrange
        output = io.StringIO()
        injector = FailureInjector()
        cli = SimulatorCli(
            outputStream=output,
            failureInjector=injector,
        )
        cli.start()

        # Act - Pause
        result1 = cli.executeCommand(COMMAND_PAUSE)
        self.assertTrue(result1.success)
        self.assertTrue(cli.isPaused())

        # Act - Inject failure
        result2 = cli.injectFailureByType('connectionDrop')
        self.assertTrue(result2.success)
        self.assertTrue(injector.isConnectionDropped)

        # Act - Show status
        result3 = cli.executeCommand(COMMAND_STATUS)
        self.assertTrue(result3.success)

        # Act - Clear failures
        result4 = cli.executeCommand(COMMAND_CLEAR)
        self.assertTrue(result4.success)
        self.assertFalse(injector.isConnectionDropped)

        # Act - Quit
        result5 = cli.executeCommand(COMMAND_QUIT)
        self.assertTrue(result5.success)
        self.assertTrue(cli.shouldQuit())

        # Cleanup
        cli.stop()


if __name__ == '__main__':
    unittest.main(verbosity=2)
