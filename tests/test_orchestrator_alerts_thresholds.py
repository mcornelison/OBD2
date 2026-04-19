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
# AC3: Manager uses active profile's alert thresholds
# ================================================================================


class TestAlertManagerUsesProfileThresholds:
    """Tests that AlertManager uses the active profile's alert thresholds."""

    def test_factoryLoadsProfileThresholds_fromConfig(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Config with profile alert thresholds
        When: createAlertManagerFromConfig is called
        Then: Thresholds are loaded for each profile
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig

        # Act
        manager = createAlertManagerFromConfig(alertConfig)

        # Assert - daily profile thresholds loaded
        dailyThresholds = manager.getThresholdsForProfile('daily')
        assert len(dailyThresholds) > 0

    def test_factorySetsActiveProfile_fromConfig(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Config with activeProfile set to 'daily'
        When: createAlertManagerFromConfig is called
        Then: Active profile is 'daily'
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig

        # Act
        manager = createAlertManagerFromConfig(alertConfig)

        # Assert
        assert manager._activeProfileId == 'daily'

    def test_profileThresholds_includeRpmRedline(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Config with tieredThresholds.rpm.dangerMin: 7000
        When: Thresholds are loaded via setThresholdsFromConfig
        Then: RPM threshold exists with value 7000 (Spool-authoritative, US-139)
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig

        manager = createAlertManagerFromConfig(alertConfig)

        # Act
        thresholds = manager.getThresholdsForProfile('daily')

        # Assert
        rpmThresholds = [t for t in thresholds if t.parameterName == 'RPM']
        assert len(rpmThresholds) == 1
        assert rpmThresholds[0].threshold == 7000  # tiered source, not legacy profile

    def test_profileChange_setsActiveProfile(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager on 'daily' profile
        When: Profile changes to 'spirited'
        Then: alertManager.setActiveProfile() is called with 'spirited'
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        mockProfileManager = MagicMock()
        spiritedProfile = MagicMock()
        mockProfileManager.getProfile.return_value = spiritedProfile
        orchestrator._profileManager = mockProfileManager

        # Act
        orchestrator._handleProfileChange('daily', 'spirited')

        # Assert
        mockAlertManager.setActiveProfile.assert_called_once_with('spirited')


# ================================================================================
# AC5: Alerts respect cooldown period (no repeated alerts for same condition)
# ================================================================================


class TestAlertCooldownRespected:
    """Tests that alerts respect the cooldown period."""

    def test_alertManager_cooldownSet_fromConfig(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Config with cooldownSeconds: 1
        When: AlertManager is created from config
        Then: Cooldown period is 1 second
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig

        # Act
        manager = createAlertManagerFromConfig(alertConfig)

        # Assert
        assert manager._cooldownSeconds == 1

    def test_alertManager_suppressesRepeatAlerts_withinCooldown(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: AlertManager with 1 second cooldown, first alert triggered
        When: Same condition checked immediately
        Then: Second alert is suppressed
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig

        manager = createAlertManagerFromConfig(alertConfig)
        manager.start()

        # Act - trigger first alert
        firstAlert = manager.checkValue('RPM', 7500, 'daily')

        # Act - immediately check again (within cooldown)
        secondAlert = manager.checkValue('RPM', 7500, 'daily')

        # Assert
        assert firstAlert is not None
        assert secondAlert is None

        # Verify stats
        stats = manager.getStats()
        assert stats.alertsTriggered == 1
        assert stats.alertsSuppressed >= 1

    def test_alertManager_differentParams_notAffectedByCooldown(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: RPM alert triggered within cooldown
        When: COOLANT_TEMP threshold exceeded (tiered dangerMin=220)
        Then: COOLANT_TEMP alert fires (different alert type, independent cooldown)
        """
        # Arrange
        from pi.alert.helpers import createAlertManagerFromConfig

        manager = createAlertManagerFromConfig(alertConfig)
        manager.start()

        # Act - trigger RPM alert
        rpmAlert = manager.checkValue('RPM', 7500, 'daily')

        # Act - trigger COOLANT_TEMP alert (230 > 220 tiered threshold)
        tempAlert = manager.checkValue('COOLANT_TEMP', 230, 'daily')

        # Assert
        assert rpmAlert is not None
        assert tempAlert is not None
