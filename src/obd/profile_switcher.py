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
# 2026-01-22    | Ralph Agent   | Refactored to re-export from profile subpackage (US-013)
# ================================================================================
################################################################################

"""
Profile switching module for the Eclipse OBD-II Performance Monitoring System.

This module re-exports all components from the profile subpackage for
backward compatibility. New code should import directly from obd.profile.

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

# Re-export types from the profile subpackage
from obd.profile.types import (
    ProfileChangeEvent,
    SwitcherState,
    PROFILE_CHANGE_EVENT,
    PROFILE_SWITCH_REQUESTED,
    PROFILE_SWITCH_ACTIVATED,
)

# Re-export exceptions from the profile subpackage
from obd.profile.exceptions import (
    ProfileSwitchError,
    ProfileSwitchNotFoundError,
    ProfileSwitchPendingError,
)

# Re-export ProfileSwitcher from the profile subpackage
from obd.profile.switcher import ProfileSwitcher

# Re-export helper functions from the profile subpackage
from obd.profile.helpers import (
    createProfileSwitcherFromConfig,
    getActiveProfileIdFromConfig,
    getAvailableProfilesFromConfig,
    isProfileInConfig,
)

# For backward compatibility with original exception names
ProfileNotFoundError = ProfileSwitchNotFoundError


__all__ = [
    # Types
    'ProfileChangeEvent',
    'SwitcherState',
    'PROFILE_CHANGE_EVENT',
    'PROFILE_SWITCH_REQUESTED',
    'PROFILE_SWITCH_ACTIVATED',
    # Exceptions
    'ProfileSwitchError',
    'ProfileNotFoundError',  # Backward compat alias
    'ProfileSwitchNotFoundError',
    'ProfileSwitchPendingError',
    # Switcher
    'ProfileSwitcher',
    # Helpers
    'createProfileSwitcherFromConfig',
    'getActiveProfileIdFromConfig',
    'getAvailableProfilesFromConfig',
    'isProfileInConfig',
]
