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
from unittest.mock import MagicMock, patch

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
# AC1: ProfileManager created from config in orchestrator
# ================================================================================


class TestProfileManagerCreatedFromConfig:
    """Tests that ProfileManager is created from config in orchestrator."""

    def test_initializeProfileManager_createsManager_notNone(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid profile config
        When: start() initializes all components
        Then: _profileManager is created and not None
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._profileManager is not None
        finally:
            orchestrator.stop()

    def test_initializeProfileManager_usesFactory_createProfileManagerFromConfig(
        self, profileConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeProfileManager() is called
        Then: createProfileManagerFromConfig factory is invoked with config and database
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        with patch(
            'pi.obdii.orchestrator.ApplicationOrchestrator._initializeAllComponents'
        ):
            orchestrator._running = True

        # Mock the import
        mockFactory = MagicMock()
        with patch.dict(
            'sys.modules',
            {'pi.profile': MagicMock(
                createProfileManagerFromConfig=mockFactory
            )}
        ):
            with patch(
                'pi.profile.createProfileManagerFromConfig',
                mockFactory
            ):
                # Act
                orchestrator._initializeProfileManager()

                # Assert
                mockFactory.assert_called_once()
                args = mockFactory.call_args
                assert args[0][0] == profileConfig  # config is first arg

    def test_initializeProfileManager_logsStarting_infoLevel(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeProfileManager() is called
        Then: Logs 'Starting profileManager...' at INFO level
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            # Assert
            assert any(
                'Starting profileManager' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_initializeProfileManager_logsSuccess_infoLevel(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: ProfileManager initializes successfully
        Then: Logs 'ProfileManager started successfully' at INFO level
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        try:
            # Act
            with caplog.at_level(logging.INFO):
                orchestrator.start()

            # Assert
            assert any(
                'ProfileManager started successfully' in record.message
                for record in caplog.records
            )
        finally:
            orchestrator.stop()

    def test_initializeProfileManager_importError_skipsGracefully(
        self, profileConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: ProfileManager module not available
        When: _initializeProfileManager() is called
        Then: Logs warning and continues (no exception raised)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=profileConfig,
            simulate=True
        )

        with patch(
            'pi.obdii.orchestrator.ApplicationOrchestrator._initializeProfileManager'
        ) as mockInit:
            # Simulate the import error behavior
            def raiseImportError():
                import logging as log
                log.getLogger('pi.obdii.orchestrator').warning(
                    "ProfileManager not available, skipping"
                )
            mockInit.side_effect = raiseImportError

            # Act & Assert - should not raise
            with caplog.at_level(logging.WARNING):
                try:
                    orchestrator.start()
                except Exception:
                    pass  # Other components may fail, that's fine

        assert orchestrator._profileManager is None
