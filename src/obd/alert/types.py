################################################################################
# File Name: types.py
# Purpose/Description: Type definitions for alert management
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
Type definitions for alert management.

Contains enums, dataclasses, and constants used by the alert subpackage.
This module has no dependencies on other project modules.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


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
