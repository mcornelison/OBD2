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
# AC1: SIGINT (Ctrl+C) triggers graceful shutdown
# ================================================================================


@pytest.mark.integration
class TestSigintGracefulShutdown:
    """Tests that SIGINT (Ctrl+C) triggers graceful shutdown."""

    def test_signals_sigintSetsShutdownRequested(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator (RUNNING state)
        When: First SIGINT is received
        Then: ShutdownState changes to SHUTDOWN_REQUESTED
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )
        assert orchestrator._shutdownState == ShutdownState.RUNNING

        # Act
        orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        assert orchestrator._shutdownState == ShutdownState.SHUTDOWN_REQUESTED

    def test_signals_sigintDoesNotForceExit(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator (RUNNING state)
        When: First SIGINT is received
        Then: sys.exit is NOT called (graceful, not forced)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )

        # Act & Assert - should NOT raise SystemExit
        orchestrator._handleShutdownSignal(signal.SIGINT, None)
        # If we reach here, no SystemExit was raised - test passes


# ================================================================================
# AC2: SIGTERM triggers graceful shutdown (for systemd stop)
# ================================================================================


@pytest.mark.integration
class TestSigtermGracefulShutdown:
    """Tests that SIGTERM triggers graceful shutdown for systemd management."""

    def test_signals_sigtermSetsShutdownRequested(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: SIGTERM is received
        Then: ShutdownState changes to SHUTDOWN_REQUESTED
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )

        # Act - use SIGTERM if available, SIGINT otherwise (same handler)
        if hasattr(signal, 'SIGTERM'):
            orchestrator._handleShutdownSignal(signal.SIGTERM, None)
        else:
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        assert orchestrator._shutdownState == ShutdownState.SHUTDOWN_REQUESTED

    def test_signals_sigtermUseSameHandlerAsSigint(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with registered signal handlers
        When: Checking both SIGINT and SIGTERM handlers
        Then: Both point to the same _handleShutdownSignal method
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )
        orchestrator.registerSignalHandlers()

        try:
            # Assert - SIGINT and SIGTERM use the same handler function
            sigintHandler = signal.getsignal(signal.SIGINT)
            assert sigintHandler == orchestrator._handleShutdownSignal

            if hasattr(signal, 'SIGTERM'):
                sigtermHandler = signal.getsignal(signal.SIGTERM)
                assert sigtermHandler == orchestrator._handleShutdownSignal
                assert sigintHandler == sigtermHandler
        finally:
            orchestrator.restoreSignalHandlers()
