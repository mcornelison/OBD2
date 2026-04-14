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
from typing import Any
from unittest.mock import MagicMock

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
# Test: Profile switch works correctly
# ================================================================================


@pytest.mark.integration
class TestProfileSwitchWorksCorrectly:
    """Tests for profile switching functionality."""

    def test_orchestrator_logsProfileChange(
        self, integrationConfig: dict[str, Any], caplog
    ):
        """
        Given: Running orchestrator
        When: Profile change is triggered
        Then: Change is logged with old and new profile IDs
        """
        # Arrange
        import logging

        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._handleProfileChange('default', 'test')

            # Assert
            assert any(
                'Profile changed' in record.message
                and 'default' in record.message
                and 'test' in record.message
                for record in caplog.records
            )

        finally:
            orchestrator.stop()

    def test_orchestrator_handlesFirstProfileChange_withNoneOldProfile(
        self, integrationConfig: dict[str, Any], caplog
    ):
        """
        Given: Running orchestrator with no previous profile
        When: First profile is set
        Then: Change is logged with None as old profile
        """
        # Arrange
        import logging

        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._handleProfileChange(None, 'test')

            # Assert
            assert any(
                'Profile changed' in record.message
                and 'None' in record.message
                for record in caplog.records
            )

        finally:
            orchestrator.stop()

    def test_orchestrator_updatesAlertManager_onProfileChange(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with alert manager
        When: Profile changes
        Then: Alert manager thresholds are updated for new profile
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Mock alert manager methods if it exists
            if orchestrator._alertManager is not None:
                orchestrator._alertManager.setActiveProfile = MagicMock()

                # Act
                orchestrator._handleProfileChange('default', 'test')

                # Assert - at minimum, setActiveProfile should be called
                orchestrator._alertManager.setActiveProfile.assert_called_with(
                    'test'
                )

        finally:
            orchestrator.stop()

    def test_orchestrator_continuesRunning_afterProfileChangeError(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator where profile change causes error
        When: _handleProfileChange encounters an exception
        Then: Orchestrator continues running without crashing
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Mock profileManager.getProfile to raise an exception
            if orchestrator._profileManager is not None:
                orchestrator._profileManager.getProfile = MagicMock(
                    side_effect=RuntimeError("Profile not found")
                )

            # Act - should not crash
            orchestrator._handleProfileChange('old', 'nonexistent')

            # Assert - still running
            assert orchestrator.isRunning() is True

        finally:
            orchestrator.stop()
