################################################################################
# File Name: test_google_drive_uploader.py
# Purpose/Description: Tests for GoogleDriveUploader class
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial implementation for US-TD-011
# ================================================================================
################################################################################

"""
Tests for the GoogleDriveUploader class.

Run with:
    pytest tests/test_google_drive_uploader.py -v
"""

import sys
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from backup.google_drive import (
    GoogleDriveUploader,
    UploadResult,
    DEFAULT_REMOTE_NAME,
    RCLONE_CHECK_TIMEOUT,
    RCLONE_UPLOAD_TIMEOUT,
)


# ================================================================================
# Test Fixtures
# ================================================================================

@pytest.fixture
def tempFile() -> Generator[Path, None, None]:
    """
    Create a temporary file for upload testing.

    Yields:
        Path to temporary file
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix='.gz') as f:
        f.write(b'Test backup content for upload testing')
        tempPath = Path(f.name)

    yield tempPath

    # Cleanup
    if tempPath.exists():
        tempPath.unlink()


@pytest.fixture
def uploader() -> GoogleDriveUploader:
    """
    Create a GoogleDriveUploader instance for testing.

    Returns:
        GoogleDriveUploader with default settings
    """
    return GoogleDriveUploader(remoteName='gdrive')


# ================================================================================
# UploadResult Tests
# ================================================================================

class TestUploadResult:
    """Tests for the UploadResult dataclass."""

    def test_createSuccess(self):
        """
        Given: Success parameters
        When: Creating an UploadResult for success
        Then: Result should have correct values
        """
        result = UploadResult(
            success=True,
            remotePath='gdrive:OBD2_Backups/backup.gz',
            bytesTransferred=1024
        )

        assert result.success is True
        assert result.remotePath == 'gdrive:OBD2_Backups/backup.gz'
        assert result.bytesTransferred == 1024
        assert result.error is None

    def test_createFailure(self):
        """
        Given: Failure parameters
        When: Creating an UploadResult for failure
        Then: Result should have correct values
        """
        result = UploadResult(
            success=False,
            error='Upload failed: network error'
        )

        assert result.success is False
        assert result.error == 'Upload failed: network error'
        assert result.remotePath is None
        assert result.bytesTransferred is None


# ================================================================================
# Initialization Tests
# ================================================================================

class TestGoogleDriveUploaderInit:
    """Tests for GoogleDriveUploader initialization."""

    def test_defaultRemoteName(self):
        """
        Given: No remote name specified
        When: Creating an uploader
        Then: Default remote name should be used
        """
        uploader = GoogleDriveUploader()

        assert uploader.getRemoteName() == DEFAULT_REMOTE_NAME

    def test_customRemoteName(self):
        """
        Given: Custom remote name
        When: Creating an uploader
        Then: Custom remote name should be used
        """
        uploader = GoogleDriveUploader(remoteName='my_drive')

        assert uploader.getRemoteName() == 'my_drive'

    def test_defaultUploadTimeout(self):
        """
        Given: No timeout specified
        When: Creating an uploader
        Then: Default timeout should be used
        """
        uploader = GoogleDriveUploader()

        assert uploader.getUploadTimeout() == RCLONE_UPLOAD_TIMEOUT

    def test_customUploadTimeout(self):
        """
        Given: Custom timeout
        When: Creating an uploader
        Then: Custom timeout should be used
        """
        uploader = GoogleDriveUploader(uploadTimeout=300)

        assert uploader.getUploadTimeout() == 300


# ================================================================================
# rclone Installation Check Tests
# ================================================================================

class TestIsRcloneInstalled:
    """Tests for rclone installation detection."""

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_rcloneInstalled_success(self, mockRun, mockWhich):
        """
        Given: rclone is installed
        When: Checking if rclone is installed
        Then: Should return True
        """
        mockWhich.return_value = '/usr/bin/rclone'
        mockRun.return_value = MagicMock(
            returncode=0,
            stdout='rclone v1.60.0\n- os/type: linux\n'
        )

        uploader = GoogleDriveUploader()
        result = uploader.isRcloneInstalled()

        assert result is True
        mockWhich.assert_called_once_with('rclone')
        mockRun.assert_called_once()

    @patch('backup.google_drive.shutil.which')
    def test_rcloneNotInPath(self, mockWhich):
        """
        Given: rclone is not in PATH
        When: Checking if rclone is installed
        Then: Should return False
        """
        mockWhich.return_value = None

        uploader = GoogleDriveUploader()
        result = uploader.isRcloneInstalled()

        assert result is False

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_rcloneVersionFails(self, mockRun, mockWhich):
        """
        Given: rclone version command fails
        When: Checking if rclone is installed
        Then: Should return False
        """
        mockWhich.return_value = '/usr/bin/rclone'
        mockRun.return_value = MagicMock(
            returncode=1,
            stderr='Command not found'
        )

        uploader = GoogleDriveUploader()
        result = uploader.isRcloneInstalled()

        assert result is False

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_rcloneVersionTimeout(self, mockRun, mockWhich):
        """
        Given: rclone version command times out
        When: Checking if rclone is installed
        Then: Should return False
        """
        import subprocess
        mockWhich.return_value = '/usr/bin/rclone'
        mockRun.side_effect = subprocess.TimeoutExpired('rclone', RCLONE_CHECK_TIMEOUT)

        uploader = GoogleDriveUploader()
        result = uploader.isRcloneInstalled()

        assert result is False

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_rcloneInstalled_cached(self, mockRun, mockWhich):
        """
        Given: rclone installation already checked
        When: Checking again
        Then: Should use cached result
        """
        mockWhich.return_value = '/usr/bin/rclone'
        mockRun.return_value = MagicMock(returncode=0, stdout='rclone v1.60.0\n')

        uploader = GoogleDriveUploader()

        # First check
        result1 = uploader.isRcloneInstalled()
        # Second check
        result2 = uploader.isRcloneInstalled()

        assert result1 is True
        assert result2 is True
        # Only called once due to caching
        assert mockRun.call_count == 1


# ================================================================================
# rclone Configuration Check Tests
# ================================================================================

class TestIsRcloneConfigured:
    """Tests for rclone configuration detection."""

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_remoteConfigured(self, mockRun, mockWhich):
        """
        Given: rclone remote is configured
        When: Checking if remote is configured
        Then: Should return True
        """
        mockWhich.return_value = '/usr/bin/rclone'

        # First call for version, second for listremotes
        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=0, stdout='gdrive:\nother_remote:\n')
        ]

        uploader = GoogleDriveUploader(remoteName='gdrive')
        result = uploader.isRcloneConfigured()

        assert result is True

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_remoteNotConfigured(self, mockRun, mockWhich):
        """
        Given: rclone remote is not configured
        When: Checking if remote is configured
        Then: Should return False
        """
        mockWhich.return_value = '/usr/bin/rclone'

        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=0, stdout='other_remote:\nbackup:\n')
        ]

        uploader = GoogleDriveUploader(remoteName='gdrive')
        result = uploader.isRcloneConfigured()

        assert result is False

    @patch('backup.google_drive.shutil.which')
    def test_rcloneNotInstalled_configCheck(self, mockWhich):
        """
        Given: rclone is not installed
        When: Checking if remote is configured
        Then: Should return False
        """
        mockWhich.return_value = None

        uploader = GoogleDriveUploader()
        result = uploader.isRcloneConfigured()

        assert result is False

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_listremotesFails(self, mockRun, mockWhich):
        """
        Given: rclone listremotes command fails
        When: Checking if remote is configured
        Then: Should return False
        """
        mockWhich.return_value = '/usr/bin/rclone'

        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=1, stderr='Error listing remotes')
        ]

        uploader = GoogleDriveUploader()
        result = uploader.isRcloneConfigured()

        assert result is False


# ================================================================================
# isAvailable Tests
# ================================================================================

class TestIsAvailable:
    """Tests for combined availability check."""

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_available(self, mockRun, mockWhich):
        """
        Given: rclone installed and configured
        When: Checking availability
        Then: Should return True
        """
        mockWhich.return_value = '/usr/bin/rclone'

        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=0, stdout='gdrive:\n')
        ]

        uploader = GoogleDriveUploader(remoteName='gdrive')
        result = uploader.isAvailable()

        assert result is True

    @patch('backup.google_drive.shutil.which')
    def test_notAvailable_notInstalled(self, mockWhich):
        """
        Given: rclone not installed
        When: Checking availability
        Then: Should return False
        """
        mockWhich.return_value = None

        uploader = GoogleDriveUploader()
        result = uploader.isAvailable()

        assert result is False

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_notAvailable_notConfigured(self, mockRun, mockWhich):
        """
        Given: rclone installed but remote not configured
        When: Checking availability
        Then: Should return False
        """
        mockWhich.return_value = '/usr/bin/rclone'

        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=0, stdout='other:\n')
        ]

        uploader = GoogleDriveUploader(remoteName='gdrive')
        result = uploader.isAvailable()

        assert result is False


# ================================================================================
# getRemotes Tests
# ================================================================================

class TestGetRemotes:
    """Tests for getting list of configured remotes."""

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_getRemotes_success(self, mockRun, mockWhich):
        """
        Given: rclone has configured remotes
        When: Getting remotes list
        Then: Should return list of remote names
        """
        mockWhich.return_value = '/usr/bin/rclone'

        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=0, stdout='gdrive:\nbackup:\nonedrive:\n')
        ]

        uploader = GoogleDriveUploader()
        remotes = uploader.getRemotes()

        assert remotes == ['gdrive', 'backup', 'onedrive']

    @patch('backup.google_drive.shutil.which')
    def test_getRemotes_notInstalled(self, mockWhich):
        """
        Given: rclone not installed
        When: Getting remotes list
        Then: Should return empty list
        """
        mockWhich.return_value = None

        uploader = GoogleDriveUploader()
        remotes = uploader.getRemotes()

        assert remotes == []


# ================================================================================
# Upload Tests
# ================================================================================

class TestUpload:
    """Tests for file upload functionality."""

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_uploadSuccess(self, mockRun, mockWhich, tempFile):
        """
        Given: rclone available and file exists
        When: Uploading file
        Then: Should return success result
        """
        mockWhich.return_value = '/usr/bin/rclone'

        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=0, stdout='gdrive:\n'),
            MagicMock(returncode=0, stdout='Transferred: 1 KB\n')
        ]

        uploader = GoogleDriveUploader(remoteName='gdrive')
        result = uploader.upload(str(tempFile), 'OBD2_Backups/backup.gz')

        assert result.success is True
        assert result.remotePath == 'gdrive:OBD2_Backups/backup.gz'
        assert result.error is None

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_uploadFailure_rcloneError(self, mockRun, mockWhich, tempFile):
        """
        Given: rclone available but upload fails
        When: Uploading file
        Then: Should return failure result with error message
        """
        mockWhich.return_value = '/usr/bin/rclone'

        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=0, stdout='gdrive:\n'),
            MagicMock(returncode=1, stderr='ERROR: failed to open source: permission denied')
        ]

        uploader = GoogleDriveUploader(remoteName='gdrive')
        result = uploader.upload(str(tempFile), 'OBD2_Backups/backup.gz')

        assert result.success is False
        assert 'permission denied' in result.error.lower()

    def test_uploadFailure_fileNotFound(self, uploader):
        """
        Given: Local file does not exist
        When: Uploading file
        Then: Should return failure result
        """
        result = uploader.upload('/nonexistent/file.gz', 'OBD2_Backups/backup.gz')

        assert result.success is False
        assert 'not found' in result.error.lower()

    def test_uploadFailure_pathIsDirectory(self, uploader):
        """
        Given: Path is a directory not a file
        When: Uploading
        Then: Should return failure result
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result = uploader.upload(tmpdir, 'OBD2_Backups/backup.gz')

            assert result.success is False
            assert 'not a file' in result.error.lower()

    @patch('backup.google_drive.shutil.which')
    def test_uploadFailure_rcloneNotInstalled(self, mockWhich, tempFile):
        """
        Given: rclone not installed
        When: Uploading file
        Then: Should return failure result
        """
        mockWhich.return_value = None

        uploader = GoogleDriveUploader()
        result = uploader.upload(str(tempFile), 'OBD2_Backups/backup.gz')

        assert result.success is False
        assert 'not installed' in result.error.lower()

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_uploadFailure_remoteNotConfigured(self, mockRun, mockWhich, tempFile):
        """
        Given: rclone installed but remote not configured
        When: Uploading file
        Then: Should return failure result
        """
        mockWhich.return_value = '/usr/bin/rclone'

        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=0, stdout='other:\n')
        ]

        uploader = GoogleDriveUploader(remoteName='gdrive')
        result = uploader.upload(str(tempFile), 'OBD2_Backups/backup.gz')

        assert result.success is False
        assert 'not configured' in result.error.lower()

    @patch('backup.google_drive.shutil.which')
    @patch('backup.google_drive.subprocess.run')
    def test_uploadFailure_timeout(self, mockRun, mockWhich, tempFile):
        """
        Given: rclone upload times out
        When: Uploading file
        Then: Should return failure result
        """
        import subprocess

        mockWhich.return_value = '/usr/bin/rclone'

        mockRun.side_effect = [
            MagicMock(returncode=0, stdout='rclone v1.60.0\n'),
            MagicMock(returncode=0, stdout='gdrive:\n'),
            subprocess.TimeoutExpired('rclone', 600)
        ]

        uploader = GoogleDriveUploader(remoteName='gdrive')
        result = uploader.upload(str(tempFile), 'OBD2_Backups/backup.gz')

        assert result.success is False
        assert 'timed out' in result.error.lower()


# ================================================================================
# Error Message Parsing Tests
# ================================================================================

class TestParseRcloneError:
    """Tests for rclone error message parsing."""

    def test_parseError_withErrorLine(self, uploader):
        """
        Given: stderr with error message
        When: Parsing error
        Then: Should extract error line
        """
        stderr = """
        2026/01/26 10:00:00 INFO: Starting upload
        2026/01/26 10:00:01 ERROR: Failed to upload: permission denied
        """

        result = uploader._parseRcloneError(stderr)

        assert 'permission denied' in result.lower()

    def test_parseError_emptyStderr(self, uploader):
        """
        Given: empty stderr
        When: Parsing error
        Then: Should return unknown error
        """
        result = uploader._parseRcloneError('')

        assert 'unknown' in result.lower()

    def test_parseError_noErrorLine(self, uploader):
        """
        Given: stderr without explicit error line
        When: Parsing error
        Then: Should return last line
        """
        stderr = "Some output\nAnother line\nFinal message"

        result = uploader._parseRcloneError(stderr)

        assert result == 'Final message'


# ================================================================================
# Configuration Setter Tests
# ================================================================================

class TestConfigurationSetters:
    """Tests for configuration setters."""

    def test_setRemoteName(self):
        """
        Given: Uploader with default remote
        When: Setting new remote name
        Then: Remote name should be updated and cache cleared
        """
        uploader = GoogleDriveUploader(remoteName='gdrive')

        # Set cache manually to verify it gets cleared
        uploader._rcloneConfigured = True

        uploader.setRemoteName('newdrive')

        assert uploader.getRemoteName() == 'newdrive'
        assert uploader._rcloneConfigured is None  # Cache cleared

    def test_setUploadTimeout(self):
        """
        Given: Uploader with default timeout
        When: Setting new timeout
        Then: Timeout should be updated
        """
        uploader = GoogleDriveUploader()

        uploader.setUploadTimeout(120)

        assert uploader.getUploadTimeout() == 120

    def test_clearCache(self):
        """
        Given: Uploader with cached values
        When: Clearing cache
        Then: Cached values should be None
        """
        uploader = GoogleDriveUploader()
        uploader._rcloneInstalled = True
        uploader._rcloneConfigured = True

        uploader.clearCache()

        assert uploader._rcloneInstalled is None
        assert uploader._rcloneConfigured is None


# ================================================================================
# Constants Tests
# ================================================================================

class TestConstants:
    """Tests for module constants."""

    def test_defaultRemoteName(self):
        """Default remote name should be 'gdrive'."""
        assert DEFAULT_REMOTE_NAME == 'gdrive'

    def test_checkTimeout(self):
        """Check timeout should be reasonable."""
        assert RCLONE_CHECK_TIMEOUT == 10
        assert RCLONE_CHECK_TIMEOUT > 0

    def test_uploadTimeout(self):
        """Upload timeout should be longer than check timeout."""
        assert RCLONE_UPLOAD_TIMEOUT == 600
        assert RCLONE_UPLOAD_TIMEOUT > RCLONE_CHECK_TIMEOUT


# ================================================================================
# Import Tests
# ================================================================================

class TestImports:
    """Tests that all exports are available from the backup package."""

    def test_importFromBackupPackage(self):
        """
        Given: backup package
        When: Importing GoogleDriveUploader exports
        Then: All exports should be available
        """
        from backup import (
            GoogleDriveUploader,
            UploadResult,
            DEFAULT_REMOTE_NAME,
            RCLONE_CHECK_TIMEOUT,
            RCLONE_UPLOAD_TIMEOUT,
        )

        assert GoogleDriveUploader is not None
        assert UploadResult is not None
        assert DEFAULT_REMOTE_NAME == 'gdrive'
        assert RCLONE_CHECK_TIMEOUT > 0
        assert RCLONE_UPLOAD_TIMEOUT > 0
