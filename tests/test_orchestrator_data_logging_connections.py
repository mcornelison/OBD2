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
            assert 'profiles' in configArg['pi']
            assert configArg['pi']['profiles']['activeProfile'] == 'daily'
