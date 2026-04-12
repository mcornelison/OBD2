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
        'aiAnalysis': {
            'enabled': False
        },
        'profiles': {
            'activeProfile': 'test',
            'availableProfiles': [
                {
                    'id': 'test',
                    'name': 'Test Profile',
                    'description': 'Profile for startup tests',
                    'alertThresholds': {
                        'rpmRedline': 6000,
                        'coolantTempCritical': 105
                    },
                    'pollingIntervalMs': 100
                }
            ]
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
        'logging': {
            'level': 'DEBUG',
            'maskPII': False
        }
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
# AC1: Startup sequence follows correct dependency order
# ================================================================================


@pytest.mark.integration
class TestStartupSequenceOrder:
    """Tests that startup initializes components in dependency order."""

    def test_startup_initializesComponentsInDependencyOrder(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration with simulator enabled
        When: Orchestrator starts
        Then: Components are initialized in correct dependency order
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Act
        with caplog.at_level(logging.INFO):
            try:
                orchestrator.start()

                # Assert - extract component 'Starting X...' messages
                # from orchestrator logger only (exclude top-level
                # 'Starting ApplicationOrchestrator...')
                startMessages = [
                    record.message
                    for record in caplog.records
                    if record.name == 'obd.orchestrator'
                    and record.message.startswith("Starting ")
                    and record.message.endswith("...")
                    and "ApplicationOrchestrator" not in record.message
                ]

                # Database must be first (everything depends on it)
                assert startMessages[0] == "Starting database..."

                # ProfileManager must come before connection
                dbIdx = startMessages.index("Starting database...")
                pmIdx = startMessages.index("Starting profileManager...")
                connIdx = startMessages.index("Starting connection...")
                assert dbIdx < pmIdx < connIdx

                # DataLogger must be last among core components
                # (depends on connection and database)
                dlIdx = startMessages.index("Starting dataLogger...")
                assert dlIdx > connIdx

            finally:
                orchestrator.stop()

    def test_startup_initializesDatabaseBeforeAllOtherComponents(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts
        Then: Database is initialized before all other components
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Act
        with caplog.at_level(logging.INFO):
            try:
                orchestrator.start()

                # Filter to orchestrator component-level messages only
                startMessages = [
                    record.message
                    for record in caplog.records
                    if record.name == 'obd.orchestrator'
                    and record.message.startswith("Starting ")
                    and record.message.endswith("...")
                    and "ApplicationOrchestrator" not in record.message
                ]

                # Assert - database is first
                assert startMessages[0] == "Starting database..."

                # All other components come after database
                for msg in startMessages[1:]:
                    assert msg != "Starting database..."

            finally:
                orchestrator.stop()

    def test_startup_statisticsBeforeDriveDetector(
        self, startupConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts
        Then: StatisticsEngine is initialized before DriveDetector
              (DriveDetector depends on StatisticsEngine for post-drive analysis)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=startupConfig,
            simulate=True
        )

        # Act
        with caplog.at_level(logging.INFO):
            try:
                orchestrator.start()

                startMessages = [
                    record.message
                    for record in caplog.records
                    if record.message.startswith("Starting ")
                    and record.message.endswith("...")
                ]

                # Assert - stats before drive detector
                statsIdx = startMessages.index("Starting statisticsEngine...")
                driveIdx = startMessages.index("Starting driveDetector...")
                assert statsIdx < driveIdx

            finally:
                orchestrator.stop()


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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
                    if record.name != 'obd.orchestrator':
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
        from obd.orchestrator import (
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
        from obd.orchestrator import (
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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import (
            DEFAULT_RECONNECT_DELAYS,
            ApplicationOrchestrator,
        )

        config = getStartupTestConfig(tempDb)
        del config['bluetooth']['retryDelays']

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import (
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
        from obd.orchestrator import (
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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
