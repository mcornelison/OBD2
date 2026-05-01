################################################################################
# File Name: status_display.py
# Purpose/Description: Status display module using pygame, canvas-aware layout
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial implementation for US-RPI-010
# 2026-04-19    | Ralph Agent  | US-198 (TD-024): force SDL software renderer via
#               |              | env hints before pygame.init to prevent GL
#               |              | BadAccess crash under X11. New constructor arg
#               |              | forceSoftwareRenderer (default True).
# 2026-05-01    | Rex          | US-257 (B-052): full-canvas redesign. Replaced
#               |              | hardcoded 480x320 vertical-strip render with a
#               |              | proportional 4-quadrant layout (engine NW /
#               |              | power NE / drive SW / alerts SE) sourced from
#               |              | pi.hardware.dashboard_layout.computeLayout.
#               |              | Added updateShutdownStage so the power
#               |              | quadrant surfaces the staged-shutdown ladder
#               |              | (NORMAL=green / WARNING=amber / IMMINENT=
#               |              | orange / TRIGGER=red). Backwards-compat: the
#               |              | constructor still accepts width=480 height=320
#               |              | for legacy dev/testing.
# ================================================================================
################################################################################

"""
Status display module for the Eclipse OBD-II HDMI dashboard.

This module provides a canvas-aware status display showing:
- NW quadrant: battery percentage and voltage
- NE quadrant: power source + staged-shutdown stage indicator
- SW quadrant: OBD2 connection status
- SE quadrant: warning and error counts
- footer: uptime and IP address

The display is rendered using pygame. Geometry comes from
``pi.hardware.dashboard_layout.computeLayout(width, height)`` so the same
codepath drives the legacy 480x320 OSOYOO touchscreen and a 1920x1080 HDMI
screen plugged into the Eclipse.

Usage:
    from pi.hardware.status_display import StatusDisplay
    from pi.hardware.dashboard_layout import ShutdownStage

    display = StatusDisplay(width=1920, height=1080)
    display.start()
    display.updateBatteryInfo(percentage=85, voltage=4.1)
    display.updatePowerSource('external')
    display.updateShutdownStage(ShutdownStage.WARNING)
    display.stop()

Note:
    On non-Raspberry Pi systems, the display handler logs a warning
    and operates in a disabled mode where no pygame operations occur.
"""

import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from enum import Enum

from .dashboard_layout import (
    COLOR_BLACK,
    COLOR_BLUE,
    COLOR_GRAY,
    COLOR_GREEN,
    COLOR_ORANGE,
    COLOR_RED,
    COLOR_WHITE,
    STAGE_COLORS,
    DashboardLayout,
    Rect,
    ShutdownStage,
    computeLayout,
)
from .platform_utils import isRaspberryPi

logger = logging.getLogger(__name__)


# SDL env hints forcing the software renderer path. Set BEFORE pygame.init() --
# hints registered after SDL video subsystem initialization are ignored.
# TD-024: pygame's wheel-bundled SDL2 defaulted to an EGL/GL context on X11 and
# the X server denied GLX with BadAccess, killing the orchestrator runLoop at
# uptime=0.6s. The software path renders visibly and avoids GL entirely.
_SDL_SOFTWARE_RENDERER_HINTS: dict[str, str] = {
    "SDL_RENDER_DRIVER": "software",
    "SDL_VIDEO_X11_FORCE_EGL": "0",
    "SDL_FRAMEBUFFER_ACCELERATION": "0",
}


def _applySoftwareRendererHints() -> None:
    """Install SDL software-renderer hints, preserving any operator overrides."""
    for key, value in _SDL_SOFTWARE_RENDERER_HINTS.items():
        if key not in os.environ:
            os.environ[key] = value


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


# Legacy display dimensions (OSOYOO 3.5" HDMI touch screen, dev/test fallback).
DISPLAY_WIDTH = 480
DISPLAY_HEIGHT = 320

# Default refresh rate in seconds
DEFAULT_REFRESH_RATE = 2.0


# ================================================================================
# Status Display Class
# ================================================================================


class StatusDisplay:
    """
    Canvas-aware status display rendered via pygame.

    Renders a 4-quadrant dashboard (engine NW / power NE / drive SW / alerts
    SE) sized to the constructor's (width, height) so the same code drives
    the legacy 480x320 touchscreen and a 1920x1080 HDMI screen.

    Attributes:
        refreshRate: Display refresh rate in seconds
        isAvailable: Whether display is available on this system
        isRunning: Whether the display is currently running

    Example:
        display = StatusDisplay(width=1920, height=1080, refreshRate=2.0)
        display.start()
        display.updateBatteryInfo(85, 4.1)
        display.updatePowerSource('external')
        display.stop()
    """

    def __init__(
        self,
        refreshRate: float = DEFAULT_REFRESH_RATE,
        width: int = DISPLAY_WIDTH,
        height: int = DISPLAY_HEIGHT,
        forceSoftwareRenderer: bool = True
    ):
        """
        Initialize status display.

        Args:
            refreshRate: Display refresh rate in seconds (default: 2.0)
            width: Display width in pixels (default: 480)
            height: Display height in pixels (default: 320)
            forceSoftwareRenderer: Inject SDL hints that steer SDL2 to its
                software renderer before pygame.init (default: True). This is
                the TD-024 fix for GL BadAccess under X11. Set False only if
                you intentionally want the native renderer on a host known to
                grant GL contexts (e.g. a desktop Linux dev box).

        Raises:
            ValueError: If refresh rate is not positive or dimensions invalid
        """
        if refreshRate <= 0:
            raise ValueError("Refresh rate must be positive")
        if width <= 0 or height <= 0:
            raise ValueError("Display dimensions must be positive")

        self._refreshRate = refreshRate
        self._width = width
        self._height = height
        self._forceSoftwareRenderer = forceSoftwareRenderer

        # Layout computed once up-front; the same DashboardLayout instance is
        # reused on every render so quadrant rects + font sizes are stable.
        self._layout: DashboardLayout = computeLayout(width, height)

        # Display state
        self._isAvailable = False
        self._isRunning = False
        self._screen = None
        self._fonts: dict[str, object] = {}

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
        self._shutdownStage: ShutdownStage = ShutdownStage.NORMAL
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
            # SDL hints MUST be in the environment before pygame.init() --
            # SDL reads them during video subsystem startup and never re-checks.
            if self._forceSoftwareRenderer:
                _applySoftwareRendererHints()

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

            # Build fonts sized to the canvas via DashboardLayout.
            scale = self._layout.fonts
            self._fonts = {
                'title': pygame.font.SysFont('arial', scale.title, bold=True),
                'value': pygame.font.SysFont('arial', scale.value, bold=True),
                'label': pygame.font.SysFont('arial', scale.label),
                'detail': pygame.font.SysFont('arial', scale.detail),
            }

            logger.info(
                f"Pygame display initialized: {self._width}x{self._height}; "
                f"fonts title={scale.title} value={scale.value} "
                f"label={scale.label} detail={scale.detail}"
            )
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

    # ================================================================================
    # Rendering -- 4-quadrant dashboard
    # ================================================================================

    def _render(self) -> None:
        """Render one frame of the dashboard."""
        if self._screen is None:
            return

        import pygame

        self._screen.fill(COLOR_BLACK)

        self._renderEngineQuadrant(self._layout.engine)
        self._renderPowerQuadrant(self._layout.power)
        self._renderDriveQuadrant(self._layout.drive)
        self._renderAlertsQuadrant(self._layout.alerts)
        self._renderFooter(self._layout.footer)

        pygame.display.flip()

    def _drawText(
        self,
        text: str,
        rect: Rect,
        font: object,
        color: tuple[int, int, int],
        offsetX: int = 0,
        offsetY: int = 0,
    ) -> None:
        """Blit ``text`` inside ``rect`` at (rect.x+offsetX, rect.y+offsetY)."""
        rendered = font.render(text, True, color)
        self._screen.blit(rendered, (rect.x + offsetX, rect.y + offsetY))

    def _renderEngineQuadrant(self, rect: Rect) -> None:
        """NW: battery percentage + voltage (engine-side telemetry surface)."""
        with self._dataLock:
            percentage = self._batteryPercentage
            voltage = self._batteryVoltage

        padding = self._layout.padding
        labelFont = self._fonts['label']
        titleFont = self._fonts['title']

        self._drawText("Eclipse OBD-II", rect, labelFont, COLOR_BLUE,
                       offsetX=padding, offsetY=padding)

        if percentage is not None and voltage is not None:
            if percentage >= 50:
                color = COLOR_GREEN
            elif percentage >= 20:
                color = COLOR_ORANGE
            else:
                color = COLOR_RED
            valueStr = f"{percentage}%"
            detailStr = f"{voltage:.2f} V"
        else:
            color = COLOR_GRAY
            valueStr = "N/A"
            detailStr = ""

        valueY = rect.y + padding + labelFont.get_height() + padding
        self._drawText(valueStr, rect, titleFont, color,
                       offsetX=padding, offsetY=valueY - rect.y)

        if detailStr:
            detailFont = self._fonts['detail']
            detailY = valueY + titleFont.get_height() + padding // 2
            self._drawText(detailStr, rect, detailFont, COLOR_WHITE,
                           offsetX=padding, offsetY=detailY - rect.y)

    def _renderPowerQuadrant(self, rect: Rect) -> None:
        """NE: power source + staged-shutdown stage banner."""
        import pygame

        with self._dataLock:
            source = self._powerSource
            stage = self._shutdownStage

        padding = self._layout.padding
        labelFont = self._fonts['label']
        titleFont = self._fonts['title']
        detailFont = self._fonts['detail']

        # Stage color tints the entire power quadrant background so an operator
        # 6 feet from the screen can see WARNING/IMMINENT/TRIGGER at a glance.
        stageColor = STAGE_COLORS[stage]
        if stage is ShutdownStage.NORMAL:
            # Don't tint the entire panel green during normal operation; reserve
            # the alarming colors for actual stage transitions.
            tint: tuple[int, int, int] | None = None
        else:
            # Dim the stage color to roughly 40% intensity so foreground text
            # remains readable on top of the tinted background.
            tint = (stageColor[0] // 3, stageColor[1] // 3, stageColor[2] // 3)

        if tint is not None:
            pygame.draw.rect(self._screen, tint,
                             (rect.x, rect.y, rect.width, rect.height))

        self._drawText("Power", rect, labelFont, COLOR_WHITE,
                       offsetX=padding, offsetY=padding)

        if source == PowerSourceDisplay.CAR:
            sourceColor = COLOR_GREEN
        elif source == PowerSourceDisplay.BATTERY:
            sourceColor = COLOR_ORANGE
        else:
            sourceColor = COLOR_GRAY

        valueY = rect.y + padding + labelFont.get_height() + padding
        self._drawText(source.value, rect, titleFont, sourceColor,
                       offsetX=padding, offsetY=valueY - rect.y)

        stageY = valueY + titleFont.get_height() + padding
        stageStr = f"Stage: {stage.value.upper()}"
        self._drawText(stageStr, rect, detailFont, stageColor,
                       offsetX=padding, offsetY=stageY - rect.y)

    def _renderDriveQuadrant(self, rect: Rect) -> None:
        """SW: OBD2 connection status (the drive-side surface)."""
        with self._dataLock:
            status = self._obdStatus

        padding = self._layout.padding
        labelFont = self._fonts['label']
        titleFont = self._fonts['title']

        self._drawText("OBD2", rect, labelFont, COLOR_WHITE,
                       offsetX=padding, offsetY=padding)

        if status == ConnectionStatus.CONNECTED:
            color = COLOR_GREEN
        elif status == ConnectionStatus.RECONNECTING:
            color = COLOR_ORANGE
        else:
            color = COLOR_RED

        valueY = rect.y + padding + labelFont.get_height() + padding
        self._drawText(status.value, rect, titleFont, color,
                       offsetX=padding, offsetY=valueY - rect.y)

    def _renderAlertsQuadrant(self, rect: Rect) -> None:
        """SE: warning + error counts."""
        with self._dataLock:
            warnings = self._warningCount
            errors = self._errorCount

        padding = self._layout.padding
        labelFont = self._fonts['label']
        titleFont = self._fonts['title']

        self._drawText("Issues", rect, labelFont, COLOR_WHITE,
                       offsetX=padding, offsetY=padding)

        if errors > 0:
            color = COLOR_RED
            valueStr = f"{errors} errors"
        elif warnings > 0:
            color = COLOR_ORANGE
            valueStr = f"{warnings} warnings"
        else:
            color = COLOR_GREEN
            valueStr = "None"

        valueY = rect.y + padding + labelFont.get_height() + padding
        self._drawText(valueStr, rect, titleFont, color,
                       offsetX=padding, offsetY=valueY - rect.y)

    def _renderFooter(self, rect: Rect) -> None:
        """Bottom strip: uptime + IP."""
        padding = self._layout.padding
        detailFont = self._fonts['detail']

        uptime = time.time() - self._startTime
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptimeStr = f"Uptime {hours:02d}:{minutes:02d}:{seconds:02d}"

        self._drawText(uptimeStr, rect, detailFont, COLOR_GRAY,
                       offsetX=padding, offsetY=padding // 2)

        ipStr = f"IP {self._getIpAddress()}"
        ipText = detailFont.render(ipStr, True, COLOR_GRAY)
        ipWidth = ipText.get_width()
        self._screen.blit(
            ipText,
            (rect.x + rect.width - ipWidth - padding, rect.y + padding // 2),
        )

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

    def updateShutdownStage(self, stage: ShutdownStage | str) -> None:
        """
        Update the staged-shutdown stage indicator.

        Args:
            stage: ShutdownStage enum or its string value ("normal" / "warning"
                / "imminent" / "trigger"). Unknown strings are coerced to NORMAL.
        """
        with self._dataLock:
            if isinstance(stage, ShutdownStage):
                self._shutdownStage = stage
                return
            try:
                self._shutdownStage = ShutdownStage(stage.lower())
            except (AttributeError, ValueError):
                logger.warning(f"Unknown shutdown stage '{stage}' -- coerced to NORMAL")
                self._shutdownStage = ShutdownStage.NORMAL

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
    def layout(self) -> DashboardLayout:
        """Get the computed dashboard layout (quadrant rects + font scale)."""
        return self._layout

    @property
    def forceSoftwareRenderer(self) -> bool:
        """Whether SDL software-renderer hints are injected pre-pygame.init."""
        return self._forceSoftwareRenderer

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
    def shutdownStage(self) -> ShutdownStage:
        """Get the current staged-shutdown stage indicator."""
        with self._dataLock:
            return self._shutdownStage

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
