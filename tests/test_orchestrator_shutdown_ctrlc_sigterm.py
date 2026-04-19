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
# AC4: Double Ctrl+C forces immediate exit
# ================================================================================


@pytest.mark.integration
class TestDoubleCtrlCForceExit:
    """Tests that double Ctrl+C forces immediate exit."""

    def test_shutdown_secondSignalSetsForceExitState(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator in SHUTDOWN_REQUESTED state (first Ctrl+C received)
        When: Second SIGINT is received
        Then: ShutdownState changes to FORCE_EXIT
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act - second signal should force exit
        with pytest.raises(SystemExit) as excInfo:
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        assert orchestrator._shutdownState == ShutdownState.FORCE_EXIT
        assert excInfo.value.code != 0

    def test_shutdown_firstSignalSetsShutdownRequested(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator (RUNNING state)
        When: First SIGINT is received
        Then: ShutdownState changes to SHUTDOWN_REQUESTED
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        assert orchestrator._shutdownState == ShutdownState.RUNNING

        # Act
        orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        assert orchestrator._shutdownState == ShutdownState.SHUTDOWN_REQUESTED

    def test_shutdown_forceExitSkipsGracefulShutdown(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator in FORCE_EXIT state
        When: stop() is called
        Then: Graceful shutdown is skipped, returns non-zero exit code
        """
        # Arrange
        from pi.obdii.orchestrator import (
            EXIT_CODE_FORCED,
            ApplicationOrchestrator,
            ShutdownState,
        )

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()
        orchestrator._shutdownState = ShutdownState.FORCE_EXIT

        # Act
        with caplog.at_level(logging.WARNING):
            exitCode = orchestrator.stop()

        # Assert
        assert exitCode == EXIT_CODE_FORCED
        warningMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING
        ]
        assert any(
            "Force exit" in msg or "force exit" in msg.lower()
            for msg in warningMessages
        )

    def test_shutdown_forceExitSetsNonZeroExitCode(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Second signal received during shutdown
        When: Checking exit code
        Then: Exit code is EXIT_CODE_FORCED (non-zero)
        """
        # Arrange
        from pi.obdii.orchestrator import (
            EXIT_CODE_FORCED,
            ApplicationOrchestrator,
            ShutdownState,
        )

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act - force exit
        with pytest.raises(SystemExit):
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        assert orchestrator._exitCode == EXIT_CODE_FORCED


# ================================================================================
# AC5: SIGTERM handled same as SIGINT
# ================================================================================


@pytest.mark.integration
class TestSigtermHandling:
    """Tests that SIGTERM is handled the same as SIGINT."""

    def test_shutdown_sigtermTriggersGracefulShutdown(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: SIGTERM is received
        Then: ShutdownState changes to SHUTDOWN_REQUESTED (same as SIGINT)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        # Act - simulate SIGTERM (use SIGINT value on Windows where SIGTERM
        # may not be fully supported, but test the handler logic)
        if hasattr(signal, 'SIGTERM'):
            orchestrator._handleShutdownSignal(signal.SIGTERM, None)
        else:
            # On Windows, SIGTERM may not be available; test with SIGINT
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        assert orchestrator._shutdownState == ShutdownState.SHUTDOWN_REQUESTED

    def test_shutdown_registersBothSigintAndSigterm(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator instance
        When: registerSignalHandlers() is called
        Then: Both SIGINT handler is registered (SIGTERM if available)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        # Act
        orchestrator.registerSignalHandlers()

        try:
            # Assert - SIGINT handler should be our handler
            currentHandler = signal.getsignal(signal.SIGINT)
            assert currentHandler == orchestrator._handleShutdownSignal

            # SIGTERM (if available on platform)
            if hasattr(signal, 'SIGTERM'):
                currentHandler = signal.getsignal(signal.SIGTERM)
                assert currentHandler == orchestrator._handleShutdownSignal
        finally:
            orchestrator.restoreSignalHandlers()

    def test_shutdown_restoresOriginalSignalHandlers(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with registered signal handlers
        When: restoreSignalHandlers() is called
        Then: Original signal handlers are restored
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        originalSigint = signal.getsignal(signal.SIGINT)

        orchestrator.registerSignalHandlers()

        # Verify handler is ours
        assert signal.getsignal(signal.SIGINT) == orchestrator._handleShutdownSignal

        # Act
        orchestrator.restoreSignalHandlers()

        # Assert - handler should be restored to original
        restoredHandler = signal.getsignal(signal.SIGINT)
        assert restoredHandler == originalSigint

    def test_shutdown_signalHandlerLogsSignalName(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: A shutdown signal is received
        Then: Signal name is logged (e.g., 'Received signal SIGINT')
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        infoMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.INFO
        ]
        assert any(
            "Received signal" in msg and "SIGINT" in msg
            for msg in infoMessages
        ), f"Expected 'Received signal SIGINT' log, got: {infoMessages}"
