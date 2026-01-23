################################################################################
# File Name: readers.py
# Purpose/Description: Voltage reader factory functions for power monitoring
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-012
# ================================================================================
################################################################################
"""
Voltage reader factory functions for power monitoring.

This module provides factory functions to create voltage reader functions
for different hardware configurations:
- GPIO ADC readers for battery voltage monitoring
- GPIO power status readers for AC/battery detection
- I2C power status readers for power management HATs

Usage:
    # Create ADC voltage reader
    reader = createAdcVoltageReader(
        adcChannel=0,
        referenceVoltage=3.3,
        voltageDividerRatio=5.0,
        adcReadFunction=readAdcChannel
    )
    batteryMonitor.setVoltageReader(reader)

    # Create GPIO power status reader
    reader = createGpioPowerStatusReader(
        gpioPin=17,
        activeHigh=True,
        gpioReadFunction=GPIO.input
    )
    powerMonitor.setPowerStatusReader(reader)
"""

from typing import Callable, Optional

from .exceptions import BatteryConfigurationError, PowerConfigurationError


# ================================================================================
# Battery Voltage Readers
# ================================================================================

def createAdcVoltageReader(
    adcChannel: int = 0,
    referenceVoltage: float = 3.3,
    maxAdcValue: int = 4095,
    voltageDividerRatio: float = 5.0,
    adcReadFunction: Optional[Callable[[int], int]] = None,
) -> Callable[[], float]:
    """
    Create a voltage reader function for ADC-based voltage measurement.

    This is a helper to create a voltage reader for GPIO ADC setups.
    The actual ADC read function must be provided based on your hardware
    (e.g., MCP3008, ADS1115, etc.).

    Args:
        adcChannel: ADC channel to read from
        referenceVoltage: ADC reference voltage (usually 3.3V or 5V)
        maxAdcValue: Maximum ADC value (4095 for 12-bit, 65535 for 16-bit)
        voltageDividerRatio: Voltage divider ratio if used (e.g., 5.0 for 16.5V max)
        adcReadFunction: Function to read raw ADC value

    Returns:
        Voltage reader function

    Raises:
        BatteryConfigurationError: If ADC read function is not configured

    Example:
        # With MCP3008
        import spidev
        spi = spidev.SpiDev()
        spi.open(0, 0)

        def readAdcChannel(channel):
            r = spi.xfer2([1, (8 + channel) << 4, 0])
            return ((r[1] & 3) << 8) + r[2]

        reader = createAdcVoltageReader(adcChannel=0, adcReadFunction=readAdcChannel)
        monitor.setVoltageReader(reader)
    """
    def reader() -> float:
        if adcReadFunction is None:
            raise BatteryConfigurationError("ADC read function not configured")
        rawValue = adcReadFunction(adcChannel)
        voltage = (rawValue / maxAdcValue) * referenceVoltage * voltageDividerRatio
        return voltage

    return reader


def createI2cVoltageReader(
    i2cAddress: int = 0x48,
    voltageRegister: int = 0x00,
    voltageScale: float = 0.001,
    i2cReadFunction: Optional[Callable[[int, int], int]] = None,
) -> Callable[[], float]:
    """
    Create a voltage reader function for I2C-based voltage measurement.

    This is a helper to create a voltage reader for I2C power management
    boards (e.g., INA219, INA226, ADS1115).

    Args:
        i2cAddress: I2C address of the voltage monitor chip
        voltageRegister: Register address for voltage reading
        voltageScale: Scale factor to convert raw value to volts
        i2cReadFunction: Function to read I2C register (returns raw value)

    Returns:
        Voltage reader function

    Raises:
        BatteryConfigurationError: If I2C read function is not configured

    Example:
        import smbus
        bus = smbus.SMBus(1)

        def readI2cWord(addr, reg):
            return bus.read_word_data(addr, reg)

        reader = createI2cVoltageReader(
            i2cAddress=0x40,
            voltageRegister=0x02,
            voltageScale=0.00125,
            i2cReadFunction=readI2cWord
        )
        monitor.setVoltageReader(reader)
    """
    def reader() -> float:
        if i2cReadFunction is None:
            raise BatteryConfigurationError("I2C read function not configured")
        rawValue = i2cReadFunction(i2cAddress, voltageRegister)
        voltage = rawValue * voltageScale
        return voltage

    return reader


def createMockVoltageReader(fixedVoltage: float = 12.5) -> Callable[[], float]:
    """
    Create a mock voltage reader for testing.

    Returns a fixed voltage value, useful for testing without hardware.

    Args:
        fixedVoltage: Voltage value to return (default 12.5V)

    Returns:
        Mock voltage reader function

    Example:
        reader = createMockVoltageReader(12.0)
        monitor.setVoltageReader(reader)
    """
    def reader() -> float:
        return fixedVoltage

    return reader


# ================================================================================
# Power Status Readers
# ================================================================================

def createGpioPowerStatusReader(
    gpioPin: int,
    activeHigh: bool = True,
    gpioReadFunction: Optional[Callable[[int], int]] = None,
) -> Callable[[], bool]:
    """
    Create a power status reader function for GPIO-based detection.

    This is a helper to create a power status reader for setups where
    the 12V adapter status is detected via a GPIO pin.

    Args:
        gpioPin: GPIO pin number to read
        activeHigh: If True, HIGH = AC power connected
        gpioReadFunction: Function to read GPIO pin value

    Returns:
        Power status reader function

    Raises:
        PowerConfigurationError: If GPIO read function is not configured

    Example:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(17, GPIO.IN)

        reader = createGpioPowerStatusReader(
            gpioPin=17,
            activeHigh=True,
            gpioReadFunction=GPIO.input
        )
        monitor.setPowerStatusReader(reader)
    """
    def reader() -> bool:
        if gpioReadFunction is None:
            raise PowerConfigurationError("GPIO read function not configured")
        pinValue = gpioReadFunction(gpioPin)
        if activeHigh:
            return pinValue == 1
        else:
            return pinValue == 0

    return reader


def createI2cPowerStatusReader(
    i2cAddress: int = 0x6B,
    powerRegister: int = 0x00,
    acPowerBit: int = 0,
    i2cReadFunction: Optional[Callable[[int, int], int]] = None,
) -> Callable[[], bool]:
    """
    Create a power status reader function for I2C power management HAT.

    This is a helper to create a power status reader for setups using
    an I2C power management HAT (e.g., UPS HAT, power management board).

    Args:
        i2cAddress: I2C address of power management chip
        powerRegister: Register address for power status
        acPowerBit: Bit position for AC power status
        i2cReadFunction: Function to read I2C register

    Returns:
        Power status reader function

    Raises:
        PowerConfigurationError: If I2C read function is not configured

    Example:
        import smbus
        bus = smbus.SMBus(1)

        def readI2cRegister(addr, reg):
            return bus.read_byte_data(addr, reg)

        reader = createI2cPowerStatusReader(
            i2cAddress=0x6B,
            powerRegister=0x00,
            acPowerBit=2,
            i2cReadFunction=readI2cRegister
        )
        monitor.setPowerStatusReader(reader)
    """
    def reader() -> bool:
        if i2cReadFunction is None:
            raise PowerConfigurationError("I2C read function not configured")
        registerValue = i2cReadFunction(i2cAddress, powerRegister)
        # Check if AC power bit is set
        return bool(registerValue & (1 << acPowerBit))

    return reader


def createMockPowerStatusReader(onAcPower: bool = True) -> Callable[[], bool]:
    """
    Create a mock power status reader for testing.

    Returns a fixed power status value, useful for testing without hardware.

    Args:
        onAcPower: Power status to return (True = AC power, False = battery)

    Returns:
        Mock power status reader function

    Example:
        # Simulate AC power
        reader = createMockPowerStatusReader(True)
        monitor.setPowerStatusReader(reader)

        # Simulate battery power
        reader = createMockPowerStatusReader(False)
        monitor.setPowerStatusReader(reader)
    """
    def reader() -> bool:
        return onAcPower

    return reader


def createVariableVoltageReader(voltageGetter: Callable[[], float]) -> Callable[[], float]:
    """
    Create a voltage reader that delegates to a provided function.

    This is useful for testing scenarios where voltage needs to change
    over time.

    Args:
        voltageGetter: Function that returns the current voltage

    Returns:
        Voltage reader function

    Example:
        voltage = 12.5

        def getVoltage():
            return voltage

        reader = createVariableVoltageReader(getVoltage)
        monitor.setVoltageReader(reader)

        # Later, change the voltage
        voltage = 11.0
    """
    def reader() -> float:
        return voltageGetter()

    return reader


def createVariablePowerStatusReader(statusGetter: Callable[[], bool]) -> Callable[[], bool]:
    """
    Create a power status reader that delegates to a provided function.

    This is useful for testing scenarios where power status needs to change
    over time.

    Args:
        statusGetter: Function that returns the current power status

    Returns:
        Power status reader function

    Example:
        onAcPower = True

        def getStatus():
            return onAcPower

        reader = createVariablePowerStatusReader(getStatus)
        monitor.setPowerStatusReader(reader)

        # Later, simulate power loss
        onAcPower = False
    """
    def reader() -> bool:
        return statusGetter()

    return reader
