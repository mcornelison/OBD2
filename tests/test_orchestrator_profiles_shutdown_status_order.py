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


class TestProfileShutdown:
    """Tests that profile components are properly shut down."""

    def test_shutdown_profileManager_setToNone(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with running profile manager
        When: stop() called
        Then: _profileManager is set to None
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        orchestrator.start()
        assert orchestrator._profileManager is not None

        # Act
        orchestrator.stop()

        # Assert
        assert orchestrator._profileManager is None

    def test_shutdown_profileSwitcher_setToNone(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with running profile switcher
        When: stop() called
        Then: _profileSwitcher is set to None
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        orchestrator.start()
        assert orchestrator._profileSwitcher is not None

        # Act
        orchestrator.stop()

        # Assert
        assert orchestrator._profileSwitcher is None


class TestProfileStatusReporting:
    """Tests that profile status is included in orchestrator status."""

    def test_getStatus_includesProfileManager(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with profile manager running
        When: getStatus() called
        Then: Status dict components includes 'profileManager' key
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            status = orchestrator.getStatus()

            # Assert
            components = status.get('components', status)
            assert 'profileManager' in components
        finally:
            orchestrator.stop()

    def test_getStatus_includesProfileSwitcher(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with profile switcher running
        When: getStatus() called
        Then: Status dict components includes 'profileSwitcher' key
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            status = orchestrator.getStatus()

            # Assert
            components = status.get('components', status)
            assert 'profileSwitcher' in components
        finally:
            orchestrator.stop()


class TestProfileInitOrder:
    """Tests that profile components are initialized in correct dependency order."""

    def test_initOrder_profileManagerBeforeConnection(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile config
        When: start() initializes all components
        Then: profileManager starts before connection (step 2 before step 3)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            # Find indices of log messages
            messages = [record.message for record in caplog.records]

            profileStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting profileManager' in m),
                None
            )
            connectionStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting connection' in m),
                None
            )

            # Assert
            assert profileStartIdx is not None
            assert connectionStartIdx is not None
            assert profileStartIdx < connectionStartIdx
        finally:
            orchestrator.stop()

    def test_initOrder_profileSwitcherAfterDriveDetector(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile config
        When: start() initializes all components
        Then: profileSwitcher starts after driveDetector (needs drive state)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            messages = [record.message for record in caplog.records]

            driveStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting driveDetector' in m),
                None
            )
            switcherStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting profileSwitcher' in m),
                None
            )

            # Assert
            assert driveStartIdx is not None
            assert switcherStartIdx is not None
            assert driveStartIdx < switcherStartIdx
        finally:
            orchestrator.stop()

    def test_initOrder_databaseBeforeProfileManager(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with profile config
        When: start() initializes all components
        Then: database starts before profileManager (DB needed for sync)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            messages = [record.message for record in caplog.records]

            dbStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting database' in m),
                None
            )
            profileStartIdx = next(
                (i for i, m in enumerate(messages)
                 if 'Starting profileManager' in m),
                None
            )

            # Assert
            assert dbStartIdx is not None
            assert profileStartIdx is not None
            assert dbStartIdx < profileStartIdx
        finally:
            orchestrator.stop()
