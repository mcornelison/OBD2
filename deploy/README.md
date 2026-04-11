# Eclipse OBD-II Deployment

Systemd service files and scripts for deploying to Raspberry Pi.

## Files

| File | Purpose |
|------|---------|
| `eclipse-obd.service` | systemd unit file (template) |
| `install-service.sh` | Installs and enables the service |
| `uninstall-service.sh` | Stops, disables, and removes the service |
| `deploy.conf.example` | Pi connection settings for remote deploy |

## Prerequisites

- Raspberry Pi with Raspbian/Debian
- Python 3.11+ virtual environment at `<install-path>/.venv`
- Bluetooth adapter and OBD-II dongle paired
- Application files deployed to `<install-path>/`

## Installation

### Quick Start

```bash
cd /home/mcornelison/obd2/deploy
sudo ./install-service.sh --user mcornelison --path /home/mcornelison/obd2
```

### What install-service.sh Does

1. Validates user exists, install path exists, venv exists, `src/main.py` exists
2. Creates `logs/` and `data/` directories under the install path
3. Copies `eclipse-obd.service` to `/etc/systemd/system/`
4. Substitutes `User`, `WorkingDirectory`, `PATH`, `ExecStart`, and log paths via sed
5. Runs `systemctl daemon-reload` and `systemctl enable eclipse-obd`

### Manual Installation

If you prefer to install manually:

```bash
# 1. Copy and edit the service file
sudo cp eclipse-obd.service /etc/systemd/system/
sudo nano /etc/systemd/system/eclipse-obd.service
# Update: User=, WorkingDirectory=, Environment=PATH=, ExecStart=, log paths

# 2. Reload systemd and enable
sudo systemctl daemon-reload
sudo systemctl enable eclipse-obd

# 3. Start the service
sudo systemctl start eclipse-obd
```

## Managing the Service

```bash
# Start / stop / restart
sudo systemctl start eclipse-obd
sudo systemctl stop eclipse-obd
sudo systemctl restart eclipse-obd

# Check status
sudo systemctl status eclipse-obd

# View logs (journald)
sudo journalctl -u eclipse-obd -f

# View logs (file)
tail -f /home/mcornelison/obd2/logs/service.log
tail -f /home/mcornelison/obd2/logs/service-error.log

# Disable auto-start on boot
sudo systemctl disable eclipse-obd
```

## Uninstallation

```bash
sudo ./uninstall-service.sh           # Removes service and log files
sudo ./uninstall-service.sh --keep-logs  # Removes service, keeps logs
```

## Service Configuration

The service file (`eclipse-obd.service`) is configured with:

| Setting | Value | Notes |
|---------|-------|-------|
| Type | simple | ExecStart is the main process |
| Restart | on-failure | Auto-restart on non-zero exit |
| RestartSec | 10 | Delay before restart (Bluetooth stabilization) |
| StartLimitBurst | 5 | Max restarts in 5 minutes |
| After | network.target, bluetooth.target | Wait for network and BT |
| Logging | append to `logs/service.log` | stdout and stderr to separate files |

## Troubleshooting

**Service won't start:**
```bash
sudo systemctl status eclipse-obd    # Check for error messages
sudo journalctl -u eclipse-obd -n 50 # Last 50 log entries
```

**Bluetooth not ready:**
The service waits for `bluetooth.target`. If the dongle isn't paired, the application handles reconnection internally with exponential backoff.

**Permission denied:**
Verify the service user owns the install directory and has access to the Bluetooth adapter:
```bash
ls -la /home/mcornelison/obd2/
groups mcornelison  # Should include 'bluetooth' and 'dialout'
```
