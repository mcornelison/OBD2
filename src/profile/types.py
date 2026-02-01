################################################################################
# File Name: types.py
# Purpose/Description: Type definitions for profile management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-013
# ================================================================================
################################################################################

"""
Type definitions for the profile subpackage.

Contains:
- Profile dataclass for representing driving/tuning profiles
- ProfileChangeEvent dataclass for tracking profile changes
- SwitcherState dataclass for profile switcher state
- Constants for default values and event types

This module has no dependencies on other project modules (only stdlib).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ================================================================================
# Constants
# ================================================================================

# Default profile settings
DEFAULT_PROFILE_ID = 'daily'
DEFAULT_PROFILE_NAME = 'Daily'
DEFAULT_PROFILE_DESCRIPTION = 'Normal daily driving profile'
DEFAULT_POLLING_INTERVAL_MS = 1000

# Default alert thresholds for the default profile
DEFAULT_ALERT_THRESHOLDS: dict[str, Any] = {
    'rpmRedline': 6500,
    'coolantTempCritical': 110,
    'oilPressureLow': 20,
}

# Profile change event types for database logging
PROFILE_CHANGE_EVENT = 'profile_change'
PROFILE_SWITCH_REQUESTED = 'profile_switch_requested'
PROFILE_SWITCH_ACTIVATED = 'profile_switch_activated'


# ================================================================================
# Profile Dataclass
# ================================================================================

@dataclass
class Profile:
    """
    Represents a driving/tuning profile.

    Profiles allow different configurations for various driving scenarios:
    - Different alert thresholds (e.g., higher redline for track day)
    - Different polling intervals (faster for performance monitoring)
    - Independent data tracking and statistics

    Attributes:
        id: Unique identifier for the profile
        name: Display name for the profile
        description: Optional description of the profile
        alertThresholds: Dictionary of alert threshold settings
        pollingIntervalMs: Polling interval in milliseconds
        createdAt: Timestamp when profile was created
        updatedAt: Timestamp when profile was last updated
    """

    id: str
    name: str
    description: str | None = None
    alertThresholds: dict[str, Any] = field(default_factory=dict)
    pollingIntervalMs: int = DEFAULT_POLLING_INTERVAL_MS
    createdAt: datetime | None = None
    updatedAt: datetime | None = None

    def toDict(self) -> dict[str, Any]:
        """
        Convert profile to dictionary.

        Returns:
            Dictionary representation of the profile
        """
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'alertThresholds': self.alertThresholds.copy(),
            'pollingIntervalMs': self.pollingIntervalMs,
            'createdAt': self.createdAt.isoformat() if self.createdAt else None,
            'updatedAt': self.updatedAt.isoformat() if self.updatedAt else None,
        }

    @classmethod
    def fromDict(cls, data: dict[str, Any]) -> 'Profile':
        """
        Create Profile from dictionary.

        Args:
            data: Dictionary with profile data

        Returns:
            Profile instance
        """
        createdAt = None
        updatedAt = None

        if data.get('createdAt'):
            if isinstance(data['createdAt'], str):
                createdAt = datetime.fromisoformat(data['createdAt'])
            elif isinstance(data['createdAt'], datetime):
                createdAt = data['createdAt']

        if data.get('updatedAt'):
            if isinstance(data['updatedAt'], str):
                updatedAt = datetime.fromisoformat(data['updatedAt'])
            elif isinstance(data['updatedAt'], datetime):
                updatedAt = data['updatedAt']

        return cls(
            id=data['id'],
            name=data['name'],
            description=data.get('description'),
            alertThresholds=data.get('alertThresholds', {}),
            pollingIntervalMs=data.get('pollingIntervalMs', DEFAULT_POLLING_INTERVAL_MS),
            createdAt=createdAt,
            updatedAt=updatedAt,
        )

    @classmethod
    def fromConfigDict(cls, configProfile: dict[str, Any]) -> 'Profile':
        """
        Create Profile from config file format.

        Args:
            configProfile: Profile data from config file

        Returns:
            Profile instance
        """
        return cls(
            id=configProfile['id'],
            name=configProfile['name'],
            description=configProfile.get('description'),
            alertThresholds=configProfile.get('alertThresholds', {}),
            pollingIntervalMs=configProfile.get(
                'pollingIntervalMs', DEFAULT_POLLING_INTERVAL_MS
            ),
        )

    def getAlertConfigJson(self) -> str:
        """
        Get alert thresholds as JSON string for database storage.

        Returns:
            JSON string of alert thresholds
        """
        import json
        return json.dumps(self.alertThresholds)


# ================================================================================
# Profile Change Event
# ================================================================================

@dataclass
class ProfileChangeEvent:
    """
    Represents a profile change event.

    Attributes:
        timestamp: When the change occurred
        oldProfileId: Previous profile ID
        newProfileId: New profile ID
        eventType: Type of event (requested, activated)
        triggeredBy: What triggered the change (config, api, drive_start)
        success: Whether the change was successful
        errorMessage: Error message if change failed
    """
    timestamp: datetime
    oldProfileId: str | None
    newProfileId: str
    eventType: str
    triggeredBy: str = 'api'
    success: bool = True
    errorMessage: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'oldProfileId': self.oldProfileId,
            'newProfileId': self.newProfileId,
            'eventType': self.eventType,
            'triggeredBy': self.triggeredBy,
            'success': self.success,
            'errorMessage': self.errorMessage,
        }


# ================================================================================
# Switcher State
# ================================================================================

@dataclass
class SwitcherState:
    """
    Current state of the profile switcher.

    Attributes:
        activeProfileId: Currently active profile ID
        pendingProfileId: Profile ID pending activation on next drive
        isDriving: Whether a drive is currently in progress
        lastChangeTime: Time of last profile change
        changeCount: Total number of profile changes
    """
    activeProfileId: str | None = None
    pendingProfileId: str | None = None
    isDriving: bool = False
    lastChangeTime: datetime | None = None
    changeCount: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'activeProfileId': self.activeProfileId,
            'pendingProfileId': self.pendingProfileId,
            'isDriving': self.isDriving,
            'lastChangeTime': (
                self.lastChangeTime.isoformat() if self.lastChangeTime else None
            ),
            'changeCount': self.changeCount,
        }
