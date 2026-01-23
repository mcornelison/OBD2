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
# 2026-01-22    | Ralph Agent  | US-005: Moved drivers to display/drivers subpackage
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
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

# Import types and exceptions from refactored modules
from obd.display.types import DisplayMode, StatusInfo, AlertInfo
from obd.display.exceptions import (
    DisplayError,
    DisplayInitializationError,
    DisplayOutputError,
)

# Import drivers from refactored modules
from obd.display.drivers import (
    BaseDisplayDriver,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
    DeveloperDisplayDriver,
    NullDisplayAdapter,
)

# Backward compatibility alias for internal _NullDisplayAdapter
_NullDisplayAdapter = NullDisplayAdapter

logger = logging.getLogger(__name__)


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
