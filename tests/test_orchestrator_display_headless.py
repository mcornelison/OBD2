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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
            mockFactory.return_value = mockManager

            # Act
            orchestrator._createHeadlessDisplayFallback()

            # Assert
            passedConfig = mockFactory.call_args[0][0]
            assert passedConfig['pi']['display']['mode'] == 'headless'

    def test_createHeadlessDisplayFallback_initializesManager(
        self, displayConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator config
        When: _createHeadlessDisplayFallback() is called
        Then: Returned manager is initialized
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import (
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
