################################################################################
# File Name: command_gpio.py
# Purpose/Description: GpioButtonTrigger — Pi GPIO button monitoring for shutdown triggering
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-009
# 2026-04-14    | Sweep 5       | Extracted from command.py (task 4 split)
# ================================================================================
################################################################################

"""
GpioButtonTrigger — monitors a GPIO pin and initiates shutdown on button press.

Imports RPi.GPIO at module scope (with graceful fallback on non-Pi platforms).
The GPIO_AVAILABLE flag and isGpioAvailable() helper live here so consumers
can probe availability without importing RPi.GPIO themselves.
"""

import logging
import time
from collections.abc import Callable

from .command_core import ShutdownCommand
from .command_types import (
    DEFAULT_GPIO_PIN,
    SHUTDOWN_REASON_GPIO_BUTTON,
    GpioNotAvailableError,
    ShutdownConfig,
)

logger = logging.getLogger(__name__)


# Try to import GPIO library (Raspberry Pi specific)
GPIO_AVAILABLE = False
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO = None


def isGpioAvailable() -> bool:
    """
    Check if GPIO library is available.

    Returns:
        True if RPi.GPIO can be imported, False otherwise
    """
    return GPIO_AVAILABLE


class GpioButtonTrigger:
    """
    GPIO button trigger for initiating shutdown.

    Monitors a GPIO pin for button presses and initiates shutdown
    when pressed. Uses pull-up resistor by default (button connects
    pin to ground when pressed).

    Attributes:
        _config: Shutdown configuration
        _shutdownCommand: ShutdownCommand instance
        _running: Whether monitoring is active
        _callback: Optional callback on button press

    Example:
        trigger = GpioButtonTrigger(gpioPin=17, callback=onButtonPress)
        trigger.start()
        # ... application runs ...
        trigger.stop()
    """

    def __init__(
        self,
        gpioPin: int = DEFAULT_GPIO_PIN,
        config: ShutdownConfig | None = None,
        shutdownCommand: ShutdownCommand | None = None,
        callback: Callable[[], None] | None = None,
        autoShutdown: bool = True,
        powerOff: bool = False
    ):
        """
        Initialize GPIO button trigger.

        Args:
            gpioPin: GPIO pin number (BCM numbering)
            config: Shutdown configuration
            shutdownCommand: ShutdownCommand instance to use
            callback: Optional callback when button is pressed
            autoShutdown: Whether to automatically initiate shutdown
            powerOff: Whether to power off after shutdown

        Raises:
            GpioNotAvailableError: If GPIO library is not available
        """
        if not GPIO_AVAILABLE:
            raise GpioNotAvailableError(
                "RPi.GPIO not available - GPIO button trigger requires Raspberry Pi"
            )

        self._config = config or ShutdownConfig()
        self._config.gpioPin = gpioPin

        self._shutdownCommand = shutdownCommand
        self._callback = callback
        self._autoShutdown = autoShutdown
        self._powerOff = powerOff
        self._running = False
        self._lastPressTime = 0

    def start(self) -> None:
        """
        Start monitoring GPIO button.

        Sets up GPIO pin with pull-up resistor and falling edge detection.
        """
        if self._running:
            logger.warning("GPIO button trigger already running")
            return

        logger.info(f"Starting GPIO button trigger | pin={self._config.gpioPin}")

        try:
            GPIO.setmode(GPIO.BCM)

            # Set up pin with pull-up
            pullUpDown = GPIO.PUD_UP if self._config.gpioPullUp else GPIO.PUD_DOWN
            GPIO.setup(self._config.gpioPin, GPIO.IN, pull_up_down=pullUpDown)

            # Add event detection for falling edge (button press with pull-up)
            edge = GPIO.FALLING if self._config.gpioPullUp else GPIO.RISING
            GPIO.add_event_detect(
                self._config.gpioPin,
                edge,
                callback=self._onButtonPress,
                bouncetime=self._config.gpioDebounceMs
            )

            self._running = True
            logger.info("GPIO button trigger started")

        except Exception as e:
            logger.error(f"Failed to start GPIO button trigger: {e}")
            raise GpioNotAvailableError(f"Failed to initialize GPIO: {e}") from e

    def stop(self) -> None:
        """
        Stop monitoring GPIO button.

        Cleans up GPIO resources.
        """
        if not self._running:
            return

        logger.info("Stopping GPIO button trigger")

        try:
            GPIO.remove_event_detect(self._config.gpioPin)
            GPIO.cleanup(self._config.gpioPin)
        except Exception as e:
            logger.warning(f"Error during GPIO cleanup: {e}")

        self._running = False
        logger.info("GPIO button trigger stopped")

    def _onButtonPress(self, channel: int) -> None:
        """
        Handle button press event.

        Args:
            channel: GPIO channel that triggered the event
        """
        currentTime = time.time()

        # Additional software debounce
        if currentTime - self._lastPressTime < (self._config.gpioDebounceMs / 1000.0):
            return

        self._lastPressTime = currentTime

        logger.info(f"GPIO button pressed | channel={channel}")

        # Execute callback if provided
        if self._callback:
            try:
                self._callback()
            except Exception as e:
                logger.error(f"Error in button callback: {e}")

        # Initiate shutdown if auto-shutdown is enabled
        if self._autoShutdown:
            self._initiateShutdown()

    def _initiateShutdown(self) -> None:
        """Initiate shutdown via button press."""
        logger.info("Initiating shutdown from GPIO button press")

        if self._shutdownCommand:
            try:
                result = self._shutdownCommand.initiateShutdown(
                    reason=SHUTDOWN_REASON_GPIO_BUTTON,
                    powerOff=self._powerOff
                )
                if not result.success:
                    logger.error(f"Shutdown failed: {result.errorMessage}")
            except Exception as e:
                logger.error(f"Error initiating shutdown: {e}")

    def isRunning(self) -> bool:
        """Check if GPIO monitoring is active."""
        return self._running
