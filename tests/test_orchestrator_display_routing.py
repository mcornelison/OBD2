################################################################################
# File Name: test_orchestrator_display.py
# Purpose/Description: Tests for orchestrator display manager wiring (US-OSC-010)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-010
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator display manager wiring.

Verifies that the orchestrator correctly:
- Creates DisplayManager from config via factory function
- Selects display mode from config (headless, minimal, developer)
- Initializes display on startup with welcome screen
- Routes status updates to display (connection, RPM/speed/coolant, profile,
  drive status, alerts)
- Configures refresh rate from config (default 1Hz / 1000ms)
- Shows 'Shutting down...' during shutdown
- Falls back to headless if display hardware unavailable
- Passes typecheck and lint

Usage:
    pytest tests/test_orchestrator_display.py -v
"""

import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getDisplayTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for display manager wiring tests.

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
                'name': 'Display Manager Test',
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
                'showOnStartup': True
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
                    {'name': 'INTAKE_PRESSURE', 'logData': True, 'displayOnDashboard': True},
                ]
            },
            'analysis': {
                'triggerAfterDrive': True,
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 1,
                'driveEndRpmThreshold': 100,
                'driveEndDurationSeconds': 2,
                'calculateStatistics': [
                    'max', 'min', 'avg', 'mode',
                    'std_1', 'std_2', 'outlier_min', 'outlier_max'
                ]
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
                        'id': 'spirited',
                        'name': 'Spirited Profile',
                        'description': 'Spirited driving with higher thresholds',
                        'pollingIntervalMs': 100
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
def displayConfig(tempDb: str) -> dict[str, Any]:
    """Create display test configuration with temp database."""
    return getDisplayTestConfig(tempDb)


# ================================================================================
# AC4: Display receives status updates: connection, RPM/speed/coolant, profile,
#      drive status, alerts
# ================================================================================


class TestDisplayReceivesStatusUpdatesRouting:
    """Tests that display receives various status updates."""

    def test_handleReading_updatesDisplay_forDashboardParams(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager and dashboard parameters
        When: _handleReading() receives a dashboard parameter reading
        Then: displayManager.updateValue() is called with param/value/unit
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        orchestrator._dashboardParameters = {'RPM', 'SPEED', 'COOLANT_TEMP'}

        reading = MagicMock()
        reading.parameterName = 'RPM'
        reading.value = 2500.0
        reading.unit = 'rpm'

        # Act
        orchestrator._handleReading(reading)

        # Assert
        mockDisplay.updateValue.assert_called_once_with('RPM', 2500.0, 'rpm')

    def test_handleReading_skipsDisplay_forNonDashboardParams(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleReading() receives a non-dashboard parameter
        Then: displayManager.updateValue() is NOT called
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        orchestrator._dashboardParameters = {'RPM', 'SPEED'}

        reading = MagicMock()
        reading.parameterName = 'ENGINE_LOAD'
        reading.value = 45.0
        reading.unit = '%'

        # Act
        orchestrator._handleReading(reading)

        # Assert
        mockDisplay.updateValue.assert_not_called()

    def test_handleDriveStart_updatesDisplay_showsDriving(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleDriveStart() is called
        Then: displayManager.showDriveStatus('driving') is called
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        session = MagicMock()
        session.id = 'test-session'

        # Act
        orchestrator._handleDriveStart(session)

        # Assert
        mockDisplay.showDriveStatus.assert_called_once_with('driving')

    def test_handleDriveEnd_updatesDisplay_showsStopped(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleDriveEnd() is called
        Then: displayManager.showDriveStatus('stopped') is called
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        session = MagicMock()
        session.duration = 120.5

        # Act
        orchestrator._handleDriveEnd(session)

        # Assert
        mockDisplay.showDriveStatus.assert_called_once_with('stopped')

    def test_handleAlert_updatesDisplay_showsAlert(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleAlert() is called with an alert event
        Then: displayManager.showAlert() is called with the event
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        alertEvent = MagicMock()
        alertEvent.alertType = 'coolant_temp'
        alertEvent.parameterName = 'COOLANT_TEMP'
        alertEvent.value = 110
        alertEvent.threshold = 105
        alertEvent.profileId = 'daily'

        # Act
        orchestrator._handleAlert(alertEvent)

        # Assert
        mockDisplay.showAlert.assert_called_once_with(alertEvent)

    def test_handleAnalysisComplete_updatesDisplay_showsResult(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleAnalysisComplete() is called
        Then: displayManager.showAnalysisResult() is called with result
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        result = MagicMock()

        # Act
        orchestrator._handleAnalysisComplete(result)

        # Assert
        mockDisplay.showAnalysisResult.assert_called_once_with(result)
