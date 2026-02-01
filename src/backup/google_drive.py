################################################################################
# File Name: google_drive.py
# Purpose/Description: Google Drive upload functionality via rclone
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
Google Drive upload functionality via rclone.

Provides the GoogleDriveUploader class for uploading backup files to Google Drive
using rclone subprocess calls. Designed for graceful degradation when rclone is
not installed or not configured.

Usage:
    from backup.google_drive import GoogleDriveUploader

    uploader = GoogleDriveUploader(remoteName='gdrive')

    # Check if rclone is available and configured
    if uploader.isAvailable():
        result = uploader.upload('/path/to/backup.gz', 'OBD2_Backups/backup.gz')
        if result.success:
            print(f"Uploaded to {result.remotePath}")
"""

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Default rclone remote name for Google Drive
DEFAULT_REMOTE_NAME = 'gdrive'

# Default timeout for rclone operations (seconds)
RCLONE_CHECK_TIMEOUT = 10
RCLONE_UPLOAD_TIMEOUT = 600  # 10 minutes for large uploads

# rclone version command for checking installation
RCLONE_VERSION_CMD = ['rclone', 'version']

# rclone listremotes command for checking configuration
RCLONE_LISTREMOTES_CMD = ['rclone', 'listremotes']


@dataclass
class UploadResult:
    """
    Result of an upload operation.

    Attributes:
        success: Whether the upload completed successfully
        remotePath: Full remote path where file was uploaded (None if failed)
        error: Error message if upload failed (None if success)
        bytesTransferred: Number of bytes transferred (None if unknown/failed)
    """

    success: bool
    remotePath: str | None = None
    error: str | None = None
    bytesTransferred: int | None = None


class GoogleDriveUploader:
    """
    Uploads files to Google Drive via rclone.

    This class provides a simple interface for uploading files to Google Drive
    using rclone subprocess calls. It checks for rclone availability and proper
    configuration before attempting uploads.

    Attributes:
        remoteName: Name of the rclone remote (e.g., 'gdrive')
        uploadTimeout: Timeout in seconds for upload operations

    Example:
        uploader = GoogleDriveUploader(remoteName='gdrive')

        if uploader.isAvailable():
            result = uploader.upload('backup.gz', 'OBD2_Backups/backup.gz')
            if result.success:
                print(f"Uploaded to {result.remotePath}")
        else:
            print("Google Drive upload not available")
    """

    def __init__(
        self,
        remoteName: str = DEFAULT_REMOTE_NAME,
        uploadTimeout: int = RCLONE_UPLOAD_TIMEOUT
    ):
        """
        Initialize the Google Drive uploader.

        Args:
            remoteName: Name of the rclone remote for Google Drive
            uploadTimeout: Timeout in seconds for upload operations
        """
        self._remoteName = remoteName
        self._uploadTimeout = uploadTimeout
        self._rcloneInstalled: bool | None = None
        self._rcloneConfigured: bool | None = None

    # ================================================================================
    # Availability Checks
    # ================================================================================

    def isRcloneInstalled(self) -> bool:
        """
        Check if rclone is installed and accessible.

        Returns:
            True if rclone is installed and can be executed
        """
        if self._rcloneInstalled is not None:
            return self._rcloneInstalled

        # Also check if rclone is in PATH using shutil.which
        rclonePath = shutil.which('rclone')
        if rclonePath is None:
            logger.debug("rclone not found in PATH")
            self._rcloneInstalled = False
            return False

        try:
            result = subprocess.run(
                RCLONE_VERSION_CMD,
                capture_output=True,
                text=True,
                timeout=RCLONE_CHECK_TIMEOUT
            )
            self._rcloneInstalled = result.returncode == 0

            if self._rcloneInstalled:
                # Extract version from output for logging
                versionLine = result.stdout.strip().split('\n')[0] if result.stdout else 'unknown'
                logger.debug(f"rclone installed: {versionLine}")
            else:
                logger.warning(f"rclone check failed: {result.stderr}")

        except FileNotFoundError:
            logger.warning("rclone not installed")
            self._rcloneInstalled = False
        except subprocess.TimeoutExpired:
            logger.warning("rclone version check timed out")
            self._rcloneInstalled = False
        except Exception as e:
            logger.warning(f"Failed to check rclone installation: {e}")
            self._rcloneInstalled = False

        return self._rcloneInstalled

    def isRcloneConfigured(self) -> bool:
        """
        Check if rclone remote is configured for Google Drive.

        Returns:
            True if the configured remote exists in rclone config
        """
        if not self.isRcloneInstalled():
            return False

        if self._rcloneConfigured is not None:
            return self._rcloneConfigured

        try:
            result = subprocess.run(
                RCLONE_LISTREMOTES_CMD,
                capture_output=True,
                text=True,
                timeout=RCLONE_CHECK_TIMEOUT
            )

            if result.returncode != 0:
                logger.warning(f"rclone listremotes failed: {result.stderr}")
                self._rcloneConfigured = False
                return False

            # Parse remotes list (each line is "remotename:")
            remotes = [
                line.strip().rstrip(':')
                for line in result.stdout.strip().split('\n')
                if line.strip()
            ]

            self._rcloneConfigured = self._remoteName in remotes

            if self._rcloneConfigured:
                logger.debug(f"rclone remote '{self._remoteName}' is configured")
            else:
                logger.warning(
                    f"rclone remote '{self._remoteName}' not found. "
                    f"Available remotes: {remotes}"
                )

        except subprocess.TimeoutExpired:
            logger.warning("rclone listremotes timed out")
            self._rcloneConfigured = False
        except Exception as e:
            logger.warning(f"Failed to check rclone configuration: {e}")
            self._rcloneConfigured = False

        return self._rcloneConfigured

    def isAvailable(self) -> bool:
        """
        Check if Google Drive upload is available.

        This combines both installation and configuration checks.

        Returns:
            True if rclone is installed and the remote is configured
        """
        return self.isRcloneInstalled() and self.isRcloneConfigured()

    def getRemotes(self) -> list[str]:
        """
        Get list of configured rclone remotes.

        Returns:
            List of remote names, or empty list if rclone not available
        """
        if not self.isRcloneInstalled():
            return []

        try:
            result = subprocess.run(
                RCLONE_LISTREMOTES_CMD,
                capture_output=True,
                text=True,
                timeout=RCLONE_CHECK_TIMEOUT
            )

            if result.returncode != 0:
                return []

            return [
                line.strip().rstrip(':')
                for line in result.stdout.strip().split('\n')
                if line.strip()
            ]

        except Exception:
            return []

    # ================================================================================
    # Upload Operations
    # ================================================================================

    def upload(self, localPath: str, remotePath: str) -> UploadResult:
        """
        Upload a file to Google Drive.

        Args:
            localPath: Path to the local file to upload
            remotePath: Remote path (relative to remote root) where file should be stored

        Returns:
            UploadResult with success status and details

        Raises:
            BackupNotAvailableError: If rclone is not installed or configured
            BackupOperationError: If upload fails due to an error
        """
        # Validate local file exists
        localFilePath = Path(localPath)
        if not localFilePath.exists():
            error = f"Local file not found: {localPath}"
            logger.error(error)
            return UploadResult(success=False, error=error)

        if not localFilePath.is_file():
            error = f"Path is not a file: {localPath}"
            logger.error(error)
            return UploadResult(success=False, error=error)

        # Check rclone availability
        if not self.isRcloneInstalled():
            error = "rclone is not installed"
            logger.warning(error)
            return UploadResult(success=False, error=error)

        if not self.isRcloneConfigured():
            error = f"rclone remote '{self._remoteName}' is not configured"
            logger.warning(error)
            return UploadResult(success=False, error=error)

        # Build full remote path
        fullRemotePath = f"{self._remoteName}:{remotePath}"

        # Get file size for logging
        fileSize = localFilePath.stat().st_size

        # Build rclone copy command
        cmd = [
            'rclone',
            'copyto',
            str(localFilePath),
            fullRemotePath,
            '--progress',
            '--stats-one-line',
        ]

        logger.info(f"Uploading {localFilePath.name} ({fileSize / 1024:.1f} KB) to {fullRemotePath}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._uploadTimeout
            )

            if result.returncode == 0:
                logger.info(f"Upload completed: {fullRemotePath}")
                return UploadResult(
                    success=True,
                    remotePath=fullRemotePath,
                    bytesTransferred=fileSize
                )
            else:
                error = self._parseRcloneError(result.stderr)
                logger.error(f"Upload failed: {error}")
                return UploadResult(success=False, error=error)

        except subprocess.TimeoutExpired:
            error = f"Upload timed out after {self._uploadTimeout} seconds"
            logger.error(error)
            return UploadResult(success=False, error=error)

        except Exception as e:
            error = f"Upload error: {e}"
            logger.error(error)
            return UploadResult(success=False, error=error)

    def _parseRcloneError(self, stderr: str) -> str:
        """
        Parse rclone stderr to extract a meaningful error message.

        Args:
            stderr: The stderr output from rclone

        Returns:
            A cleaned up error message
        """
        if not stderr:
            return "Unknown rclone error"

        # Look for common error patterns
        stderr = stderr.strip()

        # Return last non-empty line as it usually contains the error
        lines = [line.strip() for line in stderr.split('\n') if line.strip()]
        if lines:
            # Find error lines
            errorLines = [line for line in lines if 'error' in line.lower() or 'failed' in line.lower()]
            if errorLines:
                return errorLines[-1]
            return lines[-1]

        return stderr

    # ================================================================================
    # Utility Methods
    # ================================================================================

    def setRemoteName(self, remoteName: str) -> None:
        """
        Set the rclone remote name.

        Args:
            remoteName: New remote name
        """
        self._remoteName = remoteName
        # Reset cached configuration check
        self._rcloneConfigured = None

    def getRemoteName(self) -> str:
        """
        Get the current rclone remote name.

        Returns:
            Current remote name
        """
        return self._remoteName

    def setUploadTimeout(self, timeout: int) -> None:
        """
        Set the upload timeout.

        Args:
            timeout: Timeout in seconds
        """
        self._uploadTimeout = timeout

    def getUploadTimeout(self) -> int:
        """
        Get the current upload timeout.

        Returns:
            Timeout in seconds
        """
        return self._uploadTimeout

    def clearCache(self) -> None:
        """
        Clear cached availability checks.

        Call this to force re-checking rclone installation and configuration.
        """
        self._rcloneInstalled = None
        self._rcloneConfigured = None
