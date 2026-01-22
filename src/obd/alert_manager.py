################################################################################
# File Name: alert_manager.py
# Purpose/Description: Threshold-based alert system for OBD-II monitoring
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-017
# ================================================================================
################################################################################

"""
Threshold-based alert system for OBD-II monitoring.

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

Usage:
    from obd.alert_manager import AlertManager, createAlertManagerFromConfig

    # Create from config
    manager = createAlertManagerFromConfig(config, database, displayManager)
    manager.start()

    # Check value against thresholds
    manager.checkValue('RPM', 7500)  # Triggers alert if above threshold

    # Shutdown
    manager.stop()
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Default alert cooldown in seconds
DEFAULT_COOLDOWN_SECONDS = 30

# Minimum cooldown allowed
MIN_COOLDOWN_SECONDS = 1

# Alert types
ALERT_TYPE_RPM_REDLINE = "rpm_redline"
ALERT_TYPE_COOLANT_TEMP_CRITICAL = "coolant_temp_critical"
ALERT_TYPE_BOOST_PRESSURE_MAX = "boost_pressure_max"
ALERT_TYPE_OIL_PRESSURE_LOW = "oil_pressure_low"

# Parameter to alert type mapping
PARAMETER_ALERT_TYPES = {
    'RPM': ALERT_TYPE_RPM_REDLINE,
    'COOLANT_TEMP': ALERT_TYPE_COOLANT_TEMP_CRITICAL,
    'INTAKE_PRESSURE': ALERT_TYPE_BOOST_PRESSURE_MAX,
    'BOOST_PRESSURE': ALERT_TYPE_BOOST_PRESSURE_MAX,
    'OIL_PRESSURE': ALERT_TYPE_OIL_PRESSURE_LOW,
}

# Threshold config keys to parameter mapping
THRESHOLD_KEY_TO_PARAMETER = {
    'rpmRedline': 'RPM',
    'coolantTempCritical': 'COOLANT_TEMP',
    'boostPressureMax': 'INTAKE_PRESSURE',
    'oilPressureLow': 'OIL_PRESSURE',
}

# Alert priority mapping (1=highest, 5=lowest)
ALERT_PRIORITIES = {
    ALERT_TYPE_COOLANT_TEMP_CRITICAL: 1,  # Safety critical
    ALERT_TYPE_OIL_PRESSURE_LOW: 1,       # Safety critical
    ALERT_TYPE_RPM_REDLINE: 2,            # Engine damage risk
    ALERT_TYPE_BOOST_PRESSURE_MAX: 3,     # Performance limit
}


# ================================================================================
# Enums
# ================================================================================

class AlertDirection(Enum):
    """Direction of threshold comparison."""

    ABOVE = "above"  # Alert when value > threshold
    BELOW = "below"  # Alert when value < threshold


class AlertState(Enum):
    """State of the alert manager."""

    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class AlertThreshold:
    """
    Alert threshold configuration.

    Attributes:
        parameterName: OBD-II parameter name (e.g., 'RPM')
        alertType: Type of alert (e.g., 'rpm_redline')
        threshold: Threshold value
        direction: Direction of comparison (ABOVE or BELOW)
        priority: Alert priority (1-5, 1 is highest)
        message: Alert message template
    """

    parameterName: str
    alertType: str
    threshold: float
    direction: AlertDirection
    priority: int = 3
    message: str = ""

    def __post_init__(self) -> None:
        """Set default message if not provided."""
        if not self.message:
            if self.direction == AlertDirection.ABOVE:
                self.message = f"{self.parameterName} above {self.threshold}"
            else:
                self.message = f"{self.parameterName} below {self.threshold}"

    def checkValue(self, value: float) -> bool:
        """
        Check if a value exceeds this threshold.

        Args:
            value: Value to check

        Returns:
            True if threshold is exceeded
        """
        if self.direction == AlertDirection.ABOVE:
            return value > self.threshold
        else:
            return value < self.threshold

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'parameterName': self.parameterName,
            'alertType': self.alertType,
            'threshold': self.threshold,
            'direction': self.direction.value,
            'priority': self.priority,
            'message': self.message,
        }


@dataclass
class AlertEvent:
    """
    Record of an alert event.

    Attributes:
        alertType: Type of alert
        parameterName: Parameter that triggered the alert
        value: Value that triggered the alert
        threshold: Threshold that was exceeded
        profileId: Active profile when alert occurred
        timestamp: When the alert occurred
        acknowledged: Whether the alert has been acknowledged
    """

    alertType: str
    parameterName: str
    value: float
    threshold: float
    profileId: Optional[str] = None
    timestamp: Optional[datetime] = None
    acknowledged: bool = False

    def __post_init__(self) -> None:
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'alertType': self.alertType,
            'parameterName': self.parameterName,
            'value': self.value,
            'threshold': self.threshold,
            'profileId': self.profileId,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'acknowledged': self.acknowledged,
        }


@dataclass
class AlertStats:
    """
    Statistics about alert manager operation.

    Attributes:
        totalChecks: Total number of value checks performed
        alertsTriggered: Total number of alerts triggered
        alertsSuppressed: Alerts suppressed due to cooldown
        alertsByType: Count of alerts by type
        lastAlertTime: Time of most recent alert
    """

    totalChecks: int = 0
    alertsTriggered: int = 0
    alertsSuppressed: int = 0
    alertsByType: Dict[str, int] = field(default_factory=dict)
    lastAlertTime: Optional[datetime] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'totalChecks': self.totalChecks,
            'alertsTriggered': self.alertsTriggered,
            'alertsSuppressed': self.alertsSuppressed,
            'alertsByType': self.alertsByType.copy(),
            'lastAlertTime': self.lastAlertTime.isoformat() if self.lastAlertTime else None,
        }


# ================================================================================
# Exceptions
# ================================================================================

class AlertError(Exception):
    """Base exception for alert-related errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AlertConfigurationError(AlertError):
    """Error in alert configuration."""
    pass


class AlertDatabaseError(AlertError):
    """Error logging alert to database."""
    pass


# ================================================================================
# Alert Manager Class
# ================================================================================

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
        database: Optional[Any] = None,
        displayManager: Optional[Any] = None,
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
        self._profileThresholds: Dict[str, List[AlertThreshold]] = {}

        # Active profile
        self._activeProfileId: Optional[str] = None

        # Cooldown tracking: {alert_type: last_alert_timestamp}
        self._lastAlertTimes: Dict[str, datetime] = {}

        # State
        self._state = AlertState.STOPPED
        self._stats = AlertStats()

        # Callbacks
        self._onAlertCallbacks: List[Callable[[AlertEvent], None]] = []

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
        thresholds: Dict[str, float]
    ) -> None:
        """
        Set thresholds for a profile.

        Args:
            profileId: Profile ID
            thresholds: Dictionary mapping threshold keys to values
                       (e.g., {'rpmRedline': 6500, 'coolantTempCritical': 110})
        """
        alertThresholds = self._convertThresholds(thresholds)
        self._profileThresholds[profileId] = alertThresholds
        logger.info(
            f"Set {len(alertThresholds)} thresholds for profile '{profileId}'"
        )

    def _convertThresholds(
        self,
        thresholds: Dict[str, float]
    ) -> List[AlertThreshold]:
        """
        Convert threshold config dict to AlertThreshold objects.

        Args:
            thresholds: Threshold config dictionary

        Returns:
            List of AlertThreshold objects
        """
        result = []

        for key, value in thresholds.items():
            if key not in THRESHOLD_KEY_TO_PARAMETER:
                logger.warning(f"Unknown threshold key: {key}")
                continue

            parameterName = THRESHOLD_KEY_TO_PARAMETER[key]
            alertType = PARAMETER_ALERT_TYPES.get(parameterName, key)
            priority = ALERT_PRIORITIES.get(alertType, 3)

            # Determine direction based on threshold type
            if key in ('oilPressureLow',):
                direction = AlertDirection.BELOW
            else:
                direction = AlertDirection.ABOVE

            # Create message
            if key == 'rpmRedline':
                message = f"RPM REDLINE! ({value})"
            elif key == 'coolantTempCritical':
                message = f"COOLANT CRITICAL! ({value}C)"
            elif key == 'boostPressureMax':
                message = f"MAX BOOST! ({value} psi)"
            elif key == 'oilPressureLow':
                message = f"LOW OIL PRESSURE! (<{value} psi)"
            else:
                message = f"{parameterName} alert ({value})"

            threshold = AlertThreshold(
                parameterName=parameterName,
                alertType=alertType,
                threshold=value,
                direction=direction,
                priority=priority,
                message=message,
            )
            result.append(threshold)

        return result

    def getThresholdsForProfile(
        self,
        profileId: str
    ) -> List[AlertThreshold]:
        """
        Get thresholds for a profile.

        Args:
            profileId: Profile ID

        Returns:
            List of AlertThreshold objects
        """
        return self._profileThresholds.get(profileId, []).copy()

    def getActiveThresholds(self) -> List[AlertThreshold]:
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
        profileId: Optional[str] = None
    ) -> Optional[AlertEvent]:
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
        values: Dict[str, float],
        profileId: Optional[str] = None
    ) -> List[AlertEvent]:
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
    ) -> Optional[AlertEvent]:
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
        profileId: Optional[str] = None,
        limit: int = 100,
        alertType: Optional[str] = None
    ) -> List[Dict[str, Any]]:
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
                params: List[Any] = []

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
        profileId: Optional[str] = None,
        sinceTimestamp: Optional[datetime] = None
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
                params: List[Any] = []

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


# ================================================================================
# Helper Functions
# ================================================================================

def createAlertManagerFromConfig(
    config: Dict[str, Any],
    database: Optional[Any] = None,
    displayManager: Optional[Any] = None
) -> AlertManager:
    """
    Create an AlertManager from configuration.

    Args:
        config: Configuration dictionary
        database: ObdDatabase instance (optional)
        displayManager: DisplayManager instance (optional)

    Returns:
        Configured AlertManager instance
    """
    alertsConfig = config.get('alerts', {})

    enabled = alertsConfig.get('enabled', True)
    cooldownSeconds = alertsConfig.get('cooldownSeconds', DEFAULT_COOLDOWN_SECONDS)
    visualAlerts = alertsConfig.get('visualAlerts', True)
    logAlerts = alertsConfig.get('logAlerts', True)

    manager = AlertManager(
        database=database,
        displayManager=displayManager,
        cooldownSeconds=cooldownSeconds,
        enabled=enabled,
        visualAlerts=visualAlerts,
        logAlerts=logAlerts,
    )

    # Load profile thresholds
    profilesConfig = config.get('profiles', {})
    activeProfile = profilesConfig.get('activeProfile', 'daily')

    for profile in profilesConfig.get('availableProfiles', []):
        profileId = profile.get('id')
        thresholds = profile.get('alertThresholds', {})
        if profileId and thresholds:
            manager.setProfileThresholds(profileId, thresholds)

    manager.setActiveProfile(activeProfile)

    logger.info(
        f"AlertManager created from config: enabled={enabled}, "
        f"cooldown={cooldownSeconds}s, visual={visualAlerts}, log={logAlerts}"
    )

    return manager


def getAlertThresholdsForProfile(
    config: Dict[str, Any],
    profileId: str
) -> Dict[str, float]:
    """
    Get alert thresholds for a specific profile from config.

    Args:
        config: Configuration dictionary
        profileId: Profile ID to get thresholds for

    Returns:
        Dictionary of threshold key to value
    """
    profilesConfig = config.get('profiles', {})

    for profile in profilesConfig.get('availableProfiles', []):
        if profile.get('id') == profileId:
            return profile.get('alertThresholds', {})

    return {}


def isAlertingEnabled(config: Dict[str, Any]) -> bool:
    """
    Check if alerting is enabled in config.

    Args:
        config: Configuration dictionary

    Returns:
        True if alerting is enabled
    """
    return config.get('alerts', {}).get('enabled', True)


def getDefaultThresholds() -> Dict[str, float]:
    """
    Get default threshold values.

    Returns:
        Dictionary of default thresholds
    """
    return {
        'rpmRedline': 6500,
        'coolantTempCritical': 110,
        'boostPressureMax': 18,
        'oilPressureLow': 20,
    }


def checkThresholdValue(
    parameterName: str,
    value: float,
    thresholds: Dict[str, float]
) -> Optional[str]:
    """
    Check a single value against thresholds without AlertManager.

    Args:
        parameterName: Parameter name
        value: Value to check
        thresholds: Threshold dictionary

    Returns:
        Alert type string if threshold exceeded, None otherwise
    """
    # Map parameter name to threshold key
    paramToKey = {
        'RPM': 'rpmRedline',
        'COOLANT_TEMP': 'coolantTempCritical',
        'INTAKE_PRESSURE': 'boostPressureMax',
        'BOOST_PRESSURE': 'boostPressureMax',
        'OIL_PRESSURE': 'oilPressureLow',
    }

    thresholdKey = paramToKey.get(parameterName)
    if not thresholdKey or thresholdKey not in thresholds:
        return None

    threshold = thresholds[thresholdKey]

    # Oil pressure is "below" threshold, others are "above"
    if thresholdKey == 'oilPressureLow':
        if value < threshold:
            return ALERT_TYPE_OIL_PRESSURE_LOW
    else:
        if value > threshold:
            return PARAMETER_ALERT_TYPES.get(parameterName)

    return None
