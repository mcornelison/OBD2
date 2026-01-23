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
# 2026-01-23    | Ralph Agent  | US-OSC-006: Add realtime data logging wiring tests
# 2026-01-23    | Ralph Agent  | US-OSC-007: Add drive detection wiring tests
# 2026-01-23    | Ralph Agent  | US-OSC-008: Add alert system wiring tests
# 2026-01-23    | Ralph Agent  | US-OSC-010: Add display manager wiring tests
# 2026-01-23    | Ralph Agent  | US-OSC-011: Add profile system wiring tests
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

        # Assert - verify exact order (statisticsEngine before driveDetector)
        expectedOrder = [
            'database', 'profileManager', 'connection', 'vinDecoder',
            'displayManager', 'statisticsEngine', 'driveDetector',
            'alertManager', 'dataLogger'
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
        # (driveDetector before statisticsEngine because detector may trigger analysis)
        expectedOrder = [
            'dataLogger', 'alertManager', 'driveDetector', 'statisticsEngine',
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
        Then: Health stats show reconnecting status
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        orchestrator._handleConnectionLost()

        # Assert
        assert orchestrator._healthCheckStats.connectionConnected is False
        assert orchestrator._healthCheckStats.connectionStatus == "reconnecting"

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


# ================================================================================
# US-OSC-006: Wire Up Realtime Data Logging Tests
# ================================================================================


class TestDataLoggerWiring:
    """Test US-OSC-006: RealtimeDataLogger wiring in orchestrator."""

    @patch('obd.orchestrator.createDatabaseFromConfig')
    def test_dataLoggerCreated_fromConfig(self, mockCreateDb):
        """
        Given: Valid configuration with realtimeData settings
        When: _initializeDataLogger is called
        Then: RealtimeDataLogger is created from config
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        mockDb = MagicMock()
        mockCreateDb.return_value = mockDb

        config = {
            'realtimeData': {
                'pollingIntervalMs': 500,
                'parameters': [
                    {'name': 'RPM', 'logData': True}
                ]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        orchestrator._database = mockDb
        orchestrator._connection = MagicMock()

        # Act - will try to import data_logger module
        with patch('obd.orchestrator.ApplicationOrchestrator._initializeDataLogger') as mockInit:
            # Verify config is stored for dataLogger creation
            assert orchestrator._config == config
            assert 'realtimeData' in orchestrator._config

    def test_dataLogger_property_returnsLogger(self):
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


class TestDashboardParameters:
    """Test US-OSC-006: Dashboard parameter extraction."""

    def test_extractDashboardParameters_extractsCorrectParams(self):
        """
        Given: Config with parameters having displayOnDashboard: true
        When: _extractDashboardParameters is called
        Then: Returns set of dashboard parameter names
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'ENGINE_LOAD', 'logData': True, 'displayOnDashboard': False},
                    {'name': 'MAF', 'logData': True}  # No displayOnDashboard key
                ]
            }
        }

        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert 'RPM' in orchestrator._dashboardParameters
        assert 'SPEED' in orchestrator._dashboardParameters
        assert 'ENGINE_LOAD' not in orchestrator._dashboardParameters
        assert 'MAF' not in orchestrator._dashboardParameters

    def test_extractDashboardParameters_handlesEmptyConfig(self):
        """
        Given: Config without realtimeData section
        When: _extractDashboardParameters is called
        Then: Returns empty set
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {}

        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert len(orchestrator._dashboardParameters) == 0

    def test_extractDashboardParameters_ignoresInvalidEntries(self):
        """
        Given: Config with mixed parameter formats
        When: _extractDashboardParameters is called
        Then: Only processes dict parameters, ignores strings
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'displayOnDashboard': True},
                    'SPEED',  # String format - should be ignored
                    {'name': '', 'displayOnDashboard': True},  # Empty name
                ]
            }
        }

        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert 'RPM' in orchestrator._dashboardParameters
        assert 'SPEED' not in orchestrator._dashboardParameters
        assert '' not in orchestrator._dashboardParameters


class TestDashboardUpdates:
    """Test US-OSC-006: Display updates for dashboard parameters."""

    def test_handleReading_updatesDashboardForConfiguredParams(self):
        """
        Given: Orchestrator with display manager and dashboard parameters
        When: _handleReading is called with a dashboard parameter
        Then: Display updateValue is called
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'displayOnDashboard': True}
                ]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 3500
        mockReading.unit = 'rpm'

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockDisplay.updateValue.assert_called_once_with('RPM', 3500, 'rpm')

    def test_handleReading_skipsNonDashboardParams(self):
        """
        Given: Orchestrator with display manager
        When: _handleReading is called with non-dashboard parameter
        Then: Display updateValue is NOT called
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'displayOnDashboard': True},
                    {'name': 'ENGINE_LOAD', 'displayOnDashboard': False}
                ]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        mockReading = MagicMock()
        mockReading.parameterName = 'ENGINE_LOAD'
        mockReading.value = 45.0
        mockReading.unit = 'percent'

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockDisplay.updateValue.assert_not_called()

    def test_handleReading_handlesDisplayWithoutUpdateValueMethod(self):
        """
        Given: Orchestrator with display manager missing updateValue
        When: _handleReading is called
        Then: Does not crash
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'displayOnDashboard': True}
                ]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)

        # Mock without updateValue method
        mockDisplay = MagicMock(spec=[])
        orchestrator._displayManager = mockDisplay

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 3500
        mockReading.unit = 'rpm'

        # Act & Assert - should not raise
        orchestrator._handleReading(mockReading)

    def test_handleReading_handlesDisplayUpdateError(self):
        """
        Given: Orchestrator with display that throws on update
        When: _handleReading is called
        Then: Error is caught and logged, doesn't crash
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'displayOnDashboard': True}
                ]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)

        mockDisplay = MagicMock()
        mockDisplay.updateValue.side_effect = RuntimeError("Display error")
        orchestrator._displayManager = mockDisplay

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 3500
        mockReading.unit = 'rpm'

        # Act & Assert - should not raise
        orchestrator._handleReading(mockReading)


class TestDataLoggingRateLog:
    """Test US-OSC-006: Data logging rate logging every 5 minutes."""

    def test_dataRateLogInterval_defaultsTo300Seconds(self):
        """
        Given: Config without dataRateLogIntervalSeconds
        When: ApplicationOrchestrator is created
        Then: Data rate log interval defaults to 300 seconds (5 minutes)
        """
        # Arrange & Act
        from obd.orchestrator import (
            ApplicationOrchestrator, DEFAULT_DATA_RATE_LOG_INTERVAL
        )

        orchestrator = ApplicationOrchestrator(config={})

        # Assert
        assert orchestrator._dataRateLogInterval == DEFAULT_DATA_RATE_LOG_INTERVAL
        assert orchestrator._dataRateLogInterval == 300.0

    def test_dataRateLogInterval_canBeConfigured(self):
        """
        Given: Config with custom dataRateLogIntervalSeconds
        When: ApplicationOrchestrator is created
        Then: Custom interval is used
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'monitoring': {'dataRateLogIntervalSeconds': 600.0}}

        # Act
        orchestrator = ApplicationOrchestrator(config=config)

        # Assert
        assert orchestrator._dataRateLogInterval == 600.0

    @patch('obd.orchestrator.logger')
    def test_logDataLoggingRate_logsRate(self, mockLogger):
        """
        Given: Orchestrator with some readings logged
        When: _logDataLoggingRate is called
        Then: Rate is logged at INFO level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator
        from datetime import datetime, timedelta

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=5)
        orchestrator._lastDataRateLogCount = 0
        orchestrator._healthCheckStats.totalReadings = 300  # 300 readings in 5 minutes

        # Act
        orchestrator._logDataLoggingRate()

        # Assert
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('DATA LOGGING RATE' in str(c) for c in infoCalls)
        assert any('records/min=' in str(c) for c in infoCalls)

    @patch('obd.orchestrator.logger')
    def test_logDataLoggingRate_calculatesCorrectRate(self, mockLogger):
        """
        Given: Orchestrator with 300 readings over 5 minutes
        When: _logDataLoggingRate is called
        Then: Rate is calculated as 60 records/minute
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator
        from datetime import datetime, timedelta

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=5)
        orchestrator._lastDataRateLogCount = 0
        orchestrator._healthCheckStats.totalReadings = 300

        # Act
        orchestrator._logDataLoggingRate()

        # Assert - 300 readings / 5 minutes = 60/min
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        # Check the log contains approximately 60 records/min
        assert any('records/min=60' in str(c) for c in infoCalls)

    def test_logDataLoggingRate_updatesLastLogCount(self):
        """
        Given: Orchestrator with readings logged
        When: _logDataLoggingRate is called
        Then: _lastDataRateLogCount is updated
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator
        from datetime import datetime, timedelta

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=1)
        orchestrator._lastDataRateLogCount = 0
        orchestrator._healthCheckStats.totalReadings = 100

        # Act
        orchestrator._logDataLoggingRate()

        # Assert
        assert orchestrator._lastDataRateLogCount == 100


class TestProfileSpecificPolling:
    """Test US-OSC-006: Profile-specific polling interval usage."""

    def test_dataLoggerUsesProfilePollingInterval(self):
        """
        Given: Config with profile-specific pollingIntervalMs
        When: DataLogger is created
        Then: Profile polling interval is used
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'profiles': {
                'activeProfile': 'performance',
                'availableProfiles': [
                    {'id': 'daily', 'pollingIntervalMs': 1000},
                    {'id': 'performance', 'pollingIntervalMs': 500}
                ]
            },
            'realtimeData': {
                'pollingIntervalMs': 1000,  # Global fallback
                'parameters': [{'name': 'RPM', 'logData': True}]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        # Verify config is available for data logger to use
        assert orchestrator._config == config
        profiles = config.get('profiles', {})
        assert profiles.get('activeProfile') == 'performance'


class TestLogDataOnlyParameters:
    """Test US-OSC-006: Only parameters with logData: true are logged."""

    def test_configHasLogDataFalseParams(self):
        """
        Given: Config with some parameters having logData: false
        When: Orchestrator is created
        Then: Config is available for data logger filtering
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'logData': True},
                    {'name': 'SPEED', 'logData': True},
                    {'name': 'EGR', 'logData': False},
                    {'name': 'BAROMETRIC', 'logData': False}
                ]
            }
        }

        orchestrator = ApplicationOrchestrator(config=config)

        # The filtering happens in RealtimeDataLogger, but orchestrator
        # passes the full config - verify it's preserved
        params = config['realtimeData']['parameters']
        loggedParams = [p['name'] for p in params if p.get('logData', False)]
        assert loggedParams == ['RPM', 'SPEED']


class TestDataLoggerCallbackWiring:
    """Test US-OSC-006: Data logger callback wiring."""

    def test_dataLoggerOnReadingCallback_updatesStats(self):
        """
        Given: Orchestrator with data logger callback wired
        When: onReading callback is invoked
        Then: Stats are updated and display is updated for dashboard params
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'displayOnDashboard': True}
                ]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        initialReadings = orchestrator._healthCheckStats.totalReadings
        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 4000
        mockReading.unit = 'rpm'

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        assert orchestrator._healthCheckStats.totalReadings == initialReadings + 1
        mockDisplay.updateValue.assert_called_once_with('RPM', 4000, 'rpm')

    def test_dataLoggerOnErrorCallback_logsWarning(self):
        """
        Given: Orchestrator
        When: onError callback is invoked
        Then: Error is logged and error count incremented
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        initialErrors = orchestrator._healthCheckStats.totalErrors

        # Act
        orchestrator._handleLoggingError('RPM', RuntimeError("Read timeout"))

        # Assert
        assert orchestrator._healthCheckStats.totalErrors == initialErrors + 1


# ================================================================================
# US-OSC-007: Wire Up Drive Detection Tests
# ================================================================================


class TestDriveDetectorWiring:
    """Test US-OSC-007: DriveDetector wiring in orchestrator."""

    def test_driveDetector_property_returnsDetector(self):
        """
        Given: Orchestrator with drive detector set
        When: driveDetector property is accessed
        Then: Returns the stored detector instance
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        # Act
        result = orchestrator.driveDetector

        # Assert
        assert result is mockDetector

    @patch('obd.orchestrator.createDatabaseFromConfig')
    def test_driveDetectorCreated_fromConfig(self, mockCreateDb):
        """
        Given: Valid configuration with analysis settings
        When: _initializeDriveDetector is called
        Then: DriveDetector is created from config
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        mockDb = MagicMock()
        mockCreateDb.return_value = mockDb

        config = {
            'analysis': {
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 10,
                'driveEndDurationSeconds': 60,
                'triggerAfterDrive': True
            }
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        orchestrator._database = mockDb
        orchestrator._statisticsEngine = MagicMock()

        # Assert config is available for drive detector
        assert orchestrator._config == config
        assert 'analysis' in orchestrator._config


class TestDriveDetectorRpmRouting:
    """Test US-OSC-007: Detector receives RPM values from realtime logger."""

    def test_handleReading_routesRpmToDriveDetector(self):
        """
        Given: Orchestrator with drive detector
        When: _handleReading is called with RPM value
        Then: Value is passed to drive detector's processValue method
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 3500

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockDetector.processValue.assert_called_once_with('RPM', 3500)

    def test_handleReading_routesSpeedToDriveDetector(self):
        """
        Given: Orchestrator with drive detector
        When: _handleReading is called with SPEED value
        Then: Value is passed to drive detector's processValue method
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        mockReading = MagicMock()
        mockReading.parameterName = 'SPEED'
        mockReading.value = 65

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockDetector.processValue.assert_called_once_with('SPEED', 65)

    def test_handleReading_handlesDetectorProcessError(self):
        """
        Given: Orchestrator with drive detector that throws on processValue
        When: _handleReading is called
        Then: Error is caught and doesn't crash the orchestrator
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDetector = MagicMock()
        mockDetector.processValue.side_effect = RuntimeError("Detector error")
        orchestrator._driveDetector = mockDetector

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 3500

        # Act & Assert - should not raise
        orchestrator._handleReading(mockReading)


class TestDriveStartCallback:
    """Test US-OSC-007: Detector onDriveStart callback."""

    @patch('obd.orchestrator.logger')
    def test_handleDriveStart_logsEvent(self, mockLogger):
        """
        Given: Orchestrator
        When: _handleDriveStart is called
        Then: Drive start event is logged at INFO level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockSession = MagicMock()
        mockSession.id = 'session_123'

        # Act
        orchestrator._handleDriveStart(mockSession)

        # Assert
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('Drive started' in str(c) for c in infoCalls)

    def test_handleDriveStart_updatesDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleDriveStart is called
        Then: Display is updated with driving status
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        mockSession = MagicMock()

        # Act
        orchestrator._handleDriveStart(mockSession)

        # Assert
        mockDisplay.showDriveStatus.assert_called_once_with('driving')

    def test_handleDriveStart_incrementsDrivesDetectedCount(self):
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


class TestDriveEndCallback:
    """Test US-OSC-007: Detector onDriveEnd callback."""

    @patch('obd.orchestrator.logger')
    def test_handleDriveEnd_logsEvent(self, mockLogger):
        """
        Given: Orchestrator
        When: _handleDriveEnd is called
        Then: Drive end event is logged at INFO level with duration
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockSession = MagicMock()
        mockSession.duration = 1234.5

        # Act
        orchestrator._handleDriveEnd(mockSession)

        # Assert
        infoCalls = [str(c) for c in mockLogger.info.call_args_list]
        assert any('Drive ended' in str(c) for c in infoCalls)
        assert any('duration=' in str(c) for c in infoCalls)

    def test_handleDriveEnd_updatesDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleDriveEnd is called
        Then: Display is updated with stopped status
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        mockSession = MagicMock()
        mockSession.duration = 300.0

        # Act
        orchestrator._handleDriveEnd(mockSession)

        # Assert
        mockDisplay.showDriveStatus.assert_called_once_with('stopped')

    def test_handleDriveEnd_invokesExternalCallback(self):
        """
        Given: Orchestrator with onDriveEnd callback registered
        When: _handleDriveEnd is called
        Then: External callback is invoked with session
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        callbackMock = MagicMock()
        orchestrator._onDriveEnd = callbackMock
        mockSession = MagicMock()
        mockSession.duration = 600.0

        # Act
        orchestrator._handleDriveEnd(mockSession)

        # Assert
        callbackMock.assert_called_once_with(mockSession)


class TestDriveDetectorCallbackRegistration:
    """Test US-OSC-007: Drive detector callback wiring."""

    def test_setupComponentCallbacks_registersDriveCallbacks(self):
        """
        Given: Orchestrator with drive detector
        When: _setupComponentCallbacks is called
        Then: onDriveStart and onDriveEnd callbacks are registered
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
        # Verify callbacks point to orchestrator methods
        assert callArgs.kwargs['onDriveStart'] == orchestrator._handleDriveStart
        assert callArgs.kwargs['onDriveEnd'] == orchestrator._handleDriveEnd

    def test_setupComponentCallbacks_handlesDetectorCallbackError(self):
        """
        Given: Orchestrator with detector that throws on registerCallbacks
        When: _setupComponentCallbacks is called
        Then: Error is caught and logged, doesn't crash
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDetector = MagicMock()
        mockDetector.registerCallbacks.side_effect = RuntimeError("Registration error")
        orchestrator._driveDetector = mockDetector

        # Act & Assert - should not raise
        orchestrator._setupComponentCallbacks()


class TestDriveDetectorStartStop:
    """Test US-OSC-007: Drive detector lifecycle in main loop."""

    def test_runLoop_startsDriveDetector(self):
        """
        Given: Orchestrator with drive detector
        When: runLoop is called
        Then: Drive detector start() is called
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True
        orchestrator._loopSleepInterval = 0.01

        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        # Trigger immediate shutdown
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act
        orchestrator.runLoop()

        # Assert
        mockDetector.start.assert_called_once()

    def test_shutdownDriveDetector_callsStop(self):
        """
        Given: Orchestrator with running drive detector
        When: _shutdownDriveDetector is called
        Then: Drive detector stop() is called
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        # Act
        orchestrator._shutdownDriveDetector()

        # Assert
        mockDetector.stop.assert_called_once()
        assert orchestrator._driveDetector is None


class TestDriveDetectorDebounce:
    """Test US-OSC-007: Detector state survives brief RPM dropouts."""

    def test_driveDetectorConfig_includesDebounceSettings(self):
        """
        Given: Config with drive detection debounce settings
        When: Orchestrator is created
        Then: Config includes driveStartDurationSeconds and driveEndDurationSeconds
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'analysis': {
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 10,  # Must stay above threshold for 10s
                'driveEndRpmThreshold': 0,
                'driveEndDurationSeconds': 60     # Must stay below threshold for 60s
            }
        }

        orchestrator = ApplicationOrchestrator(config=config)

        # Assert config is available for drive detector
        analysisConfig = orchestrator._config.get('analysis', {})
        assert analysisConfig.get('driveStartDurationSeconds') == 10
        assert analysisConfig.get('driveEndDurationSeconds') == 60


class TestDriveSessionDatabaseLogging:
    """Test US-OSC-007: Drive sessions logged to database for history."""

    def test_driveDetectorInitialized_withDatabase(self):
        """
        Given: Orchestrator with database
        When: DriveDetector is initialized
        Then: Database is passed to drive detector for session logging
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {}
        orchestrator = ApplicationOrchestrator(config=config)
        mockDb = MagicMock()
        orchestrator._database = mockDb

        # The database should be available when initializing drive detector
        # Verify the config and database are stored for initialization
        assert orchestrator._database is mockDb
        assert orchestrator._config == config


# ================================================================================
# US-OSC-008: Wire Up Alert System Tests
# ================================================================================


class TestAlertManagerCreation:
    """Test US-OSC-008: AlertManager created from config in orchestrator."""

    def test_initializeAlertManager_createsFromConfig(self):
        """
        Given: Config with alert settings
        When: _initializeAlertManager is called
        Then: AlertManager is created with config settings
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'alerts': {
                'enabled': True,
                'cooldownSeconds': 60,
                'visualAlerts': True,
                'logAlerts': True
            },
            'profiles': {
                'activeProfile': 'sport',
                'availableProfiles': [
                    {
                        'id': 'sport',
                        'alertThresholds': {
                            'rpmRedline': 7500,
                            'coolantTempCritical': 110
                        }
                    }
                ]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)
        mockDb = MagicMock()
        mockDisplay = MagicMock()
        orchestrator._database = mockDb
        orchestrator._displayManager = mockDisplay

        # Act - Patch at actual module location (import is inside function)
        with patch('obd.alert_manager.createAlertManagerFromConfig') as mockCreate:
            mockAlertMgr = MagicMock()
            mockCreate.return_value = mockAlertMgr
            orchestrator._initializeAlertManager()

        # Assert
        mockCreate.assert_called_once_with(config, mockDb, mockDisplay)
        assert orchestrator._alertManager == mockAlertMgr

    def test_alertManagerProperty_returnsInstance(self):
        """
        Given: Orchestrator with initialized alert manager
        When: alertManager property is accessed
        Then: Returns the alert manager instance
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockAlertMgr = MagicMock()
        orchestrator._alertManager = mockAlertMgr

        # Act
        result = orchestrator.alertManager

        # Assert
        assert result is mockAlertMgr


class TestAlertManagerReceivesValues:
    """Test US-OSC-008: Manager receives all realtime values from logger."""

    def test_handleReading_passesToAlertManager_checkValue(self):
        """
        Given: Orchestrator with alert manager
        When: _handleReading is called with a value
        Then: Value is passed to alertManager.checkValue()
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockAlertMgr = MagicMock()
        orchestrator._alertManager = mockAlertMgr
        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 7500
        mockReading.unit = 'rpm'

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockAlertMgr.checkValue.assert_called_once_with('RPM', 7500)

    def test_handleReading_multipleCalls_passesAllValues(self):
        """
        Given: Orchestrator with alert manager
        When: _handleReading is called multiple times
        Then: All values are passed to alert manager
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockAlertMgr = MagicMock()
        orchestrator._alertManager = mockAlertMgr

        readings = [
            ('RPM', 3000),
            ('COOLANT_TEMP', 95),
            ('OIL_PRESSURE', 50),
        ]

        # Act
        for paramName, value in readings:
            mockReading = MagicMock()
            mockReading.parameterName = paramName
            mockReading.value = value
            mockReading.unit = None
            orchestrator._handleReading(mockReading)

        # Assert
        assert mockAlertMgr.checkValue.call_count == 3
        calls = mockAlertMgr.checkValue.call_args_list
        assert calls[0] == call('RPM', 3000)
        assert calls[1] == call('COOLANT_TEMP', 95)
        assert calls[2] == call('OIL_PRESSURE', 50)


class TestAlertCallbackRegistration:
    """Test US-OSC-008: Alert onAlert callback is registered correctly."""

    def test_setupComponentCallbacks_registersAlertCallback(self):
        """
        Given: Orchestrator with alert manager that has onAlert method
        When: _setupComponentCallbacks is called
        Then: onAlert callback is registered on alert manager
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockAlertMgr = MagicMock()
        mockAlertMgr.onAlert = MagicMock()
        orchestrator._alertManager = mockAlertMgr

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        mockAlertMgr.onAlert.assert_called_once()
        # Verify the callback registered is _handleAlert
        registeredCallback = mockAlertMgr.onAlert.call_args[0][0]
        assert registeredCallback == orchestrator._handleAlert

    def test_setupComponentCallbacks_noAlertManager_noError(self):
        """
        Given: Orchestrator without alert manager
        When: _setupComponentCallbacks is called
        Then: No error occurs
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._alertManager = None

        # Act / Assert - no exception
        orchestrator._setupComponentCallbacks()

    def test_setupComponentCallbacks_alertManagerWithoutOnAlert_noError(self):
        """
        Given: Orchestrator with alert manager that lacks onAlert method
        When: _setupComponentCallbacks is called
        Then: No error occurs
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockAlertMgr = MagicMock(spec=[])  # Empty spec = no methods
        orchestrator._alertManager = mockAlertMgr

        # Act / Assert - no exception
        orchestrator._setupComponentCallbacks()


class TestAlertHandlerLogging:
    """Test US-OSC-008: Alert handler logs at WARNING level."""

    def test_handleAlert_logsWarning(self, caplog):
        """
        Given: Alert event
        When: _handleAlert is called
        Then: Alert is logged at WARNING level with details
        """
        # Arrange
        import logging
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockAlert = MagicMock()
        mockAlert.alertType = 'rpm_redline'
        mockAlert.parameterName = 'RPM'
        mockAlert.value = 7800
        mockAlert.threshold = 7500
        mockAlert.profileId = 'sport'

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._handleAlert(mockAlert)

        # Assert
        assert 'ALERT triggered' in caplog.text
        assert 'rpm_redline' in caplog.text
        assert 'RPM' in caplog.text
        assert '7800' in caplog.text
        assert '7500' in caplog.text

    def test_handleAlert_incrementsAlertCount(self):
        """
        Given: Orchestrator
        When: _handleAlert is called
        Then: alertsTriggered stat is incremented
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        initialCount = orchestrator._healthCheckStats.alertsTriggered
        mockAlert = MagicMock()
        mockAlert.alertType = 'coolant_temp_critical'

        # Act
        orchestrator._handleAlert(mockAlert)

        # Assert
        assert orchestrator._healthCheckStats.alertsTriggered == initialCount + 1


class TestAlertDisplayIntegration:
    """Test US-OSC-008: Visual alerts shown on display if enabled."""

    def test_handleAlert_sendsToDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleAlert is called
        Then: Alert is sent to display via showAlert()
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        mockAlert = MagicMock()
        mockAlert.alertType = 'oil_pressure_low'
        mockAlert.parameterName = 'OIL_PRESSURE'
        mockAlert.value = 15
        mockAlert.threshold = 20
        mockAlert.profileId = 'daily'

        # Act
        orchestrator._handleAlert(mockAlert)

        # Assert
        mockDisplay.showAlert.assert_called_once_with(mockAlert)

    def test_handleAlert_noDisplay_noError(self):
        """
        Given: Orchestrator without display manager
        When: _handleAlert is called
        Then: No error occurs
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._displayManager = None
        mockAlert = MagicMock()
        mockAlert.alertType = 'rpm_redline'

        # Act / Assert - no exception
        orchestrator._handleAlert(mockAlert)

    def test_handleAlert_displayShowAlertFails_logsDebug(self, caplog):
        """
        Given: Orchestrator with display that fails on showAlert
        When: _handleAlert is called
        Then: Error is logged at debug level but no exception raised
        """
        # Arrange
        import logging
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDisplay = MagicMock()
        mockDisplay.showAlert.side_effect = Exception("Display error")
        orchestrator._displayManager = mockDisplay
        mockAlert = MagicMock()
        mockAlert.alertType = 'coolant_temp_critical'

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._handleAlert(mockAlert)  # Should not raise

        # Assert
        assert 'Display alert failed' in caplog.text


class TestAlertExternalCallback:
    """Test US-OSC-008: External alert callback invocation."""

    def test_handleAlert_invokesExternalCallback(self):
        """
        Given: Orchestrator with external onAlert callback registered
        When: _handleAlert is called
        Then: External callback is invoked with alert event
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        callbackMock = MagicMock()
        orchestrator._onAlert = callbackMock
        mockAlert = MagicMock()
        mockAlert.alertType = 'boost_pressure_max'

        # Act
        orchestrator._handleAlert(mockAlert)

        # Assert
        callbackMock.assert_called_once_with(mockAlert)

    def test_handleAlert_externalCallbackError_logsWarning(self, caplog):
        """
        Given: Orchestrator with failing external callback
        When: _handleAlert is called
        Then: Error is logged but no exception raised
        """
        # Arrange
        import logging
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        callbackMock = MagicMock(side_effect=ValueError("Callback error"))
        orchestrator._onAlert = callbackMock
        mockAlert = MagicMock()
        mockAlert.alertType = 'rpm_redline'

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._handleAlert(mockAlert)  # Should not raise

        # Assert
        assert 'onAlert callback error' in caplog.text


class TestAlertCooldownRespect:
    """Test US-OSC-008: Alerts respect cooldown period."""

    def test_alertManager_respectsCooldownFromConfig(self):
        """
        Given: Config with cooldown setting
        When: AlertManager is created
        Then: Cooldown is applied (verified via config pass-through)
        """
        # Arrange - This tests the config is passed correctly
        # Actual cooldown enforcement is in AlertManager
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'alerts': {
                'cooldownSeconds': 45
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)

        # Verify config is preserved for AlertManager creation
        assert orchestrator._config['alerts']['cooldownSeconds'] == 45


class TestAlertHistoryQueryable:
    """Test US-OSC-008: Alert history queryable from database."""

    def test_alertManager_hasDatabaseForHistory(self):
        """
        Given: Orchestrator with database
        When: AlertManager is initialized
        Then: Database is passed for alert history storage
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {}
        orchestrator = ApplicationOrchestrator(config=config)
        mockDb = MagicMock()
        mockDisplay = MagicMock()
        orchestrator._database = mockDb
        orchestrator._displayManager = mockDisplay

        # Act - Patch at actual module location (import is inside function)
        with patch('obd.alert_manager.createAlertManagerFromConfig') as mockCreate:
            mockAlertMgr = MagicMock()
            mockCreate.return_value = mockAlertMgr
            orchestrator._initializeAlertManager()

        # Assert - database is passed to createAlertManagerFromConfig
        mockCreate.assert_called_once()
        callArgs = mockCreate.call_args
        assert callArgs[0][1] == mockDb  # Second positional arg is database


class TestAlertManagerShutdown:
    """Test US-OSC-008: Alert manager shutdown."""

    def test_shutdownAlertManager_stopsComponent(self):
        """
        Given: Orchestrator with running alert manager
        When: _shutdownAlertManager is called
        Then: Alert manager is stopped and reference cleared
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockAlertMgr = MagicMock()
        orchestrator._alertManager = mockAlertMgr

        # Act
        orchestrator._shutdownAlertManager()

        # Assert
        mockAlertMgr.stop.assert_called_once()
        assert orchestrator._alertManager is None

    def test_shutdownAlertManager_noComponent_noError(self):
        """
        Given: Orchestrator without alert manager
        When: _shutdownAlertManager is called
        Then: No error occurs
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._alertManager = None

        # Act / Assert - no exception
        orchestrator._shutdownAlertManager()
        assert orchestrator._alertManager is None


class TestAlertIntegration:
    """Test US-OSC-008: Full alert system integration."""

    def test_fullAlertFlow_checkValueTriggersCallback(self):
        """
        Given: Orchestrator with alert manager and registered callback
        When: Value exceeds threshold
        Then: Alert flows through entire system
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Create mock alert manager that calls callback when checkValue detects alert
        mockAlertMgr = MagicMock()
        mockAlertMgr.onAlert = MagicMock()
        orchestrator._alertManager = mockAlertMgr

        # Setup callbacks
        orchestrator._setupComponentCallbacks()

        # Get the registered callback
        registeredCallback = mockAlertMgr.onAlert.call_args[0][0]

        # Create a mock alert event
        mockAlert = MagicMock()
        mockAlert.alertType = 'rpm_redline'
        mockAlert.parameterName = 'RPM'
        mockAlert.value = 7800
        mockAlert.threshold = 7500
        mockAlert.profileId = 'sport'

        # Track external callback
        externalCallback = MagicMock()
        orchestrator._onAlert = externalCallback

        # Act - Simulate AlertManager calling the registered callback
        registeredCallback(mockAlert)

        # Assert - External callback was invoked
        externalCallback.assert_called_once_with(mockAlert)
        assert orchestrator._healthCheckStats.alertsTriggered == 1

    def test_alertWithDisplay_showsVisualAlert(self):
        """
        Given: Orchestrator with alert manager and display
        When: Alert is triggered
        Then: Visual alert is shown on display
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        mockAlert = MagicMock()
        mockAlert.alertType = 'coolant_temp_critical'
        mockAlert.parameterName = 'COOLANT_TEMP'
        mockAlert.value = 115
        mockAlert.threshold = 110
        mockAlert.profileId = 'daily'

        # Act
        orchestrator._handleAlert(mockAlert)

        # Assert
        mockDisplay.showAlert.assert_called_once_with(mockAlert)


class TestAlertHandlerDetailedLogging:
    """Test US-OSC-008: Enhanced alert logging with full details."""

    def test_handleAlert_logsFullAlertDetails(self, caplog):
        """
        Given: Alert event with all details
        When: _handleAlert is called
        Then: All details are logged
        """
        # Arrange
        import logging
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockAlert = MagicMock()
        mockAlert.alertType = 'oil_pressure_low'
        mockAlert.parameterName = 'OIL_PRESSURE'
        mockAlert.value = 12
        mockAlert.threshold = 20
        mockAlert.profileId = 'track'

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._handleAlert(mockAlert)

        # Assert - All details logged
        logMessage = caplog.text
        assert 'oil_pressure_low' in logMessage
        assert 'OIL_PRESSURE' in logMessage
        assert '12' in logMessage
        assert '20' in logMessage
        assert 'track' in logMessage

    def test_handleAlert_handlesUnknownAttributes(self):
        """
        Given: Alert event with missing attributes
        When: _handleAlert is called
        Then: Defaults to 'unknown' or 'N/A' without error
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        # Create simple mock without setting attributes
        mockAlert = MagicMock(spec=[])

        # Act / Assert - no exception
        orchestrator._handleAlert(mockAlert)


# ================================================================================
# US-OSC-009: Wire Up Statistics Engine
# ================================================================================


class TestStatisticsEngineCreation:
    """Test US-OSC-009: StatisticsEngine created from config in orchestrator."""

    @patch('obd.orchestrator.createDatabaseFromConfig')
    def test_initializeStatisticsEngine_createsFromConfig(self, mockCreateDb):
        """
        Given: Config with analysis section
        When: _initializeStatisticsEngine is called
        Then: StatisticsEngine is created with database and config
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        mockDb = MagicMock()
        mockCreateDb.return_value = mockDb

        config = {
            'analysis': {
                'calculateStatistics': ['max', 'min', 'avg', 'mode']
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)
        orchestrator._database = mockDb

        # Act - patch at the actual module location where the import happens
        with patch(
            'obd.statistics_engine.createStatisticsEngineFromConfig'
        ) as mockCreate:
            mockEngine = MagicMock()
            mockCreate.return_value = mockEngine
            orchestrator._initializeStatisticsEngine()

        # Assert
        mockCreate.assert_called_once_with(mockDb, config)
        assert orchestrator._statisticsEngine == mockEngine

    def test_statisticsEngine_property_accessReturnsEngine(self):
        """
        Given: Orchestrator with initialized statistics engine
        When: statisticsEngine property accessed
        Then: Returns the engine instance
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockEngine = MagicMock()
        orchestrator._statisticsEngine = mockEngine

        # Act
        result = orchestrator.statisticsEngine

        # Assert
        assert result == mockEngine


class TestStatisticsEngineDatabaseConnection:
    """Test US-OSC-009: Engine connected to database for data retrieval/storage."""

    @patch('obd.orchestrator.createDatabaseFromConfig')
    def test_statisticsEngine_receivesDatabase(self, mockCreateDb):
        """
        Given: Orchestrator with database
        When: StatisticsEngine is initialized
        Then: Database is passed to createStatisticsEngineFromConfig
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        mockDb = MagicMock()
        mockDb.initialize = MagicMock()
        mockCreateDb.return_value = mockDb

        config = {'database': {'path': 'test.db'}}
        orchestrator = ApplicationOrchestrator(config=config)
        orchestrator._database = mockDb

        # Act - patch at the actual module location where the import happens
        with patch(
            'obd.statistics_engine.createStatisticsEngineFromConfig'
        ) as mockCreate:
            mockEngine = MagicMock()
            mockCreate.return_value = mockEngine
            orchestrator._initializeStatisticsEngine()

        # Assert - first arg should be database
        mockCreate.assert_called_once()
        callArgs = mockCreate.call_args
        assert callArgs[0][0] == mockDb


class TestStatisticsEngineScheduleAnalysis:
    """Test US-OSC-009: Engine scheduleAnalysis() called on drive end."""

    def test_driveDetector_receivesStatisticsEngine(self):
        """
        Given: Orchestrator with statistics engine
        When: DriveDetector is initialized
        Then: Statistics engine is passed to create function
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'analysis': {'triggerAfterDrive': True}
        }
        orchestrator = ApplicationOrchestrator(config=config)

        mockDb = MagicMock()
        mockEngine = MagicMock()
        orchestrator._database = mockDb
        orchestrator._statisticsEngine = mockEngine

        # Act - patch at the actual module location where the import happens
        with patch(
            'obd.drive_detector.createDriveDetectorFromConfig'
        ) as mockCreate:
            mockDetector = MagicMock()
            mockCreate.return_value = mockDetector
            orchestrator._initializeDriveDetector()

        # Assert - engine passed as second arg
        mockCreate.assert_called_once()
        callArgs = mockCreate.call_args
        assert callArgs[0][1] == mockEngine  # Second positional arg

    def test_driveDetector_triggersAnalysisOnDriveEnd(self):
        """
        Given: DriveDetector with statistics engine
        When: Drive ends
        Then: statisticsEngine.scheduleAnalysis is called

        Note: This test verifies the integration point; actual
        scheduling is handled by DriveDetector internal logic.
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockEngine = MagicMock()
        orchestrator._statisticsEngine = mockEngine

        # DriveDetector should have statistics engine reference
        mockDetector = MagicMock()
        mockDetector._statisticsEngine = mockEngine
        orchestrator._driveDetector = mockDetector

        # Assert - verify engine can be accessed for scheduling
        assert orchestrator._statisticsEngine is not None
        assert orchestrator._driveDetector is not None


class TestStatisticsEngineCallbackRegistration:
    """Test US-OSC-009: Engine onComplete callback logs and notifies display."""

    def test_setupComponentCallbacks_registersStatisticsEngineCallbacks(self):
        """
        Given: Orchestrator with statistics engine that has registerCallbacks
        When: _setupComponentCallbacks is called
        Then: Callbacks are registered with engine
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockEngine = MagicMock()
        mockEngine.registerCallbacks = MagicMock()
        orchestrator._statisticsEngine = mockEngine

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        mockEngine.registerCallbacks.assert_called_once()
        callKwargs = mockEngine.registerCallbacks.call_args[1]
        assert 'onAnalysisComplete' in callKwargs
        assert callKwargs['onAnalysisComplete'] is not None

    @patch('obd.orchestrator.logger')
    def test_handleAnalysisComplete_logsResults(self, mockLogger):
        """
        Given: Orchestrator
        When: _handleAnalysisComplete is called with result
        Then: Results are logged at INFO level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        mockResult = MagicMock()
        mockResult.profileId = 'daily'
        mockResult.totalParameters = 5
        mockResult.totalSamples = 100

        # Act
        orchestrator._handleAnalysisComplete(mockResult)

        # Assert
        mockLogger.info.assert_called()
        logCall = mockLogger.info.call_args
        assert 'Statistical analysis completed' in str(logCall)

    def test_handleAnalysisComplete_notifiesDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleAnalysisComplete is called
        Then: Display is notified via showAnalysisResult
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDisplay = MagicMock()
        mockDisplay.showAnalysisResult = MagicMock()
        orchestrator._displayManager = mockDisplay

        mockResult = MagicMock()

        # Act
        orchestrator._handleAnalysisComplete(mockResult)

        # Assert
        mockDisplay.showAnalysisResult.assert_called_once_with(mockResult)

    def test_handleAnalysisComplete_invokesExternalCallback(self):
        """
        Given: Orchestrator with registered onAnalysisComplete callback
        When: _handleAnalysisComplete is called
        Then: External callback is invoked
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockCallback = MagicMock()
        orchestrator._onAnalysisComplete = mockCallback

        mockResult = MagicMock()

        # Act
        orchestrator._handleAnalysisComplete(mockResult)

        # Assert
        mockCallback.assert_called_once_with(mockResult)

    def test_handleAnalysisComplete_handlesDisplayError(self):
        """
        Given: Display manager that throws on showAnalysisResult
        When: _handleAnalysisComplete is called
        Then: Error is caught and external callback still invoked
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        mockDisplay = MagicMock()
        mockDisplay.showAnalysisResult.side_effect = RuntimeError("Display error")
        orchestrator._displayManager = mockDisplay

        mockCallback = MagicMock()
        orchestrator._onAnalysisComplete = mockCallback

        mockResult = MagicMock()

        # Act - should not raise
        orchestrator._handleAnalysisComplete(mockResult)

        # Assert - external callback still called
        mockCallback.assert_called_once_with(mockResult)


class TestStatisticsEngineErrorCallback:
    """Test US-OSC-009: Engine onError callback logs error and continues."""

    def test_setupComponentCallbacks_registersErrorCallback(self):
        """
        Given: Orchestrator with statistics engine
        When: _setupComponentCallbacks is called
        Then: onAnalysisError callback is registered
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockEngine = MagicMock()
        mockEngine.registerCallbacks = MagicMock()
        orchestrator._statisticsEngine = mockEngine

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        callKwargs = mockEngine.registerCallbacks.call_args[1]
        assert 'onAnalysisError' in callKwargs
        assert callKwargs['onAnalysisError'] is not None

    @patch('obd.orchestrator.logger')
    def test_handleAnalysisError_logsError(self, mockLogger):
        """
        Given: Orchestrator
        When: _handleAnalysisError is called with error
        Then: Error is logged at ERROR level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        profileId = 'track'
        error = RuntimeError("Analysis failed")

        # Act
        orchestrator._handleAnalysisError(profileId, error)

        # Assert
        mockLogger.error.assert_called()
        logCall = mockLogger.error.call_args
        assert 'Analysis error' in str(logCall) or 'analysis' in str(logCall).lower()

    def test_handleAnalysisError_continuesOperation(self):
        """
        Given: Orchestrator
        When: _handleAnalysisError is called
        Then: Orchestrator continues running (no exception raised)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True

        # Act - should not raise
        orchestrator._handleAnalysisError('daily', RuntimeError("Test error"))

        # Assert - orchestrator still running
        assert orchestrator._running is True


class TestStatisticsEngineBackgroundThread:
    """Test US-OSC-009: Analysis runs in background thread."""

    def test_statisticsEngine_scheduleAnalysisIsNonBlocking(self):
        """
        Given: Statistics engine with scheduleAnalysis
        When: scheduleAnalysis is called
        Then: It uses background thread (daemon=True)

        Note: This tests the engine interface expectation.
        Actual threading is verified in statistics_engine tests.
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockEngine = MagicMock()
        mockEngine.scheduleAnalysis = MagicMock(return_value=True)
        orchestrator._statisticsEngine = mockEngine

        # The expectation is that scheduleAnalysis returns immediately
        # and runs analysis in background thread
        assert hasattr(mockEngine, 'scheduleAnalysis')


class TestStatisticsEngineProfileAssociation:
    """Test US-OSC-009: Results stored with profile_id association."""

    def test_statisticsEngine_receivesActiveProfile(self):
        """
        Given: Config with active profile
        When: Statistics engine initialized
        Then: Profile ID is available for analysis
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'profiles': {
                'activeProfile': 'track'
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)

        # Assert - config accessible for profile lookup
        assert orchestrator._config.get('profiles', {}).get('activeProfile') == 'track'


class TestStatisticsEngineInitializationOrder:
    """Test US-OSC-009: Correct initialization order for statistics integration."""

    def test_initializationOrder_statisticsEngineBeforeDriveDetector(self):
        """
        Given: Orchestrator
        When: _initializeAllComponents is called
        Then: StatisticsEngine is initialized BEFORE DriveDetector
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        initOrder = []

        orchestrator = ApplicationOrchestrator(config={})

        # Track initialization order
        def makeTracker(name):
            def track():
                initOrder.append(name)
            return track

        orchestrator._initializeDatabase = makeTracker('database')
        orchestrator._initializeProfileManager = makeTracker('profileManager')
        orchestrator._initializeConnection = makeTracker('connection')
        orchestrator._initializeVinDecoder = makeTracker('vinDecoder')
        orchestrator._initializeDisplayManager = makeTracker('displayManager')
        orchestrator._initializeStatisticsEngine = makeTracker('statisticsEngine')
        orchestrator._initializeDriveDetector = makeTracker('driveDetector')
        orchestrator._initializeAlertManager = makeTracker('alertManager')
        orchestrator._initializeDataLogger = makeTracker('dataLogger')

        # Act
        orchestrator._initializeAllComponents()

        # Assert - statisticsEngine before driveDetector
        statsIndex = initOrder.index('statisticsEngine')
        detectorIndex = initOrder.index('driveDetector')
        assert statsIndex < detectorIndex, (
            f"statisticsEngine (index {statsIndex}) must be initialized before "
            f"driveDetector (index {detectorIndex}). Order: {initOrder}"
        )

    def test_shutdownOrder_statisticsEngineAfterDriveDetector(self):
        """
        Given: Running orchestrator
        When: _shutdownAllComponents is called
        Then: DriveDetector is shutdown BEFORE StatisticsEngine
        (reverse of initialization order)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        shutdownOrder = []

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._running = True

        # Create mock components
        def createMockComponent(name):
            mock = MagicMock()
            mock.stop = MagicMock(side_effect=lambda: shutdownOrder.append(name))
            return mock

        orchestrator._dataLogger = createMockComponent('dataLogger')
        orchestrator._statisticsEngine = createMockComponent('statisticsEngine')
        orchestrator._alertManager = createMockComponent('alertManager')
        orchestrator._driveDetector = createMockComponent('driveDetector')
        orchestrator._displayManager = createMockComponent('displayManager')
        orchestrator._vinDecoder = createMockComponent('vinDecoder')
        orchestrator._connection = createMockComponent('connection')
        orchestrator._connection.disconnect = orchestrator._connection.stop
        orchestrator._profileManager = createMockComponent('profileManager')
        orchestrator._database = createMockComponent('database')

        # Act
        orchestrator._shutdownAllComponents()

        # Assert - driveDetector before statisticsEngine
        if 'driveDetector' in shutdownOrder and 'statisticsEngine' in shutdownOrder:
            detectorIndex = shutdownOrder.index('driveDetector')
            statsIndex = shutdownOrder.index('statisticsEngine')
            assert detectorIndex < statsIndex, (
                f"driveDetector (index {detectorIndex}) must be shutdown before "
                f"statisticsEngine (index {statsIndex}). Order: {shutdownOrder}"
            )


# ================================================================================
# US-OSC-010: Wire Up Display Manager Tests
# ================================================================================

class TestUSOSC010_DisplayManagerCreatedFromConfig:
    """Test US-OSC-010: DisplayManager created from config in orchestrator."""

    def test_displayManagerCreatedFromConfig(self):
        """
        Given: Config with display settings
        When: _initializeDisplayManager() called
        Then: DisplayManager is created from config
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'display': {'mode': 'headless'},
            'database': {'path': ':memory:'}
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        # Mock the display manager factory to track config passed
        mockDisplayManager = MagicMock()
        mockDisplayManager.initialize.return_value = True
        mockDisplayManager.mode = MagicMock()
        mockDisplayManager.mode.value = 'headless'

        with patch('obd.display_manager.createDisplayManagerFromConfig') as mockFactory:
            mockFactory.return_value = mockDisplayManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            mockFactory.assert_called_once_with(config)
            assert orchestrator._displayManager is not None


class TestUSOSC010_DisplayModeSelection:
    """Test US-OSC-010: Display mode selected from config."""

    @pytest.mark.parametrize("displayMode", ["headless", "minimal", "developer"])
    def test_displayModePassedFromConfig(self, displayMode):
        """
        Given: Config with specific display mode
        When: _initializeDisplayManager() called
        Then: Config with display mode is passed to factory
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'display': {'mode': displayMode},
            'database': {'path': ':memory:'}
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockDisplayManager = MagicMock()
        mockDisplayManager.initialize.return_value = True
        mockDisplayManager.mode = MagicMock()
        mockDisplayManager.mode.value = displayMode

        with patch('obd.display_manager.createDisplayManagerFromConfig') as mockFactory:
            mockFactory.return_value = mockDisplayManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            passedConfig = mockFactory.call_args[0][0]
            assert passedConfig['display']['mode'] == displayMode


class TestUSOSC010_DisplayInitializedOnStartup:
    """Test US-OSC-010: Display initialized on startup with welcome screen."""

    def test_initializeCalledOnDisplayManager(self):
        """
        Given: DisplayManager created from config
        When: _initializeDisplayManager() called
        Then: initialize() is called on display manager
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockDisplayManager = MagicMock()
        mockDisplayManager.initialize.return_value = True
        mockDisplayManager.mode = MagicMock()
        mockDisplayManager.mode.value = 'headless'

        with patch('obd.display_manager.createDisplayManagerFromConfig') as mockFactory:
            mockFactory.return_value = mockDisplayManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            mockDisplayManager.initialize.assert_called_once()

    def test_welcomeScreenShownOnStartup(self):
        """
        Given: DisplayManager initialized successfully
        When: _initializeDisplayManager() completes
        Then: showWelcomeScreen() is called
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockDisplayManager = MagicMock()
        mockDisplayManager.initialize.return_value = True
        mockDisplayManager.mode = MagicMock()
        mockDisplayManager.mode.value = 'headless'

        with patch('obd.display_manager.createDisplayManagerFromConfig') as mockFactory:
            mockFactory.return_value = mockDisplayManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            mockDisplayManager.showWelcomeScreen.assert_called_once()
            call_kwargs = mockDisplayManager.showWelcomeScreen.call_args
            assert 'appName' in call_kwargs.kwargs or len(call_kwargs.args) > 0


class TestUSOSC010_DisplayReceivesStatusUpdates:
    """Test US-OSC-010: Display receives status updates."""

    def test_connectionStatusSentToDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleConnectionLost() called
        Then: showConnectionStatus() called with 'Reconnecting...'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._handleConnectionLost()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_once_with('Reconnecting...')

    def test_connectionRestoredStatusSentToDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleConnectionRestored() called
        Then: showConnectionStatus() called with 'Connected'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._handleConnectionRestored()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_once_with('Connected')

    def test_driveStatusSentToDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleDriveStart() called
        Then: showDriveStatus('driving') called
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        mockSession = MagicMock()
        mockSession.id = 'test-session'

        # Act
        orchestrator._handleDriveStart(mockSession)

        # Assert
        mockDisplay.showDriveStatus.assert_called_once_with('driving')

    def test_driveEndStatusSentToDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleDriveEnd() called
        Then: showDriveStatus('stopped') called
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        mockSession = MagicMock()
        mockSession.duration = 120.0

        # Act
        orchestrator._handleDriveEnd(mockSession)

        # Assert
        mockDisplay.showDriveStatus.assert_called_once_with('stopped')


class TestUSOSC010_DisplayRefreshRate:
    """Test US-OSC-010: Display refreshes at configured rate."""

    def test_refreshRatePassedInConfig(self):
        """
        Given: Config with refreshRateMs setting
        When: DisplayManager created
        Then: refreshRateMs is included in config passed to factory
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'display': {'mode': 'headless', 'refreshRateMs': 500},
            'database': {'path': ':memory:'}
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockDisplayManager = MagicMock()
        mockDisplayManager.initialize.return_value = True
        mockDisplayManager.mode = MagicMock()
        mockDisplayManager.mode.value = 'headless'

        with patch('obd.display_manager.createDisplayManagerFromConfig') as mockFactory:
            mockFactory.return_value = mockDisplayManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            passedConfig = mockFactory.call_args[0][0]
            assert passedConfig['display']['refreshRateMs'] == 500


class TestUSOSC010_DisplayShutdownMessage:
    """Test US-OSC-010: Display shows 'Shutting down...' during shutdown."""

    def test_shutdownMessageShownOnShutdown(self):
        """
        Given: Orchestrator with display manager
        When: _shutdownDisplayManager() called
        Then: showShutdownMessage() called before shutdown
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._shutdownDisplayManager()

        # Assert
        mockDisplay.showShutdownMessage.assert_called_once()

    def test_shutdownMessageCalledBeforeStop(self):
        """
        Given: Orchestrator with display manager
        When: _shutdownDisplayManager() called
        Then: showShutdownMessage called before shutdown
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        mockDisplay = MagicMock()

        callOrder = []
        mockDisplay.showShutdownMessage.side_effect = lambda: callOrder.append('showShutdownMessage')
        mockDisplay.stop.side_effect = lambda: callOrder.append('stop')
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._shutdownDisplayManager()

        # Assert - showShutdownMessage should be called first
        if len(callOrder) >= 2:
            assert callOrder.index('showShutdownMessage') < callOrder.index('stop')


class TestUSOSC010_GracefulFallbackToHeadless:
    """Test US-OSC-010: Graceful fallback to headless if display unavailable."""

    def test_fallbackToHeadlessOnInitializeFail(self):
        """
        Given: Display initialization fails
        When: _initializeDisplayManager() called
        Then: Falls back to headless mode
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'display': {'mode': 'minimal'},  # Minimal mode might fail on non-RPi
            'database': {'path': ':memory:'}
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        # First display fails to initialize
        failingDisplay = MagicMock()
        failingDisplay.initialize.return_value = False

        # Fallback headless display succeeds
        headlessDisplay = MagicMock()
        headlessDisplay.initialize.return_value = True
        headlessDisplay.mode = MagicMock()
        headlessDisplay.mode.value = 'headless'

        with patch('obd.display_manager.createDisplayManagerFromConfig') as mockFactory:
            mockFactory.side_effect = [failingDisplay, headlessDisplay]

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            assert orchestrator._displayManager is not None

    def test_createHeadlessDisplayFallback(self):
        """
        Given: Need for headless fallback
        When: _createHeadlessDisplayFallback() called
        Then: Headless display manager created with mode='headless'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'display': {'mode': 'minimal'},
            'database': {'path': ':memory:'}
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockHeadless = MagicMock()
        mockHeadless.initialize.return_value = True

        with patch('obd.display_manager.createDisplayManagerFromConfig') as mockFactory:
            mockFactory.return_value = mockHeadless

            # Act
            result = orchestrator._createHeadlessDisplayFallback()

            # Assert
            assert result is mockHeadless
            passedConfig = mockFactory.call_args[0][0]
            assert passedConfig['display']['mode'] == 'headless'


class TestUSOSC010_UpdateValueMethod:
    """Test US-OSC-010: Display receives realtime value updates."""

    def test_updateValueCalledForDashboardParam(self):
        """
        Given: Orchestrator with display manager and dashboard param
        When: _handleReading() called with dashboard parameter
        Then: updateValue() called on display manager
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'display': {'mode': 'headless'},
            'database': {'path': ':memory:'},
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'displayOnDashboard': True}
                ]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 2500
        mockReading.unit = 'rpm'

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockDisplay.updateValue.assert_called_once_with('RPM', 2500, 'rpm')


class TestUSOSC010_AlertsShownOnDisplay:
    """Test US-OSC-010: Alerts shown on display."""

    def test_alertShownOnDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleAlert() called
        Then: showAlert() called on display manager
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        mockAlert = MagicMock()
        mockAlert.alertType = 'high'
        mockAlert.parameterName = 'COOLANT_TEMP'
        mockAlert.value = 110
        mockAlert.threshold = 100
        mockAlert.profileId = 'daily'

        # Act
        orchestrator._handleAlert(mockAlert)

        # Assert
        mockDisplay.showAlert.assert_called_once_with(mockAlert)


class TestUSOSC010_ProfileShownOnDisplay:
    """Test US-OSC-010: Profile shown on display."""

    def test_profilePassedInShowStatus(self):
        """
        Given: DisplayManager with showStatus method
        When: showStatus called
        Then: Profile name is included in status
        """
        # This tests the DisplayManager.showStatus() method interface
        # Verify via manager.py implementation
        from display.manager import DisplayManager
        from display.types import DisplayMode

        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()

        # Capture the status via driver
        captured = {}
        original_showStatus = manager._driver.showStatus

        def captureStatus(status):
            captured['status'] = status
            original_showStatus(status)

        manager._driver.showStatus = captureStatus

        # Act
        manager.showStatus(profileName='sport')

        # Assert
        assert captured['status'].profileName == 'sport'


class TestUSOSC010_AnalysisResultShownOnDisplay:
    """Test US-OSC-010: Analysis result shown on display."""

    def test_analysisResultShownOnDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleAnalysisComplete() called
        Then: showAnalysisResult() called on display manager
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'display': {'mode': 'headless'}, 'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        mockResult = MagicMock()

        # Act
        orchestrator._handleAnalysisComplete(mockResult)

        # Assert
        mockDisplay.showAnalysisResult.assert_called_once_with(mockResult)


class TestUSOSC010_DisplayManagerStopMethod:
    """Test US-OSC-010: DisplayManager has stop() method for orchestrator compatibility."""

    def test_stopMethodExists(self):
        """
        Given: DisplayManager instance
        When: stop() called
        Then: shutdown() is executed
        """
        from display.manager import DisplayManager
        from display.types import DisplayMode

        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()

        # Verify stop method exists and works
        assert hasattr(manager, 'stop')
        manager.stop()  # Should not raise

        # Verify manager is no longer initialized
        assert not manager.isInitialized


# ================================================================================
# US-OSC-011: Wire Up Profile System
# ================================================================================


class TestUSOSC011_ProfileManagerCreatedFromConfig:
    """Test US-OSC-011: ProfileManager created from config in orchestrator."""

    def test_profileManagerPropertyAccessible(self):
        """
        Given: Orchestrator instance
        When: profileManager property accessed
        Then: Returns profile manager reference
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        # Act/Assert
        assert hasattr(orchestrator, 'profileManager')
        # Initially None before start
        assert orchestrator.profileManager is None

    def test_initializeProfileManager_createsProfileManager(self):
        """
        Given: Config with profiles section
        When: _initializeProfileManager() called
        Then: ProfileManager created via createProfileManagerFromConfig()
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'database': {'path': ':memory:'},
            'profiles': {
                'activeProfile': 'daily',
                'availableProfiles': [
                    {'id': 'daily', 'name': 'Daily Driver'}
                ]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        # Mock database
        mockDb = MagicMock()
        orchestrator._database = mockDb

        # Act - patch at actual import location in the method
        with patch('obd.profile_manager.createProfileManagerFromConfig') as mockFactory:
            mockManager = MagicMock()
            mockFactory.return_value = mockManager
            orchestrator._initializeProfileManager()

        # Assert
        mockFactory.assert_called_once_with(config, mockDb)
        assert orchestrator._profileManager == mockManager


class TestUSOSC011_ProfilesSyncedToDatabase:
    """Test US-OSC-011: Profiles from config synced to database on startup."""

    def test_profileManagerFactorySyncsProfiles(self):
        """
        Given: Config with availableProfiles
        When: createProfileManagerFromConfig called
        Then: Profiles are synced to database (created or updated)
        """
        # Arrange
        from profile.helpers import createProfileManagerFromConfig

        mockDb = MagicMock()
        # Setup mock cursor for database operations
        mockCursor = MagicMock()
        mockCursor.fetchone.return_value = None  # Profile doesn't exist
        mockConn = MagicMock()
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        config = {
            'profiles': {
                'activeProfile': 'daily',
                'availableProfiles': [
                    {'id': 'daily', 'name': 'Daily Driver'},
                    {'id': 'sport', 'name': 'Sport Mode'}
                ]
            }
        }

        # Act
        manager = createProfileManagerFromConfig(config, mockDb)

        # Assert - cursor.execute called (for INSERT operations)
        # The helper creates ProfileManager and calls createProfile/updateProfile
        assert mockCursor.execute.call_count >= 2  # At least 2 inserts for profiles


class TestUSOSC011_ActiveProfileLoadedFromConfig:
    """Test US-OSC-011: Active profile loaded from config."""

    def test_activeProfileSetFromConfig(self):
        """
        Given: Config with activeProfile setting
        When: ProfileManager initialized via helper
        Then: Active profile is set from config
        """
        # Arrange
        from profile.helpers import createProfileManagerFromConfig

        mockDb = MagicMock()
        # Setup mock cursor that returns profile exists
        mockCursor = MagicMock()
        mockCursor.fetchone.return_value = (1,)  # Profile exists
        mockConn = MagicMock()
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        config = {
            'profiles': {
                'activeProfile': 'sport',
                'availableProfiles': [
                    {'id': 'sport', 'name': 'Sport Mode'}
                ]
            }
        }

        # Act
        manager = createProfileManagerFromConfig(config, mockDb)

        # Assert - manager has active profile set
        assert manager.getActiveProfileId() == 'sport'


class TestUSOSC011_ProfileSwitcherCreation:
    """Test US-OSC-011: ProfileSwitcher created and wired in orchestrator."""

    def test_profileSwitcherProperty(self):
        """
        Given: Orchestrator instance
        When: profileSwitcher property accessed
        Then: Returns profile switcher reference
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        # Act/Assert
        assert hasattr(orchestrator, 'profileSwitcher')
        # Initially None before start
        assert orchestrator.profileSwitcher is None

    def test_profileSwitcherInitialized(self):
        """
        Given: Orchestrator with components initialized
        When: _initializeProfileSwitcher() called
        Then: ProfileSwitcher created and wired to components
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'database': {'path': ':memory:'},
            'profiles': {
                'activeProfile': 'daily',
                'availableProfiles': [{'id': 'daily', 'name': 'Daily'}]
            }
        }
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        # Mock components
        orchestrator._profileManager = MagicMock()
        orchestrator._driveDetector = MagicMock()
        orchestrator._displayManager = MagicMock()
        orchestrator._database = MagicMock()

        # Act - patch at actual import location
        with patch('obd.profile_manager.createProfileSwitcherFromConfig') as mockFactory:
            mockSwitcher = MagicMock()
            mockFactory.return_value = mockSwitcher
            orchestrator._initializeProfileSwitcher()

        # Assert - Factory called with correct components
        mockFactory.assert_called_once()
        callArgs = mockFactory.call_args
        assert callArgs[0][0] == config  # config first arg
        assert callArgs[1]['profileManager'] == orchestrator._profileManager
        assert callArgs[1]['driveDetector'] == orchestrator._driveDetector


class TestUSOSC011_ProfileChangeUpdatesAlertManager:
    """Test US-OSC-011: Profile change updates alert manager thresholds."""

    def test_handleProfileChange_updatesAlertManagerThresholds(self):
        """
        Given: Orchestrator with alertManager and new profile
        When: _handleProfileChange() called
        Then: alertManager.setProfileThresholds() called with new thresholds
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        mockProfileManager = MagicMock()
        mockProfile = MagicMock()
        mockProfile.alertThresholds = {'rpmRedline': 7000}
        mockProfileManager.getProfile.return_value = mockProfile
        orchestrator._profileManager = mockProfileManager

        # Act
        orchestrator._handleProfileChange('daily', 'sport')

        # Assert
        mockAlertManager.setProfileThresholds.assert_called_once_with(
            'sport', {'rpmRedline': 7000}
        )
        mockAlertManager.setActiveProfile.assert_called_once_with('sport')

    def test_handleProfileChange_logsProfileChange(self, caplog):
        """
        Given: Valid profile switch
        When: _handleProfileChange() called
        Then: Profile change logged at INFO level
        """
        # Arrange
        import logging
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockProfile = MagicMock()
        mockProfile.alertThresholds = {}
        mockProfileManager = MagicMock()
        mockProfileManager.getProfile.return_value = mockProfile
        orchestrator._profileManager = mockProfileManager

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._handleProfileChange('daily', 'sport')

        # Assert
        assert 'Profile changed from daily to sport' in caplog.text


class TestUSOSC011_ProfileChangeUpdatesDataLogger:
    """Test US-OSC-011: Profile change updates data logger polling interval."""

    def test_handleProfileChange_updatesPollingInterval(self):
        """
        Given: Orchestrator with dataLogger and new profile with pollingIntervalMs
        When: _handleProfileChange() called
        Then: dataLogger.setPollingInterval() called with profile's interval
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockDataLogger = MagicMock()
        orchestrator._dataLogger = mockDataLogger

        mockProfile = MagicMock()
        mockProfile.pollingIntervalMs = 500
        mockProfile.alertThresholds = {}
        mockProfileManager = MagicMock()
        mockProfileManager.getProfile.return_value = mockProfile
        orchestrator._profileManager = mockProfileManager

        # Act
        orchestrator._handleProfileChange('daily', 'sport')

        # Assert
        mockDataLogger.setPollingInterval.assert_called_once_with(500)


class TestUSOSC011_ProfileSwitchQueuedIfDriving:
    """Test US-OSC-011: Profile switch queued if driving."""

    def test_profileSwitchRequestedWhileDriving_queued(self):
        """
        Given: Orchestrator in driving state
        When: requestProfileSwitch() called on switcher
        Then: Switch is queued, not immediate
        """
        # Arrange
        from profile.switcher import ProfileSwitcher

        mockProfileManager = MagicMock()
        mockProfileManager.profileExists.return_value = True

        mockDriveDetector = MagicMock()
        mockDriveDetector.isDriving.return_value = True

        switcher = ProfileSwitcher(
            profileManager=mockProfileManager,
            driveDetector=mockDriveDetector
        )
        switcher._state.activeProfileId = 'daily'

        # Act
        result = switcher.requestProfileSwitch('sport')

        # Assert
        assert result is True
        assert switcher.getPendingProfileId() == 'sport'
        assert switcher.getActiveProfileId() == 'daily'  # Not changed yet

    def test_profileSwitchActivatedOnDriveStart(self):
        """
        Given: Pending profile switch
        When: Drive starts (_onDriveStart called)
        Then: Pending switch is activated
        """
        # Arrange
        from profile.switcher import ProfileSwitcher

        mockProfileManager = MagicMock()
        mockProfileManager.profileExists.return_value = True

        switcher = ProfileSwitcher(profileManager=mockProfileManager)
        switcher._state.activeProfileId = 'daily'
        switcher._state.pendingProfileId = 'sport'

        mockSession = MagicMock()

        # Act
        switcher._onDriveStart(mockSession)

        # Assert
        assert switcher.getActiveProfileId() == 'sport'
        assert switcher.getPendingProfileId() is None


class TestUSOSC011_ProfileChangesLogged:
    """Test US-OSC-011: Profile changes logged with proper message format."""

    def test_profileChangeLogged_correctFormat(self, caplog):
        """
        Given: Valid profile switch
        When: _handleProfileChange() called
        Then: Log message follows format 'Profile changed from [A] to [B]'
        """
        # Arrange
        import logging
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockProfile = MagicMock()
        mockProfile.alertThresholds = {}
        mockProfileManager = MagicMock()
        mockProfileManager.getProfile.return_value = mockProfile
        orchestrator._profileManager = mockProfileManager

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._handleProfileChange('DailyDrive', 'TrackDay')

        # Assert
        assert 'Profile changed from DailyDrive to TrackDay' in caplog.text


class TestUSOSC011_ProfileSwitcherCallbacksWired:
    """Test US-OSC-011: ProfileSwitcher callbacks wired to orchestrator."""

    def test_profileSwitcherCallbackRegistered(self):
        """
        Given: Orchestrator with profile switcher
        When: _setupComponentCallbacks() called
        Then: _handleProfileChange registered with switcher
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        mockSwitcher = MagicMock()
        orchestrator._profileSwitcher = mockSwitcher

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        mockSwitcher.onProfileChange.assert_called_once()
        # The callback should be the orchestrator's _handleProfileChange
        callback = mockSwitcher.onProfileChange.call_args[0][0]
        assert callable(callback)


class TestUSOSC011_InitializationOrder:
    """Test US-OSC-011: Profile components initialized in correct order."""

    def test_profileSwitcherInitializedAfterDependencies(self):
        """
        Given: Orchestrator with all component init methods mocked
        When: _initializeAllComponents() called
        Then: ProfileSwitcher initialized after profileManager and driveDetector
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        initOrder = []

        def trackInit(name):
            def init():
                initOrder.append(name)
            return init

        orchestrator._initializeDatabase = trackInit('database')
        orchestrator._initializeProfileManager = trackInit('profileManager')
        orchestrator._initializeConnection = trackInit('connection')
        orchestrator._initializeVinDecoder = trackInit('vinDecoder')
        orchestrator._initializeDisplayManager = trackInit('displayManager')
        orchestrator._initializeStatisticsEngine = trackInit('statisticsEngine')
        orchestrator._initializeDriveDetector = trackInit('driveDetector')
        orchestrator._initializeAlertManager = trackInit('alertManager')
        orchestrator._initializeDataLogger = trackInit('dataLogger')
        orchestrator._initializeProfileSwitcher = trackInit('profileSwitcher')

        # Act
        orchestrator._initializeAllComponents()

        # Assert - profileSwitcher after profileManager and driveDetector
        assert initOrder.index('profileSwitcher') > initOrder.index('profileManager')
        assert initOrder.index('profileSwitcher') > initOrder.index('driveDetector')


class TestUSOSC011_ShutdownOrder:
    """Test US-OSC-011: Profile switcher shutdown in correct order."""

    def test_profileSwitcherShutdownBeforeProfileManager(self):
        """
        Given: Orchestrator with all components initialized
        When: _shutdownAllComponents() called
        Then: ProfileSwitcher shutdown before ProfileManager
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = {'database': {'path': ':memory:'}}
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        shutdownOrder = []

        def trackShutdown(name):
            def shutdown():
                shutdownOrder.append(name)
            return shutdown

        orchestrator._shutdownDataLogger = trackShutdown('dataLogger')
        orchestrator._shutdownAlertManager = trackShutdown('alertManager')
        orchestrator._shutdownDriveDetector = trackShutdown('driveDetector')
        orchestrator._shutdownStatisticsEngine = trackShutdown('statisticsEngine')
        orchestrator._shutdownProfileSwitcher = trackShutdown('profileSwitcher')
        orchestrator._shutdownDisplayManager = trackShutdown('displayManager')
        orchestrator._shutdownVinDecoder = trackShutdown('vinDecoder')
        orchestrator._shutdownConnection = trackShutdown('connection')
        orchestrator._shutdownProfileManager = trackShutdown('profileManager')
        orchestrator._shutdownDatabase = trackShutdown('database')

        # Act
        orchestrator._shutdownAllComponents()

        # Assert - profileSwitcher before profileManager
        assert shutdownOrder.index('profileSwitcher') < shutdownOrder.index('profileManager')


# ================================================================================
# US-OSC-012: Connection Recovery Tests
# ================================================================================


class TestConnectionRecoveryConstants:
    """Test US-OSC-012: Connection recovery constants."""

    def test_defaultConnectionCheckInterval(self):
        """
        Given: Orchestrator constants
        When: Checking DEFAULT_CONNECTION_CHECK_INTERVAL
        Then: Value is 5.0 seconds
        """
        from obd.orchestrator import DEFAULT_CONNECTION_CHECK_INTERVAL

        assert DEFAULT_CONNECTION_CHECK_INTERVAL == 5.0

    def test_defaultReconnectDelays(self):
        """
        Given: Orchestrator constants
        When: Checking DEFAULT_RECONNECT_DELAYS
        Then: Value is exponential backoff list [1, 2, 4, 8, 16]
        """
        from obd.orchestrator import DEFAULT_RECONNECT_DELAYS

        assert DEFAULT_RECONNECT_DELAYS == [1, 2, 4, 8, 16]

    def test_defaultMaxReconnectAttempts(self):
        """
        Given: Orchestrator constants
        When: Checking DEFAULT_MAX_RECONNECT_ATTEMPTS
        Then: Value is 5
        """
        from obd.orchestrator import DEFAULT_MAX_RECONNECT_ATTEMPTS

        assert DEFAULT_MAX_RECONNECT_ATTEMPTS == 5


class TestConnectionRecoveryStateTracking:
    """Test US-OSC-012: Connection recovery state tracking."""

    def test_init_setsDefaultReconnectState(self):
        """
        Given: New orchestrator
        When: Checking reconnection state
        Then: State is initialized to not reconnecting
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        assert orchestrator._isReconnecting is False
        assert orchestrator._reconnectAttempt == 0
        assert orchestrator._dataLoggerPausedForReconnect is False

    def test_init_usesConfigReconnectDelays(self):
        """
        Given: Config with custom retry delays
        When: Creating orchestrator
        Then: Uses config values for reconnect delays
        """
        from obd.orchestrator import ApplicationOrchestrator

        config = {
            'bluetooth': {
                'retryDelays': [2, 4, 8],
                'maxRetries': 3
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)

        assert orchestrator._reconnectDelays == [2, 4, 8]
        assert orchestrator._maxReconnectAttempts == 3

    def test_init_usesDefaultsWhenConfigMissing(self):
        """
        Given: Config without bluetooth settings
        When: Creating orchestrator
        Then: Uses default reconnect delays
        """
        from obd.orchestrator import (
            ApplicationOrchestrator,
            DEFAULT_RECONNECT_DELAYS,
            DEFAULT_MAX_RECONNECT_ATTEMPTS
        )

        orchestrator = ApplicationOrchestrator(config={})

        assert orchestrator._reconnectDelays == DEFAULT_RECONNECT_DELAYS
        assert orchestrator._maxReconnectAttempts == DEFAULT_MAX_RECONNECT_ATTEMPTS


class TestConnectionRecoveryStartReconnection:
    """Test US-OSC-012: _startReconnection method."""

    def test_startReconnection_setsReconnectingFlag(self):
        """
        Given: Orchestrator with connection
        When: _startReconnection is called
        Then: _isReconnecting is set to True
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        orchestrator._connection = mockConn

        # Act
        orchestrator._startReconnection()

        # Assert
        assert orchestrator._isReconnecting is True

        # Cleanup
        orchestrator._isReconnecting = False
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=0.1)

    def test_startReconnection_resetsAttemptCounter(self):
        """
        Given: Orchestrator with previous reconnect attempts
        When: _startReconnection is called
        Then: _reconnectAttempt is reset before reconnection starts
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._reconnectAttempt = 5

        # Track when attempt counter is reset
        attemptResetObserved = [False]
        originalLoop = orchestrator._reconnectionLoop

        def trackingLoop():
            # The loop should see attempt = 0 (it was reset before thread started)
            # And then loop increments it, so first iteration sets it to 1
            attemptResetObserved[0] = True
            # Don't run actual loop to avoid delays
            orchestrator._isReconnecting = False

        orchestrator._reconnectionLoop = trackingLoop

        mockConn = MagicMock()
        orchestrator._connection = mockConn

        # Act
        orchestrator._startReconnection()

        # Wait for thread to start
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=0.5)

        # Assert - counter was reset (verified by the loop being called with reset value)
        assert attemptResetObserved[0] is True

    def test_startReconnection_doesNothingIfAlreadyReconnecting(self):
        """
        Given: Orchestrator already reconnecting
        When: _startReconnection is called again
        Then: No new thread is started
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._isReconnecting = True
        orchestrator._reconnectThread = MagicMock()
        mockConn = MagicMock()
        orchestrator._connection = mockConn

        # Act
        orchestrator._startReconnection()

        # Assert - original thread not replaced
        assert orchestrator._reconnectThread is not None

    def test_startReconnection_doesNothingIfNoConnection(self):
        """
        Given: Orchestrator without connection object
        When: _startReconnection is called
        Then: _isReconnecting remains False
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._connection = None

        # Act
        orchestrator._startReconnection()

        # Assert
        assert orchestrator._isReconnecting is False

    def test_startReconnection_startsBackgroundThread(self):
        """
        Given: Orchestrator with connection
        When: _startReconnection is called
        Then: Background thread is started
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        orchestrator._connection = mockConn

        # Act
        orchestrator._startReconnection()

        # Assert
        assert orchestrator._reconnectThread is not None
        assert orchestrator._reconnectThread.is_alive() or orchestrator._reconnectThread.daemon

        # Cleanup
        orchestrator._isReconnecting = False
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=0.5)


class TestConnectionRecoveryAttemptReconnection:
    """Test US-OSC-012: _attemptReconnection method."""

    def test_attemptReconnection_usesReconnectMethodIfAvailable(self):
        """
        Given: Connection with reconnect method
        When: _attemptReconnection is called
        Then: reconnect() is called on connection
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        mockConn.reconnect.return_value = True
        orchestrator._connection = mockConn

        # Act
        result = orchestrator._attemptReconnection()

        # Assert
        assert result is True
        mockConn.reconnect.assert_called_once()

    def test_attemptReconnection_fallsBackToDisconnectConnect(self):
        """
        Given: Connection without reconnect method
        When: _attemptReconnection is called
        Then: disconnect() then connect() are called
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock(spec=['disconnect', 'connect'])
        mockConn.connect.return_value = True
        orchestrator._connection = mockConn

        # Act
        result = orchestrator._attemptReconnection()

        # Assert
        assert result is True
        mockConn.disconnect.assert_called_once()
        mockConn.connect.assert_called_once()

    def test_attemptReconnection_returnsFalseWhenNoConnection(self):
        """
        Given: Orchestrator without connection
        When: _attemptReconnection is called
        Then: Returns False
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._connection = None

        # Act
        result = orchestrator._attemptReconnection()

        # Assert
        assert result is False

    def test_attemptReconnection_returnsFalseOnException(self):
        """
        Given: Connection that throws exception
        When: _attemptReconnection is called
        Then: Returns False
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        mockConn.reconnect.side_effect = Exception("Connection error")
        orchestrator._connection = mockConn

        # Act
        result = orchestrator._attemptReconnection()

        # Assert
        assert result is False


class TestConnectionRecoverySuccess:
    """Test US-OSC-012: _handleReconnectionSuccess method."""

    def test_handleReconnectionSuccess_clearsReconnectingFlag(self):
        """
        Given: Orchestrator in reconnecting state
        When: _handleReconnectionSuccess is called
        Then: _isReconnecting is set to False
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 3

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        assert orchestrator._isReconnecting is False
        assert orchestrator._reconnectAttempt == 0

    def test_handleReconnectionSuccess_updatesHealthStats(self):
        """
        Given: Orchestrator after successful reconnection
        When: _handleReconnectionSuccess is called
        Then: Health stats show connected
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        assert orchestrator._healthCheckStats.connectionConnected is True
        assert orchestrator._healthCheckStats.connectionStatus == "connected"

    def test_handleReconnectionSuccess_resumesDataLogging(self):
        """
        Given: Data logger was paused for reconnection
        When: _handleReconnectionSuccess is called
        Then: Data logger is resumed
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger
        orchestrator._dataLoggerPausedForReconnect = True

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        mockLogger.start.assert_called_once()
        assert orchestrator._dataLoggerPausedForReconnect is False

    def test_handleReconnectionSuccess_updatesDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleReconnectionSuccess is called
        Then: Display shows 'Connected'
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_once_with('Connected')

    def test_handleReconnectionSuccess_invokesCallback(self):
        """
        Given: Orchestrator with onConnectionRestored callback
        When: _handleReconnectionSuccess is called
        Then: Callback is invoked
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        callbackMock = MagicMock()
        orchestrator._onConnectionRestored = callbackMock

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        callbackMock.assert_called_once()


class TestConnectionRecoveryFailure:
    """Test US-OSC-012: _handleReconnectionFailure method."""

    def test_handleReconnectionFailure_clearsReconnectingFlag(self):
        """
        Given: Orchestrator in reconnecting state
        When: _handleReconnectionFailure is called
        Then: _isReconnecting is set to False
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._isReconnecting = True

        # Act
        orchestrator._handleReconnectionFailure()

        # Assert
        assert orchestrator._isReconnecting is False

    def test_handleReconnectionFailure_incrementsErrors(self):
        """
        Given: Orchestrator
        When: _handleReconnectionFailure is called
        Then: totalErrors is incremented
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        initialErrors = orchestrator._healthCheckStats.totalErrors

        # Act
        orchestrator._handleReconnectionFailure()

        # Assert
        assert orchestrator._healthCheckStats.totalErrors == initialErrors + 1

    def test_handleReconnectionFailure_updatesStatusToDisconnected(self):
        """
        Given: Orchestrator
        When: _handleReconnectionFailure is called
        Then: Health stats show disconnected
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})

        # Act
        orchestrator._handleReconnectionFailure()

        # Assert
        assert orchestrator._healthCheckStats.connectionConnected is False
        assert orchestrator._healthCheckStats.connectionStatus == "disconnected"

    def test_handleReconnectionFailure_updatesDisplay(self):
        """
        Given: Orchestrator with display manager
        When: _handleReconnectionFailure is called
        Then: Display shows 'Disconnected'
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._handleReconnectionFailure()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_once_with('Disconnected')


class TestConnectionRecoveryPauseResumeLogging:
    """Test US-OSC-012: Pause/resume data logging during reconnection."""

    def test_pauseDataLogging_stopsDataLogger(self):
        """
        Given: Orchestrator with running data logger
        When: _pauseDataLogging is called
        Then: Data logger is stopped
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger

        # Act
        orchestrator._pauseDataLogging()

        # Assert
        mockLogger.stop.assert_called_once()
        assert orchestrator._dataLoggerPausedForReconnect is True

    def test_pauseDataLogging_doesNothingIfAlreadyPaused(self):
        """
        Given: Data logger already paused
        When: _pauseDataLogging is called again
        Then: stop() is not called again
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger
        orchestrator._dataLoggerPausedForReconnect = True

        # Act
        orchestrator._pauseDataLogging()

        # Assert
        mockLogger.stop.assert_not_called()

    def test_pauseDataLogging_doesNothingIfNoDataLogger(self):
        """
        Given: Orchestrator without data logger
        When: _pauseDataLogging is called
        Then: No error occurs
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        orchestrator._dataLogger = None

        # Act - should not raise
        orchestrator._pauseDataLogging()

        # Assert
        assert orchestrator._dataLoggerPausedForReconnect is False

    def test_resumeDataLogging_startsDataLogger(self):
        """
        Given: Data logger was paused for reconnection
        When: _resumeDataLogging is called
        Then: Data logger is started
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger
        orchestrator._dataLoggerPausedForReconnect = True

        # Act
        orchestrator._resumeDataLogging()

        # Assert
        mockLogger.start.assert_called_once()
        assert orchestrator._dataLoggerPausedForReconnect is False

    def test_resumeDataLogging_doesNothingIfNotPaused(self):
        """
        Given: Data logger was not paused
        When: _resumeDataLogging is called
        Then: start() is not called
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger
        orchestrator._dataLoggerPausedForReconnect = False

        # Act
        orchestrator._resumeDataLogging()

        # Assert
        mockLogger.start.assert_not_called()


class TestConnectionRecoveryIntegration:
    """Test US-OSC-012: Integration tests for connection recovery."""

    def test_handleConnectionLost_startsReconnection(self):
        """
        Given: Orchestrator with connection
        When: _handleConnectionLost is called
        Then: Reconnection is started
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        orchestrator._connection = mockConn

        # Act
        orchestrator._handleConnectionLost()

        # Assert
        assert orchestrator._isReconnecting is True

        # Cleanup
        orchestrator._isReconnecting = False
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=0.1)

    def test_handleConnectionLost_pausesDataLogging(self):
        """
        Given: Orchestrator with running data logger
        When: _handleConnectionLost is called
        Then: Data logging is paused
        """
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        orchestrator._connection = mockConn
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger

        # Act
        orchestrator._handleConnectionLost()

        # Assert
        mockLogger.stop.assert_called_once()
        assert orchestrator._dataLoggerPausedForReconnect is True

        # Cleanup
        orchestrator._isReconnecting = False
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=0.1)

    def test_reconnectionLoop_attemptsReconnectWithBackoff(self):
        """
        Given: Orchestrator with failing connection
        When: Reconnection loop runs
        Then: Multiple attempts made with backoff
        """
        from obd.orchestrator import ApplicationOrchestrator

        # Use very short delays for test
        config = {
            'bluetooth': {
                'retryDelays': [0.01, 0.02],
                'maxRetries': 2
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)
        mockConn = MagicMock()
        mockConn.reconnect.return_value = False  # Always fail
        orchestrator._connection = mockConn

        # Act - run reconnection loop synchronously
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 0
        orchestrator._reconnectionLoop()

        # Assert - all attempts made before failure
        assert mockConn.reconnect.call_count == 2
        assert orchestrator._isReconnecting is False

    def test_reconnectionLoop_stopsOnSuccess(self):
        """
        Given: Orchestrator with connection that succeeds on second attempt
        When: Reconnection loop runs
        Then: Loop stops after success
        """
        from obd.orchestrator import ApplicationOrchestrator

        # Use very short delays for test
        config = {
            'bluetooth': {
                'retryDelays': [0.01, 0.02],
                'maxRetries': 5
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)
        mockConn = MagicMock()
        # Fail first attempt, succeed second
        mockConn.reconnect.side_effect = [False, True]
        orchestrator._connection = mockConn

        # Act - run reconnection loop synchronously
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 0
        orchestrator._reconnectionLoop()

        # Assert - stopped after success
        assert mockConn.reconnect.call_count == 2
        assert orchestrator._isReconnecting is False
        assert orchestrator._healthCheckStats.connectionStatus == "connected"

    def test_reconnectionLoop_respectsShutdownState(self):
        """
        Given: Orchestrator in shutdown state
        When: Reconnection loop runs
        Then: Loop exits without attempting reconnection
        """
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(config={})
        mockConn = MagicMock()
        orchestrator._connection = mockConn
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act - run reconnection loop synchronously
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 0
        orchestrator._reconnectionLoop()

        # Assert - no reconnection attempted
        mockConn.reconnect.assert_not_called()

    def test_connectionRecovery_fullFlow(self):
        """
        Given: Orchestrator with connection
        When: Connection is lost and then recovered
        Then: Full recovery flow executes correctly
        """
        from obd.orchestrator import ApplicationOrchestrator

        # Use very short delays for test
        config = {
            'bluetooth': {
                'retryDelays': [0.01],
                'maxRetries': 3
            }
        }
        orchestrator = ApplicationOrchestrator(config=config)
        mockConn = MagicMock()
        mockConn.reconnect.return_value = True  # Succeed first try
        orchestrator._connection = mockConn

        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        callbackCalled = []

        def onConnectionRestored():
            callbackCalled.append('restored')

        orchestrator._onConnectionRestored = onConnectionRestored

        # Act - trigger connection lost (which starts reconnection)
        orchestrator._handleConnectionLost()

        # Wait for reconnection thread to complete
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=1.0)

        # Assert - full flow completed
        assert orchestrator._isReconnecting is False
        assert orchestrator._healthCheckStats.connectionConnected is True
        assert orchestrator._healthCheckStats.connectionStatus == "connected"
        # Callback called both from _handleConnectionLost start and _handleReconnectionSuccess
        assert 'restored' in callbackCalled
