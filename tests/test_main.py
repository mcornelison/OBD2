################################################################################
# File Name: test_main.py
# Purpose/Description: Tests for main.py orchestrator integration (US-OSC-014)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-014
# ================================================================================
################################################################################

"""
Tests for main.py orchestrator integration.

Verifies that main.py:
- AC1: runWorkflow() creates ApplicationOrchestrator instance
- AC2: Orchestrator receives parsed config and simulate flag
- AC3: orchestrator.start() called to begin operation
- AC4: Main thread waits for shutdown signal (via runLoop)
- AC5: orchestrator.stop() called on shutdown
- AC6: Exit code reflects orchestrator status
- AC7: All existing CLI flags continue to work
- AC8: --dry-run validates config without starting orchestrator
- AC9: Typecheck/lint passes

Usage:
    pytest tests/test_main.py -v
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure src is importable
srcPath = Path(__file__).resolve().parent.parent / 'src'
if str(srcPath) not in sys.path:
    sys.path.insert(0, str(srcPath))

from main import (
    EXIT_CONFIG_ERROR,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_UNKNOWN_ERROR,
    main,
    parseArgs,
    runWorkflow,
)

# ================================================================================
# Test Configuration
# ================================================================================


def getTestConfig() -> dict[str, Any]:
    """
    Create minimal test configuration for main.py tests.

    Returns:
        Configuration dictionary matching expected schema.
    """
    return {
        'application': {
            'name': 'Main Test',
            'version': '1.0.0',
            'environment': 'test'
        },
        'database': {
            'path': ':memory:',
            'walMode': True,
            'vacuumOnStartup': False,
            'backupOnShutdown': False
        },
        'bluetooth': {
            'macAddress': 'SIMULATED',
            'retryDelays': [0.1],
            'maxRetries': 1,
            'connectionTimeoutSeconds': 5
        },
        'vinDecoder': {
            'enabled': False,
            'apiBaseUrl': 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues',
            'apiTimeoutSeconds': 5,
            'cacheVinData': False
        },
        'display': {
            'mode': 'headless',
            'width': 240,
            'height': 240,
            'refreshRateMs': 1000,
            'brightness': 100,
            'showOnStartup': False
        },
        'realtimeData': {
            'pollingIntervalMs': 100,
            'parameters': []
        },
        'profiles': {
            'activeProfile': 'test',
            'availableProfiles': [{
                'id': 'test',
                'name': 'Test',
                'description': 'Test profile',
                'pollingIntervalMs': 100
            }]
        },
        'alerts': {
            'enabled': False,
            'cooldownSeconds': 1,
            'visualAlerts': False,
            'audioAlerts': False,
            'logAlerts': False
        },
        'simulator': {
            'enabled': True,
            'connectionDelaySeconds': 0,
            'updateIntervalMs': 50
        },
        'logging': {
            'level': 'DEBUG',
            'maskPII': False
        }
    }


def createMockOrchestrator(exitCode: int = 0) -> MagicMock:
    """
    Create a mock orchestrator with standard method stubs.

    Args:
        exitCode: Exit code returned by stop()

    Returns:
        MagicMock configured as ApplicationOrchestrator
    """
    mock = MagicMock()
    mock.stop.return_value = exitCode
    mock.isRunning.return_value = True
    return mock


# ================================================================================
# AC1: runWorkflow() creates ApplicationOrchestrator instance
# ================================================================================


class TestRunWorkflowCreatesOrchestrator:
    """Tests that runWorkflow creates an ApplicationOrchestrator via factory."""

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_callsFactory(
        self, mockFactory: MagicMock
    ):
        """
        Given: Valid config
        When: runWorkflow is called
        Then: createOrchestratorFromConfig is called to create orchestrator
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockFactory.assert_called_once()

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_usesFactoryResult(
        self, mockFactory: MagicMock
    ):
        """
        Given: Factory returns an orchestrator
        When: runWorkflow is called
        Then: The factory result's methods are called (start, runLoop, stop)
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockOrch.start.assert_called_once()
        mockOrch.runLoop.assert_called_once()
        mockOrch.stop.assert_called_once()


# ================================================================================
# AC2: Orchestrator receives parsed config and simulate flag
# ================================================================================


class TestOrchestratorReceivesConfig:
    """Tests that config and simulate flag are passed to orchestrator factory."""

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_passesConfig(
        self, mockFactory: MagicMock
    ):
        """
        Given: A specific config dict
        When: runWorkflow is called with that config
        Then: createOrchestratorFromConfig receives the same config
        """
        # Arrange
        config = getTestConfig()
        mockFactory.return_value = createMockOrchestrator()

        # Act
        runWorkflow(config, simulate=False)

        # Assert
        passedConfig = mockFactory.call_args[1].get(
            'config', mockFactory.call_args[0][0]
        )
        assert passedConfig is config

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_passesSimulateTrue(
        self, mockFactory: MagicMock
    ):
        """
        Given: simulate=True
        When: runWorkflow is called
        Then: createOrchestratorFromConfig receives simulate=True
        """
        # Arrange
        config = getTestConfig()
        mockFactory.return_value = createMockOrchestrator()

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockFactory.assert_called_once_with(config, simulate=True)

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_passesSimulateFalse(
        self, mockFactory: MagicMock
    ):
        """
        Given: simulate=False
        When: runWorkflow is called
        Then: createOrchestratorFromConfig receives simulate=False
        """
        # Arrange
        config = getTestConfig()
        mockFactory.return_value = createMockOrchestrator()

        # Act
        runWorkflow(config, simulate=False)

        # Assert
        mockFactory.assert_called_once_with(config, simulate=False)


# ================================================================================
# AC3: orchestrator.start() called to begin operation
# ================================================================================


class TestOrchestratorStartCalled:
    """Tests that orchestrator.start() is called during workflow."""

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_callsStart(
        self, mockFactory: MagicMock
    ):
        """
        Given: Valid config
        When: runWorkflow is called
        Then: orchestrator.start() is called
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockOrch.start.assert_called_once()

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_startCalledBeforeRunLoop(
        self, mockFactory: MagicMock
    ):
        """
        Given: Valid config
        When: runWorkflow is called
        Then: start() is called before runLoop()
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch
        callOrder: list[str] = []
        mockOrch.start.side_effect = lambda: callOrder.append('start')
        mockOrch.runLoop.side_effect = lambda: callOrder.append('runLoop')

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        startIdx = callOrder.index('start')
        runLoopIdx = callOrder.index('runLoop')
        assert startIdx < runLoopIdx, "start() must be called before runLoop()"


# ================================================================================
# AC4: Main thread waits for shutdown signal
# ================================================================================


class TestMainThreadWaitsForShutdown:
    """Tests that the main thread blocks in runLoop() waiting for shutdown."""

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_callsRunLoop(
        self, mockFactory: MagicMock
    ):
        """
        Given: Valid config
        When: runWorkflow is called
        Then: orchestrator.runLoop() is called (blocks for shutdown)
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockOrch.runLoop.assert_called_once()

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_runLoopCalledBetweenStartAndStop(
        self, mockFactory: MagicMock
    ):
        """
        Given: Valid config
        When: runWorkflow is called
        Then: Call order is: registerSignalHandlers -> start -> runLoop -> stop
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch
        callOrder: list[str] = []
        mockOrch.registerSignalHandlers.side_effect = (
            lambda: callOrder.append('registerSignalHandlers')
        )
        mockOrch.start.side_effect = lambda: callOrder.append('start')
        mockOrch.runLoop.side_effect = lambda: callOrder.append('runLoop')
        mockOrch.stop.side_effect = lambda: (
            callOrder.append('stop') or 0  # type: ignore[func-returns-value]
        )

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        assert callOrder == [
            'registerSignalHandlers', 'start', 'runLoop', 'stop'
        ]


# ================================================================================
# AC5: orchestrator.stop() called on shutdown
# ================================================================================


class TestOrchestratorStopCalled:
    """Tests that orchestrator.stop() is called on shutdown."""

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_callsStop(
        self, mockFactory: MagicMock
    ):
        """
        Given: Normal workflow
        When: runLoop completes
        Then: orchestrator.stop() is called
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockOrch.stop.assert_called_once()

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_callsStopOnKeyboardInterrupt(
        self, mockFactory: MagicMock
    ):
        """
        Given: Orchestrator raises KeyboardInterrupt during start
        When: runWorkflow handles the exception
        Then: orchestrator.stop() is still called
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockOrch.start.side_effect = KeyboardInterrupt()
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockOrch.stop.assert_called_once()

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_callsStopOnException(
        self, mockFactory: MagicMock
    ):
        """
        Given: Orchestrator raises an exception during runLoop
        When: runWorkflow handles the exception
        Then: orchestrator.stop() is still called
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockOrch.runLoop.side_effect = RuntimeError("test error")
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockOrch.stop.assert_called_once()

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_restoresSignalHandlersInFinally(
        self, mockFactory: MagicMock
    ):
        """
        Given: Normal or exceptional workflow
        When: runWorkflow completes
        Then: restoreSignalHandlers() is always called (in finally)
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockOrch.restoreSignalHandlers.assert_called_once()

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_restoresSignalHandlersOnException(
        self, mockFactory: MagicMock
    ):
        """
        Given: Orchestrator raises exception
        When: runWorkflow handles it
        Then: restoreSignalHandlers() still called
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockOrch.start.side_effect = RuntimeError("boom")
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        mockOrch.restoreSignalHandlers.assert_called_once()


# ================================================================================
# AC6: Exit code reflects orchestrator status
# ================================================================================


class TestExitCodeReflectsStatus:
    """Tests that exit codes from orchestrator.stop() are propagated."""

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_returnsCleanExitCode(
        self, mockFactory: MagicMock
    ):
        """
        Given: Orchestrator stops cleanly (exit code 0)
        When: runWorkflow completes
        Then: Returns 0
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator(exitCode=0)
        mockFactory.return_value = mockOrch

        # Act
        result = runWorkflow(config, simulate=True)

        # Assert
        assert result == EXIT_SUCCESS

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_returnsForcedExitCode(
        self, mockFactory: MagicMock
    ):
        """
        Given: Orchestrator stops with forced exit (exit code 1)
        When: runWorkflow completes
        Then: Returns 1
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator(exitCode=1)
        mockFactory.return_value = mockOrch

        # Act
        result = runWorkflow(config, simulate=True)

        # Assert
        assert result == 1

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_returnsErrorExitCodeOnException(
        self, mockFactory: MagicMock
    ):
        """
        Given: Orchestrator raises exception, stop returns 0
        When: runWorkflow catches the exception
        Then: Returns EXIT_RUNTIME_ERROR (overrides clean 0)
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator(exitCode=0)
        mockOrch.runLoop.side_effect = RuntimeError("unexpected")
        mockFactory.return_value = mockOrch

        # Act
        result = runWorkflow(config, simulate=True)

        # Assert
        assert result == EXIT_RUNTIME_ERROR

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_preservesNonZeroExitCodeOnException(
        self, mockFactory: MagicMock
    ):
        """
        Given: Orchestrator raises exception, stop returns non-zero
        When: runWorkflow catches the exception
        Then: Returns the orchestrator's non-zero exit code
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator(exitCode=1)
        mockOrch.runLoop.side_effect = RuntimeError("unexpected")
        mockFactory.return_value = mockOrch

        # Act
        result = runWorkflow(config, simulate=True)

        # Assert
        assert result == 1


# ================================================================================
# AC7: All existing CLI flags continue to work
# ================================================================================


class TestCliFlags:
    """Tests that all existing CLI flags are parsed correctly."""

    def test_parseArgs_defaultConfig(self):
        """
        Given: No arguments
        When: parseArgs called
        Then: Default config path is set
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py']):
            args = parseArgs()

        # Assert
        assert args.config.endswith('obd_config.json')

    def test_parseArgs_customConfig(self):
        """
        Given: --config flag with custom path
        When: parseArgs called
        Then: Custom config path is set
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py', '--config', '/tmp/my.json']):
            args = parseArgs()

        # Assert
        assert args.config == '/tmp/my.json'

    def test_parseArgs_configShortFlag(self):
        """
        Given: -c flag (short form)
        When: parseArgs called
        Then: Config path is set
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py', '-c', '/tmp/c.json']):
            args = parseArgs()

        # Assert
        assert args.config == '/tmp/c.json'

    def test_parseArgs_envFile(self):
        """
        Given: --env-file flag
        When: parseArgs called
        Then: env_file is set
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py', '--env-file', '/tmp/.env']):
            args = parseArgs()

        # Assert
        assert args.env_file == '/tmp/.env'

    def test_parseArgs_envFileShortFlag(self):
        """
        Given: -e flag (short form)
        When: parseArgs called
        Then: env_file is set
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py', '-e', '/tmp/.env']):
            args = parseArgs()

        # Assert
        assert args.env_file == '/tmp/.env'

    def test_parseArgs_dryRun(self):
        """
        Given: --dry-run flag
        When: parseArgs called
        Then: dry_run is True
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py', '--dry-run']):
            args = parseArgs()

        # Assert
        assert args.dry_run is True

    def test_parseArgs_noDryRunDefault(self):
        """
        Given: No --dry-run flag
        When: parseArgs called
        Then: dry_run is False
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py']):
            args = parseArgs()

        # Assert
        assert args.dry_run is False

    def test_parseArgs_verbose(self):
        """
        Given: --verbose flag
        When: parseArgs called
        Then: verbose is True
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py', '--verbose']):
            args = parseArgs()

        # Assert
        assert args.verbose is True

    def test_parseArgs_verboseShortFlag(self):
        """
        Given: -v flag (short form)
        When: parseArgs called
        Then: verbose is True
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py', '-v']):
            args = parseArgs()

        # Assert
        assert args.verbose is True

    def test_parseArgs_simulate(self):
        """
        Given: --simulate flag
        When: parseArgs called
        Then: simulate is True
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py', '--simulate']):
            args = parseArgs()

        # Assert
        assert args.simulate is True

    def test_parseArgs_simulateShortFlag(self):
        """
        Given: -s flag (short form)
        When: parseArgs called
        Then: simulate is True
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py', '-s']):
            args = parseArgs()

        # Assert
        assert args.simulate is True

    def test_parseArgs_noSimulateDefault(self):
        """
        Given: No --simulate flag
        When: parseArgs called
        Then: simulate is False
        """
        # Arrange & Act
        with patch('sys.argv', ['main.py']):
            args = parseArgs()

        # Assert
        assert args.simulate is False

    def test_parseArgs_version(self):
        """
        Given: --version flag
        When: parseArgs called
        Then: Version is printed and SystemExit raised
        """
        # Arrange & Act & Assert
        with patch('sys.argv', ['main.py', '--version']):
            with pytest.raises(SystemExit) as exc:
                parseArgs()
            assert exc.value.code == 0

    def test_parseArgs_allFlagsCombined(self):
        """
        Given: All flags together
        When: parseArgs called
        Then: All flags are set correctly
        """
        # Arrange & Act
        with patch('sys.argv', [
            'main.py', '-c', '/tmp/c.json', '-e', '/tmp/.env',
            '--dry-run', '-v', '-s'
        ]):
            args = parseArgs()

        # Assert
        assert args.config == '/tmp/c.json'
        assert args.env_file == '/tmp/.env'
        assert args.dry_run is True
        assert args.verbose is True
        assert args.simulate is True


# ================================================================================
# AC8: --dry-run validates config without starting orchestrator
# ================================================================================


class TestDryRunMode:
    """Tests that --dry-run validates config but doesn't start orchestrator."""

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_dryRunSkipsOrchestrator(
        self, mockFactory: MagicMock
    ):
        """
        Given: dryRun=True
        When: runWorkflow is called
        Then: createOrchestratorFromConfig is never called
        """
        # Arrange
        config = getTestConfig()

        # Act
        result = runWorkflow(config, dryRun=True)

        # Assert
        mockFactory.assert_not_called()
        assert result == EXIT_SUCCESS

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_dryRunReturnsSuccess(
        self, mockFactory: MagicMock
    ):
        """
        Given: dryRun=True with valid config
        When: runWorkflow is called
        Then: Returns EXIT_SUCCESS (0)
        """
        # Arrange
        config = getTestConfig()

        # Act
        result = runWorkflow(config, dryRun=True)

        # Assert
        assert result == EXIT_SUCCESS

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_dryRunDoesNotStart(
        self, mockFactory: MagicMock
    ):
        """
        Given: dryRun=True
        When: runWorkflow is called
        Then: No start/stop/runLoop calls occur
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch

        # Act
        runWorkflow(config, dryRun=True)

        # Assert
        mockOrch.start.assert_not_called()
        mockOrch.runLoop.assert_not_called()
        mockOrch.stop.assert_not_called()


# ================================================================================
# Signal Handler Registration (AC4 from US-OSC-004, verified here for main.py)
# ================================================================================


class TestSignalHandlerRegistration:
    """Tests that signal handlers are registered before start in runWorkflow."""

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_registersSignalHandlersBeforeStart(
        self, mockFactory: MagicMock
    ):
        """
        Given: Valid config
        When: runWorkflow is called
        Then: registerSignalHandlers() called before start()
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch
        callOrder: list[str] = []
        mockOrch.registerSignalHandlers.side_effect = (
            lambda: callOrder.append('register')
        )
        mockOrch.start.side_effect = lambda: callOrder.append('start')

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        assert callOrder.index('register') < callOrder.index('start')

    @patch('pi.obd.orchestrator.createOrchestratorFromConfig')
    def test_runWorkflow_restoresSignalHandlersAfterStop(
        self, mockFactory: MagicMock
    ):
        """
        Given: Valid config
        When: runWorkflow completes
        Then: restoreSignalHandlers() called after stop()
        """
        # Arrange
        config = getTestConfig()
        mockOrch = createMockOrchestrator()
        mockFactory.return_value = mockOrch
        callOrder: list[str] = []
        mockOrch.stop.side_effect = lambda: (
            callOrder.append('stop') or 0  # type: ignore[func-returns-value]
        )
        mockOrch.restoreSignalHandlers.side_effect = (
            lambda: callOrder.append('restore')
        )

        # Act
        runWorkflow(config, simulate=True)

        # Assert
        assert callOrder.index('stop') < callOrder.index('restore')


# ================================================================================
# main() Integration Tests
# ================================================================================


class TestMainFunction:
    """Tests for the main() entry point function."""

    @patch('main.runWorkflow')
    @patch('main.loadConfiguration')
    @patch('main.setupLogging')
    def test_main_loadsConfigAndCallsRunWorkflow(
        self,
        mockSetupLogging: MagicMock,
        mockLoadConfig: MagicMock,
        mockRunWorkflow: MagicMock,
    ):
        """
        Given: Valid args
        When: main() is called
        Then: loadConfiguration and runWorkflow are called
        """
        # Arrange
        mockLoadConfig.return_value = getTestConfig()
        mockRunWorkflow.return_value = EXIT_SUCCESS
        with patch('sys.argv', ['main.py', '--simulate']):
            # Act
            result = main()

        # Assert
        mockLoadConfig.assert_called_once()
        mockRunWorkflow.assert_called_once()
        assert result == EXIT_SUCCESS

    @patch('main.runWorkflow')
    @patch('main.loadConfiguration')
    @patch('main.setupLogging')
    def test_main_passesSimulateFlagToRunWorkflow(
        self,
        mockSetupLogging: MagicMock,
        mockLoadConfig: MagicMock,
        mockRunWorkflow: MagicMock,
    ):
        """
        Given: --simulate flag
        When: main() is called
        Then: runWorkflow receives simulate=True
        """
        # Arrange
        config = getTestConfig()
        mockLoadConfig.return_value = config
        mockRunWorkflow.return_value = EXIT_SUCCESS
        with patch('sys.argv', ['main.py', '--simulate']):
            # Act
            main()

        # Assert
        _, kwargs = mockRunWorkflow.call_args
        assert kwargs.get('simulate') is True or (
            mockRunWorkflow.call_args[0][2] if len(
                mockRunWorkflow.call_args[0]
            ) > 2 else kwargs.get('simulate')
        )

    @patch('main.runWorkflow')
    @patch('main.loadConfiguration')
    @patch('main.setupLogging')
    def test_main_passesDryRunFlagToRunWorkflow(
        self,
        mockSetupLogging: MagicMock,
        mockLoadConfig: MagicMock,
        mockRunWorkflow: MagicMock,
    ):
        """
        Given: --dry-run flag
        When: main() is called
        Then: runWorkflow receives dryRun=True
        """
        # Arrange
        mockLoadConfig.return_value = getTestConfig()
        mockRunWorkflow.return_value = EXIT_SUCCESS
        with patch('sys.argv', ['main.py', '--dry-run']):
            # Act
            main()

        # Assert
        _, kwargs = mockRunWorkflow.call_args
        assert kwargs.get('dryRun') is True or (
            mockRunWorkflow.call_args[0][1] if len(
                mockRunWorkflow.call_args[0]
            ) > 1 else kwargs.get('dryRun')
        )

    @patch('main.loadConfiguration')
    @patch('main.setupLogging')
    def test_main_returnsConfigErrorOnConfigurationError(
        self,
        mockSetupLogging: MagicMock,
        mockLoadConfig: MagicMock,
    ):
        """
        Given: Configuration loading raises ConfigurationError
        When: main() is called
        Then: Returns EXIT_CONFIG_ERROR
        """
        # Arrange
        from common.errors.handler import ConfigurationError
        mockLoadConfig.side_effect = ConfigurationError("bad config")
        with patch('sys.argv', ['main.py']):
            # Act
            result = main()

        # Assert
        assert result == EXIT_CONFIG_ERROR

    @patch('main.loadConfiguration')
    @patch('main.setupLogging')
    def test_main_returnsUnknownErrorOnUnexpectedException(
        self,
        mockSetupLogging: MagicMock,
        mockLoadConfig: MagicMock,
    ):
        """
        Given: An unexpected exception occurs
        When: main() is called
        Then: Returns EXIT_UNKNOWN_ERROR
        """
        # Arrange
        mockLoadConfig.side_effect = ValueError("surprise")
        with patch('sys.argv', ['main.py']):
            # Act
            result = main()

        # Assert
        assert result == EXIT_UNKNOWN_ERROR

    @patch('main.loadConfiguration')
    @patch('main.setupLogging')
    def test_main_returnsRuntimeErrorOnKeyboardInterrupt(
        self,
        mockSetupLogging: MagicMock,
        mockLoadConfig: MagicMock,
    ):
        """
        Given: KeyboardInterrupt during config loading
        When: main() is called
        Then: Returns EXIT_RUNTIME_ERROR
        """
        # Arrange
        mockLoadConfig.side_effect = KeyboardInterrupt()
        with patch('sys.argv', ['main.py']):
            # Act
            result = main()

        # Assert
        assert result == EXIT_RUNTIME_ERROR

    @patch('main.runWorkflow')
    @patch('main.loadConfiguration')
    @patch('main.setupLogging')
    def test_main_setsDebugLogLevelForVerbose(
        self,
        mockSetupLogging: MagicMock,
        mockLoadConfig: MagicMock,
        mockRunWorkflow: MagicMock,
    ):
        """
        Given: --verbose flag
        When: main() is called
        Then: Logging is set up with DEBUG level
        """
        # Arrange
        mockLoadConfig.return_value = getTestConfig()
        mockRunWorkflow.return_value = EXIT_SUCCESS
        with patch('sys.argv', ['main.py', '--verbose']):
            # Act
            main()

        # Assert
        mockSetupLogging.assert_called_once_with(level='DEBUG')

    @patch('main.runWorkflow')
    @patch('main.loadConfiguration')
    @patch('main.setupLogging')
    def test_main_setsInfoLogLevelByDefault(
        self,
        mockSetupLogging: MagicMock,
        mockLoadConfig: MagicMock,
        mockRunWorkflow: MagicMock,
    ):
        """
        Given: No --verbose flag
        When: main() is called
        Then: Logging is set up with INFO level
        """
        # Arrange
        mockLoadConfig.return_value = getTestConfig()
        mockRunWorkflow.return_value = EXIT_SUCCESS
        with patch('sys.argv', ['main.py']):
            # Act
            main()

        # Assert
        mockSetupLogging.assert_called_once_with(level='INFO')

    @patch('main.runWorkflow')
    @patch('main.loadConfiguration')
    @patch('main.setupLogging')
    def test_main_propagatesExitCodeFromRunWorkflow(
        self,
        mockSetupLogging: MagicMock,
        mockLoadConfig: MagicMock,
        mockRunWorkflow: MagicMock,
    ):
        """
        Given: runWorkflow returns non-zero exit code
        When: main() is called
        Then: main() returns same exit code
        """
        # Arrange
        mockLoadConfig.return_value = getTestConfig()
        mockRunWorkflow.return_value = 2
        with patch('sys.argv', ['main.py', '--simulate']):
            # Act
            result = main()

        # Assert
        assert result == 2
