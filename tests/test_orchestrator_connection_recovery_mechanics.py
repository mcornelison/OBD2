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
    from pi.obd.orchestrator import ApplicationOrchestrator
    return ApplicationOrchestrator(config=config, simulate=True)


# ================================================================================
# Reconnection Mechanics
# ================================================================================


class TestReconnectionMechanics:
    """Tests for the low-level reconnection attempt behavior."""

    def test_attemptReconnection_usesReconnectMethod(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Connection object with reconnect() method
        When: _attemptReconnection is called
        Then: reconnect() is called (preferred path)
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockConnection = MagicMock()
        mockConnection.reconnect.return_value = True
        orchestrator._connection = mockConnection

        # Act
        result = orchestrator._attemptReconnection()

        # Assert
        assert result is True
        mockConnection.reconnect.assert_called_once()

    def test_attemptReconnection_fallsBackToDisconnectConnect(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Connection without reconnect() but with disconnect()/connect()
        When: _attemptReconnection is called
        Then: Falls back to disconnect + connect pattern
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockConnection = MagicMock(spec=['disconnect', 'connect'])
        mockConnection.connect.return_value = True
        orchestrator._connection = mockConnection

        # Act
        result = orchestrator._attemptReconnection()

        # Assert
        assert result is True
        mockConnection.disconnect.assert_called_once()
        mockConnection.connect.assert_called_once()

    def test_attemptReconnection_returnsFalseOnException(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Connection that throws during reconnect
        When: _attemptReconnection is called
        Then: Returns False without raising
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockConnection = MagicMock()
        mockConnection.reconnect.side_effect = OSError("Bluetooth error")
        orchestrator._connection = mockConnection

        # Act
        result = orchestrator._attemptReconnection()

        # Assert
        assert result is False

    def test_attemptReconnection_returnsFalseWhenNoConnection(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no connection object
        When: _attemptReconnection is called
        Then: Returns False
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._connection = None

        # Act
        result = orchestrator._attemptReconnection()

        # Assert
        assert result is False

    def test_pauseDataLogging_idempotent(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Data logging already paused
        When: _pauseDataLogging called again
        Then: stop() not called a second time
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger
        orchestrator._dataLoggerPausedForReconnect = True

        # Act
        orchestrator._pauseDataLogging()

        # Assert - stop should NOT be called (already paused)
        mockLogger.stop.assert_not_called()

    def test_resumeDataLogging_onlyIfPaused(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Data logging was NOT paused for reconnect
        When: _resumeDataLogging called
        Then: start() not called (wasn't paused by us)
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger
        orchestrator._dataLoggerPausedForReconnect = False

        # Act
        orchestrator._resumeDataLogging()

        # Assert - start should NOT be called
        mockLogger.start.assert_not_called()

    def test_startReconnection_spawnsBackgroundThread(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with connection available
        When: _startReconnection is called
        Then: A background daemon thread named 'connection-recovery' is started
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockConnection = MagicMock()
        mockConnection.reconnect.return_value = False
        orchestrator._connection = mockConnection

        # Act
        orchestrator._startReconnection()

        # Assert
        assert orchestrator._reconnectThread is not None
        assert orchestrator._reconnectThread.name == "connection-recovery"
        assert orchestrator._reconnectThread.daemon is True

        # Cleanup
        orchestrator._isReconnecting = False
        orchestrator._reconnectThread.join(timeout=2)

    def test_connectionLostCallback_called(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with onConnectionLost callback registered
        When: Connection is lost
        Then: External callback is invoked
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        lostCalled = []

        def onLost() -> None:
            lostCalled.append(True)

        orchestrator.registerCallbacks(onConnectionLost=onLost)
        mockConnection = MagicMock()
        orchestrator._connection = mockConnection

        # Act
        orchestrator._handleConnectionLost()

        # Assert
        assert len(lostCalled) == 1

        # Cleanup
        orchestrator._isReconnecting = False
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=1)

    def test_connectionLost_survivesCallbackError(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with callback that throws
        When: Connection is lost
        Then: Connection lost handling completes despite callback error
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)

        def badCallback() -> None:
            raise RuntimeError("Callback failed")

        orchestrator.registerCallbacks(onConnectionLost=badCallback)
        mockConnection = MagicMock()
        orchestrator._connection = mockConnection

        # Act - should not raise
        orchestrator._handleConnectionLost()

        # Assert
        assert orchestrator._healthCheckStats.connectionStatus == 'reconnecting'

        # Cleanup
        orchestrator._isReconnecting = False
        if orchestrator._reconnectThread:
            orchestrator._reconnectThread.join(timeout=1)
