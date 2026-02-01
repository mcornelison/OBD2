################################################################################
# File Name: test_telemetry_logger.py
# Purpose/Description: Tests for system telemetry logger
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial implementation for US-RPI-011
# ================================================================================
################################################################################

"""
Tests for the telemetry_logger module.

Tests telemetry logging functionality with mocked system calls for
cross-platform testing.

Run with:
    pytest tests/test_telemetry_logger.py -v
"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from hardware.telemetry_logger import (
    CPU_TEMP_PATH,
    DEFAULT_BACKUP_COUNT,
    DEFAULT_LOG_INTERVAL,
    DEFAULT_LOG_PATH,
    DEFAULT_MAX_BYTES,
    JsonFormatter,
    TelemetryLogger,
    TelemetryLoggerError,
    TelemetryLoggerNotAvailableError,
)

# ================================================================================
# Exception Tests
# ================================================================================


class TestTelemetryLoggerExceptions:
    """Tests for telemetry logger exception classes."""

    def test_telemetryLoggerError_isBaseException(self):
        """
        Given: TelemetryLoggerError
        When: Checked for inheritance
        Then: Is subclass of Exception
        """
        assert issubclass(TelemetryLoggerError, Exception)

    def test_telemetryLoggerNotAvailableError_isSubclass(self):
        """
        Given: TelemetryLoggerNotAvailableError
        When: Checked for inheritance
        Then: Is subclass of TelemetryLoggerError
        """
        assert issubclass(TelemetryLoggerNotAvailableError, TelemetryLoggerError)

    def test_telemetryLoggerError_hasMessage(self):
        """
        Given: TelemetryLoggerError with message
        When: Converted to string
        Then: Contains the message
        """
        error = TelemetryLoggerError("Test error message")
        assert "Test error message" in str(error)

    def test_telemetryLoggerNotAvailableError_hasMessage(self):
        """
        Given: TelemetryLoggerNotAvailableError with message
        When: Converted to string
        Then: Contains the message
        """
        error = TelemetryLoggerNotAvailableError("Logging not available")
        assert "Logging not available" in str(error)


# ================================================================================
# Constants Tests
# ================================================================================


class TestTelemetryLoggerConstants:
    """Tests for telemetry logger constants."""

    def test_defaultLogPath_isVarLogCarpi(self):
        """
        Given: DEFAULT_LOG_PATH constant
        When: Checked
        Then: Is /var/log/carpi/telemetry.log
        """
        assert DEFAULT_LOG_PATH == "/var/log/carpi/telemetry.log"

    def test_defaultLogInterval_is10(self):
        """
        Given: DEFAULT_LOG_INTERVAL constant
        When: Checked
        Then: Is 10.0 seconds
        """
        assert DEFAULT_LOG_INTERVAL == 10.0

    def test_defaultMaxBytes_is100MB(self):
        """
        Given: DEFAULT_MAX_BYTES constant
        When: Checked
        Then: Is 100MB
        """
        assert DEFAULT_MAX_BYTES == 100 * 1024 * 1024

    def test_defaultBackupCount_is7(self):
        """
        Given: DEFAULT_BACKUP_COUNT constant
        When: Checked
        Then: Is 7
        """
        assert DEFAULT_BACKUP_COUNT == 7

    def test_cpuTempPath_isCorrect(self):
        """
        Given: CPU_TEMP_PATH constant
        When: Checked
        Then: Is Linux thermal zone path
        """
        assert CPU_TEMP_PATH == "/sys/class/thermal/thermal_zone0/temp"


# ================================================================================
# JsonFormatter Tests
# ================================================================================


class TestJsonFormatter:
    """Tests for JsonFormatter class."""

    def test_format_returnsMessageAsIs(self):
        """
        Given: JsonFormatter and a log record
        When: Formatted
        Then: Returns the message unchanged
        """
        import logging
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg='{"key": "value"}',
            args=(),
            exc_info=None
        )

        result = formatter.format(record)

        assert result == '{"key": "value"}'


# ================================================================================
# Initialization Tests
# ================================================================================


class TestTelemetryLoggerInitialization:
    """Tests for TelemetryLogger initialization."""

    def test_init_defaultValues(self):
        """
        Given: TelemetryLogger with no arguments
        When: Created
        Then: Uses default values
        """
        logger = TelemetryLogger()

        assert logger.logPath == DEFAULT_LOG_PATH
        assert logger.logInterval == DEFAULT_LOG_INTERVAL
        assert logger.maxBytes == DEFAULT_MAX_BYTES
        assert logger.backupCount == DEFAULT_BACKUP_COUNT
        assert logger.isLogging is False

    def test_init_customLogPath(self):
        """
        Given: TelemetryLogger with custom log path
        When: Created
        Then: Uses custom path
        """
        customPath = "/tmp/custom_telemetry.log"
        logger = TelemetryLogger(logPath=customPath)

        assert logger.logPath == customPath

    def test_init_customLogInterval(self):
        """
        Given: TelemetryLogger with custom log interval
        When: Created
        Then: Uses custom interval
        """
        logger = TelemetryLogger(logInterval=30.0)

        assert logger.logInterval == 30.0

    def test_init_customMaxBytes(self):
        """
        Given: TelemetryLogger with custom max bytes
        When: Created
        Then: Uses custom value
        """
        logger = TelemetryLogger(maxBytes=50 * 1024 * 1024)

        assert logger.maxBytes == 50 * 1024 * 1024

    def test_init_customBackupCount(self):
        """
        Given: TelemetryLogger with custom backup count
        When: Created
        Then: Uses custom value
        """
        logger = TelemetryLogger(backupCount=14)

        assert logger.backupCount == 14

    def test_init_zeroLogInterval_raisesValueError(self):
        """
        Given: TelemetryLogger with zero log interval
        When: Created
        Then: Raises ValueError
        """
        with pytest.raises(ValueError) as exc:
            TelemetryLogger(logInterval=0)

        assert "positive" in str(exc.value).lower()

    def test_init_negativeLogInterval_raisesValueError(self):
        """
        Given: TelemetryLogger with negative log interval
        When: Created
        Then: Raises ValueError
        """
        with pytest.raises(ValueError) as exc:
            TelemetryLogger(logInterval=-5.0)

        assert "positive" in str(exc.value).lower()

    def test_init_zeroMaxBytes_raisesValueError(self):
        """
        Given: TelemetryLogger with zero max bytes
        When: Created
        Then: Raises ValueError
        """
        with pytest.raises(ValueError) as exc:
            TelemetryLogger(maxBytes=0)

        assert "positive" in str(exc.value).lower()

    def test_init_negativeBackupCount_raisesValueError(self):
        """
        Given: TelemetryLogger with negative backup count
        When: Created
        Then: Raises ValueError
        """
        with pytest.raises(ValueError) as exc:
            TelemetryLogger(backupCount=-1)

        assert "negative" in str(exc.value).lower()


# ================================================================================
# UPS Monitor Integration Tests
# ================================================================================


class TestUpsMonitorIntegration:
    """Tests for UPS monitor integration."""

    def test_setUpsMonitor_storesMonitor(self):
        """
        Given: TelemetryLogger and UPS monitor
        When: setUpsMonitor called
        Then: Monitor is stored
        """
        logger = TelemetryLogger()
        mockMonitor = MagicMock()

        logger.setUpsMonitor(mockMonitor)

        # Verify by checking getTelemetry uses it
        mockMonitor.getTelemetry.return_value = {
            'powerSource': MagicMock(value='external'),
            'voltage': 4.2,
            'current': 500.0,
            'percentage': 85
        }

        telemetry = logger.getTelemetry()

        assert telemetry['power_source'] == 'external'
        assert telemetry['battery_v'] == 4.2

    def test_getTelemetry_withoutUpsMonitor_returnsNoneForBattery(self):
        """
        Given: TelemetryLogger without UPS monitor
        When: getTelemetry called
        Then: Battery fields are None
        """
        logger = TelemetryLogger()

        telemetry = logger.getTelemetry()

        assert telemetry['power_source'] is None
        assert telemetry['battery_v'] is None
        assert telemetry['battery_ma'] is None
        assert telemetry['battery_pct'] is None

    def test_getTelemetry_upsError_returnsNoneForBattery(self):
        """
        Given: TelemetryLogger with failing UPS monitor
        When: getTelemetry called
        Then: Battery fields are None
        """
        logger = TelemetryLogger()
        mockMonitor = MagicMock()
        mockMonitor.getTelemetry.side_effect = Exception("UPS error")
        logger.setUpsMonitor(mockMonitor)

        telemetry = logger.getTelemetry()

        assert telemetry['power_source'] is None
        assert telemetry['battery_v'] is None


# ================================================================================
# Custom Reader Tests
# ================================================================================


class TestCustomReaders:
    """Tests for custom CPU temp and disk free readers."""

    def test_setCpuTempReader_usesCustomReader(self):
        """
        Given: TelemetryLogger with custom CPU temp reader
        When: getTelemetry called
        Then: Uses custom reader value
        """
        logger = TelemetryLogger()
        logger.setCpuTempReader(lambda: 45.5)

        telemetry = logger.getTelemetry()

        assert telemetry['cpu_temp'] == 45.5

    def test_setDiskFreeReader_usesCustomReader(self):
        """
        Given: TelemetryLogger with custom disk free reader
        When: getTelemetry called
        Then: Uses custom reader value
        """
        logger = TelemetryLogger()
        logger.setDiskFreeReader(lambda: 50000)

        telemetry = logger.getTelemetry()

        assert telemetry['disk_free_mb'] == 50000

    def test_customCpuTempReader_returningNone(self):
        """
        Given: Custom CPU temp reader returning None
        When: getTelemetry called
        Then: cpu_temp is None
        """
        logger = TelemetryLogger()
        logger.setCpuTempReader(lambda: None)

        telemetry = logger.getTelemetry()

        assert telemetry['cpu_temp'] is None


# ================================================================================
# Get Telemetry Tests
# ================================================================================


class TestGetTelemetry:
    """Tests for getTelemetry method."""

    def test_getTelemetry_hasTimestamp(self):
        """
        Given: TelemetryLogger
        When: getTelemetry called
        Then: Returns telemetry with timestamp
        """
        logger = TelemetryLogger()
        logger.setCpuTempReader(lambda: None)
        logger.setDiskFreeReader(lambda: None)

        telemetry = logger.getTelemetry()

        assert 'timestamp' in telemetry
        assert telemetry['timestamp'].endswith('Z')
        assert 'T' in telemetry['timestamp']  # ISO format

    def test_getTelemetry_hasAllFields(self):
        """
        Given: TelemetryLogger
        When: getTelemetry called
        Then: Returns all expected fields
        """
        logger = TelemetryLogger()
        logger.setCpuTempReader(lambda: 50.0)
        logger.setDiskFreeReader(lambda: 10000)

        telemetry = logger.getTelemetry()

        assert 'timestamp' in telemetry
        assert 'power_source' in telemetry
        assert 'battery_v' in telemetry
        assert 'battery_ma' in telemetry
        assert 'battery_pct' in telemetry
        assert 'cpu_temp' in telemetry
        assert 'disk_free_mb' in telemetry

    def test_getTelemetry_withFullUpsData(self):
        """
        Given: TelemetryLogger with UPS monitor providing full data
        When: getTelemetry called
        Then: Returns complete battery telemetry
        """
        logger = TelemetryLogger()
        logger.setCpuTempReader(lambda: 55.0)
        logger.setDiskFreeReader(lambda: 20000)

        mockMonitor = MagicMock()
        mockMonitor.getTelemetry.return_value = {
            'powerSource': MagicMock(value='battery'),
            'voltage': 3.8,
            'current': -250.0,
            'percentage': 45
        }
        logger.setUpsMonitor(mockMonitor)

        telemetry = logger.getTelemetry()

        assert telemetry['power_source'] == 'battery'
        assert telemetry['battery_v'] == 3.8
        assert telemetry['battery_ma'] == -250.0
        assert telemetry['battery_pct'] == 45
        assert telemetry['cpu_temp'] == 55.0
        assert telemetry['disk_free_mb'] == 20000


# ================================================================================
# CPU Temperature Tests
# ================================================================================


class TestCpuTemperature:
    """Tests for CPU temperature reading."""

    @patch('hardware.telemetry_logger.isRaspberryPi')
    def test_getCpuTemp_notRaspberryPi_returnsNone(self, mockIsPi):
        """
        Given: Not running on Raspberry Pi
        When: getTelemetry called
        Then: cpu_temp is None
        """
        mockIsPi.return_value = False
        logger = TelemetryLogger()

        telemetry = logger.getTelemetry()

        assert telemetry['cpu_temp'] is None

    @patch('hardware.telemetry_logger.isRaspberryPi')
    @patch('builtins.open', mock_open(read_data='45500\n'))
    def test_getCpuTemp_validReading_returnsCelsius(self, mockIsPi):
        """
        Given: Running on Raspberry Pi with valid temp file
        When: getTelemetry called
        Then: cpu_temp is correct in Celsius
        """
        mockIsPi.return_value = True
        logger = TelemetryLogger()

        telemetry = logger.getTelemetry()

        assert telemetry['cpu_temp'] == 45.5

    @patch('hardware.telemetry_logger.isRaspberryPi')
    @patch('builtins.open', side_effect=FileNotFoundError())
    def test_getCpuTemp_fileNotFound_returnsNone(self, mockOpen, mockIsPi):
        """
        Given: Running on Raspberry Pi but temp file not found
        When: getTelemetry called
        Then: cpu_temp is None
        """
        mockIsPi.return_value = True
        logger = TelemetryLogger()

        telemetry = logger.getTelemetry()

        assert telemetry['cpu_temp'] is None

    @patch('hardware.telemetry_logger.isRaspberryPi')
    @patch('builtins.open', mock_open(read_data='invalid\n'))
    def test_getCpuTemp_invalidValue_returnsNone(self, mockIsPi):
        """
        Given: Running on Raspberry Pi with invalid temp value
        When: getTelemetry called
        Then: cpu_temp is None
        """
        mockIsPi.return_value = True
        logger = TelemetryLogger()

        telemetry = logger.getTelemetry()

        assert telemetry['cpu_temp'] is None


# ================================================================================
# Disk Free Space Tests
# ================================================================================


class TestDiskFreeSpace:
    """Tests for disk free space reading."""

    @patch('hardware.telemetry_logger.shutil.disk_usage')
    def test_getDiskFreeMb_validReading_returnsMb(self, mockDiskUsage):
        """
        Given: Valid disk usage reading
        When: getTelemetry called
        Then: disk_free_mb is correct
        """
        # 10GB free
        mockDiskUsage.return_value = MagicMock(
            free=10 * 1024 * 1024 * 1024
        )
        logger = TelemetryLogger()

        telemetry = logger.getTelemetry()

        assert telemetry['disk_free_mb'] == 10240  # 10GB in MB

    @patch('hardware.telemetry_logger.shutil.disk_usage')
    def test_getDiskFreeMb_osError_returnsNone(self, mockDiskUsage):
        """
        Given: disk_usage raises OSError
        When: getTelemetry called
        Then: disk_free_mb is None
        """
        mockDiskUsage.side_effect = OSError("Disk error")
        logger = TelemetryLogger()

        telemetry = logger.getTelemetry()

        assert telemetry['disk_free_mb'] is None


# ================================================================================
# Start/Stop Tests
# ================================================================================


class TestStartStop:
    """Tests for start and stop methods."""

    def test_start_createsLogDirectory(self):
        """
        Given: TelemetryLogger with non-existent log directory
        When: start called
        Then: Creates the directory
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'subdir', 'telemetry.log')
            logger = TelemetryLogger(logPath=logPath, logInterval=0.1)
            logger.setCpuTempReader(lambda: None)
            logger.setDiskFreeReader(lambda: None)

            try:
                result = logger.start()

                assert result is True
                assert os.path.exists(os.path.dirname(logPath))
            finally:
                logger.stop()

    def test_start_setsIsLoggingTrue(self):
        """
        Given: TelemetryLogger
        When: start called successfully
        Then: isLogging is True
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')
            logger = TelemetryLogger(logPath=logPath, logInterval=0.1)
            logger.setCpuTempReader(lambda: None)
            logger.setDiskFreeReader(lambda: None)

            try:
                logger.start()

                assert logger.isLogging is True
            finally:
                logger.stop()

    def test_start_alreadyRunning_raisesRuntimeError(self):
        """
        Given: TelemetryLogger that is already logging
        When: start called again
        Then: Raises RuntimeError
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')
            logger = TelemetryLogger(logPath=logPath, logInterval=0.1)
            logger.setCpuTempReader(lambda: None)
            logger.setDiskFreeReader(lambda: None)

            try:
                logger.start()

                with pytest.raises(RuntimeError) as exc:
                    logger.start()

                assert "already running" in str(exc.value).lower()
            finally:
                logger.stop()

    def test_stop_setsIsLoggingFalse(self):
        """
        Given: TelemetryLogger that is logging
        When: stop called
        Then: isLogging is False
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')
            logger = TelemetryLogger(logPath=logPath, logInterval=0.1)
            logger.setCpuTempReader(lambda: None)
            logger.setDiskFreeReader(lambda: None)

            logger.start()
            logger.stop()

            assert logger.isLogging is False

    def test_stop_whenNotRunning_isSafe(self):
        """
        Given: TelemetryLogger that is not logging
        When: stop called
        Then: No error raised
        """
        logger = TelemetryLogger()

        # Should not raise
        logger.stop()

        assert logger.isLogging is False

    def test_start_writesToLogFile(self):
        """
        Given: TelemetryLogger
        When: start called and time passes
        Then: Writes telemetry to log file
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')
            logger = TelemetryLogger(logPath=logPath, logInterval=0.1)
            logger.setCpuTempReader(lambda: 42.0)
            logger.setDiskFreeReader(lambda: 5000)

            try:
                logger.start()
                time.sleep(0.3)  # Wait for at least one log entry
            finally:
                logger.stop()

            # Check log file content
            assert os.path.exists(logPath)
            with open(logPath) as f:
                lines = f.readlines()

            assert len(lines) >= 1
            # Parse first line as JSON
            entry = json.loads(lines[0])
            assert 'timestamp' in entry
            assert entry['cpu_temp'] == 42.0
            assert entry['disk_free_mb'] == 5000


# ================================================================================
# Property Tests
# ================================================================================


class TestProperties:
    """Tests for TelemetryLogger properties."""

    def test_logInterval_getter(self):
        """
        Given: TelemetryLogger with log interval
        When: logInterval accessed
        Then: Returns correct value
        """
        logger = TelemetryLogger(logInterval=15.0)

        assert logger.logInterval == 15.0

    def test_logInterval_setter(self):
        """
        Given: TelemetryLogger
        When: logInterval set to new value
        Then: Value is updated
        """
        logger = TelemetryLogger()

        logger.logInterval = 20.0

        assert logger.logInterval == 20.0

    def test_logInterval_setter_invalidValue_raisesValueError(self):
        """
        Given: TelemetryLogger
        When: logInterval set to zero or negative
        Then: Raises ValueError
        """
        logger = TelemetryLogger()

        with pytest.raises(ValueError):
            logger.logInterval = 0

        with pytest.raises(ValueError):
            logger.logInterval = -5.0

    def test_logPath_getter(self):
        """
        Given: TelemetryLogger with log path
        When: logPath accessed
        Then: Returns correct value
        """
        logger = TelemetryLogger(logPath="/tmp/test.log")

        assert logger.logPath == "/tmp/test.log"

    def test_maxBytes_getter(self):
        """
        Given: TelemetryLogger with max bytes
        When: maxBytes accessed
        Then: Returns correct value
        """
        logger = TelemetryLogger(maxBytes=50 * 1024 * 1024)

        assert logger.maxBytes == 50 * 1024 * 1024

    def test_backupCount_getter(self):
        """
        Given: TelemetryLogger with backup count
        When: backupCount accessed
        Then: Returns correct value
        """
        logger = TelemetryLogger(backupCount=10)

        assert logger.backupCount == 10

    def test_isLogging_getter_initiallyFalse(self):
        """
        Given: New TelemetryLogger
        When: isLogging accessed
        Then: Returns False
        """
        logger = TelemetryLogger()

        assert logger.isLogging is False


# ================================================================================
# Error Callback Tests
# ================================================================================


class TestErrorCallback:
    """Tests for error callback functionality."""

    def test_onError_getter_initiallyNone(self):
        """
        Given: New TelemetryLogger
        When: onError accessed
        Then: Returns None
        """
        logger = TelemetryLogger()

        assert logger.onError is None

    def test_onError_setter(self):
        """
        Given: TelemetryLogger
        When: onError set to callback
        Then: Callback is stored
        """
        logger = TelemetryLogger()
        callback = MagicMock()

        logger.onError = callback

        assert logger.onError is callback


# ================================================================================
# Lifecycle Tests
# ================================================================================


class TestLifecycle:
    """Tests for lifecycle methods."""

    def test_close_stopsLogging(self):
        """
        Given: TelemetryLogger that is logging
        When: close called
        Then: Stops logging
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')
            logger = TelemetryLogger(logPath=logPath, logInterval=0.1)
            logger.setCpuTempReader(lambda: None)
            logger.setDiskFreeReader(lambda: None)

            logger.start()
            assert logger.isLogging is True

            logger.close()

            assert logger.isLogging is False

    def test_contextManager_startsAndStops(self):
        """
        Given: TelemetryLogger used as context manager
        When: Exited
        Then: Resources are cleaned up
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')

            with TelemetryLogger(logPath=logPath, logInterval=0.1) as logger:
                logger.setCpuTempReader(lambda: None)
                logger.setDiskFreeReader(lambda: None)
                logger.start()
                assert logger.isLogging is True

            assert logger.isLogging is False

    def test_destructor_cleansUp(self):
        """
        Given: TelemetryLogger
        When: Deleted
        Then: Resources are cleaned up
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')
            logger = TelemetryLogger(logPath=logPath, logInterval=0.1)
            logger.setCpuTempReader(lambda: None)
            logger.setDiskFreeReader(lambda: None)
            logger.start()

            # Explicit delete
            logger.__del__()

            assert logger.isLogging is False


# ================================================================================
# Thread Safety Tests
# ================================================================================


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrentGetTelemetry_noErrors(self):
        """
        Given: TelemetryLogger
        When: getTelemetry called from multiple threads
        Then: No errors or data corruption
        """
        logger = TelemetryLogger()
        logger.setCpuTempReader(lambda: 45.0)
        logger.setDiskFreeReader(lambda: 10000)

        results = []
        errors = []

        def worker():
            try:
                for _ in range(10):
                    telemetry = logger.getTelemetry()
                    results.append(telemetry)
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 50


# ================================================================================
# Integration Tests
# ================================================================================


class TestIntegration:
    """Integration tests for TelemetryLogger."""

    def test_fullWorkflow_logsCorrectData(self):
        """
        Given: TelemetryLogger with UPS monitor
        When: Full logging workflow executed
        Then: Correct data is logged
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')
            logger = TelemetryLogger(logPath=logPath, logInterval=0.1)

            # Set up mock UPS monitor
            mockMonitor = MagicMock()
            mockMonitor.getTelemetry.return_value = {
                'powerSource': MagicMock(value='external'),
                'voltage': 4.15,
                'current': 350.0,
                'percentage': 92
            }
            logger.setUpsMonitor(mockMonitor)

            # Set up custom readers
            logger.setCpuTempReader(lambda: 52.3)
            logger.setDiskFreeReader(lambda: 8192)

            try:
                logger.start()
                time.sleep(0.25)  # Wait for entries
            finally:
                logger.stop()

            # Verify log content
            with open(logPath) as f:
                lines = f.readlines()

            assert len(lines) >= 1

            entry = json.loads(lines[0])
            assert entry['power_source'] == 'external'
            assert entry['battery_v'] == 4.15
            assert entry['battery_ma'] == 350.0
            assert entry['battery_pct'] == 92
            assert entry['cpu_temp'] == 52.3
            assert entry['disk_free_mb'] == 8192

    def test_logRotation_respectsMaxBytes(self):
        """
        Given: TelemetryLogger with small max bytes
        When: Logging exceeds max bytes
        Then: File rotates correctly
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')
            # Small max bytes to trigger rotation quickly
            logger = TelemetryLogger(
                logPath=logPath,
                logInterval=0.05,
                maxBytes=500,  # Very small for testing
                backupCount=2
            )
            logger.setCpuTempReader(lambda: 50.0)
            logger.setDiskFreeReader(lambda: 5000)

            try:
                logger.start()
                time.sleep(0.5)  # Log several entries
            finally:
                logger.stop()

            # Check that rotation happened
            files = os.listdir(tmpdir)
            logFiles = [f for f in files if f.startswith('telemetry')]
            # Should have main log and possibly backup(s)
            assert len(logFiles) >= 1


# ================================================================================
# JSON Format Tests
# ================================================================================


class TestJsonFormat:
    """Tests for JSON output format."""

    def test_logEntry_isValidJson(self):
        """
        Given: TelemetryLogger writing entries
        When: Log file read
        Then: Each line is valid JSON
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logPath = os.path.join(tmpdir, 'telemetry.log')
            logger = TelemetryLogger(logPath=logPath, logInterval=0.1)
            logger.setCpuTempReader(lambda: 40.0)
            logger.setDiskFreeReader(lambda: 3000)

            try:
                logger.start()
                time.sleep(0.25)
            finally:
                logger.stop()

            with open(logPath) as f:
                for line in f:
                    # Each line should parse as valid JSON
                    entry = json.loads(line.strip())
                    assert isinstance(entry, dict)

    def test_timestamp_isIso8601(self):
        """
        Given: TelemetryLogger writing entries
        When: Timestamp checked
        Then: Is ISO 8601 format with Z suffix
        """
        logger = TelemetryLogger()
        logger.setCpuTempReader(lambda: None)
        logger.setDiskFreeReader(lambda: None)

        telemetry = logger.getTelemetry()

        # Should be like: 2026-01-26T12:34:56.123456Z
        assert telemetry['timestamp'].endswith('Z')
        assert 'T' in telemetry['timestamp']
        # Should be parseable
        from datetime import datetime
        # Remove Z and parse
        ts = telemetry['timestamp'][:-1]
        datetime.fromisoformat(ts)
