################################################################################
# File Name: backup_manager.py
# Purpose/Description: BackupManager class for orchestrating database backups
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial implementation for US-TD-010
# ================================================================================
################################################################################
"""
BackupManager class for database backup orchestration.

Provides functionality for backing up the OBD database to compressed .gz files,
managing backup metadata, and cleaning up old backups.

Features:
- Compress database to .gz format
- Track backup history via metadata
- Catch-up backup detection for missed backups
- Old backup cleanup with configurable retention

Usage:
    from backup.backup_manager import BackupManager
    from backup.types import BackupConfig

    config = BackupConfig(enabled=True, maxBackups=30)
    manager = BackupManager(config, dataDir='data')

    result = manager.performBackup()
    if result.success:
        print(f"Backup created: {result.backupPath}")
"""

import gzip
import json
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import (
    BackupConfig,
    BackupResult,
    BackupStatus,
    BACKUP_FILE_EXTENSION,
    BACKUP_METADATA_FILENAME,
    DEFAULT_MAX_BACKUPS,
    DEFAULT_CATCHUP_DAYS,
)
from .exceptions import (
    BackupOperationError,
    BackupConfigurationError,
)

logger = logging.getLogger(__name__)

# Default database filename
DEFAULT_DATABASE_FILENAME = 'obd.db'

# Backup filename format: obd_backup_YYYYMMDD_HHMMSS_ffffff.db.gz
# Uses microseconds for uniqueness when multiple backups occur in same second
BACKUP_FILENAME_FORMAT = 'obd_backup_{timestamp}.db.gz'


class BackupManager:
    """
    Manages database backups with compression and metadata tracking.

    Provides functionality for:
    - Creating compressed (.gz) backups of the database
    - Tracking backup history via JSON metadata
    - Determining when catch-up backups are needed
    - Cleaning up old backups to manage storage

    Example:
        config = BackupConfig(enabled=True, maxBackups=30)
        manager = BackupManager(config, dataDir='data')

        # Perform backup
        result = manager.performBackup()

        # Check for catch-up backup
        if manager.shouldRunCatchupBackup():
            manager.performBackup()

        # Clean up old backups
        manager.cleanupOldBackups()
    """

    def __init__(
        self,
        config: Optional[BackupConfig] = None,
        dataDir: str = 'data',
        databaseFilename: str = DEFAULT_DATABASE_FILENAME
    ):
        """
        Initialize the backup manager.

        Args:
            config: Backup configuration settings (uses defaults if None)
            dataDir: Directory containing the database and where backups are stored
            databaseFilename: Name of the database file to backup
        """
        self._config = config or BackupConfig()
        self._dataDir = Path(dataDir)
        self._databaseFilename = databaseFilename
        self._status = BackupStatus.PENDING
        self._lastResult: Optional[BackupResult] = None

    # ================================================================================
    # Configuration
    # ================================================================================

    def setConfig(self, config: BackupConfig) -> None:
        """
        Update the backup configuration.

        Args:
            config: New backup configuration
        """
        self._config = config

    def getConfig(self) -> BackupConfig:
        """
        Get the current backup configuration.

        Returns:
            Current BackupConfig
        """
        return self._config

    def setDataDir(self, dataDir: str) -> None:
        """
        Update the data directory path.

        Args:
            dataDir: New data directory path
        """
        self._dataDir = Path(dataDir)

    # ================================================================================
    # Backup Operations
    # ================================================================================

    def performBackup(self) -> BackupResult:
        """
        Perform a database backup.

        Compresses the database file to .gz format and saves it to the
        data directory. Updates backup metadata on success.

        Returns:
            BackupResult with success status, file path, and size

        Raises:
            BackupOperationError: If backup fails due to file access issues
        """
        self._status = BackupStatus.IN_PROGRESS
        timestamp = datetime.now()

        # Validate paths
        databasePath = self._dataDir / self._databaseFilename
        if not databasePath.exists():
            error = f"Database file not found: {databasePath}"
            logger.error(error)
            self._status = BackupStatus.FAILED
            result = BackupResult.createFailure(error, timestamp)
            self._lastResult = result
            return result

        # Generate backup filename (include microseconds for uniqueness)
        timestampStr = timestamp.strftime('%Y%m%d_%H%M%S_%f')
        backupFilename = f'obd_backup_{timestampStr}.db{BACKUP_FILE_EXTENSION}'
        backupPath = self._dataDir / backupFilename

        try:
            # Compress database to .gz
            if self._config.compressBackups:
                self._compressFile(databasePath, backupPath)
            else:
                # Just copy if compression disabled
                shutil.copy2(databasePath, backupPath)

            # Get backup size
            backupSize = backupPath.stat().st_size

            # Update metadata
            self._updateMetadata(backupPath, timestamp, backupSize)

            self._status = BackupStatus.COMPLETED
            result = BackupResult.createSuccess(
                size=backupSize,
                backupPath=str(backupPath),
                timestamp=timestamp
            )
            self._lastResult = result

            logger.info(
                f"Backup completed: {backupFilename} "
                f"({backupSize / 1024:.1f} KB)"
            )
            return result

        except Exception as e:
            error = f"Backup failed: {e}"
            logger.error(error)
            self._status = BackupStatus.FAILED
            result = BackupResult.createFailure(error, timestamp)
            self._lastResult = result

            # Clean up partial backup file if exists
            if backupPath.exists():
                try:
                    backupPath.unlink()
                except Exception:
                    pass

            raise BackupOperationError(error, details={'exception': str(e)})

    def _compressFile(self, sourcePath: Path, destPath: Path) -> None:
        """
        Compress a file using gzip.

        Args:
            sourcePath: Path to the source file
            destPath: Path for the compressed output file
        """
        with open(sourcePath, 'rb') as sourceFile:
            with gzip.open(destPath, 'wb') as destFile:
                shutil.copyfileobj(sourceFile, destFile)

    # ================================================================================
    # Metadata Operations
    # ================================================================================

    def _getMetadataPath(self) -> Path:
        """
        Get the path to the backup metadata file.

        Returns:
            Path to backup_metadata.json
        """
        return self._dataDir / BACKUP_METADATA_FILENAME

    def _loadMetadata(self) -> Dict[str, Any]:
        """
        Load backup metadata from file.

        Returns:
            Dictionary with backup metadata, or empty dict if not found
        """
        metadataPath = self._getMetadataPath()

        if not metadataPath.exists():
            return {'backups': [], 'lastBackupTime': None}

        try:
            with open(metadataPath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load backup metadata: {e}")
            return {'backups': [], 'lastBackupTime': None}

    def _saveMetadata(self, metadata: Dict[str, Any]) -> None:
        """
        Save backup metadata to file.

        Args:
            metadata: Metadata dictionary to save
        """
        metadataPath = self._getMetadataPath()

        try:
            with open(metadataPath, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, default=str)
        except IOError as e:
            logger.error(f"Failed to save backup metadata: {e}")

    def _updateMetadata(
        self,
        backupPath: Path,
        timestamp: datetime,
        size: int
    ) -> None:
        """
        Update metadata with new backup information.

        Args:
            backupPath: Path to the backup file
            timestamp: When the backup was created
            size: Size of the backup in bytes
        """
        metadata = self._loadMetadata()

        # Add new backup entry
        backupEntry = {
            'filename': backupPath.name,
            'timestamp': timestamp.isoformat(),
            'size': size,
            'path': str(backupPath),
        }
        metadata['backups'].append(backupEntry)
        metadata['lastBackupTime'] = timestamp.isoformat()

        self._saveMetadata(metadata)

    def getLastBackupTime(self) -> Optional[datetime]:
        """
        Get the timestamp of the last successful backup.

        Returns:
            Datetime of last backup, or None if no backups exist
        """
        metadata = self._loadMetadata()
        lastBackupStr = metadata.get('lastBackupTime')

        if not lastBackupStr:
            return None

        try:
            return datetime.fromisoformat(lastBackupStr)
        except (ValueError, TypeError):
            return None

    def getBackupHistory(self) -> List[Dict[str, Any]]:
        """
        Get the history of all backups.

        Returns:
            List of backup entries with filename, timestamp, size, path
        """
        metadata = self._loadMetadata()
        return metadata.get('backups', [])

    # ================================================================================
    # Catch-up Backup Logic
    # ================================================================================

    def shouldRunCatchupBackup(self) -> bool:
        """
        Determine if a catch-up backup should be run.

        A catch-up backup is needed if the time since the last backup
        exceeds the configured catchupDays threshold.

        Returns:
            True if catch-up backup should be run
        """
        lastBackupTime = self.getLastBackupTime()

        if lastBackupTime is None:
            # No backups ever - definitely need one
            logger.debug("No previous backup found, catch-up backup needed")
            return True

        catchupThreshold = timedelta(days=self._config.catchupDays)
        timeSinceLastBackup = datetime.now() - lastBackupTime

        needsCatchup = timeSinceLastBackup > catchupThreshold

        if needsCatchup:
            logger.debug(
                f"Catch-up backup needed: {timeSinceLastBackup.days} days "
                f"since last backup (threshold: {self._config.catchupDays} days)"
            )

        return needsCatchup

    def getDaysSinceLastBackup(self) -> Optional[int]:
        """
        Get the number of days since the last backup.

        Returns:
            Number of days since last backup, or None if no backups
        """
        lastBackupTime = self.getLastBackupTime()

        if lastBackupTime is None:
            return None

        delta = datetime.now() - lastBackupTime
        return delta.days

    # ================================================================================
    # Cleanup Operations
    # ================================================================================

    def cleanupOldBackups(self, maxBackups: Optional[int] = None) -> int:
        """
        Remove old backups exceeding the maximum retention count.

        Removes the oldest backups first until the backup count is
        within the configured maximum.

        Args:
            maxBackups: Maximum backups to keep (uses config if not specified)

        Returns:
            Number of backups removed
        """
        maxToKeep = maxBackups if maxBackups is not None else self._config.maxBackups

        metadata = self._loadMetadata()
        backups = metadata.get('backups', [])

        if len(backups) <= maxToKeep:
            logger.debug(f"No cleanup needed: {len(backups)} backups <= {maxToKeep}")
            return 0

        # Sort by timestamp (oldest first)
        backups.sort(key=lambda b: b.get('timestamp', ''))

        # Calculate how many to remove
        numToRemove = len(backups) - maxToKeep
        toRemove = backups[:numToRemove]
        toKeep = backups[numToRemove:]

        removedCount = 0

        for backup in toRemove:
            backupPath = Path(backup.get('path', ''))

            if backupPath.exists():
                try:
                    backupPath.unlink()
                    removedCount += 1
                    logger.info(f"Removed old backup: {backupPath.name}")
                except OSError as e:
                    logger.warning(f"Failed to remove backup {backupPath}: {e}")
            else:
                # File already gone, still count as removed from metadata
                removedCount += 1
                logger.debug(f"Backup file already removed: {backupPath}")

        # Update metadata with remaining backups
        metadata['backups'] = toKeep
        self._saveMetadata(metadata)

        logger.info(f"Cleanup complete: removed {removedCount} old backups")
        return removedCount

    def getBackupCount(self) -> int:
        """
        Get the current number of backups.

        Returns:
            Number of backup entries in metadata
        """
        metadata = self._loadMetadata()
        return len(metadata.get('backups', []))

    def getBackupFiles(self) -> List[Path]:
        """
        Get list of actual backup files in the data directory.

        Returns:
            List of paths to backup files
        """
        if not self._dataDir.exists():
            return []

        pattern = f'obd_backup_*{BACKUP_FILE_EXTENSION}'
        return sorted(self._dataDir.glob(pattern))

    # ================================================================================
    # Status
    # ================================================================================

    def getStatus(self) -> BackupStatus:
        """
        Get the current backup status.

        Returns:
            Current BackupStatus
        """
        return self._status

    def getLastResult(self) -> Optional[BackupResult]:
        """
        Get the result of the last backup operation.

        Returns:
            Last BackupResult, or None if no backup has been performed
        """
        return self._lastResult

    def isEnabled(self) -> bool:
        """
        Check if backup is enabled in configuration.

        Returns:
            True if backup is enabled
        """
        return self._config.enabled
