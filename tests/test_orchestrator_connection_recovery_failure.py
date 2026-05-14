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
from unittest.mock import MagicMock, patch

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
# AC6: On max retries exceeded - log error, display 'Connection Failed', continue
# ================================================================================


class TestReconnectionFailure:
    """Tests for behavior when reconnection fails after max retries."""

    def test_errorLogged_onMaxRetriesExceeded(
        self, recoveryConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator that has exhausted reconnection attempts
        When: _handleReconnectionFailure is called
        Then: Error message logged with attempt count
        """
        # Arrange
        recoveryConfig['pi']['bluetooth']['maxRetries'] = 5
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True

        # Act
        with caplog.at_level(logging.ERROR):
            orchestrator._handleReconnectionFailure()

        # Assert
        assert "Connection recovery failed after 5 attempts" in caplog.text

    def test_displayShowsConnectionFailed_onMaxRetries(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: Reconnection fails after max retries
        Then: Display shows 'Connection Failed'
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay
        orchestrator._isReconnecting = True

        # Act
        orchestrator._handleReconnectionFailure()

        # Assert
        mockDisplay.showConnectionStatus.assert_called_with('Connection Failed')

    def test_systemContinuesRunning_afterMaxRetries(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator that exhausts reconnection
        When: _handleReconnectionFailure is called
        Then: System is still running (not crashed or stopped)
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._running = True
        orchestrator._isReconnecting = True

        # Act
        orchestrator._handleReconnectionFailure()

        # Assert
        assert orchestrator._running is True

    def test_totalErrorsIncremented_onReconnectionFailure(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with 0 total errors
        When: Reconnection fails
        Then: Total errors incremented by 1
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True
        initialErrors = orchestrator._healthCheckStats.totalErrors

        # Act
        orchestrator._handleReconnectionFailure()

        # Assert
        assert orchestrator._healthCheckStats.totalErrors == initialErrors + 1

    def test_dataLoggingRemainsPaused_afterFailure(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with data logging paused for reconnection
        When: Reconnection fails
        Then: Data logging remains paused (no connection = no logging)
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._dataLoggerPausedForReconnect = True
        orchestrator._isReconnecting = True

        # Act
        orchestrator._handleReconnectionFailure()

        # Assert - logging should remain paused since no connection
        assert orchestrator._dataLoggerPausedForReconnect is True

    def test_reconnectionFailure_survivesDisplayError(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display that throws on update
        When: Reconnection fails
        Then: Failure handling completes despite display error
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        mockDisplay = MagicMock()
        mockDisplay.showConnectionStatus.side_effect = RuntimeError("Display broken")
        orchestrator._displayManager = mockDisplay
        orchestrator._isReconnecting = True

        # Act - should not raise
        orchestrator._handleReconnectionFailure()

        # Assert
        assert orchestrator._isReconnecting is False
        assert orchestrator._healthCheckStats.connectionStatus == 'disconnected'


# ================================================================================
# US-338 / I-033 (2026-05-13): post-failure reconnect heartbeat
# ================================================================================
#
# Pre-V0.27.10, _handleReconnectionFailure was a dead-end: after the bounded
# [1,2,4,8,16]s x 5-attempt budget exhausted (~3 min), the method set
# _isReconnecting=False and returned with NO further retry mechanism. The main
# runLoop's _checkConnectionStatus() then returned False indefinitely
# (self.obd was None / DISCONNECTED), so the True->False state transition
# never re-fired and _handleConnectionRestored() was never invoked.
#
# 2026-05-13 production failure (drive 12, pharmacy stop, multi-leg trip):
# engine-off dropped BT, the bounded reconnect loop exhausted while the Pi
# sat parked on fuse-box power, and when engine-on re-armed the adapter for
# the return leg, NOTHING in the process tried to connect again. Drive 13
# was silently lost (0 connect_attempt rows in connection_log between
# drive_end at 19:10:24Z and the next ~30 min).
#
# Fix: _handleReconnectionFailure now spawns a long-lived daemon thread
# running runReconnectHeartbeat (the US-301 / V0.27.1 / US-325 heartbeat that
# has exponential backoff up to 15 min and never gives up). When the adapter
# eventually returns, the heartbeat's connect() succeeds, the heartbeat
# exits, and the main runLoop's next state-transition pass picks up the
# False->True transition naturally and fires _handleConnectionRestored().
# ================================================================================


class TestUS338PostFailureHeartbeat:
    """Tests for the US-338 / I-033 post-failure reconnect heartbeat."""

    def test_runReconnectHeartbeatIsInvoked_afterReconnectionFailure(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator that has exhausted the bounded reconnect attempts
        When: _handleReconnectionFailure is called
        Then: runReconnectHeartbeat is invoked on a daemon thread within 2s,
              wired to the connection's connect / isConnected methods
              (regression for I-033 -- pre-fix, the failure handler was a
              silent dead-end and the daemon thread was never spawned).
        """
        # Arrange
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True
        # The orchestrator's _connection is wired by _initializeConnection
        # during runLoop startup; in unit tests we bypass runLoop and
        # inject a mock directly so the failure-handler-spawned heartbeat
        # has a deterministic connect/isConnected/isConnectInFlight surface
        # to wire to.
        mockConn = MagicMock()
        mockConn.isConnectInFlight.return_value = False
        orchestrator._connection = mockConn

        spawned_kwargs: dict[str, Any] = {}
        spawned_event = threading.Event()
        spawned_thread_holder: dict[str, threading.Thread] = {}

        def fake_runReconnectHeartbeat(**kwargs: Any) -> int:
            # Record args so the test can verify wiring.
            spawned_kwargs.update(kwargs)
            spawned_thread_holder['t'] = threading.current_thread()
            spawned_event.set()
            return 0  # exit immediately so the daemon thread terminates

        # Patch at the connection_recovery module since that's where the
        # symbol is resolved at call time (module-level import).
        with patch(
            'pi.obdii.orchestrator.connection_recovery.runReconnectHeartbeat',
            side_effect=fake_runReconnectHeartbeat,
        ):
            # Act
            orchestrator._handleReconnectionFailure()

            # Wait for the daemon thread to invoke the patched heartbeat.
            assert spawned_event.wait(timeout=2.0), (
                "US-338 regression: _handleReconnectionFailure did NOT spawn "
                "a thread that invokes runReconnectHeartbeat. Pre-fix the "
                "failure handler was a silent dead-end."
            )

        # Assert: ran on a DIFFERENT thread (daemon), not the test thread.
        assert spawned_thread_holder['t'] is not threading.main_thread(), (
            "Heartbeat must run on a background daemon thread so the main "
            "loop can keep ticking and pick up state transitions."
        )
        assert spawned_thread_holder['t'].daemon is True, (
            "Heartbeat thread must be daemon=True so it does not block "
            "process exit."
        )

        # Assert: wired to the LIVE connection so a successful tick affects
        # orchestrator state.  bound-method identity is the cheapest probe.
        assert 'connectFn' in spawned_kwargs and 'isConnectedFn' in spawned_kwargs
        assert spawned_kwargs['connectFn'] == orchestrator._connection.connect
        assert spawned_kwargs['isConnectedFn'] == orchestrator._connection.isConnected

    def test_postFailureHeartbeat_isIdempotent_whenThreadAlreadyAlive(
        self, recoveryConfig: dict[str, Any]
    ):
        """
        Given: A post-failure heartbeat is already running (1st failure)
        When: _handleReconnectionFailure fires a 2nd time
        Then: A second heartbeat thread is NOT spawned -- the existing one
              keeps running.  Prevents thread churn if the failure handler
              gets called twice (e.g., from health-check + state-transition
              both firing).
        """
        orchestrator = createOrchestrator(recoveryConfig)
        orchestrator._isReconnecting = True
        mockConn = MagicMock()
        mockConn.isConnectInFlight.return_value = False
        orchestrator._connection = mockConn

        invocations: list[dict[str, Any]] = []
        invocations_done = threading.Event()
        # Block the first heartbeat call so it "stays alive" while we fire
        # the second _handleReconnectionFailure.
        release_first_call = threading.Event()

        def fake_runReconnectHeartbeat(**kwargs: Any) -> int:
            invocations.append(kwargs)
            invocations_done.set()
            # Hold the first invocation open until the test releases it.
            release_first_call.wait(timeout=2.0)
            return 0

        try:
            with patch(
                'pi.obdii.orchestrator.connection_recovery.runReconnectHeartbeat',
                side_effect=fake_runReconnectHeartbeat,
            ):
                # 1st failure: spawns the heartbeat
                orchestrator._handleReconnectionFailure()
                assert invocations_done.wait(timeout=2.0), "1st spawn missed"

                # Reset for the 2nd call's bookkeeping
                orchestrator._isReconnecting = True

                # 2nd failure: must NOT spawn a second heartbeat thread
                # because the first one is still alive (mid-call).
                orchestrator._handleReconnectionFailure()

                # Give any rogue 2nd thread a moment to fire.
                import time as _time
                _time.sleep(0.2)

                assert len(invocations) == 1, (
                    f"Expected exactly 1 heartbeat invocation across two "
                    f"failure-handler calls; got {len(invocations)}.  "
                    f"Idempotency broken -- a 2nd heartbeat would race the "
                    f"first against the connection's _connectLock."
                )
        finally:
            release_first_call.set()
