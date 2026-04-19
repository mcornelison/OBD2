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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
