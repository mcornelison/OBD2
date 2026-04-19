# Eclipse OBD-II Testing Guide

## Overview

This document provides comprehensive testing procedures for the Eclipse OBD-II Performance Monitoring System. It covers both automated testing via pytest and manual end-to-end testing in simulator mode.

**Last Updated**: 2026-01-23

---

## Quick Start

### Running Unit Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run fast tests only (skip slow tests)
pytest tests/ -v -m "not slow"

# Run a specific test file
pytest tests/test_orchestrator.py -v

# Run integration tests only
pytest tests/test_orchestrator_integration.py -v
```

### Running the Simulator

```bash
# Start application in simulator mode
python src/pi/main.py --simulate --config src/obd_config.json

# Start with verbose logging
python src/pi/main.py --simulate --verbose --config src/obd_config.json

# Dry-run (validate config only)
python src/pi/main.py --dry-run --config src/obd_config.json
```

---

## End-to-End Simulator Test Procedure

This procedure verifies the complete application works correctly in simulator mode before deploying to hardware.

### Prerequisites

1. Python 3.11+ installed
2. Virtual environment activated
3. Dependencies installed (`pip install -r requirements.txt`)
4. Configuration file exists (`src/obd_config.json`)

### Test Steps

#### Step 1: Validate Configuration

```bash
# Verify config is valid
python src/pi/main.py --dry-run --config src/obd_config.json
```

**Expected Result**:
- Output shows "DRY RUN MODE - Validating config without starting orchestrator"
- Output shows "Configuration is valid"
- Exit code 0

#### Step 2: Start Simulator

```bash
# Start in simulator mode with verbose logging
python src/pi/main.py --simulate --verbose --config src/obd_config.json
```

**Expected Output**:
```
============================================================
Application starting...
*** Running in SIMULATION MODE ***
============================================================
Configuration loaded from src/obd_config.json
Starting workflow...
Starting ApplicationOrchestrator...
Starting database...
Database started successfully
Starting profileManager...
ProfileManager started successfully
Starting connection...
Connecting to simulated OBD-II | delay=2.0s
Connected to simulated OBD-II
Connection started successfully
[... additional component initialization ...]
ApplicationOrchestrator started successfully | startup_time=X.XXs
Entering main application loop | health_check_interval=60.0s
Data logger started
Drive detector started
```

#### Step 3: Verify Health Checks (Wait 60 seconds)

**Expected Output** (every 60 seconds):
```
HEALTH CHECK | connection=connected | data_rate=X.X/min | readings=XXX | errors=0 | drives=0 | alerts=0 | uptime=60s
```

**Verify**:
- [ ] `connection=connected` - Simulated connection is active
- [ ] `data_rate` > 0 - Data is being polled
- [ ] `readings` increasing - Records being logged
- [ ] `errors=0` - No errors during operation

#### Step 4: Verify Data Logging Rate (Wait 5 minutes)

**Expected Output** (every 5 minutes):
```
DATA LOGGING RATE | records/min=X.X | total_logged=XXXX | period_minutes=5.0
```

**Verify**:
- [ ] Records are being logged to database
- [ ] Rate is consistent with configured polling interval

#### Step 5: Verify Drive Detection

The simulator starts at idle RPM (~800 RPM). To trigger drive detection, the RPM must exceed the threshold (default 500 RPM) for the configured duration (default 10 seconds).

Since the simulated engine starts at idle, drive detection should NOT trigger automatically. The simulator maintains a realistic idle state.

**To simulate a drive** (if simulator CLI is enabled):
- Press 't' to increase throttle (increases RPM)
- Press 's' to view status
- Wait for drive start detection

**Expected Output on Drive Start**:
```
Drive started | session_id=XXXXXXXX
```

**Expected Output on Drive End** (when RPM returns to 0 for 60 seconds):
```
Drive ended | duration=XX.Xs
Statistical analysis completed
```

#### Step 6: Graceful Shutdown (Press Ctrl+C)

**Expected Output**:
```
Received signal SIGINT, initiating shutdown
Stopping ApplicationOrchestrator...
Stopping dataLogger...
dataLogger stopped successfully
Stopping statisticsEngine...
statisticsEngine stopped successfully
[... additional component shutdown ...]
Stopping database...
Database stopped successfully
ApplicationOrchestrator stopped | shutdown_time=X.XXs | exit_code=0
Workflow completed
============================================================
Application finished
============================================================
```

**Verify**:
- [ ] All components shut down in reverse order
- [ ] Exit code is 0 (clean shutdown)
- [ ] No error messages during shutdown

#### Step 7: Verify Database Records

After shutdown, verify the database contains expected records:

```bash
# Connect to database and check records
python -c "
import sqlite3
db_path = './data/obd.db'  # Or your configured path
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check realtime_data table
cursor.execute('SELECT COUNT(*) FROM realtime_data')
readings = cursor.fetchone()[0]
print(f'Realtime Data Records: {readings}')

# Check profiles table
cursor.execute('SELECT COUNT(*) FROM profiles')
profiles = cursor.fetchone()[0]
print(f'Profiles: {profiles}')

# Sample recent readings
cursor.execute('SELECT parameter_name, value, timestamp FROM realtime_data ORDER BY timestamp DESC LIMIT 10')
print('\\nRecent Readings:')
for row in cursor.fetchall():
    print(f'  {row[0]:20}: {row[1]:>10.2f} at {row[2]}')

conn.close()
"
```

**Expected**:
- [ ] `realtime_data` table has records
- [ ] `profiles` table has profile entries
- [ ] Records have realistic timestamps and values

---

## Extended Test: 5-Minute Continuous Run

This test verifies the application runs stably for an extended period without memory leaks or errors.

### Procedure

1. **Start the simulator**:
   ```bash
   python src/pi/main.py --simulate --verbose --config src/obd_config.json
   ```

2. **Let it run for 5 minutes** (300 seconds)

3. **Monitor during operation**:
   - Watch for any ERROR or WARNING messages
   - Observe health checks every 60 seconds
   - Verify data logging rate every 5 minutes

4. **After 5 minutes**, press Ctrl+C for graceful shutdown

5. **Verify results**:
   - [ ] No ERROR messages in logs
   - [ ] At least 5 health checks completed (one per minute)
   - [ ] At least 1 data logging rate report
   - [ ] Clean shutdown with exit code 0
   - [ ] Database contains recorded data

### Success Criteria

| Metric | Expected Value |
|--------|----------------|
| Runtime | 300+ seconds |
| Errors in log | 0 |
| Health checks | 5+ |
| Data rate reports | 1+ |
| Exit code | 0 |
| Database records | Hundreds (depending on polling interval) |

---

## Alert Testing

To test the alert system, you need to trigger threshold violations.

### Using Custom Test Configuration

Create a test config with low thresholds:

```json
{
  "profiles": {
    "activeProfile": "test",
    "availableProfiles": [
      {
        "id": "test",
        "name": "Test Profile",
        "alertThresholds": {
          "rpmRedline": 1000,
          "coolantTempCritical": 30
        }
      }
    ]
  }
}
```

### Expected Alert Output

```
ALERT triggered | type=rpm_redline | param=RPM | value=1200 | threshold=1000 | profile=test
```

---

## Statistics Engine Testing

Statistics are calculated after a drive ends. The drive detection requires:

1. **Drive Start**: RPM > 500 for 10+ seconds (configurable)
2. **Drive End**: RPM = 0 for 60+ seconds (configurable)

### Quick Test Configuration

For faster testing, modify `src/obd_config.json`:

```json
{
  "analysis": {
    "driveStartRpmThreshold": 500,
    "driveStartDurationSeconds": 1,
    "driveEndRpmThreshold": 100,
    "driveEndDurationSeconds": 5,
    "calculateStatistics": ["max", "min", "avg"]
  }
}
```

---

## Integration Test Suite

The project includes comprehensive integration tests that verify orchestrator behavior:

```bash
# Run integration tests
pytest tests/test_orchestrator_integration.py -v

# Run with timeout limit
pytest tests/test_orchestrator_integration.py -v --timeout=120
```

### Test Coverage

| Test Class | Description |
|------------|-------------|
| `TestOrchestratorStartsInSimulatorMode` | Verifies startup in simulator mode |
| `TestOrchestratorStopsGracefully` | Verifies graceful shutdown |
| `TestDataLoggingDuringSimulatedDrive` | Verifies data logging to database |
| `TestDriveDetectionOnRpmChanges` | Verifies drive detection triggers |
| `TestStatisticsAfterDriveEnd` | Verifies statistics calculation |
| `TestAlertTriggersOnThresholdViolation` | Verifies alert system |
| `TestTemporaryDatabaseUsage` | Verifies temp DB isolation |
| `TestCompletionWithinTimeLimit` | Verifies tests complete quickly |

---

## Troubleshooting

### Application Won't Start

**Symptom**: Error on startup
**Common Causes**:
- Missing configuration file
- Invalid configuration syntax
- Missing environment variables
- Database path not writable

**Solution**:
```bash
# Validate config first
python src/pi/main.py --dry-run --config src/obd_config.json

# Check for missing env vars
cat .env
```

### No Data Being Logged

**Symptom**: `data_rate=0.0/min` in health check
**Common Causes**:
- Connection not established
- Data logger not started
- No parameters configured

**Solution**:
- Check `connection=connected` in health check
- Verify `realtimeData.parameters` in config has entries
- Enable verbose logging (`--verbose`)

### Drive Detection Not Triggering

**Symptom**: `drives=0` even after running for a while
**Explanation**: In simulator mode, the engine idles at ~800 RPM. This is above the default threshold (500 RPM) but the simulator starts in idle state without throttle.

**Solution**:
- Lower `driveStartRpmThreshold` below idle RPM for testing
- Or use simulator CLI to increase throttle

### High Memory Usage Over Time

**Symptom**: Memory grows continuously
**Solution**:
- Check for unbounded list growth in logs
- The orchestrator uses fixed-size counters, not lists
- Run with profiler if issue persists

---

## Performance Benchmarks

| Metric | Target | Notes |
|--------|--------|-------|
| Startup time | < 10 seconds | In simulator mode |
| Shutdown time | < 5 seconds | Graceful shutdown |
| Memory usage | < 100 MB | Stable over time |
| CPU usage (idle) | < 5% | When polling at 1 Hz |
| Data rate | Matches polling interval | e.g., 60/min at 1 Hz |

---

## Test Automation Script

For automated testing, use this script:

```bash
#!/bin/bash
# scripts/run_e2e_test.sh

echo "Starting E2E Simulator Test..."

# Run in background, capture PID
python src/pi/main.py --simulate --verbose --config src/obd_config.json &
PID=$!

# Wait 5 minutes
echo "Running for 5 minutes (PID: $PID)..."
sleep 300

# Send SIGINT for graceful shutdown
echo "Sending shutdown signal..."
kill -SIGINT $PID

# Wait for shutdown
wait $PID
EXIT_CODE=$?

echo "Exit code: $EXIT_CODE"

# Verify exit code
if [ $EXIT_CODE -eq 0 ]; then
    echo "TEST PASSED: Clean shutdown"
else
    echo "TEST FAILED: Non-zero exit code"
fi

exit $EXIT_CODE
```

Make executable: `chmod +x scripts/run_e2e_test.sh`

---

## Manual Pi -> Server Sync (Walk phase)

Once `sprint/pi-walk` is deployed and the Pi is on `DeathStarWiFi`, the CIO
can manually push Pi delta rows to Chi-Srv-01 with `scripts/sync_now.py`.
Auto-sync on WiFi return is Run-phase scope; this CLI is the Walk-phase
trigger.

### Prerequisites
- `COMPANION_API_KEY` set in the Pi's `.env` (must match server-side key).
- `pi.companionService.enabled=true` in `config.json` (default).
- Pi can reach `chi-srv-01:8000`.

### Normal invocation

On the Pi:

```bash
cd /home/mcornelison/Projects/Eclipse-01
~/obd2-venv/bin/python scripts/sync_now.py
```

Expected output shape:

```
Sync started: 2026-04-18 14:32:05
Config: baseUrl=http://10.27.27.120:8000, batchSize=500

alert_log                 0 new rows -> nothing to sync
calibration_sessions      0 new rows -> nothing to sync
realtime_data           247 new rows -> pushed -> accepted (batch: chi-eclipse-01-2026-04-18T14:32:06Z)
statistics               12 new rows -> pushed -> accepted (batch: chi-eclipse-01-2026-04-18T14:32:06Z)
...

Total: 259 rows pushed across 2 tables
Elapsed: 1.8s
Status: OK
```

Exit code `0` = all pushes succeeded (including `Nothing to sync` across the
board). Exit code `1` = at least one table failed (server unreachable, 5xx,
auth bad, etc.).

### Dry run (no HTTP)

```bash
~/obd2-venv/bin/python scripts/sync_now.py --dry-run
```

Prints the pending delta count per table without touching the network. Useful
before a real push to see what's queued up.

### Invariants
- A failed push never advances `sync_log.last_synced_id` (US-149 invariant).
  Re-run `sync_now.py` once the server is reachable again -- the same rows
  get re-sent.
- The API key never appears in stdout.
- No scheduling is built in. Run it when you want a sync.

---

## Walk-Phase End-to-End Validation (US-166 sprint exit)

Sprint 11's exit criterion is a manual end-to-end run proving simulator
data flows Pi -> Chi-Srv-01 -> analytics, with row counts matching exactly
across layers.  Two artifacts make this observable:

1. **`tests/integration/test_pi_to_server_e2e.py`** -- CI-friendly.  Spins
   up a stdlib `ThreadingHTTPServer` mocking `/api/v1/sync`, seeds a temp
   Pi SQLite, drives `SyncClient` (and `scripts/sync_now.py`) against it,
   and asserts rows arrive + high-water marks advance + a second push is
   empty.  Runs as part of `pytest tests/` on every commit.
2. **`scripts/validate_pi_to_server.sh`** -- the CIO-runnable live driver.
   Executes the 7-step protocol from spec 2.5 against the real Pi and
   server, prints PASS/FAIL per step + an overall summary.  Run it on
   bench hardware with both machines live; the row-count assertions are
   against live MariaDB, not a mock.

### Running the CI test locally

```bash
pytest tests/integration/test_pi_to_server_e2e.py -v
```

No Pi, no server, no network access required -- the mock server binds to
`127.0.0.1` on an ephemeral port.  Expected: 6 tests pass in ~30s.

### Running the live validation driver

```bash
# Default: 60s simulator run on the Pi, then full 7-step validation.
bash scripts/validate_pi_to_server.sh

# Shorter simulator run (for quicker iteration during investigation).
bash scripts/validate_pi_to_server.sh --duration 30

# Skip the simulator step entirely and validate whatever is already on
# the Pi.  Useful if a previous run already seeded the DB.
bash scripts/validate_pi_to_server.sh --skip-simulator

# Print the plan without touching anything.
bash scripts/validate_pi_to_server.sh --dry-run
```

Prerequisites:

- Key-based SSH works: `ssh mcornelison@10.27.27.28 hostname` and
  `ssh mcornelison@10.27.27.120 hostname` both return cleanly.
- `COMPANION_API_KEY` present in the Pi `.env` and matches the server
  `.env` `API_KEY` (or whichever var the server uses).
- Chi-Srv-01:8000 reachable from the Pi network-wise.
- Server `.env` has working `MYSQL_*` credentials; the server venv has
  `mysql-connector-python` installed (the driver uses it to count rows).

### What each step proves

| Step | Proves |
|---|---|
| 1 | Simulator boots on ARM and runs a drive cycle end-to-end |
| 2 | Drive data was captured in the Pi's local SQLite |
| 3 | `scripts/sync_now.py` pushes to the server without error |
| 4 | MariaDB row counts match (or exceed) what the Pi sent |
| 5 | Server CLI `report.py --drive latest` renders against the new data |
| 6 | Report output is non-empty and references a real drive |
| 7 | Display `Sync` indicator flipped green (CIO visual, cannot be automated remotely) |

If any step FAILs, the driver prints the exact reason and exits 1.  The
broken layer should be identifiable from the step number alone:

- Step 1-2 FAIL -> Pi-side simulator or SQLite write path
- Step 3 FAIL -> `SyncClient` or companion-service config / auth
- Step 4 FAIL -> server `/api/v1/sync` endpoint or MariaDB upsert
- Step 5-6 FAIL -> server analytics (`scripts/report.py`)
- Step 7 FAIL -> display rendering of sync status

### Invariants worth re-reading before a live run

- A failed push must NOT advance `sync_log.last_synced_id` (US-149).  If
  the live run hits step 3 FAIL, re-run once the server is reachable --
  the same rows get re-sent without intervention.
- Row counts must match *exactly* (Pi sends N, server stores N).  Any
  mismatch is a real bug, not a rounding artifact.
- The API key must never appear in stdout.  Both the CLI and the driver
  take care to never print the key; don't edit either to add a "for
  debugging" echo.

## HDMI Render Validation (US-183 — Pi Polish)

The OSOYOO 3.5" HDMI display on chi-eclipse-01 is the primary glance
surface while driving. US-183 adds a CIO-runnable driver that exercises
the full pygame render path on the physical hardware and asks the CIO to
eyeball a short live session before declaring the display tier healthy.

### What you're validating

- `pygame.display.init()` and `pygame.display.set_mode((480, 320))` succeed
  against the real Pi 5 framebuffer with the OSOYOO HDMI display attached.
- `primary_renderer.renderPrimaryScreen()` draws the basic-tier screen
  without tearing or clipping at native 480x320.
- The render loop does not stall — a scripted RPM sweep (800 -> 6500 ->
  800 over ~4s) is the heartbeat signal.
- The harness exits cleanly on SIGTERM / duration-elapsed and blanks the
  display (no frozen last frame, no visible glitch).

### How to run it

```bash
# From the Windows dev box (runs SSH-based driver against chi-eclipse-01)
bash scripts/validate_hdmi_display.sh                  # 30s render
bash scripts/validate_hdmi_display.sh --duration 60    # longer eyeball window
bash scripts/validate_hdmi_display.sh --snapshot /tmp/hdmi.png
bash scripts/validate_hdmi_display.sh --dry-run        # print plan, no SSH
```

The driver walks through 7 steps:

| Step | Proves |
|---|---|
| 1 | SSH key-based auth to the Pi works |
| 2 | Pi firmware sees an HDMI display attached (`tvservice` / `drm_info`) |
| 3 | `pygame.display.set_mode((480, 320))` succeeds on the Pi |
| 4 | `render_primary_screen_live.py` runs for N seconds and exits 0 |
| 5 | (manual) CIO confirms 480x320 render, text readable, no clipping |
| 6 | (manual) CIO confirms RPM gauge animates (not frozen) |
| 7 | (manual) CIO confirms display is black after clean exit |

Steps 1-4 are programmatic and fail fast with a diagnosable reason. Steps
5-7 require the CIO to physically walk up to the display. Mark US-183
`passes: true` only after all three manual steps are visually confirmed.

### Running just the live harness (no SSH wrapper)

On the Pi (after SSH in), you can drive the pygame harness directly:

```bash
# Borderless kiosk-mode full-screen render for 30s
~/obd2-venv/bin/python scripts/render_primary_screen_live.py

# Custom duration + snapshot the final frame
~/obd2-venv/bin/python scripts/render_primary_screen_live.py \
    --duration 60 --snapshot /tmp/hdmi_final.png

# Windowed (non-kiosk) for desktop debugging
~/obd2-venv/bin/python scripts/render_primary_screen_live.py --windowed
```

Ctrl+C or SIGTERM during the run is expected to blank the display and
exit 0 (no traceback).

### Off-Pi test coverage

`tests/pi/display/test_hdmi_render.py` has two sets of tests:

- **Off-Pi smoke** (runs on Windows + CI under `SDL_VIDEODRIVER=dummy`):
  proves `renderPrimaryScreen` handles a 480x320 offscreen surface, draws
  non-background pixels, and is loop-stable across 10 refreshes.
- **`pi_only`** (auto-skipped off-Pi; opt in with `ECLIPSE_PI_HOST=1`):
  proves `pygame.display.init()` + `set_mode((480, 320))` succeed on the
  real framebuffer and that `renderPrimaryScreen` can draw onto the live
  display surface without raising. These give the CI a sanity floor; they
  do NOT replace the CIO's eyeball confirmation.

### Known-issue log

If the bash driver reports step 2 FAIL but step 3 PASS, the firmware-probe
heuristic missed something harmless (Pi 5 `drm_info` is optional). The
authoritative signal is step 3 — `pygame.display.set_mode` is what the app
actually uses.

If step 4 hangs, SIGTERM the ssh session. `render_primary_screen_live.py`
installs SIGTERM / SIGINT handlers that set an exit flag on the next
frame, so it should clean up within ~100ms.

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-04-18 | Rex (Ralph) | Added HDMI Render Validation section for US-183 |
| 2026-04-18 | Rex (Ralph) | Added Walk-Phase End-to-End Validation section for US-166 |
| 2026-04-18 | Rex (Ralph) | Added Manual Pi -> Server Sync section for US-154 |
| 2026-01-23 | Ralph Agent | Initial testing guide for US-OSC-020 |
