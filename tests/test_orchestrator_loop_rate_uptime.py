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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

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

        with caplog.at_level(logging.INFO, logger='pi.obdii.orchestrator'):
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
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

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

        with caplog.at_level(logging.INFO, logger='pi.obdii.orchestrator'):
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
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

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
