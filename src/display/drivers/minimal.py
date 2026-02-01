################################################################################
# File Name: minimal.py
# Purpose/Description: Minimal display driver for Adafruit 1.3" 240x240 TFT display
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation (US-005) - extracted from display_manager.py
# ================================================================================
################################################################################
"""
Minimal display driver implementation.

Shows status screen on Adafruit 1.3" 240x240 TFT display with:
- OBD-II connection status
- Database status
- Current RPM and coolant temp
- Active alerts
- Current profile name
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any

from display.types import AlertInfo, StatusInfo

from .base import BaseDisplayDriver

logger = logging.getLogger(__name__)

# Try to import Adafruit display adapter
# Note: On non-Raspberry Pi platforms, this may fail with NotImplementedError
try:
    from display.adapters.adafruit import (
        ADAFRUIT_AVAILABLE,
        AdafruitDisplayAdapter,
        isDisplayHardwareAvailable,
    )
except (ImportError, NotImplementedError, RuntimeError):
    ADAFRUIT_AVAILABLE = False

    def isDisplayHardwareAvailable() -> bool:
        return False

    AdafruitDisplayAdapter = None  # type: ignore


class NullDisplayAdapter:
    """
    Null adapter for testing - does nothing.

    Used when no display hardware is available.
    """

    def initialize(self) -> bool:
        """Initialize null adapter - always succeeds."""
        return True

    def shutdown(self) -> None:
        """Shutdown null adapter."""
        pass

    def clear(self) -> None:
        """Clear null adapter."""
        pass

    def drawText(
        self,
        x: int,
        y: int,
        text: str,
        size: str = 'normal',
        color: str = 'white'
    ) -> None:
        """Draw text (no-op)."""
        pass

    def drawLine(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: str = 'white'
    ) -> None:
        """Draw line (no-op)."""
        pass

    def fill(self, color: str) -> None:
        """Fill display (no-op)."""
        pass

    def refresh(self) -> None:
        """Refresh display (no-op)."""
        pass


class MinimalDisplayDriver(BaseDisplayDriver):
    """
    Minimal display driver - Adafruit 1.3" 240x240 TFT display.

    Shows status screen with:
    - OBD-II connection status
    - Database status
    - Current RPM and coolant temp
    - Active alerts
    - Current profile name

    The display is updated via the update() method which should be called
    periodically (e.g., every 1 second). Auto-refresh can be enabled to
    automatically update the display at the configured interval.

    Note: Actual Adafruit hardware support is implemented via the
    AdafruitDisplayAdapter class. If hardware is not available, the driver
    gracefully degrades to a null adapter for testing.
    """

    # Display dimensions
    WIDTH = 240
    HEIGHT = 240

    # Layout constants for 240x240 display
    HEADER_Y = 5
    HEADER_HEIGHT = 50
    MAIN_Y = 60
    MAIN_HEIGHT = 90
    ALERTS_Y = 155
    ALERTS_HEIGHT = 45
    FOOTER_Y = 205
    FOOTER_HEIGHT = 35

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize minimal display driver.

        Args:
            config: Optional configuration dictionary with keys:
                - refreshRateMs: Display refresh rate in milliseconds (default: 1000)
                - brightness: Display brightness 0-100 (default: 100)
                - autoRefresh: Enable auto-refresh thread (default: True)
                - useHardware: Try to use real hardware (default: True)
        """
        super().__init__(config)
        self._displayAdapter: Any | None = None
        self._refreshRateMs = config.get('refreshRateMs', 1000) if config else 1000
        self._brightness = config.get('brightness', 100) if config else 100
        self._lastUpdateTime: datetime | None = None
        self._autoRefreshEnabled = config.get('autoRefresh', True) if config else True
        self._autoRefreshThread: threading.Thread | None = None
        self._stopRefresh = threading.Event()
        self._useHardware = config.get('useHardware', True) if config else True

    def setDisplayAdapter(self, adapter: Any) -> None:
        """
        Set the display adapter for hardware communication.

        This allows dependency injection of the actual display hardware
        adapter for testing and modularity.

        Args:
            adapter: Display adapter instance with draw methods
        """
        self._displayAdapter = adapter

    def initialize(self) -> bool:
        """
        Initialize minimal display driver.

        Attempts to initialize the Adafruit display hardware. If hardware
        is not available or initialization fails, logs a warning and
        gracefully degrades to a null adapter (continues without display).

        Returns:
            True if display initialized, False otherwise
        """
        # If no adapter set, try to use real hardware or null adapter
        if self._displayAdapter is None:
            if self._useHardware and ADAFRUIT_AVAILABLE and AdafruitDisplayAdapter is not None:
                try:
                    self._displayAdapter = AdafruitDisplayAdapter(
                        config=self._config,
                        brightness=self._brightness
                    )
                    logger.info("Using Adafruit ST7789 hardware display adapter")
                except Exception as e:
                    logger.warning(f"Failed to create Adafruit adapter: {e}")
                    self._displayAdapter = None

            if self._displayAdapter is None:
                logger.warning(
                    "Adafruit display hardware not available - using null adapter. "
                    "Install adafruit-circuitpython-rgb-display for hardware support."
                )
                self._displayAdapter = NullDisplayAdapter()

        try:
            if hasattr(self._displayAdapter, 'initialize'):
                result = self._displayAdapter.initialize()
                if not result:
                    logger.warning(
                        "Display adapter initialization returned False. "
                        "Continuing without display."
                    )
                    self._initialized = False
                    return False

            self._initialized = True
            logger.info(
                f"Minimal display driver initialized "
                f"({self.WIDTH}x{self.HEIGHT}, refresh={self._refreshRateMs}ms)"
            )

            # Start auto-refresh thread if enabled
            if self._autoRefreshEnabled:
                self._startAutoRefresh()

            return True
        except Exception as e:
            logger.warning(
                f"Minimal display initialization failed: {e}. "
                "Continuing without display."
            )
            self._initialized = False
            return False

    def shutdown(self) -> None:
        """Shutdown minimal display driver and release hardware."""
        # Stop auto-refresh thread
        self._stopAutoRefresh()

        if self._displayAdapter and hasattr(self._displayAdapter, 'shutdown'):
            try:
                self._displayAdapter.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down display adapter: {e}")
        self._initialized = False
        logger.debug("Minimal display driver shutdown")

    def _startAutoRefresh(self) -> None:
        """Start the auto-refresh background thread."""
        if self._autoRefreshThread is not None:
            return

        self._stopRefresh.clear()
        self._autoRefreshThread = threading.Thread(
            target=self._autoRefreshLoop,
            name="DisplayAutoRefresh",
            daemon=True
        )
        self._autoRefreshThread.start()
        logger.debug(f"Auto-refresh started (interval={self._refreshRateMs}ms)")

    def _stopAutoRefresh(self) -> None:
        """Stop the auto-refresh background thread."""
        if self._autoRefreshThread is None:
            return

        self._stopRefresh.set()
        self._autoRefreshThread.join(timeout=2.0)
        self._autoRefreshThread = None
        logger.debug("Auto-refresh stopped")

    def _autoRefreshLoop(self) -> None:
        """Background thread loop for auto-refreshing the display."""
        intervalSec = self._refreshRateMs / 1000.0

        while not self._stopRefresh.is_set():
            try:
                if self._initialized and self._lastStatus:
                    self._renderStatusScreen(self._lastStatus)
            except Exception as e:
                logger.error(f"Error in auto-refresh loop: {e}")

            # Sleep in small intervals for responsive shutdown
            sleepTime = 0
            while sleepTime < intervalSec and not self._stopRefresh.is_set():
                time.sleep(0.1)
                sleepTime += 0.1

    def enableAutoRefresh(self, enabled: bool = True) -> None:
        """
        Enable or disable auto-refresh.

        Args:
            enabled: True to enable, False to disable
        """
        if enabled and not self._autoRefreshEnabled:
            self._autoRefreshEnabled = True
            if self._initialized:
                self._startAutoRefresh()
        elif not enabled and self._autoRefreshEnabled:
            self._autoRefreshEnabled = False
            self._stopAutoRefresh()

    def setRefreshRate(self, intervalMs: int) -> None:
        """
        Set the refresh rate in milliseconds.

        Args:
            intervalMs: Refresh interval in milliseconds (min 100ms)
        """
        self._refreshRateMs = max(100, intervalMs)

    def showStatus(self, status: StatusInfo) -> None:
        """
        Display status information on the 240x240 screen.

        Args:
            status: StatusInfo object with current status
        """
        self._lastStatus = status
        self._lastUpdateTime = datetime.now()

        if not self._initialized or self._displayAdapter is None:
            return

        try:
            self._renderStatusScreen(status)
        except Exception as e:
            logger.error(f"Error rendering status screen: {e}")

    def showAlert(self, alert: AlertInfo) -> None:
        """
        Display an alert on the screen.

        High priority alerts (1-2) override the status display.

        Args:
            alert: AlertInfo object with alert details
        """
        if not alert.acknowledged:
            self._activeAlerts.append(alert)

        if not self._initialized or self._displayAdapter is None:
            return

        try:
            if alert.priority <= 2:
                # High priority - show full screen alert
                self._renderAlertScreen(alert)
            else:
                # Lower priority - add to status screen alerts section
                if self._lastStatus:
                    self._renderStatusScreen(self._lastStatus)
        except Exception as e:
            logger.error(f"Error rendering alert: {e}")

    def clearDisplay(self) -> None:
        """Clear the display screen."""
        self._activeAlerts.clear()

        if not self._initialized or self._displayAdapter is None:
            return

        try:
            if hasattr(self._displayAdapter, 'clear'):
                self._displayAdapter.clear()
        except Exception as e:
            logger.error(f"Error clearing display: {e}")

    def _renderStatusScreen(self, status: StatusInfo) -> None:
        """
        Render the status screen layout for 240x240 display.

        Optimized layout for readability with clear fonts and icons:

        +---------------------------+  y=0
        |  [*] OBD: Connected       |  y=5  (status icons/text)
        |  [#] DB:  Ready           |  y=28
        +===========================+  y=55 (divider)
        |                           |
        |      RPM                  |  y=65  (label)
        |      2500                 |  y=85  (large value)
        |                           |
        |      COOLANT              |  y=115 (label)
        |      85 C                 |  y=135 (large value)
        |                           |
        +===========================+  y=155 (divider)
        |  ALERTS: none             |  y=160
        |  [first alert message]    |  y=180
        +===========================+  y=205 (divider)
        |  Profile: Daily           |  y=215
        +---------------------------+  y=240

        Args:
            status: StatusInfo to render
        """
        if not hasattr(self._displayAdapter, 'drawText'):
            return

        adapter = self._displayAdapter

        # Clear screen first
        if hasattr(adapter, 'clear'):
            adapter.clear()

        # === HEADER SECTION (y=5 to y=50) ===
        # Connection status with icon
        isConnected = status.connectionStatus.lower() in ('connected', 'ok', 'ready')
        connColor = 'green' if isConnected else 'red'
        connIcon = "[*]" if isConnected else "[!]"
        adapter.drawText(5, self.HEADER_Y, connIcon, size='normal', color=connColor)
        adapter.drawText(35, self.HEADER_Y, f"OBD: {status.connectionStatus[:15]}", color=connColor)

        # Database status with icon
        dbReady = status.databaseStatus.lower() in ('ready', 'ok', 'connected')
        dbColor = 'green' if dbReady else 'yellow'
        dbIcon = "[#]" if dbReady else "[?]"
        adapter.drawText(5, self.HEADER_Y + 23, dbIcon, size='normal', color=dbColor)
        adapter.drawText(35, self.HEADER_Y + 23, f"DB:  {status.databaseStatus[:15]}", color=dbColor)

        # Header divider
        if hasattr(adapter, 'drawLine'):
            adapter.drawLine(0, self.HEADER_Y + self.HEADER_HEIGHT, self.WIDTH, self.HEADER_Y + self.HEADER_HEIGHT, color='gray')

        # === MAIN VALUES SECTION (y=60 to y=150) ===
        # RPM display
        adapter.drawText(90, self.MAIN_Y + 5, "RPM", size='small', color='cyan')
        if status.currentRpm is not None:
            rpmText = f"{int(status.currentRpm)}"
            # Color based on RPM range
            if status.currentRpm > 6000:
                rpmColor = 'red'
            elif status.currentRpm > 4000:
                rpmColor = 'yellow'
            else:
                rpmColor = 'white'
        else:
            rpmText = "---"
            rpmColor = 'gray'
        # Center the RPM value
        adapter.drawText(70, self.MAIN_Y + 20, rpmText, size='xlarge', color=rpmColor)

        # Coolant Temperature display
        adapter.drawText(75, self.MAIN_Y + 55, "COOLANT", size='small', color='cyan')
        if status.coolantTemp is not None:
            tempText = f"{int(status.coolantTemp)} C"
            # Color based on temperature range
            if status.coolantTemp > 110:
                tempColor = 'red'
            elif status.coolantTemp > 100:
                tempColor = 'orange'
            elif status.coolantTemp < 60:
                tempColor = 'blue'
            else:
                tempColor = 'white'
        else:
            tempText = "--- C"
            tempColor = 'gray'
        adapter.drawText(70, self.MAIN_Y + 70, tempText, size='large', color=tempColor)

        # Main values divider
        if hasattr(adapter, 'drawLine'):
            adapter.drawLine(0, self.ALERTS_Y, self.WIDTH, self.ALERTS_Y, color='gray')

        # === ALERTS SECTION (y=155 to y=200) ===
        if status.activeAlerts and len(status.activeAlerts) > 0:
            alertCount = len(status.activeAlerts)
            alertColor = 'red' if alertCount > 2 else 'yellow'
            adapter.drawText(5, self.ALERTS_Y + 5, f"ALERTS: {alertCount}", size='normal', color=alertColor)
            # Show first alert message (truncated to fit)
            firstAlert = status.activeAlerts[0][:28]
            adapter.drawText(5, self.ALERTS_Y + 25, firstAlert, size='small', color=alertColor)
        else:
            adapter.drawText(5, self.ALERTS_Y + 5, "ALERTS: none", size='normal', color='green')

        # Footer divider
        if hasattr(adapter, 'drawLine'):
            adapter.drawLine(0, self.FOOTER_Y, self.WIDTH, self.FOOTER_Y, color='gray')

        # === FOOTER SECTION (y=205 to y=240) ===
        profileText = f"Profile: {status.profileName[:12]}"
        adapter.drawText(5, self.FOOTER_Y + 10, profileText, size='normal', color='white')

        # Power source indicator
        powerSource = getattr(status, 'powerSource', 'unknown')
        if powerSource == 'ac_power':
            powerIcon = "[~]"
            powerColor = 'green'
        elif powerSource == 'battery':
            powerIcon = "[B]"
            powerColor = 'yellow'
        else:
            powerIcon = "[?]"
            powerColor = 'gray'
        adapter.drawText(130, self.FOOTER_Y + 10, powerIcon, size='small', color=powerColor)

        # Timestamp in corner
        if status.timestamp:
            timeStr = status.timestamp.strftime("%H:%M:%S")
            adapter.drawText(175, self.FOOTER_Y + 10, timeStr, size='small', color='gray')

        # Refresh display to show changes
        if hasattr(adapter, 'refresh'):
            adapter.refresh()

    def _renderAlertScreen(self, alert: AlertInfo) -> None:
        """
        Render a full-screen alert.

        Args:
            alert: AlertInfo to render
        """
        if not hasattr(self._displayAdapter, 'drawText'):
            return

        adapter = self._displayAdapter

        # Clear and show alert background
        if hasattr(adapter, 'fill'):
            bgColor = 'red' if alert.priority == 1 else 'orange'
            adapter.fill(bgColor)

        # Alert text
        adapter.drawText(20, 80, "! ALERT !", size='large', color='white')
        adapter.drawText(20, 130, alert.message[:20], size='medium', color='white')

        if hasattr(adapter, 'refresh'):
            adapter.refresh()
