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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class DisplayMode(Enum):
    """Display mode enumeration."""

    HEADLESS = "headless"
    MINIMAL = "minimal"
    DEVELOPER = "developer"

    @classmethod
    def fromString(cls, value: str) -> 'DisplayMode':
        """
        Convert string to DisplayMode enum.

        Args:
            value: String value of display mode

        Returns:
            DisplayMode enum value

        Raises:
            ValueError: If value is not a valid display mode
        """
        valueLower = value.lower().strip()
        for mode in cls:
            if mode.value == valueLower:
                return mode
        validModes = [m.value for m in cls]
        raise ValueError(
            f"Invalid display mode: '{value}'. Must be one of: {', '.join(validModes)}"
        )

    @classmethod
    def isValid(cls, value: str) -> bool:
        """
        Check if a string is a valid display mode.

        Args:
            value: String to check

        Returns:
            True if valid display mode, False otherwise
        """
        try:
            cls.fromString(value)
            return True
        except ValueError:
            return False


@dataclass
class StatusInfo:
    """Information to display on status screen."""

    connectionStatus: str = "Disconnected"
    databaseStatus: str = "Unknown"
    currentRpm: Optional[float] = None
    coolantTemp: Optional[float] = None
    activeAlerts: List[str] = field(default_factory=list)
    profileName: str = "daily"
    timestamp: Optional[datetime] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'connectionStatus': self.connectionStatus,
            'databaseStatus': self.databaseStatus,
            'currentRpm': self.currentRpm,
            'coolantTemp': self.coolantTemp,
            'activeAlerts': self.activeAlerts,
            'profileName': self.profileName,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


@dataclass
class AlertInfo:
    """Alert information for display."""

    message: str
    priority: int = 3  # 1-5, 1 is highest
    timestamp: Optional[datetime] = None
    acknowledged: bool = False

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'message': self.message,
            'priority': self.priority,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'acknowledged': self.acknowledged
        }


class DisplayError(Exception):
    """Base exception for display-related errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}


class DisplayInitializationError(DisplayError):
    """Raised when display initialization fails."""
    pass


class DisplayOutputError(DisplayError):
    """Raised when display output fails."""
    pass


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
    periodically (e.g., every 1 second).

    Note: Actual Adafruit hardware support is implemented via the
    AdafruitDisplayAdapter class which can be set via setDisplayAdapter().
    """

    # Display dimensions
    WIDTH = 240
    HEIGHT = 240

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._displayAdapter: Optional[Any] = None
        self._refreshRateMs = config.get('refreshRateMs', 1000) if config else 1000
        self._brightness = config.get('brightness', 100) if config else 100
        self._lastUpdateTime: Optional[datetime] = None

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

        Attempts to initialize the display hardware. If hardware is not
        available, logs a warning and returns False (graceful degradation).

        Returns:
            True if display initialized, False otherwise
        """
        # If no adapter set, try to use a null adapter (for testing)
        if self._displayAdapter is None:
            logger.warning(
                "No display adapter set - minimal display will use null output. "
                "Set an adapter with setDisplayAdapter() for actual hardware."
            )
            self._displayAdapter = _NullDisplayAdapter()

        try:
            if hasattr(self._displayAdapter, 'initialize'):
                self._displayAdapter.initialize()
            self._initialized = True
            logger.info(
                f"Minimal display driver initialized "
                f"({self.WIDTH}x{self.HEIGHT}, refresh={self._refreshRateMs}ms)"
            )
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
        if self._displayAdapter and hasattr(self._displayAdapter, 'shutdown'):
            try:
                self._displayAdapter.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down display adapter: {e}")
        self._initialized = False
        logger.debug("Minimal display driver shutdown")

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
        Render the status screen layout.

        Layout (240x240):
        +---------------------------+
        |  CONNECTION: Connected    |  <- Line 1 (y=10)
        |  DATABASE:   Ready        |  <- Line 2 (y=30)
        +---------------------------+
        |        RPM: 2500          |  <- Main value (y=80)
        |     TEMP: 85 C            |  <- Second value (y=120)
        +---------------------------+
        |  ALERTS: (none)           |  <- Alerts section (y=160)
        |                           |
        +---------------------------+
        |  Profile: Daily           |  <- Footer (y=220)
        +---------------------------+

        Args:
            status: StatusInfo to render
        """
        if not hasattr(self._displayAdapter, 'drawText'):
            return

        adapter = self._displayAdapter

        # Clear screen first
        if hasattr(adapter, 'clear'):
            adapter.clear()

        # Header section - connection and database status
        connColor = 'green' if status.connectionStatus == 'Connected' else 'red'
        adapter.drawText(10, 10, f"OBD: {status.connectionStatus}", color=connColor)

        dbColor = 'green' if status.databaseStatus == 'Ready' else 'yellow'
        adapter.drawText(10, 30, f"DB:  {status.databaseStatus}", color=dbColor)

        # Horizontal divider
        if hasattr(adapter, 'drawLine'):
            adapter.drawLine(0, 55, 240, 55, color='gray')

        # Main values section - RPM and Coolant Temp
        rpmText = f"RPM: {int(status.currentRpm)}" if status.currentRpm else "RPM: ---"
        adapter.drawText(60, 80, rpmText, size='large')

        tempText = f"TEMP: {int(status.coolantTemp)} C" if status.coolantTemp else "TEMP: --- C"
        tempColor = 'red' if status.coolantTemp and status.coolantTemp > 100 else 'white'
        adapter.drawText(50, 120, tempText, size='large', color=tempColor)

        # Divider
        if hasattr(adapter, 'drawLine'):
            adapter.drawLine(0, 150, 240, 150, color='gray')

        # Alerts section
        if status.activeAlerts:
            alertText = f"ALERTS: {len(status.activeAlerts)}"
            adapter.drawText(10, 160, alertText, color='yellow')
            # Show first alert
            if len(status.activeAlerts) > 0:
                adapter.drawText(10, 180, status.activeAlerts[0][:25], color='yellow')
        else:
            adapter.drawText(10, 160, "ALERTS: none", color='green')

        # Footer - profile name
        if hasattr(adapter, 'drawLine'):
            adapter.drawLine(0, 210, 240, 210, color='gray')
        adapter.drawText(10, 220, f"Profile: {status.profileName}")

        # Refresh display if needed
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

    def initialize(self) -> None:
        pass

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

    def setOutputStream(self, stream: Any) -> None:
        """
        Set the output stream for console output.

        Args:
            stream: Output stream (default: sys.stdout)
        """
        self._outputStream = stream

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

        output = [
            f"\n{self._color('cyan', '--- STATUS UPDATE ---')}{timestamp}",
            f"  Connection: {self._color(connColor, status.connectionStatus)}",
            f"  Database:   {self._color(dbColor, status.databaseStatus)}",
            f"  RPM:        {status.currentRpm if status.currentRpm else '---'}",
            f"  Coolant:    {status.coolantTemp if status.coolantTemp else '---'} C",
            f"  Profile:    {status.profileName}",
            f"  Alerts:     {len(status.activeAlerts)}"
        ]

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
        profileName: str = "daily"
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
        """
        status = StatusInfo(
            connectionStatus=connectionStatus,
            databaseStatus=databaseStatus,
            currentRpm=currentRpm,
            coolantTemp=coolantTemp,
            activeAlerts=activeAlerts or [],
            profileName=profileName,
            timestamp=datetime.now()
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
