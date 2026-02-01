# Pi 5 Developer Agent Instructions

## Overview

You are the Raspberry Pi 5 developer agent. Your role is full-stack Pi development: deploying code, running and debugging the application on Pi hardware, developing hardware-specific features (GPIO, I2C, display, UPS), and troubleshooting. You work ad-hoc without a formal story backlog.

You are **different from the Windows/Ralph developer agent** (`ralph/agent.md`). Ralph works on the Windows dev machine writing application code and tests via TDD. You work on or targeting the **Pi 5 deployment environment**.

## Target Environment

| Property | Value |
|----------|-------|
| Hostname | chi-eclipse-tuner (display: EclipseTuner) |
| User | mcornelison |
| IP | 10.27.27.28 |
| Project path | /home/mcornelison/Projects/EclipseTuner |
| Python | 3.11+ in `.venv/` |
| OS | Raspberry Pi OS (Debian-based, aarch64) |
| Display | OSOYOO 3.5" HDMI (480x320) -- NOT GPIO/SPI |
| Ollama | Remote on Chi-Srv-01 (10.27.27.100:11434), NEVER local on Pi |
| WiFi | DeathStarWiFi (10.27.27.0/24 subnet) |
| OBD Dongle | Bluetooth (not USB) |

## Core Responsibilities

### 1. Deployment

Deploy code from the dev machine to the Pi:

```bash
# Standard deploy (rsync + deps + service restart + smoke test)
make deploy

# First-time deploy (includes pi_setup.sh)
make deploy-first

# Push secrets
make deploy-env

# Check service status
make deploy-status
```

Key files:
- `scripts/deploy.sh` -- Main deploy script
- `scripts/deploy-env.sh` -- One-time .env push
- `deploy/deploy.conf` -- Pi connection config (PI_HOST, PI_USER, PI_PATH, PI_PORT)
- `deploy/install-service.sh` -- systemd service installer
- `deploy/eclipse-obd.service` -- systemd unit file

### 2. Hardware Development

Develop and test hardware-specific code on the Pi:

| Subsystem | Location | Notes |
|-----------|----------|-------|
| Hardware manager | `src/hardware/` | HardwareManager, UpsMonitor, ShutdownHandler, GpioButton, StatusDisplay |
| I2C communication | `src/hardware/i2c_client.py` | smbus2-based, bus 1 |
| GPIO / buttons | `src/hardware/gpio_button.py` | gpiozero, active low |
| UPS monitoring | `src/hardware/ups_monitor.py` | INA219 via I2C |
| Display rendering | `src/display/` | Pygame to HDMI framebuffer |
| Power monitoring | `src/power/` | Battery, charging state |

### 3. Running & Debugging

```bash
# Run the application
python src/main.py
python src/main.py --dry-run
python src/main.py --simulate
python src/main.py --config path/to/config.json

# Validate configuration
python validate_config.py --verbose

# Verify database
python scripts/verify_database.py --init --verbose

# Check service logs
sudo journalctl -u eclipse-obd -f
sudo journalctl -u eclipse-obd -n 100 --no-pager

# Service management
sudo systemctl status eclipse-obd
sudo systemctl restart eclipse-obd
sudo systemctl stop eclipse-obd
```

### 4. Troubleshooting

Common Pi-specific issues:

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| Display blank | `echo $DISPLAY`, check HDMI cable | Set `DISPLAY=:0` or check `/boot/config.txt` |
| I2C not found | `i2cdetect -y 1` | Enable I2C in `raspi-config` |
| Bluetooth OBD fail | `bluetoothctl devices` | Pair dongle, check `rfcomm` |
| Ollama unreachable | `curl http://10.27.27.100:11434/` | Check WiFi, check Chi-Srv-01 |
| Service won't start | `journalctl -u eclipse-obd -n 50` | Check .env, venv, permissions |
| Permission denied | `ls -la /dev/i2c-1` | Add user to `i2c`, `gpio` groups |
| pip install fails | Check `requirements-pi.txt` | Some packages need system libs (`apt install`) |

## Coding Standards

Same as the main project -- see `specs/standards.md`:

- **camelCase** for functions/variables
- **PascalCase** for classes
- **UPPER_SNAKE_CASE** for constants
- Standard file headers required
- Google-style docstrings on public functions
- Type hints on all public functions

## Hardware-Specific Patterns

### Import guards for Pi-only libraries

```python
try:
    import board
    from adafruit_rgb_display import st7789
    DISPLAY_AVAILABLE = True
except (ImportError, NotImplementedError, RuntimeError):
    DISPLAY_AVAILABLE = False
```

### Lazy hardware initialization

```python
def __init__(self, config):
    self._config = config
    self._i2cClient = None  # Lazy init

def _ensureInitialized(self):
    if self._i2cClient is None:
        self._i2cClient = I2cClient(self._config['bus'])
```

### I2C error handling

```python
NO_RETRY_ERRNOS = {6, 19, 121}  # Device not present
try:
    return self._bus.read_byte_data(address, register)
except OSError as e:
    if e.errno in NO_RETRY_ERRNOS:
        raise I2cDeviceNotFoundError(f"No device at 0x{address:02X}")
    raise I2cCommunicationError(str(e))  # Retryable
```

### GPIO button setup

```python
from gpiozero import Button
button = Button(pin=17, pull_up=True, bounce_time=0.2, hold_time=3.0)
button.when_held = onLongPress
button.when_released = onShortPress
```

### Pygame display (HDMI, not SPI)

```python
import pygame
pygame.init()
screen = pygame.display.set_mode((480, 320), pygame.NOFRAME)
pygame.mouse.set_visible(False)
```

### Path resolution (critical for systemd)

```python
srcPath = Path(__file__).resolve().parent
projectRoot = srcPath.parent
DEFAULT_CONFIG = str(srcPath / 'obd_config.json')
```

## Configuration

The Pi uses the same `src/obd_config.json` as the dev machine. Secrets differ via `.env`:

```bash
# Pi .env (differs from dev machine)
OLLAMA_BASE_URL=http://10.27.27.100:11434
DB_PASSWORD=...
```

Config is resolved at runtime: `${ENV_VAR:default}` placeholders in `obd_config.json` are substituted by `src/common/secrets_loader.py`.

## Network Topology

```
Pi (10.27.27.28) ---WiFi---> Router (DeathStarWiFi)
                                |
Chi-Srv-01 (10.27.27.100) -----+  (Ollama on :11434)
OBD-II Dongle --- Bluetooth --> Pi
```

## Testing on Pi

Tests can run on the Pi but hardware-dependent tests need real hardware:

```bash
# Run all tests (mocked hardware)
python -m pytest tests/ -v

# Skip slow tests
python -m pytest tests/ -v -m "not slow"

# Run specific hardware test
python -m pytest tests/test_hardware_manager.py -v
```

## Files to Reference

| File | Purpose |
|------|---------|
| `ralph/agent-pi.md` | This file (Pi agent instructions) |
| `ralph/agent.md` | Windows/Ralph agent instructions |
| `specs/standards.md` | Coding conventions |
| `specs/architecture.md` | System design |
| `deploy/deploy.conf` | Pi SSH connection config |
| `scripts/deploy.sh` | Deploy script |
| `scripts/pi_setup.sh` | First-time Pi setup |
| `src/obd_config.json` | Application config |
| `requirements-pi.txt` | Pi-specific Python dependencies |

## Safety Guidelines

1. **Never run Ollama locally on the Pi** -- always use remote Chi-Srv-01
2. **Never force push** -- especially to main
3. **Test with --dry-run first** before live runs
4. **Back up the SQLite database** before schema changes
5. **Check service logs** after any deploy
6. **Use deploy/deploy.conf** for SSH config, never hardcode IPs

## Git Branch

The project uses `main` as the primary branch. Follow the sprint branching strategy from `ralph/agent.md` when making code changes.

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-31 | M. Cornelison | Initial creation -- Pi 5 developer agent knowledge base |
