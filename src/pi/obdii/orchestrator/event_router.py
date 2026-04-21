################################################################################
# File Name: event_router.py
# Purpose/Description: Component callback routing mixin for the orchestrator
# Author: Ralph Agent
# Creation Date: 2026-04-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-14    | Ralph Agent  | Sweep 5 Task 2: extracted from orchestrator.py
#               |              | (5 callback chains preserved exactly per TD-003)
# ================================================================================
################################################################################

"""
Event router mixin for ApplicationOrchestrator.

Owns the five callback chains:
    1. Reading:  DataLogger → Orchestrator → DisplayManager + DriveDetector + AlertManager
    2. Drive:    DriveDetector → Orchestrator → DisplayManager + external
    3. Alert:    AlertManager → Orchestrator → DisplayManager + HardwareManager + external
    4. Analysis: StatisticsEngine → Orchestrator → DisplayManager + external
    5. Profile:  ProfileSwitcher → Orchestrator → AlertManager + DataLogger
"""

import logging
from collections.abc import Callable
from typing import Any

from .types import HealthCheckStats

# Unified logger name matches the original monolith module so existing tests
# that filter caplog by logger name continue to work unchanged.
logger = logging.getLogger("pi.obdii.orchestrator")


class EventRouterMixin:
    """
    Mixin providing callback registration and routing.

    Assumes the composing class has:
        _driveDetector, _alertManager, _statisticsEngine, _dataLogger,
        _profileSwitcher, _displayManager, _hardwareManager, _profileManager,
        _connection, _dtcLogger, _milEdgeDetector:
        Any | None
        _healthCheckStats: HealthCheckStats
        _dashboardParameters: set[str]
        _alertsPausedForReconnect: bool
        _onDriveStart, _onDriveEnd, _onAlert, _onAnalysisComplete,
        _onConnectionLost, _onConnectionRestored: Callable | None
        _startReconnection() method (from ConnectionRecoveryMixin)
    """

    _driveDetector: Any | None
    _alertManager: Any | None
    _statisticsEngine: Any | None
    _dataLogger: Any | None
    _profileSwitcher: Any | None
    _displayManager: Any | None
    _hardwareManager: Any | None
    _profileManager: Any | None
    _healthCheckStats: HealthCheckStats
    _dashboardParameters: set[str]
    _alertsPausedForReconnect: bool
    _connection: Any | None
    _dtcLogger: Any | None
    _milEdgeDetector: Any | None
    _onDriveStart: Callable[[Any], None] | None
    _onDriveEnd: Callable[[Any], None] | None
    _onAlert: Callable[[Any], None] | None
    _onAnalysisComplete: Callable[[Any], None] | None
    _onConnectionLost: Callable[[], None] | None
    _onConnectionRestored: Callable[[], None] | None

    def registerCallbacks(
        self,
        onDriveStart: Callable[[Any], None] | None = None,
        onDriveEnd: Callable[[Any], None] | None = None,
        onAlert: Callable[[Any], None] | None = None,
        onAnalysisComplete: Callable[[Any], None] | None = None,
        onConnectionLost: Callable[[], None] | None = None,
        onConnectionRestored: Callable[[], None] | None = None
    ) -> None:
        """
        Register callbacks for component events.

        Args:
            onDriveStart: Called when a drive session starts (DriveSession)
            onDriveEnd: Called when a drive session ends (DriveSession)
            onAlert: Called when an alert is triggered (AlertEvent)
            onAnalysisComplete: Called when statistics analysis completes
            onConnectionLost: Called when OBD connection is lost
            onConnectionRestored: Called when OBD connection is restored
        """
        self._onDriveStart = onDriveStart
        self._onDriveEnd = onDriveEnd
        self._onAlert = onAlert
        self._onAnalysisComplete = onAnalysisComplete
        self._onConnectionLost = onConnectionLost
        self._onConnectionRestored = onConnectionRestored

    def _setupComponentCallbacks(self) -> None:
        """
        Wire up callbacks between orchestrator and components.

        Called after all components are initialized to connect event handlers.
        """
        # Connect drive detector callbacks
        if self._driveDetector is not None:
            try:
                self._driveDetector.registerCallbacks(
                    onDriveStart=self._handleDriveStart,
                    onDriveEnd=self._handleDriveEnd
                )
                logger.debug("Drive detector callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register drive detector callbacks: {e}")

        # Connect alert manager callbacks
        # AlertManager uses onAlert() method to register single callback
        if self._alertManager is not None and hasattr(self._alertManager, 'onAlert'):
            try:
                self._alertManager.onAlert(self._handleAlert)
                logger.debug("Alert manager callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register alert manager callbacks: {e}")

        # Connect statistics engine callbacks
        # StatisticsEngine uses registerCallbacks() with onAnalysisComplete and onAnalysisError
        if self._statisticsEngine is not None and hasattr(self._statisticsEngine, 'registerCallbacks'):
            try:
                self._statisticsEngine.registerCallbacks(
                    onAnalysisComplete=self._handleAnalysisComplete,
                    onAnalysisError=self._handleAnalysisError
                )
                logger.debug("Statistics engine callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register statistics engine callbacks: {e}")

        # Connect realtime data logger callbacks
        if self._dataLogger is not None and hasattr(self._dataLogger, 'registerCallbacks'):
            try:
                self._dataLogger.registerCallbacks(
                    onReading=self._handleReading,
                    onError=self._handleLoggingError
                )
                logger.debug("Data logger callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register data logger callbacks: {e}")

        # Connect profile switcher callbacks
        # ProfileSwitcher uses onProfileChange() to register profile change callback
        if self._profileSwitcher is not None and hasattr(self._profileSwitcher, 'onProfileChange'):
            try:
                self._profileSwitcher.onProfileChange(self._handleProfileChange)
                logger.debug("Profile switcher callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register profile switcher callbacks: {e}")

    def _handleDriveStart(self, session: Any) -> None:
        """Handle drive start event from DriveDetector."""
        logger.info(f"Drive started | session_id={getattr(session, 'id', 'unknown')}")
        self._healthCheckStats.drivesDetected += 1

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showDriveStatus'):
            try:
                self._displayManager.showDriveStatus('driving')
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # US-204: capture session-start DTCs.  DriveDetector._openDriveId
        # has already published the new drive_id on the process context;
        # we pass driveId=None so the DtcLogger pulls it from there.
        # MIL edge detector also resets so a freshly-illuminated MIL on
        # the *next* poll (vs. a sustained on-state) re-triggers the
        # mid-drive refetch path.
        self._dispatchSessionStartDtcs()
        if self._milEdgeDetector is not None:
            try:
                self._milEdgeDetector.reset()
            except Exception as e:  # noqa: BLE001 -- defensive
                logger.debug(f"MIL edge reset failed: {e}")

        # Call external callback
        if self._onDriveStart is not None:
            try:
                self._onDriveStart(session)
            except Exception as e:
                logger.warning(f"onDriveStart callback error: {e}")

    def _handleDriveEnd(self, session: Any) -> None:
        """Handle drive end event from DriveDetector."""
        duration = getattr(session, 'duration', 0)
        logger.info(f"Drive ended | duration={duration:.1f}s")

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showDriveStatus'):
            try:
                self._displayManager.showDriveStatus('stopped')
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # Call external callback
        if self._onDriveEnd is not None:
            try:
                self._onDriveEnd(session)
            except Exception as e:
                logger.warning(f"onDriveEnd callback error: {e}")

    def _handleAlert(self, alertEvent: Any) -> None:
        """
        Handle alert event from AlertManager.

        The AlertManager has already logged the alert to the database
        at this point. This callback is responsible for:
        - Logging the alert at WARNING level
        - Updating the display with the alert
        - Calling any external callbacks
        - Updating statistics

        Args:
            alertEvent: AlertEvent object with alert details
        """
        alertType = getattr(alertEvent, 'alertType', 'unknown')
        paramName = getattr(alertEvent, 'parameterName', 'unknown')
        value = getattr(alertEvent, 'value', 'N/A')
        threshold = getattr(alertEvent, 'threshold', 'N/A')
        profileId = getattr(alertEvent, 'profileId', 'unknown')

        logger.warning(
            f"ALERT triggered | type={alertType} | param={paramName} | "
            f"value={value} | threshold={threshold} | profile={profileId}"
        )
        self._healthCheckStats.alertsTriggered += 1

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showAlert'):
            try:
                self._displayManager.showAlert(alertEvent)
            except Exception as e:
                logger.debug(f"Display alert failed: {e}")

        # Update hardware manager display (Pi status display) with alert count
        if self._hardwareManager is not None:
            try:
                self._hardwareManager.updateErrorCount(
                    errors=self._healthCheckStats.alertsTriggered
                )
            except Exception as e:
                logger.debug(f"Hardware display error count update failed: {e}")

        # Call external callback
        if self._onAlert is not None:
            try:
                self._onAlert(alertEvent)
            except Exception as e:
                logger.warning(f"onAlert callback error: {e}")

    def _handleAnalysisComplete(self, result: Any) -> None:
        """Handle analysis complete event from StatisticsEngine."""
        logger.info("Statistical analysis completed")

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showAnalysisResult'):
            try:
                self._displayManager.showAnalysisResult(result)
            except Exception as e:
                logger.debug(f"Display analysis result failed: {e}")

        # Call external callback
        if self._onAnalysisComplete is not None:
            try:
                self._onAnalysisComplete(result)
            except Exception as e:
                logger.warning(f"onAnalysisComplete callback error: {e}")

    def _handleAnalysisError(self, profileId: str, error: Exception) -> None:
        """
        Handle analysis error event from StatisticsEngine.

        Logs the error and continues operation - analysis failures
        should not crash the application.

        Args:
            profileId: Profile ID that was being analyzed
            error: The exception that occurred
        """
        logger.error(
            f"Analysis error | profile={profileId} | error={error}"
        )
        self._healthCheckStats.totalErrors += 1

    def _handleReading(self, reading: Any) -> None:
        """Handle reading event from RealtimeDataLogger."""
        self._healthCheckStats.totalReadings += 1

        paramName = getattr(reading, 'parameterName', None)
        value = getattr(reading, 'value', None)
        unit = getattr(reading, 'unit', None)

        # Update display if parameter is configured for dashboard
        if (
            self._displayManager is not None
            and paramName is not None
            and paramName in self._dashboardParameters
            and hasattr(self._displayManager, 'updateValue')
        ):
            try:
                self._displayManager.updateValue(paramName, value, unit)
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # Pass reading to drive detector for state machine processing
        if self._driveDetector is not None:
            try:
                if paramName is not None and value is not None:
                    self._driveDetector.processValue(paramName, value)
            except Exception as e:
                logger.debug(f"Drive detector process failed: {e}")

        # Pass reading to alert manager for threshold checking
        # Skip during reconnection to avoid false alerts on stale data
        if (
            self._alertManager is not None
            and hasattr(self._alertManager, 'checkValue')
            and not self._alertsPausedForReconnect
        ):
            try:
                if paramName is not None and value is not None:
                    self._alertManager.checkValue(paramName, value)
            except Exception as e:
                logger.debug(f"Alert check failed: {e}")

        # US-204: route MIL_ON observations through the rising-edge
        # detector and dispatch a Mode 03 re-fetch on 0->1 transitions.
        # The MIL parameter only flows here when US-199 polling is on
        # (config.realtimeData.parameters includes MIL_ON).
        if (
            paramName == 'MIL_ON'
            and self._milEdgeDetector is not None
            and self._dtcLogger is not None
            and self._connection is not None
        ):
            try:
                if self._milEdgeDetector.observe(value):
                    self._dispatchMilEventDtcs()
            except Exception as e:  # noqa: BLE001 -- defensive (must not crash poll loop)
                logger.debug(f"MIL edge dispatch failed: {e}")

    def _handleLoggingError(self, paramName: str, error: Exception) -> None:
        """Handle logging error event from RealtimeDataLogger."""
        self._healthCheckStats.totalErrors += 1
        logger.debug(f"Data logging error | param={paramName} | error={error}")

    def _handleProfileChange(
        self, oldProfileId: str | None, newProfileId: str
    ) -> None:
        """
        Handle profile change event from ProfileSwitcher.

        Updates alert manager thresholds and data logger polling interval
        to match the new profile's settings.

        Args:
            oldProfileId: Previous profile ID (or None if first profile)
            newProfileId: New active profile ID
        """
        logger.info(f"Profile changed from {oldProfileId} to {newProfileId}")

        # Get the new profile from profile manager
        newProfile = None
        if self._profileManager is not None:
            try:
                newProfile = self._profileManager.getProfile(newProfileId)
            except Exception as e:
                logger.warning(f"Could not get profile {newProfileId}: {e}")

        # Thresholds are global (tiered) and bound at AlertManager construction.
        # Profile switching no longer rebinds them — see Sweep 2a.
        if self._alertManager is not None:
            try:
                if hasattr(self._alertManager, 'setActiveProfile'):
                    self._alertManager.setActiveProfile(newProfileId)
            except Exception as e:
                logger.warning(f"Could not update alert manager on profile switch: {e}")

        # Update data logger polling interval
        if self._dataLogger is not None and newProfile is not None:
            try:
                pollingInterval = getattr(newProfile, 'pollingIntervalMs', None)
                if pollingInterval and hasattr(self._dataLogger, 'setPollingInterval'):
                    self._dataLogger.setPollingInterval(pollingInterval)
                    logger.debug(
                        f"Data logger polling interval updated to {pollingInterval}ms"
                    )
            except Exception as e:
                logger.warning(f"Could not update data logger polling interval: {e}")

    def _handleConnectionLost(self) -> None:
        """
        Handle connection lost event.

        Called when the OBD connection is detected as lost. Updates state,
        notifies display, calls external callbacks, and initiates automatic
        reconnection with exponential backoff.
        """
        logger.warning("OBD connection lost")
        self._healthCheckStats.connectionStatus = "reconnecting"
        self._healthCheckStats.connectionConnected = False

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showConnectionStatus'):
            try:
                self._displayManager.showConnectionStatus('Reconnecting...')
            except Exception as e:
                logger.debug(f"Display connection status failed: {e}")

        # Update hardware manager display (Pi status display) if available
        if self._hardwareManager is not None:
            try:
                self._hardwareManager.updateObdStatus('reconnecting')
            except Exception as e:
                logger.debug(f"Hardware display OBD status update failed: {e}")

        # Call external callback
        if self._onConnectionLost is not None:
            try:
                self._onConnectionLost()
            except Exception as e:
                logger.warning(f"onConnectionLost callback error: {e}")

        # Start automatic reconnection
        self._startReconnection()  # type: ignore[attr-defined]

    def _handleConnectionRestored(self) -> None:
        """Handle connection restored event."""
        logger.info("OBD connection restored")
        self._healthCheckStats.connectionStatus = "connected"
        self._healthCheckStats.connectionConnected = True

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showConnectionStatus'):
            try:
                self._displayManager.showConnectionStatus('Connected')
            except Exception as e:
                logger.debug(f"Display connection status failed: {e}")

        # Update hardware manager display (Pi status display) if available
        if self._hardwareManager is not None:
            try:
                self._hardwareManager.updateObdStatus('connected')
            except Exception as e:
                logger.debug(f"Hardware display OBD status update failed: {e}")

        # Call external callback
        if self._onConnectionRestored is not None:
            try:
                self._onConnectionRestored()
            except Exception as e:
                logger.warning(f"onConnectionRestored callback error: {e}")

    # ================================================================================
    # US-204 -- DTC dispatch helpers
    # ================================================================================

    def _dispatchSessionStartDtcs(self) -> None:
        """Fire DtcLogger.logSessionStartDtcs from _handleDriveStart.

        Skips silently when no DtcLogger or no live connection is
        available -- the orchestrator may be running in a configuration
        (simulator, replay) where DTC capture isn't applicable.  Any
        exception in the DTC path is swallowed to keep drive-start
        non-fatal.
        """
        if self._dtcLogger is None or self._connection is None:
            return
        try:
            result = self._dtcLogger.logSessionStartDtcs(
                driveId=None, connection=self._connection,
            )
            stored = getattr(result, 'storedCount', 0)
            pending = getattr(result, 'pendingCount', 0)
            probe = getattr(result, 'mode07Probe', None)
            mode07Note = (
                getattr(probe, 'reason', 'unknown') if probe is not None else 'no-probe'
            )
            logger.info(
                "DTC session-start | stored=%d | pending=%d | mode07=%s",
                stored, pending, mode07Note,
            )
        except Exception as e:  # noqa: BLE001 -- defensive
            logger.warning(f"DTC session-start dispatch failed: {e}")

    def _dispatchMilEventDtcs(self) -> None:
        """Fire DtcLogger.logMilEventDtcs from _handleReading on rising edge."""
        if self._dtcLogger is None or self._connection is None:
            return
        try:
            result = self._dtcLogger.logMilEventDtcs(
                driveId=None, connection=self._connection,
            )
            inserted = getattr(result, 'inserted', 0)
            updated = getattr(result, 'updated', 0)
            logger.info(
                "DTC MIL-event | inserted=%d | updated=%d",
                inserted, updated,
            )
        except Exception as e:  # noqa: BLE001 -- defensive
            logger.warning(f"DTC MIL-event dispatch failed: {e}")


__all__ = ['EventRouterMixin']
