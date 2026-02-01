################################################################################
# File Name: exceptions.py
# Purpose/Description: Custom exceptions for profile management
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
Custom exceptions for the profile subpackage.

Contains:
- ProfileError: Base exception for profile-related errors
- ProfileNotFoundError: When profile is not found
- ProfileValidationError: When profile data is invalid
- ProfileDatabaseError: When database operation fails
- ProfileSwitchError: Base exception for profile switch errors
- ProfileSwitchPendingError: When a switch is already pending

This module has no dependencies on other project modules (only stdlib).
"""

from typing import Any

# ================================================================================
# Profile Manager Exceptions
# ================================================================================

class ProfileError(Exception):
    """Base exception for profile-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """
        Initialize the exception.

        Args:
            message: Error message
            details: Additional error details as a dictionary
        """
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
        invalidFields: list[str] | None = None,
        details: dict[str, Any] | None = None
    ):
        """
        Initialize the exception.

        Args:
            message: Error message
            invalidFields: List of invalid field names
            details: Additional error details
        """
        super().__init__(message, details)
        self.invalidFields = invalidFields or []


class ProfileDatabaseError(ProfileError):
    """Error performing database operation on profile."""
    pass


# ================================================================================
# Profile Switcher Exceptions
# ================================================================================

class ProfileSwitchError(Exception):
    """Base exception for profile switch errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """
        Initialize the exception.

        Args:
            message: Error message
            details: Additional error details as a dictionary
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ProfileSwitchNotFoundError(ProfileSwitchError):
    """Raised when requested profile doesn't exist during switch."""
    pass


class ProfileSwitchPendingError(ProfileSwitchError):
    """Raised when a switch is already pending."""
    pass
