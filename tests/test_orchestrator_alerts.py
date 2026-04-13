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
from unittest.mock import MagicMock, patch

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
        'aiAnalysis': {
            'enabled': False
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
        'logging': {
            'level': 'DEBUG',
            'maskPII': False
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
# AC1: AlertManager created from config in orchestrator
# ================================================================================


class TestAlertManagerCreatedFromConfig:
    """Tests that AlertManager is created from config in orchestrator."""

    def test_initializeAlertManager_createsManager_viaFactory(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid alert config
        When: start() initializes all components
        Then: _alertManager is created and not None
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._alertManager is not None
        finally:
            orchestrator.stop()

    def test_initializeAlertManager_passesConfig_toFactory(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert config
        When: _initializeAlertManager() is called
        Then: Factory receives config, database, and displayManager
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockDb = MagicMock()
        mockDisplay = MagicMock()
        orchestrator._database = mockDb
        orchestrator._displayManager = mockDisplay

        with patch(
            'alert.createAlertManagerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeAlertManager()

            # Assert
            mockFactory.assert_called_once_with(
                alertConfig, mockDb, mockDisplay
            )

    def test_initializeAlertManager_logsSuccess_onCreation(
        self, alertConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeAlertManager() succeeds
        Then: Logs 'AlertManager started successfully'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        with patch(
            'alert.createAlertManagerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._initializeAlertManager()

        # Assert
        assert any(
            'AlertManager started successfully' in record.message
            for record in caplog.records
        )

    def test_initializeAlertManager_logsStarting_message(
        self, alertConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeAlertManager() is called
        Then: Logs 'Starting alertManager...'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        with patch(
            'alert.createAlertManagerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._initializeAlertManager()

        # Assert
        assert any(
            'Starting alertManager' in record.message
            for record in caplog.records
        )

    def test_initializeAlertManager_raisesError_onFailure(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Factory raises an exception
        When: _initializeAlertManager() is called
        Then: ComponentInitializationError is raised
        """
        # Arrange
        from obd.orchestrator import (
            ApplicationOrchestrator,
            ComponentInitializationError,
        )

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        with patch(
            'alert.createAlertManagerFromConfig'
        ) as mockFactory:
            mockFactory.side_effect = RuntimeError("test error")

            # Act & Assert
            with pytest.raises(ComponentInitializationError):
                orchestrator._initializeAlertManager()


# ================================================================================
# AC2: Manager receives all realtime values from logger
# ================================================================================


class TestAlertManagerReceivesValues:
    """Tests that AlertManager receives all realtime values from the logger."""

    def test_handleReading_callsCheckValue_withParameterAndValue(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager wired
        When: _handleReading() is called with a reading
        Then: alertManager.checkValue() receives parameterName and value
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 5500.0

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockAlertManager.checkValue.assert_called_once_with('RPM', 5500.0)

    def test_handleReading_callsCheckValue_forCoolantTemp(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager wired
        When: _handleReading() receives COOLANT_TEMP reading
        Then: alertManager.checkValue() is called with COOLANT_TEMP
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        mockReading = MagicMock()
        mockReading.parameterName = 'COOLANT_TEMP'
        mockReading.value = 98.0

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockAlertManager.checkValue.assert_called_once_with(
            'COOLANT_TEMP', 98.0
        )

    def test_handleReading_skipsCheckValue_whenAlertManagerIsNone(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no alert manager
        When: _handleReading() is called
        Then: No error occurs (graceful degradation)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        orchestrator._alertManager = None

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 7000.0

        # Act (should not raise)
        orchestrator._handleReading(mockReading)

    def test_handleReading_skipsCheckValue_whenValueIsNone(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager
        When: _handleReading() receives None value
        Then: checkValue is NOT called
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = None

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockAlertManager.checkValue.assert_not_called()

    def test_handleReading_continuesOnCheckValueError(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: alertManager.checkValue() raises an exception
        When: _handleReading() is called
        Then: No exception propagates (error is caught and logged)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        mockAlertManager.checkValue.side_effect = RuntimeError("check failed")
        orchestrator._alertManager = mockAlertManager

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 5000.0

        # Act (should not raise)
        orchestrator._handleReading(mockReading)


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
        from alert.helpers import createAlertManagerFromConfig

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
        from alert.helpers import createAlertManagerFromConfig

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
        from alert.helpers import createAlertManagerFromConfig

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from alert.helpers import createAlertManagerFromConfig

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
        from alert.helpers import createAlertManagerFromConfig

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
        from alert.helpers import createAlertManagerFromConfig

        manager = createAlertManagerFromConfig(alertConfig)
        manager.start()

        # Act - trigger RPM alert
        rpmAlert = manager.checkValue('RPM', 7500, 'daily')

        # Act - trigger COOLANT_TEMP alert (230 > 220 tiered threshold)
        tempAlert = manager.checkValue('COOLANT_TEMP', 230, 'daily')

        # Assert
        assert rpmAlert is not None
        assert tempAlert is not None


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
        from alert.types import (
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
        from alert.types import (
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
        from alert.types import ALERT_PRIORITIES, ALERT_TYPE_RPM_REDLINE

        # Assert
        assert ALERT_PRIORITIES[ALERT_TYPE_RPM_REDLINE] == 2

    def test_boostPressureMax_hasPriority3(self):
        """
        Given: ALERT_PRIORITIES constant
        When: Checking boost_pressure_max
        Then: Priority is 3 (performance limit)
        """
        # Arrange
        from alert.types import (
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
        from alert.types import ALERT_PRIORITIES

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
        from alert.helpers import createAlertManagerFromConfig

        manager = createAlertManagerFromConfig(alertConfig)
        manager.start()

        # Act
        event = manager.checkValue('RPM', 7500, 'daily')

        # Assert
        assert event is not None
        assert hasattr(event, 'alertType')
        assert event.alertType == 'rpm_redline'


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
        from alert.helpers import createAlertManagerFromConfig
        from obd.database import ObdDatabase

        dbPath = alertConfig['database']['path']
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
        from alert.helpers import createAlertManagerFromConfig
        from obd.database import ObdDatabase

        dbPath = alertConfig['database']['path']
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
        from alert.helpers import createAlertManagerFromConfig
        from obd.database import ObdDatabase

        dbPath = alertConfig['database']['path']
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
        from alert.helpers import createAlertManagerFromConfig
        from obd.database import ObdDatabase

        dbPath = alertConfig['database']['path']
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
        from alert.helpers import createAlertManagerFromConfig

        manager = createAlertManagerFromConfig(alertConfig)
        manager.start()

        # Act
        history = manager.getAlertHistory()

        # Assert
        assert history == []


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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
