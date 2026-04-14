"""
Backup metadata wire format.

Will eventually contain:
- BackupMetadata: a backup artifact's metadata (filename, size, checksum,
  device ID, timestamp, content type)
- BackupType: enum (drive_log, config_snapshot, calibration, other)

Populated post-reorg.
"""
