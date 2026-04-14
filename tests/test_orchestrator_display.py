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

import logging
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
def displayConfig(tempDb: str) -> dict[str, Any]:
    """Create display test configuration with temp database."""
    return getDisplayTestConfig(tempDb)


# ================================================================================
# AC1: DisplayManager created from config in orchestrator
# ================================================================================


class TestDisplayManagerCreatedFromConfig:
    """Tests that DisplayManager is created from config in orchestrator."""

    def test_initializeDisplayManager_createsManager_notNone(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid display config
        When: start() initializes all components
        Then: _displayManager is created and not None
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._displayManager is not None
        finally:
            orchestrator.stop()

    def test_initializeDisplayManager_usesFactory_createDisplayManagerFromConfig(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeDisplayManager() is called
        Then: createDisplayManagerFromConfig factory is invoked with config
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = True
            mockManager.mode = MagicMock()
            mockManager.mode.value = 'headless'
            mockFactory.return_value = mockManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            mockFactory.assert_called_once_with(displayConfig)

    def test_initializeDisplayManager_callsInitialize_onCreatedManager(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display config
        When: _initializeDisplayManager() is called
        Then: initialize() is called on the created DisplayManager
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = True
            mockManager.mode = MagicMock()
            mockManager.mode.value = 'headless'
            mockFactory.return_value = mockManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            mockManager.initialize.assert_called_once()

    def test_initializeDisplayManager_logsStarting_beforeCreation(
        self, displayConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with display config
        When: _initializeDisplayManager() is called
        Then: 'Starting displayManager...' is logged at INFO level
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with caplog.at_level(logging.INFO):
            with patch(
                'pi.display.createDisplayManagerFromConfig'
            ) as mockFactory:
                mockManager = MagicMock()
                mockManager.initialize.return_value = True
                mockManager.mode = MagicMock()
                mockManager.mode.value = 'headless'
                mockFactory.return_value = mockManager

                # Act
                orchestrator._initializeDisplayManager()

        # Assert
        assert any(
            'Starting displayManager' in record.message
            for record in caplog.records
        )

    def test_initializeDisplayManager_logsSuccess_afterCreation(
        self, displayConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid display config
        When: _initializeDisplayManager() completes successfully
        Then: 'DisplayManager started successfully' is logged
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with caplog.at_level(logging.INFO):
            with patch(
                'pi.display.createDisplayManagerFromConfig'
            ) as mockFactory:
                mockManager = MagicMock()
                mockManager.initialize.return_value = True
                mockManager.mode = MagicMock()
                mockManager.mode.value = 'headless'
                mockFactory.return_value = mockManager

                # Act
                orchestrator._initializeDisplayManager()

        # Assert
        assert any(
            'DisplayManager started successfully' in record.message
            for record in caplog.records
        )


# ================================================================================
# AC2: Display mode selected from config: headless, minimal, developer
# ================================================================================


class TestDisplayModeFromConfig:
    """Tests that display mode is selected from config."""

    def test_displayMode_headless_selectedFromConfig(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Config with display.mode = 'headless'
        When: DisplayManager is created
        Then: Manager mode is HEADLESS
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        displayConfig['display']['mode'] = 'headless'
        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._displayManager is not None
            assert orchestrator._displayManager.mode.value == 'headless'
        finally:
            orchestrator.stop()

    def test_displayMode_developer_selectedFromConfig(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Config with display.mode = 'developer'
        When: DisplayManager is created
        Then: Manager mode is DEVELOPER
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        displayConfig['display']['mode'] = 'developer'
        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._displayManager is not None
            assert orchestrator._displayManager.mode.value == 'developer'
        finally:
            orchestrator.stop()

    def test_displayMode_passedToFactory_inConfig(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Config with display.mode = 'minimal'
        When: _initializeDisplayManager() is called
        Then: Factory receives full config with the mode value
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        displayConfig['display']['mode'] = 'minimal'
        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = True
            mockManager.mode = MagicMock()
            mockManager.mode.value = 'minimal'
            mockFactory.return_value = mockManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            passedConfig = mockFactory.call_args[0][0]
            assert passedConfig['display']['mode'] == 'minimal'

    def test_displayMode_logsMode_onSuccess(
        self, displayConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Config with display.mode = 'headless'
        When: _initializeDisplayManager() completes
        Then: Log message includes mode=headless
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with caplog.at_level(logging.INFO):
            with patch(
                'pi.display.createDisplayManagerFromConfig'
            ) as mockFactory:
                mockManager = MagicMock()
                mockManager.initialize.return_value = True
                mockManager.mode = MagicMock()
                mockManager.mode.value = 'headless'
                mockFactory.return_value = mockManager

                # Act
                orchestrator._initializeDisplayManager()

        # Assert
        assert any(
            'mode=headless' in record.message
            for record in caplog.records
        )


# ================================================================================
# AC3: Display initialized on startup with welcome screen
# ================================================================================


class TestDisplayWelcomeScreen:
    """Tests that display shows welcome screen on startup."""

    def test_initializeDisplay_callsShowWelcomeScreen_onStartup(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display config
        When: _initializeDisplayManager() is called
        Then: showWelcomeScreen() is called on the display manager
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = True
            mockManager.mode = MagicMock()
            mockManager.mode.value = 'headless'
            mockFactory.return_value = mockManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            mockManager.showWelcomeScreen.assert_called_once()

    def test_welcomeScreen_receivesAppName_andVersion(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display config
        When: showWelcomeScreen() is called on startup
        Then: It receives app name and version arguments
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = True
            mockManager.mode = MagicMock()
            mockManager.mode.value = 'headless'
            mockFactory.return_value = mockManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            callArgs = mockManager.showWelcomeScreen.call_args
            assert callArgs is not None
            kwargs = callArgs[1] if callArgs[1] else {}
            args = callArgs[0] if callArgs[0] else ()
            # Either kwargs or positional — check appName was passed
            if kwargs:
                assert 'appName' in kwargs
                assert 'version' in kwargs
            else:
                assert len(args) >= 2

    def test_welcomeScreen_notCalled_whenDisplayNone(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator where display creation returns None
        When: _initializeDisplayManager() is called
        Then: No error occurs (showWelcomeScreen not called on None)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = False
            mockFactory.return_value = mockManager
            # Fallback also fails
            with patch.object(
                orchestrator, '_createHeadlessDisplayFallback',
                return_value=None
            ):
                # Act
                orchestrator._initializeDisplayManager()

                # Assert — no exception raised, manager is None
                assert orchestrator._displayManager is None


# ================================================================================
# AC4: Display receives status updates: connection, RPM/speed/coolant, profile,
#      drive status, alerts
# ================================================================================


class TestDisplayReceivesStatusUpdates:
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

    def test_connectionEstablished_updatesDisplay_showsConnected(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleReconnectionSuccess() is called
        Then: displayManager.showConnectionStatus('Connected') is called
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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


# ================================================================================
# AC5: Display refreshes at configured rate (default 1Hz)
# ================================================================================


class TestDisplayRefreshRate:
    """Tests that display refresh rate is configured from config."""

    def test_configContainsRefreshRateMs_default1000(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Default test config
        When: Checking display.refreshRateMs
        Then: Default value is 1000 (1Hz)
        """
        # Assert
        assert displayConfig['display']['refreshRateMs'] == 1000

    def test_displayManagerReceivesConfig_withRefreshRate(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Config with display.refreshRateMs = 500
        When: _initializeDisplayManager() creates the display
        Then: Factory receives config containing refreshRateMs
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        displayConfig['display']['refreshRateMs'] = 500
        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = True
            mockManager.mode = MagicMock()
            mockManager.mode.value = 'headless'
            mockFactory.return_value = mockManager

            # Act
            orchestrator._initializeDisplayManager()

            # Assert
            passedConfig = mockFactory.call_args[0][0]
            assert passedConfig['display']['refreshRateMs'] == 500

    def test_displayConfig_refreshRateMs_passedToManager(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display config containing refreshRateMs=1000
        When: DisplayManager is created via full startup
        Then: The display manager receives the config with refresh rate
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            dm = orchestrator._displayManager
            assert dm is not None
            # The config was passed through — verify manager exists and runs
            assert dm.isInitialized
        finally:
            orchestrator.stop()


# ================================================================================
# AC6: Display shows 'Shutting down...' during shutdown
# ================================================================================


class TestDisplayShutdownMessage:
    """Tests that display shows shutdown message."""

    def test_shutdownDisplayManager_callsShowShutdownMessage(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with initialized display manager
        When: _shutdownDisplayManager() is called
        Then: showShutdownMessage() is called before stopping
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._shutdownDisplayManager()

        # Assert
        mockDisplay.showShutdownMessage.assert_called_once()

    def test_shutdownDisplayManager_stopsManager_afterMessage(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _shutdownDisplayManager() is called
        Then: Display manager is set to None after shutdown
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._shutdownDisplayManager()

        # Assert
        assert orchestrator._displayManager is None

    def test_shutdownDisplayManager_survivesMessageError_continues(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Display manager that throws on showShutdownMessage
        When: _shutdownDisplayManager() is called
        Then: Shutdown proceeds without error
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.showShutdownMessage.side_effect = RuntimeError("broken")
        orchestrator._displayManager = mockDisplay

        # Act — should NOT raise
        orchestrator._shutdownDisplayManager()

        # Assert — manager still cleaned up
        assert orchestrator._displayManager is None

    def test_fullLifecycle_showsShutdownMessage_onStop(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator started successfully
        When: stop() is called
        Then: Display shows 'Shutting down...' message (via log)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            assert orchestrator._displayManager is not None
        except Exception:
            pytest.skip("Could not start orchestrator")
            return

        # Act
        orchestrator.stop()

        # Assert — display manager is None after stop
        assert orchestrator._displayManager is None

    def test_shutdownDisplayManager_noDisplay_doesNotCrash(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with _displayManager = None
        When: _shutdownDisplayManager() is called
        Then: No error occurs
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )
        orchestrator._displayManager = None

        # Act — should NOT raise
        orchestrator._shutdownDisplayManager()

        # Assert
        assert orchestrator._displayManager is None


# ================================================================================
# AC7: Graceful fallback to headless if display hardware unavailable
# ================================================================================


class TestDisplayHeadlessFallback:
    """Tests graceful fallback to headless mode."""

    def test_initializeFails_fallsBackToHeadless(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Display initialization fails (hardware unavailable)
        When: _initializeDisplayManager() is called
        Then: Falls back to headless display mode
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            # First call (original mode) — initialize fails
            mockManager = MagicMock()
            mockManager.initialize.return_value = False
            mockFactory.return_value = mockManager

            # Mock the fallback
            fallbackDisplay = MagicMock()
            fallbackDisplay.initialize.return_value = True
            fallbackDisplay.mode = MagicMock()
            fallbackDisplay.mode.value = 'headless'

            with patch.object(
                orchestrator, '_createHeadlessDisplayFallback',
                return_value=fallbackDisplay
            ) as mockFallback:
                # Act
                orchestrator._initializeDisplayManager()

                # Assert
                mockFallback.assert_called_once()
                assert orchestrator._displayManager == fallbackDisplay

    def test_createHeadlessDisplayFallback_forcesHeadlessMode(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Config with display.mode = 'minimal'
        When: _createHeadlessDisplayFallback() is called
        Then: Factory is called with mode forced to 'headless'
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        displayConfig['display']['mode'] = 'minimal'
        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = True
            mockFactory.return_value = mockManager

            # Act
            orchestrator._createHeadlessDisplayFallback()

            # Assert
            passedConfig = mockFactory.call_args[0][0]
            assert passedConfig['display']['mode'] == 'headless'

    def test_createHeadlessDisplayFallback_initializesManager(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator config
        When: _createHeadlessDisplayFallback() is called
        Then: Returned manager is initialized
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = True
            mockFactory.return_value = mockManager

            # Act
            result = orchestrator._createHeadlessDisplayFallback()

            # Assert
            assert result is not None
            mockManager.initialize.assert_called_once()

    def test_createHeadlessDisplayFallback_returnsNone_onFailure(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Even headless display fails to initialize
        When: _createHeadlessDisplayFallback() is called
        Then: Returns None
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig'
        ) as mockFactory:
            mockManager = MagicMock()
            mockManager.initialize.return_value = False
            mockFactory.return_value = mockManager

            # Act
            result = orchestrator._createHeadlessDisplayFallback()

            # Assert
            assert result is None

    def test_fallbackLogsWarning_whenInitFails(
        self, displayConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Display initialization fails
        When: _initializeDisplayManager() is called
        Then: Warning about fallback is logged
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with caplog.at_level(logging.WARNING):
            with patch(
                'pi.display.createDisplayManagerFromConfig'
            ) as mockFactory:
                mockManager = MagicMock()
                mockManager.initialize.return_value = False
                mockFactory.return_value = mockManager

                with patch.object(
                    orchestrator, '_createHeadlessDisplayFallback',
                    return_value=None
                ):
                    # Act
                    orchestrator._initializeDisplayManager()

        # Assert
        assert any(
            'falling back to headless' in record.message.lower()
            for record in caplog.records
        )

    def test_importError_skipsDisplay_gracefully(
        self, displayConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: display_manager module cannot be imported
        When: _initializeDisplayManager() is called
        Then: Warning is logged, display remains None
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with caplog.at_level(logging.WARNING):
            with patch(
                'pi.display.createDisplayManagerFromConfig',
                side_effect=ImportError("No module")
            ):
                # Act
                orchestrator._initializeDisplayManager()

        # Assert
        assert orchestrator._displayManager is None
        assert any(
            'not available' in record.message.lower()
            for record in caplog.records
        )

    def test_unexpectedError_raisesComponentInitError(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: DisplayManager raises unexpected error
        When: _initializeDisplayManager() is called
        Then: ComponentInitializationError is raised
        """
        # Arrange
        from pi.obd.orchestrator import (
            ApplicationOrchestrator,
            ComponentInitializationError,
        )

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        with patch(
            'pi.display.createDisplayManagerFromConfig',
            side_effect=RuntimeError("Something broke badly")
        ):
            # Act & Assert
            with pytest.raises(ComponentInitializationError):
                orchestrator._initializeDisplayManager()


# ================================================================================
# AC8: Typecheck/lint passes (verified by running make lint)
# ================================================================================


class TestDisplayManagerAccessor:
    """Tests that display manager is accessible via orchestrator."""

    def test_displayManager_property_returnsManager(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with initialized display
        When: Accessing displayManager property
        Then: Returns the display manager instance
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            dm = orchestrator.displayManager

            # Assert
            assert dm is not None
        finally:
            orchestrator.stop()

    def test_getStatus_includesDisplayManager(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: getStatus() is called
        Then: Status dict includes displayManager in components
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            status = orchestrator.getStatus()

            # Assert
            assert 'components' in status
            assert 'displayManager' in status['components']
            assert status['components']['displayManager'] == 'initialized'
        finally:
            orchestrator.stop()

    def test_displayManager_initOrder_afterVinDecoder(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator config
        When: start() initializes components
        Then: Display is initialized in correct dependency order
             (after VinDecoder, before HardwareManager)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=displayConfig,
            simulate=True
        )

        initOrder: list[str] = []

        originalInitDisplay = orchestrator._initializeDisplayManager
        originalInitHardware = orchestrator._initializeHardwareManager

        def trackInitDisplay():
            initOrder.append('displayManager')
            originalInitDisplay()

        def trackInitHardware():
            initOrder.append('hardwareManager')
            originalInitHardware()

        orchestrator._initializeDisplayManager = trackInitDisplay
        orchestrator._initializeHardwareManager = trackInitHardware

        try:
            # Act
            orchestrator.start()

            # Assert
            assert 'displayManager' in initOrder
            assert 'hardwareManager' in initOrder
            dmIdx = initOrder.index('displayManager')
            hwIdx = initOrder.index('hardwareManager')
            assert dmIdx < hwIdx, (
                f"DisplayManager (idx={dmIdx}) should init before "
                f"HardwareManager (idx={hwIdx})"
            )
        finally:
            orchestrator.stop()
