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
# 2026-04-20    | Ralph (Rex)  | US-207 TD-017: restructure test_loopContinuesAfterException
#               |              | to drive shutdown from the failing callback
#               |              | (deterministic) instead of wall-clock sleep.
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
import tempfile
import threading
import time
from typing import Any

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

        US-207 TD-017 restructure: the prior version used a thread with
        ``time.sleep(0.8)`` as the shutdown trigger, which was timing-dependent
        and flaky under Windows Store Python cold-start latency. The restructure
        drives shutdown from the instrumented check itself (call-count based) so
        the test is fully deterministic.
        """
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

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
            # First call is outside the try/except (initial state), so only
            # fail on calls 2-4 (inside the loop's try/except). Once callCount
            # is past the "must be > 4" threshold the test asserts, trigger
            # shutdown from inside the callback -- no wall-clock sleep required.
            if 2 <= callCount <= 4:
                raise RuntimeError("Test connection check failure")
            if callCount >= 5:
                orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED
            return originalCheck()

        orchestrator._checkConnectionStatus = failingCheck  # type: ignore[assignment]

        with caplog.at_level(logging.ERROR, logger='pi.obdii.orchestrator'):
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
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from pi.obdii.orchestrator import HealthCheckStats

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
        from pi.obdii.orchestrator import HealthCheckStats

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
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

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
