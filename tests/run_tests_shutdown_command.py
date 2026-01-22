#!/usr/bin/env python3
################################################################################
# File Name: run_tests_shutdown_command.py
# Purpose/Description: Test runner for shutdown_command module
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-009
# ================================================================================
################################################################################

"""
Tests for the shutdown_command module.

Tests cover:
- ShutdownConfig dataclass
- ShutdownResult dataclass
- ShutdownCommand class
- Script generation (shutdown.sh)
- GPIO button trigger (mocked)
- Helper functions
- Error handling
"""

import os
import stat
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.shutdown_command import (
    ShutdownCommand,
    ShutdownConfig,
    ShutdownResult,
    ShutdownState,
    ShutdownCommandError,
    ProcessNotFoundError,
    ShutdownTimeoutError,
    GpioNotAvailableError,
    generateShutdownScript,
    generateGpioTriggerScript,
    createShutdownCommandFromConfig,
    isGpioAvailable,
    sendShutdownSignal,
    SHUTDOWN_REASON_USER_REQUEST,
    SHUTDOWN_REASON_GPIO_BUTTON,
    SHUTDOWN_REASON_LOW_BATTERY,
    SHUTDOWN_REASON_MAINTENANCE,
    SHUTDOWN_REASON_SYSTEM,
    DEFAULT_SHUTDOWN_TIMEOUT,
    DEFAULT_GPIO_PIN,
    DEFAULT_PID_FILE,
    DEFAULT_SERVICE_NAME,
)


class TestShutdownConfig(unittest.TestCase):
    """Tests for ShutdownConfig dataclass."""

    def test_defaultValues(self):
        """ShutdownConfig has correct default values."""
        config = ShutdownConfig()

        self.assertEqual(config.timeoutSeconds, DEFAULT_SHUTDOWN_TIMEOUT)
        self.assertEqual(config.pidFile, DEFAULT_PID_FILE)
        self.assertEqual(config.serviceName, DEFAULT_SERVICE_NAME)
        self.assertEqual(config.gpioPin, DEFAULT_GPIO_PIN)
        self.assertTrue(config.gpioPullUp)
        self.assertEqual(config.gpioDebounceMs, 200)
        self.assertFalse(config.powerOffEnabled)
        self.assertEqual(config.powerOffDelaySeconds, 5)
        self.assertIsNone(config.logFile)

    def test_customValues(self):
        """ShutdownConfig accepts custom values."""
        config = ShutdownConfig(
            timeoutSeconds=60,
            pidFile='/tmp/test.pid',
            serviceName='test-service',
            gpioPin=27,
            gpioPullUp=False,
            gpioDebounceMs=500,
            powerOffEnabled=True,
            powerOffDelaySeconds=10,
            logFile='/var/log/shutdown.log'
        )

        self.assertEqual(config.timeoutSeconds, 60)
        self.assertEqual(config.pidFile, '/tmp/test.pid')
        self.assertEqual(config.serviceName, 'test-service')
        self.assertEqual(config.gpioPin, 27)
        self.assertFalse(config.gpioPullUp)
        self.assertEqual(config.gpioDebounceMs, 500)
        self.assertTrue(config.powerOffEnabled)
        self.assertEqual(config.powerOffDelaySeconds, 10)
        self.assertEqual(config.logFile, '/var/log/shutdown.log')

    def test_toDict(self):
        """ShutdownConfig.toDict returns correct dictionary."""
        config = ShutdownConfig(timeoutSeconds=45, gpioPin=22)
        result = config.toDict()

        self.assertIsInstance(result, dict)
        self.assertEqual(result['timeoutSeconds'], 45)
        self.assertEqual(result['gpioPin'], 22)
        self.assertEqual(result['serviceName'], DEFAULT_SERVICE_NAME)


class TestShutdownResult(unittest.TestCase):
    """Tests for ShutdownResult dataclass."""

    def test_defaultValues(self):
        """ShutdownResult has correct default values."""
        result = ShutdownResult(
            success=True,
            state=ShutdownState.COMPLETED,
            reason='test',
            startTime=datetime.now()
        )

        self.assertTrue(result.success)
        self.assertEqual(result.state, ShutdownState.COMPLETED)
        self.assertEqual(result.reason, 'test')
        self.assertIsNone(result.endTime)
        self.assertEqual(result.durationSeconds, 0.0)
        self.assertIsNone(result.processId)
        self.assertFalse(result.powerOffRequested)
        self.assertFalse(result.powerOffExecuted)
        self.assertIsNone(result.errorMessage)

    def test_toDict(self):
        """ShutdownResult.toDict returns correct dictionary."""
        startTime = datetime.now()
        endTime = datetime.now()

        result = ShutdownResult(
            success=True,
            state=ShutdownState.COMPLETED,
            reason='user_request',
            startTime=startTime,
            endTime=endTime,
            durationSeconds=2.5,
            processId=12345,
            powerOffRequested=True,
            powerOffExecuted=True
        )

        d = result.toDict()

        self.assertIsInstance(d, dict)
        self.assertTrue(d['success'])
        self.assertEqual(d['state'], 'completed')
        self.assertEqual(d['reason'], 'user_request')
        self.assertEqual(d['processId'], 12345)
        self.assertTrue(d['powerOffRequested'])
        self.assertTrue(d['powerOffExecuted'])
        self.assertEqual(d['durationSeconds'], 2.5)


class TestShutdownState(unittest.TestCase):
    """Tests for ShutdownState enum."""

    def test_allStates(self):
        """ShutdownState has all expected states."""
        states = [s.value for s in ShutdownState]

        self.assertIn('idle', states)
        self.assertIn('initiating', states)
        self.assertIn('waiting', states)
        self.assertIn('completed', states)
        self.assertIn('timeout', states)
        self.assertIn('failed', states)


class TestShutdownConstants(unittest.TestCase):
    """Tests for shutdown constants."""

    def test_reasonConstants(self):
        """Shutdown reason constants are defined."""
        self.assertEqual(SHUTDOWN_REASON_USER_REQUEST, 'user_request')
        self.assertEqual(SHUTDOWN_REASON_GPIO_BUTTON, 'gpio_button')
        self.assertEqual(SHUTDOWN_REASON_LOW_BATTERY, 'low_battery')
        self.assertEqual(SHUTDOWN_REASON_MAINTENANCE, 'maintenance')
        self.assertEqual(SHUTDOWN_REASON_SYSTEM, 'system')

    def test_defaultConstants(self):
        """Default constants are defined."""
        self.assertEqual(DEFAULT_SHUTDOWN_TIMEOUT, 30)
        self.assertEqual(DEFAULT_GPIO_PIN, 17)
        self.assertIsInstance(DEFAULT_PID_FILE, str)
        self.assertIsInstance(DEFAULT_SERVICE_NAME, str)


class TestShutdownCommandInit(unittest.TestCase):
    """Tests for ShutdownCommand initialization."""

    def test_defaultInit(self):
        """ShutdownCommand initializes with defaults."""
        cmd = ShutdownCommand()

        self.assertIsNotNone(cmd._config)
        self.assertEqual(cmd._config.timeoutSeconds, DEFAULT_SHUTDOWN_TIMEOUT)
        self.assertEqual(cmd._state, ShutdownState.IDLE)
        self.assertIsNone(cmd._lastResult)

    def test_customConfig(self):
        """ShutdownCommand accepts custom config."""
        config = ShutdownConfig(timeoutSeconds=60, gpioPin=27)
        cmd = ShutdownCommand(config=config)

        self.assertEqual(cmd._config.timeoutSeconds, 60)
        self.assertEqual(cmd._config.gpioPin, 27)

    def test_pidFileOverride(self):
        """ShutdownCommand pidFile parameter overrides config."""
        config = ShutdownConfig(pidFile='/original.pid')
        cmd = ShutdownCommand(config=config, pidFile='/override.pid')

        self.assertEqual(cmd._config.pidFile, '/override.pid')

    def test_timeoutOverride(self):
        """ShutdownCommand timeoutSeconds parameter overrides config."""
        config = ShutdownConfig(timeoutSeconds=30)
        cmd = ShutdownCommand(config=config, timeoutSeconds=45)

        self.assertEqual(cmd._config.timeoutSeconds, 45)

    def test_databaseParameter(self):
        """ShutdownCommand accepts database parameter."""
        mockDb = MagicMock()
        cmd = ShutdownCommand(database=mockDb)

        self.assertEqual(cmd._database, mockDb)


class TestShutdownCommandState(unittest.TestCase):
    """Tests for ShutdownCommand state management."""

    def test_getState_initial(self):
        """getState returns IDLE initially."""
        cmd = ShutdownCommand()
        self.assertEqual(cmd.getState(), ShutdownState.IDLE)

    def test_getLastResult_initial(self):
        """getLastResult returns None initially."""
        cmd = ShutdownCommand()
        self.assertIsNone(cmd.getLastResult())


class TestShutdownCommandProcessId(unittest.TestCase):
    """Tests for ShutdownCommand process ID detection."""

    def test_getProcessId_noProcess(self):
        """getProcessId returns None when no process found."""
        cmd = ShutdownCommand(pidFile='/nonexistent/file.pid')

        with patch.object(cmd, '_getProcessIdFromSystemd', return_value=None):
            result = cmd.getProcessId()
            self.assertIsNone(result)

    def test_getProcessIdFromFile_validPid(self):
        """_getProcessIdFromFile returns PID from valid file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pid') as f:
            f.write('12345\n')
            pidFile = f.name

        try:
            cmd = ShutdownCommand(pidFile=pidFile)

            with patch.object(cmd, '_isProcessRunning', return_value=True):
                result = cmd._getProcessIdFromFile()
                self.assertEqual(result, 12345)
        finally:
            os.unlink(pidFile)

    def test_getProcessIdFromFile_invalidContent(self):
        """_getProcessIdFromFile returns None for invalid content."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pid') as f:
            f.write('not-a-number\n')
            pidFile = f.name

        try:
            cmd = ShutdownCommand(pidFile=pidFile)
            result = cmd._getProcessIdFromFile()
            self.assertIsNone(result)
        finally:
            os.unlink(pidFile)

    def test_getProcessIdFromFile_emptyFile(self):
        """_getProcessIdFromFile returns None for empty file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pid') as f:
            f.write('')
            pidFile = f.name

        try:
            cmd = ShutdownCommand(pidFile=pidFile)
            result = cmd._getProcessIdFromFile()
            self.assertIsNone(result)
        finally:
            os.unlink(pidFile)

    def test_getProcessIdFromFile_processNotRunning(self):
        """_getProcessIdFromFile returns None if process not running."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pid') as f:
            f.write('99999\n')
            pidFile = f.name

        try:
            cmd = ShutdownCommand(pidFile=pidFile)

            with patch.object(cmd, '_isProcessRunning', return_value=False):
                result = cmd._getProcessIdFromFile()
                self.assertIsNone(result)
        finally:
            os.unlink(pidFile)

    @patch('subprocess.run')
    def test_getProcessIdFromSystemd_validPid(self, mockRun):
        """_getProcessIdFromSystemd returns PID from systemctl."""
        mockRun.return_value = MagicMock(
            returncode=0,
            stdout='MainPID=54321\n'
        )

        cmd = ShutdownCommand()

        with patch.object(cmd, '_isProcessRunning', return_value=True):
            result = cmd._getProcessIdFromSystemd()
            self.assertEqual(result, 54321)

    @patch('subprocess.run')
    def test_getProcessIdFromSystemd_zeroPid(self, mockRun):
        """_getProcessIdFromSystemd returns None for PID=0."""
        mockRun.return_value = MagicMock(
            returncode=0,
            stdout='MainPID=0\n'
        )

        cmd = ShutdownCommand()
        result = cmd._getProcessIdFromSystemd()
        self.assertIsNone(result)

    @patch('subprocess.run', side_effect=FileNotFoundError)
    def test_getProcessIdFromSystemd_noSystemctl(self, mockRun):
        """_getProcessIdFromSystemd returns None when systemctl not found."""
        cmd = ShutdownCommand()
        result = cmd._getProcessIdFromSystemd()
        self.assertIsNone(result)


class TestShutdownCommandProcessRunning(unittest.TestCase):
    """Tests for process running detection."""

    @patch('os.kill')
    def test_isProcessRunning_true(self, mockKill):
        """_isProcessRunning returns True for running process."""
        mockKill.return_value = None  # No exception = process exists

        cmd = ShutdownCommand()
        result = cmd._isProcessRunning(12345)

        self.assertTrue(result)
        mockKill.assert_called_once_with(12345, 0)

    @patch('os.kill', side_effect=OSError)
    def test_isProcessRunning_false(self, mockKill):
        """_isProcessRunning returns False for non-existent process."""
        cmd = ShutdownCommand()
        result = cmd._isProcessRunning(99999)

        self.assertFalse(result)


class TestShutdownCommandInitiateShutdown(unittest.TestCase):
    """Tests for ShutdownCommand.initiateShutdown."""

    def test_initiateShutdown_processNotFound(self):
        """initiateShutdown raises ProcessNotFoundError when no process."""
        cmd = ShutdownCommand(pidFile='/nonexistent.pid')

        with patch.object(cmd, 'getProcessId', return_value=None):
            with self.assertRaises(ProcessNotFoundError):
                cmd.initiateShutdown()

    @patch('os.kill')
    def test_initiateShutdown_success(self, mockKill):
        """initiateShutdown succeeds when process exits gracefully."""
        cmd = ShutdownCommand()

        # Mock process detection
        with patch.object(cmd, 'getProcessId', return_value=12345):
            # Mock wait for exit
            with patch.object(cmd, '_waitForProcessExit', return_value=True):
                result = cmd.initiateShutdown(reason='test')

                self.assertTrue(result.success)
                self.assertEqual(result.state, ShutdownState.COMPLETED)
                self.assertEqual(result.reason, 'test')
                self.assertEqual(result.processId, 12345)
                mockKill.assert_called_once_with(12345, 15)  # SIGTERM

    @patch('os.kill')
    def test_initiateShutdown_timeout(self, mockKill):
        """initiateShutdown handles timeout gracefully."""
        cmd = ShutdownCommand(timeoutSeconds=1)

        with patch.object(cmd, 'getProcessId', return_value=12345):
            with patch.object(cmd, '_waitForProcessExit', return_value=False):
                with patch.object(cmd, '_isProcessRunning', return_value=False):
                    result = cmd.initiateShutdown(reason='test')

                    self.assertEqual(result.state, ShutdownState.TIMEOUT)
                    self.assertIn('Timeout', result.errorMessage)

    @patch('os.kill')
    def test_initiateShutdown_noWait(self, mockKill):
        """initiateShutdown returns immediately when wait=False."""
        cmd = ShutdownCommand()

        with patch.object(cmd, 'getProcessId', return_value=12345):
            result = cmd.initiateShutdown(reason='test', wait=False)

            self.assertTrue(result.success)
            self.assertEqual(result.state, ShutdownState.COMPLETED)

    @patch('os.kill')
    @patch('subprocess.run')
    def test_initiateShutdown_withPowerOff(self, mockRun, mockKill):
        """initiateShutdown executes power off when requested."""
        cmd = ShutdownCommand()
        cmd._config.powerOffDelaySeconds = 1

        with patch.object(cmd, 'getProcessId', return_value=12345):
            with patch.object(cmd, '_waitForProcessExit', return_value=True):
                result = cmd.initiateShutdown(reason='test', powerOff=True)

                self.assertTrue(result.success)
                self.assertTrue(result.powerOffRequested)
                self.assertTrue(result.powerOffExecuted)

    def test_initiateShutdown_setsState(self):
        """initiateShutdown updates command state."""
        cmd = ShutdownCommand()

        with patch.object(cmd, 'getProcessId', return_value=12345):
            with patch.object(cmd, '_sendSignal'):
                with patch.object(cmd, '_waitForProcessExit', return_value=True):
                    cmd.initiateShutdown()

                    self.assertEqual(cmd.getState(), ShutdownState.COMPLETED)

    def test_initiateShutdown_logsToDatabase(self):
        """initiateShutdown logs shutdown event to database."""
        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=None)
        mockConn.cursor.return_value = mockCursor

        cmd = ShutdownCommand(database=mockDb)

        with patch.object(cmd, 'getProcessId', return_value=12345):
            with patch.object(cmd, '_sendSignal'):
                with patch.object(cmd, '_waitForProcessExit', return_value=True):
                    cmd.initiateShutdown(reason='test_log')

                    # Should have logged twice (initiated + completed)
                    self.assertGreaterEqual(mockCursor.execute.call_count, 1)


class TestShutdownCommandStopViaSystemctl(unittest.TestCase):
    """Tests for ShutdownCommand.stopViaSystemctl."""

    @patch('subprocess.run')
    def test_stopViaSystemctl_success(self, mockRun):
        """stopViaSystemctl returns True on success."""
        mockRun.return_value = MagicMock(returncode=0)

        cmd = ShutdownCommand()
        result = cmd.stopViaSystemctl()

        self.assertTrue(result)

    @patch('subprocess.run')
    def test_stopViaSystemctl_failure(self, mockRun):
        """stopViaSystemctl returns False on failure."""
        mockRun.return_value = MagicMock(returncode=1)

        cmd = ShutdownCommand()
        result = cmd.stopViaSystemctl()

        self.assertFalse(result)

    @patch('subprocess.run', side_effect=FileNotFoundError)
    def test_stopViaSystemctl_noSystemctl(self, mockRun):
        """stopViaSystemctl returns False when systemctl not found."""
        cmd = ShutdownCommand()
        result = cmd.stopViaSystemctl()

        self.assertFalse(result)


class TestGenerateShutdownScript(unittest.TestCase):
    """Tests for generateShutdownScript function."""

    def test_generatesFile(self):
        """generateShutdownScript creates a file."""
        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'shutdown.sh')
            result = generateShutdownScript(outputPath=outputPath)

            self.assertEqual(result, outputPath)
            self.assertTrue(os.path.exists(outputPath))

    @unittest.skipIf(sys.platform == 'win32', 'Executable bit not supported on Windows')
    def test_scriptIsExecutable(self):
        """Generated script is executable."""
        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'shutdown.sh')
            generateShutdownScript(outputPath=outputPath)

            mode = os.stat(outputPath).st_mode
            self.assertTrue(mode & stat.S_IXUSR)

    def test_scriptContainsShebang(self):
        """Generated script starts with shebang."""
        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'shutdown.sh')
            generateShutdownScript(outputPath=outputPath)

            with open(outputPath, 'r') as f:
                content = f.read()

            self.assertTrue(content.startswith('#!/bin/bash'))

    def test_scriptContainsTimeout(self):
        """Generated script contains configured timeout."""
        config = ShutdownConfig(timeoutSeconds=45)

        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'shutdown.sh')
            generateShutdownScript(outputPath=outputPath, config=config)

            with open(outputPath, 'r') as f:
                content = f.read()

            self.assertIn('SHUTDOWN_TIMEOUT=45', content)

    def test_scriptContainsServiceName(self):
        """Generated script contains configured service name."""
        config = ShutdownConfig(serviceName='test-service')

        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'shutdown.sh')
            generateShutdownScript(outputPath=outputPath, config=config)

            with open(outputPath, 'r') as f:
                content = f.read()

            self.assertIn('SERVICE_NAME="test-service"', content)

    def test_scriptContainsPidFile(self):
        """Generated script contains configured PID file."""
        config = ShutdownConfig(pidFile='/custom/path.pid')

        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'shutdown.sh')
            generateShutdownScript(outputPath=outputPath, config=config)

            with open(outputPath, 'r') as f:
                content = f.read()

            self.assertIn('PID_FILE="/custom/path.pid"', content)

    def test_scriptContainsPowerOffSection(self):
        """Generated script contains power off section when requested."""
        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'shutdown.sh')
            generateShutdownScript(outputPath=outputPath, powerOff=True)

            with open(outputPath, 'r') as f:
                content = f.read()

            self.assertIn('POWER_OFF_DELAY', content)
            self.assertIn('shutdown -h', content)


class TestGenerateGpioTriggerScript(unittest.TestCase):
    """Tests for generateGpioTriggerScript function."""

    def test_generatesFile(self):
        """generateGpioTriggerScript creates a file."""
        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'gpio_shutdown.py')
            result = generateGpioTriggerScript(outputPath=outputPath)

            self.assertEqual(result, outputPath)
            self.assertTrue(os.path.exists(outputPath))

    def test_scriptIsPython(self):
        """Generated script is a Python script."""
        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'gpio_shutdown.py')
            generateGpioTriggerScript(outputPath=outputPath)

            with open(outputPath, 'r') as f:
                content = f.read()

            self.assertTrue(content.startswith('#!/usr/bin/env python3'))

    def test_scriptContainsGpioPin(self):
        """Generated script contains configured GPIO pin."""
        config = ShutdownConfig(gpioPin=27)

        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'gpio_shutdown.py')
            generateGpioTriggerScript(outputPath=outputPath, config=config)

            with open(outputPath, 'r') as f:
                content = f.read()

            self.assertIn('GPIO_PIN = 27', content)

    def test_scriptContainsDebounce(self):
        """Generated script contains configured debounce."""
        config = ShutdownConfig(gpioDebounceMs=500)

        with tempfile.TemporaryDirectory() as tmpDir:
            outputPath = os.path.join(tmpDir, 'gpio_shutdown.py')
            generateGpioTriggerScript(outputPath=outputPath, config=config)

            with open(outputPath, 'r') as f:
                content = f.read()

            self.assertIn('DEBOUNCE_MS = 500', content)


class TestCreateShutdownCommandFromConfig(unittest.TestCase):
    """Tests for createShutdownCommandFromConfig function."""

    def test_emptyConfig(self):
        """createShutdownCommandFromConfig handles empty config."""
        cmd = createShutdownCommandFromConfig({})

        self.assertIsNotNone(cmd)
        self.assertEqual(cmd._config.timeoutSeconds, DEFAULT_SHUTDOWN_TIMEOUT)

    def test_withShutdownSection(self):
        """createShutdownCommandFromConfig parses shutdown section."""
        config = {
            'shutdown': {
                'timeoutSeconds': 60,
                'gpioPin': 22,
                'powerOffEnabled': True
            }
        }

        cmd = createShutdownCommandFromConfig(config)

        self.assertEqual(cmd._config.timeoutSeconds, 60)
        self.assertEqual(cmd._config.gpioPin, 22)
        self.assertTrue(cmd._config.powerOffEnabled)

    def test_withAutoStartSection(self):
        """createShutdownCommandFromConfig uses service name from autoStart."""
        config = {
            'autoStart': {
                'serviceName': 'custom-service'
            }
        }

        cmd = createShutdownCommandFromConfig(config)

        self.assertEqual(cmd._config.serviceName, 'custom-service')


class TestIsGpioAvailable(unittest.TestCase):
    """Tests for isGpioAvailable function."""

    def test_returnsBoolean(self):
        """isGpioAvailable returns boolean."""
        result = isGpioAvailable()
        self.assertIsInstance(result, bool)


class TestSendShutdownSignal(unittest.TestCase):
    """Tests for sendShutdownSignal function."""

    @patch('os.kill')
    def test_sendsSignal(self, mockKill):
        """sendShutdownSignal sends SIGTERM to process."""
        with patch.object(ShutdownCommand, 'getProcessId', return_value=12345):
            result = sendShutdownSignal()

            self.assertTrue(result)
            mockKill.assert_called_once_with(12345, 15)  # SIGTERM

    def test_returnsFalseWhenNoProcess(self):
        """sendShutdownSignal returns False when no process found."""
        with patch.object(ShutdownCommand, 'getProcessId', return_value=None):
            result = sendShutdownSignal(pidFile='/nonexistent.pid')

            self.assertFalse(result)


class TestGpioButtonTrigger(unittest.TestCase):
    """Tests for GpioButtonTrigger class."""

    def test_initRaisesErrorWhenGpioNotAvailable(self):
        """GpioButtonTrigger raises error when GPIO not available."""
        # Mock GPIO_AVAILABLE to False
        import obd.shutdown_command as module
        original = module.GPIO_AVAILABLE

        try:
            module.GPIO_AVAILABLE = False
            with self.assertRaises(GpioNotAvailableError):
                from obd.shutdown_command import GpioButtonTrigger
                GpioButtonTrigger()
        finally:
            module.GPIO_AVAILABLE = original


class TestExceptions(unittest.TestCase):
    """Tests for custom exceptions."""

    def test_shutdownCommandError(self):
        """ShutdownCommandError stores message and details."""
        error = ShutdownCommandError('test error', {'key': 'value'})

        self.assertEqual(error.message, 'test error')
        self.assertEqual(error.details, {'key': 'value'})
        self.assertEqual(str(error), 'test error')

    def test_processNotFoundError(self):
        """ProcessNotFoundError inherits from ShutdownCommandError."""
        error = ProcessNotFoundError('process not found')

        self.assertIsInstance(error, ShutdownCommandError)
        self.assertEqual(error.message, 'process not found')

    def test_shutdownTimeoutError(self):
        """ShutdownTimeoutError inherits from ShutdownCommandError."""
        error = ShutdownTimeoutError('timeout')

        self.assertIsInstance(error, ShutdownCommandError)

    def test_gpioNotAvailableError(self):
        """GpioNotAvailableError inherits from ShutdownCommandError."""
        error = GpioNotAvailableError('GPIO not available')

        self.assertIsInstance(error, ShutdownCommandError)


class TestWaitForProcessExit(unittest.TestCase):
    """Tests for _waitForProcessExit method."""

    def test_returnsImmediatelyWhenProcessExits(self):
        """_waitForProcessExit returns True when process exits."""
        cmd = ShutdownCommand(timeoutSeconds=5)

        with patch.object(cmd, '_isProcessRunning', return_value=False):
            startTime = time.time()
            result = cmd._waitForProcessExit(12345)
            elapsed = time.time() - startTime

            self.assertTrue(result)
            self.assertLess(elapsed, 1)  # Should return immediately

    def test_returnsFalseOnTimeout(self):
        """_waitForProcessExit returns False on timeout."""
        cmd = ShutdownCommand(timeoutSeconds=1)

        with patch.object(cmd, '_isProcessRunning', return_value=True):
            startTime = time.time()
            result = cmd._waitForProcessExit(12345)
            elapsed = time.time() - startTime

            self.assertFalse(result)
            self.assertGreaterEqual(elapsed, 1)


def runTests():
    """Run all tests and return success status."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return len(result.failures) == 0 and len(result.errors) == 0


if __name__ == '__main__':
    success = runTests()

    # Print summary
    print('\n' + '=' * 70)
    if success:
        print('ALL TESTS PASSED')
    else:
        print('SOME TESTS FAILED')
    print('=' * 70)

    sys.exit(0 if success else 1)
