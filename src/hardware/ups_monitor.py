################################################################################
# File Name: ups_monitor.py
# Purpose/Description: UPS telemetry monitor for Geekworm X1209 UPS HAT
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
UPS telemetry monitor for Geekworm X1209 UPS HAT.

This module provides monitoring of the X1209 UPS HAT connected to a Raspberry Pi
via I2C. It reads battery voltage, current, percentage, and power source, and
can trigger callbacks when power source changes.

Usage:
    from hardware.ups_monitor import UpsMonitor, PowerSource

    def onPowerChange(oldSource, newSource):
        print(f"Power changed: {oldSource.value} -> {newSource.value}")

    monitor = UpsMonitor(address=0x36)
    monitor.onPowerSourceChange = onPowerChange
    monitor.startPolling(interval=5.0)

    # Read telemetry
    voltage = monitor.getBatteryVoltage()  # Returns volts as float
    current = monitor.getBatteryCurrent()  # Returns mA as float
    percentage = monitor.getBatteryPercentage()  # Returns 0-100
    source = monitor.getPowerSource()  # Returns PowerSource enum

    # Stop monitoring
    monitor.stopPolling()

Note:
    This module requires the I2cClient from hardware.i2c_client and
    I2C hardware support on a Raspberry Pi.
"""

import logging
import threading
import time
from enum import Enum
from typing import Callable, Optional

from .i2c_client import (
    I2cClient,
    I2cCommunicationError,
    I2cDeviceNotFoundError,
    I2cError,
    I2cNotAvailableError,
)
from .platform_utils import isRaspberryPi

logger = logging.getLogger(__name__)


# ================================================================================
# UPS Exceptions
# ================================================================================


class UpsMonitorError(Exception):
    """Base exception for UPS monitor errors."""
    pass


class UpsNotAvailableError(UpsMonitorError):
    """Exception raised when UPS is not available."""
    pass


# ================================================================================
# UPS Constants
# ================================================================================


class PowerSource(Enum):
    """Power source enumeration for UPS."""
    EXTERNAL = "external"
    BATTERY = "battery"
    UNKNOWN = "unknown"


# X1209 UPS HAT register addresses
REGISTER_VOLTAGE = 0x02  # Battery voltage in mV (16-bit word)
REGISTER_CURRENT = 0x04  # Battery current in mA (16-bit signed)
REGISTER_PERCENTAGE = 0x06  # Battery percentage (8-bit)
REGISTER_POWER_SOURCE = 0x08  # Power source (8-bit: 0=external, 1=battery)

# Default configuration
DEFAULT_UPS_ADDRESS = 0x36
DEFAULT_I2C_BUS = 1
DEFAULT_POLL_INTERVAL = 5.0  # seconds


# ================================================================================
# UPS Monitor Class
# ================================================================================


class UpsMonitor:
    """
    Monitor for the Geekworm X1209 UPS HAT via I2C.

    This class provides methods to read battery telemetry from the X1209 UPS HAT
    and supports polling with callbacks for power source changes.

    Attributes:
        address: I2C address of the UPS (default: 0x36)
        bus: I2C bus number (default: 1)
        pollInterval: Polling interval in seconds (default: 5.0)
        onPowerSourceChange: Callback for power source changes

    Example:
        monitor = UpsMonitor()
        monitor.onPowerSourceChange = lambda old, new: print(f"{old} -> {new}")
        monitor.startPolling()
    """

    def __init__(
        self,
        address: int = DEFAULT_UPS_ADDRESS,
        bus: int = DEFAULT_I2C_BUS,
        pollInterval: float = DEFAULT_POLL_INTERVAL,
        i2cClient: Optional[I2cClient] = None
    ):
        """
        Initialize UPS monitor.

        Args:
            address: I2C address of the UPS (default: 0x36)
            bus: I2C bus number (default: 1)
            pollInterval: Polling interval in seconds (default: 5.0)
            i2cClient: Optional pre-configured I2C client (for testing)

        Raises:
            UpsNotAvailableError: If UPS is not available on this system
        """
        self._address = address
        self._bus = bus
        self._pollInterval = pollInterval

        # Callback for power source change
        self.onPowerSourceChange: Optional[
            Callable[[PowerSource, PowerSource], None]
        ] = None

        # Polling state
        self._pollingThread: Optional[threading.Thread] = None
        self._stopEvent = threading.Event()
        self._isPolling = False

        # Last known state (for change detection)
        self._lastPowerSource: Optional[PowerSource] = None

        # I2C client (lazy initialization)
        self._i2cClient: Optional[I2cClient] = i2cClient
        self._clientOwned = i2cClient is None  # We own the client if we created it

        logger.debug(
            f"UpsMonitor initialized: address=0x{address:02x}, bus={bus}, "
            f"pollInterval={pollInterval}s"
        )

    def _getClient(self) -> I2cClient:
        """
        Get or create the I2C client.

        Returns:
            I2C client instance

        Raises:
            UpsNotAvailableError: If I2C is not available
        """
        if self._i2cClient is not None:
            return self._i2cClient

        # Check if we're on a Raspberry Pi
        if not isRaspberryPi():
            raise UpsNotAvailableError(
                "UPS monitoring not available - not running on Raspberry Pi"
            )

        # Create I2C client
        try:
            self._i2cClient = I2cClient(bus=self._bus)
            return self._i2cClient
        except I2cNotAvailableError as e:
            raise UpsNotAvailableError(f"UPS not available: {e}") from e

    def getBatteryVoltage(self) -> float:
        """
        Read battery voltage from UPS.

        Returns:
            Battery voltage in volts (e.g., 3.7)

        Raises:
            UpsMonitorError: If read fails
            UpsNotAvailableError: If UPS is not available

        Example:
            voltage = monitor.getBatteryVoltage()
            print(f"Battery: {voltage:.2f}V")
        """
        try:
            client = self._getClient()
            # Read voltage as 16-bit word (mV)
            voltageMv = client.readWord(self._address, REGISTER_VOLTAGE)
            voltageV = voltageMv / 1000.0
            logger.debug(f"Battery voltage: {voltageV:.3f}V ({voltageMv}mV)")
            return voltageV
        except I2cDeviceNotFoundError as e:
            raise UpsNotAvailableError(
                f"UPS device not found at address 0x{self._address:02x}"
            ) from e
        except I2cError as e:
            raise UpsMonitorError(f"Failed to read battery voltage: {e}") from e

    def getBatteryCurrent(self) -> float:
        """
        Read battery current from UPS.

        Positive values indicate charging, negative values indicate discharging.

        Returns:
            Battery current in milliamps (mA)

        Raises:
            UpsMonitorError: If read fails
            UpsNotAvailableError: If UPS is not available

        Example:
            current = monitor.getBatteryCurrent()
            if current > 0:
                print(f"Charging: {current:.0f}mA")
            else:
                print(f"Discharging: {abs(current):.0f}mA")
        """
        try:
            client = self._getClient()
            # Read current as 16-bit word (signed mA)
            currentRaw = client.readWord(self._address, REGISTER_CURRENT)
            # Convert to signed 16-bit
            if currentRaw > 32767:
                currentRaw -= 65536
            logger.debug(f"Battery current: {currentRaw}mA")
            return float(currentRaw)
        except I2cDeviceNotFoundError as e:
            raise UpsNotAvailableError(
                f"UPS device not found at address 0x{self._address:02x}"
            ) from e
        except I2cError as e:
            raise UpsMonitorError(f"Failed to read battery current: {e}") from e

    def getBatteryPercentage(self) -> int:
        """
        Read battery percentage from UPS.

        Returns:
            Battery percentage (0-100)

        Raises:
            UpsMonitorError: If read fails
            UpsNotAvailableError: If UPS is not available

        Example:
            pct = monitor.getBatteryPercentage()
            print(f"Battery: {pct}%")
        """
        try:
            client = self._getClient()
            # Read percentage as 8-bit byte
            percentage = client.readByte(self._address, REGISTER_PERCENTAGE)
            # Clamp to valid range
            percentage = max(0, min(100, percentage))
            logger.debug(f"Battery percentage: {percentage}%")
            return percentage
        except I2cDeviceNotFoundError as e:
            raise UpsNotAvailableError(
                f"UPS device not found at address 0x{self._address:02x}"
            ) from e
        except I2cError as e:
            raise UpsMonitorError(f"Failed to read battery percentage: {e}") from e

    def getPowerSource(self) -> PowerSource:
        """
        Read current power source from UPS.

        Returns:
            PowerSource.EXTERNAL (mains power) or PowerSource.BATTERY

        Raises:
            UpsMonitorError: If read fails
            UpsNotAvailableError: If UPS is not available

        Example:
            source = monitor.getPowerSource()
            if source == PowerSource.BATTERY:
                print("Running on battery power!")
        """
        try:
            client = self._getClient()
            # Read power source as 8-bit byte (0=external, 1=battery)
            sourceValue = client.readByte(self._address, REGISTER_POWER_SOURCE)

            if sourceValue == 0:
                source = PowerSource.EXTERNAL
            elif sourceValue == 1:
                source = PowerSource.BATTERY
            else:
                logger.warning(f"Unknown power source value: {sourceValue}")
                source = PowerSource.UNKNOWN

            logger.debug(f"Power source: {source.value}")
            return source
        except I2cDeviceNotFoundError as e:
            raise UpsNotAvailableError(
                f"UPS device not found at address 0x{self._address:02x}"
            ) from e
        except I2cError as e:
            raise UpsMonitorError(f"Failed to read power source: {e}") from e

    def getTelemetry(self) -> dict:
        """
        Read all telemetry values from UPS.

        Returns:
            Dictionary with voltage, current, percentage, and powerSource

        Raises:
            UpsMonitorError: If read fails
            UpsNotAvailableError: If UPS is not available

        Example:
            telemetry = monitor.getTelemetry()
            print(f"Voltage: {telemetry['voltage']:.2f}V")
            print(f"Current: {telemetry['current']:.0f}mA")
            print(f"Percentage: {telemetry['percentage']}%")
            print(f"Source: {telemetry['powerSource'].value}")
        """
        return {
            'voltage': self.getBatteryVoltage(),
            'current': self.getBatteryCurrent(),
            'percentage': self.getBatteryPercentage(),
            'powerSource': self.getPowerSource(),
        }

    def startPolling(self, interval: Optional[float] = None) -> None:
        """
        Start polling UPS telemetry in a background thread.

        When power source changes, the onPowerSourceChange callback is invoked.

        Args:
            interval: Polling interval in seconds (default: self.pollInterval)

        Raises:
            RuntimeError: If polling is already running
            UpsNotAvailableError: If UPS is not available

        Example:
            monitor.onPowerSourceChange = myCallback
            monitor.startPolling(interval=5.0)
        """
        if self._isPolling:
            raise RuntimeError("Polling is already running")

        if interval is not None:
            self._pollInterval = interval

        # Verify UPS is accessible before starting
        self._getClient()

        # Initialize last known state
        try:
            self._lastPowerSource = self.getPowerSource()
        except UpsMonitorError as e:
            logger.warning(f"Could not get initial power source: {e}")
            self._lastPowerSource = PowerSource.UNKNOWN

        self._stopEvent.clear()
        self._isPolling = True

        self._pollingThread = threading.Thread(
            target=self._pollingLoop,
            name="UpsMonitorPolling",
            daemon=True
        )
        self._pollingThread.start()

        logger.info(f"UPS polling started with interval={self._pollInterval}s")

    def stopPolling(self) -> None:
        """
        Stop polling UPS telemetry.

        Safe to call even if polling is not running.
        """
        if not self._isPolling:
            return

        self._stopEvent.set()

        if self._pollingThread is not None and self._pollingThread.is_alive():
            self._pollingThread.join(timeout=5.0)

        self._isPolling = False
        self._pollingThread = None

        logger.info("UPS polling stopped")

    def _pollingLoop(self) -> None:
        """Background polling loop."""
        while not self._stopEvent.is_set():
            try:
                # Read current power source
                currentSource = self.getPowerSource()

                # Check for power source change
                if (self._lastPowerSource is not None and
                        currentSource != self._lastPowerSource):

                    logger.info(
                        f"Power source changed: {self._lastPowerSource.value} -> "
                        f"{currentSource.value}"
                    )

                    # Invoke callback if registered
                    if self.onPowerSourceChange is not None:
                        try:
                            self.onPowerSourceChange(
                                self._lastPowerSource,
                                currentSource
                            )
                        except Exception as e:
                            logger.error(f"Error in power change callback: {e}")

                self._lastPowerSource = currentSource

            except UpsMonitorError as e:
                logger.warning(f"Error during UPS polling: {e}")
            except Exception as e:
                logger.error(f"Unexpected error during UPS polling: {e}")

            # Wait for next poll interval (or stop signal)
            self._stopEvent.wait(timeout=self._pollInterval)

    @property
    def address(self) -> int:
        """Get the I2C address."""
        return self._address

    @property
    def bus(self) -> int:
        """Get the I2C bus number."""
        return self._bus

    @property
    def pollInterval(self) -> float:
        """Get the polling interval in seconds."""
        return self._pollInterval

    @pollInterval.setter
    def pollInterval(self, value: float) -> None:
        """Set the polling interval in seconds."""
        if value <= 0:
            raise ValueError("Poll interval must be positive")
        self._pollInterval = value

    @property
    def isPolling(self) -> bool:
        """Check if polling is active."""
        return self._isPolling

    def close(self) -> None:
        """
        Close the UPS monitor and release resources.

        Stops polling if active and closes the I2C client if we own it.
        """
        self.stopPolling()

        if self._clientOwned and self._i2cClient is not None:
            self._i2cClient.close()
            self._i2cClient = None

        logger.debug("UpsMonitor closed")

    def __enter__(self) -> 'UpsMonitor':
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close the monitor."""
        self.close()

    def __del__(self) -> None:
        """Destructor - ensure resources are released."""
        self.close()
