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

import os
import sqlite3
import tempfile
import threading
import time
from typing import Any
from unittest.mock import MagicMock

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
        'protocolVersion': '1.0.0',
        'schemaVersion': '1.0.0',
        'deviceId': 'test-device',
        'logging': {
            'level': 'DEBUG',
            'maskPII': False
        },
        'pi': {
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
def shutdownConfig(tempDb: str) -> dict[str, Any]:
    """Create shutdown test configuration with temp database."""
    return getShutdownTestConfig(tempDb)


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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import EXIT_CODE_CLEAN, ApplicationOrchestrator

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
        from pi.obdii.orchestrator import (
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
        from pi.obdii.orchestrator import (
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
        from pi.obdii.orchestrator import EXIT_CODE_CLEAN, ApplicationOrchestrator

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
        from pi.obdii.orchestrator import (
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
