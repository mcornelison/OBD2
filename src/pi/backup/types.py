################################################################################
# File Name: types.py
# Purpose/Description: Backup types, enums, and dataclasses
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
Backup types, enums, and dataclasses.

This module contains all type definitions for the backup system:
- BackupStatus enum for backup operation states
- BackupConfig dataclass for backup configuration settings
- BackupResult dataclass for backup operation results

All types have zero project dependencies (stdlib only) to avoid circular imports.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

# ================================================================================
# Backup Constants
# ================================================================================

# Default backup provider
DEFAULT_BACKUP_PROVIDER = 'google_drive'

# Default backup folder path in remote storage
DEFAULT_BACKUP_FOLDER_PATH = 'OBD2_Backups'

# Default backup schedule time (HH:MM format)
DEFAULT_BACKUP_SCHEDULE_TIME = '03:00'

# Default maximum number of backups to keep
DEFAULT_MAX_BACKUPS = 30

# Default compression setting
DEFAULT_COMPRESS_BACKUPS = True

# Default catch-up backup threshold in days
DEFAULT_CATCHUP_DAYS = 2

# Backup file extension
BACKUP_FILE_EXTENSION = '.gz'

# Backup metadata filename
BACKUP_METADATA_FILENAME = 'backup_metadata.json'


# ================================================================================
# Backup Enums
# ================================================================================

class BackupStatus(Enum):
    """
    Status of a backup operation.

    Values:
        PENDING: Backup is scheduled but not yet started
        IN_PROGRESS: Backup is currently running
        COMPLETED: Backup completed successfully
        FAILED: Backup failed with an error
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# ================================================================================
# Backup Data Classes
# ================================================================================

@dataclass
class BackupConfig:
    """
    Configuration settings for the backup system.

    Attributes:
        enabled: Whether backup functionality is enabled
        provider: Backup provider (e.g., 'google_drive')
        folderPath: Remote folder path for storing backups
        scheduleTime: Daily backup time in HH:MM format
        maxBackups: Maximum number of backups to retain
        compressBackups: Whether to compress backups (.gz)
        catchupDays: Days threshold for catch-up backup
    """

    enabled: bool = False
    provider: str = DEFAULT_BACKUP_PROVIDER
    folderPath: str = DEFAULT_BACKUP_FOLDER_PATH
    scheduleTime: str = DEFAULT_BACKUP_SCHEDULE_TIME
    maxBackups: int = DEFAULT_MAX_BACKUPS
    compressBackups: bool = DEFAULT_COMPRESS_BACKUPS
    catchupDays: int = DEFAULT_CATCHUP_DAYS

    def toDict(self) -> dict[str, Any]:
        """
        Convert to dictionary for logging/serialization.

        Returns:
            Dictionary representation of the configuration
        """
        return {
            'enabled': self.enabled,
            'provider': self.provider,
            'folderPath': self.folderPath,
            'scheduleTime': self.scheduleTime,
            'maxBackups': self.maxBackups,
            'compressBackups': self.compressBackups,
            'catchupDays': self.catchupDays,
        }

    @classmethod
    def fromDict(cls, data: dict[str, Any]) -> 'BackupConfig':
        """
        Create BackupConfig from a dictionary.

        Args:
            data: Dictionary with backup configuration values

        Returns:
            BackupConfig instance with values from dictionary
        """
        return cls(
            enabled=data.get('enabled', False),
            provider=data.get('provider', DEFAULT_BACKUP_PROVIDER),
            folderPath=data.get('folderPath', DEFAULT_BACKUP_FOLDER_PATH),
            scheduleTime=data.get('scheduleTime', DEFAULT_BACKUP_SCHEDULE_TIME),
            maxBackups=data.get('maxBackups', DEFAULT_MAX_BACKUPS),
            compressBackups=data.get('compressBackups', DEFAULT_COMPRESS_BACKUPS),
            catchupDays=data.get('catchupDays', DEFAULT_CATCHUP_DAYS),
        )


@dataclass
class BackupResult:
    """
    Result of a backup operation.

    Attributes:
        success: Whether the backup completed successfully
        timestamp: When the backup was performed
        size: Size of the backup file in bytes (None if failed)
        error: Error message if the backup failed (None if success)
        backupPath: Path to the backup file (None if failed)
        remotePath: Remote path where backup was uploaded (None if not uploaded)
    """

    success: bool
    timestamp: datetime
    size: int | None = None
    error: str | None = None
    backupPath: str | None = None
    remotePath: str | None = None

    def toDict(self) -> dict[str, Any]:
        """
        Convert to dictionary for logging/serialization.

        Returns:
            Dictionary representation of the result
        """
        return {
            'success': self.success,
            'timestamp': self.timestamp.isoformat(),
            'size': self.size,
            'error': self.error,
            'backupPath': self.backupPath,
            'remotePath': self.remotePath,
        }

    @classmethod
    def fromDict(cls, data: dict[str, Any]) -> 'BackupResult':
        """
        Create BackupResult from a dictionary.

        Args:
            data: Dictionary with backup result values

        Returns:
            BackupResult instance with values from dictionary
        """
        timestampStr = data.get('timestamp')
        if isinstance(timestampStr, str):
            timestamp = datetime.fromisoformat(timestampStr)
        elif isinstance(timestampStr, datetime):
            timestamp = timestampStr
        else:
            timestamp = datetime.now()

        return cls(
            success=data.get('success', False),
            timestamp=timestamp,
            size=data.get('size'),
            error=data.get('error'),
            backupPath=data.get('backupPath'),
            remotePath=data.get('remotePath'),
        )

    @classmethod
    def createSuccess(
        cls,
        size: int,
        backupPath: str,
        remotePath: str | None = None,
        timestamp: datetime | None = None
    ) -> 'BackupResult':
        """
        Create a successful backup result.

        Args:
            size: Size of the backup file in bytes
            backupPath: Path to the backup file
            remotePath: Remote path where backup was uploaded
            timestamp: When the backup was performed (defaults to now)

        Returns:
            BackupResult indicating success
        """
        return cls(
            success=True,
            timestamp=timestamp or datetime.now(),
            size=size,
            error=None,
            backupPath=backupPath,
            remotePath=remotePath,
        )

    @classmethod
    def createFailure(
        cls,
        error: str,
        timestamp: datetime | None = None
    ) -> 'BackupResult':
        """
        Create a failed backup result.

        Args:
            error: Error message describing the failure
            timestamp: When the backup was attempted (defaults to now)

        Returns:
            BackupResult indicating failure
        """
        return cls(
            success=False,
            timestamp=timestamp or datetime.now(),
            size=None,
            error=error,
            backupPath=None,
            remotePath=None,
        )
