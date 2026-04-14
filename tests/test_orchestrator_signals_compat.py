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
# AC7: Works correctly on both Windows and Linux
# ================================================================================


@pytest.mark.integration
class TestCrossPlatformCompatibility:
    """Tests that signal handling works on both Windows and Linux."""

    def test_signals_sigintRegistrationWorksOnAllPlatforms(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Any platform (Windows or Linux)
        When: registerSignalHandlers() is called
        Then: At minimum, SIGINT is registered (universally available)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )

        # Act
        orchestrator.registerSignalHandlers()

        try:
            # Assert - SIGINT is always available on both platforms
            currentHandler = signal.getsignal(signal.SIGINT)
            assert currentHandler == orchestrator._handleShutdownSignal
        finally:
            orchestrator.restoreSignalHandlers()

    def test_signals_sigtermGuardedByHasattr(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Platform where SIGTERM may not exist (Windows)
        When: registerSignalHandlers() is called
        Then: SIGTERM registration is guarded (no AttributeError)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )

        # Act & Assert - should not raise regardless of platform
        orchestrator.registerSignalHandlers()
        orchestrator.restoreSignalHandlers()

    def test_signals_windowsPathRegistersOnlySigint(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Platform without SIGTERM (simulated Windows)
        When: registerSignalHandlers() is called
        Then: Only SIGINT handler is set, no error raised
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )

        # Simulate Windows: temporarily remove SIGTERM from signal module
        hasSigterm = hasattr(signal, 'SIGTERM')
        originalSigterm = getattr(signal, 'SIGTERM', None)

        if hasSigterm:
            delattr(signal, 'SIGTERM')

        try:
            # Act - should only register SIGINT
            orchestrator.registerSignalHandlers()

            # Assert - SIGINT handler should be set
            assert signal.getsignal(signal.SIGINT) == orchestrator._handleShutdownSignal

            # SIGTERM handler attribute should remain None
            assert orchestrator._originalSigtermHandler is None

            orchestrator.restoreSignalHandlers()
        finally:
            # Restore SIGTERM to signal module
            if hasSigterm and originalSigterm is not None:
                signal.SIGTERM = originalSigterm

    def test_signals_linuxRegisterssBothSigintAndSigterm(
        self, signalConfig: dict[str, Any]
    ):
        """
        Given: Platform with SIGTERM (Linux/macOS)
        When: registerSignalHandlers() is called
        Then: Both SIGINT and SIGTERM handlers are set
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        if not hasattr(signal, 'SIGTERM'):
            pytest.skip("SIGTERM not available on this platform")

        orchestrator = ApplicationOrchestrator(
            config=signalConfig,
            simulate=True
        )

        # Act
        orchestrator.registerSignalHandlers()

        try:
            # Assert - both handlers registered
            assert signal.getsignal(signal.SIGINT) == orchestrator._handleShutdownSignal
            assert signal.getsignal(signal.SIGTERM) == orchestrator._handleShutdownSignal
        finally:
            orchestrator.restoreSignalHandlers()
