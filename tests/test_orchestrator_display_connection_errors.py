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
from unittest.mock import MagicMock, patch

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


class TestDisplayReceivesStatusUpdatesConnection:
    """Tests that display receives various status updates."""

    def test_connectionEstablished_updatesDisplay_showsConnected(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleReconnectionSuccess() is called
        Then: displayManager.showConnectionStatus('Connected') is called
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 1

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_once_with('Connected')

    def test_connectionLost_updatesDisplay_showsReconnecting(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleConnectionLost() is called (connection drops)
        Then: displayManager.showConnectionStatus('Reconnecting...') is called
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        # Prevent actual reconnection attempts
        with patch.object(orchestrator, '_startReconnection'):
            # Act
            orchestrator._handleConnectionLost()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_with('Reconnecting...')

    def test_connectionFailed_updatesDisplay_showsConnectionFailed(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleReconnectionFailure() is called
        Then: displayManager.showConnectionStatus('Connection Failed') is called
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._handleReconnectionFailure()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_once_with('Connection Failed')

    def test_handleReading_survivesDisplayError_continues(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager that throws
        When: _handleReading() receives a dashboard parameter
        Then: Exception is caught, orchestrator continues (no crash)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.updateValue.side_effect = RuntimeError("Display broke")
        orchestrator._displayManager = mockDisplay
        orchestrator._dashboardParameters = {'RPM'}

        reading = MagicMock()
        reading.parameterName = 'RPM'
        reading.value = 3000.0
        reading.unit = 'rpm'

        # Act — should NOT raise
        orchestrator._handleReading(reading)

        # Assert — method completed without crashing
        mockDisplay.updateValue.assert_called_once()

    def test_handleDriveStart_survivesDisplayError_continues(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager that throws on drive status
        When: _handleDriveStart() is called
        Then: Exception is caught, orchestrator continues
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.showDriveStatus.side_effect = RuntimeError("Display error")
        orchestrator._displayManager = mockDisplay

        session = MagicMock()
        session.id = 'test-session'

        # Act — should NOT raise
        orchestrator._handleDriveStart(session)

    def test_handleAlert_survivesDisplayError_continues(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager that throws on alert display
        When: _handleAlert() is called
        Then: Exception is caught, orchestrator continues
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.showAlert.side_effect = RuntimeError("Display error")
        orchestrator._displayManager = mockDisplay

        alertEvent = MagicMock()
        alertEvent.alertType = 'test'
        alertEvent.parameterName = 'RPM'
        alertEvent.value = 7000
        alertEvent.threshold = 6000
        alertEvent.profileId = 'daily'

        # Act — should NOT raise
        orchestrator._handleAlert(alertEvent)
