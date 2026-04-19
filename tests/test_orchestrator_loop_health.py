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
from unittest.mock import MagicMock

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
        from pi.obdii.orchestrator import (
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

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

        with caplog.at_level(logging.INFO, logger='pi.obdii.orchestrator'):
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        with caplog.at_level(logging.INFO, logger='pi.obdii.orchestrator'):
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        with caplog.at_level(logging.INFO, logger='pi.obdii.orchestrator'):
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        with caplog.at_level(logging.INFO, logger='pi.obdii.orchestrator'):
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        with caplog.at_level(logging.INFO, logger='pi.obdii.orchestrator'):
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
