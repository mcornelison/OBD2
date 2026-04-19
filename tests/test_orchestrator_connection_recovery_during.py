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
# AC4: During reconnection - logging paused, display 'Reconnecting...', alerts paused
# ================================================================================


class TestDuringReconnection:
    """Tests for system behavior during active reconnection."""

    def test_dataLoggingPaused_onReconnectionStart(
        self, recoveryConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with active data logger
        When: Reconnection starts
        Then: Data logger is stopped and pause flag is set
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger
        mockConnection = MagicMock()
        orchestrator._connection = mockConnection

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._pauseDataLogging()

        # Assert
        mockLogger.stop.assert_called_once()
        assert orchestrator._dataLoggerPausedForReconnect is True
        assert "Data logging paused during reconnection" in caplog.text

    def test_displayShowsReconnecting_onConnectionLost(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: Connection is lost
        Then: Display shows 'Reconnecting...'
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        mockConnection = MagicMock()
        orchestrator._connection = mockConnection

        # Act
        orchestrator._handleConnectionLost()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_with('Reconnecting...')

        # Cleanup
        orchestrator._isReconnecting = False
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=1)

    def test_alertsPaused_duringReconnection(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator that starts reconnection
        When: _startReconnection is called
        Then: Alerts are paused (flag set)
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockConnection = MagicMock()
        orchestrator._connection = mockConnection

        # Act
        orchestrator._startReconnection()

        # Assert
        assert orchestrator._alertsPausedForReconnect is True

        # Cleanup
        orchestrator._isReconnecting = False
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=1)

    def test_alertsNotChecked_whenReconnecting(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator in reconnecting state with alerts paused
        When: A reading comes in via _handleReading
        Then: alertManager.checkValue is NOT called
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager
        orchestrator._alertsPausedForReconnect = True

        # Create mock reading
        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 7500  # Would normally trigger alert
        mockReading.unit = 'rpm'

        # Act
        orchestrator._handleReading(mockReading)

        # Assert - alert manager should NOT be called
        mockAlertManager.checkValue.assert_not_called()

    def test_alertsChecked_whenNotReconnecting(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator NOT in reconnecting state
        When: A reading comes in via _handleReading
        Then: alertManager.checkValue IS called
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager
        orchestrator._alertsPausedForReconnect = False

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 3000
        mockReading.unit = 'rpm'

        # Act
        orchestrator._handleReading(mockReading)

        # Assert - alert manager SHOULD be called
        mockAlertManager.checkValue.assert_called_once_with('RPM', 3000)

    def test_noDoubleReconnection_ifAlreadyReconnecting(
        self, recoveryConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator already in reconnecting state
        When: _startReconnection is called again
        Then: Skipped with debug log, no second thread started
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True
        originalThread = orchestrator._reconnectThread

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._startReconnection()

        # Assert
        assert "already in progress" in caplog.text
        assert orchestrator._reconnectThread == originalThread

    def test_startReconnection_skipsWhenNoConnection(
        self, recoveryConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with no connection object
        When: _startReconnection is called
        Then: Logged warning and return without starting
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._connection = None

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._startReconnection()

        # Assert
        assert "no connection object" in caplog.text
        assert orchestrator._isReconnecting is False
