################################################################################
# File Name: exceptions.py
# Purpose/Description: Backup system exceptions
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial creation for US-TD-009
# ================================================================================
################################################################################
"""
Backup system exceptions.

This module contains all exception classes for the backup system:
- BackupError: Base exception for backup-related errors
- BackupNotAvailableError: Backup service/provider is not available
- BackupConfigurationError: Error in backup configuration
- BackupOperationError: Error during a backup operation

Exception hierarchy:
    Exception
    └── BackupError
        ├── BackupNotAvailableError
        ├── BackupConfigurationError
        └── BackupOperationError
"""

from typing import Any, Dict, Optional


# ================================================================================
# Backup Exceptions
# ================================================================================

class BackupError(Exception):
    """
    Base exception for backup-related errors.

    Attributes:
        message: Human-readable error message
        details: Additional error context as a dictionary
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialize the exception.

        Args:
            message: Human-readable error message
            details: Additional error context
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        """Return string representation."""
        if self.details:
            return f"{self.message} | details={self.details}"
        return self.message


class BackupNotAvailableError(BackupError):
    """
    Backup service or provider is not available.

    Raised when the backup system cannot connect to or use the
    configured backup provider (e.g., rclone not installed,
    Google Drive not configured, network unavailable).
    """
    pass


class BackupConfigurationError(BackupError):
    """
    Error in backup configuration.

    Raised when backup configuration is invalid or missing required
    settings (e.g., invalid schedule time format, invalid provider).
    """
    pass


class BackupOperationError(BackupError):
    """
    Error during a backup operation.

    Raised when an error occurs during backup operations such as
    database compression, file upload, or metadata update.
    """
    pass
