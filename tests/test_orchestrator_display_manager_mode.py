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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

        displayConfig['pi']['display']['mode'] = 'headless'
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

        displayConfig['pi']['display']['mode'] = 'developer'
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

        displayConfig['pi']['display']['mode'] = 'minimal'
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
            assert passedConfig['pi']['display']['mode'] == 'minimal'

    def test_displayMode_logsMode_onSuccess(
        self, displayConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Config with display.mode = 'headless'
        When: _initializeDisplayManager() completes
        Then: Log message includes mode=headless
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
