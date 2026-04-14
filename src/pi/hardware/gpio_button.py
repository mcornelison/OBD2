################################################################################
# File Name: gpio_button.py
# Purpose/Description: GPIO shutdown button handler for physical button input
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
GPIO shutdown button handler for physical button input.

This module provides a class to monitor a physical button connected to GPIO,
with debounce logic and support for short press (log only) and long press
(trigger graceful shutdown) actions.

Usage:
    from hardware.gpio_button import GpioButton

    # Create button handler with default settings
    button = GpioButton()  # GPIO17 by default

    # Set up callbacks
    button.onShortPress = lambda: print("Short press!")
    button.onLongPress = lambda: print("Long press - shutting down!")

    # Start monitoring
    button.start()

    # When done
    button.stop()

Note:
    On non-Raspberry Pi systems, the button handler logs a warning
    and operates in a disabled mode where no GPIO operations occur.
"""

import logging
import threading
import time
from collections.abc import Callable

from .platform_utils import isRaspberryPi

logger = logging.getLogger(__name__)


# ================================================================================
# GPIO Button Exceptions
# ================================================================================


class GpioButtonError(Exception):
    """Base exception for GPIO button errors."""
    pass


class GpioNotAvailableError(GpioButtonError):
    """Raised when GPIO is not available (non-Pi system)."""
    pass


# ================================================================================
# GPIO Button Constants
# ================================================================================

# Default GPIO pin for shutdown button (BCM numbering)
DEFAULT_BUTTON_PIN = 17

# Debounce time in seconds to ignore bouncing contacts
DEFAULT_DEBOUNCE_TIME = 0.2  # 200ms

# Hold time in seconds for long press detection
DEFAULT_HOLD_TIME = 3.0  # 3 seconds


# ================================================================================
# GPIO Button Class
# ================================================================================


class GpioButton:
    """
    Handler for GPIO shutdown button.

    Monitors a physical button connected to a GPIO pin, with configurable
    debounce and hold times. Supports callbacks for short press (button released
    before hold time) and long press (button held for hold time or longer).

    Attributes:
        pin: GPIO pin number (BCM numbering)
        debounceTime: Debounce time in seconds
        holdTime: Hold time in seconds for long press
        isAvailable: Whether GPIO is available on this system
        isRunning: Whether the button monitor is currently running
        onShortPress: Callback for short press events
        onLongPress: Callback for long press events

    Example:
        button = GpioButton(pin=17, holdTime=3.0)
        button.onLongPress = handleShutdown
        button.start()
    """

    def __init__(
        self,
        pin: int = DEFAULT_BUTTON_PIN,
        debounceTime: float = DEFAULT_DEBOUNCE_TIME,
        holdTime: float = DEFAULT_HOLD_TIME
    ):
        """
        Initialize GPIO button handler.

        Args:
            pin: GPIO pin number in BCM numbering (default: 17)
            debounceTime: Debounce time in seconds (default: 0.2)
            holdTime: Hold time for long press in seconds (default: 3.0)

        Raises:
            ValueError: If pin is negative or times are invalid
        """
        if pin < 0:
            raise ValueError("GPIO pin must be non-negative")
        if debounceTime < 0:
            raise ValueError("Debounce time must be non-negative")
        if holdTime <= 0:
            raise ValueError("Hold time must be positive")

        self._pin = pin
        self._debounceTime = debounceTime
        self._holdTime = holdTime

        # Callbacks
        self._onShortPress: Callable[[], None] | None = None
        self._onLongPress: Callable[[], None] | None = None

        # State tracking
        self._isAvailable = False
        self._isRunning = False
        self._button = None  # gpiozero Button object
        self._lock = threading.Lock()

        # Check for GPIO availability
        self._checkAvailability()

        logger.debug(
            f"GpioButton initialized: pin={pin}, debounce={debounceTime}s, "
            f"holdTime={holdTime}s, available={self._isAvailable}"
        )

    def _checkAvailability(self) -> None:
        """Check if GPIO is available on this system."""
        if not isRaspberryPi():
            logger.warning(
                "GPIO not available - not running on Raspberry Pi. "
                "Button functionality will be disabled."
            )
            self._isAvailable = False
            return

        try:
            # Try to import gpiozero
            from gpiozero import Button  # noqa: F401
            self._isAvailable = True
        except (ImportError, RuntimeError, NotImplementedError) as e:
            logger.warning(f"GPIO not available - gpiozero import failed: {e}")
            self._isAvailable = False

    def start(self) -> bool:
        """
        Start monitoring the button.

        Returns:
            True if monitoring started successfully, False if GPIO not available

        Raises:
            GpioButtonError: If button is already running
        """
        with self._lock:
            if self._isRunning:
                raise GpioButtonError("Button monitor is already running")

            if not self._isAvailable:
                logger.warning(
                    f"Cannot start button monitor - GPIO not available. "
                    f"Pin {self._pin} will not be monitored."
                )
                return False

            try:
                from gpiozero import Button

                # Create button with pull-up resistor and debounce
                self._button = Button(
                    self._pin,
                    pull_up=True,
                    bounce_time=self._debounceTime,
                    hold_time=self._holdTime
                )

                # Set up callbacks
                self._button.when_released = self._handleRelease
                self._button.when_held = self._handleHeld

                self._isRunning = True

                logger.info(
                    f"Button monitor started on GPIO{self._pin} "
                    f"(debounce={self._debounceTime}s, holdTime={self._holdTime}s)"
                )
                return True

            except Exception as e:
                logger.error(f"Failed to start button monitor: {e}")
                raise GpioButtonError(f"Failed to start button monitor: {e}") from e

    def stop(self) -> None:
        """
        Stop monitoring the button.

        Safe to call multiple times or when not running.
        """
        with self._lock:
            if not self._isRunning:
                return

            if self._button is not None:
                try:
                    self._button.close()
                except Exception as e:
                    logger.warning(f"Error closing button: {e}")
                finally:
                    self._button = None

            self._isRunning = False
            logger.info(f"Button monitor stopped on GPIO{self._pin}")

    def _handleRelease(self) -> None:
        """
        Handle button release event.

        Called by gpiozero when button is released before hold time.
        Triggers short press callback if set.
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"Button short press detected on GPIO{self._pin} at {timestamp}")

        if self._onShortPress is not None:
            try:
                self._onShortPress()
            except Exception as e:
                logger.error(f"Error in short press callback: {e}")

    def _handleHeld(self) -> None:
        """
        Handle button held event.

        Called by gpiozero when button has been held for hold time.
        Triggers long press callback if set.
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(
            f"Button long press detected on GPIO{self._pin} at {timestamp} "
            f"(held for {self._holdTime}s)"
        )

        if self._onLongPress is not None:
            try:
                self._onLongPress()
            except Exception as e:
                logger.error(f"Error in long press callback: {e}")

    @property
    def pin(self) -> int:
        """Get the GPIO pin number."""
        return self._pin

    @property
    def debounceTime(self) -> float:
        """Get the debounce time in seconds."""
        return self._debounceTime

    @property
    def holdTime(self) -> float:
        """Get the hold time for long press in seconds."""
        return self._holdTime

    @property
    def isAvailable(self) -> bool:
        """Check if GPIO is available on this system."""
        return self._isAvailable

    @property
    def isRunning(self) -> bool:
        """Check if the button monitor is currently running."""
        return self._isRunning

    @property
    def onShortPress(self) -> Callable[[], None] | None:
        """Get the short press callback."""
        return self._onShortPress

    @onShortPress.setter
    def onShortPress(self, callback: Callable[[], None] | None) -> None:
        """
        Set the short press callback.

        Args:
            callback: Function to call on short press, or None to clear
        """
        self._onShortPress = callback

    @property
    def onLongPress(self) -> Callable[[], None] | None:
        """Get the long press callback."""
        return self._onLongPress

    @onLongPress.setter
    def onLongPress(self, callback: Callable[[], None] | None) -> None:
        """
        Set the long press callback.

        Args:
            callback: Function to call on long press, or None to clear
        """
        self._onLongPress = callback

    def close(self) -> None:
        """
        Close the button handler and release resources.

        Safe to call multiple times.
        """
        self.stop()
        logger.debug(f"GpioButton closed for GPIO{self._pin}")

    def __enter__(self) -> 'GpioButton':
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close the button handler."""
        self.close()

    def __del__(self) -> None:
        """Destructor - ensure resources are released."""
        # Check if _lock exists to handle partially initialized objects
        if hasattr(self, '_lock'):
            self.close()
