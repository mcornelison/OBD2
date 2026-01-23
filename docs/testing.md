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
python src/main.py --simulate --config src/obd_config.json

# Start with verbose logging
python src/main.py --simulate --verbose --config src/obd_config.json

# Dry-run (validate config only)
python src/main.py --dry-run --config src/obd_config.json
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
python src/main.py --dry-run --config src/obd_config.json
```

**Expected Result**:
- Output shows "DRY RUN MODE - Validating config without starting orchestrator"
- Output shows "Configuration is valid"
- Exit code 0

#### Step 2: Start Simulator

```bash
# Start in simulator mode with verbose logging
python src/main.py --simulate --verbose --config src/obd_config.json
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
   python src/main.py --simulate --verbose --config src/obd_config.json
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
python src/main.py --dry-run --config src/obd_config.json

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
python src/main.py --simulate --verbose --config src/obd_config.json &
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

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-23 | Ralph Agent | Initial testing guide for US-OSC-020 |
