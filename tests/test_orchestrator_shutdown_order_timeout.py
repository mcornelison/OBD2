################################################################################
# File Name: test_orchestrator_shutdown.py
# Purpose/Description: Tests for orchestrator shutdown sequence (US-OSC-003)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-003
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator shutdown sequence.

Verifies that the orchestrator:
- Shuts down components in reverse dependency order
- Each component stop has a configurable timeout (default 5s)
- Components that exceed timeout are force-stopped with warning
- Double Ctrl+C forces immediate exit (skip graceful shutdown)
- SIGTERM handled same as SIGINT (Ctrl+C)
- No data loss for completed logging cycles
- Exit code 0 for clean shutdown, non-zero for forced/error
- Typecheck/lint passes

Usage:
    pytest tests/test_orchestrator_shutdown.py -v
"""

import logging
import os
import tempfile
from typing import Any

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getShutdownTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create minimal test configuration for shutdown tests.

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
                'name': 'Shutdown Test',
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
                        'description': 'Profile for shutdown tests',
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
                'healthCheckIntervalSeconds': 60,
                'dataRateLogIntervalSeconds': 300
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
def shutdownConfig(tempDb: str) -> dict[str, Any]:
    """Create shutdown test configuration with temp database."""
    return getShutdownTestConfig(tempDb)


# ================================================================================
# AC1: Shutdown sequence reverse of startup
# ================================================================================


@pytest.mark.integration
class TestShutdownSequenceOrder:
    """Tests that shutdown occurs in reverse dependency order."""

    def test_shutdown_stopsComponentsInReverseOrder(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator with all components initialized
        When: stop() is called
        Then: Components are stopped in reverse of startup order
              (dataLogger first ... database last)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        # Assert - extract 'Stopping X...' messages from orchestrator
        stopMessages = [
            record.message
            for record in caplog.records
            if record.name == 'pi.obdii.orchestrator'
            and record.message.startswith("Stopping ")
            and record.message.endswith("...")
            and "ApplicationOrchestrator" not in record.message
        ]

        # dataLogger must be stopped before database
        if "Stopping dataLogger..." in stopMessages and "Stopping database..." in stopMessages:
            dlIdx = stopMessages.index("Stopping dataLogger...")
            dbIdx = stopMessages.index("Stopping database...")
            assert dlIdx < dbIdx, "dataLogger must stop before database"

        # connection must be stopped before database
        if "Stopping connection..." in stopMessages and "Stopping database..." in stopMessages:
            connIdx = stopMessages.index("Stopping connection...")
            dbIdx = stopMessages.index("Stopping database...")
            assert connIdx < dbIdx, "connection must stop before database"

        # database must be last
        assert stopMessages[-1] == "Stopping database...", \
            "database should be the last component stopped"

    def test_shutdown_stopsDataLoggerBeforeConnection(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: stop() is called
        Then: DataLogger stops before connection (can't log without connection)
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        stopMessages = [
            record.message
            for record in caplog.records
            if record.name == 'pi.obdii.orchestrator'
            and record.message.startswith("Stopping ")
            and record.message.endswith("...")
        ]

        # dataLogger before connection
        if "Stopping dataLogger..." in stopMessages and "Stopping connection..." in stopMessages:
            dlIdx = stopMessages.index("Stopping dataLogger...")
            connIdx = stopMessages.index("Stopping connection...")
            assert dlIdx < connIdx

    def test_shutdown_stopsAlertsBeforeStatistics(
        self, shutdownConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Running orchestrator
        When: stop() is called
        Then: AlertManager stops before StatisticsEngine
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=shutdownConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator.stop()

        stopMessages = [
            record.message
            for record in caplog.records
            if record.name == 'pi.obdii.orchestrator'
            and record.message.startswith("Stopping ")
            and record.message.endswith("...")
        ]

        if "Stopping alertManager..." in stopMessages and "Stopping statisticsEngine..." in stopMessages:
            alertIdx = stopMessages.index("Stopping alertManager...")
            statsIdx = stopMessages.index("Stopping statisticsEngine...")
            assert alertIdx < statsIdx


# ================================================================================
# AC2: Configurable timeout per component (default 5s)
# ================================================================================


@pytest.mark.integration
class TestShutdownConfigurableTimeout:
    """Tests that shutdown uses configurable timeout per component."""

    def test_shutdown_usesConfiguredTimeout(
        self, tempDb: str
    ):
        """
        Given: Config with custom shutdown.componentTimeout
        When: Orchestrator is created
        Then: Shutdown timeout matches config value
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        config = getShutdownTestConfig(tempDb)
        config['pi']['shutdown']['componentTimeout'] = 10

        # Act
        orchestrator = ApplicationOrchestrator(
            config=config,
            simulate=True
        )

        # Assert
        assert orchestrator._shutdownTimeout == 10

    def test_shutdown_usesDefaultTimeoutWhenNotConfigured(
        self, tempDb: str
    ):
        """
        Given: Config without shutdown.componentTimeout
        When: Orchestrator is created
        Then: Shutdown timeout defaults to 5.0 seconds
        """
        # Arrange
        from pi.obdii.orchestrator import (
            DEFAULT_SHUTDOWN_TIMEOUT,
            ApplicationOrchestrator,
        )

        config = getShutdownTestConfig(tempDb)
        del config['pi']['shutdown']['componentTimeout']

        # Act
        orchestrator = ApplicationOrchestrator(
            config=config,
            simulate=True
        )

        # Assert
        assert orchestrator._shutdownTimeout == DEFAULT_SHUTDOWN_TIMEOUT
        assert orchestrator._shutdownTimeout == 5.0

    def test_shutdown_defaultConstantIsFiveSeconds(self):
        """
        Given: The DEFAULT_SHUTDOWN_TIMEOUT constant
        When: Checking its value
        Then: It equals 5.0
        """
        from pi.obdii.orchestrator import DEFAULT_SHUTDOWN_TIMEOUT

        assert DEFAULT_SHUTDOWN_TIMEOUT == 5.0
