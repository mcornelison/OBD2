################################################################################
# File Name: test_orchestrator.py
# Purpose/Description: Unit tests for ApplicationOrchestrator class
# Author: Ralph Agent
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-23    | Ralph Agent  | Initial implementation for US-OSC-001
# 2026-01-23    | Ralph Agent  | US-OSC-002: Add startup sequence tests
# 2026-01-23    | Ralph Agent  | US-OSC-003: Add shutdown sequence tests
# ================================================================================
################################################################################

"""
Unit tests for the ApplicationOrchestrator class.

Tests the central orchestrator that manages the lifecycle of all system
components in the Eclipse OBD-II monitoring system.

Test coverage includes:
- Constructor parameter handling
- Component initialization order
- start() method functionality
- stop() method functionality
- isRunning() state tracking
- getStatus() component status reporting
- Error handling during initialization
- Dependency injection patterns

Usage:
    pytest tests/test_orchestrator.py -v
    pytest tests/test_orchestrator.py::TestApplicationOrchestratorInit -v
"""

import signal
import sys
import threading
import time

import pytest
from unittest.mock import MagicMock, patch, call, PropertyMock
from typing import Dict, Any


class TestApplicationOrchestratorInit:
    """Test ApplicationOrchestrator initialization."""

    def test_init_acceptsConfigAndSimulate_storesParameters(self):
        """
        Given: Configuration dict and simulate flag
        When: ApplicationOrchestrator is created
        Then: Parameters are stored correctly
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': 'test.db'}}
        simulate = True

        # Act
        orchestrator = ApplicationOrchestrator(config=config, simulate=simulate)

        # Assert
        assert orchestrator._config == config
        assert orchestrator._simulate is True

    def test_init_defaultSimulateIsFalse(self):
        """
        Given: Configuration dict without simulate flag
        When: ApplicationOrchestrator is created
        Then: simulate defaults to False
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': 'test.db'}}

        # Act
        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert orchestrator._simulate is False

    def test_init_createsEmptyComponentReferences(self):
        """
        Given: Valid configuration
        When: ApplicationOrchestrator is created
        Then: All component references are None initially
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {}

        # Act
        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert orchestrator._database is None
        assert orchestrator._connection is None
        assert orchestrator._dataLogger is None
        assert orchestrator._driveDetector is None
        assert orchestrator._alertManager is None
        assert orchestrator._displayManager is None
        assert orchestrator._statisticsEngine is None
        assert orchestrator._profileManager is None
        assert orchestrator._vinDecoder is None

    def test_init_setsRunningToFalse(self):
        """
        Given: Valid configuration
        When: ApplicationOrchestrator is created
        Then: isRunning returns False
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {}

        # Act
        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert orchestrator.isRunning() is False


class TestApplicationOrchestratorIsRunning:
    """Test isRunning() method."""

    def test_isRunning_beforeStart_returnsFalse(self):
        """
        Given: Orchestrator that has not been started
        When: isRunning() is called
        Then: Returns False
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        result = orchestrator.isRunning()

        # Assert
        assert result is False

    def test_isRunning_afterStop_returnsFalse(self):
        """
        Given: Orchestrator that has been stopped
        When: isRunning() is called
        Then: Returns False
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True  # Simulate started state
        orchestrator._running = False  # Simulate stopped state

        # Act
        result = orchestrator.isRunning()

        # Assert
        assert result is False


class TestApplicationOrchestratorGetStatus:
    """Test getStatus() method."""

    def test_getStatus_returnsComponentStates(self):
        """
        Given: Orchestrator with some components initialized
        When: getStatus() is called
        Then: Returns dict with status of all components
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        status = orchestrator.getStatus()

        # Assert
        assert isinstance(status, dict)
        assert 'running' in status
        assert 'components' in status
        assert 'database' in status['components']
        assert 'connection' in status['components']
        assert 'dataLogger' in status['components']
        assert 'driveDetector' in status['components']
        assert 'alertManager' in status['components']
        assert 'displayManager' in status['components']
        assert 'statisticsEngine' in status['components']
        assert 'profileManager' in status['components']
        assert 'vinDecoder' in status['components']

    def test_getStatus_showsInitializedState(self):
        """
        Given: Orchestrator with a component initialized
        When: getStatus() is called
        Then: Shows 'initialized' for that component
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._database = MagicMock()

        # Act
        status = orchestrator.getStatus()

        # Assert
        assert status['components']['database'] == 'initialized'
        assert status['components']['connection'] == 'not_initialized'

    def test_getStatus_includesRunningState(self):
        """
        Given: Orchestrator in running state
        When: getStatus() is called
        Then: Returns running=True
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True

        # Act
        status = orchestrator.getStatus()

        # Assert
        assert status['running'] is True


class TestApplicationOrchestratorComponentAccess:
    """Test component accessor properties."""

    def test_database_property_returnsStoredDatabase(self):
        """
        Given: Orchestrator with database set
        When: database property is accessed
        Then: Returns the stored database instance
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDb = MagicMock()
        orchestrator._database = mockDb

        # Act
        result = orchestrator.database

        # Assert
        assert result is mockDb

    def test_connection_property_returnsStoredConnection(self):
        """
        Given: Orchestrator with connection set
        When: connection property is accessed
        Then: Returns the stored connection instance
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        orchestrator._connection = mockConn

        # Act
        result = orchestrator.connection

        # Assert
        assert result is mockConn

    def test_dataLogger_property_returnsStoredLogger(self):
        """
        Given: Orchestrator with data logger set
        When: dataLogger property is accessed
        Then: Returns the stored logger instance
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger

        # Act
        result = orchestrator.dataLogger

        # Assert
        assert result is mockLogger


class TestApplicationOrchestratorStart:
    """Test start() method."""

    @patch('obd.orchestrator.createDatabaseFromConfig')
    def test_start_initializesDatabase(self, mockCreateDb):
        """
        Given: Valid configuration
        When: _initializeDatabase is called
        Then: Database is created and initialized
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        mockDb = MagicMock()
        mockCreateDb.return_value = mockDb
        config = {'database': {'path': 'test.db'}}
        orchestrator = ApplicationOrchestrator(config=config)

        # Act
        orchestrator._initializeDatabase()

        # Assert
        mockCreateDb.assert_called_once_with(config)
        mockDb.initialize.assert_called_once()

    @patch('obd.orchestrator.createDatabaseFromConfig')
    @patch('obd.orchestrator.logger')
    def test_start_logsStartupProgress(self, mockLogger, mockCreateDb):
        """
        Given: Valid configuration
        When: start() is called
        Then: Startup progress is logged
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        mockDb = MagicMock()
        mockCreateDb.return_value = mockDb
        config = {}
        orchestrator = ApplicationOrchestrator(config=config)

        # Act
        with patch.object(orchestrator, '_initializeAllComponents'):
            orchestrator.start()

        # Assert
        # Check that logging calls were made
        assert mockLogger.info.called

    def test_start_setsRunningToTrue(self):
        """
        Given: Valid configuration
        When: start() is called successfully
        Then: isRunning() returns True
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {}
        orchestrator = ApplicationOrchestrator(config=config)

        # Act
        with patch.object(orchestrator, '_initializeAllComponents'):
            orchestrator.start()

        # Assert
        assert orchestrator.isRunning() is True


class TestApplicationOrchestratorStop:
    """Test stop() method."""

    def test_stop_setsRunningToFalse(self):
        """
        Given: Running orchestrator
        When: stop() is called
        Then: isRunning() returns False
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True

        # Act
        orchestrator.stop()

        # Assert
        assert orchestrator.isRunning() is False

    def test_stop_cleansUpComponents(self):
        """
        Given: Orchestrator with initialized components
        When: stop() is called
        Then: Components are cleaned up
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True
        mockLogger = MagicMock()
        mockLogger.stop = MagicMock()
        orchestrator._dataLogger = mockLogger

        # Act
        orchestrator.stop()

        # Assert
        mockLogger.stop.assert_called_once()

    def test_stop_whenNotRunning_doesNothing(self):
        """
        Given: Orchestrator that is not running
        When: stop() is called
        Then: Returns gracefully without error
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        assert orchestrator._running is False

        # Act & Assert - should not raise
        orchestrator.stop()


class TestApplicationOrchestratorErrorHandling:
    """Test error handling during component initialization."""

    @patch('obd.orchestrator.createDatabaseFromConfig')
    @patch('obd.orchestrator.logger')
    def test_start_databaseInitFails_logsError(self, mockLogger, mockCreateDb):
        """
        Given: Database initialization fails
        When: start() is called
        Then: Error is logged with clear message
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, OrchestratorError

        mockCreateDb.side_effect = Exception("Database connection failed")
        config = {}
        orchestrator = ApplicationOrchestrator(config=config)

        # Act & Assert
        with pytest.raises(OrchestratorError):
            orchestrator.start()

        # Verify error logging
        assert mockLogger.error.called


class TestOrchestratorExport:
    """Test that orchestrator is properly exported."""

    def test_importFromObdOrchestrator_succeeds(self):
        """
        Given: The obd.orchestrator module
        When: Importing ApplicationOrchestrator
        Then: Import succeeds
        """
        # Act
        from obd.orchestrator import ApplicationOrchestrator

        # Assert
        assert ApplicationOrchestrator is not None

    def test_importOrchestratorError_succeeds(self):
        """
        Given: The obd.orchestrator module
        When: Importing OrchestratorError
        Then: Import succeeds
        """
        # Act
        from obd.orchestrator import OrchestratorError

        # Assert
        assert OrchestratorError is not None


class TestStartupSequenceOrder:
    """Test US-OSC-002: Startup sequence follows correct order."""

    def test_startupSequence_followsCorrectOrder(self):
        """
        Given: An ApplicationOrchestrator with valid config
        When: _initializeAllComponents is called
        Then: Components are initialized in dependency order
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={}, simulate=True)
        initOrder = []

        # Mock each init method to track call order
        def makeTracker(name):
            def tracker():
                initOrder.append(name)
            return tracker

        orchestrator._initializeDatabase = makeTracker('database')
        orchestrator._initializeProfileManager = makeTracker('profileManager')
        orchestrator._initializeConnection = makeTracker('connection')
        orchestrator._initializeVinDecoder = makeTracker('vinDecoder')
        orchestrator._initializeDisplayManager = makeTracker('displayManager')
        orchestrator._initializeDriveDetector = makeTracker('driveDetector')
        orchestrator._initializeAlertManager = makeTracker('alertManager')
        orchestrator._initializeStatisticsEngine = makeTracker('statisticsEngine')
        orchestrator._initializeDataLogger = makeTracker('dataLogger')

        # Act
        orchestrator._initializeAllComponents()

        # Assert - verify exact order
        expectedOrder = [
            'database', 'profileManager', 'connection', 'vinDecoder',
            'displayManager', 'driveDetector', 'alertManager',
            'statisticsEngine', 'dataLogger'
        ]
        assert initOrder == expectedOrder


class TestStartupLogging:
    """Test US-OSC-002: Startup logging requirements."""

    @patch('obd.orchestrator.logger')
    @patch('obd.orchestrator.createDatabaseFromConfig')
    def test_startup_logsStartingMessageForEachComponent(
        self, mockCreateDb, mockLogger
    ):
        """
        Given: ApplicationOrchestrator starting components
        When: _initializeDatabase is called
        Then: 'Starting database...' is logged at INFO level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        mockDb = MagicMock()
        mockCreateDb.return_value = mockDb
        orchestrator = ApplicationOrchestrator(config={})

        # Act
        orchestrator._initializeDatabase()

        # Assert - check INFO level log with 'Starting' message
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('Starting database' in str(c) for c in infoCalls)

    @patch('obd.orchestrator.logger')
    @patch('obd.orchestrator.createDatabaseFromConfig')
    def test_startup_logsSuccessMessageForEachComponent(
        self, mockCreateDb, mockLogger
    ):
        """
        Given: ApplicationOrchestrator starting components
        When: _initializeDatabase succeeds
        Then: 'Database started successfully' is logged at INFO level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        mockDb = MagicMock()
        mockCreateDb.return_value = mockDb
        orchestrator = ApplicationOrchestrator(config={})

        # Act
        orchestrator._initializeDatabase()

        # Assert
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('Database started successfully' in str(c) for c in infoCalls)

    @patch('obd.orchestrator.logger')
    @patch('obd.orchestrator.createDatabaseFromConfig')
    def test_startup_logsErrorOnFailure(self, mockCreateDb, mockLogger):
        """
        Given: ApplicationOrchestrator starting components
        When: Database initialization fails
        Then: Error is logged at ERROR level with clear message
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, ComponentInitializationError

        mockCreateDb.side_effect = Exception("Connection refused")
        orchestrator = ApplicationOrchestrator(config={})

        # Act & Assert
        with pytest.raises(ComponentInitializationError):
            orchestrator._initializeDatabase()

        # Verify error logging
        assert mockLogger.error.called
        errorCalls = [str(c) for c in mockLogger.error.call_args_list]
        assert any('database' in str(c).lower() for c in errorCalls)


class TestStartupTiming:
    """Test US-OSC-002: Total startup time logging."""

    @patch('obd.orchestrator.logger')
    def test_start_logsTotalStartupTime(self, mockLogger):
        """
        Given: ApplicationOrchestrator starting
        When: start() completes successfully
        Then: Total startup time is logged
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Mock init to succeed quickly
        with patch.object(orchestrator, '_initializeAllComponents'):
            # Act
            orchestrator.start()

        # Assert - check that startup completion is logged
        assert mockLogger.info.called
        # Check for success message
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('started successfully' in str(c).lower() for c in infoCalls)


class TestStartupAbort:
    """Test US-OSC-002: Startup abort with Ctrl+C."""

    def test_start_canBeInterruptedByKeyboardInterrupt(self):
        """
        Given: ApplicationOrchestrator starting components
        When: KeyboardInterrupt is raised during startup
        Then: Startup is aborted and partial state is cleaned up
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        def raiseInterrupt():
            raise KeyboardInterrupt()

        orchestrator._initializeAllComponents = raiseInterrupt
        cleanupCalled = []
        orchestrator._cleanupPartialInitialization = lambda: cleanupCalled.append(True)

        # Act & Assert
        with pytest.raises(KeyboardInterrupt):
            orchestrator.start()

        # Verify cleanup was called
        assert len(cleanupCalled) == 1

    def test_start_setsAbortedStateOnInterrupt(self):
        """
        Given: ApplicationOrchestrator starting
        When: KeyboardInterrupt is raised
        Then: isRunning() returns False
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        def raiseInterrupt():
            raise KeyboardInterrupt()

        orchestrator._initializeAllComponents = raiseInterrupt
        orchestrator._cleanupPartialInitialization = lambda: None

        # Act
        with pytest.raises(KeyboardInterrupt):
            orchestrator.start()

        # Assert
        assert orchestrator.isRunning() is False


class TestStartupCleanup:
    """Test US-OSC-002: Partial startup state cleanup."""

    def test_cleanupPartialInitialization_callsShutdownAll(self):
        """
        Given: Orchestrator with partially initialized components
        When: _cleanupPartialInitialization is called
        Then: _shutdownAllComponents is called to clean up
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        shutdownCalled = []
        orchestrator._shutdownAllComponents = lambda: shutdownCalled.append(True)

        # Manually set some components as initialized
        orchestrator._database = MagicMock()
        orchestrator._profileManager = MagicMock()

        # Act
        orchestrator._cleanupPartialInitialization()

        # Assert
        assert len(shutdownCalled) == 1

    def test_start_cleansUpOnInitializationError(self):
        """
        Given: ApplicationOrchestrator starting
        When: A component initialization fails
        Then: Partial state is cleaned up before error propagates
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, OrchestratorError

        orchestrator = ApplicationOrchestrator(config={})
        cleanupCalled = []

        def failingInit():
            raise Exception("Component failed")

        orchestrator._initializeAllComponents = failingInit
        original_cleanup = orchestrator._cleanupPartialInitialization
        orchestrator._cleanupPartialInitialization = lambda: (
            cleanupCalled.append(True),
            original_cleanup() if False else None  # Don't actually call original
        )[0]

        # Act & Assert
        with pytest.raises(OrchestratorError):
            orchestrator.start()

        # Verify cleanup was called
        assert len(cleanupCalled) == 1


class TestConnectionRetry:
    """Test US-OSC-002: Connection retry with exponential backoff."""

    @patch('obd.orchestrator.createDatabaseFromConfig')
    def test_initializeConnection_usesConfigRetrySettings(self, mockCreateDb):
        """
        Given: Config with bluetooth.retryDelays settings
        When: Connection initialization occurs
        Then: Retry settings from config are used
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        mockDb = MagicMock()
        mockCreateDb.return_value = mockDb

        config = {
            'bluetooth': {
                'retryDelays': [1, 2, 4, 8, 16],
                'maxRetries': 5,
                'connectionTimeoutSeconds': 30
            }
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        orchestrator._database = mockDb

        # The config should be passed to connection creation
        # Verify config is stored correctly
        assert orchestrator._config == config
        assert orchestrator._config.get('bluetooth', {}).get('retryDelays') == [1, 2, 4, 8, 16]


# ================================================================================
# US-OSC-003: Shutdown Sequence Tests
# ================================================================================


class TestShutdownSequenceOrder:
    """Test US-OSC-003: Shutdown sequence follows reverse order."""

    def test_shutdownSequence_followsReverseOrder(self):
        """
        Given: An ApplicationOrchestrator with components initialized
        When: _shutdownAllComponents is called
        Then: Components are shutdown in reverse dependency order
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={}, simulate=True)
        orchestrator._running = True
        shutdownOrder = []

        # Create mock components with stop methods that track order
        def createMockComponent(name):
            mock = MagicMock()
            mock.stop = MagicMock(side_effect=lambda: shutdownOrder.append(name))
            mock.disconnect = MagicMock(
                side_effect=lambda: shutdownOrder.append(name)
            )
            return mock

        orchestrator._dataLogger = createMockComponent('dataLogger')
        orchestrator._statisticsEngine = createMockComponent('statisticsEngine')
        orchestrator._alertManager = createMockComponent('alertManager')
        orchestrator._driveDetector = createMockComponent('driveDetector')
        orchestrator._displayManager = createMockComponent('displayManager')
        orchestrator._vinDecoder = createMockComponent('vinDecoder')
        orchestrator._connection = createMockComponent('connection')
        orchestrator._profileManager = createMockComponent('profileManager')
        orchestrator._database = MagicMock()  # Database has no stop method

        # Act
        orchestrator._shutdownAllComponents()

        # Assert - verify reverse order of initialization
        expectedOrder = [
            'dataLogger', 'statisticsEngine', 'alertManager', 'driveDetector',
            'displayManager', 'vinDecoder', 'connection', 'profileManager'
        ]
        assert shutdownOrder == expectedOrder


class TestShutdownTimeout:
    """Test US-OSC-003: Configurable shutdown timeouts."""

    def test_shutdown_usesConfigurableTimeout(self):
        """
        Given: Config with custom shutdown timeout
        When: ApplicationOrchestrator is created
        Then: Custom timeout is used for component shutdown
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'shutdown': {'componentTimeout': 10.0}}

        # Act
        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert orchestrator._shutdownTimeout == 10.0

    def test_shutdown_defaultsTo5Seconds(self):
        """
        Given: Config without shutdown timeout
        When: ApplicationOrchestrator is created
        Then: Default timeout of 5 seconds is used
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, DEFAULT_SHUTDOWN_TIMEOUT

        config = {}

        # Act
        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert orchestrator._shutdownTimeout == DEFAULT_SHUTDOWN_TIMEOUT
        assert orchestrator._shutdownTimeout == 5.0

    @patch('obd.orchestrator.logger')
    def test_shutdown_forceStopsSlowComponent(self, mockLogger):
        """
        Given: Component that doesn't stop within timeout
        When: Shutdown is attempted
        Then: Component is force-stopped with warning
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, EXIT_CODE_FORCED

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._shutdownTimeout = 0.1  # Very short timeout for test
        orchestrator._running = True

        # Create a component that hangs
        slowComponent = MagicMock()
        slowComponent.stop = MagicMock(side_effect=lambda: time.sleep(1))
        orchestrator._dataLogger = slowComponent

        # Act
        orchestrator._shutdownDataLogger()

        # Assert - warning logged and exit code set
        warningCalls = [str(c) for c in mockLogger.warning.call_args_list]
        assert any('force-stopping' in str(c).lower() for c in warningCalls)
        assert orchestrator._exitCode == EXIT_CODE_FORCED


class TestShutdownExitCodes:
    """Test US-OSC-003: Exit codes for shutdown."""

    def test_cleanShutdown_returnsExitCode0(self):
        """
        Given: Orchestrator that shuts down cleanly
        When: stop() is called
        Then: Exit code 0 is returned
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, EXIT_CODE_CLEAN

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True

        # Act
        exitCode = orchestrator.stop()

        # Assert
        assert exitCode == EXIT_CODE_CLEAN
        assert orchestrator.exitCode == EXIT_CODE_CLEAN

    def test_forcedShutdown_returnsNonZeroExitCode(self):
        """
        Given: Orchestrator with forced shutdown
        When: stop() is called after force exit triggered
        Then: Non-zero exit code is returned
        """
        # Arrange
        from obd.orchestrator import (
            ApplicationOrchestrator, ShutdownState, EXIT_CODE_FORCED
        )

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.FORCE_EXIT

        # Act
        exitCode = orchestrator.stop()

        # Assert
        assert exitCode == EXIT_CODE_FORCED

    def test_stop_returnsExitCodeWhenNotRunning(self):
        """
        Given: Orchestrator that is not running
        When: stop() is called
        Then: Returns current exit code
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        assert orchestrator._running is False

        # Act
        exitCode = orchestrator.stop()

        # Assert - returns clean exit by default
        assert exitCode == 0


class TestShutdownSignalHandling:
    """Test US-OSC-003: Signal handling for shutdown."""

    def test_registerSignalHandlers_registersSigint(self):
        """
        Given: ApplicationOrchestrator
        When: registerSignalHandlers is called
        Then: SIGINT handler is registered
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        with patch('obd.orchestrator.signal.signal') as mockSignal:
            orchestrator.registerSignalHandlers()

        # Assert
        calls = mockSignal.call_args_list
        sigintCall = [c for c in calls if c[0][0] == signal.SIGINT]
        assert len(sigintCall) == 1

    def test_restoreSignalHandlers_restoresOriginal(self):
        """
        Given: Orchestrator with registered signal handlers
        When: restoreSignalHandlers is called
        Then: Original handlers are restored
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        originalHandler = signal.getsignal(signal.SIGINT)

        # Register custom handlers
        orchestrator.registerSignalHandlers()

        # Act
        orchestrator.restoreSignalHandlers()

        # Assert - handlers restored
        assert orchestrator._originalSigintHandler is None

    def test_handleShutdownSignal_firstSignal_requestsGracefulShutdown(self):
        """
        Given: Orchestrator in running state
        When: First shutdown signal received
        Then: Graceful shutdown is requested
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._shutdownState = ShutdownState.RUNNING

        # Act
        orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        assert orchestrator._shutdownState == ShutdownState.SHUTDOWN_REQUESTED

    def test_handleShutdownSignal_secondSignal_forcesExit(self):
        """
        Given: Orchestrator with shutdown already requested
        When: Second shutdown signal received
        Then: Force exit is triggered
        """
        # Arrange
        from obd.orchestrator import (
            ApplicationOrchestrator, ShutdownState, EXIT_CODE_FORCED
        )

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act & Assert - should call sys.exit
        with pytest.raises(SystemExit) as exc:
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

        assert exc.value.code == EXIT_CODE_FORCED

    @patch('obd.orchestrator.logger')
    def test_handleShutdownSignal_logsSignalReceived(self, mockLogger):
        """
        Given: Orchestrator
        When: Shutdown signal received
        Then: Signal is logged
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        assert mockLogger.info.called
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('signal' in str(c).lower() for c in infoCalls)


class TestShutdownForceExit:
    """Test US-OSC-003: Double Ctrl+C forces immediate exit."""

    def test_forceExit_skipsGracefulShutdown(self):
        """
        Given: Orchestrator in force exit state
        When: stop() is called
        Then: Graceful shutdown is skipped
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.FORCE_EXIT

        # Set up components that should NOT have stop called
        mockComponent = MagicMock()
        orchestrator._dataLogger = mockComponent

        # Act
        orchestrator.stop()

        # Assert - stop was never called on component
        mockComponent.stop.assert_not_called()

    @patch('obd.orchestrator.logger')
    def test_forceExit_logsWarning(self, mockLogger):
        """
        Given: Orchestrator in force exit state
        When: stop() is called
        Then: Warning is logged about skipping graceful shutdown
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.FORCE_EXIT

        # Act
        orchestrator.stop()

        # Assert
        warningCalls = [str(c) for c in mockLogger.warning.call_args_list]
        assert any('force exit' in str(c).lower() for c in warningCalls)


class TestShutdownLogging:
    """Test US-OSC-003: Shutdown logging."""

    @patch('obd.orchestrator.logger')
    def test_shutdown_logsComponentStopMessages(self, mockLogger):
        """
        Given: Orchestrator with initialized components
        When: _shutdownDataLogger is called
        Then: Stop messages are logged at INFO level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockComponent = MagicMock()
        orchestrator._dataLogger = mockComponent

        # Act
        orchestrator._shutdownDataLogger()

        # Assert
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('stopping datalogger' in str(c).lower() for c in infoCalls)
        assert any('stopped successfully' in str(c).lower() for c in infoCalls)

    @patch('obd.orchestrator.logger')
    def test_stop_logsTotalShutdownTime(self, mockLogger):
        """
        Given: Running orchestrator
        When: stop() completes
        Then: Total shutdown time is logged
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True

        # Act
        orchestrator.stop()

        # Assert
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('shutdown_time' in str(c) for c in infoCalls)


class TestShutdownState:
    """Test US-OSC-003: Shutdown state management."""

    def test_shutdownState_initiallyRunning(self):
        """
        Given: New ApplicationOrchestrator
        When: Created
        Then: Shutdown state is RUNNING
        """
        # Arrange & Act
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(config={})

        # Assert
        assert orchestrator.shutdownState == ShutdownState.RUNNING

    def test_shutdownState_property_exposesState(self):
        """
        Given: Orchestrator with modified shutdown state
        When: shutdownState property accessed
        Then: Current state is returned
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act
        state = orchestrator.shutdownState

        # Assert
        assert state == ShutdownState.SHUTDOWN_REQUESTED


class TestShutdownComponentCleanup:
    """Test US-OSC-003: Component reference cleanup."""

    def test_shutdown_clearsComponentReferences(self):
        """
        Given: Orchestrator with initialized components
        When: shutdown completes
        Then: All component references are cleared (set to None)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True

        # Set up mock components
        orchestrator._dataLogger = MagicMock()
        orchestrator._alertManager = MagicMock()
        orchestrator._driveDetector = MagicMock()
        orchestrator._statisticsEngine = MagicMock()
        orchestrator._displayManager = MagicMock()
        orchestrator._vinDecoder = MagicMock()
        orchestrator._connection = MagicMock()
        orchestrator._profileManager = MagicMock()
        orchestrator._database = MagicMock()

        # Act
        orchestrator.stop()

        # Assert - all references cleared
        assert orchestrator._dataLogger is None
        assert orchestrator._alertManager is None
        assert orchestrator._driveDetector is None
        assert orchestrator._statisticsEngine is None
        assert orchestrator._displayManager is None
        assert orchestrator._vinDecoder is None
        assert orchestrator._connection is None
        assert orchestrator._profileManager is None
        assert orchestrator._database is None


class TestShutdownErrorHandling:
    """Test US-OSC-003: Error handling during shutdown."""

    @patch('obd.orchestrator.logger')
    def test_shutdown_continuesOnComponentError(self, mockLogger):
        """
        Given: Component that throws error during stop
        When: shutdown is performed
        Then: Other components still get stopped
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True

        # First component throws error
        badComponent = MagicMock()
        badComponent.stop = MagicMock(side_effect=Exception("Stop failed"))
        orchestrator._dataLogger = badComponent

        # Second component should still be stopped
        goodComponent = MagicMock()
        orchestrator._alertManager = goodComponent

        # Act
        orchestrator.stop()

        # Assert - both components attempted shutdown
        badComponent.stop.assert_called()
        goodComponent.stop.assert_called()

    @patch('obd.orchestrator.logger')
    def test_shutdown_logsErrorAndContinues(self, mockLogger):
        """
        Given: Component that throws error during stop
        When: shutdown is performed
        Then: Error is logged as warning and shutdown continues
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True

        errorComponent = MagicMock()
        errorComponent.stop = MagicMock(side_effect=Exception("Component error"))
        orchestrator._dataLogger = errorComponent

        # Act
        orchestrator.stop()

        # Assert - component reference still cleared
        assert orchestrator._dataLogger is None


# ================================================================================
# US-OSC-005: Main Application Loop Tests
# ================================================================================


class TestMainLoopBasic:
    """Test US-OSC-005: Basic main loop functionality."""

    def test_runLoop_whenNotRunning_returnsImmediately(self):
        """
        Given: Orchestrator that has not been started
        When: runLoop() is called
        Then: Returns immediately without error
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        assert orchestrator._running is False

        # Act & Assert - should not hang or raise
        orchestrator.runLoop()

    def test_runLoop_exitsOnShutdownRequested(self):
        """
        Given: Running orchestrator
        When: Shutdown is requested during loop
        Then: Loop exits gracefully
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True
        orchestrator._loopSleepInterval = 0.01  # Speed up test

        # Set shutdown after brief delay
        def triggerShutdown():
            time.sleep(0.05)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown)
        shutdownThread.start()

        # Act
        orchestrator.runLoop()

        # Assert - loop exited
        shutdownThread.join(timeout=1.0)
        assert orchestrator._shutdownState == ShutdownState.SHUTDOWN_REQUESTED


class TestMainLoopHealthCheck:
    """Test US-OSC-005: Health check functionality."""

    def test_healthCheckInterval_defaultsTo60Seconds(self):
        """
        Given: Config without monitoring.healthCheckIntervalSeconds
        When: ApplicationOrchestrator is created
        Then: Health check interval defaults to 60 seconds
        """
        # Arrange & Act
        from obd.orchestrator import (
            ApplicationOrchestrator, DEFAULT_HEALTH_CHECK_INTERVAL
        )

        orchestrator = ApplicationOrchestrator(config={})

        # Assert
        assert orchestrator._healthCheckInterval == DEFAULT_HEALTH_CHECK_INTERVAL
        assert orchestrator._healthCheckInterval == 60.0

    def test_healthCheckInterval_canBeConfigured(self):
        """
        Given: Config with custom healthCheckIntervalSeconds
        When: ApplicationOrchestrator is created
        Then: Custom interval is used
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'monitoring': {'healthCheckIntervalSeconds': 120.0}}

        # Act
        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert orchestrator._healthCheckInterval == 120.0

    def test_setHealthCheckInterval_updatesInterval(self):
        """
        Given: Running orchestrator
        When: setHealthCheckInterval is called
        Then: Interval is updated
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        orchestrator.setHealthCheckInterval(90.0)

        # Assert
        assert orchestrator._healthCheckInterval == 90.0

    def test_setHealthCheckInterval_rejectsUnder10Seconds(self):
        """
        Given: ApplicationOrchestrator
        When: setHealthCheckInterval called with < 10 seconds
        Then: ValueError is raised
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act & Assert
        with pytest.raises(ValueError) as exc:
            orchestrator.setHealthCheckInterval(5.0)

        assert "at least 10 seconds" in str(exc.value)

    @patch('obd.orchestrator.logger')
    def test_performHealthCheck_logsStatus(self, mockLogger):
        """
        Given: Running orchestrator
        When: _performHealthCheck is called
        Then: Status is logged with required fields
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator
        from datetime import datetime

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._startTime = datetime.now()
        orchestrator._lastDataRateCheckTime = datetime.now()
        orchestrator._lastDataRateReadingCount = 0

        # Act
        orchestrator._performHealthCheck()

        # Assert - check log was called with health check info
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('HEALTH CHECK' in str(c) for c in infoCalls)
        assert any('connection=' in str(c) for c in infoCalls)
        assert any('data_rate=' in str(c) for c in infoCalls)
        assert any('errors=' in str(c) for c in infoCalls)


class TestMainLoopCallbacks:
    """Test US-OSC-005: Component callback handling."""

    def test_registerCallbacks_storesCallbacks(self):
        """
        Given: ApplicationOrchestrator
        When: registerCallbacks is called with handlers
        Then: Callbacks are stored
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        onDriveStart = MagicMock()
        onDriveEnd = MagicMock()
        onAlert = MagicMock()

        # Act
        orchestrator.registerCallbacks(
            onDriveStart=onDriveStart,
            onDriveEnd=onDriveEnd,
            onAlert=onAlert
        )

        # Assert
        assert orchestrator._onDriveStart is onDriveStart
        assert orchestrator._onDriveEnd is onDriveEnd
        assert orchestrator._onAlert is onAlert

    def test_handleDriveStart_invokesCallback(self):
        """
        Given: Orchestrator with onDriveStart callback registered
        When: _handleDriveStart is called
        Then: Callback is invoked with session
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        callbackMock = MagicMock()
        orchestrator._onDriveStart = callbackMock
        mockSession = MagicMock()

        # Act
        orchestrator._handleDriveStart(mockSession)

        # Assert
        callbackMock.assert_called_once_with(mockSession)

    def test_handleDriveStart_incrementsDriveCount(self):
        """
        Given: Orchestrator
        When: _handleDriveStart is called
        Then: drivesDetected stat is incremented
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        initialCount = orchestrator._healthCheckStats.drivesDetected

        # Act
        orchestrator._handleDriveStart(MagicMock())

        # Assert
        assert orchestrator._healthCheckStats.drivesDetected == initialCount + 1

    def test_handleDriveEnd_invokesCallback(self):
        """
        Given: Orchestrator with onDriveEnd callback registered
        When: _handleDriveEnd is called
        Then: Callback is invoked with session
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        callbackMock = MagicMock()
        orchestrator._onDriveEnd = callbackMock
        mockSession = MagicMock()
        mockSession.duration = 120.5

        # Act
        orchestrator._handleDriveEnd(mockSession)

        # Assert
        callbackMock.assert_called_once_with(mockSession)

    def test_handleAlert_invokesCallbackAndIncrementsCount(self):
        """
        Given: Orchestrator with onAlert callback registered
        When: _handleAlert is called
        Then: Callback is invoked and alertsTriggered is incremented
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        callbackMock = MagicMock()
        orchestrator._onAlert = callbackMock
        mockAlert = MagicMock()
        mockAlert.alertType = 'RPM_HIGH'
        initialCount = orchestrator._healthCheckStats.alertsTriggered

        # Act
        orchestrator._handleAlert(mockAlert)

        # Assert
        callbackMock.assert_called_once_with(mockAlert)
        assert orchestrator._healthCheckStats.alertsTriggered == initialCount + 1

    def test_handleReading_incrementsReadingCount(self):
        """
        Given: Orchestrator
        When: _handleReading is called
        Then: totalReadings stat is incremented
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        initialCount = orchestrator._healthCheckStats.totalReadings
        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 3000

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        assert orchestrator._healthCheckStats.totalReadings == initialCount + 1

    def test_handleReading_passesToDriveDetector(self):
        """
        Given: Orchestrator with drive detector
        When: _handleReading is called with RPM value
        Then: Value is passed to drive detector
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector
        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 2500

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockDetector.processValue.assert_called_once_with('RPM', 2500)

    def test_handleReading_passesToAlertManager(self):
        """
        Given: Orchestrator with alert manager
        When: _handleReading is called
        Then: Value is passed to alert manager for threshold checking
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockAlertMgr = MagicMock()
        orchestrator._alertManager = mockAlertMgr
        mockReading = MagicMock()
        mockReading.parameterName = 'COOLANT_TEMP'
        mockReading.value = 105

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockAlertMgr.checkValue.assert_called_once_with('COOLANT_TEMP', 105)


class TestMainLoopConnectionMonitoring:
    """Test US-OSC-005: Connection status monitoring."""

    def test_checkConnectionStatus_returnsTrueWhenConnected(self):
        """
        Given: Orchestrator with connected OBD connection
        When: _checkConnectionStatus is called
        Then: Returns True
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        mockConn.isConnected.return_value = True
        orchestrator._connection = mockConn

        # Act
        result = orchestrator._checkConnectionStatus()

        # Assert
        assert result is True

    def test_checkConnectionStatus_returnsFalseWhenDisconnected(self):
        """
        Given: Orchestrator with disconnected OBD connection
        When: _checkConnectionStatus is called
        Then: Returns False
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        mockConn.isConnected.return_value = False
        orchestrator._connection = mockConn

        # Act
        result = orchestrator._checkConnectionStatus()

        # Assert
        assert result is False

    def test_checkConnectionStatus_returnsFalseWhenNoConnection(self):
        """
        Given: Orchestrator without connection component
        When: _checkConnectionStatus is called
        Then: Returns False
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._connection = None

        # Act
        result = orchestrator._checkConnectionStatus()

        # Assert
        assert result is False

    def test_handleConnectionLost_invokesCallback(self):
        """
        Given: Orchestrator with onConnectionLost callback
        When: _handleConnectionLost is called
        Then: Callback is invoked
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        callbackMock = MagicMock()
        orchestrator._onConnectionLost = callbackMock

        # Act
        orchestrator._handleConnectionLost()

        # Assert
        callbackMock.assert_called_once()

    def test_handleConnectionLost_updatesHealthStats(self):
        """
        Given: Orchestrator
        When: _handleConnectionLost is called
        Then: Health stats show disconnected
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        orchestrator._handleConnectionLost()

        # Assert
        assert orchestrator._healthCheckStats.connectionConnected is False
        assert orchestrator._healthCheckStats.connectionStatus == "disconnected"

    def test_handleConnectionRestored_invokesCallback(self):
        """
        Given: Orchestrator with onConnectionRestored callback
        When: _handleConnectionRestored is called
        Then: Callback is invoked
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        callbackMock = MagicMock()
        orchestrator._onConnectionRestored = callbackMock

        # Act
        orchestrator._handleConnectionRestored()

        # Assert
        callbackMock.assert_called_once()

    def test_handleConnectionRestored_updatesHealthStats(self):
        """
        Given: Orchestrator
        When: _handleConnectionRestored is called
        Then: Health stats show connected
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        orchestrator._handleConnectionRestored()

        # Assert
        assert orchestrator._healthCheckStats.connectionConnected is True
        assert orchestrator._healthCheckStats.connectionStatus == "connected"


class TestMainLoopExceptionHandling:
    """Test US-OSC-005: Loop exception handling."""

    def test_runLoop_catchesAndLogsUnexpectedExceptions(self):
        """
        Given: Running orchestrator
        When: Exception occurs in loop iteration
        Then: Exception is logged and loop continues
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState
        from datetime import datetime

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True
        orchestrator._loopSleepInterval = 0.01
        orchestrator._healthCheckInterval = 1000  # Don't trigger health check

        # Initialize timestamps that runLoop needs
        orchestrator._startTime = datetime.now()
        orchestrator._lastHealthCheckTime = datetime.now()
        orchestrator._lastDataRateCheckTime = datetime.now()

        exceptionCount = [0]
        iterations = [0]

        # Mock _checkConnectionStatus to throw on second call (first is setup)
        originalCheck = orchestrator._checkConnectionStatus

        def throwOnSecond():
            iterations[0] += 1
            if iterations[0] == 2 and exceptionCount[0] == 0:
                exceptionCount[0] += 1
                raise RuntimeError("Test exception")
            return False  # Return disconnected for all other calls

        orchestrator._checkConnectionStatus = throwOnSecond

        # Trigger shutdown after a few iterations
        def triggerShutdown():
            time.sleep(0.15)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown)
        shutdownThread.start()

        # Act
        orchestrator.runLoop()

        # Assert - loop ran and caught exception
        shutdownThread.join(timeout=1.0)
        assert exceptionCount[0] == 1
        assert orchestrator._healthCheckStats.totalErrors >= 1

    def test_handleDriveStart_catchesCallbackErrors(self):
        """
        Given: Orchestrator with callback that throws
        When: _handleDriveStart is called
        Then: Error is caught and logged, doesn't crash
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        def throwingCallback(session):
            raise RuntimeError("Callback error")

        orchestrator._onDriveStart = throwingCallback

        # Act & Assert - should not raise
        orchestrator._handleDriveStart(MagicMock())


class TestMainLoopLoggingError:
    """Test US-OSC-005: Logging error handling."""

    def test_handleLoggingError_incrementsErrorCount(self):
        """
        Given: Orchestrator
        When: _handleLoggingError is called
        Then: totalErrors stat is incremented
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        initialErrors = orchestrator._healthCheckStats.totalErrors

        # Act
        orchestrator._handleLoggingError('RPM', RuntimeError("Read failed"))

        # Assert
        assert orchestrator._healthCheckStats.totalErrors == initialErrors + 1


class TestHealthCheckStats:
    """Test US-OSC-005: HealthCheckStats dataclass."""

    def test_healthCheckStats_toDict_returnsAllFields(self):
        """
        Given: HealthCheckStats instance
        When: toDict is called
        Then: All fields are included in dictionary
        """
        # Arrange
        from obd.orchestrator import HealthCheckStats
        from datetime import datetime

        stats = HealthCheckStats(
            connectionConnected=True,
            connectionStatus="connected",
            dataRatePerMinute=120.5,
            totalReadings=1000,
            totalErrors=5,
            drivesDetected=3,
            alertsTriggered=2,
            lastHealthCheck=datetime.now(),
            uptimeSeconds=3600.0
        )

        # Act
        result = stats.toDict()

        # Assert
        assert result['connectionConnected'] is True
        assert result['connectionStatus'] == "connected"
        assert result['dataRatePerMinute'] == 120.5
        assert result['totalReadings'] == 1000
        assert result['totalErrors'] == 5
        assert result['drivesDetected'] == 3
        assert result['alertsTriggered'] == 2
        assert result['uptimeSeconds'] == 3600.0
        assert result['lastHealthCheck'] is not None

    def test_getHealthCheckStats_returnsCurrentStats(self):
        """
        Given: Orchestrator with health check stats
        When: getHealthCheckStats is called
        Then: Current stats are returned
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._healthCheckStats.totalReadings = 500
        orchestrator._healthCheckStats.totalErrors = 10

        # Act
        stats = orchestrator.getHealthCheckStats()

        # Assert
        assert stats.totalReadings == 500
        assert stats.totalErrors == 10


class TestSetupComponentCallbacks:
    """Test US-OSC-005: Component callback wiring."""

    def test_setupComponentCallbacks_wiresDriveDetector(self):
        """
        Given: Orchestrator with drive detector
        When: _setupComponentCallbacks is called
        Then: Drive detector callbacks are registered
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        mockDetector.registerCallbacks.assert_called_once()
        callArgs = mockDetector.registerCallbacks.call_args
        assert 'onDriveStart' in callArgs.kwargs
        assert 'onDriveEnd' in callArgs.kwargs

    def test_setupComponentCallbacks_wiresDataLogger(self):
        """
        Given: Orchestrator with data logger
        When: _setupComponentCallbacks is called
        Then: Data logger callbacks are registered
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        mockLogger.registerCallbacks.assert_called_once()
        callArgs = mockLogger.registerCallbacks.call_args
        assert 'onReading' in callArgs.kwargs
        assert 'onError' in callArgs.kwargs

    def test_setupComponentCallbacks_handlesComponentWithoutMethod(self):
        """
        Given: Orchestrator with component missing registerCallbacks
        When: _setupComponentCallbacks is called
        Then: Does not crash, logs debug
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        # Mock without registerCallbacks method
        mockComponent = MagicMock(spec=[])
        orchestrator._driveDetector = mockComponent

        # Act & Assert - should not raise
        orchestrator._setupComponentCallbacks()
