################################################################################
# File Name: test_shutdown_handler.py
# Purpose/Description: Tests for graceful shutdown handler
# Author: Ralph Agent
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Ralph Agent  | Initial implementation for US-RPI-007
# ================================================================================
################################################################################

"""
Tests for the shutdown_handler module.

Tests graceful shutdown functionality with mocked subprocess calls
for cross-platform testing.

Run with:
    pytest tests/test_shutdown_handler.py -v
"""

import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from hardware.shutdown_handler import (
    ShutdownHandler,
    ShutdownHandlerError,
    DEFAULT_SHUTDOWN_DELAY,
    DEFAULT_LOW_BATTERY_THRESHOLD,
)
from hardware.ups_monitor import PowerSource


# ================================================================================
# Exception Tests
# ================================================================================

class TestShutdownExceptions:
    """Tests for ShutdownHandler exception classes."""

    def test_shutdownHandlerError_isBaseException(self):
        """
        Given: ShutdownHandlerError
        When: Checked for inheritance
        Then: Is subclass of Exception
        """
        # Assert
        assert issubclass(ShutdownHandlerError, Exception)

    def test_shutdownHandlerError_hasMessage(self):
        """
        Given: ShutdownHandlerError with message
        When: Converted to string
        Then: Contains the message
        """
        # Arrange
        error = ShutdownHandlerError("Test shutdown error")

        # Act
        result = str(error)

        # Assert
        assert "Test shutdown error" in result


# ================================================================================
# Constants Tests
# ================================================================================

class TestShutdownConstants:
    """Tests for shutdown handler constants."""

    def test_defaultShutdownDelay_is30(self):
        """
        Given: DEFAULT_SHUTDOWN_DELAY constant
        When: Checked
        Then: Is 30 seconds
        """
        assert DEFAULT_SHUTDOWN_DELAY == 30

    def test_defaultLowBatteryThreshold_is10(self):
        """
        Given: DEFAULT_LOW_BATTERY_THRESHOLD constant
        When: Checked
        Then: Is 10 percent
        """
        assert DEFAULT_LOW_BATTERY_THRESHOLD == 10


# ================================================================================
# Initialization Tests
# ================================================================================

class TestShutdownHandlerInit:
    """Tests for ShutdownHandler initialization."""

    def test_init_withDefaults_setsDefaultValues(self):
        """
        Given: No arguments
        When: ShutdownHandler is created
        Then: Uses default values for delay and threshold
        """
        # Act
        handler = ShutdownHandler()

        # Assert
        assert handler.shutdownDelay == DEFAULT_SHUTDOWN_DELAY
        assert handler.lowBatteryThreshold == DEFAULT_LOW_BATTERY_THRESHOLD
        assert not handler.isShutdownPending

    def test_init_withCustomDelay_usesProvidedValue(self):
        """
        Given: Custom shutdown delay
        When: ShutdownHandler is created
        Then: Uses provided delay value
        """
        # Act
        handler = ShutdownHandler(shutdownDelay=60)

        # Assert
        assert handler.shutdownDelay == 60

    def test_init_withCustomThreshold_usesProvidedValue(self):
        """
        Given: Custom low battery threshold
        When: ShutdownHandler is created
        Then: Uses provided threshold value
        """
        # Act
        handler = ShutdownHandler(lowBatteryThreshold=15)

        # Assert
        assert handler.lowBatteryThreshold == 15

    def test_init_withZeroDelay_raisesValueError(self):
        """
        Given: Zero shutdown delay
        When: ShutdownHandler is created
        Then: Raises ValueError
        """
        # Act/Assert
        with pytest.raises(ValueError) as exc:
            ShutdownHandler(shutdownDelay=0)
        assert "positive" in str(exc.value).lower()

    def test_init_withNegativeDelay_raisesValueError(self):
        """
        Given: Negative shutdown delay
        When: ShutdownHandler is created
        Then: Raises ValueError
        """
        # Act/Assert
        with pytest.raises(ValueError) as exc:
            ShutdownHandler(shutdownDelay=-10)
        assert "positive" in str(exc.value).lower()

    def test_init_withNegativeThreshold_raisesValueError(self):
        """
        Given: Negative low battery threshold
        When: ShutdownHandler is created
        Then: Raises ValueError
        """
        # Act/Assert
        with pytest.raises(ValueError) as exc:
            ShutdownHandler(lowBatteryThreshold=-5)
        assert "must be" in str(exc.value).lower() or "threshold" in str(exc.value).lower()

    def test_init_withThresholdOver100_raisesValueError(self):
        """
        Given: Low battery threshold over 100
        When: ShutdownHandler is created
        Then: Raises ValueError
        """
        # Act/Assert
        with pytest.raises(ValueError) as exc:
            ShutdownHandler(lowBatteryThreshold=150)
        assert "threshold" in str(exc.value).lower() or "100" in str(exc.value)


# ================================================================================
# Power Source Change Handler Tests
# ================================================================================

class TestPowerSourceChangeHandler:
    """Tests for handling power source changes."""

    def test_onPowerLost_toBattery_schedulesShutdown(self):
        """
        Given: ShutdownHandler not pending
        When: Power source changes from EXTERNAL to BATTERY
        Then: Schedules shutdown after delay
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)

        # Act
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)

        # Assert
        assert handler.isShutdownPending

    def test_onPowerLost_toBattery_logsInfoMessage(self):
        """
        Given: ShutdownHandler
        When: Power source changes to BATTERY
        Then: Logs INFO message about pending shutdown
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)

        # Act
        with patch('hardware.shutdown_handler.logger') as mockLogger:
            handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)

        # Assert
        mockLogger.info.assert_called()
        callArgs = str(mockLogger.info.call_args)
        assert "shutdown" in callArgs.lower() or "battery" in callArgs.lower()

    def test_onPowerRestored_toExternal_cancelsShutdown(self):
        """
        Given: ShutdownHandler with pending shutdown
        When: Power source changes from BATTERY to EXTERNAL
        Then: Cancels the pending shutdown
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        assert handler.isShutdownPending

        # Act
        handler.onPowerSourceChange(PowerSource.BATTERY, PowerSource.EXTERNAL)

        # Assert
        assert not handler.isShutdownPending

    def test_onPowerRestored_toExternal_logsInfoMessage(self):
        """
        Given: ShutdownHandler with pending shutdown
        When: Power source changes to EXTERNAL
        Then: Logs INFO message about cancelled shutdown
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)

        # Act
        with patch('hardware.shutdown_handler.logger') as mockLogger:
            handler.onPowerSourceChange(PowerSource.BATTERY, PowerSource.EXTERNAL)

        # Assert
        mockLogger.info.assert_called()
        callArgs = str(mockLogger.info.call_args)
        assert "cancel" in callArgs.lower() or "restored" in callArgs.lower()

    def test_onPowerLost_alreadyPending_doesNotDoubleSchedule(self):
        """
        Given: ShutdownHandler with pending shutdown
        When: Power source changes to BATTERY again
        Then: Does not schedule a second shutdown
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        firstTimer = handler._shutdownTimer

        # Act
        handler.onPowerSourceChange(PowerSource.UNKNOWN, PowerSource.BATTERY)

        # Assert
        # Timer should be the same (not recreated)
        assert handler._shutdownTimer is firstTimer

    def test_onPowerRestored_notPending_doesNothing(self):
        """
        Given: ShutdownHandler with no pending shutdown
        When: Power source changes to EXTERNAL
        Then: Does nothing (no error)
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        assert not handler.isShutdownPending

        # Act (should not raise)
        handler.onPowerSourceChange(PowerSource.BATTERY, PowerSource.EXTERNAL)

        # Assert
        assert not handler.isShutdownPending


# ================================================================================
# Low Battery Handler Tests
# ================================================================================

class TestLowBatteryHandler:
    """Tests for handling low battery conditions."""

    @patch('hardware.shutdown_handler.subprocess.run')
    def test_onLowBattery_belowThreshold_triggersImmediateShutdown(self, mockRun):
        """
        Given: Battery percentage below threshold
        When: onLowBattery is called
        Then: Triggers immediate system shutdown
        """
        # Arrange
        handler = ShutdownHandler(lowBatteryThreshold=10)
        mockRun.return_value = MagicMock(returncode=0)

        # Act
        handler.onLowBattery(5)  # 5% is below 10% threshold

        # Assert
        mockRun.assert_called_once()
        callArgs = mockRun.call_args[0][0]
        assert 'systemctl' in callArgs or 'poweroff' in callArgs

    @patch('hardware.shutdown_handler.subprocess.run')
    def test_onLowBattery_atThreshold_triggersShutdown(self, mockRun):
        """
        Given: Battery percentage at threshold
        When: onLowBattery is called
        Then: Triggers immediate system shutdown
        """
        # Arrange
        handler = ShutdownHandler(lowBatteryThreshold=10)
        mockRun.return_value = MagicMock(returncode=0)

        # Act
        handler.onLowBattery(10)  # 10% equals 10% threshold

        # Assert
        mockRun.assert_called_once()

    def test_onLowBattery_aboveThreshold_doesNotShutdown(self):
        """
        Given: Battery percentage above threshold
        When: onLowBattery is called
        Then: Does not trigger shutdown
        """
        # Arrange
        handler = ShutdownHandler(lowBatteryThreshold=10)

        # Act
        with patch('hardware.shutdown_handler.subprocess.run') as mockRun:
            handler.onLowBattery(15)  # 15% is above 10% threshold

        # Assert
        mockRun.assert_not_called()

    @patch('hardware.shutdown_handler.subprocess.run')
    def test_onLowBattery_logsInfoMessage(self, mockRun):
        """
        Given: Battery percentage below threshold
        When: onLowBattery is called
        Then: Logs INFO message about low battery shutdown
        """
        # Arrange
        handler = ShutdownHandler(lowBatteryThreshold=10)
        mockRun.return_value = MagicMock(returncode=0)

        # Act
        with patch('hardware.shutdown_handler.logger') as mockLogger:
            handler.onLowBattery(5)

        # Assert
        mockLogger.info.assert_called()
        # Check all info calls for low battery message
        allCalls = str(mockLogger.info.call_args_list)
        assert "battery" in allCalls.lower() or "low" in allCalls.lower()


# ================================================================================
# Scheduled Shutdown Tests
# ================================================================================

class TestScheduledShutdown:
    """Tests for scheduled shutdown execution."""

    @patch('hardware.shutdown_handler.subprocess.run')
    def test_scheduledShutdown_executesAfterDelay(self, mockRun):
        """
        Given: ShutdownHandler with 1 second delay
        When: Power is lost
        Then: Shutdown executes after delay
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=1)
        mockRun.return_value = MagicMock(returncode=0)

        # Act
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        time.sleep(1.5)  # Wait for shutdown to execute

        # Assert
        mockRun.assert_called_once()

    @patch('hardware.shutdown_handler.subprocess.run')
    def test_scheduledShutdown_cancelledBeforeExecution_doesNotExecute(self, mockRun):
        """
        Given: ShutdownHandler with longer delay
        When: Power is lost then restored before delay expires
        Then: Shutdown does not execute
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=5)

        # Act
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        time.sleep(0.1)  # Brief delay
        handler.onPowerSourceChange(PowerSource.BATTERY, PowerSource.EXTERNAL)
        time.sleep(0.2)  # Brief delay to allow any callbacks

        # Assert
        mockRun.assert_not_called()

    @patch('hardware.shutdown_handler.subprocess.run')
    def test_scheduledShutdown_usesSystemctlPoweroff(self, mockRun):
        """
        Given: ShutdownHandler
        When: Shutdown is executed
        Then: Uses 'systemctl poweroff' command
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=1)
        mockRun.return_value = MagicMock(returncode=0)

        # Act
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        time.sleep(1.5)

        # Assert
        mockRun.assert_called_once()
        callArgs = mockRun.call_args[0][0]
        assert callArgs == ['systemctl', 'poweroff']

    @patch('hardware.shutdown_handler.subprocess.run')
    def test_scheduledShutdown_logsInfoBeforeShutdown(self, mockRun):
        """
        Given: ShutdownHandler
        When: Shutdown is about to execute
        Then: Logs INFO message with timestamp
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=1)
        mockRun.return_value = MagicMock(returncode=0)

        # Act
        with patch('hardware.shutdown_handler.logger') as mockLogger:
            handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
            time.sleep(1.5)

        # Assert
        # Should have logged multiple info messages (scheduling and executing)
        assert mockLogger.info.call_count >= 2


# ================================================================================
# UPS Monitor Integration Tests
# ================================================================================

class TestUpsMonitorIntegration:
    """Tests for integration with UpsMonitor."""

    def test_registerWithUpsMonitor_setsPowerChangeCallback(self):
        """
        Given: ShutdownHandler and mock UpsMonitor
        When: registerWithUpsMonitor is called
        Then: Sets the power change callback on UpsMonitor
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        mockUps = MagicMock()
        mockUps.onPowerSourceChange = None

        # Act
        handler.registerWithUpsMonitor(mockUps)

        # Assert
        assert mockUps.onPowerSourceChange == handler.onPowerSourceChange

    def test_unregisterFromUpsMonitor_clearsPowerChangeCallback(self):
        """
        Given: ShutdownHandler registered with mock UpsMonitor
        When: unregisterFromUpsMonitor is called
        Then: Clears the power change callback
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        mockUps = MagicMock()
        handler.registerWithUpsMonitor(mockUps)

        # Act
        handler.unregisterFromUpsMonitor(mockUps)

        # Assert
        assert mockUps.onPowerSourceChange is None


# ================================================================================
# Properties Tests
# ================================================================================

class TestShutdownHandlerProperties:
    """Tests for ShutdownHandler properties."""

    def test_shutdownDelay_getter(self):
        """
        Given: ShutdownHandler with custom delay
        When: shutdownDelay property is accessed
        Then: Returns the configured delay
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=45)

        # Act/Assert
        assert handler.shutdownDelay == 45

    def test_shutdownDelay_setter_validValue(self):
        """
        Given: ShutdownHandler
        When: shutdownDelay is set to valid value
        Then: Updates the delay
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=30)

        # Act
        handler.shutdownDelay = 60

        # Assert
        assert handler.shutdownDelay == 60

    def test_shutdownDelay_setter_invalidValue_raisesValueError(self):
        """
        Given: ShutdownHandler
        When: shutdownDelay is set to invalid value
        Then: Raises ValueError
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=30)

        # Act/Assert
        with pytest.raises(ValueError):
            handler.shutdownDelay = 0

    def test_lowBatteryThreshold_getter(self):
        """
        Given: ShutdownHandler with custom threshold
        When: lowBatteryThreshold property is accessed
        Then: Returns the configured threshold
        """
        # Arrange
        handler = ShutdownHandler(lowBatteryThreshold=20)

        # Act/Assert
        assert handler.lowBatteryThreshold == 20

    def test_lowBatteryThreshold_setter_validValue(self):
        """
        Given: ShutdownHandler
        When: lowBatteryThreshold is set to valid value
        Then: Updates the threshold
        """
        # Arrange
        handler = ShutdownHandler(lowBatteryThreshold=10)

        # Act
        handler.lowBatteryThreshold = 15

        # Assert
        assert handler.lowBatteryThreshold == 15

    def test_lowBatteryThreshold_setter_invalidValue_raisesValueError(self):
        """
        Given: ShutdownHandler
        When: lowBatteryThreshold is set to invalid value
        Then: Raises ValueError
        """
        # Arrange
        handler = ShutdownHandler(lowBatteryThreshold=10)

        # Act/Assert
        with pytest.raises(ValueError):
            handler.lowBatteryThreshold = -1

    def test_isShutdownPending_getter_whenNotPending(self):
        """
        Given: ShutdownHandler with no pending shutdown
        When: isShutdownPending is checked
        Then: Returns False
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)

        # Assert
        assert not handler.isShutdownPending

    def test_isShutdownPending_getter_whenPending(self):
        """
        Given: ShutdownHandler with pending shutdown
        When: isShutdownPending is checked
        Then: Returns True
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)

        # Assert
        assert handler.isShutdownPending

    def test_timeUntilShutdown_whenNotPending_returnsNone(self):
        """
        Given: ShutdownHandler with no pending shutdown
        When: timeUntilShutdown is checked
        Then: Returns None
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)

        # Assert
        assert handler.timeUntilShutdown is None

    def test_timeUntilShutdown_whenPending_returnsRemainingTime(self):
        """
        Given: ShutdownHandler with pending shutdown
        When: timeUntilShutdown is checked
        Then: Returns approximate remaining time
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)

        # Act
        timeLeft = handler.timeUntilShutdown

        # Assert
        assert timeLeft is not None
        assert 55 <= timeLeft <= 60  # Within tolerance


# ================================================================================
# Cancel Shutdown Tests
# ================================================================================

class TestCancelShutdown:
    """Tests for explicitly cancelling shutdown."""

    def test_cancelShutdown_whenPending_cancelsAndReturnsTrue(self):
        """
        Given: ShutdownHandler with pending shutdown
        When: cancelShutdown is called
        Then: Cancels shutdown and returns True
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        assert handler.isShutdownPending

        # Act
        result = handler.cancelShutdown()

        # Assert
        assert result is True
        assert not handler.isShutdownPending

    def test_cancelShutdown_whenNotPending_returnsFalse(self):
        """
        Given: ShutdownHandler with no pending shutdown
        When: cancelShutdown is called
        Then: Returns False
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        assert not handler.isShutdownPending

        # Act
        result = handler.cancelShutdown()

        # Assert
        assert result is False

    def test_cancelShutdown_logsInfoMessage(self):
        """
        Given: ShutdownHandler with pending shutdown
        When: cancelShutdown is called
        Then: Logs INFO message
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)

        # Act
        with patch('hardware.shutdown_handler.logger') as mockLogger:
            handler.cancelShutdown()

        # Assert
        mockLogger.info.assert_called()


# ================================================================================
# Lifecycle Tests
# ================================================================================

class TestShutdownHandlerLifecycle:
    """Tests for ShutdownHandler lifecycle management."""

    def test_close_cancelsPendingShutdown(self):
        """
        Given: ShutdownHandler with pending shutdown
        When: close is called
        Then: Cancels the pending shutdown
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        assert handler.isShutdownPending

        # Act
        handler.close()

        # Assert
        assert not handler.isShutdownPending

    def test_contextManager_entersAndExits(self):
        """
        Given: ShutdownHandler
        When: Used as context manager
        Then: Properly enters and exits
        """
        # Act
        with ShutdownHandler(shutdownDelay=60) as handler:
            handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
            assert handler.isShutdownPending

        # Assert (after exit)
        assert not handler.isShutdownPending

    def test_close_idempotent_safeToCallMultipleTimes(self):
        """
        Given: ShutdownHandler
        When: close is called multiple times
        Then: Does not raise error
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=60)
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)

        # Act (should not raise)
        handler.close()
        handler.close()
        handler.close()

        # Assert
        assert not handler.isShutdownPending


# ================================================================================
# Error Handling Tests
# ================================================================================

class TestShutdownErrorHandling:
    """Tests for error handling in shutdown process."""

    @patch('hardware.shutdown_handler.subprocess.run')
    def test_shutdown_subprocessError_logsError(self, mockRun):
        """
        Given: Shutdown subprocess fails
        When: Shutdown is executed
        Then: Logs error message
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=1)
        mockRun.side_effect = Exception("Subprocess failed")

        # Act
        with patch('hardware.shutdown_handler.logger') as mockLogger:
            handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
            time.sleep(1.5)

        # Assert
        mockLogger.error.assert_called()

    @patch('hardware.shutdown_handler.subprocess.run')
    def test_shutdown_nonZeroReturnCode_logsWarning(self, mockRun):
        """
        Given: Shutdown subprocess returns non-zero
        When: Shutdown is executed
        Then: Logs warning message
        """
        # Arrange
        handler = ShutdownHandler(shutdownDelay=1)
        mockRun.return_value = MagicMock(returncode=1)

        # Act
        with patch('hardware.shutdown_handler.logger') as mockLogger:
            handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
            time.sleep(1.5)

        # Assert
        mockLogger.warning.assert_called()
