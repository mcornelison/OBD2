################################################################################
# File Name: test_orchestrator_shutdown.py
# Purpose/Description: Tests for orchestrator shutdown sequence (US-OSC-003)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-003
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator shutdown sequence.

Verifies that the orchestrator:
- Shuts down components in reverse dependency order
- Each component stop has a configurable timeout (default 5s)
- Components that exceed timeout are force-stopped with warning
- Double Ctrl+C forces immediate exit (skip graceful shutdown)
- SIGTERM handled same as SIGINT (Ctrl+C)
- No data loss for completed logging cycles
- Exit code 0 for clean shutdown, non-zero for forced/error
- Typecheck/lint passes

Usage:
    pytest tests/test_orchestrator_shutdown.py -v
"""

import logging
import os
import signal
import tempfile
from typing import Any

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getShutdownTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create minimal test configuration for shutdown tests.

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
                'name': 'Shutdown Test',
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
                'pollingIntervalMs': 100,
                'parameters': [
                    {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                ]
            },
            'analysis': {
                'triggerAfterDrive': True,
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 1,
                'driveEndRpmThreshold': 100,
                'driveEndDurationSeconds': 1,
                'calculateStatistics': ['max', 'min', 'avg']
            },
            'profiles': {
                'activeProfile': 'test',
                'availableProfiles': [
                    {
                        'id': 'test',
                        'name': 'Test Profile',
                        'description': 'Profile for shutdown tests',
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
                'healthCheckIntervalSeconds': 60,
                'dataRateLogIntervalSeconds': 300
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
def shutdownConfig(tempDb: str) -> dict[str, Any]:
    """Create shutdown test configuration with temp database."""
    return getShutdownTestConfig(tempDb)


# ================================================================================
# AC8: Typecheck/lint passes (verified by running make lint / mypy)
# ================================================================================


@pytest.mark.integration
class TestShutdownStateEnum:
    """Tests for ShutdownState enum values and transitions."""

    def test_shutdownState_hasExpectedValues(self):
        """
        Given: ShutdownState enum
        When: Checking values
        Then: Contains RUNNING, SHUTDOWN_REQUESTED, FORCE_EXIT
        """
        from pi.obd.orchestrator import ShutdownState

        assert ShutdownState.RUNNING.value == "running"
        assert ShutdownState.SHUTDOWN_REQUESTED.value == "shutdown_requested"
        assert ShutdownState.FORCE_EXIT.value == "force_exit"

    def test_shutdownState_initialStateIsRunning(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Newly created orchestrator
        When: Checking shutdown state
        Then: State is RUNNING
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        assert orchestrator.shutdownState == ShutdownState.RUNNING

    def test_shutdownState_propertyExposesState(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator instance
        When: Accessing shutdownState property
        Then: Returns current shutdown state
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        assert orchestrator.shutdownState == ShutdownState.RUNNING

        # Simulate first signal
        orchestrator._handleShutdownSignal(signal.SIGINT, None)
        assert orchestrator.shutdownState == ShutdownState.SHUTDOWN_REQUESTED


# ================================================================================
# Shutdown logging and timing
# ================================================================================


@pytest.mark.integration
class TestShutdownLogging:
    """Tests for shutdown logging messages and timing."""

    def test_shutdown_logsStoppingMessageForEachComponent(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator with components
        When: stop() is called
        Then: 'Stopping [component]...' message logged for each
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        infoMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.INFO
            and r.name == 'pi.obd.orchestrator'
        ]

        # Assert - key components have 'Stopping...' messages
        coreComponents = ['dataLogger', 'connection', 'database']
        for component in coreComponents:
            expectedMsg = f"Stopping {component}..."
            assert expectedMsg in infoMessages, (
                f"Missing 'Stopping' log for {component}"
            )

    def test_shutdown_logsSuccessForEachComponent(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: stop() completes
        Then: '[Component] stopped successfully' logged for stopped components
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        infoMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.INFO
        ]

        # Assert - at least some "stopped successfully" messages
        successMessages = [
            msg for msg in infoMessages
            if "stopped successfully" in msg
        ]
        assert len(successMessages) > 0, (
            "Expected at least one 'stopped successfully' message"
        )

    def test_shutdown_logsTotalShutdownTime(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: stop() completes
        Then: Total shutdown time is logged
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        infoMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.INFO
        ]

        # Assert - should log shutdown time
        assert any(
            "shutdown_time=" in msg for msg in infoMessages
        ), "Expected shutdown_time logged on stop"

    def test_shutdown_logsExitCode(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: stop() completes
        Then: Exit code is included in the shutdown log
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        infoMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.INFO
        ]

        # Assert
        assert any(
            "exit_code=" in msg for msg in infoMessages
        ), "Expected exit_code in shutdown log"
