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

import logging
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
# AC5: Original signal handlers restored on shutdown
# ================================================================================


@pytest.mark.integration
class TestSignalHandlerRestore:
    """Tests that original signal handlers are properly restored."""

    def test_signals_restoreSigintToOriginal(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with registered signal handlers
        When: restoreSignalHandlers() is called
        Then: SIGINT handler is restored to the original handler
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )
        originalSigint = signal.getsignal(signal.SIGINT)

        orchestrator.registerSignalHandlers()
        assert signal.getsignal(signal.SIGINT) != originalSigint

        # Act
        orchestrator.restoreSignalHandlers()

        # Assert
        assert signal.getsignal(signal.SIGINT) == originalSigint

    def test_signals_restoreSigtermIfAvailable(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with registered handlers on a platform with SIGTERM
        When: restoreSignalHandlers() is called
        Then: SIGTERM handler is also restored
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )

        if hasattr(signal, 'SIGTERM'):
            originalSigterm = signal.getsignal(signal.SIGTERM)
            orchestrator.registerSignalHandlers()
            assert signal.getsignal(signal.SIGTERM) != originalSigterm

            # Act
            orchestrator.restoreSignalHandlers()

            # Assert
            assert signal.getsignal(signal.SIGTERM) == originalSigterm
        else:
            # Windows: SIGTERM not available, just verify no error
            orchestrator.registerSignalHandlers()
            orchestrator.restoreSignalHandlers()

    def test_signals_restoreIsIdempotent(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator whose handlers have already been restored
        When: restoreSignalHandlers() is called again
        Then: No error occurs (idempotent operation)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )
        orchestrator.registerSignalHandlers()
        orchestrator.restoreSignalHandlers()

        # Act & Assert - should not raise
        orchestrator.restoreSignalHandlers()


# ================================================================================
# AC6: Signal received logged: 'Received signal [SIGNAME], initiating shutdown'
# ================================================================================


@pytest.mark.integration
class TestSignalLogging:
    """Tests that signal receipt is properly logged."""

    def test_signals_firstSignalLogsInfoWithSignalName(
        self, signalConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: First signal is received
        Then: INFO log includes 'Received signal SIGINT, initiating shutdown'
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
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
            "Received signal" in msg
            and "SIGINT" in msg
            and "initiating shutdown" in msg
            for msg in infoMessages
        ), f"Expected 'Received signal SIGINT, initiating shutdown' log, got: {infoMessages}"

    def test_signals_secondSignalLogsWarning(
        self, signalConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator in SHUTDOWN_REQUESTED state
        When: Second signal is received
        Then: WARNING log includes 'Received second signal' and signal name
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        # Act
        with caplog.at_level(logging.WARNING):
            with pytest.raises(SystemExit):
                orchestrator._handleShutdownSignal(signal.SIGINT, None)

        # Assert
        warningMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING
        ]
        assert any(
            "second signal" in msg.lower() and "SIGINT" in msg
            for msg in warningMessages
        ), f"Expected 'Received second signal (SIGINT)' warning, got: {warningMessages}"

    def test_signals_sigtermLogIncludesCorrectName(
        self, signalConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: SIGTERM is received
        Then: Log message includes 'SIGTERM' (not 'SIGINT')
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )

        if not hasattr(signal, 'SIGTERM'):
            pytest.skip("SIGTERM not available on this platform")

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._handleShutdownSignal(signal.SIGTERM, None)

        # Assert
        infoMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.INFO
        ]
        assert any(
            "SIGTERM" in msg
            for msg in infoMessages
        ), f"Expected 'SIGTERM' in log message, got: {infoMessages}"
