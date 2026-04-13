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
import sqlite3
import tempfile
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

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
        'aiAnalysis': {
            'enabled': False
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
def shutdownConfig(tempDb: str) -> dict[str, Any]:
    """Create shutdown test configuration with temp database."""
    return getShutdownTestConfig(tempDb)


# ================================================================================
# AC1: Shutdown sequence reverse of startup
# ================================================================================


@pytest.mark.integration
class TestShutdownSequenceOrder:
    """Tests that shutdown occurs in reverse dependency order."""

    def test_shutdown_stopsComponentsInReverseOrder(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator with all components initialized
        When: stop() is called
        Then: Components are stopped in reverse of startup order
              (dataLogger first ... database last)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        # Assert - extract 'Stopping X...' messages from orchestrator
        stopMessages = [
            record.message
            for record in caplog.records
            if record.name == 'obd.orchestrator'
            and record.message.startswith("Stopping ")
            and record.message.endswith("...")
            and "ApplicationOrchestrator" not in record.message
        ]

        # dataLogger must be stopped before database
        if "Stopping dataLogger..." in stopMessages and "Stopping database..." in stopMessages:
            dlIdx = stopMessages.index("Stopping dataLogger...")
            dbIdx = stopMessages.index("Stopping database...")
            assert dlIdx < dbIdx, "dataLogger must stop before database"

        # connection must be stopped before database
        if "Stopping connection..." in stopMessages and "Stopping database..." in stopMessages:
            connIdx = stopMessages.index("Stopping connection...")
            dbIdx = stopMessages.index("Stopping database...")
            assert connIdx < dbIdx, "connection must stop before database"

        # database must be last
        assert stopMessages[-1] == "Stopping database...", \
            "database should be the last component stopped"

    def test_shutdown_stopsDataLoggerBeforeConnection(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: stop() is called
        Then: DataLogger stops before connection (can't log without connection)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        stopMessages = [
            record.message
            for record in caplog.records
            if record.name == 'obd.orchestrator'
            and record.message.startswith("Stopping ")
            and record.message.endswith("...")
        ]

        # dataLogger before connection
        if "Stopping dataLogger..." in stopMessages and "Stopping connection..." in stopMessages:
            dlIdx = stopMessages.index("Stopping dataLogger...")
            connIdx = stopMessages.index("Stopping connection...")
            assert dlIdx < connIdx

    def test_shutdown_stopsAlertsBeforeStatistics(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: stop() is called
        Then: AlertManager stops before StatisticsEngine
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        stopMessages = [
            record.message
            for record in caplog.records
            if record.name == 'obd.orchestrator'
            and record.message.startswith("Stopping ")
            and record.message.endswith("...")
        ]

        if "Stopping alertManager..." in stopMessages and "Stopping statisticsEngine..." in stopMessages:
            alertIdx = stopMessages.index("Stopping alertManager...")
            statsIdx = stopMessages.index("Stopping statisticsEngine...")
            assert alertIdx < statsIdx


# ================================================================================
# AC2: Configurable timeout per component (default 5s)
# ================================================================================


@pytest.mark.integration
class TestShutdownConfigurableTimeout:
    """Tests that shutdown uses configurable timeout per component."""

    def test_shutdown_usesConfiguredTimeout(
        self, tempDb: str
    ):
        """
        Given: Config with custom shutdown.componentTimeout
        When: Orchestrator is created
        Then: Shutdown timeout matches config value
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        config = getShutdownTestConfig(tempDb)
        config['shutdown']['componentTimeout'] = 10

        # Act
        orchestrator = ApplicationOrchestrator(
            config=config,
            simulate=True
        )

        # Assert
        assert orchestrator._shutdownTimeout == 10

    def test_shutdown_usesDefaultTimeoutWhenNotConfigured(
        self, tempDb: str
    ):
        """
        Given: Config without shutdown.componentTimeout
        When: Orchestrator is created
        Then: Shutdown timeout defaults to 5.0 seconds
        """
        # Arrange
        from obd.orchestrator import (
            DEFAULT_SHUTDOWN_TIMEOUT,
            ApplicationOrchestrator,
        )

        config = getShutdownTestConfig(tempDb)
        del config['shutdown']['componentTimeout']

        # Act
        orchestrator = ApplicationOrchestrator(
            config=config,
            simulate=True
        )

        # Assert
        assert orchestrator._shutdownTimeout == DEFAULT_SHUTDOWN_TIMEOUT
        assert orchestrator._shutdownTimeout == 5.0

    def test_shutdown_defaultConstantIsFiveSeconds(self):
        """
        Given: The DEFAULT_SHUTDOWN_TIMEOUT constant
        When: Checking its value
        Then: It equals 5.0
        """
        from obd.orchestrator import DEFAULT_SHUTDOWN_TIMEOUT

        assert DEFAULT_SHUTDOWN_TIMEOUT == 5.0


# ================================================================================
# AC3: Components force-stopped with warning on timeout
# ================================================================================


@pytest.mark.integration
class TestShutdownForceStopOnTimeout:
    """Tests that components exceeding timeout are force-stopped."""

    def test_shutdown_warnsWhenComponentExceedsTimeout(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: A component that takes too long to stop
        When: _stopComponentWithTimeout is called
        Then: Warning logged about force-stopping
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        # Override to a very short timeout for test speed
        orchestrator._shutdownTimeout = 0.1

        # Create a mock component that hangs on stop()
        hangingComponent = MagicMock()
        hangingComponent.stop.side_effect = lambda: time.sleep(5)

        # Act
        with caplog.at_level(logging.WARNING):
            result = orchestrator._stopComponentWithTimeout(
                hangingComponent, 'slowComponent'
            )

        # Assert
        assert result is False
        warningMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING
        ]
        assert any(
            "slowComponent" in msg and "force-stopping" in msg
            for msg in warningMessages
        ), f"Expected force-stop warning for slowComponent, got: {warningMessages}"

    def test_shutdown_returnsTrue_whenComponentStopsCleanly(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: A component that stops quickly
        When: _stopComponentWithTimeout is called
        Then: Returns True for clean stop
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        cleanComponent = MagicMock()
        cleanComponent.stop.return_value = None

        # Act
        result = orchestrator._stopComponentWithTimeout(
            cleanComponent, 'fastComponent'
        )

        # Assert
        assert result is True

    def test_shutdown_returnsFalse_whenComponentRaisesError(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: A component that raises an error during stop
        When: _stopComponentWithTimeout is called
        Then: Returns False and logs warning
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        errorComponent = MagicMock()
        errorComponent.stop.side_effect = RuntimeError("Stop failed")

        # Act
        with caplog.at_level(logging.WARNING):
            result = orchestrator._stopComponentWithTimeout(
                errorComponent, 'errorComponent'
            )

        # Assert
        assert result is False
        warningMessages = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING
        ]
        assert any(
            "errorComponent" in msg for msg in warningMessages
        )

    def test_shutdown_skipsNoneComponents(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: A None component reference
        When: _stopComponentWithTimeout is called
        Then: Returns True immediately (nothing to stop)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        # Act
        result = orchestrator._stopComponentWithTimeout(None, 'missingComponent')

        # Assert
        assert result is True


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
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from obd.orchestrator import (
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
        from obd.orchestrator import (
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
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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


# ================================================================================
# AC6: No data loss for completed logging cycles
# ================================================================================


@pytest.mark.integration
@pytest.mark.slow
class TestNoDataLossOnShutdown:
    """Tests that completed logging cycles are not lost during shutdown."""

    def test_shutdown_preservesLoggedDataInDatabase(
        self, shutdownConfig: dict[str, Any], tempDb: str
    ):
        """
        Given: Orchestrator running with data being logged
        When: Graceful shutdown is performed
        Then: All previously logged data is preserved in the database
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        orchestrator.start()

        # Run the main loop briefly to generate some data
        loopThread = threading.Thread(
            target=orchestrator.runLoop,
            daemon=True
        )
        loopThread.start()

        # Let data accumulate for a brief period
        time.sleep(2)

        # Act - graceful shutdown
        orchestrator._shutdownState = orchestrator._shutdownState.__class__('shutdown_requested')
        orchestrator.stop()
        loopThread.join(timeout=5)

        # Assert - query the database for logged data
        conn = sqlite3.connect(tempDb)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM realtime_data")
            rowCount = cursor.fetchone()[0]
            # Should have logged some data during the 2 seconds
            assert rowCount > 0, (
                f"Expected data in database after shutdown, got {rowCount} rows"
            )
        finally:
            conn.close()

    def test_shutdown_databaseAccessibleAfterCleanShutdown(
        self, shutdownConfig: dict[str, Any], tempDb: str
    ):
        """
        Given: Orchestrator that was started and logged data
        When: stop() completes
        Then: Database file is intact and queryable
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Brief loop to generate some data
        loopThread = threading.Thread(
            target=orchestrator.runLoop,
            daemon=True
        )
        loopThread.start()
        time.sleep(1)

        # Act
        orchestrator._shutdownState = orchestrator._shutdownState.__class__('shutdown_requested')
        orchestrator.stop()
        loopThread.join(timeout=5)

        # Assert - database file exists and is queryable
        assert os.path.exists(tempDb)
        conn = sqlite3.connect(tempDb)
        try:
            cursor = conn.cursor()
            # Verify we can query without corruption
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            assert 'realtime_data' in tables
        finally:
            conn.close()


# ================================================================================
# AC7: Exit codes (0 for clean, non-zero for forced/error)
# ================================================================================


@pytest.mark.integration
class TestShutdownExitCodes:
    """Tests for shutdown exit codes."""

    def test_shutdown_returnsZeroForCleanShutdown(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: stop() completes normally
        Then: Returns exit code 0
        """
        # Arrange
        from obd.orchestrator import EXIT_CODE_CLEAN, ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        exitCode = orchestrator.stop()

        # Assert
        assert exitCode == EXIT_CODE_CLEAN
        assert exitCode == 0

    def test_shutdown_returnsNonZeroForForcedShutdown(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator in FORCE_EXIT state
        When: stop() is called
        Then: Returns non-zero exit code
        """
        # Arrange
        from obd.orchestrator import (
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
        exitCode = orchestrator.stop()

        # Assert
        assert exitCode == EXIT_CODE_FORCED
        assert exitCode != 0

    def test_shutdown_exitCodeConstants_areCorrect(self):
        """
        Given: Exit code constants
        When: Checking their values
        Then: EXIT_CODE_CLEAN is 0, EXIT_CODE_FORCED is 1, EXIT_CODE_ERROR is 2
        """
        from obd.orchestrator import (
            EXIT_CODE_CLEAN,
            EXIT_CODE_ERROR,
            EXIT_CODE_FORCED,
        )

        assert EXIT_CODE_CLEAN == 0
        assert EXIT_CODE_FORCED == 1
        assert EXIT_CODE_ERROR == 2

    def test_shutdown_notRunningReturnsExitCode(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator that was never started
        When: stop() is called
        Then: Returns exit code without error
        """
        # Arrange
        from obd.orchestrator import EXIT_CODE_CLEAN, ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        # Act
        exitCode = orchestrator.stop()

        # Assert
        assert exitCode == EXIT_CODE_CLEAN

    def test_shutdown_setsNonZeroExitCodeOnComponentTimeout(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: A component that times out during stop
        When: _stopComponentWithTimeout is called
        Then: Exit code is set to EXIT_CODE_FORCED
        """
        # Arrange
        from obd.orchestrator import (
            EXIT_CODE_FORCED,
            ApplicationOrchestrator,
        )

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator._shutdownTimeout = 0.1

        hangingComponent = MagicMock()
        hangingComponent.stop.side_effect = lambda: time.sleep(5)

        # Act
        orchestrator._stopComponentWithTimeout(hangingComponent, 'slowComponent')

        # Assert
        assert orchestrator._exitCode == EXIT_CODE_FORCED


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
        from obd.orchestrator import ShutdownState

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
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from obd.orchestrator import ApplicationOrchestrator

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
            and r.name == 'obd.orchestrator'
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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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


# ================================================================================
# Component cleanup verification
# ================================================================================


@pytest.mark.integration
class TestShutdownComponentCleanup:
    """Tests that all component references are cleaned up after shutdown."""

    def test_shutdown_clearsAllComponentReferences(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with initialized components
        When: stop() completes
        Then: All component references are set to None
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Verify components were initialized
        assert orchestrator._database is not None
        assert orchestrator._connection is not None

        # Act
        orchestrator.stop()

        # Assert - all references cleared
        assert orchestrator._database is None
        assert orchestrator._connection is None
        assert orchestrator._dataLogger is None
        assert orchestrator._driveDetector is None
        assert orchestrator._alertManager is None
        assert orchestrator._statisticsEngine is None
        assert orchestrator._displayManager is None
        assert orchestrator._profileManager is None
        assert orchestrator._vinDecoder is None

    def test_shutdown_isRunningReturnsFalseAfterStop(
        self, shutdownConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: stop() completes
        Then: isRunning() returns False
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()
        assert orchestrator.isRunning() is True

        # Act
        orchestrator.stop()

        # Assert
        assert orchestrator.isRunning() is False

    def test_shutdown_partialInitCleanup_onStartupFailure(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator where a component fails during startup
        When: Start fails partway through
        Then: Partial initialization is cleaned up
        """
        # Arrange
        from obd.orchestrator import (
            ApplicationOrchestrator,
            OrchestratorError,
        )

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        # Force a component init to fail by patching _initializeConnection
        with patch.object(
            orchestrator, '_initializeConnection',
            side_effect=RuntimeError("Simulated connection failure")
        ):
            # Act
            with caplog.at_level(logging.INFO):
                with pytest.raises(OrchestratorError):
                    orchestrator.start()

        # Assert - cleanup was performed
        cleanupMessages = [
            r.message for r in caplog.records
            if "Cleaning up" in r.message or "Cleanup complete" in r.message
        ]
        assert len(cleanupMessages) > 0, "Expected cleanup messages after failed start"
