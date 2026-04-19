# Pi-Side Crawl/Walk/Run/Sprint Architecture Design

| Field | Value |
|---|---|
| **Spec ID** | pi-crawl-walk-run-sprint |
| **Status** | Approved |
| **Created** | 2026-04-15 |
| **Author** | Ralph (with CIO) |
| **Companion Spec** | `2026-04-15-server-crawl-walk-run-design.md` (server side) |
| **Related Backlog** | B-012 (Pi Setup), B-014 (Pi Testing), B-023 (WiFi Sync), B-027 (Client Sync) |

---

## Purpose

Phase the Raspberry Pi (`chi-eclipse-01`) from validated simulator through physical car installation to real-world data collection using a **crawl/walk/run/sprint** progression:

- **Crawl**: Deploy to Pi hardware, validate existing code works on ARM, prove display and startup/shutdown.
- **Walk**: Connect to Chi-Srv-01 server, push simulated data through real sync pipeline.
- **Run**: Physical car installation, Bluetooth OBD-II diagnostics, real idle data.
- **Sprint**: Real driving, full lifecycle, Spool engagement, interactive display.

The Pi has 164 existing Python files across 18 subpackages. This is primarily a **validation and hardening** effort for crawl/walk, then **hardware integration** for run/sprint. Very little greenfield code — mostly proving what exists works on real hardware and filling integration gaps.

### Relationship to Server Spec

This spec is the Pi-side companion to `2026-04-15-server-crawl-walk-run-design.md`. The two specs share stories in the walk phase (sync client) and coordinate at phase boundaries:

```
Pi Crawl (validate on hardware)  ←→  Server Crawl (fake data analytics)
Pi Walk  (sync to server)        ←→  Server Walk  (receive sync data)
Pi Run   (car installation)      ←→  Server Run   (real data analytics)
Pi Sprint (real driving)         ←→  Server Run   (AI analytics + Spool)
```

---

## Architecture Context

### What Already Exists (164 files)

| Package | Files | Status | Purpose |
|---|---|---|---|
| `src/pi/alert/` | 13 | Built | Tiered threshold evaluation (RPM, coolant, battery, STFT, IAT, timing) |
| `src/pi/analysis/` | 4 | Built | StatisticsEngine, ProfileStatisticsManager |
| `src/pi/backup/` | 5 | Built | BackupManager, GoogleDriveUploader |
| `src/pi/calibration/` | 9 | Built | CalibrationManager, session tracking, comparison, export |
| `src/pi/clients/` | 3 | Built | OllamaClient, uploader |
| `src/pi/display/` | 15 | Built | DisplayManager, 7 screens, 3 drivers (headless/minimal/developer), adapters |
| `src/pi/hardware/` | 8 | Built | HardwareManager, UpsMonitor, ShutdownHandler, GpioButton, I2cClient |
| `src/pi/obd/config/` | 4 | Built | OBD config loading and validation |
| `src/pi/obd/data/` | 5 | Built | ObdDataLogger, RealtimeDataLogger |
| `src/pi/obd/drive/` | 4 | Built | DriveDetector state machine |
| `src/pi/obd/export/` | 3 | Built | CSV/JSON export |
| `src/pi/obd/orchestrator/` | 5 | Built | ApplicationOrchestrator, component wiring |
| `src/pi/obd/service/` | 4 | Built | OBD connection service |
| `src/pi/obd/shutdown/` | 3 | Built | Graceful shutdown coordination |
| `src/pi/obd/simulator/` | 8 | Built | SensorSimulator, DriveScenarioRunner, VehicleProfile, 4 scenarios |
| `src/pi/obd/vehicle/` | 4 | Built | VinDecoder, StaticDataCollector |
| `src/pi/power/` | 3 | Built | PowerMonitor, BatteryMonitor |
| `src/pi/profile/` | 4 | Built | ProfileManager, ProfileSwitcher |

### What's NOT Built Yet

| Component | Phase Needed | Description |
|---|---|---|
| Sync client (SyncClient) | Walk | HTTP delta push to server, high-water mark tracking |
| Sync log table | Walk | Pi SQLite table tracking sync state per table |
| Companion service config | Walk | Config section for server URL, API key, batch size |
| WiFi connectivity detection | Walk | Detect DeathStarWiFi, trigger sync |
| Manual sync CLI | Walk | `scripts/sync_now.py` one-shot push |
| Backup push to server | Sprint | Upload SQLite DB + logs to server `/backup` endpoint |
| Display content refinement | Crawl-Sprint | Spool-reviewed gauge content across 3 tiers |

### Existing Display Screens

| Screen | File | Current Content |
|---|---|---|
| Primary | `primary_screen.py` | Main gauges: RPM, speed, coolant, AFR, boost, voltage |
| Boost Detail | `boost_detail.py` | Boost pressure focused view |
| Fuel Detail | `fuel_detail.py` | AFR / fuel data |
| Knock Detail | `knock_detail.py` | Knock count monitoring |
| Thermal Detail | `thermal_detail.py` | Coolant and IAT temperatures |
| System Detail | `system_detail.py` | System health (CPU, memory, disk, battery) |
| Parked Mode | `parked_mode.py` | Display when engine is off |

These screens were built before Spool joined and before tiered thresholds were designed. They need validation on real hardware and Spool review for data relevance.

### Hardware Specs

| Component | Specification |
|---|---|
| Board | Raspberry Pi 5 Model B, 8GB RAM |
| Storage | 128GB A2 U3/V30 microSD |
| Display | OSOYOO 3.5" HDMI Touch, 480x320, capacitive |
| UPS | Geekworm X1209 HAT, 18650 battery backup |
| OBD Dongle | OBDLink LX, Bluetooth, MAC `00:04:3E:85:0D:FB`, FW 5.6.19 |
| Network | WiFi 5 (802.11ac) → DeathStarWiFi (10.27.27.0/24) |

---

## Hostname Migration

| Field | Old | New |
|---|---|---|
| Hostname | `chi-eclipse-tuner` | `chi-eclipse-01` |
| Display name | `EclipseTuner` | `Eclipse-01` |
| Device ID (sync payloads) | `chi-eclipse-tuner` | `chi-eclipse-01` |
| IP address | 10.27.27.28 | 10.27.27.28 (unchanged) |
| User | mcornelison | mcornelison (unchanged) |
| Project path | `/home/mcornelison/Projects/EclipseTuner` | `/home/mcornelison/Projects/Eclipse-01` |

Updated in: `/etc/hostname`, `/etc/hosts`, config.json `deviceId`, server sync payloads, display header text, `offices/ralph/agent-pi.md`, `offices/ralph/CLAUDE.md`, `offices/tester/tester.md`, `offices/pm/roadmap.md`, and all documentation references.

---

## Display Tier Architecture

The OSOYOO 3.5" HDMI display (480x320) follows its own crawl/walk/run progression. Each tier builds on the previous. Spool reviews content at each tier to ensure gauges show tuning-relevant data.

### Basic Tier (Crawl Phase)

Core gauges — large, readable at a glance while driving. Static layout.

```
┌───────────────────────────────────────────┐
│ Eclipse-01              ● Connected   [D] │
├───────────────────────────────────────────┤
│                                           │
│   RPM        2500      SPEED    45 mph    │
│   COOLANT    185°F     AFR      14.7:1    │
│   BOOST      8.2 psi   VOLTS   14.2V     │
│                                           │
├───────────────────────────────────────────┤
│ No Alerts                    🔋 98% [AC]  │
└───────────────────────────────────────────┘
```

**Spool review gate**: Validate that RPM, coolant, boost, AFR, speed, voltage are the right 6 parameters for the primary screen. Spool may suggest swapping one (e.g., knock count instead of speed for a tuning-focused driver).

### Advanced Tier (Walk Phase)

Adds connectivity context and historical markers to gauges.

```
┌───────────────────────────────────────────┐
│ Eclipse-01    ● OBD  ● WiFi  ● Sync  [D] │
├───────────────────────────────────────────┤
│                                           │
│   RPM    2500  [▼850  ▲5200]              │
│   COOL   185°F [▼145  ▲198 ]  ← NORMAL   │
│   BOOST  8.2   [▼0.0  ▲12.4]             │
│   AFR    14.7  [▼13.8 ▲15.1]  ← NORMAL   │
│   IAT    94°F  [▼72   ▲118 ]  ← ⚠ WATCH  │
│                                           │
├───────────────────────────────────────────┤
│ Last sync: 14:30  │  Drives: 12  │ 🔋 98% │
└───────────────────────────────────────────┘
```

Changes from basic:
- Connection status indicators: OBD (dongle), WiFi (network), Sync (server)
- Min/max markers from recent drives shown next to each parameter
- Color-coded status per tiered thresholds (NORMAL=white, WATCH=orange, DANGER=red)
- Footer: last sync time, total drive count, battery

**Spool review gate**: Validate threshold color mapping matches tiered threshold specs. Confirm min/max markers are useful vs noisy.

### Interactive Tier (Sprint Phase)

Touch-screen carousel with swipeable detail screens.

```
┌───────────────────────────────────────────┐
│ Eclipse-01    [1/7]  ● ● ● ● ● ● ●  [D] │
├───────────────────────────────────────────┤
│                                           │
│          ┌─────────────────┐              │
│          │   BOOST DETAIL  │              │
│          │                 │              │
│          │   Current: 8.2  │              │
│          │   Peak:   12.4  │              │
│          │   Avg:     4.2  │              │
│          │   ████████░░░░  │              │
│          │   0    8   16   │              │
│          └─────────────────┘              │
│       ← swipe left    swipe right →       │
├───────────────────────────────────────────┤
│ [Primary] [Boost] [Fuel] [Thermal] [Sys]  │
└───────────────────────────────────────────┘
```

Changes from advanced:
- Swipe left/right to navigate between detail screens
- Dot indicators show current screen position
- Bottom tab bar for quick screen jumps (touch targets)
- Each detail screen shows focused deep-dive for one domain
- Parked mode: drive summary with statistics and AI recommendations (if available)
- Screen priority order set by Spool based on tuning relevance

**Spool review gate**: Define screen order priority. Review each detail screen's content for tuning relevance. Decide which screens are "always on" vs "on demand."

---

## Phase 1: Crawl — Validate and Harden on Pi Hardware

### Goal

Deploy existing code to `chi-eclipse-01`. Prove the simulator, display, and startup/shutdown all work on real Pi 5 ARM hardware. Fix what doesn't.

### Done Milestone

CIO SSHs to `chi-eclipse-01`, runs the simulator, sees data on the OSOYOO display, verifies clean startup and shutdown. Test suite green on ARM.

### 1.1 Pi OS Setup and Project Deployment (absorbed from B-012)

- Raspberry Pi OS (64-bit Bookworm) installed
- Hostname set to `chi-eclipse-01`
- User `mcornelison` created
- SSH enabled, key-based auth configured
- Python 3.11+ verified
- Project cloned to `/home/mcornelison/Projects/Eclipse-01`
- Virtual environment created at `.venv/`
- `pip install -r requirements.txt` succeeds
- WiFi configured for DeathStarWiFi (10.27.27.0/24)
- Static IP 10.27.27.28 assigned

### 1.2 Simulator Validation on ARM (absorbed from B-014)

- `python src/pi/main.py --simulate --dry-run` runs without errors on ARM/Linux
- All 4 existing scenarios execute: `cold_start`, `city_driving`, `highway_cruise`, `full_cycle`
- Data written to local SQLite database
- DriveDetector correctly identifies drive start/end events
- StatisticsEngine produces post-drive analysis
- Fix any platform-specific issues (path separators, missing system libraries, ARM-specific failures)

### 1.3 OSOYOO Display Validation (absorbed from B-014)

- pygame initializes on Pi 5 with OSOYOO 3.5" HDMI (480x320)
- Primary screen renders with simulated data
- Touch input detected and routed to display manager
- Display modes verified: headless (no display), minimal (OSOYOO), developer (console)
- Font sizes readable on 3.5" screen (may need adjustment from development assumptions)
- Screen refresh rate acceptable (target 1Hz update for gauge values)

### 1.4 Display Basic Tier — Core Gauges (new)

- Primary screen shows 6 core parameters: RPM, coolant temp, boost pressure, AFR, speed, voltage
- Large text, high contrast, readable at arm's length in daylight
- Header: hostname `Eclipse-01`, OBD connection status, active profile indicator
- Footer: alert status bar, battery SOC + power source
- Color scheme: dark background, white text, colored values for warnings
- **Spool inbox note**: Request review of primary screen parameter selection — are these the right 6 for a tuning-focused driver?

### 1.5 systemd Service Deployment (absorbed from B-012)

- Service file `deploy/eclipse-obd.service` installed to `/etc/systemd/system/`
- `ExecStart` runs `python src/pi/main.py` (with appropriate flags)
- `Restart=on-failure`, `RestartSec=10`
- `After=network.target bluetooth.target`
- Service enables on boot: `systemctl enable eclipse-obd`
- Logs accessible via `journalctl -u eclipse-obd -f`

### 1.6 Hardware Subsystem Validation (absorbed from B-014)

- I2C communication with Geekworm X1209 UPS HAT verified
- Battery voltage, current, SOC readings accurate
- Power source detection (AC vs battery) working
- TelemetryLogger writes battery/power data to rotating log files
- GPIO button wired and responsive (gpiozero `Button` with debounce)
- UpsMonitor graceful degradation when UPS HAT not connected (dev/test scenarios)

### 1.7 Startup/Shutdown Lifecycle (absorbed from B-014)

- **Boot sequence**: Pi power on → systemd starts service → config loaded → OBD connection attempted (fails gracefully in simulator) → display initialized → "Ready" state
- **Shutdown via GPIO button**: Long press (3s) → `ShutdownHandler` triggers → components shut down in reverse order → clean exit
- **Shutdown via power loss**: UPS detects AC loss → `ShutdownHandler` schedules shutdown after grace period → same clean shutdown path
- **Double Ctrl+C**: First sets shutdown flag, second forces immediate exit
- Verify shutdown order: data components → hardware manager → display (per architecture spec)

### 1.8 Test Suite on ARM (absorbed from B-014)

- Run full `pytest tests/` on Pi hardware
- Current baseline: 1488 tests collected (1469 fast pass, 1487 full pass on Windows)
- Identify and fix ARM/Linux-specific failures:
  - Path separator differences
  - Missing system libraries (pygame dependencies, GPIO libraries)
  - Timing-sensitive tests that behave differently on ARM
  - Hardware mock assumptions that differ on real Pi
- Establish Pi-specific test baseline
- Tests marked `@pytest.mark.pi_only` for tests that only run on Pi hardware

---

## Phase 2: Walk — Connect Pi to Server with Simulated Data

### Goal

Wire up sync pipeline to Chi-Srv-01. Push simulated drive data through real HTTP endpoints. Validate end-to-end data flow.

### Done Milestone

Simulator runs on `chi-eclipse-01`, sync pushes to Chi-Srv-01, server CLI reports show the data. Display shows sync status.

### 2.1 Sync Client Implementation (absorbed from B-027: US-148, US-149, US-151)

**Sync Log Table** (US-148):
- New `sync_log` table in Pi SQLite:
  - `table_name TEXT PRIMARY KEY`
  - `last_synced_id INTEGER NOT NULL DEFAULT 0`
  - `last_synced_at TEXT`
  - `last_batch_id TEXT`
  - `status TEXT` (ok, pending, failed)
- Added to Pi database initialization (idempotent)
- `getDeltaRows(tableName, lastId, limit)` returns rows where `id > lastId`, ascending
- Tables in scope: `realtime_data`, `statistics`, `profiles`, `vehicle_info`, `ai_recommendations`, `connection_log`, `alert_log`, `calibration_sessions`
- Excluded (Pi-only): `battery_log`, `power_log`

**HTTP Sync Client** (US-149):
- `SyncClient` class in new sync module
- `pushDelta(tableName)`: read sync_log → get delta rows → POST to server → update high-water mark on success only
- `pushAllDeltas()`: iterate all in-scope tables
- API key from `COMPANION_API_KEY` env var via secrets_loader
- Exponential backoff retry: `[1, 2, 4, 8, 16]` seconds, max 3 attempts
- Failed push does NOT advance high-water mark (data loss safety)
- Connection timeout: configurable (default 30s)

**Companion Service Config** (US-151):
- New section in `config.json` under `pi:`:
  ```json
  "companionService": {
      "enabled": true,
      "baseUrl": "http://10.27.27.10:8000",
      "apiKeyEnv": "COMPANION_API_KEY",
      "syncTimeoutSeconds": 30,
      "batchSize": 500,
      "retryMaxAttempts": 3,
      "retryBackoffSeconds": [1, 2, 4, 8, 16]
  }
  ```
- `COMPANION_API_KEY` added to `.env.example`
- ConfigValidator updated with new section + defaults
- When `enabled: false`, sync returns early (graceful no-op)

### 2.2 Manual Sync CLI (absorbed from B-027: US-154)

`scripts/sync_now.py`:
```bash
python scripts/sync_now.py
```

Output:
```
Sync started: 2026-04-15 14:32:05
Config: baseUrl=http://10.27.27.10:8000, batchSize=500

realtime_data: 247 new rows → pushed → accepted (batch: abc123)
statistics: 12 new rows → pushed → accepted (batch: abc124)
alert_log: 0 new rows → nothing to sync
...

Total: 259 rows pushed across 2 tables
Elapsed: 1.8s
Status: OK
```

Exit code 0 on success, 1 on failure. Works with empty DB ("Nothing to sync"). Works when server unreachable (prints error, exits 1, does NOT advance sync_log).

### 2.3 WiFi Connectivity Detection (absorbed from B-023)

- Detect connection to DeathStarWiFi (SSID-based or subnet 10.27.27.0/24 detection)
- Log connectivity state changes (connected/disconnected)
- When connected: set internal flag `isServerReachable`
- Do NOT auto-trigger sync in walk phase (manual only via `sync_now.py`)
- Future enhancement (run/sprint): auto-sync on WiFi return

### 2.4 Display Advanced Tier — Connectivity and History (new)

Updates to existing display screens:

**Header enhancements**:
- Three connection indicators: `● OBD` (dongle), `● WiFi` (network), `● Sync` (server)
- Green = connected/recent, gray = disconnected, red = error

**Gauge enhancements**:
- Min/max markers from recent drives shown in brackets next to each parameter value
- Color-coded status per tiered thresholds:
  - Blue: cold/below normal
  - White: normal operating range
  - Orange: caution (WATCH)
  - Red: danger (INVESTIGATE/CRITICAL)

**Footer enhancements**:
- Last sync timestamp
- Total drive count
- Battery SOC + power source

**Spool inbox note**: Request review of threshold-to-color mapping. Confirm min/max markers are useful context vs visual noise on a 3.5" screen.

### 2.5 End-to-End Simulator-to-Server Validation (new)

Integration validation proving the full pipeline works:

1. Run simulator on `chi-eclipse-01` with `full_cycle` scenario
2. Verify data in local SQLite (realtime_data, connection_log, statistics)
3. Run `scripts/sync_now.py` to push to Chi-Srv-01
4. Verify data in MariaDB on Chi-Srv-01 (row counts match)
5. Run `scripts/report.py --drive latest` on Chi-Srv-01
6. Confirm analytics output matches expectations (statistics within tolerance)
7. Verify display shows sync success indicator

This is a manual validation checklist for the CIO, not an automated test (Pi + server coordination requires both systems running).

---

## Phase 3: Run — Physical Car Installation and Bluetooth Diagnostics

### Goal

Put the Pi in the Eclipse. Pair with OBDLink LX. Read real idle data. Prove the hardware chain works before driving.

### Done Milestone

Pi mounted in car, display shows real idle data from the Eclipse's ECU, Bluetooth connection stable, VIN decoded correctly, clean power on/off cycle.

### 3.1 Bluetooth OBD-II Pairing (new)

- Pi Bluetooth enabled and discoverable
- Scan discovers OBDLink LX at MAC `00:04:3E:85:0D:FB`
- Bluetooth pairing established (PIN-based if required by OBDLink)
- Serial port binding: `/dev/rfcomm0` or equivalent
- python-OBD library connects via Bluetooth serial
- Connection survives Pi reboot (paired device remembered)
- Troubleshooting: if pairing fails, log detailed Bluetooth stack errors
- Config: Bluetooth MAC address configurable in `config.json` (not hardcoded)

### 3.2 Live Idle Data Verification (new)

With engine running at idle in the garage:

- OBD connection established via Bluetooth
- Supported PIDs queried — verify which PIDs the Eclipse's ECU supports
- Real-time readings at idle verified against expected ranges:
  | Parameter | Expected Idle Range | Source |
  |---|---|---|
  | RPM | 800-950 | `specs/grounded-knowledge.md` |
  | Coolant Temp | 180-200°F (warm) | `specs/grounded-knowledge.md` |
  | Battery Voltage | 13.5-14.5V | `specs/grounded-knowledge.md` |
  | IAT | Ambient temp ±10°F | Reasonable |
  | STFT | -10% to +10% | `specs/grounded-knowledge.md` |
  | Speed | 0 mph | Idle |
- VIN decode: query VIN from ECU, NHTSA decode succeeds, result matches 1998 Mitsubishi Eclipse GST
- Data written to local SQLite database
- Log any unsupported PIDs for later review

### 3.3 UPS Power Behavior Validation (new)

- With car running: UPS charges from car USB power, SOC increases
- Ignition off: UPS detects AC power loss within configured timeout
- UPS provides battery power for grace period (configurable, target 30-60 seconds)
- ShutdownHandler triggers clean shutdown before battery depletes
- Verify: no data corruption in SQLite after power-loss shutdown
- Edge case: rapid ignition on-off-on (bouncing) — should not trigger spurious shutdowns

### 3.4 Display Verification with Real Data (new)

- Primary screen renders with real sensor values (not simulated)
- Gauge values update at ~1Hz
- Values visually match what a scan tool would show (CIO can cross-reference with phone OBD app)
- Font size and contrast readable in car cabin (daylight and night)
- Touch responsiveness verified in car mounting position

---

## Phase 4: Sprint — Real Driving Data, Full Integration

### Goal

Drive the car with Pi collecting real data. Test full startup-to-sync lifecycle. Engage Spool for data quality feedback. Deploy interactive display.

### Done Milestone

Complete drive cycle captured, synced to server, analytics correct, display usable during driving. Spool has reviewed real data and provided feedback.

### 4.1 First Real Drive Capture (new)

- Plan: garage warmup → local drive (15-20 min) → return to garage
- Pi auto-starts on ignition (systemd service)
- OBD connects via Bluetooth automatically
- DriveDetector identifies engine start → STARTING → RUNNING transitions
- Real-time data logged to SQLite throughout the drive
- Data quality check against `specs/grounded-knowledge.md` expected ranges:
  - RPM under load: 2000-4500 normal driving
  - Coolant temp: rises from cold to 180-200°F
  - IAT: rises with engine bay heat soak
  - STFT: fluctuates within ±10% (healthy closed-loop)
  - Boost: 0-12 psi depending on throttle (turbo behavior)
- DriveDetector identifies engine stop → STOPPING → STOPPED transitions
- Post-drive: StatisticsEngine runs on drive data

### 4.2 Post-Drive Analytics on Real Data (new)

- StatisticsEngine calculates per-parameter statistics for the drive
- Results stored in `statistics` table
- Anomaly flags if any parameter exceeded grounded-knowledge ranges
- On WiFi reconnection in garage: manual sync to Chi-Srv-01 via `sync_now.py`
- Server-side: `scripts/report.py --drive latest` shows real drive analytics
- Validate: server analytics match Pi-side statistics (same math, different platform)

### 4.3 Full Startup-to-Sync Lifecycle Test (new)

Complete lifecycle validated in one session:

```
1. Car in garage, Pi off
2. Turn ignition ON
   → UPS powers Pi
   → Pi boots
   → systemd starts eclipse-obd service
   → Config loaded, display initialized
   → Bluetooth OBD connection established
   → Primary screen shows live idle data
3. Drive (15-20 min local)
   → DriveDetector: STARTING → RUNNING
   → Real-time data logged at ~5 reads/sec
   → Display shows live gauges
   → Alerts evaluated per tiered thresholds
4. Return to garage, turn ignition OFF
   → DriveDetector: RUNNING → STOPPING → STOPPED
   → Post-drive statistics calculated
   → Pi detects WiFi (DeathStarWiFi)
5. Manual sync: python scripts/sync_now.py
   → Delta data pushed to Chi-Srv-01
   → Server acknowledges receipt
6. UPS detects AC power loss (ignition off)
   → Grace period countdown
   → Clean shutdown triggered
   → All data flushed to SQLite
   → Display shows "Shutting down..."
   → Pi powers off cleanly
7. Verify on Chi-Srv-01:
   → python scripts/report.py --drive latest
   → Real drive data visible and correct
```

### 4.4 Display Interactive Tier — Touch Carousel (new)

Touch-screen navigation between detail screens:

**Navigation**:
- Swipe left/right to cycle through screens
- Dot indicators at top show current position (e.g., `[3/7]`)
- Bottom tab bar for quick jumps: `[Primary] [Boost] [Fuel] [Thermal] [Sys]`
- Touch targets sized for finger use (minimum 44x44 pixel hit areas)

**Screen order** (Spool to finalize priority):
1. Primary — core gauges overview (always first)
2. Boost Detail — boost pressure gauge, peak tracking, wastegate duty
3. Fuel Detail — AFR actual vs target, STFT/LTFT, injector duty cycle (when ECMLink)
4. Thermal Detail — coolant temp, IAT, heat soak tracking
5. Knock Detail — knock count, knock sum, timing retard events
6. System Detail — CPU temp, memory, disk, battery, uptime, sync status
7. Parked Mode — drive summary with statistics, AI recommendations (if available)

**Behavior**:
- While driving: primary screen is default, touch navigation available
- While parked: auto-switches to parked mode after drive end
- Screen auto-dim after configurable inactivity timeout

**Spool inbox note**: Request priority ordering of detail screens based on tuning relevance. Which screens does a driver need instant access to under boost? Which can wait until parked?

### 4.5 Spool Data Quality Review (new)

After first real drive data is captured and synced:

- Send Spool an inbox note with:
  - Summary of captured parameters and sample rates
  - Drive statistics output
  - Any anomalies or unexpected values
  - Questions about data quality and completeness
- Spool reviews and provides feedback:
  - Are the right parameters being captured?
  - Are sample rates sufficient for tuning analysis?
  - What parameters are missing that ECMLink would provide?
  - Display screen content recommendations based on real data
- Spool feedback informs future work:
  - ECMLink integration priority (Phase 2 / Summer 2026)
  - Display refinements
  - Server-side analytics adjustments

### 4.6 Backup Push to Server (absorbed from B-027: US-150)

- Push SQLite database file to server `/backup` endpoint
- Push rotating log files (`.log`) to server `/backup` endpoint
- Multipart form upload with SHA256 content hash
- CLI: `python scripts/backup_push.py`
- Allowed extensions: `.db`, `.log`, `.json`, `.gz`
- Non-fatal: backup failure does not block sync or other operations
- Future: scheduled run (every 24h) — not in this story

---

## Story Map

### Phase 1: Crawl (8 stories)

| # | Story ID | Title | Source | Description |
|---|---|---|---|---|
| 1 | B-012 | Pi OS setup and project deployment | Existing | OS, Python, venv, git, hostname `chi-eclipse-01` |
| 2 | B-014 | Simulator validation on ARM | Existing | Run simulator on Pi, fix platform issues |
| 3 | B-014 | OSOYOO display validation | Existing | pygame on 480x320 HDMI, touch input |
| 4 | NEW-P01 | Display basic tier — core gauges | New | 6 parameters, large text, Spool review |
| 5 | B-012 | systemd service deployment | Existing | Auto-start, restart-on-failure |
| 6 | B-014 | Hardware subsystem validation | Existing | I2C UPS, GPIO button, telemetry |
| 7 | B-014 | Startup/shutdown lifecycle | Existing | Boot → ready → shutdown via button/power-loss |
| 8 | B-014 | Test suite on ARM | Existing | pytest on Pi, fix platform failures |

### Phase 2: Walk (5 stories)

| # | Story ID | Title | Source | Description |
|---|---|---|---|---|
| 9 | US-148/149/151 | Sync client implementation | B-027 | SyncClient, sync_log, companion config |
| 10 | US-154 | Manual sync CLI | B-027 | scripts/sync_now.py |
| 11 | B-023 | WiFi connectivity detection | Existing | Detect DeathStarWiFi, log state |
| 12 | NEW-P02 | Display advanced tier | New | Connectivity indicators, min/max, warning colors, Spool review |
| 13 | NEW-P03 | End-to-end simulator-to-server validation | New | Full pipeline validation checklist |

### Phase 3: Run (4 stories)

| # | Story ID | Title | Source | Description |
|---|---|---|---|---|
| 14 | NEW-P04 | Bluetooth OBD-II pairing | New | Discover + pair OBDLink LX, ELM327 handshake |
| 15 | NEW-P05 | Live idle data verification | New | Real readings at idle, VIN decode, PID discovery |
| 16 | NEW-P06 | UPS power behavior validation | New | Charge, power-loss detection, graceful shutdown |
| 17 | NEW-P07 | Display verification with real data | New | Gauges render real values, readability in car |

### Phase 4: Sprint (6 stories)

| # | Story ID | Title | Source | Description |
|---|---|---|---|---|
| 18 | NEW-P08 | First real drive capture | New | Local drive, data quality, grounded-knowledge validation |
| 19 | NEW-P09 | Post-drive analytics on real data | New | StatisticsEngine, server sync, report validation |
| 20 | NEW-P10 | Full startup-to-sync lifecycle test | New | Ignition → boot → collect → park → analyze → sync → shutdown |
| 21 | NEW-P11 | Display interactive tier — touch carousel | New | Swipe navigation, detail screens, Spool priority order |
| 22 | NEW-P12 | Spool data quality review | New | Real data to Spool, feedback on parameters + display |
| 23 | US-150 | Backup push to server | B-027 | SQLite + log upload to server /backup |

**Total: 23 stories across 4 phases.** 9 absorbed from existing backlog items, 12 new, 2 from B-027.

---

## Dependencies

```
Crawl Phase:
  Story 1 (Pi setup)
    → Story 2 (simulator on ARM) — needs Python + project deployed
    → Story 3 (display validation) — needs pygame on Pi
    → Story 4 (basic display tier) — depends on Story 3
    → Story 5 (systemd) — needs project deployed
    → Story 6 (hardware validation) — needs I2C/GPIO access
    → Story 7 (startup/shutdown) — depends on Stories 5, 6
    → Story 8 (test suite) — needs venv + all deps installed
  CHECKPOINT: SSH to chi-eclipse-01, simulator runs, display works, clean shutdown

Walk Phase:
  Story 9 (sync client) — depends on Crawl complete + Server Walk phase
  Story 10 (sync CLI) — depends on Story 9
  Story 11 (WiFi detection) — independent
  Story 12 (advanced display) — depends on Story 4
  Story 13 (e2e validation) — depends on Stories 9, 10 + Server running
  CHECKPOINT: Simulated data syncs to server, reports match

Run Phase:
  Story 14 (Bluetooth pairing) — depends on Crawl + physical car access
  Story 15 (live idle) — depends on Story 14
  Story 16 (UPS validation) — depends on Crawl + car power
  Story 17 (display with real data) — depends on Stories 14, 15
  CHECKPOINT: Real idle data on display, Bluetooth stable, clean power cycle

Sprint Phase:
  Story 18 (first drive) — depends on Run complete
  Story 19 (post-drive analytics) — depends on Story 18 + Server running
  Story 20 (full lifecycle) — depends on Stories 18, 19
  Story 21 (interactive display) — depends on Story 12
  Story 22 (Spool review) — depends on Story 18 (needs real data)
  Story 23 (backup push) — depends on Server Run phase (US-CMP-007)
  CHECKPOINT: Full drive cycle, synced, analytics correct, Spool feedback received
```

### Cross-Spec Dependencies (Pi ↔ Server)

| Pi Story | Depends on Server Story | Reason |
|---|---|---|
| Walk: Sync client (9) | Server Walk: Sync endpoint (US-CMP-004) | Pi pushes to server endpoint |
| Walk: E2E validation (13) | Server Walk: Health + sync running | Need server to receive data |
| Sprint: Post-drive analytics (19) | Server Crawl: CLI reports (NEW-05) | Validate server analytics on real data |
| Sprint: Backup push (23) | Server Run: Backup receiver (US-CMP-007) | Server must accept uploads |

---

## Testing Strategy

| Category | Approach |
|---|---|
| **Simulator tests** | Run existing test suite on ARM, fix failures, establish Pi baseline |
| **Display tests** | Manual validation on OSOYOO hardware (automated display testing impractical) |
| **Sync tests** | Mock HTTP endpoint on dev machine, verify sync_log behavior, retry logic |
| **Bluetooth tests** | Manual pairing checklist + automated PID query validation |
| **Integration tests** | End-to-end: simulator → SQLite → sync → server (manual, both systems running) |
| **Lifecycle tests** | Manual: power on → service start → collect → shutdown → verify data integrity |
| **Platform tests** | `@pytest.mark.pi_only` for tests requiring Pi hardware (GPIO, I2C, Bluetooth) |

---

## Spool Coordination Points

Three Spool inbox notes generated during this spec's execution:

| Phase | Topic | Question for Spool |
|---|---|---|
| Crawl | Basic display content | Are RPM, coolant, boost, AFR, speed, voltage the right 6 primary parameters? |
| Walk | Threshold visualization | Does the color mapping (blue/white/orange/red) match tiered threshold intent? Are min/max markers useful? |
| Sprint | Screen priority + data quality | What screen order for detail carousel? Review real drive data for completeness and quality. ECMLink priorities. |

Spool reviews are **gate checks**, not blocking dependencies. Ralph builds the display with reasonable defaults; Spool feedback refines content in follow-up stories if needed.

---

## Non-Goals

- No ECMLink integration (blocked until hardware install, Summer 2026)
- No auto-sync on WiFi return (manual only until proven stable)
- No web-based remote display (CLI reports on server are sufficient)
- No multi-vehicle support (one Eclipse, one Pi)
- No custom PID implementation (use standard OBD-II PIDs for now)
- No mobile app integration
- No GPS tracking

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Existing code has ARM/Linux issues | Medium | Medium | Crawl phase is entirely about finding and fixing these |
| OSOYOO display has pygame compatibility issues on Pi 5 | Medium | Medium | Fallback to headless mode; display is not blocking |
| OBDLink LX Bluetooth pairing unreliable | Medium | High | OBDLink LX is a proven dongle; log detailed BT errors for diagnosis |
| Simulator data doesn't match real Eclipse sensor behavior | High | Low | Expected — Sprint phase is where we calibrate to reality |
| UPS shutdown timing too aggressive/too slow | Medium | Medium | Configurable grace period; test in garage before driving |
| 480x320 screen too small for useful gauge display | Low | Medium | Spool helps prioritize what matters; detail screens reduce info density |
| WiFi reconnection unreliable in garage | Low | Medium | Manual sync as fallback; Pi stores data locally indefinitely |

---

## Success Criteria

| Phase | Success Looks Like |
|---|---|
| **Crawl** | Simulator runs on Pi, display shows gauges, clean startup/shutdown, test suite green on ARM |
| **Walk** | Simulated data syncs to server, display shows connectivity, server reports match |
| **Run** | Bluetooth paired, real idle data on display, VIN decoded, UPS power cycle clean |
| **Sprint** | Complete drive captured, synced, server analytics correct, Spool has reviewed data, interactive display works |

---

## Approval

| Date | Who | What |
|---|---|---|
| 2026-04-15 | CIO | Approved 4-phase approach, hostname `chi-eclipse-01`, display tiers, Spool coordination |
| 2026-04-15 | Ralph | Authored spec based on brainstorming session |
