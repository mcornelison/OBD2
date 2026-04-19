################################################################################
# File Name: test_orchestrator_connection_recovery.py
# Purpose/Description: Tests for orchestrator connection recovery wiring (US-OSC-012)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-012
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator connection recovery wiring.

Verifies that the orchestrator correctly:
- Detects connection loss within configured interval (default 5 seconds)
- Attempts automatic reconnection with exponential backoff: [1, 2, 4, 8, 16]
- Limits retry attempts from config (default 5)
- Pauses logging, display shows 'Reconnecting...', alerts paused during reconnection
- On success: resumes logging, display 'Connected', log restore event
- On max retries exceeded: log error, display 'Connection Failed', system continues
- Passes typecheck and lint

Usage:
    pytest tests/test_orchestrator_connection_recovery.py -v
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


def getConnectionRecoveryTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for connection recovery tests.

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
                'name': 'Connection Recovery Test',
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
                'retryDelays': [1, 2, 4, 8, 16],
                'maxRetries': 5,
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
                'dataRateLogIntervalSeconds': 5,
                'connectionCheckIntervalSeconds': 5
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
    with tempfile.NamedTemporaryFile(
        suffix='.db', delete=False, dir=tempfile.gettempdir()
    ) as f:
        dbPath = f.name
    yield dbPath
    # Cleanup
    for suffix in ['', '-wal', '-shm']:
        path = dbPath + suffix
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass


@pytest.fixture
def recoveryConfig(tempDb: str) -> dict[str, Any]:
    """Create test config with temporary database."""
    return getConnectionRecoveryTestConfig(tempDb)


def createOrchestrator(config: dict[str, Any]) -> Any:
    """Create an orchestrator instance for testing."""
    from pi.obdii.orchestrator import ApplicationOrchestrator
    return ApplicationOrchestrator(config=config, simulate=True)


# ================================================================================
# AC5: On successful reconnection - resume logging, display 'Connected', log event
# ================================================================================


class TestReconnectionSuccess:
    """Tests for behavior after successful reconnection."""

    def test_dataLoggingResumed_onReconnectionSuccess(
        self, recoveryConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with data logging paused for reconnection
        When: Reconnection succeeds
        Then: Data logging is resumed
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger
        orchestrator._dataLoggerPausedForReconnect = True
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 1

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._handleReconnectionSuccess()

        # Assert
        mockLogger.start.assert_called_once()
        assert orchestrator._dataLoggerPausedForReconnect is False
        assert "Data logging resumed after reconnection" in caplog.text

    def test_alertsResumed_onReconnectionSuccess(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alerts paused for reconnection
        When: Reconnection succeeds
        Then: Alerts are resumed (flag cleared)
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._alertsPausedForReconnect = True
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 1

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        assert orchestrator._alertsPausedForReconnect is False

    def test_displayShowsConnected_onReconnectionSuccess(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: Reconnection succeeds
        Then: Display shows 'Connected'
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 2

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_with('Connected')

    def test_restoreEventLogged_onReconnectionSuccess(
        self, recoveryConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator recovering from connection loss
        When: Reconnection succeeds after 3 attempts
        Then: Log message includes attempt count
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 3

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._handleReconnectionSuccess()

        # Assert
        assert "Connection recovered successfully after 3 attempt(s)" in caplog.text

    def test_externalCallbackCalled_onReconnectionSuccess(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with onConnectionRestored callback registered
        When: Reconnection succeeds
        Then: External callback is invoked
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        restoredCalled = []

        def onRestored() -> None:
            restoredCalled.append(True)

        orchestrator.registerCallbacks(onConnectionRestored=onRestored)
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 1

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        assert len(restoredCalled) == 1

    def test_reconnectStateCleared_onSuccess(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator in reconnecting state
        When: Reconnection succeeds
        Then: All reconnection state is cleared
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 4
        orchestrator._healthCheckStats.connectionStatus = 'reconnecting'
        orchestrator._healthCheckStats.connectionConnected = False

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert
        assert orchestrator._isReconnecting is False
        assert orchestrator._reconnectAttempt == 0
        assert orchestrator._healthCheckStats.connectionStatus == 'connected'
        assert orchestrator._healthCheckStats.connectionConnected is True

    def test_reconnectionSuccess_survivesDisplayError(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display that throws on update
        When: Reconnection succeeds
        Then: Success handling completes despite display error
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockDisplay = MagicMock()
        mockDisplay.showConnectionStatus.side_effect = RuntimeError("Display broken")
        orchestrator._displayManager = mockDisplay
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 1

        # Act - should not raise
        orchestrator._handleReconnectionSuccess()

        # Assert
        assert orchestrator._isReconnecting is False
        assert orchestrator._healthCheckStats.connectionStatus == 'connected'

    def test_reconnectionSuccess_survivesCallbackError(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with callback that throws
        When: Reconnection succeeds
        Then: Success handling completes despite callback error
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)

        def badCallback() -> None:
            raise RuntimeError("Callback exploded")

        orchestrator.registerCallbacks(onConnectionRestored=badCallback)
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 1

        # Act - should not raise
        orchestrator._handleReconnectionSuccess()

        # Assert
        assert orchestrator._isReconnecting is False
