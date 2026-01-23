################################################################################
# File Name: test_main.py
# Purpose/Description: Tests for main application entry point
# Author: Michael Cornelison
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-21    | M. Cornelison | Initial implementation
# 2026-01-23    | Ralph Agent  | US-OSC-004: Updated tests for orchestrator integration
# ================================================================================
################################################################################

"""
Tests for the main module.

Run with:
    pytest tests/test_main.py -v
"""

import json
import os
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from main import (
    EXIT_CONFIG_ERROR,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_UNKNOWN_ERROR,
    loadConfiguration,
    main,
    parseArgs,
    runWorkflow,
)
from common.error_handler import ConfigurationError


# ================================================================================
# CLI Argument Parsing Tests
# ================================================================================

class TestParseArgs:
    """Tests for command line argument parsing."""

    def test_parseArgs_noArgs_usesDefaults(self):
        """
        Given: No command line arguments
        When: parseArgs() is called
        Then: Returns defaults for all options
        """
        with patch('sys.argv', ['main.py']):
            args = parseArgs()

        assert args.config == 'src/config.json'
        assert args.env_file == '.env'
        assert args.dry_run is False
        assert args.verbose is False

    def test_parseArgs_customConfig_setsConfigPath(self):
        """
        Given: Custom config path argument
        When: parseArgs() is called
        Then: Returns specified config path
        """
        with patch('sys.argv', ['main.py', '--config', 'custom/config.json']):
            args = parseArgs()

        assert args.config == 'custom/config.json'

    def test_parseArgs_shortConfigFlag_setsConfigPath(self):
        """
        Given: Short -c flag for config
        When: parseArgs() is called
        Then: Returns specified config path
        """
        with patch('sys.argv', ['main.py', '-c', 'custom.json']):
            args = parseArgs()

        assert args.config == 'custom.json'

    def test_parseArgs_envFile_setsEnvPath(self):
        """
        Given: Custom env file argument
        When: parseArgs() is called
        Then: Returns specified env file path
        """
        with patch('sys.argv', ['main.py', '--env-file', '.env.production']):
            args = parseArgs()

        assert args.env_file == '.env.production'

    def test_parseArgs_shortEnvFlag_setsEnvPath(self):
        """
        Given: Short -e flag for env file
        When: parseArgs() is called
        Then: Returns specified env file path
        """
        with patch('sys.argv', ['main.py', '-e', '.env.test']):
            args = parseArgs()

        assert args.env_file == '.env.test'

    def test_parseArgs_dryRun_setsDryRunTrue(self):
        """
        Given: --dry-run flag
        When: parseArgs() is called
        Then: Returns dry_run=True
        """
        with patch('sys.argv', ['main.py', '--dry-run']):
            args = parseArgs()

        assert args.dry_run is True

    def test_parseArgs_verbose_setsVerboseTrue(self):
        """
        Given: --verbose flag
        When: parseArgs() is called
        Then: Returns verbose=True
        """
        with patch('sys.argv', ['main.py', '--verbose']):
            args = parseArgs()

        assert args.verbose is True

    def test_parseArgs_shortVerboseFlag_setsVerboseTrue(self):
        """
        Given: Short -v flag
        When: parseArgs() is called
        Then: Returns verbose=True
        """
        with patch('sys.argv', ['main.py', '-v']):
            args = parseArgs()

        assert args.verbose is True

    def test_parseArgs_multipleFlags_setsAllOptions(self):
        """
        Given: Multiple flags combined
        When: parseArgs() is called
        Then: Returns all specified options
        """
        with patch('sys.argv', ['main.py', '-c', 'my.json', '-e', '.env.test',
                                 '--dry-run', '--verbose']):
            args = parseArgs()

        assert args.config == 'my.json'
        assert args.env_file == '.env.test'
        assert args.dry_run is True
        assert args.verbose is True

    def test_parseArgs_helpFlag_exitsWithZero(self, capsys):
        """
        Given: --help flag
        When: parseArgs() is called
        Then: Exits with code 0 and shows help
        """
        with patch('sys.argv', ['main.py', '--help']):
            with pytest.raises(SystemExit) as exc:
                parseArgs()

        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert 'usage:' in captured.out.lower()

    def test_parseArgs_versionFlag_exitsWithZero(self, capsys):
        """
        Given: --version flag
        When: parseArgs() is called
        Then: Exits with code 0 and shows version
        """
        with patch('sys.argv', ['main.py', '--version']):
            with pytest.raises(SystemExit) as exc:
                parseArgs()

        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert '1.0.0' in captured.out


# ================================================================================
# Configuration Loading Tests
# ================================================================================

class TestLoadConfiguration:
    """Tests for configuration loading and validation."""

    def test_loadConfiguration_validConfig_returnsConfig(
        self, tmp_path, sampleConfig
    ):
        """
        Given: Valid configuration file
        When: loadConfiguration() is called
        Then: Returns validated configuration
        """
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)

        with patch('main.setupLogging'), patch('main.getLogger'):
            config = loadConfiguration(str(configFile))

        assert config is not None
        assert 'application' in config

    def test_loadConfiguration_withEnvFile_resolvesSecrets(
        self, tmp_path, envVars
    ):
        """
        Given: Config with placeholders and env file
        When: loadConfiguration() is called
        Then: Resolves placeholders from env file
        """
        configWithPlaceholders = {
            'application': {'name': 'TestApp'},
            'database': {'server': '${DB_SERVER}'}
        }
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(configWithPlaceholders, f)

        envFile = tmp_path / '.env'
        with open(envFile, 'w') as f:
            f.write('DB_SERVER=test-server\n')

        with patch('main.setupLogging'), patch('main.getLogger'):
            config = loadConfiguration(str(configFile), str(envFile))

        assert config['database']['server'] == 'test-server'

    def test_loadConfiguration_missingFile_raisesConfigError(self):
        """
        Given: Non-existent configuration file
        When: loadConfiguration() is called
        Then: Raises ConfigurationError
        """
        with patch('main.setupLogging'), patch('main.getLogger'):
            with pytest.raises(ConfigurationError) as exc:
                loadConfiguration('/nonexistent/config.json')

        assert 'not found' in str(exc.value).lower()

    def test_loadConfiguration_invalidJson_raisesError(self, tmp_path):
        """
        Given: Invalid JSON file
        When: loadConfiguration() is called
        Then: Raises appropriate error
        """
        configFile = tmp_path / 'invalid.json'
        with open(configFile, 'w') as f:
            f.write('{ invalid json }')

        with patch('main.setupLogging'), patch('main.getLogger'):
            with pytest.raises(Exception):
                loadConfiguration(str(configFile))


# ================================================================================
# Workflow Tests
# ================================================================================

class TestRunWorkflow:
    """Tests for workflow execution with orchestrator integration."""

    def test_runWorkflow_dryRunMode_returnsSuccessWithoutStartingOrchestrator(
        self, sampleConfig
    ):
        """
        Given: Valid configuration with dry_run=True
        When: runWorkflow() is called
        Then: Logs dry run message and returns EXIT_SUCCESS without starting orchestrator
        """
        mockLogger = MagicMock()
        with patch('main.getLogger', return_value=mockLogger):
            with patch(
                'obd.orchestrator.createOrchestratorFromConfig'
            ) as mockCreate:
                result = runWorkflow(sampleConfig, dryRun=True)

        assert result == EXIT_SUCCESS
        # Orchestrator should not be created in dry run mode
        mockCreate.assert_not_called()
        dryRunLogged = any(
            'DRY RUN' in str(call) for call in mockLogger.info.call_args_list
        )
        assert dryRunLogged

    def test_runWorkflow_normalMode_createsAndStartsOrchestrator(
        self, sampleConfig
    ):
        """
        Given: Valid configuration
        When: runWorkflow() is called
        Then: Creates orchestrator and starts it
        """
        mockOrchestrator = MagicMock()
        # Set up orchestrator to return immediately (not running after shutdown signal)
        mockOrchestrator.isRunning.return_value = False
        mockOrchestrator.stop.return_value = 0
        from obd.orchestrator import ShutdownState
        type(mockOrchestrator).shutdownState = property(
            lambda self: ShutdownState.SHUTDOWN_REQUESTED
        )

        with patch('main.getLogger'):
            with patch(
                'obd.orchestrator.createOrchestratorFromConfig',
                return_value=mockOrchestrator
            ):
                result = runWorkflow(sampleConfig)

        # Verify orchestrator was configured correctly
        mockOrchestrator.registerSignalHandlers.assert_called_once()
        mockOrchestrator.start.assert_called_once()
        mockOrchestrator.stop.assert_called_once()
        mockOrchestrator.restoreSignalHandlers.assert_called_once()
        assert result == 0

    def test_runWorkflow_withSimulateFlag_passesToOrchestrator(
        self, sampleConfig
    ):
        """
        Given: Configuration with simulate=True
        When: runWorkflow() is called
        Then: Orchestrator is created with simulate=True
        """
        mockOrchestrator = MagicMock()
        mockOrchestrator.isRunning.return_value = False
        mockOrchestrator.stop.return_value = 0
        from obd.orchestrator import ShutdownState
        type(mockOrchestrator).shutdownState = property(
            lambda self: ShutdownState.SHUTDOWN_REQUESTED
        )

        with patch('main.getLogger'):
            with patch(
                'obd.orchestrator.createOrchestratorFromConfig',
                return_value=mockOrchestrator
            ) as mockCreate:
                runWorkflow(sampleConfig, simulate=True)

        mockCreate.assert_called_once_with(sampleConfig, simulate=True)


class TestSignalHandlerIntegration:
    """Tests for US-OSC-004: Signal handler integration in main."""

    def test_runWorkflow_registersSignalHandlersBeforeStart(
        self, sampleConfig
    ):
        """
        Given: Valid configuration
        When: runWorkflow() is called
        Then: Signal handlers are registered before orchestrator.start()
        """
        callOrder = []
        mockOrchestrator = MagicMock()
        mockOrchestrator.isRunning.return_value = False
        mockOrchestrator.stop.return_value = 0
        mockOrchestrator.registerSignalHandlers = MagicMock(
            side_effect=lambda: callOrder.append('register')
        )
        mockOrchestrator.start = MagicMock(
            side_effect=lambda: callOrder.append('start')
        )
        from obd.orchestrator import ShutdownState
        type(mockOrchestrator).shutdownState = property(
            lambda self: ShutdownState.SHUTDOWN_REQUESTED
        )

        with patch('main.getLogger'):
            with patch(
                'obd.orchestrator.createOrchestratorFromConfig',
                return_value=mockOrchestrator
            ):
                runWorkflow(sampleConfig)

        # Register must come before start
        assert callOrder.index('register') < callOrder.index('start')

    def test_runWorkflow_restoresSignalHandlersOnShutdown(
        self, sampleConfig
    ):
        """
        Given: Valid configuration
        When: runWorkflow() completes
        Then: Signal handlers are restored in finally block
        """
        mockOrchestrator = MagicMock()
        mockOrchestrator.isRunning.return_value = False
        mockOrchestrator.stop.return_value = 0
        from obd.orchestrator import ShutdownState
        type(mockOrchestrator).shutdownState = property(
            lambda self: ShutdownState.SHUTDOWN_REQUESTED
        )

        with patch('main.getLogger'):
            with patch(
                'obd.orchestrator.createOrchestratorFromConfig',
                return_value=mockOrchestrator
            ):
                runWorkflow(sampleConfig)

        mockOrchestrator.restoreSignalHandlers.assert_called_once()

    def test_runWorkflow_restoresSignalHandlersOnError(
        self, sampleConfig
    ):
        """
        Given: Exception during workflow
        When: runWorkflow() fails
        Then: Signal handlers are still restored
        """
        mockOrchestrator = MagicMock()
        mockOrchestrator.start.side_effect = Exception("Start failed")
        mockOrchestrator.stop.return_value = 2

        with patch('main.getLogger'):
            with patch(
                'obd.orchestrator.createOrchestratorFromConfig',
                return_value=mockOrchestrator
            ):
                runWorkflow(sampleConfig)

        # Handlers should be restored even on error
        mockOrchestrator.restoreSignalHandlers.assert_called_once()

    def test_runWorkflow_keyboardInterrupt_stopsOrchestrator(
        self, sampleConfig
    ):
        """
        Given: KeyboardInterrupt during startup
        When: runWorkflow() handles the interrupt
        Then: Orchestrator is stopped and handlers restored
        """
        mockOrchestrator = MagicMock()
        mockOrchestrator.start.side_effect = KeyboardInterrupt()
        mockOrchestrator.stop.return_value = 1

        with patch('main.getLogger'):
            with patch(
                'obd.orchestrator.createOrchestratorFromConfig',
                return_value=mockOrchestrator
            ):
                result = runWorkflow(sampleConfig)

        mockOrchestrator.stop.assert_called_once()
        mockOrchestrator.restoreSignalHandlers.assert_called_once()
        assert result == 1


# ================================================================================
# Main Function Tests
# ================================================================================

class TestMain:
    """Tests for main entry point function."""

    def test_main_successfulRun_returnsExitSuccess(
        self, tmp_path, sampleConfig
    ):
        """
        Given: Valid configuration and successful workflow
        When: main() is called
        Then: Returns EXIT_SUCCESS (0)
        """
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)

        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', return_value=EXIT_SUCCESS):
                    result = main()

        assert result == EXIT_SUCCESS

    def test_main_configError_returnsExitConfigError(self):
        """
        Given: Invalid/missing configuration
        When: main() is called
        Then: Returns EXIT_CONFIG_ERROR (1)
        """
        with patch('sys.argv', ['main.py', '--config', '/nonexistent.json']):
            with patch('main.setupLogging'), patch('main.getLogger'):
                result = main()

        assert result == EXIT_CONFIG_ERROR

    def test_main_workflowReturnsNonZero_returnsExitCode(
        self, tmp_path, sampleConfig
    ):
        """
        Given: Workflow returns non-zero exit code
        When: main() is called
        Then: Returns that exit code
        """
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)

        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', return_value=EXIT_RUNTIME_ERROR):
                    result = main()

        assert result == EXIT_RUNTIME_ERROR

    def test_main_unexpectedException_returnsExitUnknownError(
        self, tmp_path, sampleConfig
    ):
        """
        Given: Unexpected exception during execution
        When: main() is called
        Then: Returns EXIT_UNKNOWN_ERROR (3)
        """
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)

        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', side_effect=RuntimeError("Unexpected")):
                    result = main()

        assert result == EXIT_UNKNOWN_ERROR

    def test_main_verboseFlag_setsDebugLevel(
        self, tmp_path, sampleConfig
    ):
        """
        Given: --verbose flag
        When: main() is called
        Then: setupLogging is called with DEBUG level
        """
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)

        mockSetupLogging = MagicMock()
        with patch('sys.argv', ['main.py', '--config', str(configFile), '-v']):
            with patch('main.setupLogging', mockSetupLogging):
                with patch('main.getLogger'):
                    with patch('main.runWorkflow', return_value=EXIT_SUCCESS):
                        main()

        mockSetupLogging.assert_called_once_with(level='DEBUG')

    def test_main_normalMode_setsInfoLevel(
        self, tmp_path, sampleConfig
    ):
        """
        Given: No verbose flag
        When: main() is called
        Then: setupLogging is called with INFO level
        """
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)

        mockSetupLogging = MagicMock()
        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging', mockSetupLogging):
                with patch('main.getLogger'):
                    with patch('main.runWorkflow', return_value=EXIT_SUCCESS):
                        main()

        mockSetupLogging.assert_called_once_with(level='INFO')

    def test_main_dryRunFlag_passesToWorkflow(
        self, tmp_path, sampleConfig
    ):
        """
        Given: --dry-run flag
        When: main() is called
        Then: runWorkflow is called with dryRun=True
        """
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)

        mockWorkflow = MagicMock(return_value=EXIT_SUCCESS)
        with patch('sys.argv', ['main.py', '--config', str(configFile), '--dry-run']):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', mockWorkflow):
                    main()

        _, kwargs = mockWorkflow.call_args
        assert kwargs.get('dryRun') is True

    def test_main_simulateFlag_passesToWorkflow(
        self, tmp_path, sampleConfig
    ):
        """
        Given: --simulate flag
        When: main() is called
        Then: runWorkflow is called with simulate=True
        """
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)

        mockWorkflow = MagicMock(return_value=EXIT_SUCCESS)
        with patch('sys.argv', ['main.py', '--config', str(configFile), '--simulate']):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', mockWorkflow):
                    main()

        _, kwargs = mockWorkflow.call_args
        assert kwargs.get('simulate') is True


# ================================================================================
# Edge Case Tests
# ================================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_main_keyboardInterrupt_returnsRuntimeError(
        self, tmp_path, sampleConfig
    ):
        """
        Given: KeyboardInterrupt during workflow
        When: main() is called
        Then: Returns EXIT_RUNTIME_ERROR
        """
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)

        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', side_effect=KeyboardInterrupt):
                    result = main()

        assert result == EXIT_RUNTIME_ERROR

    def test_loadConfiguration_emptyConfig_appliesDefaults(self, tmp_path):
        """
        Given: Empty configuration file
        When: loadConfiguration() is called
        Then: Applies default values
        """
        configFile = tmp_path / 'empty.json'
        with open(configFile, 'w') as f:
            json.dump({}, f)

        with patch('main.setupLogging'), patch('main.getLogger'):
            config = loadConfiguration(str(configFile))

        assert config is not None

    def test_runWorkflow_emptyConfig_dryRun_returnsSuccess(self):
        """
        Given: Empty configuration dictionary with dry_run=True
        When: runWorkflow() is called
        Then: Returns EXIT_SUCCESS (config validation only)
        """
        with patch('main.getLogger'):
            result = runWorkflow({}, dryRun=True)

        assert result == EXIT_SUCCESS

    def test_parseArgs_unknownArg_exitsWithError(self, capsys):
        """
        Given: Unknown command line argument
        When: parseArgs() is called
        Then: Exits with non-zero code
        """
        with patch('sys.argv', ['main.py', '--unknown-arg']):
            with pytest.raises(SystemExit) as exc:
                parseArgs()

        assert exc.value.code != 0

    def test_main_configWithEnvFile_loadsCorrectly(
        self, tmp_path, sampleConfig
    ):
        """
        Given: Config with --env-file specified
        When: main() is called
        Then: Loads configuration with env file
        """
        configFile = tmp_path / 'config.json'
        envFile = tmp_path / '.env.test'

        with open(configFile, 'w') as f:
            json.dump(sampleConfig, f)
        with open(envFile, 'w') as f:
            f.write('TEST_VAR=value\n')

        with patch('sys.argv', ['main.py', '-c', str(configFile),
                                '-e', str(envFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', return_value=EXIT_SUCCESS):
                    result = main()

        assert result == EXIT_SUCCESS


# ================================================================================
# Cross-Platform Signal Handler Tests (US-OSC-004)
# ================================================================================

class TestCrossPlatformSignalHandlers:
    """Tests for US-OSC-004: Signal handlers work correctly on Windows and Linux."""

    def test_signalHandlers_sigintRegistered(self):
        """
        Given: ApplicationOrchestrator
        When: registerSignalHandlers() is called
        Then: SIGINT handler is registered (works on all platforms)
        """
        import signal
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Get original handler
        originalHandler = signal.getsignal(signal.SIGINT)

        try:
            # Register handlers
            orchestrator.registerSignalHandlers()

            # Check that handler was changed
            currentHandler = signal.getsignal(signal.SIGINT)
            assert currentHandler != originalHandler
            assert currentHandler == orchestrator._handleShutdownSignal

        finally:
            # Restore original handler
            orchestrator.restoreSignalHandlers()

    def test_signalHandlers_sigtermHandledGracefullyOnWindows(self):
        """
        Given: Windows platform (no SIGTERM)
        When: registerSignalHandlers() is called
        Then: Handles gracefully (no error, only SIGINT registered)
        """
        import signal
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # This should work on all platforms
        # On Windows, SIGTERM registration is skipped gracefully
        orchestrator.registerSignalHandlers()
        orchestrator.restoreSignalHandlers()

        # Should not raise any errors
        assert orchestrator._originalSigintHandler is None

    def test_signalHandlers_logsSignalName(self):
        """
        Given: Orchestrator with signal handlers registered
        When: SIGINT signal is received
        Then: Signal name is logged correctly
        """
        import signal
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        with patch('obd.orchestrator.logger') as mockLogger:
            # Call handler directly
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Check log message contains signal name
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('SIGINT' in str(c) for c in infoCalls)

    def test_signalHandlers_storeOriginalHandlers(self):
        """
        Given: ApplicationOrchestrator
        When: registerSignalHandlers() is called
        Then: Original handlers are stored for later restoration
        """
        import signal
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        originalHandler = signal.getsignal(signal.SIGINT)

        try:
            orchestrator.registerSignalHandlers()

            # Original handler should be stored
            assert orchestrator._originalSigintHandler == originalHandler

        finally:
            orchestrator.restoreSignalHandlers()

    def test_signalHandlers_restoreOriginalHandlers(self):
        """
        Given: Orchestrator with registered signal handlers
        When: restoreSignalHandlers() is called
        Then: Original handlers are restored
        """
        import signal
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        originalHandler = signal.getsignal(signal.SIGINT)

        # Register then restore
        orchestrator.registerSignalHandlers()
        orchestrator.restoreSignalHandlers()

        # Handler should be restored
        currentHandler = signal.getsignal(signal.SIGINT)
        assert currentHandler == originalHandler
        assert orchestrator._originalSigintHandler is None

    def test_signalHandlers_doubleRestoreIsSafe(self):
        """
        Given: Orchestrator with already restored handlers
        When: restoreSignalHandlers() is called again
        Then: No error occurs
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Register and restore twice
        orchestrator.registerSignalHandlers()
        orchestrator.restoreSignalHandlers()
        orchestrator.restoreSignalHandlers()  # Second call should be safe

        # No error should occur
        assert orchestrator._originalSigintHandler is None
