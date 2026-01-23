################################################################################
# File Name: display_manager.py
# Purpose/Description: Display mode management for OBD-II monitoring system
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-007
# 2026-01-22    | M. Cornelison | US-008: Added AdafruitDisplayAdapter integration
# 2026-01-22    | Ralph Agent  | US-004: Moved types/exceptions to display subpackage
# ================================================================================
################################################################################

"""
Display mode management module.

Provides configurable display output modes for the Eclipse OBD-II Performance
Monitoring System:

- **headless**: No display output, logs only (for background service operation)
- **minimal**: Adafruit 1.3" 240x240 display shows status screen (for in-vehicle use)
- **developer**: Detailed console logging of all operations (for debugging)

Usage:
    from obd.display_manager import DisplayManager, DisplayMode

    manager = DisplayManager(mode=DisplayMode.HEADLESS)
    manager.showStatus("Connected", details={"RPM": 2500})
    manager.showAlert("High Temp", priority=1)
"""

import logging
import sys
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

# Import types and exceptions from refactored modules
from obd.display.types import DisplayMode, StatusInfo, AlertInfo
from obd.display.exceptions import (
    DisplayError,
    DisplayInitializationError,
    DisplayOutputError,
)

logger = logging.getLogger(__name__)

# Try to import Adafruit display adapter
# Note: On non-Raspberry Pi platforms, this may fail with NotImplementedError
try:
    from obd.adafruit_display import (
        AdafruitDisplayAdapter,
        isDisplayHardwareAvailable,
        ADAFRUIT_AVAILABLE
    )
except (ImportError, NotImplementedError, RuntimeError):
    ADAFRUIT_AVAILABLE = False

    def isDisplayHardwareAvailable() -> bool:
        return False

    AdafruitDisplayAdapter = None  # type: ignore


class BaseDisplayDriver(ABC):
    """Abstract base class for display drivers."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize display driver.

        Args:
            config: Optional configuration dictionary
        """
        self._config = config or {}
        self._initialized = False
        self._lastStatus: Optional[StatusInfo] = None
        self._activeAlerts: List[AlertInfo] = []

    @property
    def isInitialized(self) -> bool:
        """Check if display is initialized."""
        return self._initialized

    @abstractmethod
    def initialize(self) -> bool:
        """
        Initialize the display driver.

        Returns:
            True if initialization successful, False otherwise
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown the display driver and release resources."""
        pass

    @abstractmethod
    def showStatus(self, status: StatusInfo) -> None:
        """
        Display status information.

        Args:
            status: StatusInfo object with current status
        """
        pass

    @abstractmethod
    def showAlert(self, alert: AlertInfo) -> None:
        """
        Display an alert.

        Args:
            alert: AlertInfo object with alert details
        """
        pass

    @abstractmethod
    def clearDisplay(self) -> None:
        """Clear the display output."""
        pass

    def getLastStatus(self) -> Optional[StatusInfo]:
        """Get the last displayed status."""
        return self._lastStatus

    def getActiveAlerts(self) -> List[AlertInfo]:
        """Get list of active alerts."""
        return self._activeAlerts.copy()


class HeadlessDisplayDriver(BaseDisplayDriver):
    """
    Headless display driver - no display output, logs only.

    Used for background service operation where no visual output is needed.
    All operations are logged at appropriate levels for monitoring.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._logLevel = logging.INFO

    def initialize(self) -> bool:
        """
        Initialize headless display driver.

        Always succeeds as no hardware is required.

        Returns:
            True (always successful)
        """
        logger.info("Headless display driver initialized - no visual output")
        self._initialized = True
        return True

    def shutdown(self) -> None:
        """Shutdown headless display driver."""
        logger.debug("Headless display driver shutdown")
        self._initialized = False

    def showStatus(self, status: StatusInfo) -> None:
        """
        Log status information.

        Args:
            status: StatusInfo object with current status
        """
        self._lastStatus = status
        logger.debug(
            f"Status: connection={status.connectionStatus}, "
            f"db={status.databaseStatus}, rpm={status.currentRpm}, "
            f"temp={status.coolantTemp}, profile={status.profileName}"
        )

    def showAlert(self, alert: AlertInfo) -> None:
        """
        Log alert information.

        Args:
            alert: AlertInfo object with alert details
        """
        if not alert.acknowledged:
            self._activeAlerts.append(alert)

        # Log at appropriate level based on priority
        if alert.priority <= 2:
            logger.warning(f"ALERT [P{alert.priority}]: {alert.message}")
        else:
            logger.info(f"Alert [P{alert.priority}]: {alert.message}")

    def clearDisplay(self) -> None:
        """Clear active alerts (no visual display to clear)."""
        self._activeAlerts.clear()
        logger.debug("Display cleared")


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

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._displayAdapter: Optional[Any] = None
        self._refreshRateMs = config.get('refreshRateMs', 1000) if config else 1000
        self._brightness = config.get('brightness', 100) if config else 100
        self._lastUpdateTime: Optional[datetime] = None
        self._autoRefreshEnabled = config.get('autoRefresh', True) if config else True
        self._autoRefreshThread: Optional[threading.Thread] = None
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
                self._displayAdapter = _NullDisplayAdapter()

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


class _NullDisplayAdapter:
    """Null adapter for testing - does nothing."""

    def initialize(self) -> bool:
        """Initialize null adapter - always succeeds."""
        return True

    def shutdown(self) -> None:
        pass

    def clear(self) -> None:
        pass

    def drawText(
        self,
        x: int,
        y: int,
        text: str,
        size: str = 'normal',
        color: str = 'white'
    ) -> None:
        pass

    def drawLine(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: str = 'white'
    ) -> None:
        pass

    def fill(self, color: str) -> None:
        pass

    def refresh(self) -> None:
        pass


class DeveloperDisplayDriver(BaseDisplayDriver):
    """
    Developer display driver - detailed console logging.

    Provides verbose output of all operations for debugging and development.
    Outputs to stdout with formatted display showing:
    - Timestamped status updates
    - Detailed parameter values
    - Alert history
    - Operation timing
    - SIM indicator when in simulation mode
    - Current scenario phase (if running scenario)
    - Active failure injections
    """

    # ANSI color codes for terminal output
    COLORS = {
        'reset': '\033[0m',
        'red': '\033[91m',
        'green': '\033[92m',
        'yellow': '\033[93m',
        'blue': '\033[94m',
        'magenta': '\033[95m',
        'cyan': '\033[96m',
        'white': '\033[97m',
        'bold': '\033[1m',
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._useColors = config.get('useColors', True) if config else True
        self._showTimestamps = config.get('showTimestamps', True) if config else True
        self._outputStream = sys.stdout
        self._statusUpdateCount = 0
        self._alertCount = 0
        self._isSimulationMode = False
        self._simulatorStatus: Optional[Any] = None  # SimulatorStatus

    def setOutputStream(self, stream: Any) -> None:
        """
        Set the output stream for console output.

        Args:
            stream: Output stream (default: sys.stdout)
        """
        self._outputStream = stream

    def setSimulationMode(self, enabled: bool) -> None:
        """
        Set whether the system is in simulation mode.

        When enabled, the SIM indicator will be shown prominently
        in status output.

        Args:
            enabled: True to enable simulation mode display
        """
        self._isSimulationMode = enabled

    def setSimulatorStatus(self, status: Any) -> None:
        """
        Set the current simulator status for display.

        Args:
            status: SimulatorStatus object with current simulator state
        """
        self._simulatorStatus = status

    def getSimulatorStatus(self) -> Optional[Any]:
        """
        Get the current simulator status.

        Returns:
            SimulatorStatus object or None if not set
        """
        return self._simulatorStatus

    def initialize(self) -> bool:
        """
        Initialize developer display driver.

        Returns:
            True (always successful)
        """
        self._print(
            f"\n{'='*60}\n"
            f"  Eclipse OBD-II Performance Monitor - Developer Mode\n"
            f"{'='*60}\n"
        )
        self._initialized = True
        logger.info("Developer display driver initialized - verbose console output enabled")
        return True

    def shutdown(self) -> None:
        """Shutdown developer display driver."""
        self._print(
            f"\n{'='*60}\n"
            f"  Developer Mode Shutdown\n"
            f"  Status updates: {self._statusUpdateCount}\n"
            f"  Alerts shown: {self._alertCount}\n"
            f"{'='*60}\n"
        )
        self._initialized = False

    def showStatus(self, status: StatusInfo) -> None:
        """
        Display detailed status information to console.

        Args:
            status: StatusInfo object with current status
        """
        self._lastStatus = status
        self._statusUpdateCount += 1

        timestamp = self._getTimestamp()
        connColor = 'green' if status.connectionStatus == 'Connected' else 'red'
        dbColor = 'green' if status.databaseStatus == 'Ready' else 'yellow'

        # Build header with SIM indicator if in simulation mode
        header = f"\n{self._color('cyan', '--- STATUS UPDATE ---')}"
        if self._isSimulationMode:
            simIndicator = self._color('bold', self._color('magenta', '[SIM]'))
            header = f"\n{simIndicator} {self._color('cyan', '--- STATUS UPDATE ---')}"
        header += timestamp

        output = [
            header,
            f"  Connection: {self._color(connColor, status.connectionStatus)}",
            f"  Database:   {self._color(dbColor, status.databaseStatus)}",
            f"  RPM:        {status.currentRpm if status.currentRpm else '---'}",
            f"  Coolant:    {status.coolantTemp if status.coolantTemp else '---'} C",
            f"  Profile:    {status.profileName}",
            f"  Alerts:     {len(status.activeAlerts)}"
        ]

        # Add simulator status section if in simulation mode
        if self._isSimulationMode and self._simulatorStatus is not None:
            simStatus = self._simulatorStatus
            output.append(f"\n  {self._color('magenta', '--- SIMULATOR STATUS ---')}")

            # Show scenario info if available
            if simStatus.scenarioName:
                scenarioInfo = f"  Scenario:   {simStatus.scenarioName}"
                if simStatus.currentPhase:
                    scenarioInfo += f" [{simStatus.currentPhase}]"
                output.append(scenarioInfo)

                # Show progress
                progressBar = self._renderProgressBar(simStatus.scenarioProgress)
                output.append(f"  Progress:   {progressBar} {simStatus.scenarioProgress:.1f}%")

                # Show elapsed time
                elapsed = simStatus.elapsedSeconds
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                output.append(f"  Elapsed:    {mins}m {secs}s")

                # Show loops if applicable
                if simStatus.loopsCompleted > 0:
                    output.append(f"  Loops:      {simStatus.loopsCompleted}")

            # Show active failures
            if simStatus.activeFailures:
                failuresColor = 'red' if len(simStatus.activeFailures) > 0 else 'green'
                output.append(f"  Failures:   {self._color(failuresColor, ', '.join(simStatus.activeFailures))}")
            else:
                output.append(f"  Failures:   {self._color('green', 'none')}")

        if status.activeAlerts:
            output.append(f"  Active alerts:")
            for alert in status.activeAlerts[:3]:  # Show first 3
                output.append(f"    - {alert}")

        self._print('\n'.join(output))

    def showAlert(self, alert: AlertInfo) -> None:
        """
        Display alert with detailed information.

        Args:
            alert: AlertInfo object with alert details
        """
        if not alert.acknowledged:
            self._activeAlerts.append(alert)
        self._alertCount += 1

        timestamp = self._getTimestamp()
        priorityColor = 'red' if alert.priority <= 2 else 'yellow'

        output = [
            f"\n{self._color('bold', self._color(priorityColor, '!!! ALERT !!!'))}{timestamp}",
            f"  Priority: {self._color(priorityColor, f'P{alert.priority}')}",
            f"  Message:  {alert.message}",
        ]

        self._print('\n'.join(output))

    def clearDisplay(self) -> None:
        """Clear display state and show clear message."""
        self._activeAlerts.clear()
        self._print(f"\n{self._color('cyan', '--- DISPLAY CLEARED ---')}")

    def _print(self, message: str) -> None:
        """
        Print message to output stream.

        Args:
            message: Message to print
        """
        try:
            print(message, file=self._outputStream, flush=True)
        except Exception as e:
            logger.error(f"Error writing to output stream: {e}")

    def _getTimestamp(self) -> str:
        """Get formatted timestamp string."""
        if not self._showTimestamps:
            return ""
        return f" [{datetime.now().strftime('%H:%M:%S.%f')[:-3]}]"

    def _color(self, color: str, text: str) -> str:
        """
        Apply ANSI color to text.

        Args:
            color: Color name
            text: Text to colorize

        Returns:
            Colorized text (or original if colors disabled)
        """
        if not self._useColors:
            return text
        colorCode = self.COLORS.get(color, '')
        resetCode = self.COLORS.get('reset', '')
        return f"{colorCode}{text}{resetCode}"

    def _renderProgressBar(self, percent: float, width: int = 20) -> str:
        """
        Render a text-based progress bar.

        Args:
            percent: Progress percentage (0-100)
            width: Width of the progress bar in characters

        Returns:
            Progress bar string like [=========>         ]
        """
        percent = max(0, min(100, percent))
        filledWidth = int((percent / 100) * width)
        emptyWidth = width - filledWidth

        if filledWidth > 0:
            bar = "=" * (filledWidth - 1) + ">"
        else:
            bar = ""
        bar += " " * emptyWidth

        return f"[{bar}]"


class DisplayManager:
    """
    Main display manager class.

    Manages display output based on configured mode. Provides a unified
    interface for status updates and alerts across all display modes.

    Usage:
        # From config
        manager = DisplayManager.fromConfig(config)

        # Or directly
        manager = DisplayManager(mode=DisplayMode.DEVELOPER)

        # Initialize
        if manager.initialize():
            # Show status
            status = StatusInfo(connectionStatus="Connected", currentRpm=2500)
            manager.showStatus(status)

            # Show alert
            alert = AlertInfo(message="High Temperature", priority=1)
            manager.showAlert(alert)

        # Cleanup
        manager.shutdown()
    """

    def __init__(
        self,
        mode: DisplayMode = DisplayMode.HEADLESS,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize DisplayManager.

        Args:
            mode: Display mode to use
            config: Optional configuration dictionary
        """
        self._mode = mode
        self._config = config or {}
        self._driver: Optional[BaseDisplayDriver] = None
        self._initialized = False
        self._callbacks: Dict[str, List[Callable]] = {
            'status_update': [],
            'alert': [],
            'mode_change': [],
        }

        # Create appropriate driver based on mode
        self._driver = self._createDriver(mode, config)

    @classmethod
    def fromConfig(cls, config: Dict[str, Any]) -> 'DisplayManager':
        """
        Create DisplayManager from configuration dictionary.

        Args:
            config: Configuration dictionary with 'display' section

        Returns:
            Configured DisplayManager instance
        """
        displayConfig = config.get('display', {})
        modeStr = displayConfig.get('mode', 'headless')

        try:
            mode = DisplayMode.fromString(modeStr)
        except ValueError:
            logger.warning(
                f"Invalid display mode '{modeStr}', defaulting to headless"
            )
            mode = DisplayMode.HEADLESS

        return cls(mode=mode, config=displayConfig)

    def _createDriver(
        self,
        mode: DisplayMode,
        config: Optional[Dict[str, Any]]
    ) -> BaseDisplayDriver:
        """
        Create display driver for the specified mode.

        Args:
            mode: Display mode
            config: Configuration dictionary

        Returns:
            Display driver instance
        """
        if mode == DisplayMode.HEADLESS:
            return HeadlessDisplayDriver(config)
        elif mode == DisplayMode.MINIMAL:
            return MinimalDisplayDriver(config)
        elif mode == DisplayMode.DEVELOPER:
            return DeveloperDisplayDriver(config)
        else:
            # Fallback to headless
            logger.warning(f"Unknown mode {mode}, using headless")
            return HeadlessDisplayDriver(config)

    @property
    def mode(self) -> DisplayMode:
        """Get current display mode."""
        return self._mode

    @property
    def isInitialized(self) -> bool:
        """Check if display manager is initialized."""
        return self._initialized

    def initialize(self) -> bool:
        """
        Initialize the display driver.

        Returns:
            True if initialization successful, False otherwise
        """
        if self._driver is None:
            logger.error("No display driver available")
            return False

        try:
            result = self._driver.initialize()
            self._initialized = result
            logger.info(f"Display manager initialized in {self._mode.value} mode")
            return result
        except Exception as e:
            logger.error(f"Display initialization failed: {e}")
            self._initialized = False
            return False

    def shutdown(self) -> None:
        """Shutdown the display driver."""
        if self._driver:
            try:
                self._driver.shutdown()
            except Exception as e:
                logger.error(f"Error during display shutdown: {e}")
        self._initialized = False
        logger.debug("Display manager shutdown")

    def showStatus(
        self,
        connectionStatus: str = "Unknown",
        databaseStatus: str = "Unknown",
        currentRpm: Optional[float] = None,
        coolantTemp: Optional[float] = None,
        activeAlerts: Optional[List[str]] = None,
        profileName: str = "daily",
        powerSource: str = "unknown"
    ) -> None:
        """
        Display status information.

        Args:
            connectionStatus: OBD-II connection status
            databaseStatus: Database status
            currentRpm: Current RPM value
            coolantTemp: Coolant temperature
            activeAlerts: List of active alert messages
            profileName: Current profile name
            powerSource: Current power source (ac_power, battery, unknown)
        """
        status = StatusInfo(
            connectionStatus=connectionStatus,
            databaseStatus=databaseStatus,
            currentRpm=currentRpm,
            coolantTemp=coolantTemp,
            activeAlerts=activeAlerts or [],
            profileName=profileName,
            timestamp=datetime.now(),
            powerSource=powerSource
        )

        if self._driver:
            self._driver.showStatus(status)

        # Trigger callbacks
        for callback in self._callbacks.get('status_update', []):
            try:
                callback(status)
            except Exception as e:
                logger.error(f"Status callback error: {e}")

    def showStatusInfo(self, status: StatusInfo) -> None:
        """
        Display status from StatusInfo object.

        Args:
            status: StatusInfo object
        """
        if self._driver:
            self._driver.showStatus(status)

        for callback in self._callbacks.get('status_update', []):
            try:
                callback(status)
            except Exception as e:
                logger.error(f"Status callback error: {e}")

    def showAlert(
        self,
        message: str,
        priority: int = 3,
        acknowledged: bool = False
    ) -> None:
        """
        Display an alert.

        Args:
            message: Alert message
            priority: Alert priority (1-5, 1 is highest)
            acknowledged: Whether alert has been acknowledged
        """
        alert = AlertInfo(
            message=message,
            priority=priority,
            timestamp=datetime.now(),
            acknowledged=acknowledged
        )

        if self._driver:
            self._driver.showAlert(alert)

        # Trigger callbacks
        for callback in self._callbacks.get('alert', []):
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    def showAlertInfo(self, alert: AlertInfo) -> None:
        """
        Display alert from AlertInfo object.

        Args:
            alert: AlertInfo object
        """
        if self._driver:
            self._driver.showAlert(alert)

        for callback in self._callbacks.get('alert', []):
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    def clearDisplay(self) -> None:
        """Clear the display."""
        if self._driver:
            self._driver.clearDisplay()

    def getLastStatus(self) -> Optional[StatusInfo]:
        """Get the last displayed status."""
        if self._driver:
            return self._driver.getLastStatus()
        return None

    def getActiveAlerts(self) -> List[AlertInfo]:
        """Get list of active alerts."""
        if self._driver:
            return self._driver.getActiveAlerts()
        return []

    def onStatusUpdate(self, callback: Callable[[StatusInfo], None]) -> None:
        """
        Register callback for status updates.

        Args:
            callback: Function to call on status update
        """
        self._callbacks['status_update'].append(callback)

    def onAlert(self, callback: Callable[[AlertInfo], None]) -> None:
        """
        Register callback for alerts.

        Args:
            callback: Function to call on alert
        """
        self._callbacks['alert'].append(callback)

    def changeMode(self, newMode: DisplayMode) -> bool:
        """
        Change display mode at runtime.

        Note: Mode change takes effect after re-initialization.

        Args:
            newMode: New display mode

        Returns:
            True if mode change successful
        """
        if newMode == self._mode:
            return True

        oldMode = self._mode
        wasInitialized = self._initialized

        # Shutdown current driver
        self.shutdown()

        # Create new driver
        self._mode = newMode
        self._driver = self._createDriver(newMode, self._config)

        logger.info(f"Display mode changed from {oldMode.value} to {newMode.value}")

        # Trigger callbacks
        for callback in self._callbacks.get('mode_change', []):
            try:
                callback(oldMode, newMode)
            except Exception as e:
                logger.error(f"Mode change callback error: {e}")

        # Re-initialize if was previously initialized
        if wasInitialized:
            return self.initialize()

        return True

    def onModeChange(
        self,
        callback: Callable[[DisplayMode, DisplayMode], None]
    ) -> None:
        """
        Register callback for mode changes.

        Args:
            callback: Function to call on mode change (oldMode, newMode)
        """
        self._callbacks['mode_change'].append(callback)


# Helper functions

def createDisplayManagerFromConfig(config: Dict[str, Any]) -> DisplayManager:
    """
    Create a DisplayManager from configuration.

    Args:
        config: Configuration dictionary

    Returns:
        Configured DisplayManager instance
    """
    return DisplayManager.fromConfig(config)


def getDisplayModeFromConfig(config: Dict[str, Any]) -> DisplayMode:
    """
    Get the display mode from configuration.

    Args:
        config: Configuration dictionary

    Returns:
        DisplayMode enum value
    """
    modeStr = config.get('display', {}).get('mode', 'headless')
    try:
        return DisplayMode.fromString(modeStr)
    except ValueError:
        logger.warning(f"Invalid display mode '{modeStr}', defaulting to headless")
        return DisplayMode.HEADLESS


def isDisplayAvailable(mode: DisplayMode) -> bool:
    """
    Check if a display mode is available.

    For headless and developer modes, always returns True.
    For minimal mode, checks if display hardware might be available
    (returns True as actual hardware check happens during initialization).

    Args:
        mode: Display mode to check

    Returns:
        True if mode is likely available
    """
    # All modes are "available" - actual hardware check happens during init
    return True
