################################################################################
# File Name: exceptions.py
# Purpose/Description: Exception classes for drive detection module
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation (US-009)
# ================================================================================
################################################################################
"""
Exception classes for drive detection.

Contains custom exceptions for error handling in drive detection:
- DriveDetectorError: Base exception for all drive detector errors
- DriveDetectorConfigError: Configuration-related errors
- DriveDetectorStateError: Invalid state transition errors

These exceptions include typed details dictionaries for clear debugging.
"""

from typing import Any, Dict, Optional


class DriveDetectorError(Exception):
    """
    Base exception for drive detector errors.

    Attributes:
        message: Human-readable error message
        details: Dictionary with additional error context

    Example:
        raise DriveDetectorError(
            "Failed to process RPM value",
            details={'value': -100, 'reason': 'negative RPM'}
        )
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} - {self.details}"
        return self.message


class DriveDetectorConfigError(DriveDetectorError):
    """
    Error in drive detector configuration.

    Raised when configuration values are invalid or missing.

    Example:
        raise DriveDetectorConfigError(
            "Invalid threshold configuration",
            details={
                'invalidFields': ['driveStartRpmThreshold'],
                'reason': 'threshold must be positive'
            }
        )
    """
    pass


class DriveDetectorStateError(DriveDetectorError):
    """
    Invalid state transition error.

    Raised when an invalid state transition is attempted.

    Example:
        raise DriveDetectorStateError(
            "Invalid state transition",
            details={
                'fromState': 'STOPPED',
                'toState': 'STOPPING',
                'reason': 'cannot stop when not running'
            }
        )
    """
    pass
