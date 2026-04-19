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
# AC7: Alert history queryable from database
# ================================================================================


class TestAlertHistoryQueryable:
    """Tests that alert history is queryable from the database."""

    @staticmethod
    def _seedProfiles(database: Any) -> None:
        """Insert profile records so FK constraints pass."""
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO profiles (id, name) VALUES (?, ?)",
                ('daily', 'Daily Profile')
            )
            cursor.execute(
                "INSERT OR IGNORE INTO profiles (id, name) VALUES (?, ?)",
                ('spirited', 'Spirited Profile')
            )

    def test_alertManager_logsToDB_whenLogAlertsEnabled(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: AlertManager with logAlerts=True and database
        When: Alert is triggered
        Then: Alert is logged to alert_log table
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig
        from pi.obdii.database import ObdDatabase

        dbPath = alertConfig['pi']['database']['path']
        database = ObdDatabase(dbPath)
        database.initialize()
        self._seedProfiles(database)

        manager = createAlertManagerFromConfig(
            alertConfig, database=database
        )
        manager.start()

        # Act
        manager.checkValue('RPM', 7500, 'daily')

        # Assert
        history = manager.getAlertHistory()
        assert len(history) >= 1
        assert history[0]['alert_type'] == 'rpm_redline'
        assert history[0]['parameter_name'] == 'RPM'

    def test_alertHistory_filterable_byProfileId(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Alerts from both 'daily' and 'spirited' profiles
        When: getAlertHistory(profileId='daily') called
        Then: Only daily profile alerts returned
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig
        from pi.obdii.database import ObdDatabase

        dbPath = alertConfig['pi']['database']['path']
        database = ObdDatabase(dbPath)
        database.initialize()
        self._seedProfiles(database)

        manager = createAlertManagerFromConfig(
            alertConfig, database=database
        )
        manager.start()

        # Trigger alerts from daily profile
        manager.checkValue('RPM', 7500, 'daily')
        manager.clearCooldowns()

        # Trigger alerts from spirited profile
        manager.checkValue('RPM', 7500, 'spirited')

        # Act
        dailyHistory = manager.getAlertHistory(profileId='daily')
        spiritedHistory = manager.getAlertHistory(profileId='spirited')

        # Assert
        assert len(dailyHistory) >= 1
        assert all(h['profile_id'] == 'daily' for h in dailyHistory)
        assert len(spiritedHistory) >= 1
        assert all(h['profile_id'] == 'spirited' for h in spiritedHistory)

    def test_alertHistory_filterable_byAlertType(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Multiple alert types triggered
        When: getAlertHistory(alertType='rpm_redline') called
        Then: Only RPM redline alerts returned
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig
        from pi.obdii.database import ObdDatabase

        dbPath = alertConfig['pi']['database']['path']
        database = ObdDatabase(dbPath)
        database.initialize()
        self._seedProfiles(database)

        manager = createAlertManagerFromConfig(
            alertConfig, database=database
        )
        manager.start()

        # Trigger RPM and COOLANT_TEMP alerts
        manager.checkValue('RPM', 7500, 'daily')
        manager.checkValue('COOLANT_TEMP', 120, 'daily')

        # Act
        rpmHistory = manager.getAlertHistory(alertType='rpm_redline')

        # Assert
        assert len(rpmHistory) >= 1
        assert all(h['alert_type'] == 'rpm_redline' for h in rpmHistory)

    def test_getAlertCount_returnsCorrectCount(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Multiple alerts triggered
        When: getAlertCount() called
        Then: Returns correct count of alerts
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig
        from pi.obdii.database import ObdDatabase

        dbPath = alertConfig['pi']['database']['path']
        database = ObdDatabase(dbPath)
        database.initialize()
        self._seedProfiles(database)

        manager = createAlertManagerFromConfig(
            alertConfig, database=database
        )
        manager.start()

        # Trigger alerts (different types have independent cooldowns)
        # 7500 > 7000 RPM tiered threshold; 230 > 220 coolant tiered threshold
        manager.checkValue('RPM', 7500, 'daily')
        manager.checkValue('COOLANT_TEMP', 230, 'daily')

        # Act
        count = manager.getAlertCount()

        # Assert
        assert count == 2

    def test_getAlertHistory_returnsEmptyList_whenNoDatabase(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: AlertManager with no database
        When: getAlertHistory() called
        Then: Returns empty list (no error)
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig

        manager = createAlertManagerFromConfig(alertConfig)
        manager.start()

        # Act
        history = manager.getAlertHistory()

        # Assert
        assert history == []
