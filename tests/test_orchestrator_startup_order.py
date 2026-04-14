################################################################################
# File Name: test_orchestrator_startup.py
# Purpose/Description: Tests for orchestrator startup sequence (US-OSC-002)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-002
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator startup sequence.

Verifies that the orchestrator:
- Initializes components in correct dependency order
- Logs INFO for each step start and success
- Logs ERROR on component failure
- Uses exponential backoff from config for connection retry
- Can be aborted with Ctrl+C at any point
- Cleans up partial state on failure
- Logs total startup time at completion

Usage:
    pytest tests/test_orchestrator_startup.py -v
"""

import logging
import os
import tempfile
from typing import Any

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getStartupTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create minimal test configuration for startup tests.

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
                'name': 'Startup Test',
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
                'retryDelays': [0.1, 0.2, 0.4],
                'maxRetries': 3,
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
                        'description': 'Profile for startup tests',
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
                'healthCheckIntervalSeconds': 2,
                'dataRateLogIntervalSeconds': 5
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
def startupConfig(tempDb: str) -> dict[str, Any]:
    """Create startup test configuration with temp database."""
    return getStartupTestConfig(tempDb)


# ================================================================================
# AC1: Startup sequence follows correct dependency order
# ================================================================================


@pytest.mark.integration
class TestStartupSequenceOrder:
    """Tests that startup initializes components in dependency order."""

    def test_startup_initializesComponentsInDependencyOrder(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration with simulator enabled
        When: Orchestrator starts
        Then: Components are initialized in correct dependency order
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Act
        with caplog.at_level(logging.INFO):
            try:
                orchestrator.start()

                # Assert - extract component 'Starting X...' messages
                # from orchestrator logger only (exclude top-level
                # 'Starting ApplicationOrchestrator...')
                startMessages = [
                    record.message
                    for record in caplog.records
                    if record.name == 'pi.obd.orchestrator'
                    and record.message.startswith("Starting ")
                    and record.message.endswith("...")
                    and "ApplicationOrchestrator" not in record.message
                ]

                # Database must be first (everything depends on it)
                assert startMessages[0] == "Starting database..."

                # ProfileManager must come before connection
                dbIdx = startMessages.index("Starting database...")
                pmIdx = startMessages.index("Starting profileManager...")
                connIdx = startMessages.index("Starting connection...")
                assert dbIdx < pmIdx < connIdx

                # DataLogger must be last among core components
                # (depends on connection and database)
                dlIdx = startMessages.index("Starting dataLogger...")
                assert dlIdx > connIdx

            finally:
                orchestrator.stop()

    def test_startup_initializesDatabaseBeforeAllOtherComponents(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts
        Then: Database is initialized before all other components
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Act
        with caplog.at_level(logging.INFO):
            try:
                orchestrator.start()

                # Filter to orchestrator component-level messages only
                startMessages = [
                    record.message
                    for record in caplog.records
                    if record.name == 'pi.obd.orchestrator'
                    and record.message.startswith("Starting ")
                    and record.message.endswith("...")
                    and "ApplicationOrchestrator" not in record.message
                ]

                # Assert - database is first
                assert startMessages[0] == "Starting database..."

                # All other components come after database
                for msg in startMessages[1:]:
                    assert msg != "Starting database..."

            finally:
                orchestrator.stop()

    def test_startup_statisticsBeforeDriveDetector(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts
        Then: StatisticsEngine is initialized before DriveDetector
              (DriveDetector depends on StatisticsEngine for post-drive analysis)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Act
        with caplog.at_level(logging.INFO):
            try:
                orchestrator.start()

                startMessages = [
                    record.message
                    for record in caplog.records
                    if record.message.startswith("Starting ")
                    and record.message.endswith("...")
                ]

                # Assert - stats before drive detector
                statsIdx = startMessages.index("Starting statisticsEngine...")
                driveIdx = startMessages.index("Starting driveDetector...")
                assert statsIdx < driveIdx

            finally:
                orchestrator.stop()
