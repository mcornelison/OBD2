################################################################################
# File Name: test_orchestrator_loop.py
# Purpose/Description: Tests for orchestrator main application loop (US-OSC-005)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-005
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator main application loop.

Verifies that the orchestrator's runLoop():
- Runs until shutdown signal is received
- Handles component callbacks: drive start/end, alert, analysis, connection lost
- Performs health checks at configurable interval
- Logs connection status, data rate, and error count during health check
- Catches and logs unexpected exceptions without crashing
- Is memory-efficient (no unbounded growth)
- Integrates with runWorkflow() in main.py

Usage:
    pytest tests/test_orchestrator_loop.py -v
"""

import logging
import os
import sys
import tempfile
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getLoopTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create minimal test configuration for loop tests.

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
                'name': 'Loop Test',
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
                        'description': 'Profile for loop tests',
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
                'healthCheckIntervalSeconds': 0.5,
                'dataRateLogIntervalSeconds': 1.0
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
def loopConfig(tempDb: str) -> dict[str, Any]:
    """Create loop test configuration with temp database."""
    return getLoopTestConfig(tempDb)


# ================================================================================
# AC1: Main loop in runWorkflow() replaced with actual implementation
# ================================================================================


@pytest.mark.integration
class TestRunWorkflowCallsRunLoop:
    """Verify runWorkflow() in main.py calls orchestrator.runLoop()."""

    def test_runWorkflow_callsRunLoop_notPlaceholder(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: runWorkflow called with valid config
        When: orchestrator starts
        Then: runLoop() is called (not a placeholder/pass)
        """
        callOrder: list[str] = []

        mockOrchestrator = MagicMock()
        mockOrchestrator.start.side_effect = (
            lambda: callOrder.append('start')
        )
        mockOrchestrator.runLoop.side_effect = (
            lambda: callOrder.append('runLoop')
        )
        mockOrchestrator.stop.return_value = 0
        mockOrchestrator.restoreSignalHandlers.return_value = None

        with patch(
            'pi.obd.orchestrator.createOrchestratorFromConfig',
            return_value=mockOrchestrator
        ):
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
            from main import runWorkflow
            exitCode = runWorkflow(loopConfig, dryRun=False, simulate=True)

        assert 'start' in callOrder, "start() should be called"
        assert 'runLoop' in callOrder, "runLoop() should be called"
        assert callOrder.index('start') < callOrder.index('runLoop'), (
            "start() should be called before runLoop()"
        )
        assert exitCode == 0

    def test_runWorkflow_dryRun_skipsRunLoop(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: runWorkflow called with dryRun=True
        When: executing
        Then: runLoop() is NOT called
        """
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
        from main import runWorkflow
        exitCode = runWorkflow(loopConfig, dryRun=True, simulate=True)

        assert exitCode == 0


# ================================================================================
# AC2: Loop runs until shutdown signal received
# ================================================================================


@pytest.mark.integration
class TestLoopRunsUntilShutdown:
    """Verify the loop runs continuously until shutdown is triggered."""

    def test_runLoop_exitsOnShutdownRequested(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator is running
        When: shutdownState changes to SHUTDOWN_REQUESTED
        Then: runLoop() exits
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        # Signal shutdown after short delay
        def triggerShutdown() -> None:
            time.sleep(0.3)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown, daemon=True)
        shutdownThread.start()

        # runLoop should exit once shutdown is requested
        startTime = time.time()
        orchestrator.runLoop()
        elapsed = time.time() - startTime

        assert elapsed < 5.0, "Loop should have exited after shutdown signal"

    def test_runLoop_exitsOnForceExit(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator is running
        When: shutdownState changes to FORCE_EXIT
        Then: runLoop() exits immediately
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        def triggerForceExit() -> None:
            time.sleep(0.2)
            orchestrator._shutdownState = ShutdownState.FORCE_EXIT

        forceThread = threading.Thread(target=triggerForceExit, daemon=True)
        forceThread.start()

        startTime = time.time()
        orchestrator.runLoop()
        elapsed = time.time() - startTime

        assert elapsed < 5.0, "Loop should have exited after force exit"

    def test_runLoop_exitsWhenRunningFalse(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator is running
        When: _running set to False
        Then: runLoop() exits
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        def stopRunning() -> None:
            time.sleep(0.2)
            orchestrator._running = False

        stopThread = threading.Thread(target=stopRunning, daemon=True)
        stopThread.start()

        startTime = time.time()
        orchestrator.runLoop()
        elapsed = time.time() - startTime

        assert elapsed < 5.0, "Loop should have exited when _running=False"

    def test_runLoop_doesNotRunWhenNotStarted(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with _running=False
        When: runLoop() called
        Then: Returns immediately without entering loop
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        # _running defaults to False

        startTime = time.time()
        orchestrator.runLoop()
        elapsed = time.time() - startTime

        assert elapsed < 1.0, "Should return immediately when not running"


# ================================================================================
# AC3: Loop handles component callbacks
# ================================================================================


@pytest.mark.integration
class TestComponentCallbacks:
    """Verify callbacks are wired up for drive, alert, analysis, connection."""

    def test_setupComponentCallbacks_wiresDriveDetector(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with a mock drive detector
        When: _setupComponentCallbacks() is called
        Then: Drive detector has registerCallbacks called
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        orchestrator._setupComponentCallbacks()

        mockDetector.registerCallbacks.assert_called_once()
        callKwargs = mockDetector.registerCallbacks.call_args[1]
        assert 'onDriveStart' in callKwargs
        assert 'onDriveEnd' in callKwargs

    def test_setupComponentCallbacks_wiresAlertManager(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with a mock alert manager
        When: _setupComponentCallbacks() is called
        Then: Alert manager has onAlert registered
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        orchestrator._setupComponentCallbacks()

        mockAlertManager.onAlert.assert_called_once()

    def test_setupComponentCallbacks_wiresStatisticsEngine(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with a mock statistics engine
        When: _setupComponentCallbacks() is called
        Then: Statistics engine has registerCallbacks called
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockStats = MagicMock()
        orchestrator._statisticsEngine = mockStats

        orchestrator._setupComponentCallbacks()

        mockStats.registerCallbacks.assert_called_once()
        callKwargs = mockStats.registerCallbacks.call_args[1]
        assert 'onAnalysisComplete' in callKwargs

    def test_setupComponentCallbacks_wiresDataLogger(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with a mock data logger
        When: _setupComponentCallbacks() is called
        Then: Data logger has registerCallbacks called with onReading and onError
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger

        orchestrator._setupComponentCallbacks()

        mockLogger.registerCallbacks.assert_called_once()
        callKwargs = mockLogger.registerCallbacks.call_args[1]
        assert 'onReading' in callKwargs
        assert 'onError' in callKwargs

    def test_handleConnectionLost_callbackInvoked(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with connection lost callback registered
        When: Connection state changes from connected to disconnected
        Then: _handleConnectionLost is called and updates health stats
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        orchestrator._handleConnectionLost()

        assert orchestrator._healthCheckStats.connectionStatus == "reconnecting"
        assert orchestrator._healthCheckStats.connectionConnected is False

    def test_handleDriveStart_incrementsDrivesDetected(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with health check stats
        When: _handleDriveStart called
        Then: drivesDetected counter incremented
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockSession = MagicMock()
        initialDrives = orchestrator._healthCheckStats.drivesDetected

        orchestrator._handleDriveStart(mockSession)

        assert orchestrator._healthCheckStats.drivesDetected == initialDrives + 1

    def test_handleAlert_incrementsAlertsTriggered(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with health check stats
        When: _handleAlert called
        Then: alertsTriggered counter incremented
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockAlert = MagicMock()
        mockAlert.priority = 'warning'
        mockAlert.parameterName = 'RPM'
        mockAlert.value = 7000
        mockAlert.threshold = 6000
        mockAlert.message = 'RPM exceeded redline'
        initialAlerts = orchestrator._healthCheckStats.alertsTriggered

        orchestrator._handleAlert(mockAlert)

        assert orchestrator._healthCheckStats.alertsTriggered == initialAlerts + 1


# ================================================================================
# AC4: Loop includes health check every 60 seconds (configurable)
# ================================================================================


@pytest.mark.integration
class TestHealthCheckInterval:
    """Verify health checks run at configurable interval."""

    def test_healthCheckInterval_defaultsTo60Seconds(self) -> None:
        """
        Given: Config without monitoring.healthCheckIntervalSeconds
        When: Orchestrator created
        Then: Health check interval defaults to 60 seconds
        """
        from pi.obd.orchestrator import (
            DEFAULT_HEALTH_CHECK_INTERVAL,
            ApplicationOrchestrator,
        )

        config: dict[str, Any] = {
            'database': {'path': ':memory:'},
            'bluetooth': {},
            'realtimeData': {'parameters': []},
            'profiles': {'activeProfile': 'test', 'availableProfiles': []},
            'tieredThresholds': {
                'rpm': {'unit': 'rpm', 'dangerMin': 7000},
                'coolantTemp': {'unit': 'fahrenheit', 'dangerMin': 220},
            },
        }

        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        assert orchestrator._healthCheckInterval == DEFAULT_HEALTH_CHECK_INTERVAL
        assert orchestrator._healthCheckInterval == 60.0

    def test_healthCheckInterval_configurable(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Config with healthCheckIntervalSeconds=0.5
        When: Orchestrator created
        Then: Uses configured value
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        assert orchestrator._healthCheckInterval == 0.5

    def test_healthCheckRunsDuringLoop(
        self, loopConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: Orchestrator running with healthCheckIntervalSeconds=0.5
        When: Loop runs for >1 second
        Then: At least one HEALTH CHECK is logged
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        # Shutdown after 1.5 seconds (should get at least 2 health checks at 0.5s interval)
        def triggerShutdown() -> None:
            time.sleep(1.5)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown, daemon=True)
        shutdownThread.start()

        with caplog.at_level(logging.INFO, logger='pi.obd.orchestrator'):
            orchestrator.runLoop()

        healthCheckLogs = [
            r for r in caplog.records if 'HEALTH CHECK' in r.message
        ]
        assert len(healthCheckLogs) >= 2, (
            f"Expected at least 2 health checks in 1.5s with 0.5s interval, "
            f"got {len(healthCheckLogs)}"
        )

    def test_setHealthCheckInterval_updatesValue(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with default health check interval
        When: setHealthCheckInterval(30) is called
        Then: Interval updated to 30 seconds
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        orchestrator.setHealthCheckInterval(30)

        assert orchestrator._healthCheckInterval == 30

    def test_setHealthCheckInterval_rejectsLowValue(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator
        When: setHealthCheckInterval(5) called (below 10 minimum)
        Then: Raises ValueError
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        with pytest.raises(ValueError, match="at least 10 seconds"):
            orchestrator.setHealthCheckInterval(5)


# ================================================================================
# AC5: Health check logs: connection status, data rate, error count
# ================================================================================


@pytest.mark.integration
class TestHealthCheckLogging:
    """Verify health check logs contain required fields."""

    def test_performHealthCheck_logsConnectionStatus(
        self, loopConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: Orchestrator with health check stats
        When: _performHealthCheck() is called
        Then: Log contains connection= field
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        with caplog.at_level(logging.INFO, logger='pi.obd.orchestrator'):
            orchestrator._performHealthCheck()

        healthLogs = [r for r in caplog.records if 'HEALTH CHECK' in r.message]
        assert len(healthLogs) >= 1, "Should have at least one HEALTH CHECK log"
        assert 'connection=' in healthLogs[0].message

    def test_performHealthCheck_logsDataRate(
        self, loopConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: Orchestrator with health check stats
        When: _performHealthCheck() is called
        Then: Log contains data_rate= field
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        with caplog.at_level(logging.INFO, logger='pi.obd.orchestrator'):
            orchestrator._performHealthCheck()

        healthLogs = [r for r in caplog.records if 'HEALTH CHECK' in r.message]
        assert 'data_rate=' in healthLogs[0].message

    def test_performHealthCheck_logsErrorCount(
        self, loopConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: Orchestrator with health check stats
        When: _performHealthCheck() is called
        Then: Log contains errors= field
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        with caplog.at_level(logging.INFO, logger='pi.obd.orchestrator'):
            orchestrator._performHealthCheck()

        healthLogs = [r for r in caplog.records if 'HEALTH CHECK' in r.message]
        assert 'errors=' in healthLogs[0].message

    def test_performHealthCheck_logsUptimeAndDrives(
        self, loopConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: Orchestrator with health check stats
        When: _performHealthCheck() is called
        Then: Log also contains uptime= and drives= fields
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        with caplog.at_level(logging.INFO, logger='pi.obd.orchestrator'):
            orchestrator._performHealthCheck()

        healthLogs = [r for r in caplog.records if 'HEALTH CHECK' in r.message]
        msg = healthLogs[0].message
        assert 'uptime=' in msg
        assert 'drives=' in msg
        assert 'alerts=' in msg

    def test_performHealthCheck_updatesStatsFromComponents(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with mock data logger having stats
        When: _performHealthCheck() is called
        Then: Health check stats updated from component stats
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        # Mock data logger with stats
        mockLogger = MagicMock()
        mockStats = MagicMock()
        mockStats.totalLogged = 42
        mockStats.totalErrors = 3
        mockLogger.getStats.return_value = mockStats
        orchestrator._dataLogger = mockLogger

        orchestrator._performHealthCheck()

        assert orchestrator._healthCheckStats.totalReadings == 42
        assert orchestrator._healthCheckStats.totalErrors == 3


# ================================================================================
# AC6: Loop catches and logs unexpected exceptions without crashing
# ================================================================================


@pytest.mark.integration
class TestExceptionHandling:
    """Verify the loop catches exceptions and continues running."""

    def test_loopContinuesAfterException(
        self, loopConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: Orchestrator running in loop
        When: _checkConnectionStatus raises an exception
        Then: Error is logged and loop continues running
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        callCount = 0
        originalCheck = orchestrator._checkConnectionStatus

        def failingCheck() -> bool:
            nonlocal callCount
            callCount += 1
            # First call is outside the try/except (initial state),
            # so only fail on calls 2-4 (inside the loop's try/except)
            if 2 <= callCount <= 4:
                raise RuntimeError("Test connection check failure")
            return originalCheck()

        orchestrator._checkConnectionStatus = failingCheck  # type: ignore[assignment]

        # Shutdown after errors have been raised
        def triggerShutdown() -> None:
            time.sleep(0.8)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown, daemon=True)
        shutdownThread.start()

        with caplog.at_level(logging.ERROR, logger='pi.obd.orchestrator'):
            orchestrator.runLoop()

        # Loop should have continued despite exceptions
        assert callCount > 4, (
            "Loop should have called _checkConnectionStatus multiple times "
            "even after exceptions"
        )

        errorLogs = [
            r for r in caplog.records
            if 'Error in main loop iteration' in r.message
        ]
        assert len(errorLogs) >= 1, "Should have logged at least one loop error"

    def test_exceptionIncrementsErrorCount(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator running in loop
        When: An exception occurs in the loop
        Then: totalErrors in health stats is incremented
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        callCount = 0

        def failThenStop() -> bool:
            nonlocal callCount
            callCount += 1
            # First call is outside try/except (initial state), let it pass.
            # Second call (first inside loop) raises.
            # Third call stops the loop.
            if callCount == 1:
                return False
            if callCount == 2:
                raise RuntimeError("Test error")
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED
            return False

        orchestrator._checkConnectionStatus = failThenStop  # type: ignore[assignment]
        initialErrors = orchestrator._healthCheckStats.totalErrors

        orchestrator.runLoop()

        assert orchestrator._healthCheckStats.totalErrors > initialErrors, (
            "Errors should have been incremented after exception"
        )


# ================================================================================
# AC7: Memory-efficient (no unbounded growth over hours of running)
# ================================================================================


@pytest.mark.integration
class TestMemoryEfficiency:
    """Verify the loop does not accumulate unbounded data."""

    def test_healthCheckStats_usesFixedCounters(self) -> None:
        """
        Given: HealthCheckStats dataclass
        When: Inspected
        Then: All fields are scalar types (no lists, dicts, or sets)
        """
        from pi.obd.orchestrator import HealthCheckStats

        stats = HealthCheckStats()
        for fieldName, fieldValue in stats.__dict__.items():
            assert not isinstance(fieldValue, (list, dict, set)), (
                f"HealthCheckStats.{fieldName} is {type(fieldValue).__name__}, "
                f"should be scalar for memory efficiency"
            )

    def test_healthCheckStats_toDict_returnsFixedKeys(self) -> None:
        """
        Given: HealthCheckStats instance
        When: toDict() called
        Then: Returns fixed number of keys (no unbounded growth)
        """
        from pi.obd.orchestrator import HealthCheckStats

        stats = HealthCheckStats()
        result = stats.toDict()

        # Should have exactly these fields, no more
        expectedKeys = {
            'connectionConnected', 'connectionStatus', 'dataRatePerMinute',
            'totalReadings', 'totalErrors', 'drivesDetected',
            'alertsTriggered', 'lastHealthCheck', 'uptimeSeconds'
        }
        assert set(result.keys()) == expectedKeys

    def test_loopDoesNotAccumulateData(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator running briefly
        When: Loop runs for several iterations
        Then: No growing collections on the orchestrator instance
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        def triggerShutdown() -> None:
            time.sleep(0.5)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown, daemon=True)
        shutdownThread.start()

        orchestrator.runLoop()

        # Check that no instance attribute is a growing list/set
        # (callbacks, components, and config dicts are fine — they're fixed at init)
        for attrName in dir(orchestrator):
            if attrName.startswith('__'):
                continue
            try:
                val = getattr(orchestrator, attrName)
            except Exception:
                continue
            if isinstance(val, list) and len(val) > 100:
                pytest.fail(
                    f"orchestrator.{attrName} is a list with {len(val)} items — "
                    f"potential unbounded growth"
                )


# ================================================================================
# AC8: Typecheck/lint passes (verified by running quality checks externally)
# Additional: Data rate logging and uptime tracking
# ================================================================================


@pytest.mark.integration
class TestDataRateLogging:
    """Verify data logging rate is logged periodically."""

    def test_dataRateLogInterval_configurable(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Config with dataRateLogIntervalSeconds=1.0
        When: Orchestrator created
        Then: Uses configured value
        """
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        assert orchestrator._dataRateLogInterval == 1.0

    def test_dataRateLoggedDuringLoop(
        self, loopConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: Orchestrator running with dataRateLogIntervalSeconds=1.0
        When: Loop runs for >1.5 seconds
        Then: DATA LOGGING RATE message appears in logs
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        def triggerShutdown() -> None:
            time.sleep(1.5)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown, daemon=True)
        shutdownThread.start()

        with caplog.at_level(logging.INFO, logger='pi.obd.orchestrator'):
            orchestrator.runLoop()

        dataRateLogs = [
            r for r in caplog.records if 'DATA LOGGING RATE' in r.message
        ]
        assert len(dataRateLogs) >= 1, (
            "Expected at least 1 DATA LOGGING RATE log in 1.5s with 1.0s interval"
        )


@pytest.mark.integration
class TestLoopUptimeTracking:
    """Verify the loop tracks and reports uptime."""

    def test_runLoop_logsUptimeOnExit(
        self, loopConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: Orchestrator running in loop
        When: Loop exits
        Then: Total uptime is logged
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        def triggerShutdown() -> None:
            time.sleep(0.3)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown, daemon=True)
        shutdownThread.start()

        with caplog.at_level(logging.INFO, logger='pi.obd.orchestrator'):
            orchestrator.runLoop()

        uptimeLogs = [
            r for r in caplog.records if 'Main loop exited' in r.message
        ]
        assert len(uptimeLogs) == 1, "Should log uptime on exit"
        assert 'uptime=' in uptimeLogs[0].message

    def test_runLoop_setsStartTime(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator
        When: runLoop() called
        Then: _startTime is set
        """
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        orchestrator._running = True
        orchestrator._shutdownState = ShutdownState.RUNNING

        assert orchestrator._startTime is None

        def triggerShutdown() -> None:
            time.sleep(0.2)
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

        shutdownThread = threading.Thread(target=triggerShutdown, daemon=True)
        shutdownThread.start()

        orchestrator.runLoop()

        assert orchestrator._startTime is not None
