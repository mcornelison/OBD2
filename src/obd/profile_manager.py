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
# 2026-01-22    | Ralph Agent   | Refactored to re-export from profile subpackage (US-013)
# ================================================================================
################################################################################

"""
Profile management module for the Eclipse OBD-II system.

This module re-exports all components from the profile subpackage for
backward compatibility. New code should import directly from profile.

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

# Re-export all types from the profile subpackage
from profile.types import (
    Profile,
    DEFAULT_PROFILE_ID,
    DEFAULT_PROFILE_NAME,
    DEFAULT_PROFILE_DESCRIPTION,
    DEFAULT_POLLING_INTERVAL_MS,
    DEFAULT_ALERT_THRESHOLDS,
)

# Re-export all exceptions from the profile subpackage
from profile.exceptions import (
    ProfileError,
    ProfileNotFoundError,
    ProfileValidationError,
    ProfileDatabaseError,
)

# Re-export ProfileManager and getDefaultProfile from the profile subpackage
from profile.manager import (
    ProfileManager,
    getDefaultProfile,
)

# Re-export helper functions from the profile subpackage
from profile.helpers import (
    createProfileManagerFromConfig,
    createProfileSwitcherFromConfig,
    syncConfigProfilesToDatabase,
    getProfileByIdFromConfig,
    getActiveProfileFromConfig,
)


__all__ = [
    # Types
    'Profile',
    'DEFAULT_PROFILE_ID',
    'DEFAULT_PROFILE_NAME',
    'DEFAULT_PROFILE_DESCRIPTION',
    'DEFAULT_POLLING_INTERVAL_MS',
    'DEFAULT_ALERT_THRESHOLDS',
    # Exceptions
    'ProfileError',
    'ProfileNotFoundError',
    'ProfileValidationError',
    'ProfileDatabaseError',
    # Manager
    'ProfileManager',
    'getDefaultProfile',
    # Helpers
    'createProfileManagerFromConfig',
    'createProfileSwitcherFromConfig',
    'syncConfigProfilesToDatabase',
    'getProfileByIdFromConfig',
    'getActiveProfileFromConfig',
]
