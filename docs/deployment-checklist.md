# Raspberry Pi Deployment Checklist

## Overview

This checklist covers the steps needed before deploying the Eclipse OBD-II system to a Raspberry Pi 5.

**Last Updated**: 2026-01-23

---

## Pre-Deployment Tasks

### Priority 1: Application Orchestration (Critical)

The `main.py` `runWorkflow()` function is currently a placeholder. This needs to be implemented to wire up all the components.

**Required:**

```python
def runWorkflow(config: dict, simulate: bool = False) -> bool:
    """
    Main application loop that orchestrates all components.

    1. Initialize database
    2. Create OBD connection (real or simulated)
    3. Start display manager
    4. Start drive detector
    5. Start realtime data logger
    6. Start alert manager
    7. Handle graceful shutdown
    """
```

**Components to wire up:**
- [ ] `ObdDatabase` - Initialize and verify schema
- [ ] `ObdConnection` or `SimulatedObdConnection` - Based on --simulate flag
- [ ] `DisplayManager` - Start display updates
- [ ] `DriveDetector` - Monitor for drive start/end
- [ ] `RealtimeDataLogger` - Poll and log OBD parameters
- [ ] `AlertManager` - Monitor thresholds
- [ ] `StatisticsEngine` - Trigger on drive end
- [ ] `VinDecoder` - Decode on first connection
- [ ] Shutdown handlers - Clean up on SIGINT/SIGTERM

**Estimated effort:** Medium-High

---

### Priority 2: End-to-End Integration Test

Create a test that runs the full application in simulator mode:

```bash
# Should run for 60 seconds, simulate a drive, and exit cleanly
python src/main.py --simulate --config src/obd_config.json
```

**Verify:**
- [ ] Application starts without errors
- [ ] Database records are created
- [ ] Simulated drive is detected
- [ ] Statistics are calculated
- [ ] Graceful shutdown works (Ctrl+C)

**Estimated effort:** Low

---

### Priority 3: Production Configuration

**Environment file (.env) for Pi:**

```bash
# .env.production
APP_ENVIRONMENT=production
DB_PATH=/home/pi/obd2/data/obd.db
OBD_BT_MAC=XX:XX:XX:XX:XX:XX  # Your dongle's MAC address
DISPLAY_MODE=minimal
LOG_LEVEL=INFO
LOG_FILE=/home/pi/obd2/logs/obd.log
EXPORT_DIR=/home/pi/obd2/exports/
```

**Tasks:**
- [ ] Create `.env.production` template
- [ ] Document how to find OBD-II dongle MAC address
- [ ] Test configuration loading on Pi

**Estimated effort:** Low

---

### Priority 4: Systemd Service Setup

**Status: COMPLETE** - Service files and install scripts created in `deploy/` directory.

#### Service Files

The following files are provided in the `deploy/` directory:

| File | Purpose |
|------|---------|
| `eclipse-obd.service` | systemd service unit file |
| `install-service.sh` | Installation script with configuration options |
| `uninstall-service.sh` | Clean uninstallation script |

#### Quick Installation

```bash
# Navigate to your installation directory
cd /home/pi/obd2

# Run the install script (default user: pi, default path: /home/pi/obd2)
sudo ./deploy/install-service.sh

# Or with custom options:
sudo ./deploy/install-service.sh --user myuser --path /opt/obd2
```

#### Manual Installation

If you prefer manual installation:

```bash
# 1. Copy service file
sudo cp deploy/eclipse-obd.service /etc/systemd/system/

# 2. Edit the service file to match your configuration
sudo nano /etc/systemd/system/eclipse-obd.service
# Update: User, WorkingDirectory, PATH, ExecStart paths

# 3. Create logs directory
mkdir -p /home/pi/obd2/logs

# 4. Reload systemd
sudo systemctl daemon-reload

# 5. Enable service (start on boot)
sudo systemctl enable eclipse-obd

# 6. Start the service
sudo systemctl start eclipse-obd
```

#### Service Management Commands

```bash
# Start the service
sudo systemctl start eclipse-obd

# Stop the service
sudo systemctl stop eclipse-obd

# Restart the service
sudo systemctl restart eclipse-obd

# Check status
sudo systemctl status eclipse-obd

# View logs (systemd journal)
sudo journalctl -u eclipse-obd -f

# View logs (file)
tail -f /home/pi/obd2/logs/service.log

# Disable auto-start
sudo systemctl disable eclipse-obd

# Re-enable auto-start
sudo systemctl enable eclipse-obd
```

#### Uninstallation

```bash
# Remove service (also removes service log files)
sudo ./deploy/uninstall-service.sh

# Remove service but keep log files
sudo ./deploy/uninstall-service.sh --keep-logs
```

#### Service Configuration Details

The service file includes:
- **Type: simple** - Main process is the Python application
- **Restart: on-failure** - Automatically restart if crashes (non-zero exit)
- **RestartSec: 10** - Wait 10 seconds before restart (allows Bluetooth to stabilize)
- **StartLimitBurst: 5** - Maximum 5 restart attempts in 5 minutes
- **After: network.target bluetooth.target** - Starts after network and Bluetooth are ready

**Tasks:**
- [x] Create service file template
- [x] Create install script with configuration options
- [x] Create uninstall script
- [x] Document installation steps
- [ ] Test start/stop/restart (requires Raspberry Pi)
- [ ] Verify auto-start on reboot (requires Raspberry Pi)

**Estimated effort:** Low - Completed

---

### Priority 5: Bluetooth Pairing Guide

Document the OBD-II dongle setup:

```bash
# On Raspberry Pi
bluetoothctl
> scan on
> pair XX:XX:XX:XX:XX:XX
> trust XX:XX:XX:XX:XX:XX
> quit
```

**Tasks:**
- [ ] Document pairing procedure
- [ ] Add troubleshooting for common Bluetooth issues
- [ ] Test connection with `python-OBD` directly

**Estimated effort:** Low

---

### Priority 6: Hardware Verification Script

Create a script to verify Pi hardware is working:

```python
# scripts/verify_hardware.py
def main():
    # Check Bluetooth adapter
    # Check display (if connected)
    # Check GPIO (if using power monitoring)
    # Check I2C (if using voltage monitoring)
    # Attempt OBD-II connection
```

**Tasks:**
- [ ] Create hardware verification script
- [ ] Test on actual Pi hardware

**Estimated effort:** Low-Medium

---

## Nice-to-Have (Post-Deployment)

### Data Backup Strategy

- [ ] Script to backup database to USB/network
- [ ] Scheduled backup via cron

### Remote Monitoring

- [ ] SSH access documentation
- [ ] Optional: Web dashboard for remote viewing

### OTA Updates

- [ ] Script to pull latest code from git
- [ ] Restart service after update

---

## Deployment Steps (Summary)

```bash
# 1. On Raspberry Pi - Clone repository
git clone <repo-url> ~/obd2
cd ~/obd2

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-pi.txt

# 4. Configure environment
cp .env.example .env.production
nano .env.production  # Set your values

# 5. Initialize database
python -c "from src.obd.database import initializeDatabase; initializeDatabase({})"

# 6. Pair Bluetooth dongle
bluetoothctl  # Follow pairing guide

# 7. Test manually
python src/main.py --config src/obd_config.json

# 8. Install service (optional)
sudo cp eclipse-obd.service /etc/systemd/system/
sudo systemctl enable eclipse-obd
sudo systemctl start eclipse-obd

# 9. Verify
sudo systemctl status eclipse-obd
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Bluetooth pairing fails | Medium | High | Document troubleshooting, test early |
| Display not detected | Low | Medium | Graceful fallback to headless |
| Database corruption | Low | High | WAL mode, backups |
| Power loss mid-write | Medium | Medium | WAL mode handles this |
| OBD-II dongle incompatible | Low | High | Test with python-OBD first |

---

## Testing Matrix

| Test | Windows | Raspberry Pi |
|------|---------|--------------|
| Unit tests | ✅ Run all | ✅ Run all |
| Simulator mode | ✅ Full test | ✅ Full test |
| Real OBD-II | ❌ N/A | ✅ Required |
| Display | ❌ N/A | ✅ If connected |
| GPIO/I2C | ❌ N/A | ✅ If enabled |
| Service start/stop | ❌ N/A | ✅ Required |
| Boot auto-start | ❌ N/A | ✅ Required |

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-23 | Claude | Initial deployment checklist |
| 2026-01-23 | Ralph Agent | US-OSC-016: Added systemd service files and installation documentation |
