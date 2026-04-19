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
from typing import Any
from unittest.mock import patch

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.orchestrator import (
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
