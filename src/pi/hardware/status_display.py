################################################################################
# File Name: status_display.py
# Purpose/Description: Status display module using pygame for 480x320 touch screen
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
Status display module for OSOYOO 3.5" HDMI touch screen.

This module provides a simple status display showing:
- Battery percentage and voltage
- Power source (Car / Battery)
- OBD2 connection status
- Error/warning count
- System uptime and IP address

The display is rendered using pygame with large, readable fonts optimized
for a 480x320 touch display.

Usage:
    from hardware.status_display import StatusDisplay

    display = StatusDisplay()
    display.start()

    # Update display data
    display.updateBatteryInfo(percentage=85, voltage=4.1)
    display.updatePowerSource('external')
    display.updateObdStatus('connected')
    display.updateErrorCount(warnings=2, errors=0)

    # Stop display
    display.stop()

Note:
    On non-Raspberry Pi systems, the display handler logs a warning
    and operates in a disabled mode where no pygame operations occur.
"""

import logging
import socket
import threading
import time
from collections.abc import Callable
from enum import Enum

from .platform_utils import isRaspberryPi

logger = logging.getLogger(__name__)


# ================================================================================
# Status Display Exceptions
# ================================================================================


class StatusDisplayError(Exception):
    """Base exception for status display errors."""
    pass


class DisplayNotAvailableError(StatusDisplayError):
    """Raised when display is not available (non-Pi system or pygame unavailable)."""
    pass


# ================================================================================
# Status Display Constants
# ================================================================================


class ConnectionStatus(Enum):
    """OBD2 connection status enumeration."""
    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"
    RECONNECTING = "Reconnecting"


class PowerSourceDisplay(Enum):
    """Power source for display purposes."""
    CAR = "Car"
    BATTERY = "Battery"
    UNKNOWN = "Unknown"


# Display dimensions (OSOYOO 3.5" HDMI screen)
DISPLAY_WIDTH = 480
DISPLAY_HEIGHT = 320

# Default refresh rate in seconds
DEFAULT_REFRESH_RATE = 2.0

# Colors (RGB tuples)
COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_GREEN = (0, 200, 0)
COLOR_RED = (200, 0, 0)
COLOR_ORANGE = (255, 165, 0)
COLOR_BLUE = (0, 100, 255)
COLOR_GRAY = (128, 128, 128)

# Font sizes for readability on 480x320
FONT_SIZE_LARGE = 32
FONT_SIZE_MEDIUM = 24
FONT_SIZE_SMALL = 18

# Layout constants
PADDING = 10
LINE_HEIGHT_LARGE = 40
LINE_HEIGHT_MEDIUM = 30


# ================================================================================
# Status Display Class
# ================================================================================


class StatusDisplay:
    """
    Status display for OSOYOO 3.5" HDMI touch screen.

    Displays system status information including battery status, power source,
    OBD2 connection status, error counts, uptime, and IP address. Uses pygame
    for rendering with large, readable fonts.

    Attributes:
        refreshRate: Display refresh rate in seconds
        isAvailable: Whether display is available on this system
        isRunning: Whether the display is currently running

    Example:
        display = StatusDisplay(refreshRate=2.0)
        display.start()
        display.updateBatteryInfo(85, 4.1)
        display.updatePowerSource('external')
        display.stop()
    """

    def __init__(
        self,
        refreshRate: float = DEFAULT_REFRESH_RATE,
        width: int = DISPLAY_WIDTH,
        height: int = DISPLAY_HEIGHT
    ):
        """
        Initialize status display.

        Args:
            refreshRate: Display refresh rate in seconds (default: 2.0)
            width: Display width in pixels (default: 480)
            height: Display height in pixels (default: 320)

        Raises:
            ValueError: If refresh rate is not positive
        """
        if refreshRate <= 0:
            raise ValueError("Refresh rate must be positive")
        if width <= 0 or height <= 0:
            raise ValueError("Display dimensions must be positive")

        self._refreshRate = refreshRate
        self._width = width
        self._height = height

        # Display state
        self._isAvailable = False
        self._isRunning = False
        self._screen = None
        self._fonts = {}

        # Threading
        self._refreshThread: threading.Thread | None = None
        self._stopEvent = threading.Event()
        self._dataLock = threading.Lock()

        # Display data (protected by _dataLock)
        self._batteryPercentage: int | None = None
        self._batteryVoltage: float | None = None
        self._powerSource: PowerSourceDisplay = PowerSourceDisplay.UNKNOWN
        self._obdStatus: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self._warningCount: int = 0
        self._errorCount: int = 0
        self._startTime = time.time()

        # Callbacks
        self._onDisplayError: Callable[[Exception], None] | None = None

        # Error tracking for log spam suppression
        self._consecutiveRefreshErrors: int = 0

        # Check availability
        self._checkAvailability()

        logger.debug(
            f"StatusDisplay initialized: {width}x{height}, "
            f"refreshRate={refreshRate}s, available={self._isAvailable}"
        )

    def _checkAvailability(self) -> None:
        """Check if display is available on this system."""
        if not isRaspberryPi():
            logger.warning(
                "Display not available - not running on Raspberry Pi. "
                "Status display will be disabled."
            )
            self._isAvailable = False
            return

        try:
            # Try to import pygame
            import pygame  # noqa: F401
            self._isAvailable = True
        except (ImportError, RuntimeError) as e:
            logger.warning(f"Display not available - pygame import failed: {e}")
            self._isAvailable = False

    def _initializePygame(self) -> bool:
        """
        Initialize pygame display and fonts.

        Returns:
            True if initialization succeeded, False otherwise
        """
        try:
            import pygame

            # Initialize pygame
            pygame.init()
            pygame.font.init()

            # Create display surface
            self._screen = pygame.display.set_mode(
                (self._width, self._height),
                pygame.NOFRAME  # No window decorations for embedded display
            )
            pygame.display.set_caption("Eclipse OBD-II Status")

            # Hide mouse cursor for touch display
            pygame.mouse.set_visible(False)

            # Initialize fonts
            self._fonts = {
                'large': pygame.font.SysFont('arial', FONT_SIZE_LARGE, bold=True),
                'medium': pygame.font.SysFont('arial', FONT_SIZE_MEDIUM),
                'small': pygame.font.SysFont('arial', FONT_SIZE_SMALL),
            }

            logger.info(f"Pygame display initialized: {self._width}x{self._height}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize pygame display: {e}")
            return False

    def _shutdownPygame(self) -> None:
        """Shutdown pygame and release resources."""
        try:
            import pygame
            pygame.quit()
            self._screen = None
            self._fonts = {}
            logger.debug("Pygame shutdown complete")
        except Exception as e:
            logger.warning(f"Error during pygame shutdown: {e}")

    def start(self) -> bool:
        """
        Start the status display.

        Returns:
            True if display started successfully, False if unavailable

        Raises:
            StatusDisplayError: If display is already running
        """
        if self._isRunning:
            raise StatusDisplayError("Display is already running")

        if not self._isAvailable:
            logger.warning(
                "Cannot start status display - display not available. "
                "Running in disabled mode."
            )
            return False

        # Initialize pygame
        if not self._initializePygame():
            logger.error("Failed to initialize pygame - display disabled")
            return False

        self._stopEvent.clear()
        self._isRunning = True
        self._startTime = time.time()

        # Start refresh thread
        self._refreshThread = threading.Thread(
            target=self._refreshLoop,
            name="StatusDisplayRefresh",
            daemon=True
        )
        self._refreshThread.start()

        logger.info(f"Status display started with refresh rate {self._refreshRate}s")
        return True

    def stop(self) -> None:
        """
        Stop the status display.

        Safe to call multiple times or when not running.
        """
        if not self._isRunning:
            return

        self._stopEvent.set()

        if self._refreshThread is not None and self._refreshThread.is_alive():
            self._refreshThread.join(timeout=5.0)

        self._shutdownPygame()
        self._isRunning = False
        self._refreshThread = None

        logger.info("Status display stopped")

    def _refreshLoop(self) -> None:
        """Background loop for refreshing the display."""
        import pygame

        while not self._stopEvent.is_set():
            try:
                # Handle pygame events to prevent freezing
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._stopEvent.set()
                        return

                # Render display
                self._render()
                self._consecutiveRefreshErrors = 0

            except Exception as e:
                self._consecutiveRefreshErrors += 1
                if self._consecutiveRefreshErrors == 1:
                    logger.error(f"Error in display refresh loop: {e}")
                elif self._consecutiveRefreshErrors == 3:
                    logger.warning(
                        "Display refresh errors continue. "
                        "Suppressing further error logs (logging at DEBUG)."
                    )
                if self._consecutiveRefreshErrors >= 3:
                    logger.debug(f"Display refresh error (repeated): {e}")

                if self._onDisplayError is not None:
                    try:
                        self._onDisplayError(e)
                    except Exception as callbackErr:
                        logger.error(f"Error in display error callback: {callbackErr}")

            # Wait for next refresh interval (or stop signal)
            self._stopEvent.wait(timeout=self._refreshRate)

    def _render(self) -> None:
        """Render the status display."""
        if self._screen is None:
            return

        import pygame

        # Clear screen
        self._screen.fill(COLOR_BLACK)

        y = PADDING

        # Title
        y = self._renderTitle(y)

        # Battery status
        y = self._renderBatteryStatus(y)

        # Power source
        y = self._renderPowerSource(y)

        # OBD2 status
        y = self._renderObdStatus(y)

        # Error/warning count
        y = self._renderErrorCount(y)

        # System info (uptime, IP)
        y = self._renderSystemInfo(y)

        # Update display
        pygame.display.flip()

    def _renderTitle(self, y: int) -> int:
        """Render the title section."""
        text = self._fonts['large'].render("Eclipse OBD-II", True, COLOR_BLUE)
        self._screen.blit(text, (PADDING, y))
        return y + LINE_HEIGHT_LARGE + 5

    def _renderBatteryStatus(self, y: int) -> int:
        """Render battery status section."""
        with self._dataLock:
            percentage = self._batteryPercentage
            voltage = self._batteryVoltage

        # Label
        label = self._fonts['medium'].render("Battery:", True, COLOR_WHITE)
        self._screen.blit(label, (PADDING, y))

        # Value with color coding
        if percentage is not None and voltage is not None:
            # Color based on battery level
            if percentage >= 50:
                color = COLOR_GREEN
            elif percentage >= 20:
                color = COLOR_ORANGE
            else:
                color = COLOR_RED

            valueStr = f"{percentage}% ({voltage:.2f}V)"
        else:
            color = COLOR_GRAY
            valueStr = "N/A"

        value = self._fonts['medium'].render(valueStr, True, color)
        self._screen.blit(value, (150, y))

        return y + LINE_HEIGHT_MEDIUM

    def _renderPowerSource(self, y: int) -> int:
        """Render power source section."""
        with self._dataLock:
            source = self._powerSource

        # Label
        label = self._fonts['medium'].render("Power:", True, COLOR_WHITE)
        self._screen.blit(label, (PADDING, y))

        # Value with color coding
        if source == PowerSourceDisplay.CAR:
            color = COLOR_GREEN
        elif source == PowerSourceDisplay.BATTERY:
            color = COLOR_ORANGE
        else:
            color = COLOR_GRAY

        value = self._fonts['medium'].render(source.value, True, color)
        self._screen.blit(value, (150, y))

        return y + LINE_HEIGHT_MEDIUM

    def _renderObdStatus(self, y: int) -> int:
        """Render OBD2 connection status section."""
        with self._dataLock:
            status = self._obdStatus

        # Label
        label = self._fonts['medium'].render("OBD2:", True, COLOR_WHITE)
        self._screen.blit(label, (PADDING, y))

        # Value with color coding
        if status == ConnectionStatus.CONNECTED:
            color = COLOR_GREEN
        elif status == ConnectionStatus.RECONNECTING:
            color = COLOR_ORANGE
        else:
            color = COLOR_RED

        value = self._fonts['medium'].render(status.value, True, color)
        self._screen.blit(value, (150, y))

        return y + LINE_HEIGHT_MEDIUM

    def _renderErrorCount(self, y: int) -> int:
        """Render error/warning count section."""
        with self._dataLock:
            warnings = self._warningCount
            errors = self._errorCount

        # Label
        label = self._fonts['medium'].render("Issues:", True, COLOR_WHITE)
        self._screen.blit(label, (PADDING, y))

        # Value with color coding
        if errors > 0:
            color = COLOR_RED
            valueStr = f"{errors} errors"
        elif warnings > 0:
            color = COLOR_ORANGE
            valueStr = f"{warnings} warnings"
        else:
            color = COLOR_GREEN
            valueStr = "None"

        value = self._fonts['medium'].render(valueStr, True, color)
        self._screen.blit(value, (150, y))

        return y + LINE_HEIGHT_MEDIUM

    def _renderSystemInfo(self, y: int) -> int:
        """Render system info section (uptime, IP)."""
        # Uptime
        uptime = time.time() - self._startTime
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptimeStr = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        uptimeLabel = self._fonts['small'].render("Uptime:", True, COLOR_GRAY)
        self._screen.blit(uptimeLabel, (PADDING, y))
        uptimeValue = self._fonts['small'].render(uptimeStr, True, COLOR_WHITE)
        self._screen.blit(uptimeValue, (100, y))

        y += LINE_HEIGHT_MEDIUM

        # IP Address
        ipAddress = self._getIpAddress()
        ipLabel = self._fonts['small'].render("IP:", True, COLOR_GRAY)
        self._screen.blit(ipLabel, (PADDING, y))
        ipValue = self._fonts['small'].render(ipAddress, True, COLOR_WHITE)
        self._screen.blit(ipValue, (100, y))

        return y + LINE_HEIGHT_MEDIUM

    def _getIpAddress(self) -> str:
        """Get the local IP address."""
        try:
            # Create a dummy socket to determine the IP address
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                # Doesn't need to be reachable
                s.connect(("10.255.255.255", 1))
                ip = s.getsockname()[0]
            except Exception:
                ip = "127.0.0.1"
            finally:
                s.close()
            return ip
        except Exception:
            return "N/A"

    # ================================================================================
    # Data Update Methods
    # ================================================================================

    def updateBatteryInfo(
        self,
        percentage: int | None = None,
        voltage: float | None = None
    ) -> None:
        """
        Update battery status information.

        Args:
            percentage: Battery percentage (0-100)
            voltage: Battery voltage in volts
        """
        with self._dataLock:
            if percentage is not None:
                self._batteryPercentage = max(0, min(100, percentage))
            if voltage is not None:
                self._batteryVoltage = voltage

    def updatePowerSource(self, source: str) -> None:
        """
        Update power source display.

        Args:
            source: Power source ('external'/'car' or 'battery')
        """
        with self._dataLock:
            sourceLower = source.lower()
            if sourceLower in ('external', 'car'):
                self._powerSource = PowerSourceDisplay.CAR
            elif sourceLower == 'battery':
                self._powerSource = PowerSourceDisplay.BATTERY
            else:
                self._powerSource = PowerSourceDisplay.UNKNOWN

    def updateObdStatus(self, status: str) -> None:
        """
        Update OBD2 connection status.

        Args:
            status: Connection status ('connected', 'disconnected', 'reconnecting')
        """
        with self._dataLock:
            statusLower = status.lower()
            if statusLower == 'connected':
                self._obdStatus = ConnectionStatus.CONNECTED
            elif statusLower == 'reconnecting':
                self._obdStatus = ConnectionStatus.RECONNECTING
            else:
                self._obdStatus = ConnectionStatus.DISCONNECTED

    def updateErrorCount(self, warnings: int = 0, errors: int = 0) -> None:
        """
        Update error and warning counts.

        Args:
            warnings: Number of warnings
            errors: Number of errors
        """
        with self._dataLock:
            self._warningCount = max(0, warnings)
            self._errorCount = max(0, errors)

    # ================================================================================
    # Properties
    # ================================================================================

    @property
    def refreshRate(self) -> float:
        """Get the display refresh rate in seconds."""
        return self._refreshRate

    @refreshRate.setter
    def refreshRate(self, value: float) -> None:
        """Set the display refresh rate in seconds."""
        if value <= 0:
            raise ValueError("Refresh rate must be positive")
        self._refreshRate = value

    @property
    def isAvailable(self) -> bool:
        """Check if display is available on this system."""
        return self._isAvailable

    @property
    def isRunning(self) -> bool:
        """Check if the display is currently running."""
        return self._isRunning

    @property
    def width(self) -> int:
        """Get the display width in pixels."""
        return self._width

    @property
    def height(self) -> int:
        """Get the display height in pixels."""
        return self._height

    @property
    def batteryPercentage(self) -> int | None:
        """Get the current battery percentage."""
        with self._dataLock:
            return self._batteryPercentage

    @property
    def batteryVoltage(self) -> float | None:
        """Get the current battery voltage."""
        with self._dataLock:
            return self._batteryVoltage

    @property
    def powerSource(self) -> PowerSourceDisplay:
        """Get the current power source display value."""
        with self._dataLock:
            return self._powerSource

    @property
    def obdStatus(self) -> ConnectionStatus:
        """Get the current OBD2 connection status."""
        with self._dataLock:
            return self._obdStatus

    @property
    def uptime(self) -> float:
        """Get the display uptime in seconds."""
        return time.time() - self._startTime

    @property
    def onDisplayError(self) -> Callable[[Exception], None] | None:
        """Get the display error callback."""
        return self._onDisplayError

    @onDisplayError.setter
    def onDisplayError(self, callback: Callable[[Exception], None] | None) -> None:
        """
        Set the display error callback.

        Args:
            callback: Function to call on display errors, or None to clear
        """
        self._onDisplayError = callback

    # ================================================================================
    # Lifecycle Methods
    # ================================================================================

    def close(self) -> None:
        """
        Close the display and release resources.

        Safe to call multiple times.
        """
        self.stop()
        logger.debug("StatusDisplay closed")

    def __enter__(self) -> 'StatusDisplay':
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close the display."""
        self.close()

    def __del__(self) -> None:
        """Destructor - ensure resources are released."""
        # Check for _stopEvent to handle partially initialized objects
        if hasattr(self, '_stopEvent'):
            self.close()
