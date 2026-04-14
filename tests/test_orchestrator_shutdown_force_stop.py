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
import tempfile
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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )

        # Act
        result = orchestrator._stopComponentWithTimeout(None, 'missingComponent')

        # Assert
        assert result is True
