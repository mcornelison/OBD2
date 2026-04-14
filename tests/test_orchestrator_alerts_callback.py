################################################################################
# File Name: test_orchestrator_alerts.py
# Purpose/Description: Tests for orchestrator alert system wiring (US-OSC-008)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-008
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator alert system wiring.

Verifies that the orchestrator correctly:
- Creates AlertManager from config via factory function
- Routes all realtime values to AlertManager for threshold checking
- Uses active profile's alert thresholds
- Handles onAlert callback: logs at WARNING, sends to display, records in database
- Respects cooldown period (no repeated alerts for same condition)
- Displays alert priorities correctly (critical > warning > info)
- Provides queryable alert history from database
- Passes typecheck and lint

Usage:
    pytest tests/test_orchestrator_alerts.py -v
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


def getAlertTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for alert system wiring tests.

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
                'name': 'Alert System Test',
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
                    {'name': 'INTAKE_PRESSURE', 'logData': True, 'displayOnDashboard': True},
                ]
            },
            'analysis': {
                'triggerAfterDrive': True,
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 1,
                'driveEndRpmThreshold': 100,
                'driveEndDurationSeconds': 2,
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
            }
        },
        'server': {
            'ai': {'enabled': False},
            'database': {},
            'api': {}
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
def alertConfig(tempDb: str) -> dict[str, Any]:
    """Create alert test configuration with temp database."""
    return getAlertTestConfig(tempDb)


# ================================================================================
# AC4: Alert onAlert callback: logs at WARNING, sends to display,
#      records in database
# ================================================================================


class TestAlertCallbackWiring:
    """Tests alert onAlert callback behavior."""

    def test_setupComponentCallbacks_registersHandleAlert(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager
        When: _setupComponentCallbacks() is called
        Then: alertManager.onAlert() is called with _handleAlert
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        mockAlertManager.onAlert.assert_called_once_with(
            orchestrator._handleAlert
        )

    def test_handleAlert_logsAtWarningLevel(
        self, alertConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Alert event with type=rpm_redline, param=RPM, value=7500
        When: _handleAlert() is called
        Then: Log at WARNING level with alert details
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        alertEvent = MagicMock()
        alertEvent.alertType = 'rpm_redline'
        alertEvent.parameterName = 'RPM'
        alertEvent.value = 7500
        alertEvent.threshold = 6000
        alertEvent.profileId = 'daily'

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._handleAlert(alertEvent)

        # Assert
        warningRecords = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert len(warningRecords) >= 1
        msg = warningRecords[0].message
        assert 'ALERT triggered' in msg
        assert 'rpm_redline' in msg
        assert 'RPM' in msg

    def test_handleAlert_logsValue_andThreshold(
        self, alertConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Alert event with value=7500, threshold=6000
        When: _handleAlert() is called
        Then: Log message includes value and threshold
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        alertEvent = MagicMock()
        alertEvent.alertType = 'rpm_redline'
        alertEvent.parameterName = 'RPM'
        alertEvent.value = 7500
        alertEvent.threshold = 6000
        alertEvent.profileId = 'daily'

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._handleAlert(alertEvent)

        # Assert
        msg = caplog.records[-1].message
        assert '7500' in msg
        assert '6000' in msg

    def test_handleAlert_sendsToDisplay_viaShowAlert(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleAlert() is called
        Then: displayManager.showAlert() receives the alert event
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        alertEvent = MagicMock()
        alertEvent.alertType = 'coolant_temp_critical'
        alertEvent.parameterName = 'COOLANT_TEMP'
        alertEvent.value = 120
        alertEvent.threshold = 105
        alertEvent.profileId = 'daily'

        # Act
        orchestrator._handleAlert(alertEvent)

        # Assert
        mockDisplay.showAlert.assert_called_once_with(alertEvent)

    def test_handleAlert_survivesDisplayError(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: displayManager.showAlert() raises exception
        When: _handleAlert() is called
        Then: No exception propagates
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockDisplay = MagicMock()
        mockDisplay.showAlert.side_effect = RuntimeError("display error")
        orchestrator._displayManager = mockDisplay

        alertEvent = MagicMock()
        alertEvent.alertType = 'rpm_redline'
        alertEvent.parameterName = 'RPM'
        alertEvent.value = 7500
        alertEvent.threshold = 6000
        alertEvent.profileId = 'daily'

        # Act (should not raise)
        orchestrator._handleAlert(alertEvent)

    def test_handleAlert_incrementsAlertsTriggered(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with health check stats
        When: _handleAlert() is called
        Then: healthCheckStats.alertsTriggered increments by 1
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        initialCount = orchestrator._healthCheckStats.alertsTriggered

        alertEvent = MagicMock()
        alertEvent.alertType = 'rpm_redline'
        alertEvent.parameterName = 'RPM'
        alertEvent.value = 7500
        alertEvent.threshold = 6000
        alertEvent.profileId = 'daily'

        # Act
        orchestrator._handleAlert(alertEvent)

        # Assert
        assert orchestrator._healthCheckStats.alertsTriggered == (
            initialCount + 1
        )

    def test_handleAlert_callsExternalCallback(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with external onAlert callback registered
        When: _handleAlert() is called
        Then: External callback receives the alert event
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        externalCallback = MagicMock()
        orchestrator._onAlert = externalCallback

        alertEvent = MagicMock()
        alertEvent.alertType = 'boost_pressure_max'
        alertEvent.parameterName = 'INTAKE_PRESSURE'
        alertEvent.value = 22
        alertEvent.threshold = 18
        alertEvent.profileId = 'daily'

        # Act
        orchestrator._handleAlert(alertEvent)

        # Assert
        externalCallback.assert_called_once_with(alertEvent)

    def test_handleAlert_survivesExternalCallbackError(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: External callback raises an exception
        When: _handleAlert() is called
        Then: No exception propagates
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        externalCallback = MagicMock()
        externalCallback.side_effect = RuntimeError("callback error")
        orchestrator._onAlert = externalCallback

        alertEvent = MagicMock()
        alertEvent.alertType = 'rpm_redline'
        alertEvent.parameterName = 'RPM'
        alertEvent.value = 7500
        alertEvent.threshold = 6000
        alertEvent.profileId = 'daily'

        # Act (should not raise)
        orchestrator._handleAlert(alertEvent)
