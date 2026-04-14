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
        'protocolVersion': '1.0.0',
        'schemaVersion': '1.0.0',
        'deviceId': 'test-device',
        'logging': {
            'level': 'DEBUG',
            'maskPII': False
        },
        'pi': {
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
        },
        'server': {
            'ai': {
                'enabled': False
            },
            'database': {},
            'api': {},
        },
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
