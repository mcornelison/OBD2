################################################################################
# File Name: manager.py
# Purpose/Description: DisplayManager class for OBD-II display coordination
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | US-006: Extracted from display_manager.py
# 2026-01-23    | Ralph Agent  | US-OSC-010: Added updateValue, showDriveStatus,
#               |              | showConnectionStatus, showAnalysisResult,
#               |              | showWelcomeScreen, showShutdownMessage, stop methods
# ================================================================================
################################################################################

"""
Display manager module.

Provides the DisplayManager class that coordinates display output across
different display modes (headless, minimal, developer).

Usage:
    from display.manager import DisplayManager
    from display.types import DisplayMode

    manager = DisplayManager(mode=DisplayMode.HEADLESS)
    manager.initialize()
    manager.showStatus(connectionStatus="Connected")
"""

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .types import DisplayMode, StatusInfo, AlertInfo
from .drivers import (
    BaseDisplayDriver,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
    DeveloperDisplayDriver,
)

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

    def updateValue(
        self,
        paramName: str,
        value: Any,
        unit: Optional[str] = None
    ) -> None:
        """
        Update a single realtime value on the display.

        Used for dashboard parameter updates (e.g., RPM, SPEED, COOLANT_TEMP).

        Args:
            paramName: Parameter name (e.g., 'RPM', 'SPEED')
            value: Current value
            unit: Optional unit of measurement (e.g., 'rpm', 'km/h')
        """
        logger.debug(f"Display update: {paramName}={value} {unit or ''}")

        # Update specific fields in status if driver supports it
        if self._driver and hasattr(self._driver, 'updateValue'):
            try:
                self._driver.updateValue(paramName, value, unit)
            except Exception as e:
                logger.debug(f"Driver updateValue failed: {e}")

    def showDriveStatus(self, status: str) -> None:
        """
        Show current drive status on the display.

        Args:
            status: Drive status string ('driving', 'stopped', 'starting', 'stopping')
        """
        logger.debug(f"Drive status: {status}")

        if self._driver and hasattr(self._driver, 'showDriveStatus'):
            try:
                self._driver.showDriveStatus(status)
            except Exception as e:
                logger.debug(f"Driver showDriveStatus failed: {e}")

    def showConnectionStatus(self, status: str) -> None:
        """
        Show connection status on the display.

        Args:
            status: Connection status string ('Connected', 'Disconnected', 'Reconnecting...')
        """
        logger.debug(f"Connection status: {status}")

        if self._driver and hasattr(self._driver, 'showConnectionStatus'):
            try:
                self._driver.showConnectionStatus(status)
            except Exception as e:
                logger.debug(f"Driver showConnectionStatus failed: {e}")

    def showAnalysisResult(self, result: Any) -> None:
        """
        Show analysis result notification on the display.

        Args:
            result: Analysis result object from StatisticsEngine
        """
        logger.debug(f"Analysis result: {result}")

        if self._driver and hasattr(self._driver, 'showAnalysisResult'):
            try:
                self._driver.showAnalysisResult(result)
            except Exception as e:
                logger.debug(f"Driver showAnalysisResult failed: {e}")

    def showWelcomeScreen(
        self,
        appName: str = "Eclipse OBD-II",
        version: str = "1.0.0"
    ) -> None:
        """
        Show welcome screen on application startup.

        Args:
            appName: Application name to display
            version: Version string to display
        """
        logger.info(f"Display: Welcome to {appName} v{version}")

        if self._driver and hasattr(self._driver, 'showWelcomeScreen'):
            try:
                self._driver.showWelcomeScreen(appName, version)
            except Exception as e:
                logger.debug(f"Driver showWelcomeScreen failed: {e}")

    def showShutdownMessage(self) -> None:
        """
        Show shutdown message on the display.

        Called during graceful shutdown to indicate the application is stopping.
        """
        logger.info("Display: Shutting down...")

        if self._driver and hasattr(self._driver, 'showShutdownMessage'):
            try:
                self._driver.showShutdownMessage()
            except Exception as e:
                logger.debug(f"Driver showShutdownMessage failed: {e}")

    def stop(self) -> None:
        """
        Stop the display manager.

        Alias for shutdown() for compatibility with orchestrator's
        _stopComponentWithTimeout pattern.
        """
        self.shutdown()
