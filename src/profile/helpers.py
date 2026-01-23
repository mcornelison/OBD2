################################################################################
# File Name: helpers.py
# Purpose/Description: Helper functions for profile management
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
Helper functions for the profile subpackage.

Provides:
- Factory functions for creating ProfileManager and ProfileSwitcher from config
- Config access helpers for profile-related settings
- Profile sync and lookup utilities

Usage:
    from obd.profile.helpers import (
        createProfileManagerFromConfig,
        createProfileSwitcherFromConfig,
        getActiveProfileFromConfig,
    )

    manager = createProfileManagerFromConfig(config, database)
    switcher = createProfileSwitcherFromConfig(config, ...)
"""

import logging
from typing import Any, Dict, List, Optional

from .types import Profile
from .manager import ProfileManager
from .switcher import ProfileSwitcher

logger = logging.getLogger(__name__)


# ================================================================================
# ProfileManager Factory Functions
# ================================================================================

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


# ================================================================================
# ProfileSwitcher Factory Functions
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


# ================================================================================
# Config Access Helpers
# ================================================================================

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


def getProfileConfig(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get the profiles section from configuration.

    Args:
        config: Configuration dictionary

    Returns:
        Profiles configuration section (may be empty dict)
    """
    return config.get('profiles', {})


def isProfileManagementEnabled(config: Dict[str, Any]) -> bool:
    """
    Check if profile management is enabled in configuration.

    Returns True if there are available profiles defined.

    Args:
        config: Configuration dictionary

    Returns:
        True if profile management is enabled
    """
    profilesConfig = config.get('profiles', {})
    availableProfiles = profilesConfig.get('availableProfiles', [])
    return len(availableProfiles) > 0


def getDefaultProfileConfig() -> Dict[str, Any]:
    """
    Get the default profile configuration.

    Returns:
        Default profile configuration dictionary
    """
    from .types import (
        DEFAULT_PROFILE_ID,
        DEFAULT_PROFILE_NAME,
        DEFAULT_PROFILE_DESCRIPTION,
        DEFAULT_ALERT_THRESHOLDS,
        DEFAULT_POLLING_INTERVAL_MS,
    )

    return {
        'activeProfile': DEFAULT_PROFILE_ID,
        'availableProfiles': [
            {
                'id': DEFAULT_PROFILE_ID,
                'name': DEFAULT_PROFILE_NAME,
                'description': DEFAULT_PROFILE_DESCRIPTION,
                'alertThresholds': DEFAULT_ALERT_THRESHOLDS.copy(),
                'pollingIntervalMs': DEFAULT_POLLING_INTERVAL_MS,
            }
        ]
    }


def validateProfileConfig(config: Dict[str, Any]) -> List[str]:
    """
    Validate profile configuration.

    Args:
        config: Configuration dictionary

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    profilesConfig = config.get('profiles', {})

    activeProfile = profilesConfig.get('activeProfile')
    availableProfiles = profilesConfig.get('availableProfiles', [])

    # Check if active profile is in available profiles
    if activeProfile:
        if not any(p.get('id') == activeProfile for p in availableProfiles):
            errors.append(
                f"Active profile '{activeProfile}' not found in availableProfiles"
            )

    # Validate each profile
    profileIds = set()
    for i, profile in enumerate(availableProfiles):
        if not profile.get('id'):
            errors.append(f"Profile at index {i} missing required field 'id'")
        elif profile['id'] in profileIds:
            errors.append(f"Duplicate profile ID: {profile['id']}")
        else:
            profileIds.add(profile['id'])

        if not profile.get('name'):
            errors.append(f"Profile at index {i} missing required field 'name'")

    return errors
