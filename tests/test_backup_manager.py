################################################################################
# File Name: test_backup_manager.py
# Purpose/Description: Tests for BackupManager class
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
Tests for the BackupManager class.

Run with:
    pytest tests/test_backup_manager.py -v
"""

import gzip
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from backup.backup_manager import BackupManager
from backup.types import (
    BackupConfig,
    BackupStatus,
    BackupResult,
    BACKUP_METADATA_FILENAME,
)
from backup.exceptions import BackupOperationError


# ================================================================================
# Test Fixtures
# ================================================================================

@pytest.fixture
def tempDataDir() -> Generator[Path, None, None]:
    """
    Create a temporary data directory for testing.

    Yields:
        Path to temporary directory
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sampleDatabase(tempDataDir: Path) -> Path:
    """
    Create a sample database file for testing.

    Args:
        tempDataDir: Temporary directory path

    Returns:
        Path to the sample database file
    """
    dbPath = tempDataDir / 'obd.db'
    # Create a simple SQLite-like file with some content
    dbPath.write_text('Test database content for backup testing')
    return dbPath


@pytest.fixture
def backupConfig() -> BackupConfig:
    """
    Create a sample backup configuration.

    Returns:
        BackupConfig with test settings
    """
    return BackupConfig(
        enabled=True,
        provider='google_drive',
        folderPath='Test_Backups',
        scheduleTime='03:00',
        maxBackups=5,
        compressBackups=True,
        catchupDays=2,
    )


@pytest.fixture
def backupManager(
    backupConfig: BackupConfig,
    tempDataDir: Path,
    sampleDatabase: Path
) -> BackupManager:
    """
    Create a BackupManager instance for testing.

    Args:
        backupConfig: Test backup configuration
        tempDataDir: Temporary directory path
        sampleDatabase: Path to sample database

    Returns:
        Configured BackupManager instance
    """
    return BackupManager(
        config=backupConfig,
        dataDir=str(tempDataDir),
        databaseFilename='obd.db'
    )


# ================================================================================
# Initialization Tests
# ================================================================================

class TestBackupManagerInit:
    """Tests for BackupManager initialization."""

    def test_init_withConfig_setsConfig(self, backupConfig: BackupConfig):
        """
        Given: BackupConfig instance
        When: BackupManager is initialized
        Then: Config is stored correctly
        """
        manager = BackupManager(config=backupConfig)

        assert manager.getConfig() == backupConfig
        assert manager.getConfig().maxBackups == 5

    def test_init_withoutConfig_usesDefaults(self):
        """
        Given: No config provided
        When: BackupManager is initialized
        Then: Uses default BackupConfig
        """
        manager = BackupManager()

        assert manager.getConfig() is not None
        assert manager.getConfig().enabled is False

    def test_init_withDataDir_setsDataDir(self, tempDataDir: Path):
        """
        Given: Custom data directory
        When: BackupManager is initialized
        Then: Data directory is set correctly
        """
        manager = BackupManager(dataDir=str(tempDataDir))

        # Verify by checking internal state
        assert manager._dataDir == tempDataDir

    def test_init_defaultStatus_isPending(self, backupManager: BackupManager):
        """
        Given: New BackupManager
        When: Status is checked
        Then: Status is PENDING
        """
        assert backupManager.getStatus() == BackupStatus.PENDING


# ================================================================================
# Perform Backup Tests
# ================================================================================

class TestPerformBackup:
    """Tests for performBackup() method."""

    def test_performBackup_validDatabase_createsBackupFile(
        self,
        backupManager: BackupManager,
        tempDataDir: Path
    ):
        """
        Given: Valid database file exists
        When: performBackup() is called
        Then: Compressed backup file is created
        """
        result = backupManager.performBackup()

        assert result.success is True
        assert result.backupPath is not None
        assert Path(result.backupPath).exists()
        assert result.backupPath.endswith('.db.gz')

    def test_performBackup_compressesContent(
        self,
        backupManager: BackupManager,
        tempDataDir: Path,
        sampleDatabase: Path
    ):
        """
        Given: Valid database file
        When: performBackup() is called with compression enabled
        Then: Backup is smaller than original (or similar for small files)
        """
        result = backupManager.performBackup()

        backupPath = Path(result.backupPath)
        assert backupPath.exists()

        # Verify it's gzip compressed by reading it
        with gzip.open(backupPath, 'rb') as f:
            content = f.read().decode()
            assert 'Test database content' in content

    def test_performBackup_setsCompletedStatus(
        self,
        backupManager: BackupManager
    ):
        """
        Given: BackupManager
        When: performBackup() succeeds
        Then: Status is COMPLETED
        """
        backupManager.performBackup()

        assert backupManager.getStatus() == BackupStatus.COMPLETED

    def test_performBackup_missingDatabase_returnsFailed(
        self,
        backupConfig: BackupConfig,
        tempDataDir: Path
    ):
        """
        Given: Database file does not exist
        When: performBackup() is called
        Then: Returns failed result with error
        """
        manager = BackupManager(
            config=backupConfig,
            dataDir=str(tempDataDir),
            databaseFilename='nonexistent.db'
        )

        result = manager.performBackup()

        assert result.success is False
        assert result.error is not None
        assert 'not found' in result.error.lower()
        assert manager.getStatus() == BackupStatus.FAILED

    def test_performBackup_storesLastResult(
        self,
        backupManager: BackupManager
    ):
        """
        Given: BackupManager
        When: performBackup() is called
        Then: Last result is stored and accessible
        """
        result = backupManager.performBackup()
        lastResult = backupManager.getLastResult()

        assert lastResult is not None
        assert lastResult.success == result.success
        assert lastResult.timestamp == result.timestamp

    def test_performBackup_withoutCompression_copiesFile(
        self,
        tempDataDir: Path,
        sampleDatabase: Path
    ):
        """
        Given: Compression disabled in config
        When: performBackup() is called
        Then: File is copied without compression
        """
        config = BackupConfig(enabled=True, compressBackups=False)
        manager = BackupManager(
            config=config,
            dataDir=str(tempDataDir),
            databaseFilename='obd.db'
        )

        result = manager.performBackup()

        assert result.success is True
        # File extension still has .gz but content is not compressed
        backupPath = Path(result.backupPath)
        assert backupPath.exists()

    def test_performBackup_recordsTimestamp(
        self,
        backupManager: BackupManager
    ):
        """
        Given: BackupManager
        When: performBackup() is called
        Then: Result has valid timestamp
        """
        beforeBackup = datetime.now()
        result = backupManager.performBackup()
        afterBackup = datetime.now()

        assert result.timestamp >= beforeBackup
        assert result.timestamp <= afterBackup

    def test_performBackup_recordsSize(
        self,
        backupManager: BackupManager
    ):
        """
        Given: BackupManager
        When: performBackup() is called
        Then: Result has size > 0
        """
        result = backupManager.performBackup()

        assert result.size is not None
        assert result.size > 0


# ================================================================================
# Metadata Tests
# ================================================================================

class TestMetadata:
    """Tests for backup metadata operations."""

    def test_getLastBackupTime_noBackups_returnsNone(
        self,
        backupManager: BackupManager
    ):
        """
        Given: No backups have been performed
        When: getLastBackupTime() is called
        Then: Returns None
        """
        result = backupManager.getLastBackupTime()

        assert result is None

    def test_getLastBackupTime_afterBackup_returnsTime(
        self,
        backupManager: BackupManager
    ):
        """
        Given: Backup has been performed
        When: getLastBackupTime() is called
        Then: Returns the backup timestamp
        """
        backupManager.performBackup()

        result = backupManager.getLastBackupTime()

        assert result is not None
        assert isinstance(result, datetime)

    def test_performBackup_createsMetadataFile(
        self,
        backupManager: BackupManager,
        tempDataDir: Path
    ):
        """
        Given: BackupManager
        When: performBackup() is called
        Then: Metadata file is created
        """
        backupManager.performBackup()

        metadataPath = tempDataDir / BACKUP_METADATA_FILENAME
        assert metadataPath.exists()

    def test_metadata_containsBackupInfo(
        self,
        backupManager: BackupManager,
        tempDataDir: Path
    ):
        """
        Given: Backup performed
        When: Metadata file is read
        Then: Contains backup filename, timestamp, size, path
        """
        backupManager.performBackup()

        metadataPath = tempDataDir / BACKUP_METADATA_FILENAME
        with open(metadataPath, 'r') as f:
            metadata = json.load(f)

        assert 'backups' in metadata
        assert len(metadata['backups']) == 1

        backup = metadata['backups'][0]
        assert 'filename' in backup
        assert 'timestamp' in backup
        assert 'size' in backup
        assert 'path' in backup

    def test_getBackupHistory_returnsBackupList(
        self,
        backupManager: BackupManager
    ):
        """
        Given: Multiple backups performed
        When: getBackupHistory() is called
        Then: Returns list of all backups
        """
        backupManager.performBackup()
        backupManager.performBackup()

        history = backupManager.getBackupHistory()

        assert len(history) == 2

    def test_getBackupCount_returnsCorrectCount(
        self,
        backupManager: BackupManager
    ):
        """
        Given: Multiple backups performed
        When: getBackupCount() is called
        Then: Returns correct count
        """
        assert backupManager.getBackupCount() == 0

        backupManager.performBackup()
        assert backupManager.getBackupCount() == 1

        backupManager.performBackup()
        assert backupManager.getBackupCount() == 2


# ================================================================================
# Catch-up Backup Tests
# ================================================================================

class TestCatchupBackup:
    """Tests for catch-up backup logic."""

    def test_shouldRunCatchupBackup_noBackups_returnsTrue(
        self,
        backupManager: BackupManager
    ):
        """
        Given: No previous backups
        When: shouldRunCatchupBackup() is called
        Then: Returns True
        """
        result = backupManager.shouldRunCatchupBackup()

        assert result is True

    def test_shouldRunCatchupBackup_recentBackup_returnsFalse(
        self,
        backupManager: BackupManager
    ):
        """
        Given: Backup performed recently (within catchupDays)
        When: shouldRunCatchupBackup() is called
        Then: Returns False
        """
        backupManager.performBackup()

        result = backupManager.shouldRunCatchupBackup()

        assert result is False

    def test_shouldRunCatchupBackup_oldBackup_returnsTrue(
        self,
        backupManager: BackupManager,
        tempDataDir: Path
    ):
        """
        Given: Last backup was more than catchupDays ago
        When: shouldRunCatchupBackup() is called
        Then: Returns True
        """
        # Create fake old metadata
        oldTime = datetime.now() - timedelta(days=5)
        metadata = {
            'backups': [{
                'filename': 'old_backup.db.gz',
                'timestamp': oldTime.isoformat(),
                'size': 1000,
                'path': str(tempDataDir / 'old_backup.db.gz')
            }],
            'lastBackupTime': oldTime.isoformat()
        }

        metadataPath = tempDataDir / BACKUP_METADATA_FILENAME
        with open(metadataPath, 'w') as f:
            json.dump(metadata, f)

        result = backupManager.shouldRunCatchupBackup()

        assert result is True

    def test_getDaysSinceLastBackup_noBackups_returnsNone(
        self,
        backupManager: BackupManager
    ):
        """
        Given: No previous backups
        When: getDaysSinceLastBackup() is called
        Then: Returns None
        """
        result = backupManager.getDaysSinceLastBackup()

        assert result is None

    def test_getDaysSinceLastBackup_recentBackup_returnsZero(
        self,
        backupManager: BackupManager
    ):
        """
        Given: Backup performed today
        When: getDaysSinceLastBackup() is called
        Then: Returns 0
        """
        backupManager.performBackup()

        result = backupManager.getDaysSinceLastBackup()

        assert result == 0


# ================================================================================
# Cleanup Tests
# ================================================================================

class TestCleanupOldBackups:
    """Tests for cleanupOldBackups() method."""

    def test_cleanupOldBackups_withinLimit_removesNone(
        self,
        backupManager: BackupManager
    ):
        """
        Given: Backup count within maxBackups limit
        When: cleanupOldBackups() is called
        Then: No backups are removed
        """
        backupManager.performBackup()
        backupManager.performBackup()

        removed = backupManager.cleanupOldBackups()

        assert removed == 0
        assert backupManager.getBackupCount() == 2

    def test_cleanupOldBackups_exceedsLimit_removesOldest(
        self,
        tempDataDir: Path,
        sampleDatabase: Path
    ):
        """
        Given: More backups than maxBackups
        When: cleanupOldBackups() is called
        Then: Oldest backups are removed
        """
        config = BackupConfig(enabled=True, maxBackups=2)
        manager = BackupManager(
            config=config,
            dataDir=str(tempDataDir),
            databaseFilename='obd.db'
        )

        # Create 4 backups
        manager.performBackup()
        manager.performBackup()
        manager.performBackup()
        manager.performBackup()

        assert manager.getBackupCount() == 4

        removed = manager.cleanupOldBackups()

        assert removed == 2
        assert manager.getBackupCount() == 2

    def test_cleanupOldBackups_customMaxBackups_usesParameter(
        self,
        backupManager: BackupManager
    ):
        """
        Given: Multiple backups
        When: cleanupOldBackups(maxBackups=1) is called
        Then: Uses parameter value instead of config
        """
        backupManager.performBackup()
        backupManager.performBackup()
        backupManager.performBackup()

        removed = backupManager.cleanupOldBackups(maxBackups=1)

        assert removed == 2
        assert backupManager.getBackupCount() == 1

    def test_cleanupOldBackups_deletesFiles(
        self,
        tempDataDir: Path,
        sampleDatabase: Path
    ):
        """
        Given: Multiple backups with files
        When: cleanupOldBackups() is called
        Then: Actual files are deleted
        """
        config = BackupConfig(enabled=True, maxBackups=1)
        manager = BackupManager(
            config=config,
            dataDir=str(tempDataDir),
            databaseFilename='obd.db'
        )

        manager.performBackup()
        manager.performBackup()

        # Get backup files before cleanup
        backupFiles = manager.getBackupFiles()
        assert len(backupFiles) == 2

        manager.cleanupOldBackups()

        # Verify files were deleted
        remainingFiles = manager.getBackupFiles()
        assert len(remainingFiles) == 1

    def test_cleanupOldBackups_handlesAlreadyDeletedFiles(
        self,
        backupManager: BackupManager,
        tempDataDir: Path
    ):
        """
        Given: Metadata references files that no longer exist
        When: cleanupOldBackups() is called
        Then: Continues without error and updates metadata
        """
        # Create some backups
        backupManager.performBackup()
        backupManager.performBackup()
        backupManager.performBackup()

        # Manually delete a backup file
        backupFiles = backupManager.getBackupFiles()
        if backupFiles:
            backupFiles[0].unlink()

        # Should not raise error
        removed = backupManager.cleanupOldBackups(maxBackups=1)

        assert removed >= 1


# ================================================================================
# Configuration Tests
# ================================================================================

class TestConfiguration:
    """Tests for configuration methods."""

    def test_setConfig_updatesConfig(self, backupManager: BackupManager):
        """
        Given: BackupManager with config
        When: setConfig() is called with new config
        Then: Config is updated
        """
        newConfig = BackupConfig(enabled=False, maxBackups=10)
        backupManager.setConfig(newConfig)

        assert backupManager.getConfig().maxBackups == 10
        assert backupManager.getConfig().enabled is False

    def test_setDataDir_updatesPath(self, backupManager: BackupManager):
        """
        Given: BackupManager
        When: setDataDir() is called
        Then: Data directory is updated
        """
        backupManager.setDataDir('/new/path')

        assert backupManager._dataDir == Path('/new/path')

    def test_isEnabled_reflectsConfig(self, backupManager: BackupManager):
        """
        Given: Config with enabled=True
        When: isEnabled() is called
        Then: Returns True
        """
        assert backupManager.isEnabled() is True

        backupManager.setConfig(BackupConfig(enabled=False))
        assert backupManager.isEnabled() is False


# ================================================================================
# Status Tests
# ================================================================================

class TestStatus:
    """Tests for status methods."""

    def test_getStatus_afterFailure_returnsFailed(
        self,
        backupConfig: BackupConfig,
        tempDataDir: Path
    ):
        """
        Given: Backup fails
        When: getStatus() is called
        Then: Returns FAILED
        """
        manager = BackupManager(
            config=backupConfig,
            dataDir=str(tempDataDir),
            databaseFilename='nonexistent.db'
        )

        manager.performBackup()

        assert manager.getStatus() == BackupStatus.FAILED

    def test_getLastResult_noBackup_returnsNone(
        self,
        backupManager: BackupManager
    ):
        """
        Given: No backup performed
        When: getLastResult() is called
        Then: Returns None
        """
        assert backupManager.getLastResult() is None


# ================================================================================
# File Operations Tests
# ================================================================================

class TestFileOperations:
    """Tests for file-related operations."""

    def test_getBackupFiles_noBackups_returnsEmptyList(
        self,
        backupManager: BackupManager
    ):
        """
        Given: No backups created
        When: getBackupFiles() is called
        Then: Returns empty list
        """
        result = backupManager.getBackupFiles()

        assert result == []

    def test_getBackupFiles_withBackups_returnsFiles(
        self,
        backupManager: BackupManager
    ):
        """
        Given: Backups have been created
        When: getBackupFiles() is called
        Then: Returns list of backup file paths
        """
        backupManager.performBackup()
        backupManager.performBackup()

        result = backupManager.getBackupFiles()

        assert len(result) == 2
        for path in result:
            assert path.name.startswith('obd_backup_')
            assert path.name.endswith('.db.gz')

    def test_getBackupFiles_nonexistentDir_returnsEmptyList(self):
        """
        Given: Data directory doesn't exist
        When: getBackupFiles() is called
        Then: Returns empty list
        """
        manager = BackupManager(dataDir='/nonexistent/path')

        result = manager.getBackupFiles()

        assert result == []


# ================================================================================
# Edge Cases
# ================================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_multipleBackups_uniqueFilenames(
        self,
        backupManager: BackupManager
    ):
        """
        Given: Multiple backups created in quick succession
        When: Filenames are checked
        Then: Each has unique filename based on timestamp
        """
        result1 = backupManager.performBackup()
        result2 = backupManager.performBackup()

        # Filenames should be different (different timestamps)
        assert result1.backupPath != result2.backupPath

    def test_corruptedMetadata_handlesGracefully(
        self,
        backupManager: BackupManager,
        tempDataDir: Path
    ):
        """
        Given: Corrupted metadata file
        When: Operations are performed
        Then: Handles gracefully without crash
        """
        # Create corrupted metadata
        metadataPath = tempDataDir / BACKUP_METADATA_FILENAME
        metadataPath.write_text('not valid json {{{')

        # Should not crash
        lastTime = backupManager.getLastBackupTime()
        assert lastTime is None

        history = backupManager.getBackupHistory()
        assert history == []

        # Backup should still work
        result = backupManager.performBackup()
        assert result.success is True

    def test_metadataWithInvalidTimestamp_handlesGracefully(
        self,
        backupManager: BackupManager,
        tempDataDir: Path
    ):
        """
        Given: Metadata with invalid timestamp format
        When: getLastBackupTime() is called
        Then: Returns None without crash
        """
        metadata = {
            'backups': [],
            'lastBackupTime': 'not-a-valid-timestamp'
        }

        metadataPath = tempDataDir / BACKUP_METADATA_FILENAME
        with open(metadataPath, 'w') as f:
            json.dump(metadata, f)

        result = backupManager.getLastBackupTime()

        assert result is None
