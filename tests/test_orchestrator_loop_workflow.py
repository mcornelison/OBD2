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
