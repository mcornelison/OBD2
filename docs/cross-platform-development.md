# Cross-Platform Development Guide

## Overview

This document covers the considerations and setup for developing on Windows while deploying to Raspberry Pi 5 for the Eclipse OBD-II Performance Monitoring System.

**Last Updated**: 2026-01-23

---

## Platform Summary

| Environment | Platform | Purpose |
|-------------|----------|---------|
| Development | Windows 10/11 | Code editing, testing, simulation |
| Production | Raspberry Pi 5 (Linux) | Real OBD-II hardware, display, GPIO |

---

## SQLite Database

### Portability

SQLite database files are **fully portable** between Windows and Linux:

- Same binary format on both platforms
- No conversion needed when transferring
- WAL mode works identically on both

### Database Location

```
project/data/
├── obd.db        # Main database file (portable)
├── obd.db-wal    # Write-ahead log (created during writes)
└── obd.db-shm    # Shared memory file (created during writes)
```

### Why SQLite for Raspberry Pi

| Factor | SQLite | Flat Files |
|--------|--------|------------|
| Analytics queries | Native SQL aggregations | Must load entire file |
| Filtering by date/profile | Indexed lookups (ms) | Full file scan |
| Concurrent access | WAL mode handles it | Manual locking |
| Data integrity | ACID, FK constraints | None |
| Memory footprint | Queries load needed rows | Parse entire file |
| Pi 5 suitability | Designed for embedded | Works but inefficient |

---

## File Path Handling

### The Problem

| Platform | Path Separator | Case Sensitivity |
|----------|---------------|------------------|
| Windows | `\` backslash | Case-insensitive |
| Linux | `/` forward slash | Case-sensitive |

### The Solution

Always use `pathlib` or `os.path.join()`:

```python
# BAD - Windows only
path = 'data\\obd.db'
path = 'src\\obd\\config.json'

# GOOD - Cross-platform
from pathlib import Path
path = Path('data') / 'obd.db'

# Also good
import os
path = os.path.join('data', 'obd.db')
```

---

## Line Endings

### Shell Scripts (Critical)

Shell scripts **must** use LF (Unix) line endings to run on Linux. The `.gitattributes` file enforces this:

```gitattributes
# Shell scripts must use LF
*.sh text eol=lf

# Python files - normalize to LF
*.py text eol=lf
```

### CSV Files

Always use `newline=''` when writing CSV files to prevent extra blank lines on Windows:

```python
# GOOD - Works on both platforms
with open('data.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['col1', 'col2'])
```

---

## Hardware Dependencies

### Pi-Only Libraries

These libraries only work on Raspberry Pi:

| Library | Purpose | Windows Behavior |
|---------|---------|------------------|
| `RPi.GPIO` | GPIO pin control | ImportError |
| `board` | Adafruit pin definitions | NotImplementedError |
| `adafruit_rgb_display` | Display driver | ImportError |
| `smbus2` | I2C communication | ImportError |
| `obd` | OBD-II communication | Works but no hardware |

### Graceful Degradation Pattern

Always wrap hardware imports in try/except:

```python
try:
    import board
    from adafruit_rgb_display import st7789
    DISPLAY_AVAILABLE = True
except (ImportError, NotImplementedError, RuntimeError):
    DISPLAY_AVAILABLE = False
    board = None
    st7789 = None
```

---

## Dependencies

### Development (Windows)

```bash
# Core dependencies
pip install -r requirements.txt

# Contains:
# - python-dotenv
# - pydantic
# - pytest, pytest-cov, pytest-mock
```

### Production (Raspberry Pi)

```bash
# Core + Pi-specific dependencies
pip install -r requirements.txt
pip install -r requirements-pi.txt

# requirements-pi.txt contains:
# - obd (OBD-II library)
# - RPi.GPIO
# - adafruit-circuitpython-rgb-display
# - adafruit-blinka
# - Pillow
```

---

## Development Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    WINDOWS (Development)                     │
├─────────────────────────────────────────────────────────────┤
│  1. Write code in your preferred IDE                        │
│  2. Run tests: pytest tests/                                │
│  3. Use simulator: python src/main.py --simulate            │
│  4. Database works identically to production                │
│  5. Hardware features gracefully disabled                   │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ git push / rsync / scp
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                 RASPBERRY PI 5 (Production)                  │
├─────────────────────────────────────────────────────────────┤
│  1. Clone/pull repository                                   │
│  2. pip install -r requirements.txt                         │
│  3. pip install -r requirements-pi.txt                      │
│  4. Copy data/obd.db or initialize fresh                    │
│  5. Run: python src/main.py                                 │
│  6. Hardware features fully available                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Simulator Mode

When developing on Windows without OBD-II hardware:

```bash
# Run with simulated OBD-II data
python src/main.py --simulate

# With verbose output
python src/main.py --simulate --verbose
```

The simulator provides:
- Realistic sensor value generation
- Drive scenarios (cold start, city, highway)
- Failure injection for testing error handling
- No hardware required

---

## Deployment to Raspberry Pi

### Option 1: Git Clone

```bash
# On Raspberry Pi
git clone <repository-url>
cd OBD2v2
pip install -r requirements.txt
pip install -r requirements-pi.txt
python src/main.py
```

### Option 2: rsync (Faster Updates)

```bash
# From Windows (Git Bash or WSL)
rsync -avz --exclude '.venv' --exclude '__pycache__' \
    /path/to/OBD2v2/ pi@raspberrypi:/home/pi/OBD2v2/
```

### Option 3: Copy Database Only

```bash
# Copy just the database to Pi
scp data/obd.db pi@raspberrypi:/home/pi/OBD2v2/data/
```

---

## Verifying Setup

Run the platform check script on any platform:

```bash
python scripts/check_platform.py
```

This verifies:
- Platform detection (Windows/Linux/Pi)
- Core dependencies installed
- Hardware dependencies (Pi only)
- Project structure intact
- Database connectivity

---

## Troubleshooting

### Shell Script Won't Run on Pi

**Symptom**: `/bin/bash^M: bad interpreter`

**Cause**: Windows CRLF line endings

**Fix**:
```bash
# On Pi
sed -i 's/\r$//' script.sh
# Or ensure .gitattributes is in place before cloning
```

### Database Locked Errors

**Symptom**: `database is locked` errors

**Cause**: Multiple processes accessing without WAL mode

**Fix**: Ensure WAL mode is enabled:
```python
db = ObdDatabase('./data/obd.db', walMode=True)
```

### Import Errors for Hardware Libraries

**Symptom**: `ModuleNotFoundError: No module named 'RPi'`

**Cause**: Running on Windows or Pi dependencies not installed

**Fix**:
- On Windows: Use simulator mode
- On Pi: `pip install -r requirements-pi.txt`

### Case Sensitivity Issues

**Symptom**: `ModuleNotFoundError` on Pi but works on Windows

**Cause**: File/folder case mismatch (Windows is case-insensitive)

**Fix**: Ensure import statements match exact file names:
```python
# If file is ConfigValidator.py
from ConfigValidator import ConfigValidator  # Correct
from configvalidator import ConfigValidator  # Fails on Linux
```

---

## File Reference

| File | Purpose |
|------|---------|
| `.gitattributes` | Line ending normalization |
| `requirements.txt` | Core/dev dependencies |
| `requirements-pi.txt` | Raspberry Pi production dependencies |
| `scripts/check_platform.py` | Platform verification script |
| `data/obd.db` | SQLite database (portable) |

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-23 | Claude | Initial cross-platform development guide |
