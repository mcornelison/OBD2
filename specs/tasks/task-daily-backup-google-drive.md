# Task: Implement Daily Backup to Google Drive

## Summary
Implement automated daily backup of the SQLite database to Google Drive, with catch-up logic for missed backups.

## Background
Currently there is no backup strategy for `data/obd.db`. If the database is corrupted, all data is lost. The Pi will be connected to home WiFi, enabling cloud backups.

## Requirements

### Backup Behavior
1. **Daily backup**: Run once per day when connected to WiFi
2. **Catch-up backup**: If backup hasn't run in 2+ days, backup immediately on next WiFi connection
3. **Backup on shutdown**: Optionally backup before graceful shutdown
4. **Compression**: Compress backup to reduce upload size

### Configuration
Add to `config.json`:
```json
{
  "backup": {
    "enabled": true,
    "provider": "google_drive",
    "folderPath": "OBD2_Backups",
    "scheduleTime": "03:00",
    "maxBackups": 30,
    "compressBackups": true
  }
}
```

### Google Drive Integration
Options to evaluate:
1. **rclone** - CLI tool, supports Google Drive, easy to configure
2. **PyDrive2** - Python library for Google Drive API
3. **google-api-python-client** - Official Google API

Recommendation: Use `rclone` for simplicity and reliability.

### Backup File Naming
```
obd_backup_YYYY-MM-DD_HHMMSS.db.gz
```

### Catch-Up Logic
```python
lastBackupTime = getLastBackupTime()
daysSinceBackup = (now - lastBackupTime).days

if daysSinceBackup >= 2:
    performBackupImmediately()
elif isScheduledTime():
    performDailyBackup()
```

## Implementation Components

### New Files
- [ ] `src/backup/backup_manager.py` - Backup orchestration
- [ ] `src/backup/google_drive.py` - Google Drive provider
- [ ] `src/backup/types.py` - Backup types and config
- [ ] `scripts/setup_backup.sh` - rclone setup helper

### Modified Files
- [ ] `src/config.json` - Add backup configuration
- [ ] `src/obd/orchestrator.py` - Integrate backup manager
- [ ] `specs/architecture.md` - Document backup architecture

## Acceptance Criteria
- [ ] Daily backup runs automatically
- [ ] Catch-up backup runs if >2 days since last backup
- [ ] Backups appear in Google Drive folder
- [ ] Old backups are cleaned up (keep last 30)
- [ ] Backup failures are logged (don't crash the app)
- [ ] Configuration documented
- [ ] Setup instructions documented

## Security Considerations
- Google Drive credentials stored securely (not in config.json)
- Use rclone's secure credential storage
- Document credential setup in deployment guide

## Priority
Medium - Important for data safety

## Estimated Effort
Medium - New feature with external integration

## Created
2026-01-25 - Tech debt review
