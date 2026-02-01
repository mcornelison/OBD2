################################################################################
# File Name: __init__.py
# Purpose/Description: Backup subpackage for database backup and cloud sync
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial subpackage creation (US-TD-009)
# ================================================================================
################################################################################
"""
Backup Subpackage.

This subpackage contains backup system components:
- Types and enums for backup operations
- Exception classes for error handling
- BackupManager for orchestrating database backups
- GoogleDriveUploader for uploading backups to Google Drive via rclone

Exports:
    Types and Constants:
        - BackupStatus: Enum for backup operation states (PENDING, IN_PROGRESS, COMPLETED, FAILED)
        - BackupConfig: Dataclass for backup configuration settings
        - BackupResult: Dataclass for backup operation results
        - Constants for defaults and file names

    Manager:
        - BackupManager: Orchestrates database backups with compression and metadata

    Uploaders:
        - GoogleDriveUploader: Uploads files to Google Drive via rclone
        - UploadResult: Dataclass for upload operation results
        - Constants for rclone timeouts and remote names

    Exceptions:
        - BackupError: Base backup exception
        - BackupNotAvailableError: Backup provider not available
        - BackupConfigurationError: Invalid backup configuration
        - BackupOperationError: Error during backup operation
"""

# Types and constants
from .types import (
    # Enums
    BackupStatus,
    # Dataclasses
    BackupConfig,
    BackupResult,
    # Constants
    DEFAULT_BACKUP_PROVIDER,
    DEFAULT_BACKUP_FOLDER_PATH,
    DEFAULT_BACKUP_SCHEDULE_TIME,
    DEFAULT_MAX_BACKUPS,
    DEFAULT_COMPRESS_BACKUPS,
    DEFAULT_CATCHUP_DAYS,
    BACKUP_FILE_EXTENSION,
    BACKUP_METADATA_FILENAME,
)

# Exceptions
from .exceptions import (
    BackupError,
    BackupNotAvailableError,
    BackupConfigurationError,
    BackupOperationError,
)

# Manager
from .backup_manager import BackupManager

# Uploaders
from .google_drive import (
    GoogleDriveUploader,
    UploadResult,
    DEFAULT_REMOTE_NAME,
    RCLONE_CHECK_TIMEOUT,
    RCLONE_UPLOAD_TIMEOUT,
)

__all__ = [
    # Enums
    'BackupStatus',
    # Dataclasses
    'BackupConfig',
    'BackupResult',
    # Constants
    'DEFAULT_BACKUP_PROVIDER',
    'DEFAULT_BACKUP_FOLDER_PATH',
    'DEFAULT_BACKUP_SCHEDULE_TIME',
    'DEFAULT_MAX_BACKUPS',
    'DEFAULT_COMPRESS_BACKUPS',
    'DEFAULT_CATCHUP_DAYS',
    'BACKUP_FILE_EXTENSION',
    'BACKUP_METADATA_FILENAME',
    # Exceptions
    'BackupError',
    'BackupNotAvailableError',
    'BackupConfigurationError',
    'BackupOperationError',
    # Manager
    'BackupManager',
    # Uploaders
    'GoogleDriveUploader',
    'UploadResult',
    'DEFAULT_REMOTE_NAME',
    'RCLONE_CHECK_TIMEOUT',
    'RCLONE_UPLOAD_TIMEOUT',
]
