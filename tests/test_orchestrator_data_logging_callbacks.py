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
from unittest.mock import MagicMock

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
