################################################################################
# File Name: test_orchestrator_profiles.py
# Purpose/Description: Tests for orchestrator profile system wiring (US-OSC-011)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-011
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator profile system wiring.

Verifies that the orchestrator correctly:
- Creates ProfileManager from config via factory function (AC1)
- Syncs profiles from config to database on startup (AC2)
- Loads active profile from config (AC3)
- Updates alert thresholds, polling interval, display on profile change (AC4)
- Queues profile switch if driving, activates on next drive start (AC5)
- Logs profile changes: 'Profile changed from [A] to [B]' (AC6)
- Passes typecheck and lint (AC7)

Usage:
    pytest tests/test_orchestrator_profiles.py -v
"""

import logging
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getProfileTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for profile system wiring tests.

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
                'name': 'Profile System Test',
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
                'showOnStartup': True
            },
            'staticData': {
                'parameters': ['VIN'],
                'queryOnFirstConnection': False
            },
            'realtimeData': {
                'pollingIntervalMs': 200,
                'parameters': [
                    {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'COOLANT_TEMP', 'logData': True, 'displayOnDashboard': True},
                ]
            },
            'analysis': {
                'triggerAfterDrive': True,
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 1,
                'driveEndRpmThreshold': 100,
                'driveEndDurationSeconds': 2,
                'calculateStatistics': ['max', 'min', 'avg']
            },
            'profiles': {
                'activeProfile': 'daily',
                'availableProfiles': [
                    {
                        'id': 'daily',
                        'name': 'Daily Profile',
                        'description': 'Normal daily driving',
                        'pollingIntervalMs': 200
                    },
                    {
                        'id': 'spirited',
                        'name': 'Spirited Profile',
                        'description': 'Spirited driving with higher thresholds',
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
def profileConfig(tempDb: str) -> dict[str, Any]:
    """Create profile test configuration with temp database."""
    return getProfileTestConfig(tempDb)


# ================================================================================
# AC4: Profile change updates alert thresholds, polling interval, display
# ================================================================================


class TestProfileChangeUpdatesComponents:
    """Tests that profile change updates alert thresholds, polling interval, display."""

    def test_handleProfileChange_updatesActiveProfile_onAlertManager(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager
        When: _handleProfileChange called with 'spirited'
        Then: Alert manager's setActiveProfile is called with 'spirited'
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockAlertManager = MagicMock()
            mockAlertManager.setActiveProfile = MagicMock()
            orchestrator._alertManager = mockAlertManager

            # Act
            orchestrator._handleProfileChange('daily', 'spirited')

            # Assert
            mockAlertManager.setActiveProfile.assert_called_once_with('spirited')
        finally:
            orchestrator.stop()

    def test_handleProfileChange_updatesPollingInterval_onDataLogger(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with data logger and profile with pollingIntervalMs
        When: _handleProfileChange called with 'spirited' (100ms polling)
        Then: Data logger's setPollingInterval is called with 100
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockDataLogger = MagicMock()
            mockDataLogger.setPollingInterval = MagicMock()
            orchestrator._dataLogger = mockDataLogger

            # Act
            orchestrator._handleProfileChange('daily', 'spirited')

            # Assert
            mockDataLogger.setPollingInterval.assert_called_once_with(100)
        finally:
            orchestrator.stop()

    def test_handleProfileChange_survivesAlertManagerError_continuesRunning(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Alert manager whose setActiveProfile raises on profile switch
        When: _handleProfileChange is called
        Then: Orchestrator continues (no crash), logs warning
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockAlertManager = MagicMock()
            mockAlertManager.setActiveProfile = MagicMock(
                side_effect=RuntimeError("alert manager failed on profile switch")
            )
            orchestrator._alertManager = mockAlertManager

            # Act & Assert - should not raise
            with caplog.at_level(logging.WARNING):
                orchestrator._handleProfileChange('daily', 'spirited')

            assert any(
                'Could not update alert manager' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_handleProfileChange_survivesDataLoggerError_continuesRunning(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Data logger that raises an exception
        When: _handleProfileChange is called
        Then: Orchestrator continues (no crash), logs warning
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockDataLogger = MagicMock()
            mockDataLogger.setPollingInterval = MagicMock(
                side_effect=RuntimeError("polling update failed")
            )
            orchestrator._dataLogger = mockDataLogger

            # Act & Assert - should not raise
            with caplog.at_level(logging.WARNING):
                orchestrator._handleProfileChange('daily', 'spirited')

            assert any(
                'Could not update data logger' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_handleProfileChange_noAlertManager_skipsGracefully(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no alert manager (None)
        When: _handleProfileChange is called
        Then: No error raised, runs silently
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            orchestrator._alertManager = None

            # Act & Assert - should not raise
            orchestrator._handleProfileChange('daily', 'spirited')
        finally:
            orchestrator.stop()

    def test_handleProfileChange_noDataLogger_skipsGracefully(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no data logger (None)
        When: _handleProfileChange is called
        Then: No error raised, runs silently
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            orchestrator._dataLogger = None

            # Act & Assert - should not raise
            orchestrator._handleProfileChange('daily', 'spirited')
        finally:
            orchestrator.stop()

    def test_handleProfileChange_profileNotFound_logsWarning(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile manager that can't find the profile
        When: _handleProfileChange called with unknown profile ID
        Then: Logs warning about not finding the profile
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockProfileManager = MagicMock()
            mockProfileManager.getProfile = MagicMock(
                side_effect=Exception("Profile not found: unknown")
            )
            orchestrator._profileManager = mockProfileManager

            # Act
            with caplog.at_level(logging.WARNING):
                orchestrator._handleProfileChange('daily', 'unknown')

            # Assert
            assert any(
                'Could not get profile' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()
