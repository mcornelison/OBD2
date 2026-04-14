################################################################################
# File Name: backup_coordinator.py
# Purpose/Description: Backup lifecycle, scheduling, and execution mixin for
#                      the orchestrator
# Author: Ralph Agent
# Creation Date: 2026-04-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-14    | Ralph Agent  | Sweep 5 Task 2: extracted from orchestrator.py
#               |              | (BACKUP_AVAILABLE fallback preserved)
# ================================================================================
################################################################################

"""
Backup coordination mixin for ApplicationOrchestrator.

Owns backup initialization, catch-up check, schedule setup, backup execution,
cleanup, and shutdown. Uses a graceful fallback when the backup module is
unavailable so non-Pi systems can still import the orchestrator.
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

# Import backup module with graceful fallback for optional dependency
try:
    from pi.backup import (
        BackupConfig,
        BackupManager,
        BackupStatus,
        GoogleDriveUploader,
    )
    BACKUP_AVAILABLE = True
except ImportError:
    BACKUP_AVAILABLE = False
    BackupManager = None  # type: ignore
    BackupConfig = None  # type: ignore
    BackupStatus = None  # type: ignore
    GoogleDriveUploader = None  # type: ignore

# Unified logger name matches the original monolith module so existing tests
# that filter caplog by logger name continue to work unchanged.
logger = logging.getLogger("pi.obd.orchestrator")


class BackupCoordinatorMixin:
    """
    Mixin providing backup lifecycle and execution.

    Assumes the composing class has:
        _config: dict
        _running: bool
        _backupManager, _googleDriveUploader: Any | None
        _backupScheduleTimer: threading.Timer | None
    """

    _config: dict[str, Any]
    _running: bool
    _backupManager: Any | None
    _googleDriveUploader: Any | None
    _backupScheduleTimer: threading.Timer | None

    def _getBackupStatus(self) -> dict[str, Any]:
        """
        Get detailed backup status information.

        Returns:
            Dictionary with backup status details including:
            - enabled: Whether backup is enabled
            - status: Current backup status (pending, in_progress, completed, failed)
            - lastBackupTime: ISO timestamp of last backup
            - daysSinceLastBackup: Days since last backup (None if never)
            - backupCount: Total number of backups stored
            - uploaderAvailable: Whether Google Drive upload is available
            - nextScheduledBackup: Estimated time of next scheduled backup
        """
        if self._backupManager is None:
            return {'enabled': False}

        status: dict[str, Any] = {
            'enabled': self._backupManager.isEnabled(),
            'status': self._backupManager.getStatus().value,
            'lastBackupTime': None,
            'daysSinceLastBackup': self._backupManager.getDaysSinceLastBackup(),
            'backupCount': self._backupManager.getBackupCount(),
            'uploaderAvailable': False,
        }

        # Get last backup time
        lastBackupTime = self._backupManager.getLastBackupTime()
        if lastBackupTime is not None:
            status['lastBackupTime'] = lastBackupTime.isoformat()

        # Check uploader availability
        if self._googleDriveUploader is not None:
            try:
                status['uploaderAvailable'] = self._googleDriveUploader.isAvailable()
            except Exception:
                status['uploaderAvailable'] = False

        return status

    def _initializeBackupManager(self) -> None:
        """
        Initialize the backup manager component if enabled.

        Only initializes if backup.enabled is true in config and the
        backup module is available. Also performs catch-up backup check
        on startup and schedules daily backups.
        """
        if not BACKUP_AVAILABLE:
            logger.debug("Backup module not available, skipping")
            return

        # Check if backup is enabled in config
        backupConfig = self._config.get('backup', {})
        if not backupConfig.get('enabled', False):
            logger.debug("Backup is disabled in config, skipping initialization")
            return

        logger.info("Starting backupManager...")
        try:
            # Create BackupConfig from config dict
            config = BackupConfig.fromDict(backupConfig)

            # Determine data directory - use database path if available
            dataDir = 'data'
            dbConfig = self._config.get('pi', {}).get('database', {})
            if 'path' in dbConfig:
                import os
                dataDir = os.path.dirname(dbConfig['path']) or 'data'

            # Create backup manager
            self._backupManager = BackupManager(config=config, dataDir=dataDir)

            # Create Google Drive uploader if provider is google_drive
            if config.provider == 'google_drive':
                self._googleDriveUploader = GoogleDriveUploader()
                if self._googleDriveUploader.isAvailable():
                    logger.info("Google Drive uploader available")
                else:
                    logger.warning(
                        "Google Drive uploader not available "
                        "(rclone not installed or not configured)"
                    )

            logger.info("BackupManager started successfully")

            # Perform catch-up backup check on startup
            self._performCatchupBackupCheck()

            # Schedule daily backups at configured time
            self._scheduleNextBackup()

        except Exception as e:
            logger.error(f"Failed to initialize backupManager: {e}")
            # Backup failure is non-critical - log warning but don't raise
            logger.warning("Backup system unavailable, continuing without backup")
            self._backupManager = None
            self._googleDriveUploader = None

    def _performCatchupBackupCheck(self) -> None:
        """
        Check if a catch-up backup should be run on startup.

        A catch-up backup is needed if more than catchupDays have passed
        since the last backup (or if no backup has ever been performed).
        """
        if self._backupManager is None:
            return

        if not self._backupManager.isEnabled():
            return

        try:
            if self._backupManager.shouldRunCatchupBackup():
                daysSinceBackup = self._backupManager.getDaysSinceLastBackup()
                if daysSinceBackup is None:
                    logger.info("No previous backup found, running catch-up backup")
                else:
                    logger.info(
                        f"Running catch-up backup: {daysSinceBackup} days since last backup"
                    )

                # Perform the catch-up backup
                self._performBackup()
            else:
                logger.debug("No catch-up backup needed")
        except Exception as e:
            logger.warning(f"Catch-up backup check failed: {e}")

    def _performBackup(self) -> bool:
        """
        Perform a backup operation, including optional upload to Google Drive.

        Returns:
            True if backup (and optional upload) succeeded, False otherwise
        """
        if self._backupManager is None:
            return False

        try:
            # Perform local backup
            result = self._backupManager.performBackup()

            if not result.success:
                logger.error(f"Backup failed: {result.error}")
                return False

            logger.info(
                f"Backup completed: {result.backupPath} "
                f"({result.size / 1024:.1f} KB)"
            )

            # Upload to Google Drive if available
            if (
                self._googleDriveUploader is not None
                and self._googleDriveUploader.isAvailable()
            ):
                try:
                    config = self._backupManager.getConfig()
                    remotePath = f"{config.folderPath}/{result.backupPath.split('/')[-1]}"
                    uploadResult = self._googleDriveUploader.upload(
                        result.backupPath,
                        remotePath
                    )
                    if uploadResult.success:
                        logger.info(f"Backup uploaded to Google Drive: {remotePath}")
                    else:
                        logger.warning(
                            f"Google Drive upload failed: {uploadResult.error}"
                        )
                except Exception as e:
                    logger.warning(f"Google Drive upload error: {e}")

            # Clean up old backups
            self._backupManager.cleanupOldBackups()

            return True

        except Exception as e:
            logger.error(f"Backup operation failed: {e}")
            return False

    def _scheduleNextBackup(self) -> None:
        """
        Schedule the next daily backup at the configured time.

        Parses scheduleTime (HH:MM format) and schedules a timer
        to run the backup at that time tomorrow (or today if not yet passed).
        """
        if self._backupManager is None:
            return

        if not self._backupManager.isEnabled():
            return

        try:
            config = self._backupManager.getConfig()
            scheduleTime = config.scheduleTime  # e.g., "03:00"

            # Parse schedule time
            hour, minute = map(int, scheduleTime.split(':'))

            # Calculate next backup time
            now = datetime.now()
            scheduleDate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If the time has passed today, schedule for tomorrow
            if scheduleDate <= now:
                scheduleDate = scheduleDate + timedelta(days=1)

            # Calculate seconds until next backup
            secondsUntilBackup = (scheduleDate - now).total_seconds()

            # Cancel existing timer if any
            if self._backupScheduleTimer is not None:
                self._backupScheduleTimer.cancel()

            # Create new timer
            self._backupScheduleTimer = threading.Timer(
                secondsUntilBackup,
                self._runScheduledBackup
            )
            self._backupScheduleTimer.daemon = True
            self._backupScheduleTimer.start()

            logger.info(
                f"Next backup scheduled at {scheduleDate.strftime('%Y-%m-%d %H:%M')}"
            )

        except ValueError as e:
            logger.error(f"Invalid backup schedule time format: {e}")
        except Exception as e:
            logger.warning(f"Failed to schedule backup: {e}")

    def _runScheduledBackup(self) -> None:
        """
        Run a scheduled backup and reschedule the next one.

        Called by the backup schedule timer. Performs the backup,
        then schedules the next backup for tomorrow.
        """
        if not self._running:
            return

        logger.info("Running scheduled daily backup")

        try:
            self._performBackup()
        except Exception as e:
            logger.error(f"Scheduled backup failed: {e}")
        finally:
            # Schedule next backup for tomorrow
            self._scheduleNextBackup()

    def _shutdownBackupManager(self) -> None:
        """
        Shutdown the backup manager component.

        Cancels any pending backup schedule timer and clears references.
        """
        # Cancel scheduled backup timer
        if self._backupScheduleTimer is not None:
            try:
                self._backupScheduleTimer.cancel()
                logger.debug("Cancelled scheduled backup timer")
            except Exception as e:
                logger.debug(f"Error cancelling backup timer: {e}")
            finally:
                self._backupScheduleTimer = None

        # Clear backup manager and uploader references
        if self._backupManager is not None:
            logger.info("Stopping backupManager...")
            logger.info("BackupManager stopped successfully")
            self._backupManager = None

        self._googleDriveUploader = None


__all__ = ['BackupCoordinatorMixin', 'BACKUP_AVAILABLE']
