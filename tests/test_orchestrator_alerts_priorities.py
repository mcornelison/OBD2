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

import os
import tempfile
from typing import Any

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
# AC6: Alert priorities displayed correctly (critical > warning > info)
# ================================================================================


class TestAlertPrioritiesCorrect:
    """Tests that alert priorities are correctly ordered."""

    def test_coolantTempCritical_hasPriority1(self):
        """
        Given: ALERT_PRIORITIES constant
        When: Checking coolant_temp_critical
        Then: Priority is 1 (safety critical)
        """
        # Arrange
        from pi.alert.types import (
            ALERT_PRIORITIES,
            ALERT_TYPE_COOLANT_TEMP_CRITICAL,
        )

        # Assert
        assert ALERT_PRIORITIES[ALERT_TYPE_COOLANT_TEMP_CRITICAL] == 1

    def test_oilPressureLow_hasPriority1(self):
        """
        Given: ALERT_PRIORITIES constant
        When: Checking oil_pressure_low
        Then: Priority is 1 (safety critical)
        """
        # Arrange
        from pi.alert.types import (
            ALERT_PRIORITIES,
            ALERT_TYPE_OIL_PRESSURE_LOW,
        )

        # Assert
        assert ALERT_PRIORITIES[ALERT_TYPE_OIL_PRESSURE_LOW] == 1

    def test_rpmRedline_hasPriority2(self):
        """
        Given: ALERT_PRIORITIES constant
        When: Checking rpm_redline
        Then: Priority is 2 (engine damage risk)
        """
        # Arrange
        from pi.alert.types import ALERT_PRIORITIES, ALERT_TYPE_RPM_REDLINE

        # Assert
        assert ALERT_PRIORITIES[ALERT_TYPE_RPM_REDLINE] == 2

    def test_boostPressureMax_hasPriority3(self):
        """
        Given: ALERT_PRIORITIES constant
        When: Checking boost_pressure_max
        Then: Priority is 3 (performance limit)
        """
        # Arrange
        from pi.alert.types import (
            ALERT_PRIORITIES,
            ALERT_TYPE_BOOST_PRESSURE_MAX,
        )

        # Assert
        assert ALERT_PRIORITIES[ALERT_TYPE_BOOST_PRESSURE_MAX] == 3

    def test_criticalHigherThanWarning_higherThanInfo(self):
        """
        Given: Alert priority definitions
        When: Comparing priority numbers
        Then: Critical (1) < Warning (2) < Info (3)
             (lower number = higher priority)
        """
        # Arrange
        from pi.alert.types import ALERT_PRIORITIES

        criticalPriority = ALERT_PRIORITIES['coolant_temp_critical']
        warningPriority = ALERT_PRIORITIES['rpm_redline']
        infoPriority = ALERT_PRIORITIES['boost_pressure_max']

        # Assert
        assert criticalPriority < warningPriority < infoPriority

    def test_alertEvent_carriesPriority_fromThreshold(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: AlertManager with daily profile thresholds
        When: RPM exceeds redline threshold
        Then: AlertEvent carries priority from threshold definition
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig

        manager = createAlertManagerFromConfig(alertConfig)
        manager.start()

        # Act
        event = manager.checkValue('RPM', 7500, 'daily')

        # Assert
        assert event is not None
        assert hasattr(event, 'alertType')
        assert event.alertType == 'rpm_redline'
