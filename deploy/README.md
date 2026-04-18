# Eclipse OBD-II Deployment

Deployment tooling for both project tiers — the Raspberry Pi 5 (chi-eclipse-01)
and the home analysis server (chi-srv-01).

## Files

| File | Purpose |
|------|---------|
| `deploy-pi.sh` | Pi 5 deploy script — rsync code, update venv, restart service |
| `deploy-server.sh` | Chi-Srv-01 deploy script (parallel pattern) |
| `eclipse-obd.service` | systemd unit file for the Pi (template) |
| `install-service.sh` | Installs and enables the Pi systemd service |
| `uninstall-service.sh` | Stops, disables, and removes the Pi systemd service |
| `deploy.conf.example` | Pi connection settings for remote deploy (copy to deploy.conf) |
| `obd2-server.service` | systemd unit file for the server |
| `install-server.sh` | Server installation helper |
| `setup-mariadb.sh` | One-shot server DB bootstrap |

## Pi Tier — `deploy-pi.sh`

Single script that runs from a Windows git-bash shell, SSHes to
`mcornelison@10.27.27.28`, mirrors the working tree to the Pi, updates the
Python venv, and restarts the systemd service.

### Modes

| Flag | Behavior |
|------|----------|
| (none) | Default: `rsync` tree → update venv deps → restart service |
| `--init` | First-time setup: wipe legacy `~/Projects`, create dirs + fresh venv, install system deps via apt, rename hostname to `chi-eclipse-01`, then run the default body |
| `--restart` | Bounce the `eclipse-obd` systemd service only |
| `--dry-run` | Print intended actions without touching the Pi (offline-safe — no SSH or rsync needed) |
| `--help`, `-h` | Show usage |

### One-time setup (operator workflow)

```bash
# 1. Make a local override of the Pi connection details (gitignored)
cp deploy/deploy.conf.example deploy/deploy.conf
# (edit deploy.conf if your Pi is not at 10.27.27.28)

# 2. First-time Pi bootstrap (wipes legacy ~/Projects, sets hostname, etc.)
bash deploy/deploy-pi.sh --init

# 3. (later) re-deploy after pulling new code on Windows
bash deploy/deploy-pi.sh

# 4. (later) bounce the service after editing config on the Pi
bash deploy/deploy-pi.sh --restart
```

### Re-deploy in 30 seconds (operator quick-card)

```bash
cd /z/o/OBD2v2          # or wherever your local clone lives
bash deploy/deploy-pi.sh
```

That's it. The script is idempotent: re-running it back-to-back produces no
content or mtime change (rsync is byte-exact; the tar fallback preserves
mtimes on extract, so a second default-mode run converges to the same state).

### Prerequisites

- **Local (Windows git-bash):** key-based SSH to `mcornelison@10.27.27.28` already
  works. The script prefers `rsync` for incremental sync; if `rsync` isn't
  installed, it automatically falls back to a `tar -cz | ssh … | tar -xz`
  pipe (no extra install needed — `tar` and `ssh` ship with git-bash).
  Install `rsync` (e.g. via MSYS2 `pacman -S rsync` if available, or cwRsync)
  for faster re-runs that only re-transfer changed bytes.
- **Pi side:** SSH server running, `sudo` available without password prompt for
  the deploy user (or you'll be prompted during apt installs / hostname rename).

### What `--init` installs on the Pi (apt)

`python3-venv python3-dev i2c-tools bluetooth bluez bluez-tools libbluetooth-dev
libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev libfreetype6-dev
libjpeg-dev libportmidi-dev zlib1g-dev sqlite3 rsync`

These cover: Python venv, i2cdetect (X1209 UPS HAT), Bluetooth (future OBD-II
dongle), pygame (OSOYOO HDMI display), Pillow image processing, sqlite3 (DB
integrity checks), rsync (self-deploy parity).

### Smoke test

```bash
bash tests/deploy/test_deploy_pi.sh
# or run inside the suite:
pytest tests/deploy/ -v
```

Asserts flag parsing, `--help`, `--dry-run` safety (no real SSH, no real rsync),
mutual exclusion of `--init`/`--restart`, and `deploy.conf` override behavior.

## Pi Tier — systemd service (eclipse-obd.service)

### Prerequisites

- Raspberry Pi with Raspbian/Debian
- Python 3.11+ virtual environment at `/home/mcornelison/obd2-venv`
  (dedicated Pi venv, parallel to the server's `~/obd2-server-venv`)
- Bluetooth adapter and OBD-II dongle paired (optional — simulator mode works
  without hardware)
- Application files deployed to `/home/mcornelison/Projects/Eclipse-01/`

### Installation

#### Quick Start

```bash
cd /home/mcornelison/Projects/Eclipse-01/deploy
sudo ./install-service.sh
# Or override the defaults:
sudo ./install-service.sh \
    --user mcornelison \
    --path /home/mcornelison/Projects/Eclipse-01 \
    --venv /home/mcornelison/obd2-venv
```

#### What install-service.sh Does

1. Validates user exists, install path exists, venv exists, `src/pi/main.py` exists
2. Creates `data/` directory under the install path (logs live in the systemd
   journal — no `logs/` directory is created or used)
3. Copies `eclipse-obd.service` to `/etc/systemd/system/`
4. Substitutes `User`, `WorkingDirectory`, `PATH`, and `ExecStart` via sed
5. Runs `systemctl daemon-reload` and `systemctl enable eclipse-obd`

The script is idempotent: running it twice back-to-back produces the same
end state (the service file is overwritten with the current template and
the `systemctl enable` call is a no-op on re-run).

#### Manual Installation

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

### Managing the Service

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

### Uninstallation

```bash
sudo ./uninstall-service.sh           # Removes service and log files
sudo ./uninstall-service.sh --keep-logs  # Removes service, keeps logs
```

### Service Configuration

The service file (`eclipse-obd.service`) is configured with:

| Setting | Value | Notes |
|---------|-------|-------|
| Type | simple | ExecStart is the main process |
| Restart | on-failure | Auto-restart on non-zero exit |
| RestartSec | 10 | Delay before restart (Bluetooth stabilization) |
| StartLimitBurst | 5 | Max restarts in 5 minutes |
| After | network.target, bluetooth.target | Wait for network and BT |
| Logging | append to `logs/service.log` | stdout and stderr to separate files |

### Troubleshooting

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
