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
