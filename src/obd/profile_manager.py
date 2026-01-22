################################################################################
# File Name: profile_manager.py
# Purpose/Description: Profile management system for OBD-II monitoring
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-024
# ================================================================================
################################################################################

"""
Profile management module for the Eclipse OBD-II system.

Provides:
- Profile dataclass for representing driving/tuning profiles
- ProfileManager class for CRUD operations on profiles
- Default 'Daily' profile creation on first run
- Profile-specific alert thresholds and polling intervals

Profiles allow users to track data separately for different driving scenarios:
- Daily driving: Conservative thresholds, standard polling
- Performance/Track: Higher thresholds, faster polling
- Custom profiles: User-defined settings

Usage:
    from obd.profile_manager import ProfileManager, Profile

    # Create manager
    manager = ProfileManager(database=db)

    # Ensure default profile exists
    manager.ensureDefaultProfile()

    # Create custom profile
    profile = Profile(
        id='track',
        name='Track Day',
        alertThresholds={'rpmRedline': 7500},
        pollingIntervalMs=500
    )
    manager.createProfile(profile)

    # Set active profile
    manager.setActiveProfile('track')
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Default profile settings
DEFAULT_PROFILE_ID = 'daily'
DEFAULT_PROFILE_NAME = 'Daily'
DEFAULT_PROFILE_DESCRIPTION = 'Normal daily driving profile'
DEFAULT_POLLING_INTERVAL_MS = 1000

# Default alert thresholds for the default profile
DEFAULT_ALERT_THRESHOLDS = {
    'rpmRedline': 6500,
    'coolantTempCritical': 110,
    'oilPressureLow': 20,
}


# ================================================================================
# Custom Exceptions
# ================================================================================

class ProfileError(Exception):
    """Base exception for profile-related errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ProfileNotFoundError(ProfileError):
    """Error when profile is not found."""
    pass


class ProfileValidationError(ProfileError):
    """Error validating profile data."""

    def __init__(
        self,
        message: str,
        invalidFields: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, details)
        self.invalidFields = invalidFields or []


class ProfileDatabaseError(ProfileError):
    """Error performing database operation on profile."""
    pass


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
    description: Optional[str] = None
    alertThresholds: Dict[str, Any] = field(default_factory=dict)
    pollingIntervalMs: int = DEFAULT_POLLING_INTERVAL_MS
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    def toDict(self) -> Dict[str, Any]:
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
    def fromDict(cls, data: Dict[str, Any]) -> 'Profile':
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
    def fromConfigDict(cls, configProfile: Dict[str, Any]) -> 'Profile':
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
            pollingIntervalMs=configProfile.get('pollingIntervalMs', DEFAULT_POLLING_INTERVAL_MS),
        )

    def getAlertConfigJson(self) -> str:
        """
        Get alert thresholds as JSON string for database storage.

        Returns:
            JSON string of alert thresholds
        """
        return json.dumps(self.alertThresholds)


# ================================================================================
# Profile Manager Class
# ================================================================================

class ProfileManager:
    """
    Manages driving/tuning profiles in the database.

    Provides CRUD operations for profiles and ensures the default
    'Daily' profile exists on first run.

    Features:
    - Create, read, update, delete profiles
    - Ensure default profile exists
    - Active profile tracking
    - Profile validation

    Example:
        manager = ProfileManager(database=db)
        manager.ensureDefaultProfile()

        profile = Profile(id='track', name='Track Day')
        manager.createProfile(profile)

        manager.setActiveProfile('track')
    """

    def __init__(self, database: Optional[Any] = None):
        """
        Initialize the profile manager.

        Args:
            database: ObdDatabase instance for persistence
        """
        self._database = database
        self._activeProfileId: Optional[str] = None

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

    # ================================================================================
    # CRUD Operations
    # ================================================================================

    def createProfile(self, profile: Profile) -> None:
        """
        Create a new profile in the database.

        Args:
            profile: Profile to create

        Raises:
            ProfileValidationError: If profile data is invalid
            ProfileError: If profile already exists
            ProfileDatabaseError: If database operation fails
        """
        # Validate
        self._validateProfile(profile)

        # Check for existing
        if self.profileExists(profile.id):
            raise ProfileError(
                f"Profile already exists: {profile.id}",
                details={'profileId': profile.id}
            )

        if not self._database:
            logger.warning("No database configured, profile not persisted")
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO profiles
                    (id, name, description, alert_config_json, polling_interval_ms)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        profile.id,
                        profile.name,
                        profile.description,
                        profile.getAlertConfigJson(),
                        profile.pollingIntervalMs,
                    )
                )
                logger.info(f"Created profile: {profile.id}")

        except Exception as e:
            raise ProfileDatabaseError(
                f"Failed to create profile: {e}",
                details={'profileId': profile.id, 'error': str(e)}
            )

    def getProfile(self, profileId: str) -> Optional[Profile]:
        """
        Get a profile by ID.

        Args:
            profileId: Profile ID to retrieve

        Returns:
            Profile if found, None otherwise
        """
        if not self._database:
            return None

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, name, description, alert_config_json,
                           polling_interval_ms, created_at, updated_at
                    FROM profiles
                    WHERE id = ?
                    """,
                    (profileId,)
                )
                row = cursor.fetchone()

                if not row:
                    return None

                return self._rowToProfile(row)

        except Exception as e:
            logger.error(f"Failed to get profile {profileId}: {e}")
            return None

    def getAllProfiles(self) -> List[Profile]:
        """
        Get all profiles.

        Returns:
            List of all profiles
        """
        if not self._database:
            return []

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, name, description, alert_config_json,
                           polling_interval_ms, created_at, updated_at
                    FROM profiles
                    ORDER BY name
                    """
                )
                rows = cursor.fetchall()

                return [self._rowToProfile(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get all profiles: {e}")
            return []

    def updateProfile(self, profile: Profile) -> None:
        """
        Update an existing profile.

        Args:
            profile: Profile with updated data

        Raises:
            ProfileNotFoundError: If profile doesn't exist
            ProfileDatabaseError: If database operation fails
        """
        if not self.profileExists(profile.id):
            raise ProfileNotFoundError(
                f"Profile not found: {profile.id}",
                details={'profileId': profile.id}
            )

        if not self._database:
            logger.warning("No database configured, profile not updated")
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE profiles
                    SET name = ?,
                        description = ?,
                        alert_config_json = ?,
                        polling_interval_ms = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        profile.name,
                        profile.description,
                        profile.getAlertConfigJson(),
                        profile.pollingIntervalMs,
                        profile.id,
                    )
                )
                logger.info(f"Updated profile: {profile.id}")

        except Exception as e:
            raise ProfileDatabaseError(
                f"Failed to update profile: {e}",
                details={'profileId': profile.id, 'error': str(e)}
            )

    def deleteProfile(self, profileId: str) -> None:
        """
        Delete a profile.

        Args:
            profileId: ID of profile to delete

        Raises:
            ProfileNotFoundError: If profile doesn't exist
            ProfileDatabaseError: If database operation fails
        """
        if not self.profileExists(profileId):
            raise ProfileNotFoundError(
                f"Profile not found: {profileId}",
                details={'profileId': profileId}
            )

        if not self._database:
            logger.warning("No database configured, profile not deleted")
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM profiles WHERE id = ?",
                    (profileId,)
                )
                logger.info(f"Deleted profile: {profileId}")

                # Clear active profile if deleted
                if self._activeProfileId == profileId:
                    self._activeProfileId = None

        except Exception as e:
            raise ProfileDatabaseError(
                f"Failed to delete profile: {e}",
                details={'profileId': profileId, 'error': str(e)}
            )

    def profileExists(self, profileId: str) -> bool:
        """
        Check if a profile exists.

        Args:
            profileId: Profile ID to check

        Returns:
            True if profile exists
        """
        if not self._database:
            return False

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM profiles WHERE id = ?",
                    (profileId,)
                )
                return cursor.fetchone() is not None

        except Exception as e:
            logger.error(f"Failed to check profile existence: {e}")
            return False

    # ================================================================================
    # Default Profile
    # ================================================================================

    def ensureDefaultProfile(self) -> None:
        """
        Ensure the default 'Daily' profile exists.

        Creates the default profile if it doesn't exist.
        Does nothing if it already exists (preserves user modifications).
        """
        if self.profileExists(DEFAULT_PROFILE_ID):
            logger.debug(f"Default profile '{DEFAULT_PROFILE_ID}' already exists")
            return

        defaultProfile = getDefaultProfile()

        try:
            self.createProfile(defaultProfile)
            logger.info(f"Created default profile: {DEFAULT_PROFILE_ID}")
        except ProfileError as e:
            logger.warning(f"Could not create default profile: {e}")

    # ================================================================================
    # Active Profile
    # ================================================================================

    def setActiveProfile(self, profileId: str) -> None:
        """
        Set the active profile.

        Args:
            profileId: ID of profile to make active

        Raises:
            ProfileNotFoundError: If profile doesn't exist
        """
        if not self.profileExists(profileId):
            raise ProfileNotFoundError(
                f"Profile not found: {profileId}",
                details={'profileId': profileId}
            )

        self._activeProfileId = profileId
        logger.info(f"Active profile set to: {profileId}")

    def getActiveProfileId(self) -> Optional[str]:
        """
        Get the active profile ID.

        Returns:
            Active profile ID, or None if not set
        """
        return self._activeProfileId

    def getActiveProfile(self) -> Optional[Profile]:
        """
        Get the active profile.

        Returns:
            Active Profile instance, or None if not set
        """
        if not self._activeProfileId:
            return None

        return self.getProfile(self._activeProfileId)

    # ================================================================================
    # Statistics
    # ================================================================================

    def getProfileCount(self) -> int:
        """
        Get the number of profiles.

        Returns:
            Number of profiles in database
        """
        if not self._database:
            return 0

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM profiles")
                return cursor.fetchone()[0]

        except Exception as e:
            logger.error(f"Failed to get profile count: {e}")
            return 0

    def getProfileIds(self) -> List[str]:
        """
        Get all profile IDs.

        Returns:
            List of profile IDs
        """
        if not self._database:
            return []

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM profiles ORDER BY name")
                return [row[0] for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"Failed to get profile IDs: {e}")
            return []

    # ================================================================================
    # Private Methods
    # ================================================================================

    def _validateProfile(self, profile: Profile) -> None:
        """
        Validate profile data.

        Args:
            profile: Profile to validate

        Raises:
            ProfileValidationError: If validation fails
        """
        invalidFields = []

        if not profile.id or not profile.id.strip():
            invalidFields.append('id')

        if not profile.name or not profile.name.strip():
            invalidFields.append('name')

        if invalidFields:
            raise ProfileValidationError(
                f"Invalid profile data: {', '.join(invalidFields)}",
                invalidFields=invalidFields
            )

    def _rowToProfile(self, row: Any) -> Profile:
        """
        Convert database row to Profile.

        Args:
            row: Database row

        Returns:
            Profile instance
        """
        # Parse alert thresholds from JSON
        alertThresholds = {}
        if row['alert_config_json']:
            try:
                alertThresholds = json.loads(row['alert_config_json'])
            except json.JSONDecodeError:
                logger.warning(f"Invalid alert config JSON for profile {row['id']}")

        return Profile(
            id=row['id'],
            name=row['name'],
            description=row['description'],
            alertThresholds=alertThresholds,
            pollingIntervalMs=row['polling_interval_ms'] or DEFAULT_POLLING_INTERVAL_MS,
            createdAt=row['created_at'],
            updatedAt=row['updated_at'],
        )


# ================================================================================
# Helper Functions
# ================================================================================

def getDefaultProfile() -> Profile:
    """
    Get the default 'Daily' profile.

    Returns:
        Default Profile instance
    """
    return Profile(
        id=DEFAULT_PROFILE_ID,
        name=DEFAULT_PROFILE_NAME,
        description=DEFAULT_PROFILE_DESCRIPTION,
        alertThresholds=DEFAULT_ALERT_THRESHOLDS.copy(),
        pollingIntervalMs=DEFAULT_POLLING_INTERVAL_MS,
    )


def createProfileManagerFromConfig(
    config: Dict[str, Any],
    database: Optional[Any] = None
) -> ProfileManager:
    """
    Create a ProfileManager from configuration.

    Loads profiles from config file and syncs them to the database.

    Args:
        config: Configuration dictionary
        database: ObdDatabase instance (optional)

    Returns:
        Configured ProfileManager instance
    """
    manager = ProfileManager(database=database)

    profilesConfig = config.get('profiles', {})

    # Load profiles from config
    availableProfiles = profilesConfig.get('availableProfiles', [])
    for profileData in availableProfiles:
        try:
            profile = Profile.fromConfigDict(profileData)

            # Create or update in database
            if database and not manager.profileExists(profile.id):
                manager.createProfile(profile)
            elif database:
                manager.updateProfile(profile)

        except Exception as e:
            logger.warning(f"Failed to load profile from config: {e}")

    # Set active profile
    activeProfile = profilesConfig.get('activeProfile')
    if activeProfile and manager.profileExists(activeProfile):
        manager.setActiveProfile(activeProfile)

    profileCount = manager.getProfileCount()
    logger.info(f"ProfileManager created with {profileCount} profiles")

    return manager


def syncConfigProfilesToDatabase(
    config: Dict[str, Any],
    database: Any
) -> int:
    """
    Sync profiles from config to database.

    Creates profiles that don't exist, updates those that do.

    Args:
        config: Configuration dictionary
        database: ObdDatabase instance

    Returns:
        Number of profiles synced
    """
    manager = ProfileManager(database=database)

    profilesConfig = config.get('profiles', {})
    availableProfiles = profilesConfig.get('availableProfiles', [])

    synced = 0
    for profileData in availableProfiles:
        try:
            profile = Profile.fromConfigDict(profileData)

            if manager.profileExists(profile.id):
                manager.updateProfile(profile)
            else:
                manager.createProfile(profile)

            synced += 1

        except Exception as e:
            logger.warning(f"Failed to sync profile: {e}")

    logger.info(f"Synced {synced} profiles from config")
    return synced


def getProfileByIdFromConfig(
    config: Dict[str, Any],
    profileId: str
) -> Optional[Profile]:
    """
    Get a profile by ID from config (without database).

    Args:
        config: Configuration dictionary
        profileId: Profile ID to find

    Returns:
        Profile if found, None otherwise
    """
    profilesConfig = config.get('profiles', {})
    availableProfiles = profilesConfig.get('availableProfiles', [])

    for profileData in availableProfiles:
        if profileData.get('id') == profileId:
            return Profile.fromConfigDict(profileData)

    return None


def getActiveProfileFromConfig(config: Dict[str, Any]) -> Optional[Profile]:
    """
    Get the active profile from config (without database).

    Args:
        config: Configuration dictionary

    Returns:
        Active Profile if found, None otherwise
    """
    profilesConfig = config.get('profiles', {})
    activeProfileId = profilesConfig.get('activeProfile')

    if not activeProfileId:
        return None

    return getProfileByIdFromConfig(config, activeProfileId)
