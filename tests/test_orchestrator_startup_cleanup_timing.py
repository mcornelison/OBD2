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
import re
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
# AC7: Partial startup state cleaned up on failure
# ================================================================================


@pytest.mark.integration
class TestPartialStartupCleanup:
    """Tests that partial initialization is cleaned up on failure."""

    def test_startup_cleansUpOnComponentFailure(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with a component that will fail mid-startup
        When: Startup fails after some components initialized
        Then: Cleanup is performed for partially initialized components
        """
        # Arrange
        from pi.obd.orchestrator import (
            ApplicationOrchestrator,
            ComponentInitializationError,
            OrchestratorError,
        )

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Force connection init to fail (after database + profileManager succeed)
        with patch.object(
            orchestrator, '_initializeConnection',
            side_effect=ComponentInitializationError(
                "Connection failed: test error",
                component='connection'
            )
        ):
            # Act
            with caplog.at_level(logging.INFO):
                with pytest.raises(OrchestratorError):
                    orchestrator.start()

                # Assert - cleanup was logged
                allMessages = [record.message for record in caplog.records]
                assert any(
                    "cleanup" in msg.lower() or "Cleaning up" in msg
                    for msg in allMessages
                ), f"Expected cleanup log message, got: {allMessages}"

    def test_startup_isNotRunningAfterFailure(
        self, startupConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with a component that will fail
        When: Startup fails
        Then: Orchestrator is not in running state
        """
        # Arrange
        from pi.obd.orchestrator import (
            ApplicationOrchestrator,
            ComponentInitializationError,
            OrchestratorError,
        )

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Force failure during initialization
        with patch.object(
            orchestrator, '_initializeConnection',
            side_effect=ComponentInitializationError(
                "Connection failed: test error",
                component='connection'
            )
        ):
            # Act
            with pytest.raises(OrchestratorError):
                orchestrator.start()

            # Assert
            assert orchestrator.isRunning() is False

    def test_startup_cleansUpOnKeyboardInterrupt(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator starting up
        When: Ctrl+C aborts startup
        Then: Partial state is cleaned up
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        with patch.object(
            orchestrator, '_initializeAllComponents',
            side_effect=KeyboardInterrupt
        ):
            with caplog.at_level(logging.INFO):
                # Act
                with pytest.raises(KeyboardInterrupt):
                    orchestrator.start()

                # Assert - cleanup was performed
                allMessages = [record.message for record in caplog.records]
                assert any(
                    "cleanup" in msg.lower() or "Cleaning up" in msg
                    for msg in allMessages
                )


# ================================================================================
# AC8: Total startup time logged at completion
# ================================================================================


@pytest.mark.integration
class TestStartupTiming:
    """Tests that total startup time is logged."""

    def test_startup_logsTotalStartupTime(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts successfully
        Then: Total startup time is logged with seconds
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

                # Assert - look for startup_time in log
                infoMessages = [
                    record.message
                    for record in caplog.records
                    if record.levelno == logging.INFO
                ]

                assert any(
                    "startup_time=" in msg
                    for msg in infoMessages
                ), f"Expected startup_time in logs, got: {infoMessages}"

            finally:
                orchestrator.stop()

    def test_startup_timingIncludesSecondsValue(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts successfully
        Then: Startup time includes numeric seconds value
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

                # Assert - find the timing message and verify format
                timingMessages = [
                    record.message
                    for record in caplog.records
                    if "startup_time=" in record.message
                ]

                assert len(timingMessages) >= 1

                # Verify the format is startup_time=X.XXs
                timingMsg = timingMessages[0]
                match = re.search(r'startup_time=(\d+\.\d+)s', timingMsg)
                assert match is not None, (
                    f"Expected startup_time=X.XXs format, got: {timingMsg}"
                )

                # Verify the time is a reasonable positive number
                startupSeconds = float(match.group(1))
                assert startupSeconds >= 0.0
                assert startupSeconds < 30.0  # Should be fast in tests

            finally:
                orchestrator.stop()

    def test_startup_logsReadyMessage(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts successfully
        Then: A ready/success message is logged at completion
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

                infoMessages = [
                    record.message
                    for record in caplog.records
                    if record.levelno == logging.INFO
                ]

                # Assert - should have a final success/ready message
                assert any(
                    "started successfully" in msg
                    and "ApplicationOrchestrator" in msg
                    for msg in infoMessages
                ), "Expected ApplicationOrchestrator started successfully message"

            finally:
                orchestrator.stop()


# ================================================================================
# AC9: Typecheck/lint passes (verified by running make lint)
# ================================================================================
# This AC is validated by running the full quality check suite,
# not by a specific test case.
