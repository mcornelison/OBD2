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
import tempfile
import time
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
# Test: Statistics calculated after simulated drive ends
# ================================================================================


@pytest.mark.integration
class TestStatisticsAfterDriveEnd:
    """Tests for statistics calculation after drive ends."""

    def test_orchestrator_logsDriveEnd_withDuration(
        self, integrationConfig: dict[str, Any], caplog
    ):
        """
        Given: Running orchestrator
        When: Drive end callback is triggered
        Then: Drive end is logged with duration
        """
        # Arrange
        import logging

        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            class MockSession:
                id = 'test-session'
                duration = 120.5

            with caplog.at_level(logging.INFO):
                orchestrator._handleDriveEnd(MockSession())

            # Assert - check log message
            assert any(
                'Drive ended' in record.message and '120.5' in record.message
                for record in caplog.records
            )

        finally:
            orchestrator.stop()

    def test_orchestrator_callsExternalCallback_onDriveEnd(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with registered drive end callback
        When: Drive ends
        Then: External callback is invoked with session
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        callbackCalled = []

        def onDriveEnd(session: Any) -> None:
            callbackCalled.append(session)

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(onDriveEnd=onDriveEnd)

            # Act
            class MockSession:
                id = 'drive-session-456'
                duration = 300.0

            orchestrator._handleDriveEnd(MockSession())

            # Assert
            assert len(callbackCalled) == 1
            assert callbackCalled[0].id == 'drive-session-456'

        finally:
            orchestrator.stop()

    def test_orchestrator_notifiesAnalysisComplete_viaCallback(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with analysis complete callback registered
        When: Analysis complete event occurs
        Then: Callback is invoked with result
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        callbackResults = []

        def onAnalysisComplete(result: Any) -> None:
            callbackResults.append(result)

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(onAnalysisComplete=onAnalysisComplete)

            # Act
            mockResult = {'statistics': {'RPM': {'max': 6000, 'min': 800}}}
            orchestrator._handleAnalysisComplete(mockResult)

            # Assert
            assert len(callbackResults) == 1
            assert callbackResults[0] == mockResult

        finally:
            orchestrator.stop()


# ================================================================================
# Test: Tests use temporary database
# ================================================================================


@pytest.mark.integration
class TestTemporaryDatabaseUsage:
    """Tests to verify temporary database usage."""

    def test_integrationTests_useTemporaryDatabase(
        self, integrationConfig: dict[str, Any], tempDb: str
    ):
        """
        Given: Integration test configuration
        When: Test runs
        Then: Temporary database path is used, not production
        """
        # Assert - config uses temp db path
        assert integrationConfig['pi']['database']['path'] == tempDb
        assert tempDb.endswith('.db')
        assert 'obd.db' not in tempDb

    def test_databaseFile_isCreatedInTempLocation(
        self, integrationConfig: dict[str, Any], tempDb: str
    ):
        """
        Given: Orchestrator started with temp database config
        When: Database is initialized
        Then: Database file is in temp location
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert os.path.exists(tempDb)
            # Verify it's actually our temp file
            assert tempDb == integrationConfig['pi']['database']['path']

        finally:
            orchestrator.stop()


# ================================================================================
# Test: Tests complete within time limit
# ================================================================================


@pytest.mark.integration
class TestCompletionWithinTimeLimit:
    """Tests to verify tests complete within acceptable time."""

    def test_orchestrator_startsAndStops_withinTimeLimit(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts and stops
        Then: Completes within reasonable time (< 10 seconds)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        startTime = time.time()

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Act
        orchestrator.start()
        orchestrator.stop()

        # Assert
        elapsed = time.time() - startTime
        assert elapsed < 10, f"Start/stop took too long: {elapsed:.2f}s"

    def test_healthCheck_executesQuickly(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: Health check is performed
        Then: Completes in under 1 second
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            startTime = time.time()
            orchestrator._performHealthCheck()
            elapsed = time.time() - startTime

            # Assert
            assert elapsed < 1.0, f"Health check too slow: {elapsed:.2f}s"

        finally:
            orchestrator.stop()


@pytest.mark.integration
class TestDashboardParameterRouting:
    """Tests for dashboard parameter routing."""

    def test_orchestrator_extractsDashboardParameters_fromConfig(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Configuration with displayOnDashboard flags
        When: Orchestrator is created
        Then: Dashboard parameters are extracted correctly
        """
        # Arrange & Act
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Assert
        dashboardParams = orchestrator._dashboardParameters
        assert 'RPM' in dashboardParams
        assert 'SPEED' in dashboardParams
        assert 'COOLANT_TEMP' in dashboardParams
        assert 'ENGINE_LOAD' not in dashboardParams  # displayOnDashboard: False
