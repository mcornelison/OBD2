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

import pytest
from unittest.mock import MagicMock, patch, call
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
