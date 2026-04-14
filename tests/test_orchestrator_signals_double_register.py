################################################################################
# File Name: test_orchestrator_signals.py
# Purpose/Description: Tests for orchestrator signal handling (US-OSC-004)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-004
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator signal handling.

Verifies that the orchestrator:
- AC1: SIGINT (Ctrl+C) triggers graceful shutdown
- AC2: SIGTERM triggers graceful shutdown (for systemd stop)
- AC3: Second SIGINT/SIGTERM forces immediate exit
- AC4: Signal handlers registered in main() before starting orchestrator
- AC5: Original signal handlers restored on shutdown
- AC6: Signal received logged: 'Received signal [SIGNAME], initiating shutdown'
- AC7: Works correctly on both Windows and Linux
- AC8: Typecheck/lint passes

Usage:
    pytest tests/test_orchestrator_signals.py -v
"""

import os
import signal
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getSignalTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create minimal test configuration for signal handler tests.

    Args:
        dbPath: Path to temporary database file

    Returns:
        Configuration dictionary for orchestrator
    """
    return {
        'application': {
            'name': 'Signal Test',
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
        'aiAnalysis': {
            'enabled': False
        },
        'profiles': {
            'activeProfile': 'test',
            'availableProfiles': [
                {
                    'id': 'test',
                    'name': 'Test Profile',
                    'description': 'Profile for signal tests',
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
        'logging': {
            'level': 'DEBUG',
            'maskPII': False
        }
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
def signalConfig(tempDb: str) -> dict[str, Any]:
    """Create signal test configuration with temp database."""
    return getSignalTestConfig(tempDb)


# ================================================================================
# AC3: Second SIGINT/SIGTERM forces immediate exit
# ================================================================================


@pytest.mark.integration
class TestDoubleSignalForceExit:
    """Tests that a second signal forces immediate exit."""

    def test_signals_secondSigintForcesSystemExit(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator in SHUTDOWN_REQUESTED state
        When: Second SIGINT is received
        Then: sys.exit is called (SystemExit raised)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act & Assert
        with pytest.raises(SystemExit):
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

    def test_signals_secondSigtermForcesSystemExit(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator in SHUTDOWN_REQUESTED state
        When: Second SIGTERM is received
        Then: sys.exit is called (SystemExit raised)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act & Assert - use SIGTERM if available
        signum = signal.SIGTERM if hasattr(signal, 'SIGTERM') else signal.SIGINT
        with pytest.raises(SystemExit):
            orchestrator._handleShutdownSignal(signum, None)

    def test_signals_forceExitSetsStateAndExitCode(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator in SHUTDOWN_REQUESTED state
        When: Second signal received
        Then: State is FORCE_EXIT and exit code is non-zero
        """
        # Arrange
        from pi.obd.orchestrator import (
            EXIT_CODE_FORCED,
            ApplicationOrchestrator,
            ShutdownState,
        )

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act
        with pytest.raises(SystemExit) as excInfo:
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        assert orchestrator._shutdownState == ShutdownState.FORCE_EXIT
        assert orchestrator._exitCode == EXIT_CODE_FORCED
        assert excInfo.value.code == EXIT_CODE_FORCED


# ================================================================================
# AC4: Signal handlers registered in main() before starting orchestrator
# ================================================================================


@pytest.mark.integration
class TestSignalRegistrationInMain:
    """Tests that signal handlers are registered in main() before start()."""

    def test_signals_registeredBeforeOrchestratorStart(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: runWorkflow() is called
        When: The orchestrator is set up
        Then: registerSignalHandlers() is called BEFORE start()
        """
        # Arrange - mock the orchestrator to track call order
        callOrder: list[str] = []

        mockOrchestrator = MagicMock()
        mockOrchestrator.registerSignalHandlers.side_effect = (
            lambda: callOrder.append('registerSignalHandlers')
        )
        mockOrchestrator.start.side_effect = (
            lambda: callOrder.append('start')
        )
        mockOrchestrator.runLoop.side_effect = (
            lambda: callOrder.append('runLoop')
        )
        mockOrchestrator.stop.return_value = 0
        mockOrchestrator.restoreSignalHandlers.side_effect = (
            lambda: callOrder.append('restoreSignalHandlers')
        )

        with patch(
            'pi.obd.orchestrator.createOrchestratorFromConfig',
            return_value=mockOrchestrator
        ):
            # Act
            from main import runWorkflow
            runWorkflow(signalConfig, dryRun=False, simulate=True)

        # Assert - registration MUST come before start
        assert callOrder.index('registerSignalHandlers') < callOrder.index('start'), \
            f"Expected registerSignalHandlers before start, got: {callOrder}"

    def test_signals_restoredAfterStopInMain(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: runWorkflow() is called
        When: The workflow completes
        Then: restoreSignalHandlers() is called AFTER stop()
        """
        # Arrange
        callOrder: list[str] = []

        mockOrchestrator = MagicMock()
        mockOrchestrator.registerSignalHandlers.side_effect = (
            lambda: callOrder.append('registerSignalHandlers')
        )
        mockOrchestrator.start.side_effect = (
            lambda: callOrder.append('start')
        )
        mockOrchestrator.runLoop.side_effect = (
            lambda: callOrder.append('runLoop')
        )
        mockOrchestrator.stop.side_effect = (
            lambda: (callOrder.append('stop'), 0)[1]
        )
        mockOrchestrator.restoreSignalHandlers.side_effect = (
            lambda: callOrder.append('restoreSignalHandlers')
        )

        with patch(
            'pi.obd.orchestrator.createOrchestratorFromConfig',
            return_value=mockOrchestrator
        ):
            from main import runWorkflow
            runWorkflow(signalConfig, dryRun=False, simulate=True)

        # Assert - restore comes after stop
        assert callOrder.index('stop') < callOrder.index('restoreSignalHandlers'), \
            f"Expected stop before restoreSignalHandlers, got: {callOrder}"

    def test_signals_dryRunSkipsSignalRegistration(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: runWorkflow() called with dryRun=True
        When: Workflow runs
        Then: No orchestrator is started (no signal registration needed)
        """
        # Act
        from main import runWorkflow
        exitCode = runWorkflow(signalConfig, dryRun=True, simulate=True)

        # Assert - dry run should succeed without starting anything
        assert exitCode == 0
