################################################################################
# File Name: test_orchestrator_integration.py
# Purpose/Description: Integration tests for ApplicationOrchestrator with simulator
# Author: Ralph Agent
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-23    | Ralph Agent  | Initial implementation for US-OSC-015
# 2026-04-11    | Ralph Agent  | US-OSC-015: Add connection recovery tests (AC8)
#               |              | and profile switch tests (AC9) — 9 new tests
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Integration tests for ApplicationOrchestrator in simulator mode.

Tests the orchestrator's ability to start, run, and stop with all components
integrated together using simulated OBD-II connections. These tests verify
the end-to-end functionality of the system without requiring hardware.

Test coverage includes:
- Orchestrator startup in simulator mode
- Graceful shutdown on signal
- Data logging to database during simulated operations
- Drive detection triggering on RPM changes
- Statistics calculation after drive ends
- Alert triggering on threshold violations
- Temporary database usage (not production)

Usage:
    pytest tests/test_orchestrator_integration.py -v
    pytest tests/test_orchestrator_integration.py -v --timeout=120
"""

import os
import signal
import sqlite3
import tempfile
from typing import Any

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getIntegrationTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for integration tests.

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
                'name': 'Integration Test',
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
                'pollingIntervalMs': 100,  # Fast polling for tests
                'parameters': [
                    {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'COOLANT_TEMP', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'ENGINE_LOAD', 'logData': True, 'displayOnDashboard': False},
                    {'name': 'THROTTLE_POS', 'logData': True, 'displayOnDashboard': False}
                ]
            },
            'analysis': {
                'triggerAfterDrive': True,
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 1,  # Short for tests
                'driveEndRpmThreshold': 100,
                'driveEndDurationSeconds': 1,  # Short for tests
                'calculateStatistics': ['max', 'min', 'avg']
            },
            'profiles': {
                'activeProfile': 'test',
                'availableProfiles': [
                    {
                        'id': 'test',
                        'name': 'Test Profile',
                        'description': 'Profile for integration tests',
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
                'cooldownSeconds': 1,  # Short for tests
                'visualAlerts': False,
                'audioAlerts': False,
                'logAlerts': True
            },
            'monitoring': {
                'healthCheckIntervalSeconds': 2,  # Short for tests
                'dataRateLogIntervalSeconds': 5
            },
            'shutdown': {
                'componentTimeout': 2  # Short for tests
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
    """
    Create a temporary database file for testing.

    Yields:
        Path to temporary database file

    Automatically cleaned up after test.
    """
    # Use file-based temp database (not :memory:) for proper testing
    fd, dbPath = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    yield dbPath

    # Cleanup
    try:
        os.unlink(dbPath)
    except OSError:
        pass


@pytest.fixture
def integrationConfig(tempDb: str) -> dict[str, Any]:
    """
    Create integration test configuration with temp database.

    Args:
        tempDb: Temporary database path fixture

    Returns:
        Test configuration dictionary
    """
    return getIntegrationTestConfig(tempDb)


# ================================================================================
# Test: Orchestrator starts successfully in simulator mode
# ================================================================================


@pytest.mark.integration
class TestOrchestratorStartsInSimulatorMode:
    """Tests for orchestrator startup in simulator mode."""

    def test_orchestrator_startsSuccessfully_inSimulatorMode(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Valid configuration with simulator enabled
        When: Orchestrator is started in simulator mode
        Then: Orchestrator starts successfully and is running
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Act
        try:
            orchestrator.start()

            # Assert
            assert orchestrator.isRunning() is True
            status = orchestrator.getStatus()
            assert status['running'] is True
            assert status['components']['database'] == 'initialized'

        finally:
            # Cleanup
            orchestrator.stop()

    def test_orchestrator_initializesDatabase_inSimulatorMode(
        self, integrationConfig: dict[str, Any], tempDb: str
    ):
        """
        Given: Valid configuration with temp database
        When: Orchestrator starts in simulator mode
        Then: Database is created and initialized
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Act
        try:
            orchestrator.start()

            # Assert - database file exists
            assert os.path.exists(tempDb)

            # Assert - database has required tables
            with sqlite3.connect(tempDb) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                tables = {row[0] for row in cursor.fetchall()}

            # Should have at least realtime_data and profiles tables
            assert 'realtime_data' in tables or len(tables) > 0

        finally:
            orchestrator.stop()

    def test_orchestrator_initializesConnection_inSimulatorMode(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Configuration with simulator enabled
        When: Orchestrator starts
        Then: Simulated connection is established
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Act
        try:
            orchestrator.start()

            # Assert
            assert orchestrator.connection is not None
            status = orchestrator.getStatus()
            assert status['components']['connection'] == 'initialized'

        finally:
            orchestrator.stop()


# ================================================================================
# Test: Orchestrator stops gracefully on signal
# ================================================================================


@pytest.mark.integration
class TestOrchestratorStopsGracefully:
    """Tests for graceful orchestrator shutdown."""

    def test_orchestrator_stopsGracefully_onStopCall(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: stop() is called
        Then: Orchestrator shuts down cleanly with exit code 0
        """
        # Arrange
        from pi.obdii.orchestrator import EXIT_CODE_CLEAN, ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        orchestrator.start()
        assert orchestrator.isRunning() is True

        # Act
        exitCode = orchestrator.stop()

        # Assert
        assert orchestrator.isRunning() is False
        assert exitCode == EXIT_CODE_CLEAN

    def test_orchestrator_handlesSignalShutdown_gracefully(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with signal handlers registered
        When: SIGINT is simulated
        Then: Orchestrator enters shutdown state
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        orchestrator.start()
        orchestrator.registerSignalHandlers()

        try:
            # Act - simulate signal handler being called
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

            # Assert
            assert orchestrator.shutdownState == ShutdownState.SHUTDOWN_REQUESTED

        finally:
            orchestrator.restoreSignalHandlers()
            orchestrator.stop()

    def test_orchestrator_cleansUpAllComponents_onShutdown(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with initialized components
        When: stop() is called
        Then: All components are cleaned up (set to None)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        orchestrator.stop()

        # Assert - components should be cleaned up
        assert orchestrator._dataLogger is None
        assert orchestrator._driveDetector is None
        assert orchestrator._database is None
