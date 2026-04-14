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
import threading
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
# AC1: Connection loss detected within 5 seconds
# ================================================================================


class TestConnectionLossDetection:
    """Tests for connection loss detection timing and behavior."""

    def test_connectionCheckInterval_defaultsFiveSeconds(
        self, tempDb: str
    ):
        """
        Given: Config without connectionCheckIntervalSeconds
        When: Orchestrator is created
        Then: Connection check interval defaults to 5.0 seconds
        """
        # Arrange
        config = getConnectionRecoveryTestConfig(tempDb)
        del config['pi']['monitoring']['connectionCheckIntervalSeconds']

        # Act
        orchestrator = createOrchestrator(config)

        # Assert
        assert orchestrator._connectionCheckInterval == 5.0

    def test_connectionCheckInterval_configurableFromConfig(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Config with custom connectionCheckIntervalSeconds
        When: Orchestrator is created
        Then: Connection check interval matches config value
        """
        # Arrange
        recoveryConfig['pi']['monitoring']['connectionCheckIntervalSeconds'] = 3.0

        # Act
        orchestrator = createOrchestrator(recoveryConfig)

        # Assert
        assert orchestrator._connectionCheckInterval == 3.0

    def test_connectionLost_detectedByCheckConnectionStatus(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with connection that reports disconnected
        When: _checkConnectionStatus is called
        Then: Returns False
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockConnection = MagicMock()
        mockConnection.isConnected.return_value = False
        orchestrator._connection = mockConnection

        # Act
        result = orchestrator._checkConnectionStatus()

        # Assert
        assert result is False

    def test_connectionConnected_returnsTrue(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with connection that reports connected
        When: _checkConnectionStatus is called
        Then: Returns True
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockConnection = MagicMock()
        mockConnection.isConnected.return_value = True
        orchestrator._connection = mockConnection

        # Act
        result = orchestrator._checkConnectionStatus()

        # Assert
        assert result is True

    def test_connectionCheck_handlesMissingConnection(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no connection object
        When: _checkConnectionStatus is called
        Then: Returns False without error
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._connection = None

        # Act
        result = orchestrator._checkConnectionStatus()

        # Assert
        assert result is False


# ================================================================================
# AC2: Automatic reconnection with exponential backoff [1, 2, 4, 8, 16]
# ================================================================================


class TestExponentialBackoff:
    """Tests for reconnection exponential backoff behavior."""

    def test_reconnectDelays_defaultsExponentialBackoff(
        self, tempDb: str
    ):
        """
        Given: Config without retryDelays
        When: Orchestrator is created
        Then: Reconnect delays default to [1, 2, 4, 8, 16]
        """
        # Arrange
        config = getConnectionRecoveryTestConfig(tempDb)
        del config['pi']['bluetooth']['retryDelays']

        # Act
        orchestrator = createOrchestrator(config)

        # Assert
        assert orchestrator._reconnectDelays == [1, 2, 4, 8, 16]

    def test_reconnectDelays_configurableFromConfig(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Config with custom retryDelays
        When: Orchestrator is created
        Then: Reconnect delays match config values
        """
        # Arrange
        recoveryConfig['pi']['bluetooth']['retryDelays'] = [2, 4, 8]

        # Act
        orchestrator = createOrchestrator(recoveryConfig)

        # Assert
        assert orchestrator._reconnectDelays == [2, 4, 8]

    def test_reconnectionLoop_usesCorrectDelayPerAttempt(
        self, recoveryConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with [1, 2, 4, 8, 16] delays
        When: Reconnection loop runs
        Then: Each attempt logs the correct delay for its index
        """
        # Arrange
        recoveryConfig['pi']['bluetooth']['retryDelays'] = [0.01, 0.02, 0.04]
        recoveryConfig['pi']['bluetooth']['maxRetries'] = 3
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 0

        # Mock connection to always fail reconnection
        mockConnection = MagicMock()
        mockConnection.reconnect.return_value = False
        orchestrator._connection = mockConnection

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._reconnectionLoop()

        # Assert - verify each attempt logged correct delay
        assert "attempt 1/3 in 0.01s" in caplog.text
        assert "attempt 2/3 in 0.02s" in caplog.text
        assert "attempt 3/3 in 0.04s" in caplog.text

    def test_reconnectionLoop_lastDelayReusedWhenExceeded(
        self, recoveryConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with [0.01, 0.02] delays but 4 max retries
        When: Reconnection loop runs past delay array length
        Then: Last delay value is reused for remaining attempts
        """
        # Arrange
        recoveryConfig['pi']['bluetooth']['retryDelays'] = [0.01, 0.02]
        recoveryConfig['pi']['bluetooth']['maxRetries'] = 4
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 0

        mockConnection = MagicMock()
        mockConnection.reconnect.return_value = False
        orchestrator._connection = mockConnection

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._reconnectionLoop()

        # Assert - attempts 3 and 4 should use last delay (0.02s)
        assert "attempt 3/4 in 0.02s" in caplog.text
        assert "attempt 4/4 in 0.02s" in caplog.text

    def test_reconnectionLoop_interruptibleOnShutdown(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator in reconnection loop with long delays
        When: Shutdown is requested during backoff wait
        Then: Loop exits promptly without completing all attempts
        """
        from pi.obd.orchestrator import ShutdownState

        # Arrange
        recoveryConfig['pi']['bluetooth']['retryDelays'] = [10]
        recoveryConfig['pi']['bluetooth']['maxRetries'] = 5
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 0

        mockConnection = MagicMock()
        mockConnection.reconnect.return_value = False
        orchestrator._connection = mockConnection

        # Set shutdown after a brief moment
        def triggerShutdown():
            import time
            time.sleep(0.3)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown, daemon=True)
        shutdownThread.start()

        # Act
        orchestrator._reconnectionLoop()
        shutdownThread.join(timeout=2)

        # Assert - should NOT have exhausted all 5 attempts
        assert orchestrator._reconnectAttempt < 5
