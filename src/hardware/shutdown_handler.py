################################################################################
# File Name: shutdown_handler.py
# Purpose/Description: Graceful shutdown handler for car power loss detection
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
Graceful shutdown handler for car power loss detection.

This module monitors UPS power source changes and initiates a graceful system
shutdown when the car power is lost (switching to battery). It provides a
configurable delay before shutdown to allow power restoration, and handles
low battery conditions with immediate shutdown.

Usage:
    from hardware.shutdown_handler import ShutdownHandler
    from hardware.ups_monitor import UpsMonitor

    handler = ShutdownHandler(shutdownDelay=30, lowBatteryThreshold=10)
    monitor = UpsMonitor()

    # Register handler with UPS monitor
    handler.registerWithUpsMonitor(monitor)

    # Or use manually
    monitor.onPowerSourceChange = handler.onPowerSourceChange

    # Check for low battery
    percentage = monitor.getBatteryPercentage()
    handler.onLowBattery(percentage)

Note:
    System shutdown requires appropriate permissions (typically root).
    On Raspberry Pi, the system user should have sudo NOPASSWD for systemctl.
"""

import logging
import subprocess
import threading
import time

from .ups_monitor import PowerSource, UpsMonitor

logger = logging.getLogger(__name__)


# ================================================================================
# Shutdown Handler Exceptions
# ================================================================================


class ShutdownHandlerError(Exception):
    """Base exception for shutdown handler errors."""
    pass


# ================================================================================
# Shutdown Handler Constants
# ================================================================================

DEFAULT_SHUTDOWN_DELAY = 30  # seconds to wait before shutdown
DEFAULT_LOW_BATTERY_THRESHOLD = 10  # percentage


# ================================================================================
# Shutdown Handler Class
# ================================================================================


class ShutdownHandler:
    """
    Handler for graceful system shutdown on power loss.

    This class monitors power source changes from the UPS and schedules a
    graceful shutdown when external power is lost. Shutdown can be cancelled
    if power is restored before the delay expires.

    Attributes:
        shutdownDelay: Seconds to wait before shutdown (default: 30)
        lowBatteryThreshold: Battery percentage for immediate shutdown (default: 10)
        isShutdownPending: Whether a shutdown is currently scheduled
        timeUntilShutdown: Seconds until scheduled shutdown (or None)

    Example:
        handler = ShutdownHandler(shutdownDelay=30)
        handler.registerWithUpsMonitor(upsMonitor)
    """

    def __init__(
        self,
        shutdownDelay: int = DEFAULT_SHUTDOWN_DELAY,
        lowBatteryThreshold: int = DEFAULT_LOW_BATTERY_THRESHOLD
    ):
        """
        Initialize shutdown handler.

        Args:
            shutdownDelay: Seconds to wait before shutdown (must be positive)
            lowBatteryThreshold: Battery percentage for immediate shutdown (0-100)

        Raises:
            ValueError: If shutdownDelay is not positive or threshold is invalid
        """
        if shutdownDelay <= 0:
            raise ValueError("Shutdown delay must be positive")
        if lowBatteryThreshold < 0 or lowBatteryThreshold > 100:
            raise ValueError("Low battery threshold must be between 0 and 100")

        self._shutdownDelay = shutdownDelay
        self._lowBatteryThreshold = lowBatteryThreshold

        # Timer for scheduled shutdown
        self._shutdownTimer: threading.Timer | None = None
        self._shutdownScheduledAt: float | None = None

        # Lock for thread-safe timer operations
        self._lock = threading.Lock()

        logger.debug(
            f"ShutdownHandler initialized: delay={shutdownDelay}s, "
            f"lowBatteryThreshold={lowBatteryThreshold}%"
        )

    def onPowerSourceChange(
        self,
        oldSource: PowerSource,
        newSource: PowerSource
    ) -> None:
        """
        Handle power source change event.

        Called by UpsMonitor when power source changes. Schedules shutdown
        when switching to battery power, cancels shutdown when power is restored.

        Args:
            oldSource: Previous power source
            newSource: Current power source

        Example:
            handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        """
        if newSource == PowerSource.BATTERY:
            self._scheduleShutdown()
        elif newSource == PowerSource.EXTERNAL:
            self._cancelScheduledShutdown()

    def onLowBattery(self, percentage: int) -> None:
        """
        Handle low battery condition.

        If battery percentage is at or below the threshold, triggers immediate
        shutdown without waiting for the configured delay.

        Args:
            percentage: Current battery percentage (0-100)

        Example:
            handler.onLowBattery(5)  # Triggers shutdown if threshold is 10%
        """
        if percentage <= self._lowBatteryThreshold:
            logger.info(
                f"Low battery detected ({percentage}% <= {self._lowBatteryThreshold}% "
                f"threshold) - initiating immediate shutdown"
            )
            self._executeShutdown()

    def _scheduleShutdown(self) -> None:
        """Schedule a shutdown after the configured delay."""
        with self._lock:
            if self._shutdownTimer is not None:
                # Already scheduled
                logger.debug("Shutdown already scheduled, ignoring")
                return

            logger.info(
                f"External power lost - scheduling shutdown in {self._shutdownDelay} seconds"
            )

            self._shutdownScheduledAt = time.time()
            self._shutdownTimer = threading.Timer(
                self._shutdownDelay,
                self._executeShutdown
            )
            self._shutdownTimer.daemon = True
            self._shutdownTimer.start()

    def _cancelScheduledShutdown(self) -> None:
        """Cancel any pending scheduled shutdown."""
        with self._lock:
            if self._shutdownTimer is None:
                # Nothing to cancel
                return

            logger.info("External power restored - cancelling scheduled shutdown")

            self._shutdownTimer.cancel()
            self._shutdownTimer = None
            self._shutdownScheduledAt = None

    def _executeShutdown(self) -> None:
        """Execute the system shutdown."""
        with self._lock:
            # Clear timer state
            self._shutdownTimer = None
            self._shutdownScheduledAt = None

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"Initiating system shutdown at {timestamp}")

        try:
            result = subprocess.run(
                ['systemctl', 'poweroff'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.warning(
                    f"Shutdown command returned non-zero: {result.returncode}. "
                    f"stderr: {result.stderr}"
                )
        except subprocess.TimeoutExpired:
            logger.error("Shutdown command timed out")
        except Exception as e:
            logger.error(f"Failed to execute shutdown: {e}")

    def registerWithUpsMonitor(self, upsMonitor: UpsMonitor) -> None:
        """
        Register this handler with a UpsMonitor.

        Sets the power source change callback on the UpsMonitor to this
        handler's onPowerSourceChange method.

        Args:
            upsMonitor: UpsMonitor instance to register with

        Example:
            handler.registerWithUpsMonitor(monitor)
        """
        upsMonitor.onPowerSourceChange = self.onPowerSourceChange
        logger.debug("Registered with UpsMonitor")

    def unregisterFromUpsMonitor(self, upsMonitor: UpsMonitor) -> None:
        """
        Unregister this handler from a UpsMonitor.

        Clears the power source change callback on the UpsMonitor.

        Args:
            upsMonitor: UpsMonitor instance to unregister from

        Example:
            handler.unregisterFromUpsMonitor(monitor)
        """
        upsMonitor.onPowerSourceChange = None
        logger.debug("Unregistered from UpsMonitor")

    def cancelShutdown(self) -> bool:
        """
        Explicitly cancel any pending shutdown.

        Returns:
            True if a shutdown was cancelled, False if none was pending

        Example:
            if handler.cancelShutdown():
                print("Shutdown cancelled")
        """
        with self._lock:
            if self._shutdownTimer is None:
                return False

            logger.info("Shutdown explicitly cancelled")

            self._shutdownTimer.cancel()
            self._shutdownTimer = None
            self._shutdownScheduledAt = None
            return True

    @property
    def shutdownDelay(self) -> int:
        """Get the shutdown delay in seconds."""
        return self._shutdownDelay

    @shutdownDelay.setter
    def shutdownDelay(self, value: int) -> None:
        """
        Set the shutdown delay in seconds.

        Args:
            value: Delay in seconds (must be positive)

        Raises:
            ValueError: If value is not positive
        """
        if value <= 0:
            raise ValueError("Shutdown delay must be positive")
        self._shutdownDelay = value

    @property
    def lowBatteryThreshold(self) -> int:
        """Get the low battery threshold percentage."""
        return self._lowBatteryThreshold

    @lowBatteryThreshold.setter
    def lowBatteryThreshold(self, value: int) -> None:
        """
        Set the low battery threshold percentage.

        Args:
            value: Threshold percentage (0-100)

        Raises:
            ValueError: If value is not in valid range
        """
        if value < 0 or value > 100:
            raise ValueError("Low battery threshold must be between 0 and 100")
        self._lowBatteryThreshold = value

    @property
    def isShutdownPending(self) -> bool:
        """Check if a shutdown is currently scheduled."""
        with self._lock:
            return self._shutdownTimer is not None

    @property
    def timeUntilShutdown(self) -> float | None:
        """
        Get time remaining until shutdown.

        Returns:
            Seconds until shutdown, or None if no shutdown is pending
        """
        with self._lock:
            if self._shutdownScheduledAt is None:
                return None

            elapsed = time.time() - self._shutdownScheduledAt
            remaining = self._shutdownDelay - elapsed
            return max(0.0, remaining)

    def close(self) -> None:
        """
        Close the handler and cancel any pending shutdown.

        Safe to call multiple times.
        """
        self.cancelShutdown()
        logger.debug("ShutdownHandler closed")

    def __enter__(self) -> 'ShutdownHandler':
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close the handler."""
        self.close()

    def __del__(self) -> None:
        """Destructor - ensure resources are released."""
        # Check if _lock exists to handle partially initialized objects
        if hasattr(self, '_lock'):
            self.close()
