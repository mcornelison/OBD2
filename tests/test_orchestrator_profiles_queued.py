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
# AC5: Profile switch queued if driving (activated on next drive start)
# ================================================================================


class TestProfileSwitchQueuedIfDriving:
    """Tests that profile switch is queued if driving and activated on next drive start."""

    def test_profileSwitcher_requestSwitch_whileNotDriving_switchesImmediately(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator running, not driving
        When: ProfileSwitcher.requestProfileSwitch('spirited') called
        Then: Active profile changes immediately to 'spirited'
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None
            assert ps.getActiveProfileId() == 'daily'

            # Act
            ps.requestProfileSwitch('spirited')

            # Assert
            assert ps.getActiveProfileId() == 'spirited'
        finally:
            orchestrator.stop()

    def test_profileSwitcher_requestSwitch_whileDriving_queuesSwitch(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator running, drive in progress
        When: ProfileSwitcher.requestProfileSwitch('spirited') called
        Then: Switch is queued (pending), active remains 'daily'
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Simulate drive in progress
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector

            # Act
            ps.requestProfileSwitch('spirited')

            # Assert
            assert ps.getActiveProfileId() == 'daily'  # Still daily
            assert ps.hasPendingSwitch()
            assert ps.getPendingProfileId() == 'spirited'
        finally:
            orchestrator.stop()

    def test_profileSwitcher_pendingSwitch_activatesOnDriveStart(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Profile switch pending for 'spirited'
        When: Drive starts
        Then: Active profile switches to 'spirited'
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Queue a switch while "driving"
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector
            ps.requestProfileSwitch('spirited')

            assert ps.hasPendingSwitch()

            # Act - simulate drive start
            mockSession = MagicMock()
            ps._onDriveStart(mockSession)

            # Assert
            assert ps.getActiveProfileId() == 'spirited'
            assert not ps.hasPendingSwitch()
        finally:
            orchestrator.stop()

    def test_profileSwitcher_cancelPending_clearsPendingSwitch(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Profile switch pending for 'spirited'
        When: cancelPendingSwitch() called
        Then: Pending switch is cleared, active profile unchanged
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Queue a switch while "driving"
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector
            ps.requestProfileSwitch('spirited')

            assert ps.hasPendingSwitch()

            # Act
            result = ps.cancelPendingSwitch()

            # Assert
            assert result is True
            assert not ps.hasPendingSwitch()
            assert ps.getActiveProfileId() == 'daily'
        finally:
            orchestrator.stop()

    def test_profileSwitcher_driveEnd_doesNotActivatePending(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Profile switch pending for 'spirited'
        When: Drive ends
        Then: Pending switch is NOT activated (waits for next drive start)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()
            ps = orchestrator._profileSwitcher
            assert ps is not None

            # Queue a switch while "driving"
            mockDriveDetector = MagicMock()
            mockDriveDetector.isDriving = MagicMock(return_value=True)
            ps._driveDetector = mockDriveDetector
            ps.requestProfileSwitch('spirited')

            # Act - simulate drive end
            mockSession = MagicMock()
            ps._onDriveEnd(mockSession)

            # Assert - still pending, not activated
            assert ps.getActiveProfileId() == 'daily'
            assert ps.hasPendingSwitch()
        finally:
            orchestrator.stop()
