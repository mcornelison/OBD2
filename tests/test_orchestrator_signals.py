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
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
