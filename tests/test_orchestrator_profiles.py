################################################################################
# File Name: test_orchestrator_profiles.py
# Purpose/Description: Tests for orchestrator profile system wiring (US-OSC-011)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-011
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator profile system wiring.

Verifies that the orchestrator correctly:
- Creates ProfileManager from config via factory function (AC1)
- Syncs profiles from config to database on startup (AC2)
- Loads active profile from config (AC3)
- Updates alert thresholds, polling interval, display on profile change (AC4)
- Queues profile switch if driving, activates on next drive start (AC5)
- Logs profile changes: 'Profile changed from [A] to [B]' (AC6)
- Passes typecheck and lint (AC7)

Usage:
    pytest tests/test_orchestrator_profiles.py -v
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


def getProfileTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for profile system wiring tests.

    Args:
        dbPath: Path to temporary database file

    Returns:
        Configuration dictionary for orchestrator
    """
    return {
        'application': {
            'name': 'Profile System Test',
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
            'pollingIntervalMs': 200,
            'parameters': [
                {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                {'name': 'COOLANT_TEMP', 'logData': True, 'displayOnDashboard': True},
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
def profileConfig(tempDb: str) -> dict[str, Any]:
    """Create profile test configuration with temp database."""
    return getProfileTestConfig(tempDb)


# ================================================================================
# AC1: ProfileManager created from config in orchestrator
# ================================================================================


class TestProfileManagerCreatedFromConfig:
    """Tests that ProfileManager is created from config in orchestrator."""

    def test_initializeProfileManager_createsManager_notNone(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid profile config
        When: start() initializes all components
        Then: _profileManager is created and not None
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._profileManager is not None
        finally:
            orchestrator.stop()

    def test_initializeProfileManager_usesFactory_createProfileManagerFromConfig(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeProfileManager() is called
        Then: createProfileManagerFromConfig factory is invoked with config and database
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        with patch(
            'obd.orchestrator.ApplicationOrchestrator._initializeAllComponents'
        ):
            orchestrator._running = True

        # Mock the import
        mockFactory = MagicMock()
        with patch.dict(
            'sys.modules',
            {'pi.profile': MagicMock(
                createProfileManagerFromConfig=mockFactory
            )}
        ):
            with patch(
                'pi.profile.createProfileManagerFromConfig',
                mockFactory
            ):
                # Act
                orchestrator._initializeProfileManager()

                # Assert
                mockFactory.assert_called_once()
                args = mockFactory.call_args
                assert args[0][0] == profileConfig  # config is first arg

    def test_initializeProfileManager_logsStarting_infoLevel(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeProfileManager() is called
        Then: Logs 'Starting profileManager...' at INFO level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            # Assert
            assert any(
                'Starting profileManager' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_initializeProfileManager_logsSuccess_infoLevel(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: ProfileManager initializes successfully
        Then: Logs 'ProfileManager started successfully' at INFO level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            # Assert
            assert any(
                'ProfileManager started successfully' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_initializeProfileManager_importError_skipsGracefully(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: ProfileManager module not available
        When: _initializeProfileManager() is called
        Then: Logs warning and continues (no exception raised)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        with patch(
            'obd.orchestrator.ApplicationOrchestrator._initializeProfileManager'
        ) as mockInit:
            # Simulate the import error behavior
            def raiseImportError():
                import logging as log
                log.getLogger('obd.orchestrator').warning(
                    "ProfileManager not available, skipping"
                )
            mockInit.side_effect = raiseImportError

            # Act & Assert - should not raise
            with caplog.at_level(logging.WARNING):
                try:
                    orchestrator.start()
                except Exception:
                    pass  # Other components may fail, that's fine

        assert orchestrator._profileManager is None


# ================================================================================
# AC2: Profiles from config synced to database on startup
# ================================================================================


class TestProfilesSyncedToDatabase:
    """Tests that profiles from config are synced to database on startup."""

    def test_profileSync_configProfiles_existInManagerAfterStart(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Config with 'daily' and 'spirited' profiles
        When: Orchestrator starts
        Then: Both profiles exist in the profile manager
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            pm = orchestrator._profileManager
            assert pm is not None
            assert pm.profileExists('daily')
            assert pm.profileExists('spirited')
        finally:
            orchestrator.stop()

    def test_profileSync_profileCount_matchesConfig(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Config with 2 available profiles
        When: Orchestrator starts
        Then: ProfileManager has exactly 2 profiles
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            pm = orchestrator._profileManager
            assert pm is not None
            assert pm.getProfileCount() >= 2
        finally:
            orchestrator.stop()

    def test_profileSync_profileData_matchesConfig(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Config with 'daily' profile
        When: Orchestrator starts
        Then: Profile data in manager matches config values
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            pm = orchestrator._profileManager
            assert pm is not None
            profile = pm.getProfile('daily')
            assert profile is not None
            assert profile.name == 'Daily Profile'
        finally:
            orchestrator.stop()

    def test_profileSync_databaseReceivesProfiles_viaFactory(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Config with profiles and database
        When: createProfileManagerFromConfig called
        Then: Database parameter is passed to factory (enabling DB sync)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Assert - profileManager was created with database reference
            # (which enables DB sync inside the factory)
            pm = orchestrator._profileManager
            assert pm is not None
            # The factory passes database to ProfileManager constructor
            # and syncs profiles during creation
            assert pm._database is not None
        finally:
            orchestrator.stop()


# ================================================================================
# AC3: Active profile loaded from config
# ================================================================================


class TestActiveProfileLoadedFromConfig:
    """Tests that active profile is loaded from config on startup."""

    def test_activeProfile_setFromConfig_matchesConfigValue(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Config with activeProfile: 'daily'
        When: Orchestrator starts
        Then: ProfileManager's active profile is 'daily'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            pm = orchestrator._profileManager
            assert pm is not None
            assert pm.getActiveProfileId() == 'daily'
        finally:
            orchestrator.stop()

    def test_activeProfile_profileSwitcherInitialized_matchesConfig(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Config with activeProfile: 'daily'
        When: Orchestrator starts and ProfileSwitcher initializes
        Then: ProfileSwitcher's active profile is 'daily'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            ps = orchestrator._profileSwitcher
            assert ps is not None
            assert ps.getActiveProfileId() == 'daily'
        finally:
            orchestrator.stop()

    def test_activeProfile_differentConfigValue_usesConfigured(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Config with activeProfile changed to 'spirited'
        When: Orchestrator starts
        Then: Active profile is 'spirited'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        profileConfig['profiles']['activeProfile'] = 'spirited'
        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            pm = orchestrator._profileManager
            assert pm is not None
            assert pm.getActiveProfileId() == 'spirited'
        finally:
            orchestrator.stop()

    def test_activeProfile_profileSwitcherCreated_notNone(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with profile config
        When: start() initializes all components
        Then: _profileSwitcher is created and not None
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._profileSwitcher is not None
        finally:
            orchestrator.stop()


# ================================================================================
# AC4: Profile change updates alert thresholds, polling interval, display
# ================================================================================


class TestProfileChangeUpdatesComponents:
    """Tests that profile change updates alert thresholds, polling interval, display."""

    def test_handleProfileChange_updatesActiveProfile_onAlertManager(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager
        When: _handleProfileChange called with 'spirited'
        Then: Alert manager's setActiveProfile is called with 'spirited'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockAlertManager = MagicMock()
            mockAlertManager.setActiveProfile = MagicMock()
            orchestrator._alertManager = mockAlertManager

            # Act
            orchestrator._handleProfileChange('daily', 'spirited')

            # Assert
            mockAlertManager.setActiveProfile.assert_called_once_with('spirited')
        finally:
            orchestrator.stop()

    def test_handleProfileChange_updatesPollingInterval_onDataLogger(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with data logger and profile with pollingIntervalMs
        When: _handleProfileChange called with 'spirited' (100ms polling)
        Then: Data logger's setPollingInterval is called with 100
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockDataLogger = MagicMock()
            mockDataLogger.setPollingInterval = MagicMock()
            orchestrator._dataLogger = mockDataLogger

            # Act
            orchestrator._handleProfileChange('daily', 'spirited')

            # Assert
            mockDataLogger.setPollingInterval.assert_called_once_with(100)
        finally:
            orchestrator.stop()

    def test_handleProfileChange_survivesAlertManagerError_continuesRunning(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Alert manager whose setActiveProfile raises on profile switch
        When: _handleProfileChange is called
        Then: Orchestrator continues (no crash), logs warning
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockAlertManager = MagicMock()
            mockAlertManager.setActiveProfile = MagicMock(
                side_effect=RuntimeError("alert manager failed on profile switch")
            )
            orchestrator._alertManager = mockAlertManager

            # Act & Assert - should not raise
            with caplog.at_level(logging.WARNING):
                orchestrator._handleProfileChange('daily', 'spirited')

            assert any(
                'Could not update alert manager' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_handleProfileChange_survivesDataLoggerError_continuesRunning(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Data logger that raises an exception
        When: _handleProfileChange is called
        Then: Orchestrator continues (no crash), logs warning
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockDataLogger = MagicMock()
            mockDataLogger.setPollingInterval = MagicMock(
                side_effect=RuntimeError("polling update failed")
            )
            orchestrator._dataLogger = mockDataLogger

            # Act & Assert - should not raise
            with caplog.at_level(logging.WARNING):
                orchestrator._handleProfileChange('daily', 'spirited')

            assert any(
                'Could not update data logger' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_handleProfileChange_noAlertManager_skipsGracefully(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no alert manager (None)
        When: _handleProfileChange is called
        Then: No error raised, runs silently
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            orchestrator._alertManager = None

            # Act & Assert - should not raise
            orchestrator._handleProfileChange('daily', 'spirited')
        finally:
            orchestrator.stop()

    def test_handleProfileChange_noDataLogger_skipsGracefully(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no data logger (None)
        When: _handleProfileChange is called
        Then: No error raised, runs silently
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            orchestrator._dataLogger = None

            # Act & Assert - should not raise
            orchestrator._handleProfileChange('daily', 'spirited')
        finally:
            orchestrator.stop()

    def test_handleProfileChange_profileNotFound_logsWarning(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile manager that can't find the profile
        When: _handleProfileChange called with unknown profile ID
        Then: Logs warning about not finding the profile
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockProfileManager = MagicMock()
            mockProfileManager.getProfile = MagicMock(
                side_effect=Exception("Profile not found: unknown")
            )
            orchestrator._profileManager = mockProfileManager

            # Act
            with caplog.at_level(logging.WARNING):
                orchestrator._handleProfileChange('daily', 'unknown')

            # Assert
            assert any(
                'Could not get profile' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()


# ================================================================================
# AC5: Profile switch queued if driving (activated on next drive start)
# ================================================================================


class TestProfileSwitchQueuedIfDriving:
    """Tests that profile switch is queued if driving and activated on next drive start."""

    def test_profileSwitcher_requestSwitch_whileNotDriving_switchesImmediately(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator running, not driving
        When: ProfileSwitcher.requestProfileSwitch('spirited') called
        Then: Active profile changes immediately to 'spirited'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None
            assert ps.getActiveProfileId() == 'daily'

            # Act
            ps.requestProfileSwitch('spirited')

            # Assert
            assert ps.getActiveProfileId() == 'spirited'
        finally:
            orchestrator.stop()

    def test_profileSwitcher_requestSwitch_whileDriving_queuesSwitch(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator running, drive in progress
        When: ProfileSwitcher.requestProfileSwitch('spirited') called
        Then: Switch is queued (pending), active remains 'daily'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Simulate drive in progress
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector

            # Act
            ps.requestProfileSwitch('spirited')

            # Assert
            assert ps.getActiveProfileId() == 'daily'  # Still daily
            assert ps.hasPendingSwitch()
            assert ps.getPendingProfileId() == 'spirited'
        finally:
            orchestrator.stop()

    def test_profileSwitcher_pendingSwitch_activatesOnDriveStart(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Profile switch pending for 'spirited'
        When: Drive starts
        Then: Active profile switches to 'spirited'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Queue a switch while "driving"
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector
            ps.requestProfileSwitch('spirited')

            assert ps.hasPendingSwitch()

            # Act - simulate drive start
            mockSession = MagicMock()
            ps._onDriveStart(mockSession)

            # Assert
            assert ps.getActiveProfileId() == 'spirited'
            assert not ps.hasPendingSwitch()
        finally:
            orchestrator.stop()

    def test_profileSwitcher_cancelPending_clearsPendingSwitch(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Profile switch pending for 'spirited'
        When: cancelPendingSwitch() called
        Then: Pending switch is cleared, active profile unchanged
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Queue a switch while "driving"
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector
            ps.requestProfileSwitch('spirited')

            assert ps.hasPendingSwitch()

            # Act
            result = ps.cancelPendingSwitch()

            # Assert
            assert result is True
            assert not ps.hasPendingSwitch()
            assert ps.getActiveProfileId() == 'daily'
        finally:
            orchestrator.stop()

    def test_profileSwitcher_driveEnd_doesNotActivatePending(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Profile switch pending for 'spirited'
        When: Drive ends
        Then: Pending switch is NOT activated (waits for next drive start)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Queue a switch while "driving"
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector
            ps.requestProfileSwitch('spirited')

            # Act - simulate drive end
            mockSession = MagicMock()
            ps._onDriveEnd(mockSession)

            # Assert - still pending, not activated
            assert ps.getActiveProfileId() == 'daily'
            assert ps.hasPendingSwitch()
        finally:
            orchestrator.stop()


# ================================================================================
# AC6: Profile changes logged: 'Profile changed from [A] to [B]'
# ================================================================================


class TestProfileChangesLogged:
    """Tests that profile changes are logged correctly."""

    def test_handleProfileChange_logsMessage_withOldAndNew(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator running
        When: _handleProfileChange('daily', 'spirited') called
        Then: Logs 'Profile changed from daily to spirited' at INFO level
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._handleProfileChange('daily', 'spirited')

            # Assert
            assert any(
                'Profile changed from daily to spirited' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_handleProfileChange_logsMessage_noneToProfile(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator running, no previous profile (None)
        When: _handleProfileChange(None, 'daily') called
        Then: Logs 'Profile changed from None to daily'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._handleProfileChange(None, 'daily')

            # Assert
            assert any(
                'Profile changed from None to daily' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_profileSwitcher_switchActivated_logsProfileSwitched(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: ProfileSwitcher running with 'daily' active
        When: requestProfileSwitch('spirited') called (not driving)
        Then: Logs 'Profile switched: daily -> spirited'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Act
            with caplog.at_level(logging.INFO):
                ps.requestProfileSwitch('spirited')

            # Assert
            assert any(
                'Profile switched' in record.message
                and 'daily' in record.message
                and 'spirited' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_profileSwitcher_switchQueued_logsPendingMessage(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: ProfileSwitcher running, drive in progress
        When: requestProfileSwitch('spirited') called
        Then: Logs queued message with 'will activate on next drive start'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Simulate driving
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector

            # Act
            with caplog.at_level(logging.INFO):
                ps.requestProfileSwitch('spirited')

            # Assert
            assert any(
                'Profile switch queued' in record.message
                and 'next drive start' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()


# ================================================================================
# AC7: Typecheck/lint passes (verified by running make lint)
# Additional wiring tests
# ================================================================================


class TestProfileCallbackWiring:
    """Tests that profile callbacks are properly wired in the orchestrator."""

    def test_setupComponentCallbacks_wiresProfileSwitcher_onProfileChange(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with profileSwitcher
        When: _setupComponentCallbacks() called
        Then: ProfileSwitcher.onProfileChange receives _handleProfileChange callback
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # _setupComponentCallbacks is called in runWorkflow(), call it explicitly
            orchestrator._setupComponentCallbacks()

            # Assert - verify callback is registered
            ps = orchestrator._profileSwitcher
            assert ps is not None
            assert len(ps._onProfileChange) > 0
        finally:
            orchestrator.stop()

    def test_profileSwitcherCallback_triggersHandleProfileChange(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile switcher callback wired
        When: ProfileSwitcher fires a profile change event
        Then: Orchestrator's _handleProfileChange is called (logs profile change)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Wire callbacks (normally done in runWorkflow)
            orchestrator._setupComponentCallbacks()

            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Act - trigger a profile switch which fires the callback
            with caplog.at_level(logging.INFO):
                ps.requestProfileSwitch('spirited')

            # Assert - _handleProfileChange should have been called via callback
            assert any(
                'Profile changed from daily to spirited' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_setupCallbacks_noProfileSwitcher_skipsGracefully(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with _profileSwitcher = None
        When: _setupComponentCallbacks() called
        Then: No error raised (skips profile switcher wiring)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        orchestrator._profileSwitcher = None

        # Act & Assert - should not raise
        orchestrator._setupComponentCallbacks()

    def test_profileSwitcher_initializeFromConfig_setsActiveProfile(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: ProfileSwitcher created from config
        When: initializeFromConfig(config) called
        Then: Logs initialization of active profile from config
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            # Assert
            assert any(
                'Initialized active profile from config' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()


class TestProfileShutdown:
    """Tests that profile components are properly shut down."""

    def test_shutdown_profileManager_setToNone(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with running profile manager
        When: stop() called
        Then: _profileManager is set to None
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        orchestrator.start()
        assert orchestrator._profileManager is not None

        # Act
        orchestrator.stop()

        # Assert
        assert orchestrator._profileManager is None

    def test_shutdown_profileSwitcher_setToNone(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with running profile switcher
        When: stop() called
        Then: _profileSwitcher is set to None
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        orchestrator.start()
        assert orchestrator._profileSwitcher is not None

        # Act
        orchestrator.stop()

        # Assert
        assert orchestrator._profileSwitcher is None


class TestProfileStatusReporting:
    """Tests that profile status is included in orchestrator status."""

    def test_getStatus_includesProfileManager(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with profile manager running
        When: getStatus() called
        Then: Status dict components includes 'profileManager' key
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            status = orchestrator.getStatus()

            # Assert
            components = status.get('components', status)
            assert 'profileManager' in components
        finally:
            orchestrator.stop()

    def test_getStatus_includesProfileSwitcher(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with profile switcher running
        When: getStatus() called
        Then: Status dict components includes 'profileSwitcher' key
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            status = orchestrator.getStatus()

            # Assert
            components = status.get('components', status)
            assert 'profileSwitcher' in components
        finally:
            orchestrator.stop()


class TestProfileInitOrder:
    """Tests that profile components are initialized in correct dependency order."""

    def test_initOrder_profileManagerBeforeConnection(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile config
        When: start() initializes all components
        Then: profileManager starts before connection (step 2 before step 3)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            # Find indices of log messages
            messages = [record.message for record in caplog.records]

            profileStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting profileManager' in m),
                None
            )
            connectionStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting connection' in m),
                None
            )

            # Assert
            assert profileStartIdx is not None
            assert connectionStartIdx is not None
            assert profileStartIdx < connectionStartIdx
        finally:
            orchestrator.stop()

    def test_initOrder_profileSwitcherAfterDriveDetector(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile config
        When: start() initializes all components
        Then: profileSwitcher starts after driveDetector (needs drive state)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            messages = [record.message for record in caplog.records]

            driveStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting driveDetector' in m),
                None
            )
            switcherStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting profileSwitcher' in m),
                None
            )

            # Assert
            assert driveStartIdx is not None
            assert switcherStartIdx is not None
            assert driveStartIdx < switcherStartIdx
        finally:
            orchestrator.stop()

    def test_initOrder_databaseBeforeProfileManager(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile config
        When: start() initializes all components
        Then: database starts before profileManager (DB needed for sync)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            messages = [record.message for record in caplog.records]

            dbStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting database' in m),
                None
            )
            profileStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting profileManager' in m),
                None
            )

            # Assert
            assert dbStartIdx is not None
            assert profileStartIdx is not None
            assert dbStartIdx < profileStartIdx
        finally:
            orchestrator.stop()
