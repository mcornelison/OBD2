# Backup Configuration Guide

This guide explains how to set up and configure automatic backups for the Eclipse OBD-II system to Google Drive.

## Overview

The backup system automatically backs up your OBD-II database to Google Drive using [rclone](https://rclone.org/). Features include:

- **Automatic daily backups** at a configurable time (default: 3:00 AM)
- **Compression** to reduce storage and upload time
- **Catch-up backups** after system downtime
- **Rotation** to keep the last N backups (default: 30)
- **Graceful degradation** when Google Drive is unavailable

## Prerequisites

- Raspberry Pi running Raspberry Pi OS (or Debian-based Linux)
- Internet connection
- Google account with Drive access

## Quick Setup

Run the setup script to install and configure rclone:

```bash
sudo ./scripts/setup_backup.sh
```

The script will:
1. Install rclone if not present
2. Guide you through Google Drive OAuth authentication
3. Verify the connection with a test upload

## Manual Setup

### 1. Install rclone

```bash
sudo apt update
sudo apt install rclone
```

### 2. Configure rclone

```bash
rclone config
```

When prompted:
1. Choose `n` for new remote
2. Enter `gdrive` as the name
3. Choose `drive` (Google Drive)
4. Leave client_id and client_secret blank (use defaults)
5. Choose scope: `1` (full access)
6. Leave root_folder_id blank
7. Leave service_account_file blank
8. Choose `n` for advanced config
9. Choose `y` for auto config (or `n` for headless)

### 3. Verify Setup

```bash
# List remotes
rclone listremotes

# Test connection
rclone lsd gdrive:

# Test upload
echo "test" > /tmp/test.txt
rclone copyto /tmp/test.txt gdrive:OBD2_Backups/test.txt
rclone ls gdrive:OBD2_Backups/
rclone deletefile gdrive:OBD2_Backups/test.txt
```

## Headless Setup (No Monitor)

If configuring on a headless Raspberry Pi:

1. On your local machine (with a browser), install rclone and run:
   ```bash
   rclone authorize "drive"
   ```

2. Complete the OAuth flow in your browser

3. Copy the resulting token

4. On the Pi, run `rclone config` and when prompted for browser auth, select:
   ```
   n) No, I don't have a browser
   ```

5. Paste the authorization token

See: https://rclone.org/remote_setup/

## Configuration

Update your `config.json` to enable backups:

```json
{
  "backup": {
    "enabled": true,
    "provider": "google_drive",
    "folderPath": "OBD2_Backups",
    "scheduleTime": "03:00",
    "maxBackups": 30,
    "compressBackups": true,
    "catchupDays": 2
  }
}
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Enable/disable automatic backups |
| `provider` | `google_drive` | Backup provider (currently only Google Drive) |
| `folderPath` | `OBD2_Backups` | Folder path in Google Drive |
| `scheduleTime` | `03:00` | Daily backup time (24-hour format) |
| `maxBackups` | `30` | Maximum backups to retain |
| `compressBackups` | `true` | Compress backups with gzip |
| `catchupDays` | `2` | Run catch-up backup if last backup older than N days |

## How It Works

### Backup Process

1. **Compression**: The database (`data/obd.db`) is compressed to `.gz` format
2. **Timestamping**: Backup filename includes timestamp: `obd_backup_YYYYMMDD_HHMMSS.db.gz`
3. **Upload**: Compressed backup is uploaded to Google Drive via rclone
4. **Metadata**: Backup metadata is stored in `data/backup_metadata.json`
5. **Rotation**: Old backups are deleted when count exceeds `maxBackups`

### Catch-up Backups

If the system was offline (e.g., vehicle stored for winter), a catch-up backup runs on startup when the last backup is older than `catchupDays`.

### Graceful Degradation

If Google Drive is unavailable:
- The system logs a warning but continues normal operation
- Backup will retry at the next scheduled time
- No data is lost - the database remains local

## Manual Backup Commands

```bash
# List backups in Google Drive
rclone ls gdrive:OBD2_Backups/

# Download a backup
rclone copy gdrive:OBD2_Backups/obd_backup_20260126_030000.db.gz ./

# Upload a backup manually
rclone copyto ./data/backup.db.gz gdrive:OBD2_Backups/manual_backup.db.gz

# Check backup folder size
rclone size gdrive:OBD2_Backups/

# Delete old backups
rclone delete gdrive:OBD2_Backups/old_backup.db.gz
```

## Restoring from Backup

1. Download the backup:
   ```bash
   rclone copy gdrive:OBD2_Backups/obd_backup_TIMESTAMP.db.gz ./
   ```

2. Decompress:
   ```bash
   gunzip obd_backup_TIMESTAMP.db.gz
   ```

3. Stop the application:
   ```bash
   # If running as service
   sudo systemctl stop obd2
   ```

4. Replace the database:
   ```bash
   mv data/obd.db data/obd.db.old
   mv obd_backup_TIMESTAMP.db data/obd.db
   ```

5. Restart the application:
   ```bash
   sudo systemctl start obd2
   ```

## Troubleshooting

### rclone not found

```bash
# Install rclone
sudo apt update
sudo apt install rclone

# Or run the setup script
sudo ./scripts/setup_backup.sh
```

### Authentication failed

```bash
# Reconfigure the remote
rclone config delete gdrive
rclone config  # Create new remote named 'gdrive'
```

### Upload failed

```bash
# Check connection
rclone lsd gdrive:

# Check disk space
rclone about gdrive:

# Test with verbose output
rclone copyto file.txt gdrive:test.txt -v
```

### Check rclone version

```bash
rclone version
```

Minimum recommended version: 1.50.0

## Security Notes

- OAuth tokens are stored in `~/.config/rclone/rclone.conf`
- The rclone config file contains sensitive tokens - do not share
- Google Drive data is encrypted in transit (TLS)
- Consider enabling Google Drive's built-in encryption for sensitive data

## Related Documentation

- [Hardware Reference](hardware-reference.md) - Hardware setup guide
- [rclone Google Drive docs](https://rclone.org/drive/) - Official rclone documentation
- [Google Drive API](https://developers.google.com/drive) - Google's API documentation
