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
# AC6: Profile changes logged: 'Profile changed from [A] to [B]'
# ================================================================================


class TestProfileChangesLogged:
    """Tests that profile changes are logged correctly."""

    def test_handleProfileChange_logsMessage_withOldAndNew(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator running
        When: _handleProfileChange('daily', 'spirited') called
        Then: Logs 'Profile changed from daily to spirited' at INFO level
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._handleProfileChange('daily', 'spirited')

            # Assert
            assert any(
                'Profile changed from daily to spirited' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_handleProfileChange_logsMessage_noneToProfile(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator running, no previous profile (None)
        When: _handleProfileChange(None, 'daily') called
        Then: Logs 'Profile changed from None to daily'
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._handleProfileChange(None, 'daily')

            # Assert
            assert any(
                'Profile changed from None to daily' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_profileSwitcher_switchActivated_logsProfileSwitched(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: ProfileSwitcher running with 'daily' active
        When: requestProfileSwitch('spirited') called (not driving)
        Then: Logs 'Profile switched: daily -> spirited'
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Act
            with caplog.at_level(logging.INFO):
                ps.requestProfileSwitch('spirited')

            # Assert
            assert any(
                'Profile switched' in record.message
                and 'daily' in record.message
                and 'spirited' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_profileSwitcher_switchQueued_logsPendingMessage(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: ProfileSwitcher running, drive in progress
        When: requestProfileSwitch('spirited') called
        Then: Logs queued message with 'will activate on next drive start'
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Simulate driving
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector

            # Act
            with caplog.at_level(logging.INFO):
                ps.requestProfileSwitch('spirited')

            # Assert
            assert any(
                'Profile switch queued' in record.message
                and 'next drive start' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()


# ================================================================================
# AC7: Typecheck/lint passes (verified by running make lint)
# Additional wiring tests
# ================================================================================


class TestProfileCallbackWiring:
    """Tests that profile callbacks are properly wired in the orchestrator."""

    def test_setupComponentCallbacks_wiresProfileSwitcher_onProfileChange(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with profileSwitcher
        When: _setupComponentCallbacks() called
        Then: ProfileSwitcher.onProfileChange receives _handleProfileChange callback
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # _setupComponentCallbacks is called in runWorkflow(), call it explicitly
            orchestrator._setupComponentCallbacks()

            # Assert - verify callback is registered
            ps = orchestrator._profileSwitcher
            assert ps is not None
            assert len(ps._onProfileChange) > 0
        finally:
            orchestrator.stop()

    def test_profileSwitcherCallback_triggersHandleProfileChange(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile switcher callback wired
        When: ProfileSwitcher fires a profile change event
        Then: Orchestrator's _handleProfileChange is called (logs profile change)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Wire callbacks (normally done in runWorkflow)
            orchestrator._setupComponentCallbacks()

            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Act - trigger a profile switch which fires the callback
            with caplog.at_level(logging.INFO):
                ps.requestProfileSwitch('spirited')

            # Assert - _handleProfileChange should have been called via callback
            assert any(
                'Profile changed from daily to spirited' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_setupCallbacks_noProfileSwitcher_skipsGracefully(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with _profileSwitcher = None
        When: _setupComponentCallbacks() called
        Then: No error raised (skips profile switcher wiring)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        orchestrator._profileSwitcher = None

        # Act & Assert - should not raise
        orchestrator._setupComponentCallbacks()

    def test_profileSwitcher_initializeFromConfig_setsActiveProfile(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: ProfileSwitcher created from config
        When: initializeFromConfig(config) called
        Then: Logs initialization of active profile from config
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            # Assert
            assert any(
                'Initialized active profile from config' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()
