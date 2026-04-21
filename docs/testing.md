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

## Server Schema Migration Runbook (CIO-facing, US-209)

Sprint 15 ships `scripts/apply_server_migrations.py` to close the live-MariaDB
gap left by US-195 (`data_source`) and US-200 (`drive_id`, `drive_counter`).
CI tested against ephemeral SQLite, so the server MariaDB was never `ALTER`ed
to match the SQLAlchemy models. This runbook explains how to apply the
catchup safely; re-run any time after a schema-changing sprint ships.

### Safety posture

The script has **two modes**, gated by a dry-run sentinel file:

- `--dry-run` probes `INFORMATION_SCHEMA` on the live DB, builds the migration
  plan, writes `.us209-dry-run-ok` in the repo root, and exits 0. No DB
  mutations, no backups.
- `--execute` refuses to run without the sentinel, backs up affected tables
  via `mysqldump --single-transaction` **before** any DDL, runs the plan with
  per-statement timing guards (30s max per `ALTER`, 60s + 500 MB ceiling on
  the backup), and re-scans at the end to verify the plan is empty.
- **Idempotent**: re-running `--execute` on an already-migrated DB emits
  zero DDL statements and exits 0.

DDL in MariaDB is implicit-commit (no transactional rollback on mid-plan
failure), so on failure the operator restores from the dump:
`ssh $SERVER_USER@$SERVER_HOST "mysql obd2db < /tmp/obd2-migration-backup-<ts>.sql"`.

### Procedure

```bash
# 1. Scan state and build the migration plan. No mutations.
python scripts/apply_server_migrations.py --dry-run

#    Read the printed plan. Expected statements on the first US-209 run:
#    - ADD COLUMN data_source on realtime_data / connection_log / statistics / profiles / calibration_sessions
#    - ADD COLUMN drive_id on realtime_data / connection_log / statistics / alert_log
#    - ADD INDEX IX_<t>_drive_id (one per drive_id table)
#    - CREATE TABLE drive_counter + seed singleton (id=1, last_drive_id=0)

# 2. Apply the plan. Sentinel gate blocks this if you skip the dry-run above.
python scripts/apply_server_migrations.py --execute

#    Script output:
#      [backup] server -> /tmp/obd2-migration-backup-<ts>.sql
#      [applied +X.XXs] <ddl>
#      [applied +X.XXs] <ddl>
#      ...
#      [execute] verified: server schema now matches Pi-side shape

# 3. Manually verify with a direct DESCRIBE (independent of the script).
ssh mcornelison@10.27.27.10 "mysql obd2db -e 'DESCRIBE realtime_data; DESCRIBE connection_log; DESCRIBE statistics; DESCRIBE alert_log; SHOW CREATE TABLE drive_counter;'"

# 4. Idempotency check: a second --execute should emit zero DDL.
python scripts/apply_server_migrations.py --dry-run
python scripts/apply_server_migrations.py --execute
# Expected: "[execute] plan is empty -- nothing to do (idempotent no-op)"
```

### Rollback (if something goes wrong mid-plan)

The backup path printed during `--execute` is the authoritative restore
source. MariaDB DDL is implicit-commit so ALTER TABLE cannot be rolled back
transactionally; the operator must replay the dump:

```bash
ssh mcornelison@chi-srv-01
mysql obd2db < /tmp/obd2-migration-backup-<ts>.sql
```

The dump uses `--single-transaction` so it is point-in-time consistent
without locking writes during the backup.

### Post-migration follow-up

`TD-029` (`offices/pm/tech_debt/`) documents the underlying deploy-flow
gap: SQLAlchemy model changes need a first-class migration mechanism so
this gap does not recur on every new schema-adding sprint. Recommended
Sprint 16+ fix: add a `deploy/migrations/` directory with timestamped SQL
files and a `_schema_migrations` bookkeeping table, applied by
`deploy-server.sh` between `git pull` and service restart.

## Deploy-Time API Key Bake-In (CIO-facing, US-201)

The Pi and server authenticate each other via a shared 64-hex `API_KEY`
(server side) / `COMPANION_API_KEY` (Pi side). US-201 wires generation
and placement into the `--init` path of both deploy scripts so a fresh
install requires zero manual `.env` editing.

### Fresh pairing (Pi + server both new)

```bash
# 1. On your workstation, set up the server first.
bash deploy/deploy-server.sh --init
#   -> At the API_KEY prompt: choose [g] to generate a fresh key.
#   -> The key is written to $PROJECT/.env on chi-srv-01 with chmod 600.
#   -> The key is NEVER echoed to your terminal.

# 2. Capture the server-side key so you can paste it into the Pi.
#    (One-time; this is the only time the key appears on stdout.)
ssh mcornelison@chi-srv-01 "grep '^API_KEY=' /mnt/projects/O/OBD2v2/.env"

# 3. Initialize the Pi.
bash deploy/deploy-pi.sh --init
#   -> At the COMPANION_API_KEY prompt: choose [p] (paste existing).
#   -> Paste the value from step 2 (paste input is hidden from terminal).
#   -> The Pi's .env now matches the server; sync push is wired end-to-end.
```

### Idempotent re-init

Running `--init` again on either side is safe: when a key already
exists, the prompt is skipped entirely (no accidental rotation that
would break the paired peer).

### Helper utility

`scripts/generate_api_key.sh` is a thin wrapper around
`openssl rand -hex 32`. Prints 64 hex characters to stdout. Used by
the deploy scripts' `--init` path and available standalone for manual
workflows:

```bash
bash scripts/generate_api_key.sh > /tmp/fresh.key   # capture to file
```

### B-044 Address Audit (Companion CIO Workflow)

Whenever you change an infrastructure address (IP, hostname, port, MAC),
run the audit to ensure no literal leaked into non-config files:

```bash
make lint-addresses             # runs scripts/audit_config_literals.sh
pytest tests/lint/ -v           # same check as part of the fast suite
```

Update `config.json pi.network.*` / `server.network.*` AND
`deploy/addresses.sh` together — they are the two canonical surfaces
(Python-side and bash-side) per specs/architecture.md §6 B-044.

---

## First Real Drive Validation (CIO-facing, US-208)

After Sprint 14 + 15, the Pi captures a much richer surface per drive:
canonical UTC-ISO timestamps (US-202), `drive_id` inheritance (US-200),
`data_source` tagging (US-195), 21+ Mode 01 PIDs + `ELM_VOLTAGE` (US-199),
DTC Mode 03/07 capture (US-204), and a `drive_summary` row with
ambient / battery / barometric metadata (US-206). `validate_first_real_drive.sh`
is the CIO-runnable validator that confirms every piece of that surface
landed cleanly on an actual drive, pushes the data to the server, runs
the `report.py` summary, and exercises the Spool `/analyze` smoke.

### Preconditions

- US-204, US-205, US-206 are all `passes: true` in the current sprint.
- Pi services installed + eclipse-obd.service active (or manual
  `python src/pi/main.py` run during the drive).
- Key-based SSH from workstation to Pi *and* server.
- OBDLink LX paired + bound (`scripts/verify_bt_pair.sh`).

### Recommended drive shape

Per Spool drive-lifecycle + US-200 debounce + I-016 drill:

- **5+ minutes minimum.** Short drives produce sparse analytics.
- **At least one engine start/stop/start cycle.** Exercises CRANKING →
  RUNNING → KEY_OFF → CRANKING transitions; this is what makes
  `drive_counter` tick past its seed value.
- **15+ minutes sustained warm-idle (no connection churn)** if
  practical. This is the I-016 drill protocol: lets the validator
  confirm the thermostat disposition with statistical confidence.

### Post-drive procedure

```bash
# Dry-run first to verify the plan
bash scripts/validate_first_real_drive.sh --dry-run

# Run against the latest drive on the Pi
bash scripts/validate_first_real_drive.sh

# Or pin a specific drive_id
bash scripts/validate_first_real_drive.sh --drive-id 1

# Skip network-dependent steps (Pi-only smoke)
bash scripts/validate_first_real_drive.sh --skip-sync --skip-report --skip-spool
```

### Expected output (per-step)

| Step | What it verifies | PASS criteria |
|------|------------------|---------------|
| 1    | SSH gate (Pi + server) | Both hosts reachable |
| 2    | Resolve `drive_id` | Latest or `--drive-id` arg resolves |
| 3    | Drive window bounds | MIN + MAX timestamp present |
| 4    | `realtime_data` sanity | rows > 0, all `data_source='real'`, all timestamps end `Z`, distinct `parameter_name` ≥ 8 |
| 5    | `dtc_log` | Table exists; 0 DTCs = clean (reported explicitly); >0 = captured list printed |
| 6    | `drive_summary` | Exactly 1 row for drive_id; ambient NULL = warm restart (reported) |
| 7    | I-016 coolant disposition | `MAX(coolant) ≥ 82 C` + duration ≥ 15 min → **BENIGN**; below threshold + duration met → **ESCALATE** (file Sprint 16 hardware story); duration < 15 min → **INCONCLUSIVE** |
| 8    | `sync_now.py` | Pi → server push reports OK |
| 9    | `report.py --drive N` | Human-readable summary prints |
| 10   | Spool `/analyze` smoke | HTTP 200 (body may say "insufficient data" — valid) |

Exit codes: `0` every step PASS or explicitly N/A; `1` one or more
FAIL; `2` misuse or infra error (bad flag, SSH unreachable,
missing fixture).

### Off-Pi test path

The `tests/pi/integration/test_first_drive_replay.py` suite exercises
the validator's query paths against a synthetic fixture
(`eclipse_idle.db` + synthetic `dtc_log` + `drive_summary` rows). It
runs on any machine with Python 3.11+ — no Pi, no sqlite3 CLI, no
SSH required. Use this as the pre-drive sanity check:

```bash
pytest tests/pi/integration/test_first_drive_replay.py -v
```

If `sqlite3` CLI is on PATH, the suite also invokes the bash validator
directly against the fixture (`--fixture-db PATH`). On Windows dev
without the CLI, the Python-native query tests still cover the SQL
shape acceptance.

### I-016 drill protocol

US-208's I-016 disposition is activity-gated on a *sustained* warm-idle
window. Minimum duration is 15 minutes with no connection churn. If
the CIO drives but can't hold idle for 15 min:

- The validator reports **INCONCLUSIVE** for I-016 (not a failure).
- I-016 stays open; the drill protocol runs on the next drive that
  satisfies the duration gate.
- BENIGN / ESCALATE disposition is written to `offices/pm/issues/I-016.md`
  only after the validator confirms an authoritative reading.

### Activity-gate fallback

If no real drive lands in the sprint window:

- Off-Pi integration test must pass (`pytest tests/pi/integration/...`).
- Dry-run must pass (`bash scripts/validate_first_real_drive.sh --dry-run`).
- File a "defer to Sprint 16" note and mark US-208 `passes: true` on
  the off-Pi path only.

---

## DTC Retrieval Walkthrough (US-204)

Sprint 15 added Mode 03 + Mode 07 DTC capture. The `dtc_log` table on
both Pi and server records every code observed at session start (Mode 03
+ Mode 07 probe-first) and every MIL rising-edge mid-drive
(Mode 03 re-fetch).

### When DTCs are captured

| Trigger | Source | Modes run |
|---------|--------|-----------|
| Drive starts (RPM crosses cranking threshold) | `EventRouterMixin._handleDriveStart` | 03 + 07 (probe-first) |
| `MIL_ON` value goes 0 → 1 mid-drive | `EventRouterMixin._handleReading` + `MilRisingEdgeDetector` | 03 only (re-fetch) |

DTC retrieval is **event-driven**, not tier-scheduled — `dtc_log` is
not in `config.json:realtimeData.parameters` and adds zero per-cycle
K-line load. Disable via `pi.dtc.enabled=false` for replay or
simulator paths.

### Synthetic DTC seeding (off-Pi smoke test)

A 2-step end-to-end test that exercises Pi insert → delta extract →
server upsert without a real ECU:

```bash
# Run the regression test that seeds P0171 + P0420 synthetic codes,
# pulls them via getDeltaRows, and verifies the server upsert.
pytest tests/pi/regression/test_dtc_fixture.py -v
```

Expected output: 2 passed. The test creates an in-memory MariaDB
stand-in (sqlite) and asserts that `drive_id` + `data_source` + the
DTC tuples survive the boundary verbatim.

### Live verification (Pi + server)

After the next real drive that captures a DTC (or via a synthetic
INSERT against the live Pi DB):

```bash
# Pi side -- inspect the recorded codes.
ssh mcornelison@chi-eclipse-01 \
  "sqlite3 ~/Projects/Eclipse-01/data/obd.db \
   'SELECT dtc_code,status,drive_id,first_seen_timestamp,last_seen_timestamp \
    FROM dtc_log ORDER BY id DESC LIMIT 10;'"

# Trigger sync.
ssh mcornelison@chi-eclipse-01 "cd ~/Projects/Eclipse-01 && python scripts/sync_now.py"

# Server side -- verify the row landed with source_device + source_id.
ssh mcornelison@chi-srv-01 \
  "mysql obd2db -e 'SELECT source_device,source_id,dtc_code,status,drive_id \
   FROM dtc_log ORDER BY id DESC LIMIT 10;'"
```

### 2G DSM Mode 07 unsupported path

If the live Eclipse returns null on Mode 07, the Pi log shows:

```
INFO Mode 07 (GET_CURRENT_DTC) returned null -- treating as unsupported on this ECU
INFO DTC session-start | stored=N | pending=0 | mode07=unsupported
```

Per US-204 invariant #2 the probe verdict is NOT persisted — a
reconnect re-probes. When you have an empirical "Mode 07 unsupported"
result on the live car, append it to `specs/grounded-knowledge.md`
§2G DSM DTC Behavior so future sessions skip the probe.

### Unknown DSM codes (Mitsubishi P1XXX)

`python-obd`'s DTC_MAP only covers SAE J2012 standard codes. Unknown
codes land in `dtc_log.description` as the empty string per
US-204 invariant #6 (never fabricate). When real DSM codes are
captured, append the code → description mapping to
`specs/grounded-knowledge.md` §2G DSM DTC Behavior — the schema does
NOT auto-populate from that document.

---

## OBDLink LX Bluetooth Walkthrough (CIO-facing, US-196)

These procedures are for the one-time dongle pairing + the daily-use
`/dev/rfcomm0` binding. Run them on the Pi after SSHing in.

### A. One-time pair (only if bluez bonds have been wiped)

> **When to run this.** Only if `bluetoothctl info <MAC>` reports no
> bond, or if you have explicitly wiped `/var/lib/bluetooth`. Once
> paired+trusted, the bond survives reboot and does not need re-pairing.

1. **Put the LX into pair mode.** Press the LX button until the LED is
   *solid blue* (not blinking). You have roughly 30 seconds before it
   drops back out of pair mode.

2. **Run the pair script on the Pi:**
   ```bash
   ssh mcornelison@10.27.27.28
   cd ~/Projects/Eclipse-01
   scripts/pair_obdlink.sh AA:BB:CC:DD:EE:FF           # your LX's MAC
   # or, if OBD_BT_MAC is already in your .env:
   scripts/pair_obdlink.sh
   ```

   The script drives `bluetoothctl` via `pexpect`, auto-confirms the SSP
   passkey prompt (`Confirm passkey NNNNNN (yes/no):` → `yes`), and
   issues `trust <MAC>` so future reconnects don't re-prompt.

3. **Verify:**
   ```bash
   scripts/verify_bt_pair.sh AA:BB:CC:DD:EE:FF
   ```

   All lines should print `[ OK ]`. Lines that print `[FAIL]` include a
   remediation suggestion.

### B. Routine use — rfcomm bind (survives reboot after install)

The production `ObdConnection` layer binds `/dev/rfcomm0` lazily when the
service starts. But you can also bind it manually for ad-hoc smoke
testing:

```bash
scripts/connect_obdlink.sh AA:BB:CC:DD:EE:FF       # defaults to rfcomm0 channel 1
scripts/connect_obdlink.sh --release               # unbind when done
```

### C. Install reboot-survival (one-time; `deploy-pi.sh --init` also does this)

```bash
sudo bash deploy/install-rfcomm-bind.sh AA:BB:CC:DD:EE:FF
# or re-read an existing /etc/default/obdlink:
sudo bash deploy/install-rfcomm-bind.sh
```

This installs `/etc/systemd/system/rfcomm-bind.service`, writes
`/etc/default/obdlink`, and enables the unit. After a reboot,
`systemctl is-active rfcomm-bind.service` should return `active`.

### D. Verify reboot-survival *without* actually rebooting

```bash
# Simulate a boot cycle by releasing + restarting the service:
sudo rfcomm release 0 || true
sudo systemctl restart rfcomm-bind.service
sleep 3
rfcomm show 0                                # should show the MAC bound again
scripts/verify_bt_pair.sh AA:BB:CC:DD:EE:FF  # all green
```

For a full confidence check, do a real reboot (`sudo reboot`), wait for
the Pi to come back, SSH in, and re-run `verify_bt_pair.sh`.

### Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `pair_obdlink.sh` times out on "Confirm passkey" | LX dropped out of pair mode | Press LX button → solid blue → re-run |
| `bluetoothctl info <MAC>` reports nothing | bond wiped | Re-run `pair_obdlink.sh` |
| `rfcomm show 0` reports nothing after reboot | unit not enabled | `sudo systemctl enable rfcomm-bind.service` |
| `rfcomm-bind.service` fails at boot | `/etc/default/obdlink` missing | `sudo bash deploy/install-rfcomm-bind.sh <MAC>` |
| `python-obd` can't open `/dev/rfcomm0` | dongle powered off / out of range | Power-cycle dongle; check LED state |

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
Config: baseUrl=http://10.27.27.10:8000, batchSize=500

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

## Data Source Tagging for Tests (US-195 / Spool CR #4)

Every row written into a capture table carries a `data_source` tag. Live OBD writes default to `'real'` via the DB-level `DEFAULT`; non-real paths must pass an explicit value so server analytics and AI prompts can filter them out.

**Test fixture rule** — test fixtures MUST set `data_source='fixture'` when inserting into any of `realtime_data`, `connection_log`, `statistics`, `calibration_sessions`, `profiles`:

```python
conn.execute(
    "INSERT INTO realtime_data (parameter_name, value, unit, data_source) "
    "VALUES (?, ?, ?, ?)",
    ("RPM", 850.0, "rpm", "fixture"),
)
```

**Flat-file replay (US-191)** — the replay harness writes `data_source='replay'`. The canonical fixtures in `data/regression/pi-inputs/` are generated with the tag already applied — no per-caller action needed.

**Enum values** (see `specs/architecture.md` §5 Data Source Tagging): `'real' | 'replay' | 'physics_sim' | 'fixture'`. Any other value is rejected by the SQLite CHECK constraint at insert time.

**Why this matters** — a single untagged fixture row leaking into server analytics silently poisons baseline calibrations for the entire device. The `CHECK` constraint + server `WHERE data_source='real'` filter are load-bearing; do not bypass.

---

## Flat-File Replay Validation (B-045 / US-191 — canonical Pi→Server path)

**As of Sprint 13, the canonical Pi→Server validation uses deterministic
SQLite fixtures replayed via SCP, not the physics simulator.**  The
physics-simulator launch path that Sprint 11's `validate_pi_to_server.sh`
used is deprecated; it violated tier isolation (two `--simulate` producers
hitting one DB) and produced non-deterministic row counts that forced
sloppy "delta > 0" assertions.

Two artifacts make the replay-based validation observable:

1. **`tests/integration/test_pi_to_server_e2e.py`** — CI-friendly.  Spins
   up a stdlib `ThreadingHTTPServer` mocking `/api/v1/sync`, seeds a temp
   Pi SQLite, drives `SyncClient` (and `scripts/sync_now.py`) against it,
   and asserts rows arrive + high-water marks advance + a second push is
   empty.  Runs as part of `pytest tests/` on every commit.
2. **`scripts/replay_pi_fixture.sh`** — the CIO-runnable live driver.
   SCPs a fixture from `data/regression/pi-inputs/` to the Pi, runs
   `sync_now.py`, and asserts the server delta matches the fixture row
   count EXACTLY per-table.  Run on bench hardware with both machines
   live; the assertions are against live MariaDB, not a mock.

`scripts/validate_pi_to_server.sh` still exists for full walk-phase
validation (report + display + Pi→server), and internally delegates its
data-ingest step to `replay_pi_fixture.sh`.  New callers should prefer
the replay driver directly unless they need the report/display steps.

### Generating / regenerating fixtures

Fixtures are checked into `data/regression/pi-inputs/` as `.db` files.
They are bit-for-bit deterministic — re-running the generator produces
identical bytes.  Regenerate after any Pi schema change:

```bash
python scripts/seed_pi_fixture.py --all --output-dir data/regression/pi-inputs
```

Or one at a time:

```bash
python scripts/seed_pi_fixture.py --fixture cold_start \
    --output data/regression/pi-inputs/cold_start.db
```

Canonical fixtures:

| Fixture            | Drives | Duration  | realtime_data rows | connection_log rows |
|--------------------|-------:|----------:|-------------------:|--------------------:|
| `cold_start.db`    |      1 |    5 min  |                150 |                   2 |
| `local_loop.db`    |      1 |   15 min  |                900 |                   2 |
| `errand_day.db`    |      3 |  ~24 min  |               2400 |                   6 |

Every fixture contains the full Pi schema (all 11 production tables +
`sync_log`) with `sync_log.last_synced_id=0` for every in-scope table,
so `sync_now.py` sees the entire fixture as pending delta on first run.

### Running the CI test locally

```bash
pytest tests/integration/test_pi_to_server_e2e.py -v
pytest tests/scripts/test_seed_pi_fixture.py tests/scripts/test_replay_pi_fixture_sh.py -v
```

No Pi, no server, no network access required — the mock server binds to
`127.0.0.1` on an ephemeral port; the replay driver tests run under
`--dry-run`.  Expected: ~40 tests pass in ~90s.

### Running the live replay driver

```bash
# Default: replay cold_start.db (150 rows), assert exact-delta match.
bash scripts/replay_pi_fixture.sh cold_start

# Pick a different fixture (larger / multi-drive).
bash scripts/replay_pi_fixture.sh local_loop
bash scripts/replay_pi_fixture.sh errand_day

# Leave the Pi's eclipse-obd.service stopped at the end -- useful when
# chaining several fixtures in a single bench session.
bash scripts/replay_pi_fixture.sh --keep-service-stopped cold_start

# Print the plan without touching anything.
bash scripts/replay_pi_fixture.sh --dry-run cold_start
```

Prerequisites:

- Key-based SSH works: `ssh mcornelison@10.27.27.28 hostname` and
  `ssh mcornelison@10.27.27.10 hostname` both return cleanly.
- `COMPANION_API_KEY` present in the Pi `.env` and matches the server
  `.env` `API_KEY`.
- Chi-Srv-01:8000 reachable from the Pi network-wise.
- Server `.env` has working `MYSQL_*` credentials; the server venv has
  `mysql-connector-python` installed.
- Fixture file exists locally (regenerate via `seed_pi_fixture.py` if not).

### What each step proves

| Step | Proves |
|---|---|
| 1 | Pi producer (`eclipse-obd.service`) is stopped — no interference |
| 2 | Fixture row counts are readable locally (the "expected" side) |
| 3 | Server pre-sync baseline row counts captured |
| 4 | Fixture SCPed onto the Pi, replacing `obd.db` |
| 5 | `sync_now.py` executes on the Pi and reports `Status: OK` |
| 6 | Server post-sync row counts captured |
| 7 | Per-table delta EXACTLY matches the fixture row count |
| 8 | Summary + optional service restart |

If step 7 reports any FAIL row, the exact expected-vs-observed counts
are printed so the broken layer is obvious.  Common root causes:

- SyncClient skipped a table that the fixture populated (check
  `pi.companionService.enabledTables` if configurable, or
  `sync_log.IN_SCOPE_TABLES` for scope drift).
- Server `ACCEPTED_TABLES` set no longer matches Pi `IN_SCOPE_TABLES`.
- Pi sent the rows but server's upsert deduplication silently dropped
  them (check `source_device` column on the server side).

### Invariants worth re-reading before a live run

- A failed push must NOT advance `sync_log.last_synced_id` (US-149).  If
  a live run hits a server-reachability failure, re-run once the server
  is reachable — the same rows get re-sent without intervention.
- Row counts must match *exactly* (fixture has N, server delta is N).
  Any mismatch is a real bug, not a rounding artifact.
- The API key must never appear in stdout.  Both `sync_now.py` and this
  driver take care to never print the key; don't add a "for debugging"
  echo.
- Fixtures are deterministic — **do NOT edit the `.db` files by hand.**
  Regenerate via `seed_pi_fixture.py` so a future schema-change sweep
  has a single source of truth.

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

## HDMI Live-Data Verification (US-192 — Pi Harden)

US-192 closes US-170. Where `validate_hdmi_display.sh` (US-183) proved
pygame can paint the OSOYOO using scripted values, `verify_hdmi_live.sh`
proves **live data reaches the display**: `main.py` writes `realtime_data`
rows, the render harness polls those rows each frame, and the six gauges
update at ~1 Hz.

### What you're validating

- `eclipse-obd.service` Environment= block sets `DISPLAY=:0`,
  `XAUTHORITY=/home/mcornelison/.Xauthority`, `SDL_VIDEODRIVER=x11` so
  any downstream pygame process inherits the X11 render path.
- `python src/pi/main.py --simulate` runs past the 0.6s TD-024 cliff
  (US-198 precondition) and keeps writing realtime_data rows.
- `scripts/render_primary_screen_live.py --from-db <path>` polls
  `data/obd.db` each frame and renders the latest value per gauge.
- The BATTERY_V -> BATTERY_VOLTAGE alias (US-199 collector name ->
  US-164 display slot) works end-to-end: the Volts gauge updates from
  the real ELM_VOLTAGE path rather than a HAT voltage fallback.
- CIO eyeballs the OSOYOO: 6 gauges with non-zero values refreshing,
  no flicker, no GL errors.

### How to run it

On the CIO's Windows workstation (git bash):

```bash
bash scripts/verify_hdmi_live.sh                  # 30s live render
bash scripts/verify_hdmi_live.sh --duration 60    # longer eyeball window
bash scripts/verify_hdmi_live.sh --dry-run        # print plan, no SSH
```

Each step is PASS / FAIL and the final line reports the tally. The CIO is
prompted at Step 4 to confirm the visual result.

### What each step proves

| Step | Proves |
|------|--------|
| 1 | SSH gate reaches `mcornelison@10.27.27.28` with key-based auth |
| 2 | `eclipse-obd.service` stops cleanly (the driver starts its own main.py) |
| 3 | `python src/pi/main.py --simulate` launches, writes realtime_data within 5s |
| 4 | `render_primary_screen_live.py --from-db data/obd.db` renders for N seconds; CIO confirms 6 live gauges |
| 5 | Cleanup: background main.py killed, stale PID file removed |

The simulator path is the valid acceptance path — **engine is not
required**. Live OBD is a bonus once the dongle is bound. Invariant #1
of US-192: "Do NOT require live OBD for this acceptance."

### Running just the live harness (no SSH wrapper)

Useful for bench-side debugging on the Pi directly:

```bash
# Launch main.py in one terminal (or via systemctl)
~/obd2-venv/bin/python src/pi/main.py --simulate &

# Poll data/obd.db from the render harness in another terminal
DISPLAY=:0 XAUTHORITY=~/.Xauthority SDL_VIDEODRIVER=x11 \
    ~/obd2-venv/bin/python scripts/render_primary_screen_live.py \
        --duration 30 \
        --from-db ~/Projects/Eclipse-01/data/obd.db
```

### Troubleshooting

- **Gauges all show `---`**: `main.py` hasn't written any realtime_data
  yet (may be crashed). Tail `/tmp/us192_main.log` on the Pi.
- **Volts gauge is blank while others update**: BATTERY_V rows not
  arriving — either US-199 isn't active (`config.json::pi.pollingTiers`)
  or the adapter is declining ATRV. Check the orchestrator log for
  `ParameterNotSupportedError` or `ParameterReadError` on BATTERY_V.
- **GL BadAccess crash**: US-198 is supposed to have closed this on the
  Status Overlay. If the primary render harness hits it, the Pi may be
  missing the XAUTHORITY file or DISPLAY is not :0 — verify via `xhost`
  and `xset q` in the CIO's SSH session.
- **"display already in use"**: another pygame process (old harness,
  stale validate_hdmi_display.sh) is still holding the framebuffer.
  `pkill -f render_primary_screen_live` on the Pi, then retry.

### Off-Pi test coverage

`tests/pi/display/test_manager_live_render.py` covers the poll layer
(`buildReadingsFromDb`) with an in-memory SQLite: empty db, single row,
multi-parameter, latest-wins, BATTERY_V alias, data_source filter,
missing file, missing table. The test suite asserts that gauge values
change across polling cycles as new rows arrive — the CI mirror of the
CIO eyeball.

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-04-20 | Rex (Ralph) | Added HDMI Live-Data Verification section for US-192 (closes US-170) |
| 2026-04-19 | Rex (Ralph) | B-045 / US-191: replaced Walk-Phase End-to-End Validation with Flat-File Replay Validation; physics-sim launch deprecated |
| 2026-04-18 | Rex (Ralph) | Added HDMI Render Validation section for US-183 |
| 2026-04-18 | Rex (Ralph) | Added Walk-Phase End-to-End Validation section for US-166 |
| 2026-04-18 | Rex (Ralph) | Added Manual Pi -> Server Sync section for US-154 |
| 2026-01-23 | Ralph Agent | Initial testing guide for US-OSC-020 |
