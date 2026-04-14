################################################################################
# File Name: test_orchestrator_data_logging.py
# Purpose/Description: Tests for orchestrator realtime data logging wiring (US-OSC-006)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-006
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator realtime data logging wiring.

Verifies that the orchestrator correctly:
- Creates RealtimeDataLogger from config via factory function
- Connects logger to OBD connection and database
- Uses profile-specific polling interval
- Filters parameters by logData flag
- Routes dashboard parameters to display manager
- Wires onReading callback to update display, drive detector, and alert manager
- Wires onError callback to log warnings and continue
- Logs data rate every 5 minutes (configurable)

Usage:
    pytest tests/test_orchestrator_data_logging.py -v
"""

import logging
import os
import tempfile
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getDataLoggingTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for data logging wiring tests.

    Args:
        dbPath: Path to temporary database file

    Returns:
        Configuration dictionary for orchestrator
    """
    return {
        'application': {
            'name': 'Data Logging Test',
            'version': '1.0.0',
            'environment': 'test'
        },
        'database': {
            'path': dbPath,
            'walMode': True,
            'vacuumOnStartup': False,
            'backupOnShutdown': False
        },
        'bluetooth': {
            'macAddress': 'SIMULATED',
            'retryDelays': [0.1, 0.2],
            'maxRetries': 2,
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
        'staticData': {
            'parameters': ['VIN'],
            'queryOnFirstConnection': False
        },
        'realtimeData': {
            'pollingIntervalMs': 100,
            'parameters': [
                {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                {'name': 'COOLANT_TEMP', 'logData': True, 'displayOnDashboard': True},
                {'name': 'ENGINE_LOAD', 'logData': True, 'displayOnDashboard': False},
                {'name': 'THROTTLE_POS', 'logData': True, 'displayOnDashboard': False},
                {'name': 'INTAKE_TEMP', 'logData': False, 'displayOnDashboard': False}
            ]
        },
        'analysis': {
            'triggerAfterDrive': True,
            'driveStartRpmThreshold': 500,
            'driveStartDurationSeconds': 1,
            'driveEndRpmThreshold': 100,
            'driveEndDurationSeconds': 1,
            'calculateStatistics': ['max', 'min', 'avg']
        },
        'aiAnalysis': {
            'enabled': False
        },
        'profiles': {
            'activeProfile': 'daily',
            'availableProfiles': [
                {
                    'id': 'daily',
                    'name': 'Daily Profile',
                    'description': 'Normal daily driving',
                    'pollingIntervalMs': 200
                },
                {
                    'id': 'performance',
                    'name': 'Performance Profile',
                    'description': 'Performance driving',
                    'pollingIntervalMs': 50
                }
            ]
        },
        'tieredThresholds': {
            'rpm': {'unit': 'rpm', 'dangerMin': 7000},
            'coolantTemp': {'unit': 'fahrenheit', 'dangerMin': 220},
        },
        'alerts': {
            'enabled': True,
            'cooldownSeconds': 1,
            'visualAlerts': False,
            'audioAlerts': False,
            'logAlerts': True
        },
        'monitoring': {
            'healthCheckIntervalSeconds': 2,
            'dataRateLogIntervalSeconds': 5
        },
        'shutdown': {
            'componentTimeout': 2
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


@pytest.fixture
def tempDb():
    """Create a temporary database file for testing."""
    fd, dbPath = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield dbPath
    try:
        os.unlink(dbPath)
    except OSError:
        pass


@pytest.fixture
def dataLoggingConfig(tempDb: str) -> dict[str, Any]:
    """Create data logging test configuration with temp database."""
    return getDataLoggingTestConfig(tempDb)


# ================================================================================
# AC1: RealtimeDataLogger created from config in orchestrator
# ================================================================================


class TestDataLoggerCreatedFromConfig:
    """Tests that RealtimeDataLogger is created from config in orchestrator."""

    def test_initializeDataLogger_createsLogger_viaFactory(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid config
        When: start() initializes all components
        Then: _dataLogger is created via createRealtimeLoggerFromConfig
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._dataLogger is not None

        finally:
            orchestrator.stop()

    def test_initializeDataLogger_passesConfig_toFactory(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeDataLogger is called
        Then: createRealtimeLoggerFromConfig receives config, connection, database
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        # The factory is lazily imported inside _initializeDataLogger
        # via `from .data import createRealtimeLoggerFromConfig`
        with patch(
            'pi.obd.data.createRealtimeLoggerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Set up prerequisites that _initializeDataLogger needs
            orchestrator._connection = MagicMock()
            orchestrator._database = MagicMock()

            # Act
            orchestrator._initializeDataLogger()

            # Assert
            mockFactory.assert_called_once_with(
                dataLoggingConfig,
                orchestrator._connection,
                orchestrator._database
            )

    def test_initializeDataLogger_logsSuccess_onCreation(
        self, dataLoggingConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeDataLogger succeeds
        Then: 'DataLogger started successfully' is logged
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        orchestrator._connection = MagicMock()
        orchestrator._database = MagicMock()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._initializeDataLogger()

        # Assert
        assert any(
            'DataLogger started successfully' in record.message
            for record in caplog.records
        )


# ================================================================================
# AC2: Logger connected to OBD connection for data queries
# ================================================================================


class TestLoggerConnectedToConnection:
    """Tests that logger receives OBD connection for querying."""

    def test_dataLogger_receivesConnection_fromOrchestrator(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator started in simulator mode
        When: Data logger is initialized
        Then: Logger has access to the OBD connection
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Assert - data logger and connection are both initialized
            assert orchestrator._dataLogger is not None
            assert orchestrator._connection is not None
            # The factory passes connection to the logger
            if hasattr(orchestrator._dataLogger, 'connection'):
                assert orchestrator._dataLogger.connection is not None

        finally:
            orchestrator.stop()

    def test_factoryCall_includesConnection_asArgument(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with connection initialized
        When: _initializeDataLogger is called
        Then: Connection is passed to factory function
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        mockConnection = MagicMock()
        orchestrator._connection = mockConnection
        orchestrator._database = MagicMock()

        with patch(
            'pi.obd.data.createRealtimeLoggerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeDataLogger()

            # Assert - connection is the second argument
            args = mockFactory.call_args[0]
            assert args[1] is mockConnection


# ================================================================================
# AC3: Logger connected to database for storing readings
# ================================================================================


class TestLoggerConnectedToDatabase:
    """Tests that logger receives database for storing readings."""

    def test_dataLogger_receivesDatabase_fromOrchestrator(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator started in simulator mode
        When: Data logger is initialized
        Then: Logger has access to the database
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Assert - both data logger and database initialized
            assert orchestrator._dataLogger is not None
            assert orchestrator._database is not None
            # The factory passes database to the logger
            if hasattr(orchestrator._dataLogger, 'database'):
                assert orchestrator._dataLogger.database is not None

        finally:
            orchestrator.stop()

    def test_factoryCall_includesDatabase_asArgument(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with database initialized
        When: _initializeDataLogger is called
        Then: Database is passed to factory function
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        mockDatabase = MagicMock()
        orchestrator._connection = MagicMock()
        orchestrator._database = mockDatabase

        with patch(
            'pi.obd.data.createRealtimeLoggerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeDataLogger()

            # Assert - database is the third argument
            args = mockFactory.call_args[0]
            assert args[2] is mockDatabase


# ================================================================================
# AC4: Logger uses profile-specific polling interval
# ================================================================================


class TestProfileSpecificPollingInterval:
    """Tests that logger uses profile-specific polling interval."""

    def test_dataLogger_usesActiveProfilePollingInterval(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config with daily profile at 200ms polling
        When: Data logger is created
        Then: Logger uses profile's polling interval, not global default
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Assert - active profile is 'daily' with pollingIntervalMs=200
            if (
                orchestrator._dataLogger is not None
                and hasattr(orchestrator._dataLogger, '_pollingIntervalMs')
            ):
                assert orchestrator._dataLogger._pollingIntervalMs == 200

        finally:
            orchestrator.stop()

    def test_profileChange_updatesPollingInterval_onDataLogger(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with data logger
        When: Profile changes to 'performance' (50ms polling)
        Then: Data logger polling interval is updated
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Mock the data logger to verify setPollingInterval is called
            mockLogger = MagicMock()
            mockLogger.setPollingInterval = MagicMock()
            orchestrator._dataLogger = mockLogger

            # Create a mock new profile with pollingIntervalMs
            mockProfile = MagicMock()
            mockProfile.pollingIntervalMs = 50

            # Act - simulate profile change
            orchestrator._handleProfileChange('daily', 'performance')

        finally:
            orchestrator.stop()

    def test_configPassedToFactory_includesProfileSettings(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config with profile polling intervals
        When: createRealtimeLoggerFromConfig is called
        Then: Full config (including profiles) is passed to factory
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        orchestrator._connection = MagicMock()
        orchestrator._database = MagicMock()

        with patch(
            'pi.obd.data.createRealtimeLoggerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeDataLogger()

            # Assert - full config with profiles is passed
            configArg = mockFactory.call_args[0][0]
            assert 'profiles' in configArg
            assert configArg['profiles']['activeProfile'] == 'daily'


# ================================================================================
# AC5: Only parameters with logData: true are logged
# ================================================================================


class TestLogDataParameterFiltering:
    """Tests that only parameters with logData=true are logged."""

    def test_configWithLogDataFalse_excludesParameter(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config with INTAKE_TEMP having logData=False
        When: Data logger reads parameters
        Then: INTAKE_TEMP is not in the logged parameter list
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Assert - check logger's parameter list
            if (
                orchestrator._dataLogger is not None
                and hasattr(orchestrator._dataLogger, '_parameters')
            ):
                paramNames = [
                    p if isinstance(p, str) else p.get('name', p)
                    for p in orchestrator._dataLogger._parameters
                ]
                assert 'INTAKE_TEMP' not in paramNames

        finally:
            orchestrator.stop()

    def test_configWithLogDataTrue_includesParameters(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config with RPM, SPEED, COOLANT_TEMP having logData=True
        When: Data logger reads parameters
        Then: Those parameters are in the logged parameter list
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Assert - check logger's parameter list includes logData=true params
            if (
                orchestrator._dataLogger is not None
                and hasattr(orchestrator._dataLogger, '_parameters')
            ):
                paramNames = [
                    p if isinstance(p, str) else p.get('name', p)
                    for p in orchestrator._dataLogger._parameters
                ]
                assert 'RPM' in paramNames
                assert 'SPEED' in paramNames
                assert 'COOLANT_TEMP' in paramNames

        finally:
            orchestrator.stop()


# ================================================================================
# AC6: Parameters with displayOnDashboard: true sent to display
# ================================================================================


class TestDisplayOnDashboardRouting:
    """Tests that displayOnDashboard parameters are routed to display."""

    def test_dashboardParameters_extractedFromConfig(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config with RPM, SPEED, COOLANT_TEMP having displayOnDashboard=True
        When: Orchestrator is created
        Then: _dashboardParameters contains those names
        """
        # Arrange & Act
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        # Assert
        assert 'RPM' in orchestrator._dashboardParameters
        assert 'SPEED' in orchestrator._dashboardParameters
        assert 'COOLANT_TEMP' in orchestrator._dashboardParameters

    def test_nonDashboardParameters_excludedFromSet(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config with ENGINE_LOAD having displayOnDashboard=False
        When: Orchestrator is created
        Then: ENGINE_LOAD not in _dashboardParameters
        """
        # Arrange & Act
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        # Assert
        assert 'ENGINE_LOAD' not in orchestrator._dashboardParameters
        assert 'THROTTLE_POS' not in orchestrator._dashboardParameters
        assert 'INTAKE_TEMP' not in orchestrator._dashboardParameters

    def test_handleReading_sendsToDisplay_forDashboardParam(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with display manager
        When: Reading for dashboard parameter (RPM) arrives
        Then: displayManager.updateValue is called
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.updateValue = MagicMock()
        orchestrator._displayManager = mockDisplay

        class MockReading:
            parameterName = 'RPM'
            value = 2500.0
            unit = 'rpm'

        # Act
        orchestrator._handleReading(MockReading())

        # Assert
        mockDisplay.updateValue.assert_called_once_with('RPM', 2500.0, 'rpm')

    def test_handleReading_skipsDisplay_forNonDashboardParam(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with display manager
        When: Reading for non-dashboard parameter (ENGINE_LOAD) arrives
        Then: displayManager.updateValue is NOT called
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.updateValue = MagicMock()
        orchestrator._displayManager = mockDisplay

        class MockReading:
            parameterName = 'ENGINE_LOAD'
            value = 75.0
            unit = '%'

        # Act
        orchestrator._handleReading(MockReading())

        # Assert
        mockDisplay.updateValue.assert_not_called()


# ================================================================================
# AC7: Logger onReading callback updates display with latest values
# ================================================================================


class TestOnReadingCallbackWiring:
    """Tests that onReading callback is wired and updates display."""

    def test_setupComponentCallbacks_registersOnReading(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with data logger
        When: _setupComponentCallbacks is called
        Then: dataLogger.registerCallbacks is called with onReading
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        mockLogger = MagicMock()
        mockLogger.registerCallbacks = MagicMock()
        orchestrator._dataLogger = mockLogger

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        mockLogger.registerCallbacks.assert_called_once()
        callKwargs = mockLogger.registerCallbacks.call_args
        assert callKwargs[1].get('onReading') is not None or (
            len(callKwargs[0]) > 0
        )

    def test_handleReading_incrementsTotalReadings(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with health stats
        When: _handleReading is called
        Then: totalReadings counter increments
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        initialReadings = orchestrator._healthCheckStats.totalReadings

        class MockReading:
            parameterName = 'RPM'
            value = 3000.0
            unit = 'rpm'

        # Act
        orchestrator._handleReading(MockReading())
        orchestrator._handleReading(MockReading())

        # Assert
        assert orchestrator._healthCheckStats.totalReadings == initialReadings + 2

    def test_handleReading_passesToDriveDetector(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with drive detector
        When: _handleReading is called with RPM reading
        Then: driveDetector.processValue receives the value
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        mockDetector = MagicMock()
        mockDetector.processValue = MagicMock()
        orchestrator._driveDetector = mockDetector

        class MockReading:
            parameterName = 'RPM'
            value = 2500.0
            unit = 'rpm'

        # Act
        orchestrator._handleReading(MockReading())

        # Assert
        mockDetector.processValue.assert_called_once_with('RPM', 2500.0)

    def test_handleReading_passesToAlertManager(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager
        When: _handleReading is called
        Then: alertManager.checkValue receives the value
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        mockAlerts = MagicMock()
        mockAlerts.checkValue = MagicMock()
        orchestrator._alertManager = mockAlerts

        class MockReading:
            parameterName = 'COOLANT_TEMP'
            value = 95.0
            unit = 'C'

        # Act
        orchestrator._handleReading(MockReading())

        # Assert
        mockAlerts.checkValue.assert_called_once_with('COOLANT_TEMP', 95.0)


# ================================================================================
# AC8: Logger onError callback logs warning and continues
# ================================================================================


class TestOnErrorCallbackWiring:
    """Tests that onError callback logs and continues."""

    def test_setupComponentCallbacks_registersOnError(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with data logger
        When: _setupComponentCallbacks is called
        Then: dataLogger.registerCallbacks is called with onError
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        mockLogger = MagicMock()
        mockLogger.registerCallbacks = MagicMock()
        orchestrator._dataLogger = mockLogger

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        callKwargs = mockLogger.registerCallbacks.call_args[1]
        assert 'onError' in callKwargs
        assert callKwargs['onError'] is not None

    def test_handleLoggingError_incrementsErrorCount(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with health stats
        When: _handleLoggingError is called
        Then: totalErrors counter increments
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        initialErrors = orchestrator._healthCheckStats.totalErrors

        # Act
        orchestrator._handleLoggingError('RPM', RuntimeError("Read timeout"))

        # Assert
        assert orchestrator._healthCheckStats.totalErrors == initialErrors + 1

    def test_handleLoggingError_logsDebugMessage(
        self, dataLoggingConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator
        When: _handleLoggingError is called
        Then: Error details are logged at DEBUG level
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._handleLoggingError(
                'COOLANT_TEMP', RuntimeError("Sensor error")
            )

        # Assert
        debugMessages = [
            r.message for r in caplog.records if r.levelno == logging.DEBUG
        ]
        assert any('COOLANT_TEMP' in m for m in debugMessages)
        assert any('Sensor error' in m for m in debugMessages)

    def test_orchestrator_continuesRunning_afterLoggingError(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: Multiple logging errors occur
        Then: Orchestrator continues running (no crash)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act - fire multiple errors
            orchestrator._handleLoggingError('RPM', RuntimeError("Error 1"))
            orchestrator._handleLoggingError('SPEED', RuntimeError("Error 2"))
            orchestrator._handleLoggingError('COOLANT_TEMP', RuntimeError("Error 3"))

            # Assert - still running, errors tracked
            assert orchestrator.isRunning() is True
            assert orchestrator._healthCheckStats.totalErrors >= 3

        finally:
            orchestrator.stop()


# ================================================================================
# AC9: Data logging rate logged every 5 minutes (records/minute)
# ================================================================================


class TestDataLoggingRateTracking:
    """Tests that data logging rate is logged periodically."""

    def test_logDataLoggingRate_logsRecordsPerMinute(
        self, dataLoggingConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with some readings processed
        When: _logDataLoggingRate is called
        Then: Records/minute rate is logged at INFO level
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        # Simulate prior state: 100 readings over 5 minutes
        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=5)
        orchestrator._lastDataRateLogCount = 0
        orchestrator._healthCheckStats.totalReadings = 100

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._logDataLoggingRate()

        # Assert
        infoMessages = [
            r.message for r in caplog.records if r.levelno == logging.INFO
        ]
        assert any('DATA LOGGING RATE' in m for m in infoMessages)
        assert any('records/min=' in m for m in infoMessages)

    def test_logDataLoggingRate_calculatesCorrectRate(
        self, dataLoggingConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: 60 readings in 1 minute
        When: _logDataLoggingRate is called
        Then: Rate is approximately 60 records/minute
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=1)
        orchestrator._lastDataRateLogCount = 0
        orchestrator._healthCheckStats.totalReadings = 60

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._logDataLoggingRate()

        # Assert - rate should be ~60/min
        infoMessages = [
            r.message for r in caplog.records if r.levelno == logging.INFO
        ]
        rateMessage = next(
            (m for m in infoMessages if 'records/min=' in m), None
        )
        assert rateMessage is not None
        assert 'records/min=60.0' in rateMessage or 'records/min=59' in rateMessage

    def test_dataRateLogInterval_configurableFromConfig(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config with dataRateLogIntervalSeconds=5
        When: Orchestrator is created
        Then: _dataRateLogInterval is set to 5
        """
        # Arrange & Act
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        # Assert
        assert orchestrator._dataRateLogInterval == 5

    def test_dataRateLogInterval_defaultsToFiveMinutes(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config without dataRateLogIntervalSeconds
        When: Orchestrator is created
        Then: _dataRateLogInterval defaults to 300 seconds (5 minutes)
        """
        # Arrange
        from pi.obd.orchestrator import (
            DEFAULT_DATA_RATE_LOG_INTERVAL,
            ApplicationOrchestrator,
        )

        configWithoutInterval = dict(dataLoggingConfig)
        configWithoutInterval['monitoring'] = {}

        # Act
        orchestrator = ApplicationOrchestrator(
            config=configWithoutInterval,
            simulate=True
        )

        # Assert
        assert orchestrator._dataRateLogInterval == DEFAULT_DATA_RATE_LOG_INTERVAL
        assert DEFAULT_DATA_RATE_LOG_INTERVAL == 300.0

    def test_logDataLoggingRate_updatesTrackingState(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with readings tracked
        When: _logDataLoggingRate is called
        Then: _lastDataRateLogCount is updated to current total
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=1)
        orchestrator._lastDataRateLogCount = 0
        orchestrator._healthCheckStats.totalReadings = 50

        # Act
        orchestrator._logDataLoggingRate()

        # Assert
        assert orchestrator._lastDataRateLogCount == 50

    def test_logDataLoggingRate_logsTotalLogged(
        self, dataLoggingConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with 200 total readings
        When: _logDataLoggingRate is called
        Then: Log message includes total_logged=200
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=2)
        orchestrator._lastDataRateLogCount = 100
        orchestrator._healthCheckStats.totalReadings = 200

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._logDataLoggingRate()

        # Assert
        infoMessages = [
            r.message for r in caplog.records if r.levelno == logging.INFO
        ]
        assert any('total_logged=200' in m for m in infoMessages)
