################################################################################
# File Name: profile_switcher.py
# Purpose/Description: Profile switching with drive-aware transitions
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-025
# ================================================================================
################################################################################

"""
Profile switching module for the Eclipse OBD-II Performance Monitoring System.

Provides:
- Profile switching via config or API
- Drive-aware transitions (profile switch takes effect on next drive start)
- Profile change logging to database with timestamp
- Display integration for showing current profile
- Data tagging with active profile_id

US-025 Acceptance Criteria:
- Config.json has activeProfile setting (profile name or id)
- Profile switch takes effect on next drive start (not mid-drive)
- Display shows current active profile name
- Profile change logged to database with timestamp
- All subsequent data tagged with new profile_id

Usage:
    from obd.profile_switcher import ProfileSwitcher

    # Create switcher with dependencies
    switcher = ProfileSwitcher(
        profileManager=profileManager,
        driveDetector=driveDetector,
        displayManager=displayManager,
        database=database
    )

    # Request a profile switch (takes effect on next drive)
    switcher.requestProfileSwitch('performance')

    # Get current active profile
    profile = switcher.getActiveProfile()

    # Check if switch is pending
    if switcher.hasPendingSwitch():
        print(f"Pending switch to: {switcher.getPendingProfileId()}")
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Profile change event types for database logging
PROFILE_CHANGE_EVENT = 'profile_change'
PROFILE_SWITCH_REQUESTED = 'profile_switch_requested'
PROFILE_SWITCH_ACTIVATED = 'profile_switch_activated'


# ================================================================================
# Data Classes
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
    oldProfileId: Optional[str]
    newProfileId: str
    eventType: str
    triggeredBy: str = 'api'
    success: bool = True
    errorMessage: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
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
    activeProfileId: Optional[str] = None
    pendingProfileId: Optional[str] = None
    isDriving: bool = False
    lastChangeTime: Optional[datetime] = None
    changeCount: int = 0

    def toDict(self) -> Dict[str, Any]:
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


# ================================================================================
# Custom Exceptions
# ================================================================================

class ProfileSwitchError(Exception):
    """Base exception for profile switch errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ProfileNotFoundError(ProfileSwitchError):
    """Raised when requested profile doesn't exist."""
    pass


class ProfileSwitchPendingError(ProfileSwitchError):
    """Raised when a switch is already pending."""
    pass


# ================================================================================
# Profile Switcher Class
# ================================================================================

class ProfileSwitcher:
    """
    Manages profile switching with drive-aware transitions.

    Ensures profile switches take effect on the next drive start (not mid-drive)
    to maintain data consistency. Integrates with ProfileManager for profile
    lookup, DriveDetector for drive state awareness, and DisplayManager for
    visual feedback.

    Features:
    - Profile switch scheduling (takes effect on next drive start)
    - Immediate switch when not driving
    - Database logging of all profile changes
    - Display integration for showing current profile
    - Callback support for profile change events

    Example:
        # Create dependencies
        profileManager = ProfileManager(database)
        driveDetector = DriveDetector(config)
        displayManager = DisplayManager.fromConfig(config)

        # Create switcher
        switcher = ProfileSwitcher(
            profileManager=profileManager,
            driveDetector=driveDetector,
            displayManager=displayManager,
            database=database
        )

        # Initialize from config
        switcher.initializeFromConfig(config)

        # Request switch to performance profile
        result = switcher.requestProfileSwitch('performance')

        # Register for profile change events
        switcher.onProfileChange(lambda old, new: print(f"{old} -> {new}"))
    """

    def __init__(
        self,
        profileManager: Optional[Any] = None,
        driveDetector: Optional[Any] = None,
        displayManager: Optional[Any] = None,
        database: Optional[Any] = None
    ):
        """
        Initialize the profile switcher.

        Args:
            profileManager: ProfileManager instance for profile lookup
            driveDetector: DriveDetector instance for drive state awareness
            displayManager: DisplayManager instance for display updates
            database: ObdDatabase instance for logging profile changes
        """
        self._profileManager = profileManager
        self._driveDetector = driveDetector
        self._displayManager = displayManager
        self._database = database

        # State
        self._state = SwitcherState()
        self._changeHistory: List[ProfileChangeEvent] = []

        # Callbacks
        self._onProfileChange: List[Callable[[Optional[str], str], None]] = []
        self._onPendingSwitch: List[Callable[[str], None]] = []

        # Register with drive detector for drive start events
        if driveDetector:
            self._registerDriveDetectorCallbacks()

    # ================================================================================
    # Configuration
    # ================================================================================

    def setProfileManager(self, manager: Any) -> None:
        """
        Set the profile manager.

        Args:
            manager: ProfileManager instance
        """
        self._profileManager = manager

    def setDriveDetector(self, detector: Any) -> None:
        """
        Set the drive detector and register callbacks.

        Args:
            detector: DriveDetector instance
        """
        self._driveDetector = detector
        self._registerDriveDetectorCallbacks()

    def setDisplayManager(self, manager: Any) -> None:
        """
        Set the display manager.

        Args:
            manager: DisplayManager instance
        """
        self._displayManager = manager

    def setDatabase(self, database: Any) -> None:
        """
        Set the database for logging.

        Args:
            database: ObdDatabase instance
        """
        self._database = database

    def _registerDriveDetectorCallbacks(self) -> None:
        """Register callbacks with the drive detector."""
        if not self._driveDetector:
            return

        self._driveDetector.registerCallbacks(
            onDriveStart=self._onDriveStart,
            onDriveEnd=self._onDriveEnd,
        )
        logger.debug("Registered drive detector callbacks for profile switching")

    # ================================================================================
    # Initialization
    # ================================================================================

    def initializeFromConfig(self, config: Dict[str, Any]) -> bool:
        """
        Initialize the active profile from configuration.

        Reads the profiles.activeProfile setting from config and sets it
        as the active profile (immediate switch since no drive in progress).

        Args:
            config: Configuration dictionary

        Returns:
            True if initialization successful
        """
        profilesConfig = config.get('profiles', {})
        activeProfileId = profilesConfig.get('activeProfile')

        if not activeProfileId:
            logger.warning("No activeProfile specified in config")
            return False

        # Verify profile exists
        if not self._profileExists(activeProfileId):
            logger.error(f"Active profile from config not found: {activeProfileId}")
            return False

        # Set active profile directly (no pending state for initial load)
        self._state.activeProfileId = activeProfileId

        # Update profile manager's active profile
        if self._profileManager:
            try:
                self._profileManager.setActiveProfile(activeProfileId)
            except Exception as e:
                logger.warning(f"Failed to set profile manager active: {e}")

        # Update display
        self._updateDisplay()

        logger.info(f"Initialized active profile from config: {activeProfileId}")
        return True

    # ================================================================================
    # Profile Switching
    # ================================================================================

    def requestProfileSwitch(
        self,
        profileId: str,
        triggeredBy: str = 'api'
    ) -> bool:
        """
        Request a profile switch.

        If currently driving, the switch is queued and takes effect on next
        drive start. If not driving, the switch takes effect immediately.

        Args:
            profileId: ID of profile to switch to
            triggeredBy: What triggered the switch (config, api, user)

        Returns:
            True if switch was successful or queued

        Raises:
            ProfileNotFoundError: If profile doesn't exist
        """
        # Verify profile exists
        if not self._profileExists(profileId):
            raise ProfileNotFoundError(
                f"Profile not found: {profileId}",
                details={'profileId': profileId}
            )

        # Check if already active
        if profileId == self._state.activeProfileId:
            logger.debug(f"Profile already active: {profileId}")
            return True

        # Check if switch already pending for same profile
        if profileId == self._state.pendingProfileId:
            logger.debug(f"Switch already pending for: {profileId}")
            return True

        # Check drive state
        isDriving = self._isDriving()

        if isDriving:
            # Queue the switch for next drive start
            return self._queueProfileSwitch(profileId, triggeredBy)
        else:
            # Switch immediately
            return self._executeProfileSwitch(profileId, triggeredBy)

    def _queueProfileSwitch(
        self,
        profileId: str,
        triggeredBy: str
    ) -> bool:
        """
        Queue a profile switch for next drive start.

        Args:
            profileId: Profile ID to switch to
            triggeredBy: What triggered the switch

        Returns:
            True if queued successfully
        """
        oldPending = self._state.pendingProfileId
        self._state.pendingProfileId = profileId

        # Log the request
        event = ProfileChangeEvent(
            timestamp=datetime.now(),
            oldProfileId=self._state.activeProfileId,
            newProfileId=profileId,
            eventType=PROFILE_SWITCH_REQUESTED,
            triggeredBy=triggeredBy,
            success=True,
        )
        self._logProfileChange(event)
        self._changeHistory.append(event)

        logger.info(
            f"Profile switch queued: {profileId} "
            f"(will activate on next drive start)"
        )

        # Trigger callbacks for pending switch
        for callback in self._onPendingSwitch:
            try:
                callback(profileId)
            except Exception as e:
                logger.error(f"onPendingSwitch callback error: {e}")

        return True

    def _executeProfileSwitch(
        self,
        profileId: str,
        triggeredBy: str
    ) -> bool:
        """
        Execute an immediate profile switch.

        Args:
            profileId: Profile ID to switch to
            triggeredBy: What triggered the switch

        Returns:
            True if switch successful
        """
        oldProfileId = self._state.activeProfileId
        now = datetime.now()

        try:
            # Update state
            self._state.activeProfileId = profileId
            self._state.pendingProfileId = None
            self._state.lastChangeTime = now
            self._state.changeCount += 1

            # Update profile manager
            if self._profileManager:
                self._profileManager.setActiveProfile(profileId)

            # Update drive detector's profile ID
            if self._driveDetector:
                self._driveDetector.setProfileId(profileId)

            # Log the change
            event = ProfileChangeEvent(
                timestamp=now,
                oldProfileId=oldProfileId,
                newProfileId=profileId,
                eventType=PROFILE_SWITCH_ACTIVATED,
                triggeredBy=triggeredBy,
                success=True,
            )
            self._logProfileChange(event)
            self._changeHistory.append(event)

            # Update display
            self._updateDisplay()

            logger.info(
                f"Profile switched: {oldProfileId} -> {profileId} "
                f"(triggered by: {triggeredBy})"
            )

            # Trigger callbacks
            for callback in self._onProfileChange:
                try:
                    callback(oldProfileId, profileId)
                except Exception as e:
                    logger.error(f"onProfileChange callback error: {e}")

            return True

        except Exception as e:
            # Log failure
            event = ProfileChangeEvent(
                timestamp=now,
                oldProfileId=oldProfileId,
                newProfileId=profileId,
                eventType=PROFILE_SWITCH_ACTIVATED,
                triggeredBy=triggeredBy,
                success=False,
                errorMessage=str(e),
            )
            self._logProfileChange(event)

            logger.error(f"Profile switch failed: {e}")
            raise ProfileSwitchError(f"Profile switch failed: {e}")

    def cancelPendingSwitch(self) -> bool:
        """
        Cancel a pending profile switch.

        Returns:
            True if there was a pending switch that was cancelled
        """
        if not self._state.pendingProfileId:
            return False

        cancelledProfile = self._state.pendingProfileId
        self._state.pendingProfileId = None

        logger.info(f"Pending profile switch cancelled: {cancelledProfile}")
        return True

    # ================================================================================
    # Drive Event Handlers
    # ================================================================================

    def _onDriveStart(self, driveSession: Any) -> None:
        """
        Handle drive start event.

        If a profile switch is pending, activate it now.

        Args:
            driveSession: DriveSession from drive detector
        """
        self._state.isDriving = True

        # Activate pending switch if any
        if self._state.pendingProfileId:
            pendingId = self._state.pendingProfileId
            logger.info(
                f"Drive started - activating pending profile: {pendingId}"
            )
            self._executeProfileSwitch(pendingId, 'drive_start')

    def _onDriveEnd(self, driveSession: Any) -> None:
        """
        Handle drive end event.

        Args:
            driveSession: DriveSession from drive detector
        """
        self._state.isDriving = False

    # ================================================================================
    # State Queries
    # ================================================================================

    def getActiveProfileId(self) -> Optional[str]:
        """
        Get the currently active profile ID.

        Returns:
            Active profile ID, or None if not set
        """
        return self._state.activeProfileId

    def getActiveProfile(self) -> Optional[Any]:
        """
        Get the currently active Profile object.

        Returns:
            Profile instance, or None if not available
        """
        if not self._profileManager or not self._state.activeProfileId:
            return None

        return self._profileManager.getProfile(self._state.activeProfileId)

    def getPendingProfileId(self) -> Optional[str]:
        """
        Get the pending profile ID (if switch is queued).

        Returns:
            Pending profile ID, or None if no switch pending
        """
        return self._state.pendingProfileId

    def hasPendingSwitch(self) -> bool:
        """
        Check if a profile switch is pending.

        Returns:
            True if a switch is pending
        """
        return self._state.pendingProfileId is not None

    def getState(self) -> SwitcherState:
        """
        Get the current switcher state.

        Returns:
            SwitcherState instance
        """
        return SwitcherState(
            activeProfileId=self._state.activeProfileId,
            pendingProfileId=self._state.pendingProfileId,
            isDriving=self._state.isDriving,
            lastChangeTime=self._state.lastChangeTime,
            changeCount=self._state.changeCount,
        )

    def getChangeHistory(self, limit: int = 20) -> List[ProfileChangeEvent]:
        """
        Get recent profile change history.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of ProfileChangeEvent objects (most recent first)
        """
        return list(reversed(self._changeHistory[-limit:]))

    # ================================================================================
    # Callbacks
    # ================================================================================

    def onProfileChange(
        self,
        callback: Callable[[Optional[str], str], None]
    ) -> None:
        """
        Register callback for profile changes.

        Called when a profile switch is activated.

        Args:
            callback: Function(oldProfileId, newProfileId)
        """
        self._onProfileChange.append(callback)

    def onPendingSwitch(self, callback: Callable[[str], None]) -> None:
        """
        Register callback for pending switches.

        Called when a switch is queued (waiting for drive start).

        Args:
            callback: Function(pendingProfileId)
        """
        self._onPendingSwitch.append(callback)

    # ================================================================================
    # Private Helpers
    # ================================================================================

    def _profileExists(self, profileId: str) -> bool:
        """
        Check if a profile exists.

        Args:
            profileId: Profile ID to check

        Returns:
            True if profile exists
        """
        if not self._profileManager:
            # Without manager, assume profile exists
            return True

        return self._profileManager.profileExists(profileId)

    def _isDriving(self) -> bool:
        """
        Check if currently driving.

        Returns:
            True if drive is in progress
        """
        if not self._driveDetector:
            return False

        return self._driveDetector.isDriving()

    def _updateDisplay(self) -> None:
        """Update the display with current profile."""
        if not self._displayManager:
            return

        # The display manager reads profile name from the StatusInfo
        # passed to showStatus(). This is handled by the caller.
        logger.debug(f"Display should show profile: {self._state.activeProfileId}")

    def _logProfileChange(self, event: ProfileChangeEvent) -> None:
        """
        Log a profile change event to the database.

        Args:
            event: ProfileChangeEvent to log
        """
        if not self._database:
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO connection_log
                    (timestamp, event_type, mac_address, success, error_message)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        event.timestamp,
                        event.eventType,
                        f"profile:{event.oldProfileId}->{event.newProfileId}",
                        event.success,
                        event.errorMessage,
                    )
                )
                logger.debug(
                    f"Profile change logged: {event.eventType} | "
                    f"{event.oldProfileId} -> {event.newProfileId}"
                )
        except Exception as e:
            logger.error(f"Failed to log profile change: {e}")


# ================================================================================
# Helper Functions
# ================================================================================

def createProfileSwitcherFromConfig(
    config: Dict[str, Any],
    profileManager: Optional[Any] = None,
    driveDetector: Optional[Any] = None,
    displayManager: Optional[Any] = None,
    database: Optional[Any] = None
) -> ProfileSwitcher:
    """
    Create a ProfileSwitcher from configuration.

    Args:
        config: Configuration dictionary
        profileManager: ProfileManager instance (optional)
        driveDetector: DriveDetector instance (optional)
        displayManager: DisplayManager instance (optional)
        database: ObdDatabase instance (optional)

    Returns:
        Configured ProfileSwitcher instance
    """
    switcher = ProfileSwitcher(
        profileManager=profileManager,
        driveDetector=driveDetector,
        displayManager=displayManager,
        database=database,
    )

    # Initialize from config
    switcher.initializeFromConfig(config)

    return switcher


def getActiveProfileIdFromConfig(config: Dict[str, Any]) -> Optional[str]:
    """
    Get the active profile ID from configuration.

    Args:
        config: Configuration dictionary

    Returns:
        Active profile ID, or None if not specified
    """
    return config.get('profiles', {}).get('activeProfile')


def getAvailableProfilesFromConfig(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Get list of available profiles from configuration.

    Args:
        config: Configuration dictionary

    Returns:
        List of profile dictionaries
    """
    return config.get('profiles', {}).get('availableProfiles', [])


def isProfileInConfig(config: Dict[str, Any], profileId: str) -> bool:
    """
    Check if a profile exists in the configuration.

    Args:
        config: Configuration dictionary
        profileId: Profile ID to check

    Returns:
        True if profile is in config
    """
    availableProfiles = getAvailableProfilesFromConfig(config)
    return any(p.get('id') == profileId for p in availableProfiles)
