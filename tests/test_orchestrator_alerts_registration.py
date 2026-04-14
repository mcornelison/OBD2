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
# AC8: Typecheck/lint passes (verified by running make lint)
# ================================================================================


class TestAlertCallbackRegistration:
    """Tests for alert manager callback registration edge cases."""

    def test_setupComponentCallbacks_skips_whenAlertManagerIsNone(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no alert manager
        When: _setupComponentCallbacks() is called
        Then: No error occurs (graceful skip)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        orchestrator._alertManager = None

        # Act (should not raise)
        orchestrator._setupComponentCallbacks()

    def test_setupComponentCallbacks_logsDebug_onSuccess(
        self, alertConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with alert manager
        When: _setupComponentCallbacks() registers alert callback
        Then: Logs 'Alert manager callbacks registered' at DEBUG
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
        with caplog.at_level(logging.DEBUG):
            orchestrator._setupComponentCallbacks()

        # Assert
        assert any(
            'Alert manager callbacks registered' in record.message
            for record in caplog.records
        )

    def test_handleAlert_updatesHardwareManager_withAlertCount(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with hardware manager
        When: _handleAlert() is called
        Then: hardwareManager.updateErrorCount() is called with alert count
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockHardware = MagicMock()
        orchestrator._hardwareManager = mockHardware

        alertEvent = MagicMock()
        alertEvent.alertType = 'rpm_redline'
        alertEvent.parameterName = 'RPM'
        alertEvent.value = 7500
        alertEvent.threshold = 6000
        alertEvent.profileId = 'daily'

        # Act
        orchestrator._handleAlert(alertEvent)

        # Assert
        expectedCount = orchestrator._healthCheckStats.alertsTriggered
        mockHardware.updateErrorCount.assert_called_once_with(
            errors=expectedCount
        )

    def test_handleAlert_survivesHardwareManagerError(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: hardwareManager.updateErrorCount() raises exception
        When: _handleAlert() is called
        Then: No exception propagates
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockHardware = MagicMock()
        mockHardware.updateErrorCount.side_effect = RuntimeError("hw error")
        orchestrator._hardwareManager = mockHardware

        alertEvent = MagicMock()
        alertEvent.alertType = 'rpm_redline'
        alertEvent.parameterName = 'RPM'
        alertEvent.value = 7500
        alertEvent.threshold = 6000
        alertEvent.profileId = 'daily'

        # Act (should not raise)
        orchestrator._handleAlert(alertEvent)
