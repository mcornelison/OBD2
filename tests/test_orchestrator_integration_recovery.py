################################################################################
# File Name: test_orchestrator_integration.py
# Purpose/Description: Integration tests for ApplicationOrchestrator with simulator
# Author: Ralph Agent
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-23    | Ralph Agent  | Initial implementation for US-OSC-015
# 2026-04-11    | Ralph Agent  | US-OSC-015: Add connection recovery tests (AC8)
#               |              | and profile switch tests (AC9) — 9 new tests
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Integration tests for ApplicationOrchestrator in simulator mode.

Tests the orchestrator's ability to start, run, and stop with all components
integrated together using simulated OBD-II connections. These tests verify
the end-to-end functionality of the system without requiring hardware.

Test coverage includes:
- Orchestrator startup in simulator mode
- Graceful shutdown on signal
- Data logging to database during simulated operations
- Drive detection triggering on RPM changes
- Statistics calculation after drive ends
- Alert triggering on threshold violations
- Temporary database usage (not production)

Usage:
    pytest tests/test_orchestrator_integration.py -v
    pytest tests/test_orchestrator_integration.py -v --timeout=120
"""

import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getIntegrationTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for integration tests.

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
                'name': 'Integration Test',
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
                'pollingIntervalMs': 100,  # Fast polling for tests
                'parameters': [
                    {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'COOLANT_TEMP', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'ENGINE_LOAD', 'logData': True, 'displayOnDashboard': False},
                    {'name': 'THROTTLE_POS', 'logData': True, 'displayOnDashboard': False}
                ]
            },
            'analysis': {
                'triggerAfterDrive': True,
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 1,  # Short for tests
                'driveEndRpmThreshold': 100,
                'driveEndDurationSeconds': 1,  # Short for tests
                'calculateStatistics': ['max', 'min', 'avg']
            },
            'profiles': {
                'activeProfile': 'test',
                'availableProfiles': [
                    {
                        'id': 'test',
                        'name': 'Test Profile',
                        'description': 'Profile for integration tests',
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
                'cooldownSeconds': 1,  # Short for tests
                'visualAlerts': False,
                'audioAlerts': False,
                'logAlerts': True
            },
            'monitoring': {
                'healthCheckIntervalSeconds': 2,  # Short for tests
                'dataRateLogIntervalSeconds': 5
            },
            'shutdown': {
                'componentTimeout': 2  # Short for tests
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
    """
    Create a temporary database file for testing.

    Yields:
        Path to temporary database file

    Automatically cleaned up after test.
    """
    # Use file-based temp database (not :memory:) for proper testing
    fd, dbPath = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    yield dbPath

    # Cleanup
    try:
        os.unlink(dbPath)
    except OSError:
        pass


@pytest.fixture
def integrationConfig(tempDb: str) -> dict[str, Any]:
    """
    Create integration test configuration with temp database.

    Args:
        tempDb: Temporary database path fixture

    Returns:
        Test configuration dictionary
    """
    return getIntegrationTestConfig(tempDb)


# ================================================================================
# Additional Integration Tests
# ================================================================================


@pytest.mark.integration
class TestConnectionStateMonitoring:
    """Tests for connection state monitoring."""

    def test_orchestrator_detectsConnectionState_initially(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with simulated connection
        When: Connection status is checked
        Then: Returns valid state (connected or disconnected)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            isConnected = orchestrator._checkConnectionStatus()

            # Assert - should be boolean
            assert isinstance(isConnected, bool)

        finally:
            orchestrator.stop()

    def test_orchestrator_callsConnectionLostCallback(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with connection lost callback registered
        When: Connection lost handler is called
        Then: External callback is invoked and status shows 'reconnecting'
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        connectionLostCalled = []

        def onConnectionLost() -> None:
            connectionLostCalled.append(True)

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(onConnectionLost=onConnectionLost)

            # Act
            orchestrator._handleConnectionLost()

            # Assert
            assert len(connectionLostCalled) == 1
            # Connection lost now triggers automatic reconnection
            assert orchestrator._healthCheckStats.connectionStatus == 'reconnecting'

        finally:
            # Stop reconnection thread before stopping orchestrator
            orchestrator._isReconnecting = False
            if orchestrator._reconnectThread:
                orchestrator._reconnectThread.join(timeout=0.5)
            orchestrator.stop()


# ================================================================================
# Test: Connection recovery works on simulated disconnect
# ================================================================================


@pytest.mark.integration
class TestConnectionRecoveryOnSimulatedDisconnect:
    """Tests for connection recovery on simulated disconnect."""

    def test_orchestrator_setsReconnectingState_onConnectionLost(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with active connection
        When: Connection is lost
        Then: Status transitions to 'reconnecting' and reconnect flag is set
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            orchestrator._handleConnectionLost()

            # Assert
            assert orchestrator._healthCheckStats.connectionStatus == 'reconnecting'
            assert orchestrator._healthCheckStats.connectionConnected is False
            assert orchestrator._isReconnecting is True

        finally:
            orchestrator._isReconnecting = False
            if orchestrator._reconnectThread:
                orchestrator._reconnectThread.join(timeout=1)
            orchestrator.stop()

    def test_orchestrator_recoversConnection_onSuccessfulReconnect(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator in reconnecting state
        When: Reconnection attempt succeeds
        Then: Status returns to 'connected' and reconnect state is cleared
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Simulate being in a reconnecting state
            orchestrator._isReconnecting = True
            orchestrator._reconnectAttempt = 1
            orchestrator._healthCheckStats.connectionStatus = 'reconnecting'
            orchestrator._healthCheckStats.connectionConnected = False

            # Act - simulate successful reconnection
            orchestrator._handleReconnectionSuccess()

            # Assert
            assert orchestrator._isReconnecting is False
            assert orchestrator._reconnectAttempt == 0
            assert orchestrator._healthCheckStats.connectionStatus == 'connected'
            assert orchestrator._healthCheckStats.connectionConnected is True

        finally:
            orchestrator.stop()

    def test_orchestrator_callsRestoredCallback_onSuccessfulReconnect(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with connection restored callback registered
        When: Reconnection succeeds
        Then: External callback is invoked
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        restoredCalled = []

        def onConnectionRestored() -> None:
            restoredCalled.append(True)

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(
                onConnectionRestored=onConnectionRestored
            )
            orchestrator._isReconnecting = True
            orchestrator._reconnectAttempt = 1

            # Act
            orchestrator._handleReconnectionSuccess()

            # Assert
            assert len(restoredCalled) == 1

        finally:
            orchestrator.stop()

    def test_orchestrator_handlesReconnectionFailure_afterMaxRetries(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator that has exhausted reconnection attempts
        When: Max retries exceeded
        Then: Status set to 'disconnected', system continues running
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            orchestrator._isReconnecting = True

            # Act
            orchestrator._handleReconnectionFailure()

            # Assert
            assert orchestrator._isReconnecting is False
            assert orchestrator._healthCheckStats.connectionStatus == 'disconnected'
            assert orchestrator._healthCheckStats.connectionConnected is False
            # System should still be running
            assert orchestrator.isRunning() is True

        finally:
            orchestrator.stop()

    def test_orchestrator_attemptsReconnect_withMockedConnection(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with connection that supports reconnect()
        When: _attemptReconnection is called
        Then: Reconnect method is called on the connection object
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Mock connection.reconnect to return True
            if orchestrator._connection is not None:
                orchestrator._connection.reconnect = MagicMock(
                    return_value=True
                )

                # Act
                result = orchestrator._attemptReconnection()

                # Assert
                assert result is True
                orchestrator._connection.reconnect.assert_called_once()

        finally:
            orchestrator.stop()
