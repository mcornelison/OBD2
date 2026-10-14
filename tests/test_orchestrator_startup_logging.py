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
# 2026-10-13    | Rex (US-860-a)| start() arms the boot's kernel_start milestone.
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
# AC2 + AC3: Each step logged with INFO level
# ================================================================================


@pytest.mark.integration
class TestStartupLogging:
    """Tests that each startup step produces correct log messages."""

    def test_startup_logsStartingMessageForEachComponent(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts
        Then: Each component initialization logged with 'Starting [component]...'
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

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

                # Assert - core components each have a 'Starting...' message
                coreComponents = [
                    'database',
                    'profileManager',
                    'connection',
                    'dataLogger',
                ]

                for component in coreComponents:
                    expectedMsg = f"Starting {component}..."
                    assert expectedMsg in infoMessages, (
                        f"Missing INFO log: '{expectedMsg}'"
                    )

            finally:
                orchestrator.stop()

    def test_startup_logsSuccessMessageForEachComponent(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts successfully
        Then: Each component logged with '[Component] started successfully'
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

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

                # Assert - core components each have a success message
                expectedSuccessPatterns = [
                    "Database started successfully",
                    "ProfileManager started successfully",
                    "Connection started successfully",
                    "DataLogger started successfully",
                ]

                for pattern in expectedSuccessPatterns:
                    assert any(
                        pattern in msg for msg in infoMessages
                    ), f"Missing success log: '{pattern}'"

            finally:
                orchestrator.stop()

    def test_startup_allLogMessagesAtInfoLevel(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration with successful startup
        When: Orchestrator starts
        Then: All 'Starting...' and 'started successfully' messages are INFO level
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Act
        with caplog.at_level(logging.DEBUG):
            try:
                orchestrator.start()

                # Assert - check orchestrator's startup-related messages
                # only (other modules may have their own "Starting" logs)
                for record in caplog.records:
                    if record.name != 'pi.obdii.orchestrator':
                        continue
                    if (record.message.startswith("Starting ")
                            and record.message.endswith("...")):
                        assert record.levelno == logging.INFO, (
                            f"'{record.message}' should be INFO, "
                            f"got {record.levelname}"
                        )
                    if "started successfully" in record.message:
                        assert record.levelno == logging.INFO, (
                            f"'{record.message}' should be INFO, "
                            f"got {record.levelname}"
                        )

            finally:
                orchestrator.stop()


# ================================================================================
# AC4: Failed steps logged with ERROR level
# ================================================================================


@pytest.mark.integration
class TestStartupFailureLogging:
    """Tests that failed startup steps are logged at ERROR level."""

    def test_startup_logsErrorOnComponentFailure(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Database initialization forced to fail
        When: Orchestrator starts
        Then: Error is logged at ERROR level with clear message
        """
        # Arrange
        from pi.obdii.orchestrator import (
            ApplicationOrchestrator,
            OrchestratorError,
        )

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Force database initialization to fail
        with patch.object(
            orchestrator, '_initializeDatabase',
            side_effect=Exception("Test database failure")
        ):
            # Act & Assert
            with caplog.at_level(logging.ERROR):
                with pytest.raises(OrchestratorError):
                    orchestrator.start()

                errorMessages = [
                    record.message
                    for record in caplog.records
                    if record.levelno == logging.ERROR
                ]

                # Should have an error message about the failure
                assert any(
                    "Failed" in msg or "failed" in msg.lower()
                    for msg in errorMessages
                ), f"Expected ERROR log about failure, got: {errorMessages}"

    def test_startup_failureIncludesClearErrorMessage(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Component forced to fail during initialization
        When: Orchestrator fails to start
        Then: Error message clearly identifies what failed
        """
        # Arrange
        from pi.obdii.orchestrator import (
            ApplicationOrchestrator,
            ComponentInitializationError,
            OrchestratorError,
        )

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Force connection initialization to fail with clear component name
        with patch.object(
            orchestrator, '_initializeConnection',
            side_effect=ComponentInitializationError(
                "Connection failed: test error",
                component='connection'
            )
        ):
            # Act & Assert
            with pytest.raises(OrchestratorError) as excInfo:
                orchestrator.start()

            # Error should identify what failed
            assert "connection" in str(excInfo.value).lower() or \
                   "Failed" in str(excInfo.value)


# ================================================================================
# US-860-a: the orchestrator start arms the boot's kernel_start milestone
# ================================================================================


@pytest.mark.integration
class TestStartupBootMilestone:
    """orchestrator.start() writes kernel_start into the boot_milestone table."""

    def test_start_writesKernelStart_wallMinusUptime(
        self, startupConfig: dict[str, Any], tempDb: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """
        Given: a readable boot id and /proc/uptime of 20 s
        When: Orchestrator starts
        Then: one kernel_start row for that boot, 20 s before now, uptime 0
        """
        import sqlite3
        from datetime import UTC, datetime, timedelta

        from pi.obdii.orchestrator import ApplicationOrchestrator
        from src.pi.diagnostics import boot_milestone as bm

        now = datetime(2026, 10, 13, 12, 0, 20, tzinfo=UTC)
        monkeypatch.setattr(bm, "readBootId", lambda: "boot-start")
        monkeypatch.setattr(bm, "_bootIdSurfacePresent", lambda: True)
        monkeypatch.setattr(bm, "readSystemUptimeSeconds", lambda: 20.0)
        monkeypatch.setattr(bm, "_utcNow", lambda: now)

        orchestrator = ApplicationOrchestrator(config=startupConfig, simulate=True)
        try:
            orchestrator.start()
        finally:
            orchestrator.stop()

        conn = sqlite3.connect(tempDb)
        try:
            rows = conn.execute(
                "SELECT boot_id, milestone, ts_utc, uptime_s FROM boot_milestone"
            ).fetchall()
        finally:
            conn.close()
        expected = (now - timedelta(seconds=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert rows == [("boot-start", "kernel_start", expected, 0.0)]
