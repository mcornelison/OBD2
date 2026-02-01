################################################################################
# File Name: __init__.py
# Purpose/Description: Profile subpackage for vehicle profile management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | Added all exports for US-013 refactoring
# ================================================================================
################################################################################
"""
Profile Subpackage.

This subpackage contains profile management components:
- Profile dataclass for representing driving/tuning profiles
- ProfileManager class for CRUD operations on profiles
- ProfileSwitcher class for drive-aware profile transitions
- ProfileChangeEvent for tracking profile changes
- Helper functions for configuration and factory operations

Usage:
    from profile import (
        Profile,
        ProfileManager,
        ProfileSwitcher,
        createProfileManagerFromConfig,
        createProfileSwitcherFromConfig,
    )

    # Create manager from config
    manager = createProfileManagerFromConfig(config, database)
    manager.ensureDefaultProfile()

    # Create profile
    profile = Profile(id='track', name='Track Day')
    manager.createProfile(profile)

    # Create switcher for drive-aware switching
    switcher = createProfileSwitcherFromConfig(
        config,
        profileManager=manager,
        driveDetector=driveDetector,
    )
    switcher.requestProfileSwitch('track')
"""

# Types
# Exceptions
from .exceptions import (
    ProfileDatabaseError,
    # Profile Manager Exceptions
    ProfileError,
    ProfileNotFoundError,
    # Profile Switcher Exceptions
    ProfileSwitchError,
    ProfileSwitchNotFoundError,
    ProfileSwitchPendingError,
    ProfileValidationError,
)

# Helpers
from .helpers import (
    # ProfileManager factory
    createProfileManagerFromConfig,
    # ProfileSwitcher factory
    createProfileSwitcherFromConfig,
    getActiveProfileFromConfig,
    getActiveProfileIdFromConfig,
    getAvailableProfilesFromConfig,
    getDefaultProfileConfig,
    # Config access
    getProfileByIdFromConfig,
    getProfileConfig,
    isProfileInConfig,
    isProfileManagementEnabled,
    syncConfigProfilesToDatabase,
    validateProfileConfig,
)

# Manager
from .manager import (
    ProfileManager,
    getDefaultProfile,
)

# Switcher
from .switcher import (
    ProfileSwitcher,
)
from .types import (
    DEFAULT_ALERT_THRESHOLDS,
    DEFAULT_POLLING_INTERVAL_MS,
    DEFAULT_PROFILE_DESCRIPTION,
    # Constants
    DEFAULT_PROFILE_ID,
    DEFAULT_PROFILE_NAME,
    PROFILE_CHANGE_EVENT,
    PROFILE_SWITCH_ACTIVATED,
    PROFILE_SWITCH_REQUESTED,
    # Dataclasses
    Profile,
    ProfileChangeEvent,
    SwitcherState,
)

__all__ = [
    # Dataclasses
    'Profile',
    'ProfileChangeEvent',
    'SwitcherState',
    # Constants
    'DEFAULT_PROFILE_ID',
    'DEFAULT_PROFILE_NAME',
    'DEFAULT_PROFILE_DESCRIPTION',
    'DEFAULT_POLLING_INTERVAL_MS',
    'DEFAULT_ALERT_THRESHOLDS',
    'PROFILE_CHANGE_EVENT',
    'PROFILE_SWITCH_REQUESTED',
    'PROFILE_SWITCH_ACTIVATED',
    # Profile Manager Exceptions
    'ProfileError',
    'ProfileNotFoundError',
    'ProfileValidationError',
    'ProfileDatabaseError',
    # Profile Switcher Exceptions
    'ProfileSwitchError',
    'ProfileSwitchNotFoundError',
    'ProfileSwitchPendingError',
    # Manager
    'ProfileManager',
    'getDefaultProfile',
    # Switcher
    'ProfileSwitcher',
    # ProfileManager factory
    'createProfileManagerFromConfig',
    'syncConfigProfilesToDatabase',
    # ProfileSwitcher factory
    'createProfileSwitcherFromConfig',
    # Config access
    'getProfileByIdFromConfig',
    'getActiveProfileFromConfig',
    'getActiveProfileIdFromConfig',
    'getAvailableProfilesFromConfig',
    'isProfileInConfig',
    'getProfileConfig',
    'isProfileManagementEnabled',
    'getDefaultProfileConfig',
    'validateProfileConfig',
]
