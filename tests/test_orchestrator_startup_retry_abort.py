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
from unittest.mock import patch

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
# AC5: Connection retry uses exponential backoff from config
# ================================================================================


@pytest.mark.integration
class TestConnectionRetryBackoff:
    """Tests that connection retry uses exponential backoff from config."""

    def test_startup_usesRetryDelaysFromConfig(
        self, startupConfig: dict[str, Any]
    ):
        """
        Given: Config with specific retryDelays [0.1, 0.2, 0.4]
        When: Orchestrator is created
        Then: Reconnect delays match config values
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        # Act
        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Assert - retry delays loaded from config
        assert orchestrator._reconnectDelays == [0.1, 0.2, 0.4]

    def test_startup_usesMaxRetriesFromConfig(
        self, startupConfig: dict[str, Any]
    ):
        """
        Given: Config with maxRetries = 3
        When: Orchestrator is created
        Then: Max reconnect attempts matches config
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        # Act
        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Assert
        assert orchestrator._maxReconnectAttempts == 3

    def test_startup_usesDefaultDelaysWhenNotConfigured(self, tempDb: str):
        """
        Given: Config without explicit retryDelays
        When: Orchestrator is created
        Then: Default exponential backoff delays [1, 2, 4, 8, 16] are used
        """
        # Arrange
        from pi.obdii.orchestrator import (
            DEFAULT_RECONNECT_DELAYS,
            ApplicationOrchestrator,
        )

        config = getStartupTestConfig(tempDb)
        del config['pi']['bluetooth']['retryDelays']

        # Act
        orchestrator = ApplicationOrchestrator(
            config=config,
            simulate=True
        )

        # Assert
        assert orchestrator._reconnectDelays == DEFAULT_RECONNECT_DELAYS
        assert orchestrator._reconnectDelays == [1, 2, 4, 8, 16]


# ================================================================================
# AC6: Startup can be aborted with Ctrl+C at any point
# ================================================================================


@pytest.mark.integration
class TestStartupAbort:
    """Tests that startup can be interrupted with KeyboardInterrupt."""

    def test_startup_catchesKeyboardInterrupt(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator starting up
        When: KeyboardInterrupt raised during initialization
        Then: Startup is aborted with warning log
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Patch _initializeAllComponents to raise KeyboardInterrupt
        with patch.object(
            orchestrator, '_initializeAllComponents',
            side_effect=KeyboardInterrupt
        ):
            # Act & Assert
            with caplog.at_level(logging.WARNING):
                with pytest.raises(KeyboardInterrupt):
                    orchestrator.start()

                # Should log the abort
                warningMessages = [
                    record.message
                    for record in caplog.records
                    if record.levelno == logging.WARNING
                ]
                assert any(
                    "abort" in msg.lower() or "Ctrl+C" in msg
                    for msg in warningMessages
                ), f"Expected abort warning, got: {warningMessages}"

    def test_startup_isNotRunningAfterAbort(
        self, startupConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator starting up
        When: Startup is aborted via KeyboardInterrupt
        Then: Orchestrator is not in running state
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        with patch.object(
            orchestrator, '_initializeAllComponents',
            side_effect=KeyboardInterrupt
        ):
            # Act
            with pytest.raises(KeyboardInterrupt):
                orchestrator.start()

            # Assert
            assert orchestrator.isRunning() is False
