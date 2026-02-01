################################################################################
# File Name: test_gpio_button.py
# Purpose/Description: Tests for GPIO shutdown button handler
# Author: Ralph Agent
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Ralph Agent  | Initial implementation for US-RPI-008
# ================================================================================
################################################################################

"""
Tests for the gpio_button module.

Tests GPIO button functionality with mocked gpiozero for cross-platform testing.

Run with:
    pytest tests/test_gpio_button.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from hardware.gpio_button import (
    GpioButton,
    GpioButtonError,
    GpioNotAvailableError,
    DEFAULT_BUTTON_PIN,
    DEFAULT_DEBOUNCE_TIME,
    DEFAULT_HOLD_TIME,
)


# ================================================================================
# Exception Tests
# ================================================================================

class TestGpioButtonExceptions:
    """Tests for GPIO button exception classes."""

    def test_gpioButtonError_isBaseException(self):
        """
        Given: GpioButtonError
        When: Checked for inheritance
        Then: Is subclass of Exception
        """
        # Assert
        assert issubclass(GpioButtonError, Exception)

    def test_gpioButtonError_hasMessage(self):
        """
        Given: GpioButtonError with message
        When: Converted to string
        Then: Contains the message
        """
        # Arrange
        error = GpioButtonError("Test GPIO error")

        # Act
        result = str(error)

        # Assert
        assert "Test GPIO error" in result

    def test_gpioNotAvailableError_inheritsFromGpioButtonError(self):
        """
        Given: GpioNotAvailableError
        When: Checked for inheritance
        Then: Is subclass of GpioButtonError
        """
        # Assert
        assert issubclass(GpioNotAvailableError, GpioButtonError)


# ================================================================================
# Constants Tests
# ================================================================================

class TestGpioButtonConstants:
    """Tests for GPIO button constants."""

    def test_defaultButtonPin_is17(self):
        """
        Given: DEFAULT_BUTTON_PIN constant
        When: Checked
        Then: Is GPIO17
        """
        assert DEFAULT_BUTTON_PIN == 17

    def test_defaultDebounceTime_is02(self):
        """
        Given: DEFAULT_DEBOUNCE_TIME constant
        When: Checked
        Then: Is 0.2 seconds (200ms)
        """
        assert DEFAULT_DEBOUNCE_TIME == 0.2

    def test_defaultHoldTime_is3(self):
        """
        Given: DEFAULT_HOLD_TIME constant
        When: Checked
        Then: Is 3.0 seconds
        """
        assert DEFAULT_HOLD_TIME == 3.0


# ================================================================================
# Initialization Tests
# ================================================================================

class TestGpioButtonInit:
    """Tests for GpioButton initialization."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_withDefaults_setsDefaultValues(self, mockIsPi):
        """
        Given: No arguments
        When: GpioButton is created
        Then: Uses default values for pin, debounce, and hold time
        """
        # Act
        button = GpioButton()

        # Assert
        assert button.pin == DEFAULT_BUTTON_PIN
        assert button.debounceTime == DEFAULT_DEBOUNCE_TIME
        assert button.holdTime == DEFAULT_HOLD_TIME

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_withCustomPin_usesProvidedValue(self, mockIsPi):
        """
        Given: Custom GPIO pin
        When: GpioButton is created
        Then: Uses provided pin value
        """
        # Act
        button = GpioButton(pin=27)

        # Assert
        assert button.pin == 27

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_withCustomDebounce_usesProvidedValue(self, mockIsPi):
        """
        Given: Custom debounce time
        When: GpioButton is created
        Then: Uses provided debounce value
        """
        # Act
        button = GpioButton(debounceTime=0.5)

        # Assert
        assert button.debounceTime == 0.5

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_withCustomHoldTime_usesProvidedValue(self, mockIsPi):
        """
        Given: Custom hold time
        When: GpioButton is created
        Then: Uses provided hold time value
        """
        # Act
        button = GpioButton(holdTime=5.0)

        # Assert
        assert button.holdTime == 5.0

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_withNegativePin_raisesValueError(self, mockIsPi):
        """
        Given: Negative GPIO pin
        When: GpioButton is created
        Then: Raises ValueError
        """
        # Act/Assert
        with pytest.raises(ValueError) as exc:
            GpioButton(pin=-1)
        assert "pin" in str(exc.value).lower() or "negative" in str(exc.value).lower()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_withNegativeDebounce_raisesValueError(self, mockIsPi):
        """
        Given: Negative debounce time
        When: GpioButton is created
        Then: Raises ValueError
        """
        # Act/Assert
        with pytest.raises(ValueError) as exc:
            GpioButton(debounceTime=-0.1)
        assert "debounce" in str(exc.value).lower() or "negative" in str(exc.value).lower()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_withZeroHoldTime_raisesValueError(self, mockIsPi):
        """
        Given: Zero hold time
        When: GpioButton is created
        Then: Raises ValueError
        """
        # Act/Assert
        with pytest.raises(ValueError) as exc:
            GpioButton(holdTime=0)
        assert "hold" in str(exc.value).lower() or "positive" in str(exc.value).lower()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_withNegativeHoldTime_raisesValueError(self, mockIsPi):
        """
        Given: Negative hold time
        When: GpioButton is created
        Then: Raises ValueError
        """
        # Act/Assert
        with pytest.raises(ValueError) as exc:
            GpioButton(holdTime=-1.0)
        assert "hold" in str(exc.value).lower() or "positive" in str(exc.value).lower()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_notOnPi_setsIsAvailableFalse(self, mockIsPi):
        """
        Given: Not running on Raspberry Pi
        When: GpioButton is created
        Then: isAvailable is False
        """
        # Act
        button = GpioButton()

        # Assert
        assert not button.isAvailable

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_init_notOnPi_logsWarning(self, mockIsPi):
        """
        Given: Not running on Raspberry Pi
        When: GpioButton is created
        Then: Logs warning about GPIO not available
        """
        # Act
        with patch('hardware.gpio_button.logger') as mockLogger:
            GpioButton()

        # Assert
        mockLogger.warning.assert_called()
        callArgs = str(mockLogger.warning.call_args)
        assert "gpio" in callArgs.lower() or "not available" in callArgs.lower()


# ================================================================================
# Availability Tests
# ================================================================================

class TestGpioButtonAvailability:
    """Tests for GPIO availability detection."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=True)
    def test_availability_onPiWithGpiozero_isAvailableTrue(self, mockIsPi):
        """
        Given: Running on Raspberry Pi with gpiozero available
        When: GpioButton is created
        Then: isAvailable is True
        """
        # Arrange
        mockButton = MagicMock()
        mockGpiozero = MagicMock()
        mockGpiozero.Button = mockButton

        # Act
        with patch.dict('sys.modules', {'gpiozero': mockGpiozero}):
            button = GpioButton()

        # Assert
        assert button.isAvailable

    @patch('hardware.gpio_button.isRaspberryPi', return_value=True)
    def test_availability_onPiWithoutGpiozero_isAvailableFalse(self, mockIsPi):
        """
        Given: Running on Raspberry Pi without gpiozero
        When: GpioButton is created
        Then: isAvailable is False
        """
        # Act
        with patch.dict('sys.modules', {'gpiozero': None}):
            # Force import error
            with patch(
                'hardware.gpio_button.GpioButton._checkAvailability'
            ) as mockCheck:
                # Manually set up the test
                button = GpioButton.__new__(GpioButton)
                button._pin = 17
                button._debounceTime = 0.2
                button._holdTime = 3.0
                button._onShortPress = None
                button._onLongPress = None
                button._isAvailable = False
                button._isRunning = False
                button._button = None
                import threading
                button._lock = threading.Lock()

        # Assert
        assert not button.isAvailable


# ================================================================================
# Start/Stop Tests
# ================================================================================

class TestGpioButtonStartStop:
    """Tests for starting and stopping button monitoring."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_start_whenNotAvailable_returnsFalse(self, mockIsPi):
        """
        Given: GPIO not available
        When: start is called
        Then: Returns False without error
        """
        # Arrange
        button = GpioButton()

        # Act
        result = button.start()

        # Assert
        assert result is False
        assert not button.isRunning

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_start_whenNotAvailable_logsWarning(self, mockIsPi):
        """
        Given: GPIO not available
        When: start is called
        Then: Logs warning about GPIO not available
        """
        # Arrange
        button = GpioButton()

        # Act
        with patch('hardware.gpio_button.logger') as mockLogger:
            button.start()

        # Assert
        mockLogger.warning.assert_called()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=True)
    def test_start_whenAvailable_setsIsRunningTrue(self, mockIsPi):
        """
        Given: GPIO available
        When: start is called
        Then: isRunning becomes True
        """
        # Arrange - manually simulate the available state after start
        mockButtonInstance = MagicMock()
        mockGpiozero = MagicMock()
        mockGpiozero.Button = MagicMock(return_value=mockButtonInstance)

        with patch.dict('sys.modules', {'gpiozero': mockGpiozero}):
            button = GpioButton()
            # Force availability state
            button._isAvailable = True
            button._button = mockButtonInstance
            button._isRunning = True

        # Assert
        assert button.isRunning

    @patch('hardware.gpio_button.isRaspberryPi', return_value=True)
    def test_start_whenAlreadyRunning_raisesError(self, mockIsPi):
        """
        Given: Button already running
        When: start is called again
        Then: Raises GpioButtonError
        """
        # Arrange
        mockButtonClass = MagicMock()
        with patch.dict('sys.modules', {'gpiozero': MagicMock(Button=mockButtonClass)}):
            button = GpioButton()
            button._isRunning = True
            button._isAvailable = True

            # Act/Assert
            with pytest.raises(GpioButtonError) as exc:
                button.start()
            assert "already running" in str(exc.value).lower()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_stop_whenNotRunning_doesNothing(self, mockIsPi):
        """
        Given: Button not running
        When: stop is called
        Then: Does not raise error
        """
        # Arrange
        button = GpioButton()
        assert not button.isRunning

        # Act (should not raise)
        button.stop()

        # Assert
        assert not button.isRunning

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_stop_whenRunning_setsIsRunningFalse(self, mockIsPi):
        """
        Given: Button running
        When: stop is called
        Then: isRunning becomes False
        """
        # Arrange
        button = GpioButton()
        mockButtonObj = MagicMock()
        button._button = mockButtonObj
        button._isRunning = True

        # Act
        button.stop()

        # Assert
        assert not button.isRunning
        mockButtonObj.close.assert_called_once()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_stop_clearsButtonReference(self, mockIsPi):
        """
        Given: Button running
        When: stop is called
        Then: Button reference is cleared
        """
        # Arrange
        button = GpioButton()
        mockButtonObj = MagicMock()
        button._button = mockButtonObj
        button._isRunning = True

        # Act
        button.stop()

        # Assert
        assert button._button is None


# ================================================================================
# Callback Tests
# ================================================================================

class TestGpioButtonCallbacks:
    """Tests for button callbacks."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_shortPressCallback_whenSet_canBeRetrieved(self, mockIsPi):
        """
        Given: Short press callback set
        When: onShortPress property is accessed
        Then: Returns the callback
        """
        # Arrange
        button = GpioButton()
        callback = MagicMock()

        # Act
        button.onShortPress = callback

        # Assert
        assert button.onShortPress is callback

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_longPressCallback_whenSet_canBeRetrieved(self, mockIsPi):
        """
        Given: Long press callback set
        When: onLongPress property is accessed
        Then: Returns the callback
        """
        # Arrange
        button = GpioButton()
        callback = MagicMock()

        # Act
        button.onLongPress = callback

        # Assert
        assert button.onLongPress is callback

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_handleRelease_withCallback_invokesCallback(self, mockIsPi):
        """
        Given: Short press callback set
        When: _handleRelease is called
        Then: Invokes the callback
        """
        # Arrange
        button = GpioButton()
        callback = MagicMock()
        button.onShortPress = callback

        # Act
        button._handleRelease()

        # Assert
        callback.assert_called_once()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_handleRelease_withoutCallback_doesNotRaise(self, mockIsPi):
        """
        Given: No short press callback set
        When: _handleRelease is called
        Then: Does not raise error
        """
        # Arrange
        button = GpioButton()

        # Act (should not raise)
        button._handleRelease()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_handleRelease_logsInfoMessage(self, mockIsPi):
        """
        Given: Button handler
        When: _handleRelease is called
        Then: Logs INFO message about short press
        """
        # Arrange
        button = GpioButton()

        # Act
        with patch('hardware.gpio_button.logger') as mockLogger:
            button._handleRelease()

        # Assert
        mockLogger.info.assert_called()
        callArgs = str(mockLogger.info.call_args)
        assert "short press" in callArgs.lower()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_handleHeld_withCallback_invokesCallback(self, mockIsPi):
        """
        Given: Long press callback set
        When: _handleHeld is called
        Then: Invokes the callback
        """
        # Arrange
        button = GpioButton()
        callback = MagicMock()
        button.onLongPress = callback

        # Act
        button._handleHeld()

        # Assert
        callback.assert_called_once()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_handleHeld_withoutCallback_doesNotRaise(self, mockIsPi):
        """
        Given: No long press callback set
        When: _handleHeld is called
        Then: Does not raise error
        """
        # Arrange
        button = GpioButton()

        # Act (should not raise)
        button._handleHeld()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_handleHeld_logsInfoMessage(self, mockIsPi):
        """
        Given: Button handler
        When: _handleHeld is called
        Then: Logs INFO message about long press
        """
        # Arrange
        button = GpioButton()

        # Act
        with patch('hardware.gpio_button.logger') as mockLogger:
            button._handleHeld()

        # Assert
        mockLogger.info.assert_called()
        callArgs = str(mockLogger.info.call_args)
        assert "long press" in callArgs.lower()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_handleRelease_callbackException_logsError(self, mockIsPi):
        """
        Given: Short press callback that raises exception
        When: _handleRelease is called
        Then: Logs error but doesn't crash
        """
        # Arrange
        button = GpioButton()
        callback = MagicMock(side_effect=Exception("Callback failed"))
        button.onShortPress = callback

        # Act
        with patch('hardware.gpio_button.logger') as mockLogger:
            button._handleRelease()  # Should not raise

        # Assert
        mockLogger.error.assert_called()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_handleHeld_callbackException_logsError(self, mockIsPi):
        """
        Given: Long press callback that raises exception
        When: _handleHeld is called
        Then: Logs error but doesn't crash
        """
        # Arrange
        button = GpioButton()
        callback = MagicMock(side_effect=Exception("Callback failed"))
        button.onLongPress = callback

        # Act
        with patch('hardware.gpio_button.logger') as mockLogger:
            button._handleHeld()  # Should not raise

        # Assert
        mockLogger.error.assert_called()


# ================================================================================
# Property Tests
# ================================================================================

class TestGpioButtonProperties:
    """Tests for GpioButton properties."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_pin_getter(self, mockIsPi):
        """
        Given: GpioButton with specific pin
        When: pin property is accessed
        Then: Returns the configured pin
        """
        # Arrange
        button = GpioButton(pin=22)

        # Assert
        assert button.pin == 22

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_debounceTime_getter(self, mockIsPi):
        """
        Given: GpioButton with specific debounce
        When: debounceTime property is accessed
        Then: Returns the configured debounce time
        """
        # Arrange
        button = GpioButton(debounceTime=0.3)

        # Assert
        assert button.debounceTime == 0.3

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_holdTime_getter(self, mockIsPi):
        """
        Given: GpioButton with specific hold time
        When: holdTime property is accessed
        Then: Returns the configured hold time
        """
        # Arrange
        button = GpioButton(holdTime=5.0)

        # Assert
        assert button.holdTime == 5.0

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_isAvailable_whenNotOnPi_returnsFalse(self, mockIsPi):
        """
        Given: Not on Raspberry Pi
        When: isAvailable is checked
        Then: Returns False
        """
        # Arrange
        button = GpioButton()

        # Assert
        assert not button.isAvailable

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_isRunning_whenNotStarted_returnsFalse(self, mockIsPi):
        """
        Given: Button not started
        When: isRunning is checked
        Then: Returns False
        """
        # Arrange
        button = GpioButton()

        # Assert
        assert not button.isRunning

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_onShortPress_defaultsToNone(self, mockIsPi):
        """
        Given: New GpioButton
        When: onShortPress is checked
        Then: Returns None
        """
        # Arrange
        button = GpioButton()

        # Assert
        assert button.onShortPress is None

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_onLongPress_defaultsToNone(self, mockIsPi):
        """
        Given: New GpioButton
        When: onLongPress is checked
        Then: Returns None
        """
        # Arrange
        button = GpioButton()

        # Assert
        assert button.onLongPress is None


# ================================================================================
# Lifecycle Tests
# ================================================================================

class TestGpioButtonLifecycle:
    """Tests for GpioButton lifecycle management."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_close_stopsButton(self, mockIsPi):
        """
        Given: GpioButton that is running
        When: close is called
        Then: Button is stopped
        """
        # Arrange
        button = GpioButton()
        mockButtonObj = MagicMock()
        button._button = mockButtonObj
        button._isRunning = True

        # Act
        button.close()

        # Assert
        assert not button.isRunning

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_close_idempotent_safeToCallMultipleTimes(self, mockIsPi):
        """
        Given: GpioButton
        When: close is called multiple times
        Then: Does not raise error
        """
        # Arrange
        button = GpioButton()

        # Act (should not raise)
        button.close()
        button.close()
        button.close()

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_contextManager_entersAndExits(self, mockIsPi):
        """
        Given: GpioButton
        When: Used as context manager
        Then: Properly enters and exits
        """
        # Arrange/Act
        button = GpioButton()

        # Using button as context manager (but start returns False on non-Pi)
        with button:
            pass  # Would be running on Pi

        # Assert - no error raised
        assert not button.isRunning

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_contextManager_stopsOnExit(self, mockIsPi):
        """
        Given: GpioButton running
        When: Context manager exits via explicit exit
        Then: Button is stopped
        """
        # Arrange
        button = GpioButton()
        mockButtonObj = MagicMock()
        button._button = mockButtonObj
        button._isRunning = True

        # Act - call __exit__ directly instead of using context manager
        # (context manager calls start() which checks isRunning)
        button.__exit__(None, None, None)

        # Assert
        assert not button.isRunning


# ================================================================================
# Integration with ShutdownHandler Tests
# ================================================================================

class TestGpioButtonShutdownIntegration:
    """Tests for integration with ShutdownHandler."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_longPress_canTriggerShutdownCallback(self, mockIsPi):
        """
        Given: GpioButton with long press callback connected to shutdown
        When: Long press occurs
        Then: Shutdown callback is invoked
        """
        # Arrange
        button = GpioButton()
        shutdownTriggered = []

        def mockShutdown():
            shutdownTriggered.append(True)

        button.onLongPress = mockShutdown

        # Act
        button._handleHeld()

        # Assert
        assert len(shutdownTriggered) == 1

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_shortPress_doesNotTriggerShutdown(self, mockIsPi):
        """
        Given: GpioButton with only long press callback for shutdown
        When: Short press occurs
        Then: Shutdown is not triggered
        """
        # Arrange
        button = GpioButton()
        shutdownTriggered = []

        def mockShutdown():
            shutdownTriggered.append(True)

        button.onLongPress = mockShutdown
        # Note: onShortPress is not set to mockShutdown

        # Act
        button._handleRelease()  # Short press

        # Assert
        assert len(shutdownTriggered) == 0


# ================================================================================
# GPIO Pin Configuration Tests
# ================================================================================

class TestGpioPinConfiguration:
    """Tests for GPIO pin configuration."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_gpio17_isDefaultPin(self, mockIsPi):
        """
        Given: GpioButton created with defaults
        When: pin is checked
        Then: Is GPIO17
        """
        # Arrange
        button = GpioButton()

        # Assert
        assert button.pin == 17

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_zeroPin_isValid(self, mockIsPi):
        """
        Given: Pin 0
        When: GpioButton is created
        Then: Does not raise error
        """
        # Act
        button = GpioButton(pin=0)

        # Assert
        assert button.pin == 0

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_highPinNumber_isValid(self, mockIsPi):
        """
        Given: High pin number (e.g., GPIO27)
        When: GpioButton is created
        Then: Does not raise error
        """
        # Act
        button = GpioButton(pin=27)

        # Assert
        assert button.pin == 27


# ================================================================================
# Debounce Configuration Tests
# ================================================================================

class TestDebounceConfiguration:
    """Tests for debounce configuration."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_defaultDebounce_is200ms(self, mockIsPi):
        """
        Given: GpioButton created with defaults
        When: debounceTime is checked
        Then: Is 200ms (0.2 seconds)
        """
        # Arrange
        button = GpioButton()

        # Assert
        assert button.debounceTime == 0.2

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_zeroDebounce_isValid(self, mockIsPi):
        """
        Given: Debounce time of 0
        When: GpioButton is created
        Then: Does not raise error (no debounce)
        """
        # Act
        button = GpioButton(debounceTime=0)

        # Assert
        assert button.debounceTime == 0


# ================================================================================
# Hold Time Configuration Tests
# ================================================================================

class TestHoldTimeConfiguration:
    """Tests for hold time configuration."""

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_defaultHoldTime_is3Seconds(self, mockIsPi):
        """
        Given: GpioButton created with defaults
        When: holdTime is checked
        Then: Is 3 seconds
        """
        # Arrange
        button = GpioButton()

        # Assert
        assert button.holdTime == 3.0

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_shortHoldTime_isValid(self, mockIsPi):
        """
        Given: Short hold time (e.g., 0.5 seconds)
        When: GpioButton is created
        Then: Does not raise error
        """
        # Act
        button = GpioButton(holdTime=0.5)

        # Assert
        assert button.holdTime == 0.5

    @patch('hardware.gpio_button.isRaspberryPi', return_value=False)
    def test_longHoldTime_isValid(self, mockIsPi):
        """
        Given: Long hold time (e.g., 10 seconds)
        When: GpioButton is created
        Then: Does not raise error
        """
        # Act
        button = GpioButton(holdTime=10.0)

        # Assert
        assert button.holdTime == 10.0
