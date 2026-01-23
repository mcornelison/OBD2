################################################################################
# File Name: manager.py
# Purpose/Description: ProfileManager class for profile CRUD operations
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
ProfileManager class for the profile subpackage.

Provides CRUD operations for driving/tuning profiles with database persistence.
Supports creating, reading, updating, and deleting profiles, with special
handling for the default 'Daily' profile.

Usage:
    from obd.profile.manager import ProfileManager
    from obd.profile.types import Profile

    manager = ProfileManager(database=db)
    manager.ensureDefaultProfile()

    profile = Profile(id='track', name='Track Day')
    manager.createProfile(profile)
    manager.setActiveProfile('track')
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .types import (
    Profile,
    DEFAULT_PROFILE_ID,
    DEFAULT_PROFILE_NAME,
    DEFAULT_PROFILE_DESCRIPTION,
    DEFAULT_ALERT_THRESHOLDS,
    DEFAULT_POLLING_INTERVAL_MS,
)
from .exceptions import (
    ProfileError,
    ProfileNotFoundError,
    ProfileValidationError,
    ProfileDatabaseError,
)

logger = logging.getLogger(__name__)


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
        alertThresholds: Dict[str, Any] = {}
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
