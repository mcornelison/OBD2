################################################################################
# File Name: manager.py
# Purpose/Description: AlertManager class for threshold-based alert management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-011
# ================================================================================
################################################################################
"""
AlertManager class for threshold-based alert management.

Provides real-time alerts for critical performance thresholds:
- RPM redline warnings
- Coolant temperature critical alerts
- Boost pressure monitoring (if turbo equipped)
- Oil pressure low alerts

Features:
- Profile-specific threshold definitions
- Alert cooldown to prevent spam
- Visual alert integration with DisplayManager
- Database logging of all alert events
"""

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .thresholds import convertThresholds
from .types import (
    DEFAULT_COOLDOWN_SECONDS,
    MIN_COOLDOWN_SECONDS,
    AlertEvent,
    AlertState,
    AlertStats,
    AlertThreshold,
)

logger = logging.getLogger(__name__)


class AlertManager:
    """
    Threshold-based alert manager for OBD-II monitoring.

    Monitors OBD-II parameter values and triggers alerts when thresholds
    are exceeded. Integrates with DisplayManager for visual alerts and
    logs all alert events to the database.

    Features:
    - Profile-specific threshold definitions
    - Configurable cooldown to prevent alert spam
    - Callback support for custom alert handling
    - Statistics tracking

    Example:
        manager = AlertManager(
            database=db,
            displayManager=display,
            cooldownSeconds=30
        )
        manager.setProfileThresholds('daily', {
            'rpmRedline': 6500,
            'coolantTempCritical': 110
        })
        manager.start()

        # In data acquisition loop
        manager.checkValue('RPM', currentRpm, profileId='daily')
    """

    def __init__(
        self,
        database: Any | None = None,
        displayManager: Any | None = None,
        cooldownSeconds: float = DEFAULT_COOLDOWN_SECONDS,
        enabled: bool = True,
        visualAlerts: bool = True,
        logAlerts: bool = True
    ):
        """
        Initialize the alert manager.

        Args:
            database: ObdDatabase instance for logging alerts
            displayManager: DisplayManager instance for visual alerts
            cooldownSeconds: Cooldown period between alerts of same type
            enabled: Whether alerting is enabled
            visualAlerts: Whether to show visual alerts on display
            logAlerts: Whether to log alerts to database
        """
        self._database = database
        self._displayManager = displayManager
        self._cooldownSeconds = max(MIN_COOLDOWN_SECONDS, cooldownSeconds)
        self._enabled = enabled
        self._visualAlerts = visualAlerts
        self._logAlerts = logAlerts

        # Thresholds by profile
        self._profileThresholds: dict[str, list[AlertThreshold]] = {}

        # Active profile
        self._activeProfileId: str | None = None

        # Cooldown tracking: {alert_type: last_alert_timestamp}
        self._lastAlertTimes: dict[str, datetime] = {}

        # State
        self._state = AlertState.STOPPED
        self._stats = AlertStats()

        # Callbacks
        self._onAlertCallbacks: list[Callable[[AlertEvent], None]] = []

        # Thread safety
        self._lock = threading.Lock()

    # ================================================================================
    # Configuration
    # ================================================================================

    def setDatabase(self, database: Any) -> None:
        """
        Set the database instance.

        Args:
            database: ObdDatabase instance
        """
        self._database = database

    def setDisplayManager(self, displayManager: Any) -> None:
        """
        Set the display manager instance.

        Args:
            displayManager: DisplayManager instance
        """
        self._displayManager = displayManager

    def setCooldown(self, seconds: float) -> None:
        """
        Set the cooldown period.

        Args:
            seconds: Cooldown in seconds (minimum 1)
        """
        self._cooldownSeconds = max(MIN_COOLDOWN_SECONDS, seconds)

    def setEnabled(self, enabled: bool) -> None:
        """
        Enable or disable alerting.

        Args:
            enabled: True to enable, False to disable
        """
        self._enabled = enabled

    def setVisualAlerts(self, enabled: bool) -> None:
        """
        Enable or disable visual alerts.

        Args:
            enabled: True to enable, False to disable
        """
        self._visualAlerts = enabled

    def setLogAlerts(self, enabled: bool) -> None:
        """
        Enable or disable database logging.

        Args:
            enabled: True to enable, False to disable
        """
        self._logAlerts = enabled

    def setActiveProfile(self, profileId: str) -> None:
        """
        Set the active profile.

        Args:
            profileId: Profile ID to make active
        """
        self._activeProfileId = profileId
        logger.debug(f"Active profile set to: {profileId}")

    def setProfileThresholds(
        self,
        profileId: str,
        thresholds: dict[str, float]
    ) -> None:
        """
        Set thresholds for a profile.

        Args:
            profileId: Profile ID
            thresholds: Dictionary mapping threshold keys to values
                       (e.g., {'rpmRedline': 6500, 'coolantTempCritical': 110})
        """
        alertThresholds = convertThresholds(thresholds)
        self._profileThresholds[profileId] = alertThresholds
        logger.info(
            f"Set {len(alertThresholds)} thresholds for profile '{profileId}'"
        )

    def getThresholdsForProfile(
        self,
        profileId: str
    ) -> list[AlertThreshold]:
        """
        Get thresholds for a profile.

        Args:
            profileId: Profile ID

        Returns:
            List of AlertThreshold objects
        """
        return self._profileThresholds.get(profileId, []).copy()

    def getActiveThresholds(self) -> list[AlertThreshold]:
        """
        Get thresholds for the active profile.

        Returns:
            List of AlertThreshold objects
        """
        if self._activeProfileId:
            return self.getThresholdsForProfile(self._activeProfileId)
        return []

    # ================================================================================
    # Lifecycle
    # ================================================================================

    def start(self) -> bool:
        """
        Start the alert manager.

        Returns:
            True if started successfully
        """
        with self._lock:
            if self._state == AlertState.RUNNING:
                return True

            self._state = AlertState.RUNNING
            logger.info("Alert manager started")
            return True

    def stop(self) -> None:
        """Stop the alert manager."""
        with self._lock:
            self._state = AlertState.STOPPED
            logger.info("Alert manager stopped")

    def isRunning(self) -> bool:
        """Check if alert manager is running."""
        return self._state == AlertState.RUNNING

    def getState(self) -> AlertState:
        """Get current state."""
        return self._state

    # ================================================================================
    # Value Checking
    # ================================================================================

    def checkValue(
        self,
        parameterName: str,
        value: float,
        profileId: str | None = None
    ) -> AlertEvent | None:
        """
        Check a value against thresholds.

        Args:
            parameterName: Parameter name (e.g., 'RPM')
            value: Current value
            profileId: Profile ID (uses active profile if not specified)

        Returns:
            AlertEvent if alert was triggered, None otherwise
        """
        with self._lock:
            self._stats.totalChecks += 1

            if not self._enabled or self._state != AlertState.RUNNING:
                return None

            # Use specified profile or fall back to active profile
            effectiveProfileId = profileId or self._activeProfileId
            if not effectiveProfileId:
                return None

            # Get thresholds for this profile
            thresholds = self._profileThresholds.get(effectiveProfileId, [])

            # Check each threshold that matches this parameter
            for threshold in thresholds:
                if threshold.parameterName != parameterName:
                    continue

                if threshold.checkValue(value):
                    return self._handleThresholdExceeded(
                        threshold, value, effectiveProfileId
                    )

            return None

    def checkValues(
        self,
        values: dict[str, float],
        profileId: str | None = None
    ) -> list[AlertEvent]:
        """
        Check multiple values against thresholds.

        Args:
            values: Dictionary of parameter names to values
            profileId: Profile ID (uses active profile if not specified)

        Returns:
            List of AlertEvent objects for triggered alerts
        """
        alerts = []
        for parameterName, value in values.items():
            alert = self.checkValue(parameterName, value, profileId)
            if alert:
                alerts.append(alert)
        return alerts

    def _handleThresholdExceeded(
        self,
        threshold: AlertThreshold,
        value: float,
        profileId: str
    ) -> AlertEvent | None:
        """
        Handle a threshold being exceeded.

        Args:
            threshold: The exceeded threshold
            value: The value that exceeded it
            profileId: Active profile ID

        Returns:
            AlertEvent if alert was triggered (not in cooldown)
        """
        # Check cooldown
        now = datetime.now()
        lastAlertTime = self._lastAlertTimes.get(threshold.alertType)

        if lastAlertTime:
            elapsed = (now - lastAlertTime).total_seconds()
            if elapsed < self._cooldownSeconds:
                self._stats.alertsSuppressed += 1
                logger.debug(
                    f"Alert suppressed (cooldown): {threshold.alertType}, "
                    f"elapsed={elapsed:.1f}s, cooldown={self._cooldownSeconds}s"
                )
                return None

        # Create alert event
        event = AlertEvent(
            alertType=threshold.alertType,
            parameterName=threshold.parameterName,
            value=value,
            threshold=threshold.threshold,
            profileId=profileId,
            timestamp=now,
        )

        # Update tracking
        self._lastAlertTimes[threshold.alertType] = now
        self._stats.alertsTriggered += 1
        self._stats.alertsByType[threshold.alertType] = \
            self._stats.alertsByType.get(threshold.alertType, 0) + 1
        self._stats.lastAlertTime = now

        logger.warning(
            f"ALERT: {threshold.message} - actual value: {value}"
        )

        # Show visual alert
        if self._visualAlerts and self._displayManager:
            self._showVisualAlert(threshold, value)

        # Log to database
        if self._logAlerts and self._database:
            self._logAlertToDatabase(event)

        # Trigger callbacks
        self._triggerCallbacks(event)

        return event

    def _showVisualAlert(
        self,
        threshold: AlertThreshold,
        value: float
    ) -> None:
        """
        Show visual alert on display.

        Args:
            threshold: The threshold that was exceeded
            value: The value that exceeded it
        """
        try:
            if hasattr(self._displayManager, 'showAlert'):
                self._displayManager.showAlert(
                    message=threshold.message,
                    priority=threshold.priority,
                )
        except Exception as e:
            logger.error(f"Failed to show visual alert: {e}")

    def _logAlertToDatabase(self, event: AlertEvent) -> None:
        """
        Log alert event to database.

        Args:
            event: The alert event to log
        """
        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO alert_log
                    (timestamp, alert_type, parameter_name, value, threshold, profile_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.timestamp,
                        event.alertType,
                        event.parameterName,
                        event.value,
                        event.threshold,
                        event.profileId,
                    )
                )
                logger.debug(f"Alert logged to database: {event.alertType}")
        except Exception as e:
            logger.error(f"Failed to log alert to database: {e}")

    # ================================================================================
    # Callbacks
    # ================================================================================

    def onAlert(self, callback: Callable[[AlertEvent], None]) -> None:
        """
        Register a callback for alert events.

        Args:
            callback: Function to call when an alert is triggered
        """
        self._onAlertCallbacks.append(callback)

    def _triggerCallbacks(self, event: AlertEvent) -> None:
        """
        Trigger all registered callbacks.

        Args:
            event: The alert event
        """
        for callback in self._onAlertCallbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    # ================================================================================
    # Statistics
    # ================================================================================

    def getStats(self) -> AlertStats:
        """
        Get alert statistics.

        Returns:
            AlertStats with current statistics
        """
        with self._lock:
            return AlertStats(
                totalChecks=self._stats.totalChecks,
                alertsTriggered=self._stats.alertsTriggered,
                alertsSuppressed=self._stats.alertsSuppressed,
                alertsByType=self._stats.alertsByType.copy(),
                lastAlertTime=self._stats.lastAlertTime,
            )

    def resetStats(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._stats = AlertStats()

    def clearCooldowns(self) -> None:
        """Clear all cooldown timers."""
        with self._lock:
            self._lastAlertTimes.clear()
            logger.debug("Alert cooldowns cleared")

    # ================================================================================
    # Alert History
    # ================================================================================

    def getAlertHistory(
        self,
        profileId: str | None = None,
        limit: int = 100,
        alertType: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Get alert history from database.

        Args:
            profileId: Filter by profile ID (optional)
            limit: Maximum number of alerts to return
            alertType: Filter by alert type (optional)

        Returns:
            List of alert records
        """
        if not self._database:
            return []

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()

                query = "SELECT * FROM alert_log WHERE 1=1"
                params: list[Any] = []

                if profileId:
                    query += " AND profile_id = ?"
                    params.append(profileId)

                if alertType:
                    query += " AND alert_type = ?"
                    params.append(alertType)

                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get alert history: {e}")
            return []

    def getAlertCount(
        self,
        profileId: str | None = None,
        sinceTimestamp: datetime | None = None
    ) -> int:
        """
        Get count of alerts.

        Args:
            profileId: Filter by profile ID (optional)
            sinceTimestamp: Only count alerts since this time (optional)

        Returns:
            Number of alerts
        """
        if not self._database:
            return 0

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()

                query = "SELECT COUNT(*) FROM alert_log WHERE 1=1"
                params: list[Any] = []

                if profileId:
                    query += " AND profile_id = ?"
                    params.append(profileId)

                if sinceTimestamp:
                    query += " AND timestamp >= ?"
                    params.append(sinceTimestamp)

                cursor.execute(query, params)
                return cursor.fetchone()[0]

        except Exception as e:
            logger.error(f"Failed to get alert count: {e}")
            return 0
