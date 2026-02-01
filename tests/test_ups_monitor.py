################################################################################
# File Name: test_ups_monitor.py
# Purpose/Description: Tests for UPS telemetry monitor
# Author: Ralph Agent
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Ralph Agent  | Initial implementation for US-RPI-006
# ================================================================================
################################################################################

"""
Tests for the ups_monitor module.

Tests UPS monitoring functionality with mocked I2C client for cross-platform testing.

Run with:
    pytest tests/test_ups_monitor.py -v
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from hardware.i2c_client import (
    I2cClient,
    I2cCommunicationError,
    I2cDeviceNotFoundError,
    I2cNotAvailableError,
)
from hardware.ups_monitor import (
    DEFAULT_I2C_BUS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_UPS_ADDRESS,
    REGISTER_CURRENT,
    REGISTER_PERCENTAGE,
    REGISTER_POWER_SOURCE,
    REGISTER_VOLTAGE,
    PowerSource,
    UpsMonitor,
    UpsMonitorError,
    UpsNotAvailableError,
)

# ================================================================================
# Exception Tests
# ================================================================================

class TestUpsExceptions:
    """Tests for UPS exception classes."""

    def test_upsMonitorError_isBaseException(self):
        """
        Given: UpsMonitorError
        When: Checked for inheritance
        Then: Is subclass of Exception
        """
        # Assert
        assert issubclass(UpsMonitorError, Exception)

    def test_upsNotAvailableError_isSubclassOfUpsMonitorError(self):
        """
        Given: UpsNotAvailableError
        When: Checked for inheritance
        Then: Is subclass of UpsMonitorError
        """
        # Assert
        assert issubclass(UpsNotAvailableError, UpsMonitorError)

    def test_upsMonitorError_hasMessage(self):
        """
        Given: UpsMonitorError with message
        When: Converted to string
        Then: Contains the message
        """
        # Arrange
        error = UpsMonitorError("Test error message")

        # Act
        result = str(error)

        # Assert
        assert "Test error message" in result

    def test_upsNotAvailableError_hasMessage(self):
        """
        Given: UpsNotAvailableError with message
        When: Converted to string
        Then: Contains the message
        """
        # Arrange
        error = UpsNotAvailableError("UPS not found")

        # Act
        result = str(error)

        # Assert
        assert "UPS not found" in result


# ================================================================================
# PowerSource Enum Tests
# ================================================================================

class TestPowerSource:
    """Tests for PowerSource enumeration."""

    def test_external_hasCorrectValue(self):
        """
        Given: PowerSource.EXTERNAL
        When: Checked for value
        Then: Has value 'external'
        """
        assert PowerSource.EXTERNAL.value == "external"

    def test_battery_hasCorrectValue(self):
        """
        Given: PowerSource.BATTERY
        When: Checked for value
        Then: Has value 'battery'
        """
        assert PowerSource.BATTERY.value == "battery"

    def test_unknown_hasCorrectValue(self):
        """
        Given: PowerSource.UNKNOWN
        When: Checked for value
        Then: Has value 'unknown'
        """
        assert PowerSource.UNKNOWN.value == "unknown"


# ================================================================================
# UPS Monitor Constants Tests
# ================================================================================

class TestUpsConstants:
    """Tests for UPS module constants."""

    def test_registerVoltage_is0x02(self):
        """
        Given: REGISTER_VOLTAGE constant
        When: Checked
        Then: Is 0x02
        """
        assert REGISTER_VOLTAGE == 0x02

    def test_registerCurrent_is0x04(self):
        """
        Given: REGISTER_CURRENT constant
        When: Checked
        Then: Is 0x04
        """
        assert REGISTER_CURRENT == 0x04

    def test_registerPercentage_is0x06(self):
        """
        Given: REGISTER_PERCENTAGE constant
        When: Checked
        Then: Is 0x06
        """
        assert REGISTER_PERCENTAGE == 0x06

    def test_registerPowerSource_is0x08(self):
        """
        Given: REGISTER_POWER_SOURCE constant
        When: Checked
        Then: Is 0x08
        """
        assert REGISTER_POWER_SOURCE == 0x08

    def test_defaultUpsAddress_is0x36(self):
        """
        Given: DEFAULT_UPS_ADDRESS constant
        When: Checked
        Then: Is 0x36
        """
        assert DEFAULT_UPS_ADDRESS == 0x36

    def test_defaultI2cBus_is1(self):
        """
        Given: DEFAULT_I2C_BUS constant
        When: Checked
        Then: Is 1
        """
        assert DEFAULT_I2C_BUS == 1

    def test_defaultPollInterval_is5(self):
        """
        Given: DEFAULT_POLL_INTERVAL constant
        When: Checked
        Then: Is 5.0 seconds
        """
        assert DEFAULT_POLL_INTERVAL == 5.0


# ================================================================================
# UPS Monitor Initialization Tests
# ================================================================================

class TestUpsMonitorInitialization:
    """Tests for UpsMonitor initialization."""

    def test_init_withDefaults_storesDefaults(self):
        """
        Given: UpsMonitor created without arguments
        When: Initialized with mock I2C client
        Then: Stores default configuration
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)

        # Act
        monitor = UpsMonitor(i2cClient=mockClient)

        # Assert
        assert monitor.address == DEFAULT_UPS_ADDRESS
        assert monitor.bus == DEFAULT_I2C_BUS
        assert monitor.pollInterval == DEFAULT_POLL_INTERVAL
        assert monitor.onPowerSourceChange is None
        assert monitor.isPolling is False

    def test_init_withCustomConfig_storesCustomConfig(self):
        """
        Given: UpsMonitor created with custom config
        When: Initialized with mock I2C client
        Then: Stores custom configuration
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)

        # Act
        monitor = UpsMonitor(
            address=0x57,
            bus=2,
            pollInterval=10.0,
            i2cClient=mockClient
        )

        # Assert
        assert monitor.address == 0x57
        assert monitor.bus == 2
        assert monitor.pollInterval == 10.0

    def test_init_notRaspberryPi_lazyFailure(self):
        """
        Given: Not running on Raspberry Pi
        When: UpsMonitor created without i2cClient
        Then: Fails lazily when I2C is accessed
        """
        # Arrange & Act - Constructor should not fail
        with patch('hardware.ups_monitor.isRaspberryPi', return_value=False):
            monitor = UpsMonitor()

            # Assert - Should fail on first use
            with pytest.raises(UpsNotAvailableError) as excInfo:
                monitor.getBatteryVoltage()

            assert "not running on Raspberry Pi" in str(excInfo.value)


# ================================================================================
# UPS Monitor Battery Voltage Tests
# ================================================================================

class TestUpsMonitorBatteryVoltage:
    """Tests for getBatteryVoltage method."""

    def test_getBatteryVoltage_success_returnsVolts(self):
        """
        Given: UPS returns valid voltage reading
        When: getBatteryVoltage is called
        Then: Returns voltage in volts
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.return_value = 3700  # 3.7V in mV

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryVoltage()

        # Assert
        assert result == 3.7
        mockClient.readWord.assert_called_once_with(0x36, REGISTER_VOLTAGE)

    def test_getBatteryVoltage_highVoltage_returnsCorrectValue(self):
        """
        Given: UPS returns high voltage reading
        When: getBatteryVoltage is called
        Then: Returns correct voltage in volts
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.return_value = 4200  # 4.2V in mV (full charge)

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryVoltage()

        # Assert
        assert result == 4.2

    def test_getBatteryVoltage_lowVoltage_returnsCorrectValue(self):
        """
        Given: UPS returns low voltage reading
        When: getBatteryVoltage is called
        Then: Returns correct voltage in volts
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.return_value = 3000  # 3.0V in mV (low battery)

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryVoltage()

        # Assert
        assert result == 3.0

    def test_getBatteryVoltage_deviceNotFound_raisesUpsNotAvailable(self):
        """
        Given: UPS device not found
        When: getBatteryVoltage is called
        Then: Raises UpsNotAvailableError
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.side_effect = I2cDeviceNotFoundError(
            "No device", address=0x36, register=0x02
        )

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act & Assert
        with pytest.raises(UpsNotAvailableError) as excInfo:
            monitor.getBatteryVoltage()

        assert "0x36" in str(excInfo.value)

    def test_getBatteryVoltage_communicationError_raisesUpsMonitorError(self):
        """
        Given: I2C communication error
        When: getBatteryVoltage is called
        Then: Raises UpsMonitorError
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.side_effect = I2cCommunicationError(
            "Bus error", address=0x36, register=0x02
        )

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act & Assert
        with pytest.raises(UpsMonitorError):
            monitor.getBatteryVoltage()


# ================================================================================
# UPS Monitor Battery Current Tests
# ================================================================================

class TestUpsMonitorBatteryCurrent:
    """Tests for getBatteryCurrent method."""

    def test_getBatteryCurrent_charging_returnsPositive(self):
        """
        Given: UPS is charging (positive current)
        When: getBatteryCurrent is called
        Then: Returns positive mA value
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.return_value = 500  # +500mA charging

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryCurrent()

        # Assert
        assert result == 500.0
        mockClient.readWord.assert_called_once_with(0x36, REGISTER_CURRENT)

    def test_getBatteryCurrent_discharging_returnsNegative(self):
        """
        Given: UPS is discharging (negative current)
        When: getBatteryCurrent is called
        Then: Returns negative mA value (signed 16-bit conversion)
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        # -300mA as unsigned 16-bit: 65536 - 300 = 65236
        mockClient.readWord.return_value = 65236

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryCurrent()

        # Assert
        assert result == -300.0

    def test_getBatteryCurrent_zeroCurrent_returnsZero(self):
        """
        Given: UPS has zero current
        When: getBatteryCurrent is called
        Then: Returns zero
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.return_value = 0

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryCurrent()

        # Assert
        assert result == 0.0

    def test_getBatteryCurrent_deviceNotFound_raisesUpsNotAvailable(self):
        """
        Given: UPS device not found
        When: getBatteryCurrent is called
        Then: Raises UpsNotAvailableError
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.side_effect = I2cDeviceNotFoundError(
            "No device", address=0x36, register=0x04
        )

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act & Assert
        with pytest.raises(UpsNotAvailableError):
            monitor.getBatteryCurrent()


# ================================================================================
# UPS Monitor Battery Percentage Tests
# ================================================================================

class TestUpsMonitorBatteryPercentage:
    """Tests for getBatteryPercentage method."""

    def test_getBatteryPercentage_success_returnsPercentage(self):
        """
        Given: UPS returns valid percentage
        When: getBatteryPercentage is called
        Then: Returns percentage as int
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 75

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryPercentage()

        # Assert
        assert result == 75
        assert isinstance(result, int)
        mockClient.readByte.assert_called_once_with(0x36, REGISTER_PERCENTAGE)

    def test_getBatteryPercentage_fullBattery_returns100(self):
        """
        Given: UPS shows full battery
        When: getBatteryPercentage is called
        Then: Returns 100
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 100

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryPercentage()

        # Assert
        assert result == 100

    def test_getBatteryPercentage_emptyBattery_returnsZero(self):
        """
        Given: UPS shows empty battery
        When: getBatteryPercentage is called
        Then: Returns 0
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 0

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryPercentage()

        # Assert
        assert result == 0

    def test_getBatteryPercentage_overRange_clampedTo100(self):
        """
        Given: UPS returns value over 100
        When: getBatteryPercentage is called
        Then: Returns clamped value (100)
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 150  # Invalid high value

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getBatteryPercentage()

        # Assert
        assert result == 100

    def test_getBatteryPercentage_deviceNotFound_raisesUpsNotAvailable(self):
        """
        Given: UPS device not found
        When: getBatteryPercentage is called
        Then: Raises UpsNotAvailableError
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.side_effect = I2cDeviceNotFoundError(
            "No device", address=0x36, register=0x06
        )

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act & Assert
        with pytest.raises(UpsNotAvailableError):
            monitor.getBatteryPercentage()


# ================================================================================
# UPS Monitor Power Source Tests
# ================================================================================

class TestUpsMonitorPowerSource:
    """Tests for getPowerSource method."""

    def test_getPowerSource_external_returnsExternal(self):
        """
        Given: UPS on external power
        When: getPowerSource is called
        Then: Returns PowerSource.EXTERNAL
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 0  # External power

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getPowerSource()

        # Assert
        assert result == PowerSource.EXTERNAL
        mockClient.readByte.assert_called_once_with(0x36, REGISTER_POWER_SOURCE)

    def test_getPowerSource_battery_returnsBattery(self):
        """
        Given: UPS on battery power
        When: getPowerSource is called
        Then: Returns PowerSource.BATTERY
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 1  # Battery power

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getPowerSource()

        # Assert
        assert result == PowerSource.BATTERY

    def test_getPowerSource_unknownValue_returnsUnknown(self):
        """
        Given: UPS returns unexpected value
        When: getPowerSource is called
        Then: Returns PowerSource.UNKNOWN
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 99  # Unknown value

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getPowerSource()

        # Assert
        assert result == PowerSource.UNKNOWN

    def test_getPowerSource_deviceNotFound_raisesUpsNotAvailable(self):
        """
        Given: UPS device not found
        When: getPowerSource is called
        Then: Raises UpsNotAvailableError
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.side_effect = I2cDeviceNotFoundError(
            "No device", address=0x36, register=0x08
        )

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act & Assert
        with pytest.raises(UpsNotAvailableError):
            monitor.getPowerSource()


# ================================================================================
# UPS Monitor Telemetry Tests
# ================================================================================

class TestUpsMonitorTelemetry:
    """Tests for getTelemetry method."""

    def test_getTelemetry_success_returnsAllValues(self):
        """
        Given: UPS returns all telemetry values
        When: getTelemetry is called
        Then: Returns dict with all telemetry
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.side_effect = [3700, 500]  # voltage, current
        mockClient.readByte.side_effect = [75, 0]  # percentage, power source

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.getTelemetry()

        # Assert
        assert result['voltage'] == 3.7
        assert result['current'] == 500.0
        assert result['percentage'] == 75
        assert result['powerSource'] == PowerSource.EXTERNAL

    def test_getTelemetry_readsAllRegisters(self):
        """
        Given: UPS monitor
        When: getTelemetry is called
        Then: Reads all four registers
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readWord.return_value = 3700
        mockClient.readByte.return_value = 75

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        monitor.getTelemetry()

        # Assert - Should call readWord twice and readByte twice
        assert mockClient.readWord.call_count == 2
        assert mockClient.readByte.call_count == 2


# ================================================================================
# UPS Monitor Polling Tests
# ================================================================================

class TestUpsMonitorPolling:
    """Tests for polling functionality."""

    def test_startPolling_startsBackgroundThread(self):
        """
        Given: UPS monitor not polling
        When: startPolling is called
        Then: Starts background polling thread
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 0  # External power

        monitor = UpsMonitor(i2cClient=mockClient, pollInterval=0.1)

        # Act
        monitor.startPolling()

        try:
            # Assert
            assert monitor.isPolling is True
            assert monitor._pollingThread is not None
            assert monitor._pollingThread.is_alive()
        finally:
            # Cleanup
            monitor.stopPolling()

    def test_startPolling_alreadyPolling_raisesRuntimeError(self):
        """
        Given: UPS monitor already polling
        When: startPolling is called again
        Then: Raises RuntimeError
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 0

        monitor = UpsMonitor(i2cClient=mockClient, pollInterval=0.1)
        monitor.startPolling()

        try:
            # Act & Assert
            with pytest.raises(RuntimeError) as excInfo:
                monitor.startPolling()

            assert "already running" in str(excInfo.value)
        finally:
            # Cleanup
            monitor.stopPolling()

    def test_startPolling_withCustomInterval_usesCustomInterval(self):
        """
        Given: UPS monitor
        When: startPolling is called with custom interval
        Then: Uses the custom interval
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 0

        monitor = UpsMonitor(i2cClient=mockClient, pollInterval=5.0)

        # Act
        monitor.startPolling(interval=0.1)

        try:
            # Assert
            assert monitor.pollInterval == 0.1
        finally:
            # Cleanup
            monitor.stopPolling()

    def test_stopPolling_stopsPolling(self):
        """
        Given: UPS monitor is polling
        When: stopPolling is called
        Then: Stops the polling thread
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 0

        monitor = UpsMonitor(i2cClient=mockClient, pollInterval=0.1)
        monitor.startPolling()

        # Act
        monitor.stopPolling()

        # Assert
        assert monitor.isPolling is False

    def test_stopPolling_notPolling_safeToCall(self):
        """
        Given: UPS monitor not polling
        When: stopPolling is called
        Then: Does not raise error
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)

        monitor = UpsMonitor(i2cClient=mockClient)

        # Act & Assert - Should not raise
        monitor.stopPolling()
        assert monitor.isPolling is False


# ================================================================================
# UPS Monitor Callback Tests
# ================================================================================

class TestUpsMonitorCallback:
    """Tests for power source change callback."""

    def test_callback_powerSourceChange_callbackInvoked(self):
        """
        Given: UPS monitor with callback registered
        When: Power source changes during polling
        Then: Callback is invoked with old and new source
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        # First call returns external, second returns battery
        mockClient.readByte.side_effect = [0, 0, 1, 1]  # getPowerSource reads 0x08

        callbackResults = []

        def onPowerChange(oldSource, newSource):
            callbackResults.append((oldSource, newSource))

        monitor = UpsMonitor(i2cClient=mockClient, pollInterval=0.05)
        monitor.onPowerSourceChange = onPowerChange

        # Act
        monitor.startPolling()
        time.sleep(0.2)  # Allow time for polling to detect change
        monitor.stopPolling()

        # Assert - Should have detected change from external to battery
        assert len(callbackResults) >= 1
        assert callbackResults[0] == (PowerSource.EXTERNAL, PowerSource.BATTERY)

    def test_callback_noPowerSourceChange_callbackNotInvoked(self):
        """
        Given: UPS monitor with callback registered
        When: Power source does not change during polling
        Then: Callback is not invoked
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 0  # Always external

        callbackResults = []

        def onPowerChange(oldSource, newSource):
            callbackResults.append((oldSource, newSource))

        monitor = UpsMonitor(i2cClient=mockClient, pollInterval=0.05)
        monitor.onPowerSourceChange = onPowerChange

        # Act
        monitor.startPolling()
        time.sleep(0.15)  # Allow time for a few polls
        monitor.stopPolling()

        # Assert - No change detected
        assert len(callbackResults) == 0

    def test_callback_exceptionInCallback_doesNotCrash(self):
        """
        Given: UPS monitor with callback that raises exception
        When: Power source changes
        Then: Polling continues without crashing
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        # First external, then battery
        mockClient.readByte.side_effect = [0, 0, 1, 1, 1]

        def onPowerChange(oldSource, newSource):
            raise ValueError("Callback error")

        monitor = UpsMonitor(i2cClient=mockClient, pollInterval=0.05)
        monitor.onPowerSourceChange = onPowerChange

        # Act - Should not raise
        monitor.startPolling()
        time.sleep(0.15)
        monitor.stopPolling()

        # Assert - Monitor should still be functional
        assert monitor._pollingThread is None or not monitor._pollingThread.is_alive()


# ================================================================================
# UPS Monitor Properties Tests
# ================================================================================

class TestUpsMonitorProperties:
    """Tests for UpsMonitor properties."""

    def test_address_returnsConfiguredAddress(self):
        """
        Given: UpsMonitor with custom address
        When: address property is accessed
        Then: Returns the configured address
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        monitor = UpsMonitor(address=0x57, i2cClient=mockClient)

        # Act
        result = monitor.address

        # Assert
        assert result == 0x57

    def test_bus_returnsConfiguredBus(self):
        """
        Given: UpsMonitor with custom bus
        When: bus property is accessed
        Then: Returns the configured bus
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        monitor = UpsMonitor(bus=2, i2cClient=mockClient)

        # Act
        result = monitor.bus

        # Assert
        assert result == 2

    def test_pollInterval_returnsConfiguredInterval(self):
        """
        Given: UpsMonitor with custom poll interval
        When: pollInterval property is accessed
        Then: Returns the configured interval
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        monitor = UpsMonitor(pollInterval=10.0, i2cClient=mockClient)

        # Act
        result = monitor.pollInterval

        # Assert
        assert result == 10.0

    def test_pollInterval_setter_updatesInterval(self):
        """
        Given: UpsMonitor
        When: pollInterval property is set
        Then: Updates the interval
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        monitor.pollInterval = 15.0

        # Assert
        assert monitor.pollInterval == 15.0

    def test_pollInterval_invalidValue_raisesValueError(self):
        """
        Given: UpsMonitor
        When: pollInterval is set to invalid value
        Then: Raises ValueError
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        monitor = UpsMonitor(i2cClient=mockClient)

        # Act & Assert
        with pytest.raises(ValueError):
            monitor.pollInterval = 0

        with pytest.raises(ValueError):
            monitor.pollInterval = -1

    def test_isPolling_returnsFalseWhenNotPolling(self):
        """
        Given: UpsMonitor not polling
        When: isPolling property is accessed
        Then: Returns False
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        monitor = UpsMonitor(i2cClient=mockClient)

        # Act
        result = monitor.isPolling

        # Assert
        assert result is False


# ================================================================================
# UPS Monitor Lifecycle Tests
# ================================================================================

class TestUpsMonitorLifecycle:
    """Tests for UpsMonitor lifecycle management."""

    def test_close_stopsPolling(self):
        """
        Given: UpsMonitor is polling
        When: close is called
        Then: Stops polling
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 0

        monitor = UpsMonitor(i2cClient=mockClient, pollInterval=0.1)
        monitor.startPolling()

        # Act
        monitor.close()

        # Assert
        assert monitor.isPolling is False

    def test_close_closesOwnedClient(self):
        """
        Given: UpsMonitor that created its own I2C client
        When: close is called
        Then: Closes the I2C client
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)

        # Simulate creating with our own client (owned)
        monitor = UpsMonitor(i2cClient=mockClient)
        monitor._clientOwned = True

        # Act
        monitor.close()

        # Assert
        mockClient.close.assert_called_once()

    def test_close_doesNotCloseProvidedClient(self):
        """
        Given: UpsMonitor with provided I2C client
        When: close is called
        Then: Does not close the provided client
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        monitor = UpsMonitor(i2cClient=mockClient)

        # Verify we don't own the client
        assert monitor._clientOwned is False

        # Act
        monitor.close()

        # Assert
        mockClient.close.assert_not_called()

    def test_contextManager_closesOnExit(self):
        """
        Given: UpsMonitor used as context manager
        When: Exiting the context
        Then: Closes the monitor
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        mockClient.readByte.return_value = 0

        # Act
        with UpsMonitor(i2cClient=mockClient, pollInterval=0.1) as monitor:
            monitor.startPolling()
            assert monitor.isPolling is True

        # Assert - After context exit
        assert monitor.isPolling is False

    def test_contextManager_returnsMonitor(self):
        """
        Given: UpsMonitor used as context manager
        When: Entering the context
        Then: Returns the monitor instance
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)

        # Act
        with UpsMonitor(i2cClient=mockClient) as monitor:
            # Assert
            assert isinstance(monitor, UpsMonitor)


# ================================================================================
# UPS Monitor Error Handling Tests
# ================================================================================

class TestUpsMonitorErrorHandling:
    """Tests for UPS monitor error handling."""

    def test_pollingLoop_handlesCommunicationError(self):
        """
        Given: UPS monitor polling with communication errors
        When: I2C error occurs during polling
        Then: Continues polling without crashing
        """
        # Arrange
        mockClient = MagicMock(spec=I2cClient)
        callCount = [0]

        def readByteSideEffect(addr, reg):
            callCount[0] += 1
            if callCount[0] == 2:
                raise I2cCommunicationError("Bus error", address=addr, register=reg)
            return 0

        mockClient.readByte.side_effect = readByteSideEffect

        monitor = UpsMonitor(i2cClient=mockClient, pollInterval=0.05)

        # Act
        monitor.startPolling()
        time.sleep(0.15)  # Allow multiple polls
        monitor.stopPolling()

        # Assert - Should have polled multiple times despite error
        assert callCount[0] >= 2

    def test_getClient_i2cNotAvailable_raisesUpsNotAvailable(self):
        """
        Given: UPS monitor without pre-configured client
        When: I2C is not available
        Then: Raises UpsNotAvailableError
        """
        # Arrange
        with patch('hardware.ups_monitor.isRaspberryPi', return_value=True):
            with patch('hardware.ups_monitor.I2cClient') as mockI2cClient:
                mockI2cClient.side_effect = I2cNotAvailableError("I2C not available")

                monitor = UpsMonitor()

                # Act & Assert
                with pytest.raises(UpsNotAvailableError):
                    monitor.getBatteryVoltage()
