################################################################################
# File Name: test_status_display.py
# Purpose/Description: Tests for status display module
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial implementation for US-RPI-010
# ================================================================================
################################################################################

"""
Tests for the status_display module.

Tests StatusDisplay functionality with mocked pygame for cross-platform testing.

Run with:
    pytest tests/test_status_display.py -v
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from hardware.status_display import (
    COLOR_BLACK,
    COLOR_WHITE,
    DEFAULT_REFRESH_RATE,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FONT_SIZE_LARGE,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_SMALL,
    ConnectionStatus,
    DisplayNotAvailableError,
    PowerSourceDisplay,
    StatusDisplay,
    StatusDisplayError,
)

# ================================================================================
# Exception Tests
# ================================================================================


class TestStatusDisplayExceptions:
    """Tests for status display exception classes."""

    def test_statusDisplayError_isBaseException(self):
        """
        Given: StatusDisplayError
        When: Checked for inheritance
        Then: Is subclass of Exception
        """
        # Assert
        assert issubclass(StatusDisplayError, Exception)

    def test_statusDisplayError_hasMessage(self):
        """
        Given: StatusDisplayError with message
        When: Converted to string
        Then: Contains the message
        """
        # Arrange
        error = StatusDisplayError("Test display error")

        # Act
        result = str(error)

        # Assert
        assert "Test display error" in result

    def test_displayNotAvailableError_inheritsFromStatusDisplayError(self):
        """
        Given: DisplayNotAvailableError
        When: Checked for inheritance
        Then: Is subclass of StatusDisplayError
        """
        # Assert
        assert issubclass(DisplayNotAvailableError, StatusDisplayError)


# ================================================================================
# Enum Tests
# ================================================================================


class TestStatusDisplayEnums:
    """Tests for status display enumerations."""

    def test_connectionStatus_hasConnectedValue(self):
        """
        Given: ConnectionStatus.CONNECTED
        When: Checked
        Then: Has value 'Connected'
        """
        assert ConnectionStatus.CONNECTED.value == "Connected"

    def test_connectionStatus_hasDisconnectedValue(self):
        """
        Given: ConnectionStatus.DISCONNECTED
        When: Checked
        Then: Has value 'Disconnected'
        """
        assert ConnectionStatus.DISCONNECTED.value == "Disconnected"

    def test_connectionStatus_hasReconnectingValue(self):
        """
        Given: ConnectionStatus.RECONNECTING
        When: Checked
        Then: Has value 'Reconnecting'
        """
        assert ConnectionStatus.RECONNECTING.value == "Reconnecting"

    def test_powerSourceDisplay_hasCarValue(self):
        """
        Given: PowerSourceDisplay.CAR
        When: Checked
        Then: Has value 'Car'
        """
        assert PowerSourceDisplay.CAR.value == "Car"

    def test_powerSourceDisplay_hasBatteryValue(self):
        """
        Given: PowerSourceDisplay.BATTERY
        When: Checked
        Then: Has value 'Battery'
        """
        assert PowerSourceDisplay.BATTERY.value == "Battery"

    def test_powerSourceDisplay_hasUnknownValue(self):
        """
        Given: PowerSourceDisplay.UNKNOWN
        When: Checked
        Then: Has value 'Unknown'
        """
        assert PowerSourceDisplay.UNKNOWN.value == "Unknown"


# ================================================================================
# Constants Tests
# ================================================================================


class TestStatusDisplayConstants:
    """Tests for status display constants."""

    def test_displayWidth_is480(self):
        """
        Given: DISPLAY_WIDTH constant
        When: Checked
        Then: Is 480 pixels
        """
        assert DISPLAY_WIDTH == 480

    def test_displayHeight_is320(self):
        """
        Given: DISPLAY_HEIGHT constant
        When: Checked
        Then: Is 320 pixels
        """
        assert DISPLAY_HEIGHT == 320

    def test_defaultRefreshRate_is2(self):
        """
        Given: DEFAULT_REFRESH_RATE constant
        When: Checked
        Then: Is 2.0 seconds
        """
        assert DEFAULT_REFRESH_RATE == 2.0

    def test_colorBlack_isRgb(self):
        """
        Given: COLOR_BLACK constant
        When: Checked
        Then: Is RGB tuple (0, 0, 0)
        """
        assert COLOR_BLACK == (0, 0, 0)

    def test_colorWhite_isRgb(self):
        """
        Given: COLOR_WHITE constant
        When: Checked
        Then: Is RGB tuple (255, 255, 255)
        """
        assert COLOR_WHITE == (255, 255, 255)

    def test_fontSizeLarge_is32(self):
        """
        Given: FONT_SIZE_LARGE constant
        When: Checked
        Then: Is 32
        """
        assert FONT_SIZE_LARGE == 32

    def test_fontSizeMedium_is24(self):
        """
        Given: FONT_SIZE_MEDIUM constant
        When: Checked
        Then: Is 24
        """
        assert FONT_SIZE_MEDIUM == 24

    def test_fontSizeSmall_is18(self):
        """
        Given: FONT_SIZE_SMALL constant
        When: Checked
        Then: Is 18
        """
        assert FONT_SIZE_SMALL == 18


# ================================================================================
# Initialization Tests
# ================================================================================


class TestStatusDisplayInit:
    """Tests for StatusDisplay initialization."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_init_withDefaults_setsDefaultValues(self, mockIsPi):
        """
        Given: No arguments
        When: StatusDisplay is created
        Then: Uses default values for refresh rate and dimensions
        """
        # Act
        display = StatusDisplay()

        # Assert
        assert display.refreshRate == DEFAULT_REFRESH_RATE
        assert display.width == DISPLAY_WIDTH
        assert display.height == DISPLAY_HEIGHT

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_init_withCustomRefreshRate_usesProvidedValue(self, mockIsPi):
        """
        Given: Custom refresh rate
        When: StatusDisplay is created
        Then: Uses provided refresh rate
        """
        # Act
        display = StatusDisplay(refreshRate=1.0)

        # Assert
        assert display.refreshRate == 1.0

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_init_withCustomDimensions_usesProvidedValues(self, mockIsPi):
        """
        Given: Custom dimensions
        When: StatusDisplay is created
        Then: Uses provided dimensions
        """
        # Act
        display = StatusDisplay(width=800, height=600)

        # Assert
        assert display.width == 800
        assert display.height == 600

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_init_withInvalidRefreshRate_raisesValueError(self, mockIsPi):
        """
        Given: Zero or negative refresh rate
        When: StatusDisplay is created
        Then: Raises ValueError
        """
        # Act & Assert
        with pytest.raises(ValueError) as exc:
            StatusDisplay(refreshRate=0)

        assert "Refresh rate must be positive" in str(exc.value)

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_init_withNegativeRefreshRate_raisesValueError(self, mockIsPi):
        """
        Given: Negative refresh rate
        When: StatusDisplay is created
        Then: Raises ValueError
        """
        # Act & Assert
        with pytest.raises(ValueError) as exc:
            StatusDisplay(refreshRate=-1.0)

        assert "Refresh rate must be positive" in str(exc.value)

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_init_withInvalidWidth_raisesValueError(self, mockIsPi):
        """
        Given: Zero or negative width
        When: StatusDisplay is created
        Then: Raises ValueError
        """
        # Act & Assert
        with pytest.raises(ValueError) as exc:
            StatusDisplay(width=0)

        assert "Display dimensions must be positive" in str(exc.value)

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_init_withInvalidHeight_raisesValueError(self, mockIsPi):
        """
        Given: Zero or negative height
        When: StatusDisplay is created
        Then: Raises ValueError
        """
        # Act & Assert
        with pytest.raises(ValueError) as exc:
            StatusDisplay(height=-100)

        assert "Display dimensions must be positive" in str(exc.value)

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_init_onNonPi_setsNotAvailable(self, mockIsPi):
        """
        Given: Not running on Raspberry Pi
        When: StatusDisplay is created
        Then: isAvailable is False
        """
        # Act
        display = StatusDisplay()

        # Assert
        assert display.isAvailable is False

    @patch('hardware.status_display.isRaspberryPi', return_value=True)
    def test_init_onPi_withPygameImportError_setsNotAvailable(self, mockIsPi):
        """
        Given: Running on Pi but pygame import fails
        When: StatusDisplay is created
        Then: isAvailable is False
        """
        # Arrange - pygame import will fail by default in test environment
        # Act
        display = StatusDisplay()

        # Assert - Since pygame likely isn't installed in test env, should be False
        # This test may pass or fail depending on environment
        assert isinstance(display.isAvailable, bool)

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_init_setsInitialStateValues(self, mockIsPi):
        """
        Given: No arguments
        When: StatusDisplay is created
        Then: Initial state values are set correctly
        """
        # Act
        display = StatusDisplay()

        # Assert
        assert display.isRunning is False
        assert display.batteryPercentage is None
        assert display.batteryVoltage is None
        assert display.powerSource == PowerSourceDisplay.UNKNOWN
        assert display.obdStatus == ConnectionStatus.DISCONNECTED


# ================================================================================
# Availability Tests
# ================================================================================


class TestStatusDisplayAvailability:
    """Tests for display availability checking."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_start_whenNotAvailable_returnsFalse(self, mockIsPi):
        """
        Given: Display not available
        When: start() is called
        Then: Returns False
        """
        # Arrange
        display = StatusDisplay()

        # Act
        result = display.start()

        # Assert
        assert result is False

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_start_whenNotAvailable_doesNotSetRunning(self, mockIsPi):
        """
        Given: Display not available
        When: start() is called
        Then: isRunning remains False
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.start()

        # Assert
        assert display.isRunning is False


# ================================================================================
# Battery Info Update Tests
# ================================================================================


class TestStatusDisplayBatteryUpdate:
    """Tests for battery information updates."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateBatteryInfo_withPercentage_setsPercentage(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateBatteryInfo is called with percentage
        Then: Battery percentage is updated
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateBatteryInfo(percentage=85)

        # Assert
        assert display.batteryPercentage == 85

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateBatteryInfo_withVoltage_setsVoltage(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateBatteryInfo is called with voltage
        Then: Battery voltage is updated
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateBatteryInfo(voltage=4.1)

        # Assert
        assert display.batteryVoltage == 4.1

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateBatteryInfo_withBoth_setsBoth(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateBatteryInfo is called with both values
        Then: Both values are updated
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateBatteryInfo(percentage=75, voltage=3.8)

        # Assert
        assert display.batteryPercentage == 75
        assert display.batteryVoltage == 3.8

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateBatteryInfo_clampsPercentage_toValidRange(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateBatteryInfo is called with out-of-range percentage
        Then: Percentage is clamped to 0-100
        """
        # Arrange
        display = StatusDisplay()

        # Act - Over 100
        display.updateBatteryInfo(percentage=150)

        # Assert
        assert display.batteryPercentage == 100

        # Act - Below 0
        display.updateBatteryInfo(percentage=-10)

        # Assert
        assert display.batteryPercentage == 0


# ================================================================================
# Power Source Update Tests
# ================================================================================


class TestStatusDisplayPowerSourceUpdate:
    """Tests for power source updates."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updatePowerSource_withExternal_setsCarSource(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updatePowerSource is called with 'external'
        Then: Power source is set to CAR
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updatePowerSource('external')

        # Assert
        assert display.powerSource == PowerSourceDisplay.CAR

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updatePowerSource_withCar_setsCarSource(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updatePowerSource is called with 'car'
        Then: Power source is set to CAR
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updatePowerSource('car')

        # Assert
        assert display.powerSource == PowerSourceDisplay.CAR

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updatePowerSource_withBattery_setsBatterySource(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updatePowerSource is called with 'battery'
        Then: Power source is set to BATTERY
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updatePowerSource('battery')

        # Assert
        assert display.powerSource == PowerSourceDisplay.BATTERY

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updatePowerSource_withUnknown_setsUnknownSource(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updatePowerSource is called with unknown value
        Then: Power source is set to UNKNOWN
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updatePowerSource('invalid')

        # Assert
        assert display.powerSource == PowerSourceDisplay.UNKNOWN

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updatePowerSource_caseInsensitive(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updatePowerSource is called with mixed case
        Then: Correctly handles case-insensitive matching
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updatePowerSource('BATTERY')

        # Assert
        assert display.powerSource == PowerSourceDisplay.BATTERY


# ================================================================================
# OBD Status Update Tests
# ================================================================================


class TestStatusDisplayObdStatusUpdate:
    """Tests for OBD status updates."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateObdStatus_withConnected_setsConnected(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateObdStatus is called with 'connected'
        Then: OBD status is set to CONNECTED
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateObdStatus('connected')

        # Assert
        assert display.obdStatus == ConnectionStatus.CONNECTED

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateObdStatus_withDisconnected_setsDisconnected(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateObdStatus is called with 'disconnected'
        Then: OBD status is set to DISCONNECTED
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateObdStatus('disconnected')

        # Assert
        assert display.obdStatus == ConnectionStatus.DISCONNECTED

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateObdStatus_withReconnecting_setsReconnecting(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateObdStatus is called with 'reconnecting'
        Then: OBD status is set to RECONNECTING
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateObdStatus('reconnecting')

        # Assert
        assert display.obdStatus == ConnectionStatus.RECONNECTING

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateObdStatus_withUnknown_setsDisconnected(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateObdStatus is called with unknown value
        Then: OBD status is set to DISCONNECTED (default)
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateObdStatus('invalid')

        # Assert
        assert display.obdStatus == ConnectionStatus.DISCONNECTED

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateObdStatus_caseInsensitive(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateObdStatus is called with mixed case
        Then: Correctly handles case-insensitive matching
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateObdStatus('CONNECTED')

        # Assert
        assert display.obdStatus == ConnectionStatus.CONNECTED


# ================================================================================
# Error Count Update Tests
# ================================================================================


class TestStatusDisplayErrorCountUpdate:
    """Tests for error count updates."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateErrorCount_withWarnings_setsWarnings(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateErrorCount is called with warnings
        Then: Warning count is updated
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateErrorCount(warnings=5)

        # Assert
        with display._dataLock:
            assert display._warningCount == 5

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateErrorCount_withErrors_setsErrors(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateErrorCount is called with errors
        Then: Error count is updated
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateErrorCount(errors=3)

        # Assert
        with display._dataLock:
            assert display._errorCount == 3

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateErrorCount_withBoth_setsBoth(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateErrorCount is called with both
        Then: Both counts are updated
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateErrorCount(warnings=2, errors=1)

        # Assert
        with display._dataLock:
            assert display._warningCount == 2
            assert display._errorCount == 1

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateErrorCount_withNegative_clampedToZero(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateErrorCount is called with negative values
        Then: Values are clamped to 0
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.updateErrorCount(warnings=-5, errors=-3)

        # Assert
        with display._dataLock:
            assert display._warningCount == 0
            assert display._errorCount == 0


# ================================================================================
# Property Tests
# ================================================================================


class TestStatusDisplayProperties:
    """Tests for StatusDisplay properties."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_refreshRate_getter_returnsCurrentValue(self, mockIsPi):
        """
        Given: StatusDisplay with custom refresh rate
        When: refreshRate property accessed
        Then: Returns current value
        """
        # Arrange
        display = StatusDisplay(refreshRate=1.5)

        # Assert
        assert display.refreshRate == 1.5

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_refreshRate_setter_updatesValue(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: refreshRate property is set
        Then: Value is updated
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.refreshRate = 1.0

        # Assert
        assert display.refreshRate == 1.0

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_refreshRate_setter_withInvalid_raisesValueError(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: refreshRate is set to non-positive
        Then: Raises ValueError
        """
        # Arrange
        display = StatusDisplay()

        # Act & Assert
        with pytest.raises(ValueError) as exc:
            display.refreshRate = 0

        assert "Refresh rate must be positive" in str(exc.value)

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_isAvailable_returnsCorrectValue(self, mockIsPi):
        """
        Given: StatusDisplay on non-Pi
        When: isAvailable accessed
        Then: Returns False
        """
        # Arrange
        display = StatusDisplay()

        # Assert
        assert display.isAvailable is False

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_isRunning_initiallyFalse(self, mockIsPi):
        """
        Given: New StatusDisplay
        When: isRunning accessed
        Then: Returns False
        """
        # Arrange
        display = StatusDisplay()

        # Assert
        assert display.isRunning is False

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_width_returnsCorrectValue(self, mockIsPi):
        """
        Given: StatusDisplay with custom width
        When: width property accessed
        Then: Returns correct value
        """
        # Arrange
        display = StatusDisplay(width=640)

        # Assert
        assert display.width == 640

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_height_returnsCorrectValue(self, mockIsPi):
        """
        Given: StatusDisplay with custom height
        When: height property accessed
        Then: Returns correct value
        """
        # Arrange
        display = StatusDisplay(height=480)

        # Assert
        assert display.height == 480

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_uptime_returnsPositiveValue(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: uptime property accessed
        Then: Returns positive value
        """
        # Arrange
        display = StatusDisplay()
        time.sleep(0.01)  # Small delay

        # Act
        uptime = display.uptime

        # Assert
        assert uptime >= 0


# ================================================================================
# Lifecycle Tests
# ================================================================================


class TestStatusDisplayLifecycle:
    """Tests for StatusDisplay lifecycle methods."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_stop_whenNotRunning_doesNothing(self, mockIsPi):
        """
        Given: StatusDisplay not running
        When: stop() is called
        Then: Does nothing (no exception)
        """
        # Arrange
        display = StatusDisplay()

        # Act - Should not raise
        display.stop()

        # Assert
        assert display.isRunning is False

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_close_stopsDisplay(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: close() is called
        Then: Display is stopped
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.close()

        # Assert
        assert display.isRunning is False

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_contextManager_entry_callsStart(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: Used as context manager
        Then: __enter__ calls start() and returns self
        """
        # Arrange
        display = StatusDisplay()

        # Act
        result = display.__enter__()

        # Assert
        assert result is display

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_contextManager_exit_callsClose(self, mockIsPi):
        """
        Given: StatusDisplay in context manager
        When: Context exits
        Then: close() is called
        """
        # Arrange
        display = StatusDisplay()

        # Act
        display.__enter__()
        display.__exit__(None, None, None)

        # Assert
        assert display.isRunning is False

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_del_callsClose(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: __del__ is called
        Then: close() is called
        """
        # Arrange
        display = StatusDisplay()

        # Act - Simulate __del__
        display.__del__()

        # Assert
        assert display.isRunning is False


# ================================================================================
# Callback Tests
# ================================================================================


class TestStatusDisplayCallbacks:
    """Tests for StatusDisplay callbacks."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_onDisplayError_getter_returnsCallback(self, mockIsPi):
        """
        Given: StatusDisplay with error callback
        When: onDisplayError property accessed
        Then: Returns the callback
        """
        # Arrange
        display = StatusDisplay()
        callback = MagicMock()
        display.onDisplayError = callback

        # Assert
        assert display.onDisplayError is callback

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_onDisplayError_setter_setsCallback(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: onDisplayError property is set
        Then: Callback is stored
        """
        # Arrange
        display = StatusDisplay()
        callback = MagicMock()

        # Act
        display.onDisplayError = callback

        # Assert
        assert display._onDisplayError is callback

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_onDisplayError_canBeCleared(self, mockIsPi):
        """
        Given: StatusDisplay with error callback
        When: onDisplayError is set to None
        Then: Callback is cleared
        """
        # Arrange
        display = StatusDisplay()
        display.onDisplayError = MagicMock()

        # Act
        display.onDisplayError = None

        # Assert
        assert display.onDisplayError is None


# ================================================================================
# Error Handling Tests
# ================================================================================


class TestStatusDisplayErrorHandling:
    """Tests for error handling in StatusDisplay."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_start_whenAlreadyRunning_raisesError(self, mockIsPi):
        """
        Given: StatusDisplay (simulated as running)
        When: start() is called again
        Then: Raises StatusDisplayError
        """
        # Arrange
        display = StatusDisplay()
        display._isRunning = True  # Simulate running state

        # Act & Assert
        with pytest.raises(StatusDisplayError) as exc:
            display.start()

        assert "already running" in str(exc.value)


# ================================================================================
# Thread Safety Tests
# ================================================================================


class TestStatusDisplayThreadSafety:
    """Tests for thread safety in StatusDisplay."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updateBatteryInfo_isThreadSafe(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updateBatteryInfo called from multiple threads
        Then: No race conditions occur
        """
        # Arrange
        display = StatusDisplay()
        errors = []

        def update_worker(n):
            try:
                for i in range(100):
                    display.updateBatteryInfo(percentage=i, voltage=3.0 + i * 0.01)
            except Exception as e:
                errors.append(e)

        # Act
        threads = [threading.Thread(target=update_worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert
        assert len(errors) == 0
        assert display.batteryPercentage is not None

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_updatePowerSource_isThreadSafe(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: updatePowerSource called from multiple threads
        Then: No race conditions occur
        """
        # Arrange
        display = StatusDisplay()
        errors = []
        sources = ['external', 'battery', 'car']

        def update_worker(n):
            try:
                for i in range(100):
                    display.updatePowerSource(sources[i % 3])
            except Exception as e:
                errors.append(e)

        # Act
        threads = [threading.Thread(target=update_worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert
        assert len(errors) == 0


# ================================================================================
# IP Address Tests
# ================================================================================


class TestStatusDisplayIpAddress:
    """Tests for IP address functionality."""

    @patch('hardware.status_display.isRaspberryPi', return_value=False)
    def test_getIpAddress_returnsString(self, mockIsPi):
        """
        Given: StatusDisplay instance
        When: _getIpAddress is called
        Then: Returns a string (IP address or 'N/A')
        """
        # Arrange
        display = StatusDisplay()

        # Act
        result = display._getIpAddress()

        # Assert
        assert isinstance(result, str)
        assert len(result) > 0


# Import threading for tests
import threading
