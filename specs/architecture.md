# System Architecture

## Overview

This document describes the system architecture, technology decisions, and design patterns for the Eclipse OBD-II Performance Monitoring System.

**Last Updated**: 2026-02-01
**Author**: Michael Cornelison

---

## 1. Architecture Overview

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        External Systems                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │  OBD-II      │  │  NHTSA API   │  │   ollama     │                  │
│  │  Dongle      │  │  (VIN decode)│  │   (AI/LLM)   │                  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                  │
└─────────┼─────────────────┼─────────────────┼───────────────────────────┘
          │ Bluetooth       │ HTTP/REST       │ HTTP/REST
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Application Layer                                   │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Entry Points                                   │  │
│  │   main.py (CLI)  │  systemd service  │  shutdown.sh              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Core Services                                  │  │
│  │   obd_client/  │  analysis/  │  alerts/  │  display/             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Common Utilities                               │  │
│  │   config_validator  │  logging  │  errors  │  secrets             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Output Targets                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │   SQLite     │  │  OSOYOO      │  │   Logs       │  │   Exports   │ │
│  │   Database   │  │  Display     │  │   (files)    │  │  (CSV/JSON) │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Separation of Concerns**: Each module has a single responsibility
2. **Configuration-Driven**: All behavior externalized to config.json
3. **Fail Fast**: Validate configuration early, fail with clear messages
4. **Graceful Degradation**: Continue operating when non-critical components fail
5. **Observability**: Comprehensive logging with PII masking
6. **Profile Isolation**: Each tuning profile maintains independent data and thresholds

---

## 2. Technology Stack

### Core Technologies

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| Runtime | Python | 3.11+ | Primary language |
| Config | JSON + .env | - | Configuration management |
| Testing | pytest | 7.x | Test framework with 80% minimum coverage |
| OBD Library | python-OBD | 0.7.x | OBD-II communication |
| Display | pygame | 2.x | OSOYOO 3.5" HDMI Touch driver (480x320) |
| AI | ollama | latest | LLM inference (remote on Chi-Srv-01) |

### External Dependencies

| System | Purpose | Connection Method |
|--------|---------|-------------------|
| OBDLink LX (MAC: `00:04:3E:85:0D:FB`, FW 5.6.19) | Vehicle data acquisition | Bluetooth (ELM327 protocol) |
| NHTSA API | VIN decoding | HTTPS REST API |
| Ollama on Chi-Srv-01 | AI recommendations | HTTP (10.27.27.10:11434) -- GPU-accelerated, never local on Pi |

### Hardware

| Component | Platform | Notes |
|-----------|----------|-------|
| Processor | Raspberry Pi 5 Model B | 8GB RAM for application headroom |
| Storage | 128GB A2 U3/V30 microSD | High-endurance recommended |
| Display | OSOYOO 3.5" HDMI Touch | 480x320, capacitive touch |
| Database | SQLite (WAL mode) | Local file database |
| Power | Geekworm X1209 UPS HAT | 18650 battery backup |
| Monitoring | I2C | Battery voltage/SOC/charge-rate via MAX17048 fuel gauge at 0x36 |

**Power-source detection (AC vs battery).** The MAX17048 fuel gauge has
no AC-vs-battery sense register, and the Pi 5 PMIC `EXT5V_V` rail cannot
be used either — the Geekworm X1209 regulates that rail to ~5 V in both
wall-power and UPS-boost modes, so it looks identical whether the adapter
is plugged in or the LiPo is carrying the load.
`UpsMonitor.getPowerSource()` consumes two VCELL-only rules over a rolling
60 s history buffer:

1. **Sustained-threshold rule (primary, US-235).** If VCELL has stayed
   continuously below `vcellBatteryThresholdVolts` (default **3.95 V**)
   for at least `vcellBatteryThresholdSustainedSeconds` (default
   **30 s**), declare BATTERY. The threshold sits comfortably above the
   LiPo discharge knee (~3.7 V) and below a healthy AC-fed float
   (~4.10 V); 30 s of continuous sub-threshold data suppresses false
   positives from voltage noise.
2. **Slope rule (tuned secondary, US-235).** If the VCELL slope across
   the rolling window is strictly below `vcellSlopeThresholdVoltsPerMinute`
   (default **-0.005 V/min**, tuned from -0.02 V/min after Sprint 18
   drain tests showed real drift was slower than the old threshold),
   declare BATTERY.

Either rule firing returns BATTERY. If neither fires AND there is
decisive non-BATTERY evidence (most recent VCELL above threshold OR
slope is computable and ≥ threshold), return EXTERNAL. Otherwise return
the cached last source (EXTERNAL on first boot).

Earlier designs used the MAX17048 CRATE register's polarity as the
primary rule, but Spool's 4 drain tests across April 2026 confirmed
CRATE returns 0xFFFF (disabled) on this chip variant — the rule never
fired, leaving no way to detect wall-power loss. CRATE is still readable
via `getChargeRatePercentPerHour()` for telemetry, but does not feed
power-source detection. `EXT5V_V` via `vcgencmd pmic_read_adc EXT5V_V`
is retained as diagnostic telemetry ("is the HAT delivering power?")
but is not on the decision path. See `src/pi/hardware/ups_monitor.py`
and I-015 for background.

---

## 3. Component Architecture

### 3.1 Entry Points

Entry points coordinate high-level workflows:

```python
# src/main.py - Primary entry point
def main():
    args = parseArgs()
    config = loadConfiguration(args.config, args.envFile)
    setupLogging(config['logging']['level'])

    if args.dryRun:
        logger.info("Dry run mode - no changes will be made")
        return EXIT_SUCCESS

    return runWorkflow(config)
```

**CLI Arguments**:
- `--config/-c`: Path to configuration file (default: src/config.json)
- `--env-file/-e`: Path to environment file (default: .env)
- `--dry-run`: Run without making changes
- `--verbose/-v`: Enable DEBUG logging
- `--version`: Show version information

### 3.2 Core Services

Core services implement business logic. Each domain follows a standard subpackage structure:

```
src/obd/<domain>/
├── __init__.py      # Public API exports
├── types.py         # Enums, dataclasses, constants (no project deps)
├── exceptions.py    # Custom exceptions
├── <core>.py        # Main class implementation
└── helpers.py       # Factory functions, config helpers
```

**Implemented Domain Subpackages:**

| Domain | Purpose | Key Classes |
|--------|---------|-------------|
| `ai/` | AI-powered recommendations | AiAnalyzer, AiPromptTemplate, OllamaManager, RecommendationRanker |
| `alert/` | Threshold monitoring | AlertManager |
| `analysis/` | Statistical analysis | StatisticsEngine, ProfileStatisticsManager |
| `calibration/` | Calibration sessions | CalibrationManager, CalibrationComparator |
| `config/` | OBD configuration | loadObdConfig, validateObdConfig |
| `data/` | Data logging | ObdDataLogger, RealtimeDataLogger |
| `display/` | Display rendering | DisplayManager, drivers/, adapters/ |
| `drive/` | Drive detection | DriveDetector |
| `power/` | Power monitoring | PowerMonitor, PowerDownOrchestrator, BatteryHealthRecorder |
| `profile/` | Profile management | ProfileManager, ProfileSwitcher |
| `vehicle/` | Vehicle info | VinDecoder, StaticDataCollector |

**Top-level Packages (outside `src/obd/`):**

| Package | Purpose | Key Classes |
|---------|---------|-------------|
| `src/backup/` | Backup management | BackupManager, GoogleDriveUploader |
| `src/hardware/` | Raspberry Pi hardware | HardwareManager, UpsMonitor, ShutdownHandler, GpioButton, StatusDisplay |

See Sections 12 (Simulator) and 13 (Hardware) for detailed architecture of these components.

**Backward Compatibility:**
Original monolithic modules (e.g., `data_logger.py`) remain as facades that re-export from subpackages, ensuring existing imports continue to work.

### 3.3 Common Utilities

Shared utilities used across the application:

| Module | Purpose |
|--------|---------|
| `config_validator.py` | Validates configuration with required field checks, applies defaults via dot-notation paths |
| `secrets_loader.py` | Resolves `${VAR}` and `${VAR:default}` placeholders from environment |
| `logging_config.py` | Structured logging setup with PII masking (email, phone, SSN) |
| `error_handler.py` | Error classification (5-tier), retry decorator with exponential backoff |

### 3.4 Bluetooth Connection Resolution (Pi)

python-OBD's `obd.OBD(portstr=...)` expects a Linux serial device path like
`/dev/rfcomm0` — it does **not** perform Bluetooth discovery or binding.
Pairing and `rfcomm bind` are external prerequisites.

**Flow on Pi startup (real, non-simulator path):**

```
config.json: pi.bluetooth.macAddress = "00:04:3E:85:0D:FB"
   │
   ▼
ObdConnection.connect()
   │
   ▼
bluetooth_helper.isMacAddress(port)?
   │
   ├── yes → bluetooth_helper.bindRfcomm(mac, device=0, channel=1)
   │          │   (idempotent: no-op if already bound to same MAC;
   │          │    release+rebind if bound to a different MAC)
   │          ▼
   │        returns "/dev/rfcomm0"
   │
   └── no  → passthrough (value assumed to already be a device path;
             BC for operators who set /dev/rfcomm0 directly)
   │
   ▼
obd.OBD(portstr="/dev/rfcomm0", fast=False, timeout=...)
```

On `disconnect()`, the helper releases `/dev/rfcommN` **only when this
instance performed the bind**. When the operator supplied a literal path
(path passthrough), ownership is theirs and we never call `rfcomm release`.

**sudo policy.** `src/pi/obdii/bluetooth_helper.py` never calls `sudo` from
Python. Operators grant the service user passwordless access to
`/usr/sbin/rfcomm` via sudoers, e.g.:

```
mcornelison ALL=(root) NOPASSWD: /usr/sbin/rfcomm
```

Alternatively, `scripts/connect_obdlink.sh` wraps the same idempotent
bind/release semantics with `sudo` inside a bash script, for manual
smoke-tests and systemd-unit boot-time binding (see Sprint 14 US-196 for
unit-file persistence).

**Pairing prerequisites.** Pairing is a **separate, one-time**
operational step — the OBDLink LX uses Secure Simple Pairing (SSP) with
passkey confirmation, NOT the legacy "PIN 1234" flow. bluez's default
`NoInputNoOutput` agent handles most SSP "Just Works" devices, but the
LX firmware sends a numeric passkey and bluez prompts:

```
Confirm passkey NNNNNN (yes/no):
```

`bt-agent -c NoInputNoOutput` does not intercept this — `bt-device`'s
internal agent grabs the callback first and prompts to its own stdin. So
non-interactive pairing needs a `pexpect`-driven bluetoothctl session
that auto-confirms the passkey. That is what `scripts/pair_obdlink.sh`
does, via a bash wrapper that execs Python+pexpect inside a heredoc —
keeping shellcheck-clean arg parsing outside the pexpect block.

**Pair-mode re-trigger UX (operator-visible).** The LX drops out of
pair mode ~30s after each failed attempt. Solid blue LED = discoverable.
If pairing fails, the operator must either hold the LX button or
power-cycle the dongle before re-running the pair script. Keep within
1-2m of the Pi during pairing. Documented in `docs/testing.md`.

**Bond persistence.** Once paired/bonded/trusted, the bond survives
reboot — bluez stores it under `/var/lib/bluetooth/<adapter>/<mac>/`.
`scripts/pair_obdlink.sh` issues `trust <MAC>` after `pair`, which is
what enables the adapter to reconnect without user prompts on future
boots.

**RFCOMM bind reboot-survival.** While the bluez bond is persistent,
`rfcomm bind 0 <MAC> 1` state is NOT — it's cleared on every boot. Two
layers keep `/dev/rfcomm0` live after reboot:

1. `deploy/rfcomm-bind.service` (systemd oneshot, `After=bluetooth.service`,
   `Type=oneshot` + `RemainAfterExit=yes`). Sources MAC + channel from
   `/etc/default/obdlink` — no MAC literal in the unit file.
2. The production `ObdConnection.connect()` path calls `bluetooth_helper`
   anyway, so even if the systemd unit is missing the service self-heals
   on its first connect attempt.

Install via `deploy/install-rfcomm-bind.sh` (runs on the Pi) or let
`deploy-pi.sh --init` do it automatically — the init path writes
`/etc/default/obdlink` from the Pi's `.env` MAC and enables the unit.

**Config keys (all optional, override from defaults):**

| Key | Default | Meaning |
|-----|---------|---------|
| `pi.bluetooth.macAddress` | — | MAC **or** literal device path |
| `pi.bluetooth.rfcommDevice` | `0` | The `N` in `/dev/rfcommN` |
| `pi.bluetooth.rfcommChannel` | `1` | SPP RFCOMM channel (OBDLink LX = 1) |
| `pi.bluetooth.connectionTimeoutSeconds` | `30` | python-OBD command timeout |
| `pi.bluetooth.retryDelays` | `[1,2,4,8,16]` | Backoff delays on connect retry |

**Environment file (`/etc/default/obdlink`):**

| Key | Meaning |
|-----|---------|
| `OBD_BT_MAC` | MAC that `rfcomm-bind.service` rebinds on boot |
| `OBD_BT_CHANNEL` | SPP RFCOMM channel (defaults to 1 if unset) |

**Protocol confirmation (Session 23 empirical).** The Eclipse's ECU
answered on ISO 9141-2 K-line @ 10,400 bps via the LX; python-obd
reported `Car Connected | ISO 9141-2 | ELM327 v1.4b` on the first live
handshake. This matches the protocol documented in `specs/obd2-research.md`.

---

## 4. Data Flow

### Request Flow (OBD-II Data Acquisition)

```
1. OBD-II Client connects to Bluetooth dongle
   │
2. Polls configured realtime parameters (RPM, temp, etc.)
   │
3. Data validated and timestamped (millisecond precision)
   │
4. Threshold checker evaluates alert conditions
   │
5. Data written to SQLite (batch of 5-10 readings)
   │
6. Display updated with current values (1Hz)
```

### Analysis Flow (Post-Drive)

```
1. Drive end detected (RPM = 0 for 60 seconds)
   │
2. Statistical analysis triggered
   │  - Calculate: max, min, avg, mode, std_1, std_2
   │  - Calculate outliers: mean ± 2*std
   │
3. Results stored in statistics table with profile_id
   │
4. AI analysis triggered (if ollama available)
   │  - Prepare air/fuel ratio data window
   │  - Format prompt with vehicle context
   │
5. AI recommendations ranked and deduplicated
   │
6. Results stored in ai_recommendations table

**AI Graceful Degradation**: When ollama is unavailable (not installed, not running, or model not loaded), AI analysis is automatically skipped without affecting other system functionality. The system logs a warning on startup if AI is enabled but ollama is unavailable, then continues normal operation. Analysis requests return gracefully with an error message rather than throwing exceptions, ensuring the post-drive workflow completes successfully.
```

### Error Flow

```
1. Error occurs in any component
   │
2. Error classified by error_handler.py:
   │  - RETRYABLE: Network timeout, rate limit (429)
   │  - AUTHENTICATION: 401/403, credentials
   │  - CONFIGURATION: Missing fields, invalid values
   │  - DATA: Validation failures, parse errors
   │  - SYSTEM: Unexpected errors, resource exhaustion
   │
3. Handling based on category:
   │  Retryable: Exponential backoff (1s, 2s, 4s, 8s, 16s)
   │  Config: Fail fast with clear message
   │  Data: Log and continue/skip record
   │  System: Fail with full diagnostics
   │
4. Error logged with context, final status recorded
```

---

## 5. Database Architecture

### Schema Overview (13 Tables)

| Table | Purpose | FK to profiles? | On Delete |
|-------|---------|----------------|-----------|
| `vehicle_info` | NHTSA-decoded vehicle data, keyed by VIN | No | — |
| `profiles` | Driving profiles (daily, performance) | — (parent) | — |
| `static_data` | One-time OBD parameters (FUEL_TYPE, ECU_NAME) | FK to vehicle_info | — |
| `realtime_data` | Time-series OBD sensor readings | FK to profiles | SET NULL |
| `statistics` | Post-drive statistical analysis results | FK to profiles | CASCADE |
| `ai_recommendations` | AI-generated driving recommendations | FK to profiles, self-FK for duplicates | SET NULL |
| `calibration_sessions` | Calibration session tracking | FK to profiles | SET NULL |
| `alert_log` | Threshold violation alerts | FK to profiles | SET NULL |
| `connection_log` | OBD connection events (drive_start/end) | No FK | — |
| `power_log` | AC/battery power transitions (Pi-only, not synced) | No FK | — |
| `sync_log` | Per-table high-water mark for Pi -> server delta sync | No FK | — |
| `sqlite_sequence` | SQLite internal autoincrement tracking | — | — |

#### `sync_log` — Walk-phase sync bookkeeping (US-148)

Owned by `src.pi.data.sync_log`, decoupled from `src.pi.obdii.database` so
sync contract changes do not drag OBD schema changes through the same module.
One row per synced table; `table_name` is the PRIMARY KEY.

| Column | Type | Notes |
|--------|------|-------|
| `table_name` | TEXT PK | Name of the Pi table being tracked (must be in the sync-scope whitelist) |
| `last_synced_id` | INTEGER NOT NULL DEFAULT 0 | Highest `id` successfully pushed; US-149 SyncClient **never** advances this on failed push |
| `last_synced_at` | TEXT | ISO-8601 UTC timestamp of the last push attempt |
| `last_batch_id` | TEXT | Batch identifier for server-side traceability |
| `status` | TEXT NOT NULL DEFAULT 'pending' | CHECK constraint: `ok` \| `pending` \| `failed` |

**Sync-scope tables** (eligible for Pi -> server delta sync): `realtime_data`,
`statistics`, `profiles`, `vehicle_info`, `ai_recommendations`,
`connection_log`, `alert_log`, `calibration_sessions`.

**Excluded (Pi-only health telemetry)**: `power_log`. Stays resident on
the Pi for local diagnostics and is never uploaded.  (`battery_log` was
the companion Pi-only exclusion until US-223 deleted the table with its
sole writer `BatteryMonitor`; US-216's `PowerDownOrchestrator` + US-217's
`battery_health_log` now cover the battery-protection domain.)

##### US-194 (TD-025 + TD-026): Per-table PK registry + delta/snapshot split

The original US-148 delta query hardcoded `WHERE id > ?` and wrapped
`int(lastId)`, assuming every in-scope table had an integer `id` PK. That
assumption breaks on three of the eight tables:

- `calibration_sessions` — integer PK named `session_id`, not `id`.
- `profiles` — TEXT PK with semantic values (`'daily'`, `'performance'`).
- `vehicle_info` — TEXT PK `vin` (the actual vehicle VIN).

US-194 splits the sync set in two and adds an authoritative per-table PK
registry:

| Constant | Members | Semantic |
|----------|---------|----------|
| `sync_log.PK_COLUMN` | `{realtime_data:id, statistics:id, ai_recommendations:id, connection_log:id, alert_log:id, calibration_sessions:session_id}` | Maps each append-only table to its INTEGER PK column. Authoritative — no runtime schema introspection. |
| `sync_log.DELTA_SYNC_TABLES` | `frozenset(PK_COLUMN.keys())` | Six append-only tables eligible for delta-by-PK push. |
| `sync_log.SNAPSHOT_TABLES` | `{profiles, vehicle_info}` | TEXT-PK snapshot/upsert tables. Explicitly excluded from delta-sync; a future upsert-path story (post-Sprint 14) will add their transport. |
| `sync_log.IN_SCOPE_TABLES` | `DELTA_SYNC_TABLES ∪ SNAPSHOT_TABLES` | Unchanged whitelist (8 tables). Preserved for BC with the server payload validator, `seed_pi_fixture.py`, and integration fixtures. |

`getDeltaRows` now uses `PK_COLUMN[tableName]` for both the delta cursor
and the `ORDER BY`, and rejects snapshot tables with a clear
`"not delta-syncable"` ValueError rather than crashing on a missing
`id` column or an `int('daily')` cast.

`SyncClient.pushDelta()` returns `PushStatus.SKIPPED` (new in US-194) for
snapshot tables — a deliberate-skip status distinct from `FAILED`
(integrity problem) or `EMPTY` (no new rows). `pushAllDeltas()` still
reports one result per `IN_SCOPE_TABLES` entry, so operator output in
`scripts/sync_now.py` keeps visibility into every sync-scope table.

For `calibration_sessions`, `SyncClient` renames `session_id` → `id` in
each payload row before POSTing so the existing server rule
(`key == 'id'` → `source_id`) applies without any server-side protocol
change.

Public helpers (all take an open `sqlite3.Connection`; the module does no
connection management):
- `initDb(conn)` — idempotent CREATE TABLE IF NOT EXISTS.
- `getDeltaRows(conn, tableName, lastId, limit)` — rows with
  `PK_COLUMN[tableName] > lastId`, `ORDER BY <pk> ASC LIMIT limit`.
  Snapshot tables and unknown / out-of-scope table names raise
  `ValueError` (whitelist doubles as the SQL-injection guard — the table
  name is a SQL identifier and cannot be parameterized).
- `updateHighWaterMark(conn, tableName, lastId, batchId, status='ok')` —
  UPSERT that advances all four mutable columns atomically in a single
  transaction. Always advances `last_synced_id`; callers that need to record
  a failed-push event without advancing must use a distinct write path.
- `getHighWaterMark(conn, tableName)` — returns
  `(last_synced_id, last_synced_at, last_batch_id, status)` or the default
  `(0, None, None, 'pending')` if the row has not been created yet.

##### US-226: Sync trigger semantics + recovery playbook

The transport configuration (`pi.companionService.*`) defines HOW sync
reaches the server; `pi.sync.*` defines WHEN it fires.  Separating the
two lets operators disable the trigger without disturbing the wire
protocol (or vice-versa).

| `pi.sync.*` key | Default | Semantic |
|-----------------|---------|----------|
| `enabled` | `true` | Master switch.  `false` skips `_initializeSyncClient`; the runLoop interval gate observes `self._syncClient is None` as a no-op. |
| `intervalSeconds` | `60` | Cadence between interval-triggered pushes.  First trigger fires on the first `runLoop` pass after boot (flush-on-boot so pending rows from the previous session land immediately). |
| `triggerOn` | `['interval', 'drive_end']` | Which event sources fire a push.  `'interval'` is MANDATORY when `enabled=true` (defensive fallback; a bugged drive-end detector cannot strand rows).  `'drive_end'` hooks into `_handleDriveEnd` in `event_router.py`. |

Triggers are independent.  The drive-end trigger resets the interval
cadence so a recently-ended drive doesn't double-push on the next
interval tick.  A transport failure in one path (logged as WARNING) does
not affect the other; the high-water mark stays put per US-149 so the
next tick resends.

**Recovery playbook** — when the sync pipeline is observed stalled:

1. Confirm last-sync state (Pi side):
   ```
   ssh mcornelison@10.27.27.28 \
     'sqlite3 ~/Projects/Eclipse-01/data/obd.db \
      "SELECT table_name, last_synced_id, last_synced_at, status
        FROM sync_log ORDER BY last_synced_at DESC"'
   ```
2. Check server-side counts:
   ```
   ssh mcornelison@10.27.27.10 \
     'mysql obd2db -e "SELECT COUNT(*) FROM realtime_data"'
   ```
3. Manual flush (Walk-phase path — still valid in Run phase as an
   operator-driven override of the auto-trigger):
   ```
   python scripts/sync_now.py            # full push
   python scripts/sync_now.py --dry-run  # delta counts only
   ```
4. If the auto-trigger is silent (no `"Interval sync:"` log lines in
   `journalctl -u eclipse-obd`), check:
   * `pi.sync.enabled` — is the master switch off?
   * `pi.companionService.enabled` — is the transport off?
   * `COMPANION_API_KEY` — set in `/home/mcornelison/.env`?
   * Orchestrator log at boot should emit one of:
     `"SyncClient initialized: baseUrl=... intervalSeconds=... triggerOn=..."`
     (healthy) or
     `"SyncClient initialization failed, sync disabled: ..."` (warning).

```
┌─────────────────────┐     ┌─────────────────────┐
│    vehicle_info     │     │      profiles       │
├─────────────────────┤     ├─────────────────────┤
│ vin (PK)            │     │ id (PK)             │
│ make                │     │ name                │
│ model               │     │ description         │
│ year                │     │ alert_config_json   │
│ engine              │     │ created_at          │
│ ...                 │     └──────────┬──────────┘
└──────────┬──────────┘                │
           │                           │
┌──────────▼──────────┐     ┌──────────▼──────────┐
│    static_data      │     │   realtime_data     │
├─────────────────────┤     ├─────────────────────┤
│ id (PK)             │     │ id (PK)             │
│ vin (FK)            │     │ timestamp           │
│ parameter_name      │     │ parameter_name      │
│ value               │     │ value               │
│ unit                │     │ unit                │
│ queried_at          │     │ profile_id (FK)     │
└─────────────────────┘     └─────────────────────┘
                                       │
                            ┌──────────▼──────────┐
                            │    statistics       │
                            ├─────────────────────┤
                            │ id (PK)             │
                            │ parameter_name      │
                            │ analysis_date       │
                            │ profile_id (FK)     │
                            │ max, min, avg, mode │
                            │ std_1, std_2        │
                            │ outlier_min/max     │
                            └─────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│ ai_recommendations  │     │ calibration_sessions│
├─────────────────────┤     ├─────────────────────┤
│ id (PK)             │     │ session_id (PK)     │
│ timestamp           │     │ start_time          │
│ recommendation      │     │ end_time            │
│ priority_rank       │     │ notes               │
│ is_duplicate_of(FK) │     │ profile_id (FK)     │
│ profile_id (FK)     │     └─────────────────────┘
└─────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│    alert_log        │     │   connection_log    │
├─────────────────────┤     ├─────────────────────┤
│ id (PK)             │     │ id (PK)             │
│ timestamp           │     │ timestamp           │
│ parameter_name      │     │ event_type          │
│ value               │     │ mac_address         │
│ threshold           │     │ protocol            │
│ profile_id (FK)     │     │ details             │
└─────────────────────┘     └─────────────────────┘

┌─────────────────────┐
│     power_log       │
├─────────────────────┤
│ id (PK)             │
│ timestamp           │
│ event_type          │
│ source              │
│ details             │
└─────────────────────┘
```

### Indexes (14)

| Index | Table | Column(s) |
|-------|-------|-----------|
| `IX_realtime_data_timestamp` | realtime_data | timestamp |
| `IX_realtime_data_profile` | realtime_data | profile_id |
| `IX_realtime_data_param_timestamp` | realtime_data | parameter_name, timestamp |
| `IX_statistics_analysis_date` | statistics | analysis_date |
| `IX_statistics_profile` | statistics | profile_id |
| `IX_ai_recommendations_duplicate` | ai_recommendations | is_duplicate_of |
| `IX_alert_log_profile` | alert_log | profile_id |
| `IX_alert_log_timestamp` | alert_log | timestamp |
| `IX_connection_log_event_type` | connection_log | event_type |
| `IX_connection_log_timestamp` | connection_log | timestamp |
| `IX_power_log_timestamp` | power_log | timestamp |
| `IX_power_log_event_type` | power_log | event_type |
| `sqlite_autoindex_profiles_1` | profiles | id (auto) |
| `sqlite_autoindex_vehicle_info_1` | vehicle_info | vin (auto) |

### PRAGMAs (set per-connection by ObdDatabase.connect())

- `foreign_keys = ON`
- `journal_mode = WAL`
- `synchronous = NORMAL`

**Important**: PRAGMAs are per-connection, not persisted to the database file. Raw `sqlite3.connect()` does NOT set them -- always use `ObdDatabase.connect()`.

### Data Source Tagging (US-195, Spool CR #4; tightened US-212)

Every row written into a capture table carries a `data_source` column identifying its origin. This prevents replay / simulator / fixture rows from contaminating real-world analytics and AI prompts.

**Enum values** (closed set):

| Value | Owner | Used By |
|-------|-------|---------|
| `real` | Live OBD path | Pi collector, DB-level DEFAULT |
| `replay` | Flat-file replay harness (US-191, B-045) | Deterministic SQLite fixtures seeded ahead of a sync test |
| `physics_sim` | Physics simulator (SensorSimulator / scenario runner) | Simulator-driven captures + `scripts/seed_scenarios.py` output |
| `fixture` | Regression fixture seeder | `scripts/seed_pi_fixture.py` rows + hand-rolled test fixtures |

**Scope** — tables that carry the column (both Pi SQLite and server MariaDB): `realtime_data`, `connection_log`, `statistics`, `calibration_sessions`, `profiles`. Server also adds it to analytics `drive_summary`, and US-204 adds it to `dtc_log`. Tables that can only ever carry real data (`vehicle_info`, `sync_log`, `ai_recommendations`, `alert_log`, `power_log`) do not need the column.  (`battery_log` was also in this list until US-223 deleted the table with its writer BatteryMonitor.)

**Default** — `'real'` at the DB level is a **narrow safety net for the single live-OBD collector path**, NOT a catchall for dev writers. Writers outside the live-OBD path MUST pass `data_source` explicitly at the call site. The live-OBD writer (:class:`src.pi.obdii.data.logger.ObdDataLogger` + :func:`src.pi.obdii.data.helpers.logReading`) honors this contract by auto-deriving the tag from `connection.isSimulated`: real connections produce `'real'`, :class:`SimulatedObdConnection` produces `'physics_sim'`. An explicit `dataSource=` override wins in both constructors so fixture harnesses can tag correctly. The call-site discipline is enforced by `tests/pi/data/test_data_source_hygiene.py`, an AST audit that fails the suite if any seed script INSERT into a capture table omits the `data_source` column (US-212 closed the ~352K-row hygiene bug surfaced by US-205).

**Filter rule** — server-side analytics, AI prompt inputs, and baseline calibrations MUST filter `WHERE data_source = 'real'` unless the caller is running a synthetic test. Pre-US-195 rows with `data_source IS NULL` are treated as `'real'` for backward compatibility.

**Migration** — idempotent at Pi boot via `src/pi/obdii/data_source.py::ensureAllCaptureTables()` (called from `ObdDatabase.initialize()`). Adds the column with `DEFAULT 'real'` to any pre-US-195 table; SQLite applies the default to every existing row in place. No backfill UPDATE is scripted — Session 23's 149 real-run rows are inherently `'real'` once the column lands.

### Drive Lifecycle (US-200, Spool Priority 3)

Captures are scoped to a specific drive via a `drive_id INTEGER` column on `realtime_data`, `connection_log`, `statistics`, and `alert_log` (Pi SQLite + server MariaDB). A row-level id lets server analytics ask *"give me the warmup curve of drive N"* without reconstructing boundaries from connection_log timestamps.

**Engine state machine** — `src/pi/obdii/engine_state.py::EngineStateMachine` classifies RPM + speed observations into four states:

| State | Entry condition |
|-------|-----------------|
| `UNKNOWN` | Initial, no RPM yet |
| `CRANKING` | RPM rises to ≥ 250 (default `crankingRpmThreshold`) from any non-running state |
| `RUNNING` | RPM climbs to ≥ 500 (default `runningRpmThreshold`) while `CRANKING` |
| `KEY_OFF` | RPM = 0 AND speed = 0 continuously for `keyOffDurationSeconds` (default 30s) while `RUNNING`, OR `forceKeyOff()` called |

**drive_id generation** — on `UNKNOWN → CRANKING` and `KEY_OFF → CRANKING` transitions the machine calls an injected `driveIdGenerator`. The production generator is `drive_id.makeDriveIdGenerator(conn)` backed by a single-row `drive_counter` table (monotonic, crash-safe, NTP-skew-immune). Once minted, the id remains stable across `CRANKING → RUNNING` and is cleared on `* → KEY_OFF`.

**Writer plumbing** — a process-wide context `drive_id._currentDriveId` (set via `setCurrentDriveId` / `getCurrentDriveId`) is updated by `DriveDetector._startDrive` / `_endDrive`. The four writers that know about an active drive consult the context at INSERT time:

| Writer | Site |
|--------|------|
| realtime_data | `pi.obdii.data.helpers.logReading` + `ObdDataLogger.logReading` |
| connection_log (drive events only) | `pi.obdii.drive.detector.DriveDetector._logDriveEvent` |
| statistics | `pi.analysis.engine.StatisticsEngine._storeStatistics` |
| alert_log | `pi.alert.manager.AlertManager._logAlertToDatabase` |

Writers outside a drive (boot/shutdown connection events, startup hardware alerts) leave `drive_id` NULL — that's the correct signal that the row doesn't belong to a drive.

**Invariants** (US-200):

1. drive_id is assigned ONCE on CRANKING entry and stable until KEY_OFF.
2. Monotonic Pi-local sequence — no wall-clock ms (NTP-resync-safe).
3. Engine state is RPM/speed-driven; BT disconnect is ONE input (`forceKeyOff`), not the primary driver.
4. No retroactive backfill — the Pi operational store was truncated per CIO directive 2026-04-20 via `scripts/truncate_session23.py --execute` (US-205, Sprint 15) after US-209 closed the server schema catch-up. Pre-US-200 rows (Session 23's 149 real-capture rows plus ~491K benchtest rows that inherited `data_source='real'` via the DEFAULT — see Spool amendment 3 / future-TD for the hygiene bug) were deleted from `realtime_data`, `connection_log`, `statistics` on both Pi SQLite and the chi-srv-01 MariaDB. `drive_counter.last_drive_id` reset to 0 on both sides. The regression fixture `data/regression/pi-inputs/eclipse_idle.db` (SHA-256 `0b90b188…`, 188,416 bytes) was hash-verified pre and post and is untouched. The next real Eclipse drive now mints `drive_id=1`. Pi `eclipse-obd.service` left stopped post-truncate to preserve the clean slate against the benchtest hygiene bug — operator restores the service (`sudo systemctl start eclipse-obd.service`) before the first real drive.

   **Second operational truncate 2026-04-27 (US-227, Sprint 18)** — a second hygiene wave was needed after Spool's post-deploy review of Drive 3 surfaced 2,939,090 rows tagged `data_source='real'` on `drive_id=1` spanning 2026-04-21 02:27 → 2026-04-23 03:12 UTC (car not running). Same root cause as US-205 (pre-US-212 hygiene bug — benchtest leakage inheriting the `'real'` DEFAULT before the explicit-tagging fix took effect), but with a critical difference: by the time US-227 ran, Drive 3 (the first multi-minute real drive on record, 6,089 rows on `drive_id=3`) was already in the database and MUST be preserved. The Sprint 18 script (`scripts/truncate_drive_id_1_pollution.py`) narrows the WHERE clause accordingly — `DELETE WHERE drive_id=1 AND data_source='real'` — so Drive 3 + Drive 2 sim rows + the 584 NULL-`drive_id` orphans (US-233 territory) all stay. `drive_counter.last_drive_id` is advanced to 3 (post-Drive-3 high-water) idempotently — never regressed, even if a later drive has already moved it forward. A pre-flight sync gate refuses `--execute` unless `sync_log.realtime_data.last_synced_id ≥ 3,439,960` (Drive 3's max id) so the local DELETE never runs while Drive 3 is stranded on the Pi. Same fixture-hash invariant as US-205 (pre + post SHA-256 assertion). Same Pi-service stop / start envelope around the DELETE. Sentinel filename `.us227-dry-run-ok` keeps the gate distinct from `.us205-dry-run-ok`. The pollution window 2026-04-21 .. 2026-04-23 also drives an orphan scan on server `ai_recommendations.created_at` and `calibration_sessions.start_time` — non-zero counts halt the run per US-227 stopCondition #2. After US-227 ships, the Pi keeps Drive 3 + Drive 2 sim + NULL-`drive_id` rows and otherwise returns to a clean baseline; future real drives mint `drive_id=4` onward.

**Drive-end detection (US-229)** — `DriveDetector._endDrive` can fire via two independent paths that must *both* be reliable:

| Path | Trigger | Where |
|------|---------|-------|
| **RPM-debounce** (primary) | `RPM ≤ driveEndRpmThreshold` (default `0`) for `driveEndDurationSeconds` (default `60s`) | `_processRpmValue` on each RPM tick |
| **ECU silence** (fallback) | No ECU-sourced `processValue` call for `driveEndDurationSeconds` while `_currentSession` is open | `_checkEcuSilenceDriveEnd` on *every* `processValue` tick |

The fallback path exists because the RPM-debounce signal collapses when the ECU stops responding entirely post-engine-off: python-obd returns null for RPM, `event_router` skips the `processValue` call (`value is None` guard), and the below-threshold timer never starts — the drive remains open indefinitely. Drive 3 (2026-04-23 engine-off 16:46:21 UTC) showed this exact symptom for 6+ minutes because `BATTERY_V` via `ELM_VOLTAGE` (ATRV, adapter-level) kept firing `processValue` ticks without any ECU-sourced reading in between.

The silence path distinguishes ECU-sourced vs adapter-level parameters via `decoders.isEcuDependentParameter(name)`:

- `PARAMETER_DECODERS` entries carry an explicit `isEcuDependent: bool` field (6/7 entries `True`; only `BATTERY_V` / `ELM_VOLTAGE` is `False`).
- Legacy Mode 01 PIDs polled via the getattr fallback path (RPM, SPEED, COOLANT_TEMP, ENGINE_LOAD, THROTTLE_POS, TIMING_ADVANCE, SHORT_FUEL_TRIM_1, LONG_FUEL_TRIM_1, INTAKE_TEMP, O2_B1S1, CONTROL_MODULE_VOLTAGE, INTAKE_PRESSURE) are enumerated in `decoders.LEGACY_ECU_PARAMETERS` and return `True`.
- Unknown / future adapter commands default to `False` (safe default: an unknown parameter won't extend drive_end spuriously).

On each `processValue` tick the detector stamps `_lastEcuReadingTime = now` when the parameter is ECU-dependent, then runs `_checkEcuSilenceDriveEnd(now)`: if `_currentSession` is open, `_driveState ∈ {RUNNING, STOPPING}`, and `now - _lastEcuReadingTime ≥ driveEndDurationSeconds`, the detector calls `_endDrive()`. Adapter-level ticks advance the check without resetting the timer — exactly the wake-up we need during ECU-silence-plus-ELM-heartbeat.

`_startDrive` seeds `_lastEcuReadingTime = startTime` so the silence check doesn't fire on the first tick after drive-start before the first Mode 01 poll lands. `_endDrive` clears it to `None` so a subsequent drive-start reseeds cleanly. Both drive-end paths converge on the same `_endDrive` entry point, which is idempotent (`if not self._currentSession: return`), so a rare race where RPM-debounce and ECU-silence both want to fire in the same tick is harmless.

**Pre-mint orphan policy (US-233)** — the python-obd capture loop opens a `realtime_data` writer the moment Bluetooth links to the OBDLink LX, but `EngineStateMachine` does not mint a `drive_id` until the RPM crossing fires `UNKNOWN/KEY_OFF → CRANKING`. Rows captured during that BT-connect-to-cranking window land with `drive_id IS NULL AND data_source = 'real'` — they belong to the *next* drive but were written before the id existed. Drive 3 (2026-04-23) shipped 225 such rows over 39 seconds (16:36:10 → 16:36:49Z) before drive_id=3 was minted at 16:36:50Z.

Policy: **option (a) — post-hoc backfill via `scripts/backfill_premint_orphans.py`.** The script associates each NULL-drive_id real row with the *nearest subsequent* `drive_id` whose `MIN(timestamp)` falls within `--window-seconds` (default 60s). Rows with no drive_start within the cap stay NULL — that's the correct signal for pre-US-212 pollution and other rows that don't belong to any drive.

Why not (b) provisional drive_id at BT-connect, or (c) document NULL as authoritative:

* (b) would change the US-200 state machine, risking `drive_summary` collisions and `connection_log` drive-event ordering vs. the US-200 invariants. Mid-window BT disconnect would orphan the provisional id with no clean recovery.
* (c) leaves Spool unable to include the BT-connect window in his per-drive analysis (warm-engine-fingerprint, baseline coolant, pre-cranking battery V) — and the rows are unambiguously associable in practice (single-drive Pi, drive_start visible in raw data, hard-cap window).

Backfill invariants:

1. **Idempotent.** Re-running on an already-backfilled DB matches zero rows (the orphan scan returns NULL-drive_id rows only).
2. **Hard cap window.** Default 60s; configurable via `--window-seconds`. Orphans with no subsequent drive within the cap MUST stay NULL — never be assigned to a much-later drive.
3. **Per-drive safety cap.** Default 1000 orphans per drive; if exceeded, the script raises `SafetyCapError` rather than silently associating millions of rows to a single drive_id (defensive against a divergent schema state).
4. **Tagged rows are inviolate.** The UPDATE WHERE clause requires `drive_id IS NULL AND data_source = 'real'`, so even a stale `BackfillMatch` cannot clobber a row that already has a non-NULL drive_id.
5. **Scope: `realtime_data` only.** `drive_summary`, `connection_log`, `statistics`, `alert_log` are not touched. Server-side propagation of the new drive_id values is deferred — the cursor-based sync uses `synced_at`, so a re-tagged row will not re-sync; server-side cleanup is a separate concern flagged in the closure inbox note.
6. **Session 23 fixture is out-of-scope.** The regression fixture `data/regression/pi-inputs/eclipse_idle.db` (188,416 bytes, SHA-256 `0b90b188…`) is a separate file; the script operates on the live DB at `data/obd.db` (or whatever path `--db` names) and never touches the fixture.

**Server-side pre-mint orphan policy (US-240, Sprint 19)** — `scripts/backfill_server_premint_orphans.py` is the server-side mirror of US-233 for the chi-srv-01 MariaDB `realtime_data` table. Same algorithm (orphan → nearest subsequent `drive_id` whose `MIN(timestamp)` falls within `--window-seconds`, default 60s), same per-drive cap, same idempotent re-run, same UPDATE WHERE-clause guard. Two deltas from the Pi-side:

1. **Transport.** SSH + `mysql -B -N` via the address + credential loaders re-exported from `scripts/apply_server_migrations.py` (no plumbing duplication). Backup uses `mysqldump --single-transaction` of the `realtime_data` table to `/tmp/obd2-us240-backup-<ts>.sql` on the server, with the same 60s / 500 MB safety ceilings as US-209. Distinct dry-run sentinel `.us240-dry-run-ok` (so a Pi-side US-233 dry-run cannot silently authorize a server execute).
2. **Explicit post-engine-off exclusion.** Per US-229, the Pi's adapter-level polls (BATTERY_V via `ELM_VOLTAGE`) continue after `engine_state` goes KEY_OFF. Those rows arrive on the server with `drive_id IS NULL AND data_source = 'real'` even though they are not part of any drive — they post-date the latest drive's `MAX(timestamp)`. The matcher excludes them via two paired checks: (a) any orphan whose timestamp is past the maximum `driveEndTimestamp` across all known drives stays NULL by design; (b) a defense-in-depth between-drives check skips orphans that are closer to a prior drive's end than to the next drive's start, so even a widened `--window-seconds` cannot pull a post-engine-off row into a future drive.

Pre-flight at story start (2026-04-30): 8,782 NULL-drive_id real rows on the server across drives {3, 4, 5}; the matcher associated 156 to drive_id=4 (81 rows) and drive_id=5 (75 rows), all within an 11-second max gap. The remaining 8,626 stay NULL — pre-Drive-4 pollution (carried over from the US-227 era), between-drive gaps, and post-Drive-5-engine-off accumulation. Drive 3 contributes zero matches because its BT-connect orphans were tagged `drive_id=1` by the pre-US-212 code and were already DELETEd by US-227's pollution truncate.

**Migration** — `drive_id.ensureAllDriveIdColumns(conn)` (called from `ObdDatabase.initialize()`) idempotently `ALTER TABLE`s every pre-US-200 schema and creates `IX_<table>_drive_id` indexes. `ensureDriveCounter(conn)` seeds the singleton row at `last_drive_id = 0`.

**Server schema catch-up (US-209, Sprint 15)** — the SQLAlchemy model changes from US-195 (`data_source`) and US-200 (`drive_id`, `drive_counter`) shipped in Sessions 65 / 66 but never ran as `ALTER TABLE` / `CREATE TABLE` on the live chi-srv-01 MariaDB. CI tested against ephemeral SQLite and did not catch the gap. `scripts/apply_server_migrations.py` (US-209) closes this for the four capture tables (`realtime_data`, `connection_log`, `statistics`, `alert_log` — `alert_log` drive_id only, no data_source per the Pi-side carve-out), plus `profiles` / `calibration_sessions` (data_source only), plus the `drive_counter` singleton. Safety posture matches US-205: `--dry-run` probes `INFORMATION_SCHEMA` and prints the plan; `--execute` refuses without a prior dry-run sentinel, backs up affected tables via `mysqldump --single-transaction`, and enforces per-statement timing guards (30s per ALTER; 60s + 500 MB ceilings on the backup). Idempotent: re-running on a fully-migrated DB emits zero DDL. See `TD-029` for the underlying deploy-flow gap and Sprint 16+ root-cause fix (Alembic or explicit migration gate in `deploy-server.sh`).

**Server analytics** — `src/server/analytics/basic.py::collectReadingsForDrive(session, driveId, deviceId)` is the preferred per-drive query. Filters `drive_id = ? AND data_source IN ('real', NULL) AND source_device = ?`. Preferred over the legacy time-window `_collectReadings` path for post-US-200 drives because drive_id is row-level and cheaper than a time-range scan.

**End-to-end verification** — `scripts/validate_first_real_drive.sh` (US-208, Sprint 15) is the CIO-runnable validator that confirms the full Sprint 14+15 capture surface lands on an actual drive: canonical ISO-8601Z timestamps, drive_id inheritance, data_source tagging, 21+ Mode 01 PIDs + ELM_VOLTAGE, DTC Mode 03/07 capture, drive_summary row, Pi→server sync, report.py summary, and Spool `/analyze` smoke. Activity-gated: runs against the latest `drive_id` on the Pi (or `--drive-id N`) and is read-only against both DBs. Off-Pi test path at `tests/pi/integration/test_first_drive_replay.py` exercises the query paths against a synthesized fixture so the validator is testable without a live drive. Drill protocol (I-016): the validator surfaces **BENIGN / ESCALATE / INCONCLUSIVE** for the coolant-thermostat disposition based on `MAX(coolant_temp)` vs the 82 C gate and duration vs 15-min sustained-warmup gate. Full procedure: `docs/testing.md` → "First Real Drive Validation".

**Post-drive review ritual (US-219, Sprint 16)** — `scripts/post_drive_review.sh` is the CIO-facing wrapper that runs after every real drive.  It orchestrates the already-shipped pieces — `scripts/report.py --drive-id N` (numeric summary), `scripts/spool_prompt_invoke.py --drive-id N` (renders Spool's Jinja prompt against live analytics and calls Ollama `/api/chat`), a `cat` of `offices/tuner/drive-review-checklist.md`, and a "where to record findings" pointer to `offices/tuner/reviews/` or `offices/pm/inbox/`.  The prompt templates themselves (`src/server/services/prompts/system_message.txt` + `user_message.jinja`) are reused verbatim; the CLI imports `_buildAnalyticsContext`, `_loadSystemMessage`, `_renderUserMessage`, and `_parseRecommendations` from `src.server.services.analysis` so the interactive review and the server's auto-analysis path emit byte-identical prompts.  Ollama base URL, model, and timeout come exclusively from `config.json`'s `server.ai` block (with `${ENV_VAR}` expansion) — never hardcoded.  All "information flow" outcomes (no drive, empty drive, missing tables, Ollama unreachable or HTTP-erroring, empty JSON array) exit 0 so the checklist + pointer steps still run and the CIO can always read all four sections.  Exit code 2 is reserved for argument parsing.  Full procedure: `docs/testing.md` → "Post-Drive Review Ritual".

### Drive-Start Metadata (US-206, Spool Priority 5 + 7)

On every `UNKNOWN/KEY_OFF → CRANKING` transition the Pi captures three values from the most-recent reading snapshot and writes one row to the `drive_summary` capture table:

| Column | Source | Cold-start rule |
|--------|--------|-----------------|
| `ambient_temp_at_start_c` | PID 0x0F (IAT) | Captured ONLY when `fromState ∈ {UNKNOWN, KEY_OFF}`; NULL on warm-restart (Spool Priority 7 — warm intakes are heat-soaked, not ambient). |
| `starting_battery_v` | `ELM_VOLTAGE` (ATRV, US-199) | Captured every drive; pre-cranking loads give the contextualised battery baseline Spool wants for cranking-current-drop analysis. |
| `barometric_kpa_at_start` | PID 0x33 | Captured every drive; pinned once since baro doesn't change mid-drive (Spool Priority 5). Chicago baseline ~101.3 kPa; weather range 97–103 kPa; altitude negligible. |

**Table shape** — Pi SQLite `drive_summary`: `drive_id INTEGER PRIMARY KEY`, three metadata columns (nullable), `drive_start_timestamp DATETIME DEFAULT strftime('%Y-%m-%dT%H:%M:%SZ','now')` (canonical ISO-8601 UTC per US-202), `data_source TEXT DEFAULT 'real'` with CHECK enum. UPSERT semantics on a row that already exists: re-calling `SummaryRecorder.captureDriveStart` with the same `drive_id` UPDATEs (clobbering) the row (acceptance #4 idempotency, US-206 replay path).  US-236 changes the **missing-row** semantics — see "Cold-start defer-INSERT (US-236)" below.

**Invariants**:

1. Zero new Mode 01 polls — `SummaryRecorder` consumes `ObdDataLogger.getLatestReadings()` (read-only snapshot) and never dispatches fresh ECU queries.
2. NULL ambient is semantically meaningful — analytics treat it as "ambient unknown" and skip the IAT-caution interpretation; do NOT fill it with a fabricated value on warm restarts.
3. drive_summary row inherits the minted `drive_id` from `_startDrive`; it NEVER mints a new one.
4. Timestamps are always written via the schema DEFAULT (no Python `datetime.now()` at the Pi writer — aligns with US-202 / TD-027).

**Capture site** — `DriveDetector._startDrive → _armDriveSummaryDeferInsert()` fires AFTER `_openDriveId` publishes the id on the process context and BEFORE the external `onDriveStart` callback.  No `drive_summary` write happens at drive_start itself (US-236 — see below).  The deferred state machine drives the eventual write from inside `processValue` ticks; recorder failures inside that loop are logged and swallowed so drive recording itself is never aborted by a summary-write error.

**Cold-start defer-INSERT (US-236, replaces Sprint 18 US-228)** — `drive_start` fires on RPM crossing the threshold, which routinely beats the first IAT / BATTERY_V / BAROMETRIC_KPA reading from the ECU.  Sprint 18's US-228 attempted to fix this by INSERTing an all-NULL row at drive_start and UPDATE-backfilling the columns as readings arrived; empirically, that path failed across drives 3, 4, 5 (every row stayed all-NULL).  Sprint 19's US-236 switches to **Option (a) defer-INSERT**: the row only appears once data is actually available, eliminating the "INSERTed-then-never-filled" failure mode by construction.

**Defer-INSERT state machine** — `DriveDetector._armDriveSummaryDeferInsert(startTime)` arms three pieces of per-drive state at `_startDrive`:

* `_driveSummaryBackfillDriveId` (the drive being captured)
* `_driveSummaryBackfillDeadline` (`startTime + driveSummaryBackfillSeconds`, default 60s)
* `_driveSummaryBackfillFromState` (snapshot of `_lastEngineState` -- the warm/cold rule sees the PRE-drive state for the entire window)
* `_driveSummaryInserted = False` flag

Each `processValue` tick calls `_maybeProgressDriveSummary(now)` which runs one of two phases:

1. **Defer-INSERT phase** (`_driveSummaryInserted=False`): pulls the latest reading snapshot, calls `SummaryRecorder.captureDriveStart(driveId, snapshot, fromState, forceInsert=deadlineExpired, reason=...)`.  The recorder's behavior:
   * Row missing + post-cold-start-rule payload all-NULL + `forceInsert=False` -> **deferred no-op** (`inserted=False, deferred=True`).  Detector keeps ticking.
   * Row missing + at least one of IAT/BATTERY_V/BARO present -> **INSERT** with available data (`inserted=True`).  Detector flips `_driveSummaryInserted=True` and transitions to backfill phase.
   * Row missing + `forceInsert=True` (60s deadline reached) -> **INSERT** with whatever's in the snapshot (possibly all-NULL).  `result.reason='no_readings_within_timeout'` propagates to the detector for operator-visible logging; the row itself does NOT carry the reason (table schema is fixed -- `reason` lives in logs + result objects only).
2. **Backfill phase** (`_driveSummaryInserted=True`): runs the existing `SummaryRecorder.backfillFromSnapshot` UPDATE-NULL loop until the row is complete (all 3 fields non-NULL, OR battery+baro on warm restart) OR the deadline expires.

**Defer-INSERT invariants**:

1. **No row at drive_start.** The `drive_summary` row only appears after the first IAT/BATTERY_V/BARO reading arrives, OR at the 60s deadline via `forceInsert=True`.  This is the **runtime-validation discriminator** -- a synthetic test that asserts "no row exists immediately after drive_start with empty snapshot" must FAIL against pre-US-236 code (which INSERTed all-NULL at drive_start) and PASS post-US-236 (per `feedback_runtime_validation_required`).
2. **Warm-restart payload-empty defers too.**  A warm restart with IAT-only in the snapshot has its IAT filtered by the cold-start rule, so the post-cold-start payload is all-NULL.  Defer-INSERT no-ops until BATTERY_V or BAROMETRIC_KPA arrives (or the deadline).  This avoids creating an all-NULL warm-restart row.
3. **The 60s deadline is a hard upper bound.**  No dynamic extension.  At the deadline, `forceInsert=True` ALWAYS produces a row even when the ECU stayed silent the entire window -- analytics need to see that the drive happened (the row's all-NULL columns + the propagated `reason` document the silence).
4. **Re-entry safety.**  A new `_startDrive` arms a fresh deferred state, overwriting any previous pending drive's state.  The recorder is stateless across calls; two pending defer-INSERTs for different `drive_id`s don't interfere.  `_endDrive` clears the deferred state so a late telemetry tick can never write to the just-ended drive.
5. **`SummaryRecorder.backfillFromSnapshot` semantics unchanged.**  Still a no-op on missing rows; still never clobbers non-NULL stored values; still respects the warm-restart rule.

**Engine-state tracking** — `DriveDetector` keeps a lightweight `_lastEngineState` (defaults to `UNKNOWN` at boot; set to `KEY_OFF` inside `_endDrive` after the clean debounce; set to `RUNNING` after a successful drive-start). The recorder reads this attribute for the cold-start rule. This is deliberately minimal: the full `EngineStateMachine` (US-200) is the authoritative classifier, but US-206 only needs the from-state at drive-start entry, and wiring the full machine into the RPM-threshold-driven `DriveDetector` is out of scope.

**Server mirror** — the Pi's `drive_summary` capture table syncs into the server-side `DriveSummary` SQLAlchemy model. The model was extended in US-206 (nullable `source_id`, `source_device`, `synced_at`, `sync_batch_id`, `drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start`, `drive_id`) + `UNIQUE(source_device, source_id)` for the Pi-sync path.  The live MariaDB physical table reaches that shape via deploy-time migration `v0004_us237_drive_summary_reconcile.py` (Sprint 19) -- the Sprint-7-8 era table predated those columns and Sprint 16 US-213 / US-209 catch-up scope did not include `drive_summary`, so 148 Pi-sync attempts failed with `Unknown column 'drive_summary.source_id'` between Sprint 18 deploy and 2026-04-29.  v0004 ALTERs the 11 missing columns + adds `IX_drive_summary_drive_id` + `uq_drive_summary_source` then truncates the 9 Sprint-7-8 sim rows (`device_id IN ('sim-eclipse-gst', 'sim-eclipse-gst-multi', 'eclipse-gst-day1')`) and cascade-deletes their `drive_statistics` children (V-4 namespace cleanup, CIO directive 2026-04-29 -- the legacy auto-incremented ids 1-10 collide with Pi-minted drive_ids).  See Section 5 Server Schema Migrations subsection for migration registry mechanics.

**Sync shape** — `sync_log.PK_COLUMN['drive_summary'] = 'drive_id'`; the Pi sync client's `_renamePkToId` renames `drive_id → id` on the wire; the server maps `id → source_id` per its existing rule (US-194 pattern). Delta cursor is the monotonic `drive_id`.

**Reconciled single-writer semantics (US-214)** — US-206 shipped as a dual-writer table (two rows per drive: analytics-keyed + Pi-sync-keyed) so the capture story could ship without perturbing analytics code. US-214 converges on **one row per drive** via Option 1 (Pi writes first, analytics updates):

1. **Pi-sync writes first** at drive start with `source_device`, `source_id = drive_id`, `drive_id`, and the three metadata columns. Analytics fields (`device_id`, `start_time`, `end_time`, `duration_seconds`, `row_count`, `is_real`) stay NULL until analytics runs.
2. **Analytics runs at drive-end** via the auto-analysis trigger in `/sync`. `_ensureDriveSummary` receives the `drive_id` from the extended `extractDriveBoundaries` (US-214 extended it to extract `drive_id` from the `connection_log` rows), finds the Pi-sync row by `(source_device, drive_id)`, and UPDATES the analytics fields in place. `is_real = True` is set at this step (Pi-sync-only rows stay NULL until analytics confirms).
3. **Legacy path** (pre-US-200 data with no `drive_id` in connection_log) falls back to the historical `(device_id, start_time)` find-or-create. These rows leave `source_device`/`source_id`/`drive_id` NULL. SQL's NULL-is-distinct UNIQUE semantics keeps multiple legacy rows legal.
4. **Race / out-of-order sync**: if analytics runs before Pi-sync lands, `_ensureDriveSummary` INSERTs a fully-populated row with both halves. A later Pi-sync of the same `(source_device, source_id)` lands on that row via the UNIQUE constraint and only overwrites its own columns (`_PRESERVE_ON_UPDATE` + the fact Pi doesn't send `is_real`/`start_time`/etc. means analytics fields survive the upsert).

**One-shot migration** — `scripts/reconcile_drive_summary.py` merges pre-existing dual rows on the live DB. For each analytics-only row it finds a matching Pi-sync row (`device_id == source_device` AND `start_time` within 60s of `drive_start_timestamp`), copies analytics fields into the Pi-sync row, redirects `drive_statistics` / `anomaly_log` `drive_id` pointers onto the surviving row, then deletes the analytics-only row. Idempotent — re-runs find no unreconciled pairs. Run `--dry-run` first, then `--execute`. Analytics-only rows with no Pi-sync partner (pre-US-200 drives) stay as-is; the migration reports the orphan count so the operator can decide.

**Invariants**:
- One row per `(source_device, drive_id)` for post-US-200 drives.
- `is_real = TRUE` only after analytics confirms at drive-end. Pi-sync-only rows pre-analytics have `is_real = NULL`.
- Pi-sync writer owns metadata columns (`drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start`). Analytics must not overwrite them.
- `drive_summary` table name is permanent (renaming was rejected in US-206 as too invasive).

### Collector Resilience (US-211, Spool Session 6 Story 2)

Spool Session 6 confirmed CIO's hypothesis: a BT drop today kills the
collector. US-211 adds a Python-side resilience layer so the collector
process stays alive across BT flaps and only surfaces FATAL errors to
systemd (Restart=always, US-210).

**Error taxonomy** — the capture loop classifies raised exceptions at
the capture boundary via
`src/pi/obdii/error_classification.classifyCaptureError()`:

| Class | Trigger | Reaction |
|-------|---------|----------|
| `ADAPTER_UNREACHABLE` | `OSError`/`FileNotFoundError`/`PermissionError` against /dev/rfcomm\*, `BluetoothHelperError`, `ObdConnectionError` with rfcomm/bluez/rfcomm-timeout string | Close python-obd, log `bt_disconnect`, run reconnect-wait loop, reopen on probe-success |
| `ECU_SILENT` | Plain `TimeoutError`/`ObdConnectionTimeoutError` without adapter signature, ambiguous `ObdConnectionError` | Stay connected, log `ecu_silent_wait`, caller reduces poll cadence |
| `FATAL` | Everything else (including `KeyboardInterrupt`, `SystemExit`, `MemoryError`) | Re-raise; systemd `Restart=always` handles process restart |

**Reconnect-wait loop** — `src/pi/obdii/reconnect_loop.ReconnectLoop`
implements Spool's backoff grounding verbatim: `(1, 5, 10, 30, 60)`
seconds capped at 60 thereafter. The loop accepts an injected probe
(`bluetooth_helper.isRfcommReachable` by default), event logger
(`connection_logger.logConnectionEvent` by default), and sleep
function so unit tests run in ~0 wall-clock. `reset()` rewinds the
schedule after a successful reconnect -- the next BT flap starts at
1s, not at the cap.

**Adapter-reachability probe** — `isRfcommReachable` is two-layered and
lightweight: stat `/dev/rfcomm{N}` first (short-circuits when the
kernel node is missing, e.g. post-boot before bind) then `rfcomm show
N` to confirm the MAC is still bound. NO full `obd.OBD()`
reconstruction in the probe -- that's expensive and stateful; the
caller owns the python-obd reopen after the probe returns `True`.

**Orchestrator wiring** — `src/pi/obdii/orchestrator/bt_resilience.BtResilienceMixin`
exposes `handleCaptureError(exc)` on `ApplicationOrchestrator`. The
existing `ConnectionRecoveryMixin` (background-threaded, state-change-
driven) is not replaced; it coexists with the new synchronous error-
class-driven path. Data-logger callers invoke `handleCaptureError`
whenever python-obd raises from the capture path.

**Capture-loop integration (US-221)** — the live wiring from Spool's
Sprint 16 YELLOW concern. `RealtimeDataLogger.__init__` accepts two
dependency-injection kwargs:

- `captureErrorHandler: Callable[[BaseException], CaptureErrorClass]`
  — production wires `ApplicationOrchestrator.handleCaptureError`.
- `onFatalError: Callable[[BaseException], None]`
  — production wires `LifecycleMixin._onCaptureFatalError`, which
  flips `_shutdownState` to `FORCE_EXIT` with `EXIT_CODE_FORCED` so
  systemd `Restart=always` bounces the process on genuinely broken
  state.

`RealtimeDataLogger._queryParameterSafe` unwraps the `__cause__` from
`ParameterReadError` wrappers so the underlying capture-boundary
exception (e.g. `OSError` from /dev/rfcomm loss) reaches
`_pollCycle`'s classifier branch -- without this unwrap,
`queryParameter`'s `raise ParameterReadError(...) from e` would mask
the real cause and the classifier would see only the wrapper. Benign
null responses (ParameterReadError with `__cause__=None`) still
short-circuit as they always have.

`_pollCycle` routes unexpected exceptions through
`_routeCaptureError`:

- **ADAPTER_UNREACHABLE** — handler synchronously tore down python-obd,
  ran the reconnect loop, reopened. Loop breaks out of the current
  cycle and starts the next one fresh. Process stays alive. Same PID.
- **ECU_SILENT** — handler logged `ecu_silent_wait`. Loop enters
  silent mode: `_getEffectivePollingIntervalMs()` multiplies by
  `DEFAULT_ECU_SILENT_MULTIPLIER=5` until the next successful query
  clears the flag (see `_onSuccessfulQuery`). Connection stays open.
- **FATAL** — handler re-raised. Loop sets `_stopEvent`, invokes
  `onFatalError(exc)` which marks the orchestrator for forced exit.
  The main thread observes the shutdown state and exits with code 2;
  systemd bounces.

**Example timeline** for a 2-second BT drop during capture:

```
t=0.00  RPM poll raises OSError("rfcomm: transport endpoint...")
t=0.00  classifier: ADAPTER_UNREACHABLE
t=0.00  connection_log: bt_disconnect
t=0.00  connection.disconnect() called
t=0.00  reconnect loop: schedule[0]=1s
t=0.00  connection_log: adapter_wait, retry_count=1
t=1.00  probe /dev/rfcomm0 -> still missing
t=1.00  connection_log: reconnect_attempt, retry_count=1
t=1.00  connection_log: adapter_wait, retry_count=2 (delay=5s)
t=6.00  probe -> reachable
t=6.00  connection_log: reconnect_attempt, retry_count=2
t=6.00  connection_log: reconnect_success, retry_count=2
t=6.00  connection.reconnect() called -> python-obd reopened
t=6.00  _pollCycle breaks; next cycle starts fresh at t=6.1
t=6.10  RPM poll succeeds; _ecuSilentMode was False (stayed at 100ms)
```

In production this plays against the rfcomm-bind.service (US-196)
rebind, so the reconnect loop waits for `/dev/rfcomm0` to be re-
populated by the bind daemon after BT restoration.

**connection_log timeline** — five new canonical event_types populate
the `connection_log` table so a post-hoc "what happened during that
drive?" review reads as a flap timeline rather than a silent gap.
Constants live in `src/pi/data/connection_logger.py`; the `event_type`
column stays TEXT (no CHECK constraint) so existing dynamic writers
(profile switcher, `shutdown_{event}` f-string) keep working --
US-211 is additive.

| event_type | Meaning | retry_count |
|------------|---------|-------------|
| `bt_disconnect` | ADAPTER_UNREACHABLE fired; python-obd torn down | 0 |
| `adapter_wait` | Reconnect loop about to sleep for next probe | iteration # |
| `reconnect_attempt` | Probe returned True; about to reopen python-obd | iteration # |
| `reconnect_success` | python-obd reopened; capture resumed | iteration # |
| `ecu_silent_wait` | ECU_SILENT fired; adapter OK, cadence reduced | 0 |

Invariants (Spool Session 6 amendment):

1. Process NEVER exits on BT disconnect. Only FATAL surfaces to systemd.
2. Backoff caps at 60s; no exponential blow-up.
3. Probe is lightweight (stat + `rfcomm show`); NOT a full `OBD()` reopen.
4. `connection_log` event_types are ADDITIVE -- existing types
   (`connect_attempt`, `connect_success`, `disconnect`, `drive_start`,
   `drive_end`, `shutdown_{event}`, etc.) remain valid.
5. ECU_SILENT stays connected; do NOT tear down on engine-off.

### Battery Health Log (US-217, Spool Session 6 Story 3)

Per CIO directive 3 (Spool Session 6 — monthly drain tests May–Sept driving season; quarterly in storage), the Pi maintains a `battery_health_log` capture table with one row per UPS drain event. US-217 lands the schema + writer surface; US-216 (Power-Down Orchestrator) will consume it when it wires the staged 30/25/20 SOC shutdown ladder.

**Table shape** — Pi SQLite `battery_health_log`: `drain_event_id INTEGER PK AUTOINCREMENT`, `start_timestamp TEXT NOT NULL DEFAULT strftime('%Y-%m-%dT%H:%M:%SZ','now')`, `end_timestamp TEXT NULL`, `start_soc REAL NOT NULL`, `end_soc REAL NULL`, `runtime_seconds INTEGER NULL`, `ambient_temp_c REAL NULL`, `load_class TEXT NOT NULL DEFAULT 'production' CHECK IN ('production','test','sim')`, `notes TEXT NULL`, `data_source TEXT NOT NULL DEFAULT 'real'` with CHECK enum. Index `IX_battery_health_log_start` on `start_timestamp` for time-range queries.

**load_class enum**:

- `production` — real drain (wall power lost while Pi was running normally).
- `test` — CIO's scheduled monthly drill (battery aging baseline).
- `sim` — developer / CI synthetic drain (never touches real hardware).

Analytics filter `production` + `test` for runtime-trend baselines; `sim` is excluded so unit-test fixture rows never contaminate battery-replacement alerts.

**Writer** — `src/pi/power/battery_health.BatteryHealthRecorder` exposes two methods:

- `startDrainEvent(startSoc, loadClass='production', notes=None, dataSource='real') → drain_event_id` — INSERTs a new row with NULL end columns.
- `endDrainEvent(drainEventId, endSoc, ambientTempC=None) → DrainEventCloseResult` — UPDATEs end_timestamp + end_soc + runtime_seconds (+ optional ambient). **Close-once semantic**: re-calling on an already-closed row is a no-op that returns the stored values; the original close is authoritative.

**CLI helper** — `scripts/record_drain_test.py` opens and closes a drain event in one invocation for the CIO's monthly drill. Accepts `--start-soc`, `--end-soc`, `--runtime`, `--load-class`, `--ambient`, `--notes`. Follow with `scripts/sync_now.py` to push the row to Chi-Srv-01.

**Sync shape** — `sync_log.PK_COLUMN['battery_health_log'] = 'drain_event_id'`; the Pi sync client's `_renamePkToId` renames `drain_event_id → id` on the wire; the server's `runSyncUpsert` maps `id → source_id`. Server mirror `BatteryHealthLog` SQLAlchemy model with `UNIQUE(source_device, source_id)`. Registered in `_TABLE_REGISTRY`; deploy-time migration `v0002_us217_battery_health_log.py` creates the MariaDB table.

**Invariants**:

1. `start_soc` + `start_timestamp` are authoritative once written; the close path only touches end-event columns.
2. `drain_event_id` is auto-incremented + monotonic (per-event, not a singleton).
3. Close-once: first `endDrainEvent` wins; re-call is a no-op so a crashed orchestrator that retries on next boot cannot overwrite the original close data.
4. Timestamps route through `src.common.time.helper.utcIsoNow` (US-202 canonical ISO-8601 UTC).

**Use case — US-216 consumer**:

- At WARNING (30% SOC): `startDrainEvent(startSoc=30, loadClass='production')` → returns drain_event_id.
- At TRIGGER (20% SOC): `endDrainEvent(drainEventId=…, endSoc=20, ambientTempC=…)` → closes the row just before `systemctl poweroff`.

**Use case — monthly drain drill (CIO)**:

- Unplug wall power, let Pi drain to the trigger threshold.
- Record results: `python scripts/record_drain_test.py --start-soc 100 --end-soc 20 --runtime 1440 --load-class test --ambient 22`.
- Push to server: `python scripts/sync_now.py`.
- Analytics downstream tracks `runtime_seconds` decay for battery-replacement signal (future story).

### Data Retention

- **realtime_data**: 365 days (configurable)
- **statistics**: Indefinite
- **ai_recommendations**: Indefinite
- **calibration_sessions**: Manual management

### Server Schema Migrations (US-213, TD-029 closure)

Every server-side schema change -- new column, new table, new index --
ships as a numbered migration module under
`src/server/migrations/versions/`.  The registry
(`src/server/migrations/__init__.py::ALL_MIGRATIONS`) is the authoritative
ordered list; `deploy-server.sh` invokes
`scripts/apply_server_migrations.py --run-all` between the pip install
step and the service restart on both `--init` and the default flow.

**Why this exists.** Before US-213 the live MariaDB had no deploy-time gate
for DDL: SQLAlchemy model additions (US-195 `data_source`,
US-200 `drive_id` / `drive_counter`) tested clean against CI's ephemeral
SQLite but never ran as `ALTER TABLE` on the live DB.  US-205 halted
mid-truncate when a missing column surfaced; US-209 applied the DDL as a
one-shot; TD-029 captured the root cause.  US-213 closes the class-of-bug
permanently.

**Design choices.**

- **Explicit registry over Alembic.**  Path B in TD-029 -- matches CIO's
  "single deploy script, keep it simple" directive, zero new runtime
  dependencies, same style as Pi-side `ensureAllCaptureTables`
  (`src/pi/obdii/data_source.py`) / `ensureAllDriveIdColumns`
  (`src/pi/obdii/drive_id.py`) idempotent migrations.  Alembic remains
  available in `requirements-server.txt` for future migrations that
  genuinely need autogenerate + downgrade; no such case today.
- **Tracking table.** `schema_migrations` on MariaDB: `version` (VARCHAR(64)
  PK), `description` (VARCHAR(512)), `applied_at` (DATETIME default
  CURRENT_TIMESTAMP).  Created idempotently on first `--run-all`.
- **Idempotency is the migration author's contract.**  Each `apply(ctx)`
  function must be safe to re-run on a fully-migrated DB (probe
  INFORMATION_SCHEMA; emit DDL only when missing).  The runner guarantees
  "apply once" on success by recording the version, but never revalidates
  schema state.
- **HARD fail.**  A migration failure raises `MigrationError`; the CLI
  returns non-zero; `deploy-server.sh` halts under `set -e` before the
  service restart.  No half-deployed state.
- **No rollback machinery.**  MariaDB DDL is implicit-commit; partial
  failure leaves the DB partially migrated.  Operator restores from the
  per-migration `mysqldump` backup (for migrations that take one) and
  re-runs after fixing the underlying cause.

**Adding a new migration (developer workflow).**

1. Create `src/server/migrations/versions/vNNNN_<slug>.py` following
   `v0001_us195_us200_catch_up.py` as the template -- export `VERSION`,
   `DESCRIPTION`, `apply(ctx)`, and a module-level `MIGRATION` instance.
2. Import the `MIGRATION` symbol into
   `src/server/migrations/__init__.py` and append to `ALL_MIGRATIONS`
   (numerically ascending order; new entries at the end).
3. Add a unit test under `tests/server/test_migrations.py` (or a dedicated
   file) verifying the migration's DDL is idempotent against a mocked
   `CommandRunner`.
4. Ship.  Next `deploy-server.sh` run applies pending migrations
   automatically.

**Post-deploy verification.**

    ssh mcornelison@10.27.27.10 'mysql obd2db -e \
        "SELECT version, description, applied_at FROM schema_migrations ORDER BY version"'

Should list every applied migration with its apply timestamp.  On an
already-migrated server, re-running `apply_server_migrations.py --run-all`
emits a single `[run-all] 0 applied ... idempotent no-op` line.

**Registry (as of Sprint 19 close).**

| Version | Story | Purpose |
|---------|-------|---------|
| `0001` | US-209 | Retroactive catch-up: `data_source` (US-195) + `drive_id` / `drive_counter` (US-200) for capture/drive-id tables.  v0001 deliberately excluded `drive_summary` from CAPTURE_TABLES / DRIVE_ID_TABLES because Sprint 14 grooming treated it as analytics-only. |
| `0002` | US-217 | `CREATE TABLE battery_health_log` (Spool Session 6 Story 3 -- per-drain UPS health). |
| `0003` | US-223 | `DROP TABLE IF EXISTS battery_log` (TD-031 close -- dead Pi-only `BatteryMonitor` artifact). |
| `0004` | US-237 | `drive_summary` 3-way reconcile: ALTER 11 missing US-206/US-195/US-200 columns + add `IX_drive_summary_drive_id` + `uq_drive_summary_source` UNIQUE; cascade-delete the 9 Sprint-7-8 sim rows + their `drive_statistics` children (V-4 namespace cleanup, CIO 2026-04-29).  Closes Ralph's V-1 / V-4 from the post-Drive-4 health check. |
| `0005` | US-238 | `CREATE TABLE dtc_log` -- mirrors the `DtcLog` ORM declared in Sprint 15 US-204 but never CREATEd on live MariaDB (US-204 predates the US-213 explicit registry).  Twelve columns (id + 4 sync + 7 Pi-native) + `uq_dtc_log_source` UNIQUE + `ix_dtc_log_drive_id`.  Closes Ralph's V-2 (silent-data-loss-on-next-DTC-drive risk) from the post-Drive-4 health check. |

---

## 6. Configuration Architecture

### Configuration Hierarchy

```
.env (secrets only - never committed)
         ↓
   secrets_loader.py
   (resolve ${VAR} placeholders)
         ↓
  config.json (application settings)
         ↓
   config_validator.py
   (validate required, apply defaults)
         ↓
  Runtime Configuration (validated dict)
```

### Secret Management

Secrets use placeholder syntax in config.json:

```json
{
  "database": {
    "password": "${DB_PASSWORD}"
  },
  "api": {
    "clientSecret": "${API_CLIENT_SECRET}"
  }
}
```

Resolved at runtime from environment variables. Supports defaults: `${VAR:default_value}`

### Configuration Sections

| Section | Purpose |
|---------|---------|
| `application` | Name, version, environment |
| `database` | SQLite connection settings |
| `api` | External API configuration |
| `logging` | Log level, format, PII masking |
| `profiles` | Tuning profiles with thresholds |
| `alerts` | Alert thresholds per profile |
| `calibration` | Calibration mode settings |
| `backup` | Backup cloud storage, scheduling, retention settings |
| `pi.companionService` | Pi → Chi-Srv-01 sync endpoint + auth + retry policy (US-151) |
| `pi.homeNetwork` | Pi home-network detection (SSID/subnet/ping) for B-043 auto-sync building block (US-188) |
| `pi.network` | Pi infrastructure addresses (host, user, path, port, hostname, deviceId) — B-044 canonical source (US-201) |
| `server.network` | Server infrastructure addresses (host, user, port, hostname, projectPath, baseUrl) — B-044 canonical source (US-201) |

### B-044: Config-Driven Infrastructure Addresses (US-201)

Infrastructure addresses (IPs, hostnames, ports, MACs) MUST live in
config and NEVER as string literals in source code, scripts, deploy
files, or tests. Literal drift is a class of bug equivalent to hardcoded
credentials — it breaks across environments and requires a global
rewrite when the address changes.

**Two canonical surfaces:**

1. `config.json` `pi.network.*` / `server.network.*` — consumed by Python
   code via the 3-layer config system (env → secrets_loader → validator).
2. `deploy/addresses.sh` — the bash-side mirror, sourced by every shell
   script that needs an address. Mirrors config.json field-for-field.
   Override pattern: env var > deploy.conf > addresses.sh defaults.

**Lint enforcement** (`tests/lint/test_no_hardcoded_addresses.py`,
`scripts/audit_config_literals.py`):

- Scans `src/`, `scripts/`, `deploy/`, the repo root — reports any
  non-exempt hit of the DeathStarWiFi subnet `10.27.27.*`, project
  hostnames (`chi-srv-01`, `chi-eclipse-01`, etc.), or the OBDLink MAC.
- Exempts: `specs/`, `docs/`, `offices/`, all `*.md` files, tool caches,
  canonical files (`config.json`, `.env*.example`, `deploy/addresses.sh`,
  `tests/conftest.py`), the `tests/` tree (category-C fixtures by
  design), and Python triple-quoted docstrings.
- Inline pragma: any line containing `b044-exempt` skips detection. Use
  with a one-line reason: `# b044-exempt: validator default`.
- `make lint-addresses` runs the audit; `pytest tests/lint/` runs the
  standing-rule gate in the fast suite.

**Adding a new address:**

1. Add to `config.json` `pi.network.*` or `server.network.*`.
2. Add the bash-side default to `deploy/addresses.sh`.
3. Python code reads via the config validator; shell scripts read via
   the sourced variable.
4. `make lint-addresses` (or `pytest tests/lint/`) must stay clean.

#### `pi.homeNetwork` — home-network detection (US-188)

Consumed by `src.pi.network.HomeNetworkDetector` to answer "is the Pi on
the home WiFi?" and "is Chi-Srv-01 reachable?"  The detector is the
Component 1 building block of B-043 (auto-sync + conditional shutdown on
power loss); the future PowerLossOrchestrator (US-189, Sprint 14) will
subscribe to `UpsMonitor.onPowerSourceChange` and branch on
`HomeNetworkState`.

The validator (`src.common.config.validator._validateHomeNetwork`) rejects
empty/whitespace-only SSID, non-CIDR `subnet`, non-positive
`pingTimeoutSeconds` (bool included), and relative `serverPingPath`
with `ConfigValidationError` at config-load time.

| Key | Default | Purpose |
|-----|---------|---------|
| `ssid` | `DeathStarWiFi` | Home WiFi SSID expected from `iwgetid -r` |
| `subnet` | `10.27.27.0/24` | Home LAN CIDR; defense-in-depth co-check with SSID |
| `pingTimeoutSeconds` | `3` | Bounded timeout on `GET {baseUrl}{serverPingPath}` |
| `serverPingPath` | `/api/v1/ping` | Must be absolute (start with `/`) |

Defense in depth: `isAtHomeWifi()` is True ONLY when BOTH the SSID check
AND the subnet check pass.  A spoofed home-SSID on a foreign router
fails subnet; a tethered hotspot that happens to use the home CIDR
fails SSID.  The composed `getHomeNetworkState()` returns `UNKNOWN`
(distinct from `AWAY`) when the `iwgetid` binary is missing or the
subprocess times out — the orchestrator can branch on that separately
(e.g., "retry later" vs "definitely not home").

#### `pi.companionService` — Pi → server reach (US-151)

Consumed by `src.pi.sync.SyncClient` (US-149) for delta upload to
Chi-Srv-01's `/api/v1/sync` endpoint.  Validator (`src.common.config.validator`)
rejects non-positive `syncTimeoutSeconds`, `batchSize < 1`, non-list
`retryBackoffSeconds`, or negative `retryMaxAttempts` with
`ConfigValidationError` so a corrupt surface never reaches the client.

| Key | Default | Purpose |
|-----|---------|---------|
| `enabled` | `true` | When `false`, sync short-circuits to a no-op (US-149 owns the check) |
| `baseUrl` | `http://10.27.27.10:8000` | Chi-Srv-01 FastAPI root |
| `apiKeyEnv` | `COMPANION_API_KEY` | Env var name resolved by `secrets_loader` — key itself is never in the JSON |
| `syncTimeoutSeconds` | `30` | Per-request HTTP timeout (positive number) |
| `batchSize` | `500` | Rows per `/api/v1/sync` POST (integer >= 1) |
| `retryMaxAttempts` | `3` | Retry budget on retryable failures (integer >= 0) |
| `retryBackoffSeconds` | `[1, 2, 4, 8, 16]` | Exponential-backoff schedule in seconds (list) |

---

## 7. Error Handling Strategy

### Error Classification

| Type | Category | Behavior | Example |
|------|----------|----------|---------|
| Network timeout | RETRYABLE | Exponential backoff | OBD-II connection lost |
| Rate limit (429) | RETRYABLE | Backoff with max retries | NHTSA API throttled |
| Auth failure | AUTHENTICATION | Fail, log credentials issue | Invalid API key |
| Missing config | CONFIGURATION | Fail fast, clear message | DB_PASSWORD not set |
| Invalid data | DATA | Log and skip record | Malformed OBD response |
| System error | SYSTEM | Fail with diagnostics | Out of memory |

### Retry Strategy

- **Max retries**: 3 (configurable)
- **Backoff**: Exponential (1s, 2s, 4s, 8s, 16s)
- **Retry codes**: 429, 500, 502, 503, 504

### Exit Codes

| Code | Constant | Meaning |
|------|----------|---------|
| 0 | EXIT_SUCCESS | Successful completion |
| 1 | EXIT_CONFIG_ERROR | Configuration error |
| 2 | EXIT_RUNTIME_ERROR | Runtime/workflow error |
| 3 | EXIT_UNKNOWN_ERROR | Unexpected exception |

---

## 8. Logging and Observability

### Log Levels

| Level | Usage |
|-------|-------|
| DEBUG | Variable values, flow tracing, detailed diagnostics |
| INFO | Normal operational events, milestones |
| WARNING | Unexpected but handled situations |
| ERROR | Errors requiring attention |

### Log Format

```
2026-01-21 10:30:45 | INFO     | module_name | functionName | Message here
```

### PII Masking

The PIIMaskingFilter automatically masks sensitive data:
- **Email**: `user@example.com` → `[EMAIL_MASKED]`
- **Phone**: `555-123-4567` → `[PHONE_MASKED]`
- **SSN**: `123-45-6789` → `[SSN_MASKED]`

### Metrics to Track

- OBD-II connection success rate
- Data logging rate (records/second)
- Analysis duration (seconds)
- AI recommendation frequency
- Error rates by category

### Persistent Journald (US-210, US-230 acceptance signal)

Pi logs land in `journalctl -u eclipse-obd` (and the system journal). The
default systemd-journald `Storage=auto` puts logs on tmpfs (`/run/log/journal`)
when `/var/log/journal` does not exist -- a power-loss or service crash
takes the logs with it. US-210 ships the drop-in
`/etc/systemd/journald.conf.d/99-obd-persistent.conf` with
`Storage=persistent` so journald creates `/var/log/journal/<machine-id>/`
on next restart.

**Acceptance signal is the machine-id subdir, not the parent.** Pre-US-230
the deploy-time check only looked for `/var/log/journal/` existence.
Spool's 2026-04-23 post-deploy audit caught the actual failure mode: the
parent dir was present but EMPTY, so journald still wrote to tmpfs.
US-230 tightens the check:

| Signal | Pass condition |
|--------|----------------|
| `cat /etc/machine-id` | non-empty string |
| `/var/log/journal/<machine-id>/` | exists as a directory |
| `journalctl --disk-usage` | reports `[1-9][0-9]*[BKMGT]? in the file system` (non-zero) |
| `systemctl is-active systemd-journald` | `active` |

The drop-in install requires an explicit `systemctl restart systemd-journald`
for Storage=persistent to take effect; systemd does not hot-reload
journald.conf.d/ changes without a service restart. The deploy step
sleeps 2s after restart to let journald create the machine-id subdir and
rotate the first log segment before verification.

**Failure-mode policy.** On any of the four signals failing, deploy-pi.sh
prints diagnostics (disk-usage, `ls /var/log/journal/`, `journalctl
--verify`, conf.d contents, `is-active`) and exits non-zero. It does NOT
silently `mkdir /var/log/journal/<machine-id>/` as a recovery -- that
paper-fix would hide the real cause (stale tmpfs bind, disk-full,
SELinux, journald failing to pick up Storage=persistent). The operator
files an inbox note with the diagnostic output and proposes the recovery
path before re-deploying.

Live verification: `bash tests/deploy/test_journald_persistent_install.sh`
(autotools-style SKIP exit 77 when SSH is unreachable; runs the same four
checks the deploy post-check runs).

---

## 9. Security Considerations

### Secrets Management

- Never commit secrets to version control
- Store credentials only in `.env` file
- Use `${VAR}` placeholders in config.json
- Secrets loader masks values in logs with `[LOADED]`

### Data Protection

- PII masking in all log output
- No external network exposure (local only)
- Database file permissions (owner read/write only)

### Input Validation

- All OBD-II responses validated before storage
- Configuration validated on startup
- Export filenames sanitized

---

## 10. Display Architecture

### Display Layout (480x320)

```
┌───────────────────────────────────────────┐
│ Eclipse OBD-II                 ▲ Connected│
│ Profile: Daily                       [D]  │
├───────────────────────────────────────────┤
│                                           │
│  RPM:    2500         Speed:  45 mph      │
│  Temp:   185°F        A/F:    14.7:1      │
│  Boost:  8.2 psi      Volts:  14.2V      │
│                                           │
├───────────────────────────────────────────┤
│ No Alerts                    🔋 98% [AC]  │
└───────────────────────────────────────────┘
```

### Display Modes

| Mode | Behavior |
|------|----------|
| headless | No display output, logs only |
| minimal | OSOYOO HDMI display shows status screen |
| developer | Detailed console logging |

### Display Tiers

The primary driving screen has two data-rendering tiers, selected by the
orchestrator based on connectivity and data availability. Both share the
same 3x2 gauge grid; only the surrounding chrome differs.

| Tier | Module | Adds over previous |
|------|--------|--------------------|
| Basic (US-164) | `src/pi/display/screens/primary_screen.py` | 6-parameter grid, OBD dot, profile tag, alert line, SOC + power source |
| Advanced (US-165) | `src/pi/display/screens/primary_screen_advanced.py` | 3 connectivity dots (OBD / WiFi / Sync), `[min / max]` bracket per gauge, 4-band color coding (blue/white/orange/red), extended footer (last-sync relative time + drive count) |

**Color palette (advanced tier, spec 2.4)**: blue = cold/below normal,
white = normal, orange = caution, red = danger. Basic tier retains the
white/yellow/red palette — both tiers co-exist without regression.

**Threshold source**: `config.json::pi.tieredThresholds` (never hardcoded).
Evaluators in `src/pi/alert/tiered_thresholds.py` return an `AlertSeverity`;
`src/pi/display/theme.py::advancedTierSeverityToColor` maps severity to
color. No config duplication.

**Min/max markers**: sourced from `src/pi/data/recent_stats.py::queryRecentMinMax`,
which reduces the last N rows of the `statistics` table per parameter
(N configurable, default 5).

### Two Display Surfaces (primary + status_display overlay)

The Pi runtime wires two distinct pygame surfaces that must not fight over
GPU resources:

| Surface | Module | Owner | Renderer |
|---------|--------|-------|----------|
| Primary (driving screen) | `pi.display.manager` + `pi.display.screens.*` | Orchestrator | Headless / Minimal / Developer drivers; the Minimal driver calls `pygame.display.set_mode` under X11 with `DISPLAY=:0 XAUTHORITY=~/.Xauthority SDL_VIDEODRIVER=x11` per Session 22 baseline. |
| Status overlay | `pi.hardware.status_display` | HardwareManager | Software renderer (US-198). `pygame.display.set_mode((480,320), NOFRAME)` is wrapped by SDL env hints forcing the software path — `SDL_RENDER_DRIVER=software`, `SDL_VIDEO_X11_FORCE_EGL=0`, `SDL_FRAMEBUFFER_ACCELERATION=0` — set *before* `pygame.init()`. |

**Why the split matters (TD-024 / US-198)**: pygame's wheel-bundled SDL2
defaulted to an EGL/GL context when the overlay initialized under X11 and
the X server denied GLX with `BadAccess`. Xlib's default error handler calls
`exit()`, killing the orchestrator runLoop at uptime ~0.6s (Session 23 live
drill). The software path on the overlay renders visibly and avoids GL
entirely. The primary display keeps the native x11 renderer because its
path was already proven in Session 22.

**Config surface**:

```json
"pi": {
  "hardware": {
    "statusDisplay": {
      "enabled": true,
      "forceSoftwareRenderer": true
    }
  }
}
```

Operators can set `enabled: false` to disable the overlay entirely if it
ever breaks again — the orchestrator tolerates a null `statusDisplay`.
Operators can override any `SDL_*` env var at the `.service` / shell level;
the code only fills in missing values, never clobbering.

### Full-Canvas Status Overlay Redesign (US-257, B-052, Sprint 21)

The legacy 480x320 strip rendered fine on the OSOYOO touchscreen but
occupied a small fraction of the Eclipse's HDMI canvas (CIO observation
during 2026-05-01 drain test 5). US-257 split the layout out of
`status_display.py` into a pure-geometry module
`pi.hardware.dashboard_layout` so the same render path drives any canvas
size — 480x320 dev/test, 1280x720, 1920x1080 — without code branches.

**Quadrant layout** (fixed for muscle memory):

```
┌────────────────────────┬────────────────────────┐
│  NW: engine            │  NE: power state       │
│  battery % + voltage   │  source + stage banner │
├────────────────────────┼────────────────────────┤
│  SW: drive             │  SE: alerts            │
│  OBD2 connection       │  warning/error counts  │
├────────────────────────┴────────────────────────┤
│              footer: uptime + IP                │
└─────────────────────────────────────────────────┘
```

`dashboard_layout.computeLayout(canvasWidth, canvasHeight)` produces a
frozen `DashboardLayout` with quadrant `Rect`s, a footer rect, scaled
`FontScale` (title / value / label / detail), and proportional padding.
Font sizes scale linearly with canvas height against a 1080-tall reference
and clamp to a readable minimum so the legacy 480x320 case still renders
without truncation.

**Staged-shutdown stage banner** (NE quadrant): the new
`updateShutdownStage(stage)` setter wires the US-216 / US-252 ladder
through to the dashboard. The NE quadrant background tints with the stage
color (NORMAL=green / WARNING=amber / IMMINENT=orange / TRIGGER=red)
during a transition so an operator several feet from the screen can read
the stage at a glance. NORMAL leaves the background black to avoid
"always-amber" alarm fatigue.

**Config surface** (additive, backwards-compat with 480x320):

```json
"pi": {
  "display": {
    "width": 480,
    "height": 320,
    "displayCanvas": {
      "width": 1920,
      "height": 1080,
      "mode": "auto"
    }
  }
}
```

`displayCanvas.mode='auto'` is a hint that the consumer can call
`pygame.display.Info()` to detect screen dims at start time. An explicit
`width`/`height` falls back to those values literally. The legacy
`pi.display.width`/`height` keys are unchanged so existing dev/test rigs
keep working.

**Test surface**: `tests/pi/hardware/test_dashboard_layout.py` exercises
the geometry across (1920,1080) / (1280,720) / (480,320) and asserts the
quadrants tile the canvas-minus-footer with no gaps, no overlaps, and no
zero-dim quadrants. `tests/pi/hardware/test_status_display.py`
parameterizes the constructor + render path over the same three sizes
and verifies `updateShutdownStage` accepts both the enum and string forms
with case-insensitive coercion.

### Live-Data HDMI Render (US-192)

The orchestrator writes `realtime_data` rows to the Pi's local SQLite; the
HDMI primary-screen renderer runs as a **peer process** that polls those
rows each frame. They do not share a pygame Surface — the decoupling keeps
the orchestrator free of GL context state and lets the renderer restart
independently.

```
main.py orchestrator ──writes──▶ data/obd.db (realtime_data)
                                        │
                                        │  polled each frame
                                        ▼
       scripts/render_primary_screen_live.py --from-db
                                        │
                                        │  pygame.display.flip()
                                        ▼
                              OSOYOO 3.5" HDMI @ 480x320
```

**Live-readings poll layer** — `src/pi/display/live_readings.py`:

| Function | Purpose |
|----------|---------|
| `PARAMETER_ALIASES` | Maps collector-side names (e.g., `BATTERY_V` from US-199 ELM_VOLTAGE path) to display-side gauge slots (`BATTERY_VOLTAGE`). |
| `buildReadingsFromDb(dbPath, names)` | Returns latest value per gauge. `data_source = 'real'` only (NULL BC for pre-US-195 rows). Opens SQLite read-only via `file:…?mode=ro` URI; missing file / missing table degrade to `{}`. |
| `resolveGaugeName(n)` | Alias-aware name resolution, unknown names pass through. |

**Render harness** — `scripts/render_primary_screen_live.py --from-db PATH`:

Each frame at ~10 FPS, the harness calls `buildReadingsFromDb` and feeds the
dict into `buildBasicTierScreenState`. Gauges without a fresh row render
the `---` placeholder (renderer already handles this via `_PLACEHOLDER_VALUE`
in `primary_screen.py`). Without `--from-db` the harness falls back to the
US-183 scripted RPM sweep (kiosk demo mode).

**systemd env block** — `deploy/eclipse-obd.service` sets:

```
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/mcornelison/.Xauthority
Environment=SDL_VIDEODRIVER=x11
```

These propagate to any process the service spawns AND to the interactive
SSH session the CIO uses to launch the render harness. `SDL_VIDEODRIVER=x11`
is the Session 22 baseline that visibly paints the OSOYOO; the Status
Overlay's `forceSoftwareRenderer` (US-198) is independent and does not need
overrides here.

**CIO verification**: `bash scripts/verify_hdmi_live.sh --duration 30`
stops the service, starts `main.py --simulate` in the background, launches
the render harness in `--from-db` mode against `data/obd.db`, and asks the
CIO to eyeball that the six gauges show live non-zero values. Simulator
path is the valid acceptance path — engine isn't required.

### Session 22 pygame hygiene — closure audit (US-215)

US-215 (2026-04-21) audited four informally-referenced Session 22 pygame
hygiene concerns — `TD-019` DISPLAY/XAUTHORITY env vars, `TD-020` pygame-on-tty,
`TD-021` multi-HDMI dev workflow, `TD-022` `--no-binary` pygame rebuild on
Python 3.13. Finding: **no formal TD files were ever filed** under
`offices/pm/tech_debt/TD-01{9,20,21,22}*.md`; the IDs appeared only in auto-memory
and inbox grooming notes as placeholders for "audit next session." Per-ID
disposition:

| ID (informal) | Concern | Status | Rationale |
|---------------|---------|--------|-----------|
| TD-019 | DISPLAY / XAUTHORITY / SDL_VIDEODRIVER env vars | **Resolved by US-192** | `deploy/eclipse-obd.service` lines 67–69 ship the env block; see §10 "systemd env block" above. |
| TD-020 | pygame on tty console (no-X) | **Moot in production** | Pi-in-car deployment auto-starts X via lxsession; tty-only was never a production target. |
| TD-021 | Multi-HDMI dev workflow (xrandr force primary) | **Moot in production** | Single-HDMI production config; dev-only note not carried forward. |
| TD-022 | `--no-binary :all:` pygame rebuild fails on Python 3.13 | **Deferred — wheel path is production** | SDL2 wheel-bundled pygame is the production install path; `--no-binary` path is a nice-to-have for kmsdrm work and not a blocker. |

No TD files created retroactively — per CIO drift-observation rule, TDs filed
post-hoc for informal references that never graduated to formal status add
noise without adding signal. The audit trail lives here and in the inbox note.

---

## 10.5 DTC Lifecycle (US-204)

Spool Data v2 Story 3 added Diagnostic Trouble Code (DTC) capture so the
"Is the check engine light on?" question — Question 1 of every engine
health review — has a recorded answer.

### Table shape

`dtc_log` (Pi SQLite + MariaDB mirror):

| Column | Notes |
|--------|-------|
| `id` | INTEGER PK AUTOINCREMENT (sync delta cursor). |
| `dtc_code` | TEXT NOT NULL (e.g. `"P0171"`). |
| `description` | TEXT — empty string for unknown / Mitsubishi P1XXX codes (never fabricated). |
| `status` | CHECK in (`stored`, `pending`, `cleared`). Sprint 15 only writes the first two. |
| `first_seen_timestamp` | DEFAULT `strftime('%Y-%m-%dT%H:%M:%SZ', 'now')` — US-202 canonical. |
| `last_seen_timestamp` | Same default; bumped via UPDATE on duplicate within the same drive. |
| `drive_id` | INTEGER NULL — inherited from US-200 context (`getCurrentDriveId()`). |
| `data_source` | DEFAULT `'real'` per US-195; CHECK enum (`real`/`replay`/`physics_sim`/`fixture`). |

Indexes: `IX_dtc_log_drive_id` (per-drive analytics) + `IX_dtc_log_dtc_code`
(cross-drive lookup of a specific code).

### Capture timing

```
Drive starts (RPM crosses cranking threshold)
  -> DriveDetector._openDriveId mints drive_id, publishes via setCurrentDriveId
  -> DriveDetector._startDrive emits onDriveStart(session)
       -> EventRouterMixin._handleDriveStart
            -> DtcLogger.logSessionStartDtcs(driveId=None, connection=...)
                 -> Mode 03 GET_DTC          (stored DTCs)
                 -> Mode 07 GET_CURRENT_DTC  (pending DTCs; probe-first)
                 -> rows INSERTed with drive_id from context, data_source='real'

Mid-drive: each MIL_ON poll observation -> _handleReading
  -> MilRisingEdgeDetector.observe(value)
  -> if 0->1 transition: DtcLogger.logMilEventDtcs
       -> Mode 03 GET_DTC (re-fetch)
       -> per code: UPDATE last_seen if (drive_id, dtc_code) exists, else INSERT
```

### 2G DSM Mode 07 fallback

The 1998 2G ECU pre-dates full OBD2 compliance — Mode 07 may return a null
frame. `DtcClient.readPendingDtcs` returns
`(codes, Mode07ProbeResult(supported=...))`; when `supported=False` the
caller is expected to cache the result on the connection instance and
skip subsequent Mode 07 calls until reconnect. The probe verdict is
NOT persisted to disk — re-probing on reconnect is cheap and avoids
stale assumptions across hardware swaps.

### Server mirror

`src.server.db.models.DtcLog` — same column shape plus the standard
synced-table columns (`source_id`, `source_device`, `synced_at`,
`sync_batch_id`) and the `(source_device, source_id)` UNIQUE upsert
key. `_TABLE_REGISTRY` in `src/server/api/sync.py` includes `dtc_log`;
`PK_COLUMN['dtc_log'] = 'id'` registers the Pi-side delta cursor.

The live MariaDB physical table reaches that shape via deploy-time
migration `v0005_us238_create_dtc_log.py` (Sprint 19). Sprint 15 US-204
predated the US-213 explicit migration registry, so the ORM and
sync wiring shipped without a CREATE TABLE on the production server —
Ralph's Drive 4 health check on 2026-04-29 caught the gap as V-2
(`Table 'obd2db.dtc_log' doesn't exist`). Drive 4's DTC_COUNT was 0 so
no rows were lost, but the next DTC drive would have written to Pi
only. v0005 closes the gap with the same idempotent CREATE-TABLE-IF-NOT-EXISTS
+ post-condition probe pattern as v0002 (battery_health_log). See
Section 5 Server Schema Migrations subsection for migration registry
mechanics.

### Invariants honored

1. Every dtc_log row carries `drive_id` (or NULL only when no drive
   context exists — defensive; orchestrator should not dispatch MIL
   events outside RUNNING).
2. Mode 07 probe is per-connection cache, not persisted.
3. DTC descriptions come from python-obd's `DTC_MAP`; unknown codes
   land with empty description rather than fabricated text.
4. Duplicate detection scoped to `(drive_id, dtc_code)`. Same code in
   a new drive INSERTs a fresh row.
5. DTC capture is event-driven, not tier-scheduled. `dtc_log` is NOT
   in `config.json:realtimeData.parameters` and not in any pollingTier.
6. Schema-DEFAULT timestamps (`strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`)
   keep US-202 canonical timestamp invariant intact.

---

## 10.6 Power-Down Orchestrator (US-216 + US-234)

Per CIO directive 2 (Spool Session 6), the Pi runs a staged-shutdown
ladder instead of the legacy binary 10% low-battery trigger. The
orchestrator owns the shutdown path whenever
`pi.power.shutdownThresholds.enabled=true`; the legacy
`ShutdownHandler` 30s-after-BATTERY timer + 10% trigger become no-ops
to prevent the race (TD-D in the Spool audit of 2026-04-21).

### Trigger source (US-234, Sprint 19): VCELL volts, not SOC%

US-216 originally compared MAX17048 SOC% against a 30/25/20 ladder.
Across 4 drain tests over 9 days (Drains 1-4) the ladder NEVER fired:
the Pi hard-crashed at VCELL 3.36-3.45V every test while MAX17048
SOC% reported 57-63%. Spool's analysis identified a 40-pt SOC%
calibration error on this MAX17048 unit (gauge reads 60% when VCELL
indicates near-empty). The ladder shape (NORMAL → WARNING → IMMINENT
→ TRIGGER + AC-restore + hysteresis + callback isolation) is correct;
SOC% as the trigger source was wrong on this hardware.

US-234 switched the trigger source to **VCELL volts** read directly
from the cell. The chip-level SOC%-vs-VCELL calibration error is no
longer in the path. Threshold values come from Spool's 4-drain
analysis (Drain 1-4 hard-crash range 3.36-3.45V; TRIGGER at 3.45V
gives ~90s headroom above the buck-converter dropout).

### State Machine

```
                        VCELL drops <= 3.70V
           NORMAL ----------------------> WARNING (open drain_event row)
              ^                              |
              |  VCELL >= 3.75 (warning+hyst)| VCELL drops <= 3.55V
              |  or AC restore               v
              +---------------------------- IMMINENT (stop poll, close BT)
              |                              |
              |  AC restore                  | VCELL drops <= 3.45V
              |                              v
              +---------------------------- TRIGGER (poweroff, one-way)
```

### VCELL Ladder (config-driven)

| Stage | Default VCELL | Config key | Stage Behaviors |
|-------|---------------|------------|-----------------|
| WARNING | ≤ 3.70V | `pi.power.shutdownThresholds.warningVcell` | Open `battery_health_log` row (US-217); fire `onWarning` callback (DB `no_new_drives` flag, SyncClient force push). |
| IMMINENT | ≤ 3.55V | `...imminentVcell` | Fire `onImminent` callback (stop OBD poll tier, close BT via US-211 clean-close, `DriveDetector.forceKeyOff(reason='power_imminent')`). |
| TRIGGER | ≤ 3.45V | `...triggerVcell` | Close `battery_health_log` row; call `ShutdownHandler._executeShutdown` → `systemctl poweroff`. One-way; state machine terminal. |
| AC-restore | any | n/a | Cancel pending stages, close drain row with `notes='recovered'`, return to NORMAL. |

### Hysteresis

`hysteresisVcell` (default 0.05V) prevents flap on noisy VCELL reads
around a threshold. Once a stage fires, VCELL must recover to
`stageVcell + hysteresisVcell` (e.g. 3.75V for WARNING) to de-escalate
on battery. In practice VCELL is monotonically decreasing during real
drains, so hysteresis mainly matters for boundary oscillation
(3.69/3.71V) and momentary on-load sags followed by load reduction.

### battery_health_log column reuse (US-234 schema note)

US-234 reuses the existing `start_soc` and `end_soc` columns in
`battery_health_log` (US-217 schema unchanged per US-234 doNotTouch
list). Post-US-234 those columns hold **VCELL volts** (typical 3.45 -
4.20) rather than SOC % (typical 20 - 100). Rows written before
US-234 ship are SOC %; rows written after are volts. A column rename
or `unit` discriminator column is a Sprint 20+ candidate; not in
scope here. Analytics consumers must filter rows by drain-event start
time post-US-234-deploy when querying.

### Legacy Timer Suppression

Before US-216, `ShutdownHandler` had two automatic trigger paths:

1. **30s timer** after any AC → BATTERY transition (`_scheduleShutdown`).
2. **10% low-battery trigger** (`onLowBattery`).

Both are live in hardware today. Spool's 2026-04-21 audit identified
TD-D: if the new ladder did NOT suppress these paths, the legacy 10%
trigger (or 30s timer) could fire after the new ladder's TRIGGER@20%,
causing `systemctl poweroff` to run twice (harmless on most cases,
but the 30s timer specifically races into the IMMINENT window before
the ladder can even finish its stages).

The fix is a `suppressLegacyTriggers` boolean on `ShutdownHandler`.
When True (set automatically by `hardware_manager` when
`pi.power.shutdownThresholds.enabled=true`), both
`onPowerSourceChange` and `onLowBattery` short-circuit without
scheduling or executing shutdown. The terminal
`_executeShutdown()` method remains callable by
`PowerDownOrchestrator` at TRIGGER. The regression test
`tests/pi/power/test_ladder_vs_legacy_race.py` walks both rails
(VCELL 4.20→3.30V and SOC 100→0%) in parallel and asserts
`systemctl poweroff` fires exactly once, at the VCELL TRIGGER
crossing (post-US-234), never at the legacy 10% SOC trigger.

### battery_health_log integration (US-217 + US-234)

One row per drain event. Opened on WARNING entry with the highest
observed on-battery VCELL (captures true drain start, not the WARNING
threshold crossing). Closed on TRIGGER (with `end_soc` column carrying
VCELL volts at the 3.45V crossing post-US-234) or on AC-restore (with
`end_soc` at current VCELL). The `runtime_seconds` column is derived
from the start/end timestamps at close — queryable for drain-rate
trending across the May-Sept monthly drill cadence (CIO directive 3).

Pre-US-234 rows have `start_soc` / `end_soc` in SOC %; post-US-234
rows have them in VCELL volts. See US-234 schema-reuse note above.

### Drill Protocol

See `docs/testing.md` UPS Drain Test section for the monthly CIO
real-drain drill + regression test details.

### Tick Driver Decoupled From Display (US-252, Sprint 21)

**The bug class.**  Across 5 drain tests over 3 weeks (Sprint 17 / 18 /
20 + post-deploy drains 1-5) the staged-shutdown ladder NEVER FIRED.
The Pi hard-crashed at the LiPo discharge knee every time even though
the orchestrator's state machine was correct (US-216 + US-234 already
proved threshold logic), `PowerMonitor` was writing transition rows to
`power_log` (US-243), and US-211/US-225/US-232 had wired every stage
behavior.  The post-mortem: the orchestrator's `tick()` was called from
`HardwareManager._displayUpdateLoop`, which only spawned when
`StatusDisplay` initialized successfully.  Any pygame fault, missing
HDMI cable, or `pi.hardware.statusDisplay.enabled=false` silently
disabled the safety ladder by killing the only thread that drove it.

**The fix.**  US-252 introduces a dedicated
`HardwareManager._powerDownTickLoop` running on its own daemon thread
spawned whenever `_upsMonitor` AND `_powerDownOrchestrator` are wired
-- regardless of `_statusDisplay` state.  Loop body polls
`UpsMonitor.getTelemetry()` at the configured `pollInterval` and feeds
`(currentVcell, currentSource)` pairs to `orchestrator.tick`.  The
display loop continues to exist for UI updates only; the legacy
low-battery `ShutdownHandler.onLowBattery` check moved into the new
loop alongside the orchestrator tick.

```
   _startComponents (start order):
     UPS poll start
     GPIO button start
     StatusDisplay start  (optional)  ──► _displayUpdateLoop  (UI only)
     PowerDownOrchestrator tick thread (independent) ──► _powerDownTickLoop ──► tick()
     TelemetryLogger start (optional)
```

The decoupling is a **safety invariant**: the ladder thread is gated
on the safety-critical wiring (UPS + orchestrator), not on a UI
component.  A failure in display init, HDMI rendering, or pygame
software-renderer never reaches the staged-shutdown path.

### power_log Forensic Trail (US-252)

US-252 also adds a `vcell REAL` column to `power_log` (idempotent
`ensurePowerLogVcellColumn` migration, mirrors the
`ensureDataSourceColumn` pattern) and three new event types:

| event_type | When | vcell column |
|------------|------|---------------|
| `stage_warning` | WARNING entered | LiPo cell volts at threshold crossing |
| `stage_imminent` | IMMINENT entered | LiPo cell volts at threshold crossing |
| `stage_trigger` | TRIGGER entered (BEFORE poweroff) | LiPo cell volts at threshold crossing |

Persisted via a `(eventType, vcell) -> None` callable injected into
`PowerDownOrchestrator` via the new `powerLogWriter` constructor
parameter.  `ApplicationOrchestrator._createPowerLogWriter` builds the
closure over the live `ObdDatabase` (same DB-isolation pattern as
`_createBatteryHealthRecorder`).  Forensic value: a post-mortem can
reconstruct the full drain trajectory from `power_log` alone --
power-source transitions (US-243), stage-transition crossings with
their VCELL (this), and `battery_health_log` (US-217) start/end.

### Stage-Behavior Wiring (US-225, TD-034 close)

US-216 shipped with the four WARNING + IMMINENT + AC-restore stage
behaviors as log-only callbacks.  US-225 replaces the stubs with
concrete wiring.  Each behavior is individually no-op-safe so a
missing database, disabled companion service, or torn-down data
logger does not block the ladder from escalating to TRIGGER.

| Stage | Behavior | Implementation |
|-------|----------|----------------|
| WARNING | Set `pi_state.no_new_drives=true` | New singleton table `pi_state` (`src/pi/obdii/pi_state.py`). `DriveDetector._openDriveId` consults the flag at every cranking transition; when set, returns `None` and the drive proceeds id-less (engine-state machine still transitions). `drive_counter` is NOT incremented. |
| WARNING | SyncClient force-push | `SyncClient.forcePush()` wraps `pushAllDeltas` with explicit-intent logging + a `PushSummary` aggregate. All normal-sync invariants apply (AUTH header, retry schedule, failed-push HWM preserve, snapshot-table skip). A disabled companion service returns `disabled=True` without HTTP calls. |
| IMMINENT | Stop poll-tier dispatch | `ApplicationOrchestrator.pausePolling(reason)` / `resumePolling(reason)` delegate to `RealtimeDataLogger.stop`/`start`. The connection object stays attached; the stop handshake waits for the in-flight poll cycle to finish (no dropped queries). A separate flag `_pollingPausedForPowerDown` prevents a concurrent BT-reconnect resume from stealing the AC-restore resume. |
| IMMINENT | Force drive-end | `DriveDetector.forceKeyOff(reason)` closes any active drive (RUNNING or STOPPING), writes a real `connection_log` drive_end row with the reason in `error_message`, clears the process drive_id context, transitions to STOPPED.  Bypasses the RPM/speed debounce.  Safe no-op when no drive is active. |
| AC-restore | Clear gate + resume polling | `clearNoNewDrives` + `resumePolling`.  A failed resume does NOT reset the flag so a follow-up AC bounce can retry.  The gate clear path swallows DB hiccups -- the collector must stay live even when persistence is degraded. |

**BT close on IMMINENT** is NOT wired directly from the callback.
The TRIGGER -> `systemctl poweroff` cascade closes Bluetooth via
the existing `BtResilienceMixin` teardown + systemd service-stop
path; US-211's reconnect classifier owns the reattach side.  The
US-216 invariant "TRIGGER -> poweroff path stays unchanged" takes
priority over a redundant explicit close.  Revisit only if a
real-drain drill observes BT handle leakage beyond process exit.

**Invariant: callback failures don't block escalation.**
`_invokeCallback` broad-exception isolation means a raising
`onWarning` (e.g. sync transport error) does not prevent IMMINENT
from firing, and a raising `onImminent` (e.g. stale data logger)
does not prevent TRIGGER from running `systemctl poweroff`.  The
regression test `tests/pi/power/test_orchestrator_stage_behavior_wiring.py`
pins this for every stage.

---

## 11. Deployment Architecture

### Environments

| Environment | Purpose | Configuration |
|-------------|---------|---------------|
| Development | Local development | `.env.local` |
| Test | Automated testing | `.env.test` |
| Production | Raspberry Pi | `.env.production` |

### Auto-Start (systemd) -- per-tier units

Both tiers run under systemd with matching restart/security/logging shapes.
Living source-of-truth lives in `deploy/` (the snippet below is illustrative;
the canonical files are what ships).

| Tier | Unit | Source of Truth | Story |
|------|------|-----------------|-------|
| Pi (chi-eclipse-01) | `eclipse-obd.service` | `deploy/eclipse-obd.service` | US-210 (Sprint 16) |
| Server (chi-srv-01) | `obd-server.service` | `deploy/obd-server.service` | US-231 (Sprint 18) |

Shared invariants across both units:

- **`Restart=always`** + **`RestartSec=5`** -- backstop for unexpected process death.
- **`StartLimitIntervalSec=300` / `StartLimitBurst=10`** in the Unit section -- flap protection (modern systemd warns if these live in Service).
- **`User=mcornelison`** -- never root.
- **`Type=simple`** -- the venv-launched Python is the main process.
- **No inlined secrets** -- secrets live in `.env` referenced via `EnvironmentFile=`.
- **`journalctl -u <unit>` is the single source of truth** for runtime logs (no `StandardOutput=append:...` directives).

Tier-specific differences:

| Concern | Pi (eclipse-obd) | Server (obd-server) |
|---------|------------------|---------------------|
| `After=` deps | `network.target bluetooth.target` | `network.target mariadb.service` |
| Working directory | `/home/mcornelison/Projects/Eclipse-01` | `/mnt/projects/O/OBD2v2` |
| Venv | `/home/mcornelison/obd2-venv` | `/home/mcornelison/obd2-server-venv` |
| ExecStart | `python src/pi/main.py` | `uvicorn src.server.main:app --host 0.0.0.0 --port 8000` |
| Display env | DISPLAY/XAUTHORITY/SDL_VIDEODRIVER (US-192) | n/a (headless) |

Pre-US-231 the server ran as an unmanaged `nohup uvicorn` child launched by
`deploy-server.sh`. Spool's 2026-04-23 post-deploy audit caught it: any
chi-srv-01 reboot or process crash left the server down until manually
restarted, and Pi sync failed silently in the gap. US-231 mirrors the US-210
Pi-side fix: a systemd unit + a sync-if-changed install step in
`deploy-server.sh` (`step_install_server_unit`, mirror of
`step_install_eclipse_obd_unit`). Cutover is one-time -- the deploy script
kills any orphan pre-systemd `nohup uvicorn` (the `[u]vicorn` bracket trick
prevents the SSH shell from self-matching), then `sudo systemctl restart
obd-server` takes over. Subsequent deploys are no-op-or-restart depending
on whether the unit-file content changed.

```ini
# deploy/eclipse-obd.service (Pi tier, US-210; abridged)
[Unit]
Description=Eclipse OBD-II Performance Monitor
After=network.target bluetooth.target
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User=mcornelison
WorkingDirectory=/home/mcornelison/Projects/Eclipse-01
Environment=PATH=/home/mcornelison/obd2-venv/bin:/usr/bin:/bin
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/mcornelison/.Xauthority
Environment=SDL_VIDEODRIVER=x11
ExecStart=/home/mcornelison/obd2-venv/bin/python src/pi/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# deploy/obd-server.service (Server tier, US-231; abridged)
[Unit]
Description=OBD2v2 Analysis Server (FastAPI/uvicorn)
After=network.target mariadb.service
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User=mcornelison
WorkingDirectory=/mnt/projects/O/OBD2v2
EnvironmentFile=/mnt/projects/O/OBD2v2/.env
Environment=PYTHONPATH=/mnt/projects/O/OBD2v2
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/mcornelison/obd2-server-venv/bin/uvicorn src.server.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Release Versioning + Deploy Records (US-241, B-047 US-A)

Pre-US-241 every deploy was anonymous: a `git pull` + service restart with no
durable record of what shipped or when. CIO's 2026-04-29 directive introduced
a SemVer-shaped version string and a structured release record so B-047's Pi
self-update path (US-B/C/D in Sprint 20+) has a stable comparison key, and
so the operator can answer "what's currently running on the server?" without
reading git history.

**Versioning scheme**: `V<major>.<minor>.<patch>`. Capital `V` is required.
Starting version is **`V0.18.0`** (post-Sprint-18, pre-stable -- we have not
shipped a stable V1.0.0 yet). Bump conventions:

| Bump kind | When | Example |
|-----------|------|---------|
| **major** | Breaking schema/API change | `V0.18.0` → `V1.0.0` |
| **minor** | Sprint completes, new feature lands | `V0.18.0` → `V0.19.0` |
| **patch** | Bug fix / hotfix between sprints | `V0.18.0` → `V0.18.1` |

`major` resets minor + patch to 0; `minor` resets patch to 0.

**Canonical version file**: `deploy/RELEASE_VERSION` at repo root (committed):

```json
{"version": "V0.18.0", "description": "Sprint 18 ops-hardening shipped + Sprint 19 runtime fixes loading"}
```

`description` is hard-capped at 400 characters. PM owns the bump at sprint
close; deploy scripts NEVER bump it themselves.

**Per-tier deploy record**: each `deploy-pi.sh` / `deploy-server.sh` run
stamps a JSON record onto the deployed tier:

| Tier | Path |
|------|------|
| Pi   | `/home/mcornelison/Projects/Eclipse-01/.deploy-version` |
| Server | `/mnt/projects/O/OBD2v2/.deploy-version` |

Record shape: `{version, releasedAt, gitHash, description}`. `releasedAt` is
UTC ISO-8601 with `T` separator + `Z` suffix (e.g.,
`2026-04-30T14:32:00Z`). `gitHash` is the short git hash of the deployed
tree (caller runs `git rev-parse --short HEAD`). Idempotent: re-running with
the same `version` + `gitHash` overwrites the tier file with a refreshed
`releasedAt` so the tier always knows when it was LAST deployed.

**Helpers + CLI** (`scripts/version_helpers.py`): single source of truth
for the JSON shape. Public API:

| Function | Purpose |
|----------|---------|
| `parseVersion(s)` | Returns `(major, minor, patch)`; raises `ValueError` on bad shape |
| `bumpVersion(version, kind)` | Returns bumped version string; `kind` ∈ `{major, minor, patch}` |
| `validateRelease(record)` | Returns `True` iff the record matches the {version, releasedAt, gitHash, description ≤400} contract |
| `readDeployVersion(path)` | Returns parsed record or `None` (missing file, malformed, or invalid shape) |
| `composeReleaseRecord(versionFile, gitHash, releasedAt=None)` | Composes a record from the inputs; raises `ValueError` on bad version-file contents |

The deploy scripts shell out to the `compose-record` CLI so the JSON-
composition lives in one testable Python module rather than in two bash
heredocs:

```bash
python scripts/version_helpers.py compose-record \
    --version-file deploy/RELEASE_VERSION \
    --git-hash $(git rev-parse --short HEAD)
# stdout: {"version": "V0.18.0", "releasedAt": "...", "gitHash": "...", "description": "..."}
```

**Tier query**: `readDeployVersion(path)` returns the active record on each
tier. B-047 US-B's `/api/v1/version` endpoint will read the server-side file;
US-C's Pi self-update path will read the Pi-side file before deciding whether
to pull a newer version. The shape is **stable from US-A onward** -- US-B/C/D
must NOT be blocked on US-A changing the contract.

**Why deploy writes the stamp, not git**: a stamped tier file survives even
a partial deploy where the git tree isn't pushed (e.g., a `--restart-only`
run). The git short-hash captured in the record provides forensic
traceability without coupling tier-state to git availability on the Pi.

### Wake-on-Power EEPROM Contract (US-253, Sprint 21)

Pairs with US-216's staged shutdown (Sprint 16, fired Sprint 21 US-252) to
close the post-B-043 in-vehicle drill: key-OFF cuts wall power → UPS sustains
the Pi → US-216 fires `systemctl poweroff` at the VCELL TRIGGER threshold →
Pi sits halted on UPS battery → key-ON returns wall power → **Pi must
auto-boot without operator action** (there is no operator at the car).

The load-bearing setting is `POWER_OFF_ON_HALT` in the Pi 5 bootloader EEPROM:

| Value | Behavior on `systemctl poweroff` | Wake-on-power |
|-------|----------------------------------|----------------|
| `0` (or absent — default) | SoC halts; PMIC stays awake watching power rails | **Auto-boots when wall power returns** ✅ |
| Non-zero (e.g. `1`) | Deep sleep; PMIC also stops | **Requires button press or full power-cycle** ❌ |

`chi-eclipse-01` is on default behavior today (line absent → default 0). The
risk is **out-of-band drift**: any operator running `sudo rpi-eeprom-config
--edit` for an unrelated reason can flip the setting silently, and the
breakage only surfaces the next time wall power is cut and restored — i.e.
during a real drill, not during deploy.

**Enforcement: every deploy verifies and re-asserts**. `deploy-pi.sh` runs
`step_enforce_eeprom_power_off_on_halt` on every routine deploy and `--init`,
which SSH-invokes `deploy/enforce-eeprom-power-off-on-halt.sh` on the Pi:

```
deploy-pi.sh
  └── step_enforce_eeprom_power_off_on_halt
        └── ssh Pi: sudo bash deploy/enforce-eeprom-power-off-on-halt.sh
              ├── reads `rpi-eeprom-config` output
              ├── line absent      → no-op (defaults to 0)
              ├── value = 0        → no-op (already correct)
              ├── value ≠ 0        → rewrite via `rpi-eeprom-config --apply`
              └── tool missing/fails → exit non-zero, halt deploy
```

The enforcement script is idempotent — back-to-back runs converge with no
EEPROM writes after the first. The deploy script accepts the standard
`--dry-run` flag (prints what would be done without touching the Pi).

**Test fidelity**: `tests/deploy/test_eeprom_power_off_on_halt.sh` PATH-mocks
`rpi-eeprom-config` across 7 scenarios (absent / =0 / =1 / =2 / tool missing
/ apply fails / two-run idempotency drill). The mock seam is the
`RPI_EEPROM_CONFIG` env var the production script reads first
(falls back to a plain `rpi-eeprom-config` PATH lookup). The pytest wrapper
`tests/deploy/test_deploy_pi_eeprom_config.py` runs the bash test in the
fast suite so a regression in either the production script or the mock
harness shows up alongside other deploy regressions.

**What is NOT in scope**: actual end-to-end drill (graceful poweroff →
unplug → wait → replug → boot) is a post-sprint mechanical action item per
the no-human-tasks rule. Code-side this story makes that drill _possible_
to ship by guaranteeing the EEPROM setting is correct on every deploy.

---

## 12. Simulator Architecture

### Overview

The simulator subsystem provides hardware-free testing capabilities, enabling development and testing without physical OBD-II hardware.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Simulator Subsystem                                 │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Configuration Layer                            │  │
│  │   simulator.enabled  │  profilePath  │  scenarioPath  │  failures│  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Core Components                                │  │
│  │  SimulatedObdConnection  │  SensorSimulator  │  VehicleProfile   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Scenario System                                │  │
│  │  DriveScenario  │  DriveScenarioRunner  │  DrivePhase            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Testing Support                                │  │
│  │  FailureInjector  │  SimulatedVinDecoder  │  SimulatorCli        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| `SimulatedObdConnection` | Drop-in replacement for ObdConnection, same interface |
| `SensorSimulator` | Physics-based sensor value generation with noise |
| `VehicleProfile` | Vehicle characteristics (RPM limits, temperatures, etc.) |
| `DriveScenario` | Predefined sequences of drive phases |
| `DriveScenarioRunner` | Executes scenarios with smooth transitions |
| `FailureInjector` | Injects failures for error handling testing |
| `SimulatedVinDecoder` | Profile-based VIN decoding without NHTSA API |
| `SimulatorCli` | Keyboard commands for runtime control |

### Activation

Simulator mode is enabled via:
1. CLI flag: `python src/main.py --simulate`
2. Config: `simulator.enabled: true` in obd_config.json

### Built-in Scenarios

Located in `src/obd/simulator/scenarios/`:
- `cold_start.json` - Engine start and warmup cycle
- `city_driving.json` - Stop-and-go city driving (3 loops)
- `highway_cruise.json` - On-ramp acceleration and steady cruise
- `full_cycle.json` - Complete drive combining all phases

### Vehicle Profiles

Located in `src/obd/simulator/profiles/`:
- `default.json` - Generic 4-cylinder gasoline vehicle
- `eclipse_gst.json` - 1998 Mitsubishi Eclipse GST (project target)

---

## 13. Hardware Module Architecture

### Overview

The `src/hardware/` package provides Raspberry Pi hardware integration with graceful fallback on non-Pi systems.

### Components

| Component | Purpose |
|-----------|---------|
| `HardwareManager` | Central coordinator for all hardware modules |
| `UpsMonitor` | I2C telemetry from Geekworm X1209 UPS HAT |
| `ShutdownHandler` | Graceful shutdown on power loss or low battery |
| `GpioButton` | Physical shutdown button via GPIO |
| `StatusDisplay` | OSOYOO 3.5" HDMI touch display (480x320) |
| `TelemetryLogger` | System telemetry logging to rotating files |
| `I2cClient` | Low-level I2C communication with retry logic |

### Initialization Order

Hardware components must be initialized in specific order within the ApplicationOrchestrator:

```
1. Display (console/minimal) - First, provides fallback output
2. HardwareManager        - After display, before data components
3. Data components        - OBD connection, database, etc.
```

### Shutdown Order

Shutdown in reverse order:

```
1. Data components        - Stop data collection first
2. HardwareManager        - May use display for final status
3. Display                - Last, after all output complete
```

### Component Wiring

HardwareManager wires components via callbacks:

```
UpsMonitor.onPowerSourceChange -> ShutdownHandler (schedules shutdown)
UpsMonitor.telemetry -> StatusDisplay (updates battery/power display)
GpioButton.onLongPress -> ShutdownHandler._executeShutdown (manual shutdown)
UpsMonitor -> TelemetryLogger (battery data for logging — see TelemetryLogger Data Trail below)
```

### TelemetryLogger Data Trail

TelemetryLogger is **LIVE on Pi production** (US-251 audit, Sprint 20, 2026-05-01). Activation chain:

```
core.runLoop (core.py:726)
  -> _startHardwareManager (lifecycle.py:823)
  -> HardwareManager.start (hardware_manager.py:234)
     -> _initializeTelemetryLogger        (creates instance)
     -> _wireComponents                   (calls setUpsMonitor with the live UpsMonitor)
     -> _startComponents                  (calls TelemetryLogger.start -> daemon thread)
```

The daemon thread polls `UpsMonitor.getTelemetry()` every `telemetryLogInterval` seconds (default 10s) and emits a JSON line to a `RotatingFileHandler`.

| Property | Default value |
|----------|---------------|
| Output path | `/var/log/carpi/telemetry.log` (configurable via `HardwareManager(telemetryLogPath=...)`) |
| Rotation | 100 MB max, 7 backup files (`telemetry.log.1` … `telemetry.log.7`) |
| Format | One JSON object per line (`JsonFormatter`) |
| Cadence | 10 s |
| Activation gate | `isRaspberryPi() AND pi.hardware.enabled (default True)` — Pi-only by design |

JSON record shape (`TelemetryLogger.getTelemetry`):

```json
{
  "timestamp": "2026-05-01T13:42:18.123456Z",
  "power_source": "external|battery|unknown",
  "battery_v": 4.118,
  "battery_pct": 87,
  "battery_charge_rate_pct_per_hr": -2.5,
  "ext5v_v": 4.972,
  "cpu_temp": 47.5,
  "disk_free_mb": 38214
}
```

`battery_v`, `battery_pct`, `charge_rate`, and `ext5v_v` come from `UpsMonitor.getTelemetry()`; `cpu_temp` reads `/sys/class/thermal/thermal_zone0/temp`; `disk_free_mb` reads `shutil.disk_usage('/')`. UPS errors are spam-suppressed: first failure logs at WARNING, second at WARNING (with "suppressing further warnings"), all subsequent at DEBUG, until a successful read resets the counter.

**Drain-event forensic value (TD-033 closure).** During an AC→BATTERY transition, this file is the canonical 10-second-resolution record of `power_source`, `battery_v`, and `charge_rate` outside the database. Operators inspecting a drain post-mortem on the Pi:

```bash
ssh chi-eclipse-01 'tail -n 200 /var/log/carpi/telemetry.log | jq .'
ssh chi-eclipse-01 'zcat /var/log/carpi/telemetry.log.1 | jq "select(.power_source==\"battery\")"'
```

This complements `power_log` (post-US-243, every poll, schema-typed) and `battery_health_log` (one row per drain event). Where the DB tables are queryable but require a working SQLite/sync path, this file survives a database lock or sync outage.

### Non-Pi Fallback

All hardware modules check `isRaspberryPi()` and handle unavailability gracefully:
- Log warning message
- Set `isAvailable = False`
- Return safe defaults or skip operations
- Never crash on non-Pi systems

---

## 14. VIN Decoder

### Overview

The VIN decoder queries the NHTSA vPIC API to resolve vehicle information from the 17-character VIN.

| Property | Value |
|----------|-------|
| API endpoint | `https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json` |
| Timeout | 30s (configurable via `vinDecoder.apiTimeoutSeconds`) |
| Retry | 1 retry on transient failures |
| Caching | Results stored in `vehicle_info` table. Subsequent lookups return cached data (`fromCache=True`). |

### VIN Validation (ISO 3779)

- Must be exactly 17 characters
- Cannot contain I, O, or Q
- Invalid VINs return `success=False` without API call

### Known Behaviors

- **Pre-1996 VINs**: NHTSA returns ErrorCode 8 ("No detailed data available"). Make/year may be present but model, engine, transmission, etc. will be NULL. This is expected, not a bug.
- **TransmissionStyle**: Frequently empty in NHTSA data even for modern vehicles. Do not treat NULL transmission as an error.
- **Field mapping**: Make, Model, ModelYear, EngineModel, FuelTypePrimary, TransmissionStyle, DriveType, BodyClass, PlantCity, PlantCountry are stored in `vehicle_info` columns.

---

## 15. Component Initialization Order

The ApplicationOrchestrator initializes 12 components in strict dependency order (~2s startup):

```
Database → ProfileManager → Connection → VinDecoder → DisplayManager →
HardwareManager → StatisticsEngine → DriveDetector → AlertManager →
DataLogger → ProfileSwitcher → BackupManager
```

Shutdown is reverse order (~0.1s).

### Data Flow Through Components

| Event | Flow |
|-------|------|
| Reading | DataLogger → Orchestrator._handleReading → DisplayManager + DriveDetector + AlertManager |
| Drive start/end | DriveDetector → Orchestrator._handleDriveStart/End → DisplayManager + external callback |
| Alert | AlertManager → Orchestrator._handleAlert → DisplayManager + HardwareManager + external |
| Analysis | StatisticsEngine → Orchestrator._handleAnalysisComplete → DisplayManager + external |
| Profile change | ProfileSwitcher → Orchestrator._handleProfileChange → AlertManager + DataLogger |

---

## 16. Hardware Graceful Degradation

When hardware is absent, the system degrades gracefully without crashing:

| Component | Absent Behavior |
|-----------|----------------|
| **UPS (MAX17048 fuel gauge at 0x36)** | UpsMonitor logs first failure as WARNING, backs off polling interval from 5s to 60s after 3rd failure, logs subsequent failures at DEBUG. No crash. |
| **GPIO button** | One-time ERROR logged (`Cannot determine SOC peripheral base address`), button feature disabled. Needs `lgpio` package for Pi 5. No crash. |
| **HDMI display (no X11)** | StatusDisplay logs first GL context error, suppresses repeats at DEBUG level. Falls back to headless mode. No crash. |
| **Bluetooth dongle** | Connection manager handles via configurable retry with exponential backoff. |
| **Ollama (remote down)** | AiAnalyzer returns gracefully with error message. Post-drive workflow completes without AI analysis. |

All hardware modules check `isRaspberryPi()` and set `isAvailable = False` when hardware is not detected.

---

## 17. ECMLink Data Architecture (Phase 2)

### Overview

Phase 2 replaces OBD-II as the primary data source with ECMLink V3, which communicates directly with the 4G63 ECU via Mitsubishi's proprietary MUT protocol at **15,625 baud**. This delivers ~10x the effective sample rate of OBD-II Bluetooth, unlocking parameters critical for tuning that are invisible to standard OBD-II (knock count, wideband AFR, injector duty cycle, true boost).

**Status**: Design only — blocked on ECMLink V3 hardware installation (Summer 2026).

OBD-II (Phase 1) continues running alongside ECMLink for emissions-relevant parameters and as a fallback data source.

### 17.1 ECMLink Parameter Schema (15 Priority Parameters)

| # | Parameter | Data Type | Unit | Sample Rate | Channel Name | Priority Tier |
|---|-----------|-----------|------|-------------|--------------|---------------|
| 1 | Wideband AFR | float | ratio | 20 Hz | `WIDEBAND_AFR` | ECM-1 (Safety) |
| 2 | Knock Count | int | count | 20 Hz | `KNOCK_COUNT` | ECM-1 (Safety) |
| 3 | Knock Sum | int | count | 20 Hz | `KNOCK_SUM` | ECM-1 (Safety) |
| 4 | Boost/MAP | float | psi | 20 Hz | `BOOST_MAP` | ECM-1 (Safety) |
| 5 | Timing Advance | float | degrees | 20 Hz | `TIMING_ADV` | ECM-1 (Safety) |
| 6 | RPM | int | rpm | 20 Hz | `RPM` | ECM-1 (Safety) |
| 7 | TPS | float | percent | 20 Hz | `TPS` | ECM-1 (Safety) |
| 8 | Injector Duty Cycle | float | percent | 10 Hz | `INJECTOR_DC` | ECM-2 (Performance) |
| 9 | Target AFR | float | ratio | 10 Hz | `TARGET_AFR` | ECM-2 (Performance) |
| 10 | STFT | float | percent | 10 Hz | `STFT` | ECM-2 (Performance) |
| 11 | Coolant Temp | float | fahrenheit | 5 Hz | `COOLANT_TEMP` | ECM-3 (Monitoring) |
| 12 | IAT | float | fahrenheit | 5 Hz | `IAT` | ECM-3 (Monitoring) |
| 13 | Ethanol Content | float | percent | 1 Hz | `ETHANOL_CONTENT` | ECM-4 (Background) |
| 14 | LTFT | float | percent | 1 Hz | `LTFT` | ECM-4 (Background) |
| 15 | Barometric Pressure | float | kPa | 0.5 Hz | `BARO_PRESSURE` | ECM-5 (Slow) |

### 17.2 Sample Rate Tiers

Mirrors the Phase 1 tiered polling concept but at ECMLink speeds:

| Tier | Rate | Parameters | Samples/sec | Rationale |
|------|------|------------|-------------|-----------|
| ECM-1 (Safety) | 20 Hz | AFR, Knock Count, Knock Sum, Boost, Timing, RPM, TPS | 140 | Knock and detonation detection requires high-frequency data |
| ECM-2 (Performance) | 10 Hz | Injector DC, Target AFR, STFT | 30 | Fueling health — important but slower-moving |
| ECM-3 (Monitoring) | 5 Hz | Coolant Temp, IAT | 10 | Thermal parameters change slowly |
| ECM-4 (Background) | 1 Hz | Ethanol Content, LTFT | 2 | Stable values that rarely change mid-drive |
| ECM-5 (Slow) | 0.5 Hz | Barometric Pressure | 0.5 | Ambient — changes only with altitude |
| **Total** | | **15 parameters** | **~182.5** | **~657K samples/hr** |

### 17.3 Database Schema

Three new tables, separate from Phase 1 OBD-II tables. The `ecmlink_data` table follows the same EAV (Entity-Attribute-Value) pattern as `realtime_data` for consistency, but is kept separate to avoid mixing data sources and to allow independent retention policies and indexing.

#### Table: `ecmlink_sessions`

Tracks ECMLink logging sessions (one per ignition-on-to-off cycle or manual start/stop).

```sql
CREATE TABLE IF NOT EXISTS ecmlink_sessions (
    session_id TEXT PRIMARY KEY,
    start_time DATETIME NOT NULL,
    end_time DATETIME,
    serial_port TEXT NOT NULL,
    baud_rate INTEGER NOT NULL DEFAULT 15625,
    parameters_logged TEXT,
    total_samples INTEGER DEFAULT 0,
    profile_id TEXT,
    notes TEXT,
    CONSTRAINT FK_ecmlink_sessions_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE SET NULL
);
```

| Column | Purpose |
|--------|---------|
| `session_id` | UUID or timestamp-based ID |
| `serial_port` | e.g., `/dev/ttyUSB0` on Pi |
| `baud_rate` | MUT protocol speed (15,625 default) |
| `parameters_logged` | JSON array of channel names active this session |
| `total_samples` | Running count, updated on session close |
| `profile_id` | Links to active tuning profile |

#### Table: `ecmlink_parameters`

Parameter registry — metadata for each ECMLink channel. Populated once, referenced by ingestion pipeline.

```sql
CREATE TABLE IF NOT EXISTS ecmlink_parameters (
    name TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK(data_type IN ('float', 'int')),
    unit TEXT NOT NULL,
    sample_rate_hz REAL NOT NULL,
    tier TEXT NOT NULL,
    description TEXT,
    safe_range_min REAL,
    safe_range_max REAL
);
```

| Column | Purpose |
|--------|---------|
| `name` | Channel name (e.g., `KNOCK_COUNT`) — matches `ecmlink_data.parameter_name` |
| `data_type` | `float` or `int` — guides display formatting |
| `sample_rate_hz` | Target sample rate for this parameter |
| `tier` | `ECM-1` through `ECM-5` — scheduling tier |
| `safe_range_min/max` | Optional bounds for alert evaluation |

#### Table: `ecmlink_data`

Time-series storage for all ECMLink readings. EAV pattern consistent with `realtime_data`.

```sql
CREATE TABLE IF NOT EXISTS ecmlink_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    parameter_name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    session_id TEXT,
    profile_id TEXT,
    CONSTRAINT FK_ecmlink_data_session FOREIGN KEY (session_id)
        REFERENCES ecmlink_sessions(session_id)
        ON DELETE SET NULL,
    CONSTRAINT FK_ecmlink_data_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE SET NULL
);
```

#### Indexes

```sql
CREATE INDEX IX_ecmlink_data_timestamp ON ecmlink_data(timestamp);
CREATE INDEX IX_ecmlink_data_session ON ecmlink_data(session_id);
CREATE INDEX IX_ecmlink_data_param_timestamp ON ecmlink_data(parameter_name, timestamp);
CREATE INDEX IX_ecmlink_sessions_start_time ON ecmlink_sessions(start_time);
```

The compound index `IX_ecmlink_data_param_timestamp` is critical for the most common query pattern: "give me all readings of parameter X between time A and time B."

#### ER Diagram (Phase 2 additions)

```
┌─────────────────────────┐
│   ecmlink_parameters    │
├─────────────────────────┤
│ name (PK)               │
│ display_name            │
│ data_type               │
│ unit                    │
│ sample_rate_hz          │
│ tier                    │
│ description             │
│ safe_range_min          │
│ safe_range_max          │
└─────────────────────────┘

┌─────────────────────────┐     ┌─────────────────────────┐
│   ecmlink_sessions      │     │      profiles           │
├─────────────────────────┤     ├─────────────────────────┤
│ session_id (PK)         │     │ id (PK)                 │
│ start_time              │──┐  │ name                    │
│ end_time                │  │  │ ...                     │
│ serial_port             │  │  └──────────┬──────────────┘
│ baud_rate               │  │             │
│ parameters_logged       │  │  ┌──────────▼──────────────┐
│ total_samples           │  │  │     ecmlink_data        │
│ profile_id (FK)─────────│──┤  ├─────────────────────────┤
│ notes                   │  │  │ id (PK)                 │
└─────────────────────────┘  │  │ timestamp               │
                             └──│ session_id (FK)         │
                                │ parameter_name          │
                                │ value                   │
                                │ unit                    │
                                │ profile_id (FK)─────────│
                                └─────────────────────────┘
```

### 17.4 Ingestion Interface

ECMLink serial data enters the system through a dedicated ingestion pipeline, separate from the OBD-II Bluetooth path.

#### Data Flow

```
ECMLink V3 (ECU)
    │
    │  MUT Protocol (15,625 baud, serial)
    ▼
USB-Serial Adapter (/dev/ttyUSB0)
    │
    ▼
┌────────────────────────────────┐
│  ECMLink Serial Reader         │
│  (dedicated thread)            │
│                                │
│  1. Open serial port           │
│  2. Parse MUT protocol frames  │
│  3. Timestamp each sample      │
│  4. Route to sample buffer     │
└──────────┬─────────────────────┘
           │
           ▼
┌────────────────────────────────┐
│  Sample Buffer                 │
│  (in-memory ring buffer)       │
│                                │
│  - Capacity: 1000 samples      │
│  - Batch flush threshold: 100  │
│  - Max flush interval: 500ms   │
└──────────┬─────────────────────┘
           │
           ▼
┌────────────────────────────────┐
│  Batch Writer                  │
│  (separate thread)             │
│                                │
│  1. Dequeue batch from buffer  │
│  2. BEGIN TRANSACTION          │
│  3. INSERT batch into          │
│     ecmlink_data               │
│  4. COMMIT                     │
│  5. Update session counters    │
└──────────┬─────────────────────┘
           │
           ▼
      SQLite (WAL mode)
```

#### Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Separate table** (`ecmlink_data` not `realtime_data`) | Different data source, different sample rates (30x more volume), independent retention needs. Clean Phase 1/Phase 2 isolation. |
| **EAV pattern** (not wide table) | Consistent with Phase 1. Adding new ECMLink parameters requires zero schema changes. Sparse sampling (mixed rates) doesn't waste space on NULLs. |
| **Batch writes** (not per-sample) | At ~182 samples/sec, individual INSERTs would be ~182 transactions/sec. Batching 100 samples per transaction keeps SQLite happy and reduces I/O. |
| **Ring buffer** (not unbounded queue) | Memory-bounded on Pi 5 (8GB). If writer falls behind, oldest unwritten samples are dropped — better to lose old data than OOM. |
| **Session tracking** | ECMLink logging sessions map to ignition cycles. Session metadata enables "show me all data from drive #47" queries and cleanup. |
| **Dedicated threads** (reader + writer) | Serial I/O blocks on frame arrival; database I/O blocks on disk. Separating them keeps both responsive. |

#### Serial Protocol Notes

- **Baud rate**: 15,625 (MUT protocol, fixed)
- **Connection**: USB-to-serial adapter, typically `/dev/ttyUSB0` on Pi
- **Frame format**: ECMLink-specific binary frames (documented at ecmlink.com)
- **Handshake**: ECMLink software initiates MUT communication; our reader taps into the serial stream
- **Error handling**: CRC/checksum validation per frame. Invalid frames are logged and discarded, not retried.

#### Configuration (obd_config.json, future)

```json
{
    "ecmlink": {
        "enabled": false,
        "serialPort": "${ECMLINK_SERIAL_PORT:/dev/ttyUSB0}",
        "baudRate": 15625,
        "batchSize": 100,
        "maxFlushIntervalMs": 500,
        "bufferCapacity": 1000,
        "parameters": [
            {"name": "WIDEBAND_AFR", "enabled": true, "tier": "ECM-1"},
            {"name": "KNOCK_COUNT", "enabled": true, "tier": "ECM-1"},
            {"name": "KNOCK_SUM", "enabled": true, "tier": "ECM-1"},
            {"name": "BOOST_MAP", "enabled": true, "tier": "ECM-1"},
            {"name": "TIMING_ADV", "enabled": true, "tier": "ECM-1"},
            {"name": "RPM", "enabled": true, "tier": "ECM-1"},
            {"name": "TPS", "enabled": true, "tier": "ECM-1"},
            {"name": "INJECTOR_DC", "enabled": true, "tier": "ECM-2"},
            {"name": "TARGET_AFR", "enabled": true, "tier": "ECM-2"},
            {"name": "STFT", "enabled": true, "tier": "ECM-2"},
            {"name": "COOLANT_TEMP", "enabled": true, "tier": "ECM-3"},
            {"name": "IAT", "enabled": true, "tier": "ECM-3"},
            {"name": "ETHANOL_CONTENT", "enabled": true, "tier": "ECM-4"},
            {"name": "LTFT", "enabled": true, "tier": "ECM-4"},
            {"name": "BARO_PRESSURE", "enabled": true, "tier": "ECM-5"}
        ]
    }
}
```

### 17.5 Phase 1 / Phase 2 Coexistence

Both data sources run simultaneously. OBD-II continues providing emissions-relevant data and acts as a fallback if the ECMLink serial connection drops.

| Aspect | Phase 1 (OBD-II) | Phase 2 (ECMLink) |
|--------|-------------------|-------------------|
| Protocol | ELM327 over Bluetooth | MUT over USB serial |
| Sample rate | ~1 Hz per parameter | 0.5–20 Hz per parameter |
| Data table | `realtime_data` | `ecmlink_data` |
| Parameters | 16 standard PIDs | 15 priority + expandable |
| Alert thresholds | `tieredThresholds` in config | Shared alert system (future) |
| Primary use | Emissions monitoring, baseline | Tuning, knock detection, AFR |

Parameters that overlap (RPM, Coolant Temp, STFT, Timing Advance, IAT) will be sourced from ECMLink when available, with OBD-II as fallback. The alert system will be extended to accept either data source via a common `(parameter_name, value, timestamp)` tuple interface.

---

## 18. Data Volume Architecture (Phase 2)

### Overview

Phase 2 (ECMLink) generates ~30x the data volume of Phase 1 (OBD-II). This section documents storage estimates, retention policies, and sync strategy to ensure the system handles ECMLink data volumes across both Pi 5 (edge) and Chi-Srv-01 (server) without running out of disk, degrading query performance, or creating unsustainable sync loads.

**Status**: Design only — runtime implementation deferred until ECMLink hardware installation (Summer 2026).

### 18.1 Data Volume Estimates

#### Phase 1 (OBD-II via Bluetooth)

| Metric | Value | Derivation |
|--------|-------|------------|
| Effective sample rate | ~5 reads/sec | 12 PIDs across 4 tiers; Bluetooth latency reduces theoretical ~6/sec |
| Rows per hour | ~18,000 | 5 × 3,600 |
| Rows per 2-hour drive | ~36,000 | |
| Rows per season (~40 hrs driving) | ~720,000 | Summer-only car, weekend use |
| Rows per year (365-day retention) | ~720,000 | Same — car only runs in season |

#### Phase 2 (ECMLink via Serial)

| Metric | Value | Derivation |
|--------|-------|------------|
| Theoretical sample rate | ~182.5 reads/sec | 15 parameters across 5 tiers (Section 17.2) |
| Effective sample rate | ~150 reads/sec | Serial bandwidth constraint: 15,625 baud ÷ ~10 bits/byte = ~1,562 bytes/sec. MUT frame overhead (~3-4 bytes/param + framing) limits practical throughput |
| Rows per hour | ~540,000 | 150 × 3,600 |
| Rows per 2-hour drive | ~1,080,000 | |
| Rows per season (~40 hrs) | ~21,600,000 | |
| Phase 1 + Phase 2 combined/season | ~22,320,000 | Both run simultaneously (Section 17.5) |

#### Serial Bandwidth Constraint Detail

```
MUT Protocol: 15,625 baud, 8N1
Effective byte rate: ~1,562 bytes/sec
Estimated bytes per parameter read: ~8-10 bytes (address + response + framing)
Max parameters per second: ~1,562 / 9 ≈ 173 reads/sec
Accounting for handshake/sync overhead: ~150 reads/sec practical
```

The ~150 reads/sec practical rate drives all Phase 2 storage and bandwidth estimates. The theoretical 182.5/sec from Section 17.2 assumes zero protocol overhead.

### 18.2 Row Size Estimates

Both `realtime_data` (Phase 1) and `ecmlink_data` (Phase 2) use the same EAV schema pattern.

#### Per-Row Storage Breakdown

| Component | Bytes | Notes |
|-----------|-------|-------|
| `id` (INTEGER PK) | 8 | AUTOINCREMENT 64-bit |
| `timestamp` (DATETIME) | 8 | Stored as real/text (~19-23 chars) |
| `parameter_name` (TEXT) | ~16 | Avg channel name length (e.g., `KNOCK_COUNT`) |
| `value` (REAL) | 8 | 64-bit float |
| `unit` (TEXT) | ~8 | e.g., `percent`, `psi`, `rpm` |
| `session_id` (TEXT) | ~36 | UUID |
| `profile_id` (TEXT) | ~36 | UUID |
| SQLite row overhead | ~20 | Page headers, cell pointers, free space |
| **Subtotal (data row)** | **~140** | |

#### Index Overhead

| Index | Bytes/entry | Notes |
|-------|-------------|-------|
| `IX_ecmlink_data_timestamp` | ~30 | timestamp + rowid |
| `IX_ecmlink_data_session` | ~50 | session_id (TEXT) + rowid |
| `IX_ecmlink_data_param_timestamp` | ~50 | parameter_name + timestamp + rowid |
| **Subtotal (indexes)** | **~130** | |
| **Total per row (data + indexes)** | **~270 bytes** | |

#### Disk Usage Per Million Rows

| Storage Component | Size |
|-------------------|------|
| Data rows (1M × 140 bytes) | ~140 MB |
| Indexes (1M × 130 bytes) | ~130 MB |
| SQLite overhead (page alignment, free lists) | ~10% |
| **Total per 1M rows** | **~300 MB** |

### 18.3 Pi 5 SQLite Storage Strategy

#### Hardware Context

| Spec | Value |
|------|-------|
| Storage | microSD (64-128 GB typical) or NVMe via HAT |
| RAM | 8 GB |
| SQLite mode | WAL (already configured) |

#### Seasonal Storage Estimate (Pi)

| Data Source | Rows/Season | Size (with indexes) | Notes |
|-------------|-------------|---------------------|-------|
| Phase 1 (`realtime_data`) | ~720K | ~216 MB | 365-day retention (current config) |
| Phase 2 (`ecmlink_data`) | ~21.6M | ~6.5 GB | 90-day retention (new policy) |
| Phase 2 sessions/params | ~200 | <1 MB | Metadata tables |
| WAL file (peak) | — | ~200 MB | WAL grows during batch writes, checkpoints shrink it |
| **Total (one season)** | **~22.3M** | **~7.0 GB** | |

#### Can Pi Store a Full Season?

**Yes.** On a 64 GB microSD card:

| Allocation | Size |
|------------|------|
| OS + system | ~8 GB |
| Application + venv | ~2 GB |
| Logs | ~1 GB |
| OBD-II data (Phase 1, 1 year) | ~0.2 GB |
| ECMLink data (Phase 2, 90-day window) | ~6.5 GB |
| WAL headroom | ~0.5 GB |
| **Total used** | **~18.2 GB** |
| **Remaining** | **~45.8 GB** |
| **Utilization** | **~28%** |

With NVMe (256+ GB), storage is effectively unlimited for this use case.

#### Pi Retention Policy

| Table | Retention | Rationale |
|-------|-----------|-----------|
| `realtime_data` | 365 days | Current config. Low volume (~720K rows/season). Keep for full-season comparison. |
| `ecmlink_data` | 90 days | High volume. 90 days covers the active tuning season (May-September). Older data lives on Chi-Srv-01. |
| `ecmlink_sessions` | 90 days | Tied to ecmlink_data lifecycle. Cascade cleanup. |
| `statistics` | Forever | Aggregated — tiny footprint regardless of retention. |
| `alert_log` | 365 days | Low volume, high diagnostic value. |

**Cleanup Strategy**: Extend the existing `dataRetention` config with an `ecmlinkDataDays` field:

```json
{
    "dataRetention": {
        "realtimeDataDays": 365,
        "ecmlinkDataDays": 90,
        "statisticsRetentionDays": -1,
        "vacuumAfterCleanup": true,
        "cleanupTimeHour": 3
    }
}
```

Cleanup runs at 3 AM (existing `cleanupTimeHour`). For `ecmlink_data`, delete by timestamp:

```sql
DELETE FROM ecmlink_data
WHERE timestamp < datetime('now', '-90 days');

DELETE FROM ecmlink_sessions
WHERE end_time IS NOT NULL
  AND end_time < datetime('now', '-90 days');
```

Run `VACUUM` after cleanup to reclaim disk space (`vacuumAfterCleanup: true`).

#### SQLite Performance at Scale

At 21.6M rows, queries on `ecmlink_data` need index support:

| Query Pattern | Index Used | Expected Performance |
|---------------|-----------|---------------------|
| Parameter X between time A and B | `IX_ecmlink_data_param_timestamp` | <50ms (B-tree seek) |
| All data for session Y | `IX_ecmlink_data_session` | <100ms (session is bounded) |
| Recent N readings | `IX_ecmlink_data_timestamp` | <10ms (index scan from tail) |
| Full table scan | None | ~5-10 sec at 21.6M rows — **avoid** |

WAL mode (already enabled) prevents batch writes from blocking reads during driving. The `PRAGMA journal_size_limit` should be set to cap WAL growth during heavy ECMLink ingestion:

```sql
PRAGMA journal_size_limit = 67108864;  -- 64 MB WAL cap
```

### 18.4 Chi-Srv-01 MariaDB Strategy

#### Hardware Context

| Spec | Value |
|------|-------|
| CPU | i7-5960X (8 cores) |
| RAM | 128 GB |
| Storage | RAID array (multi-TB) |
| Database | MariaDB (`obd2db`) |
| Network | Gigabit Ethernet, same LAN as Pi (10.27.27.0/24) |

#### Retention Policy: Forever

Chi-Srv-01 is the permanent archive. All data synced from Pi is retained indefinitely. This enables:
- Multi-season trend analysis ("has knock behavior changed since injector upgrade?")
- Tuning profile comparison across months/years
- Full diagnostic history for engine health tracking

#### Storage Estimate (Multi-Season)

| Timeframe | ECMLink Rows | Size | Cumulative |
|-----------|-------------|------|------------|
| Season 1 (2026) | 21.6M | ~6.5 GB | 6.5 GB |
| Season 2 (2027) | 21.6M | ~6.5 GB | 13.0 GB |
| Season 3 (2028) | 21.6M | ~6.5 GB | 19.5 GB |
| 5 seasons | 108M | ~32.5 GB | 32.5 GB |
| 10 seasons | 216M | ~65 GB | 65 GB |

With Phase 1 data: add ~0.2 GB/season. Negligible.

At 128 GB RAM and multi-TB disk, Chi-Srv-01 handles 10+ seasons without concern. The InnoDB buffer pool can hold the hot working set entirely in memory.

#### Partitioning Strategy

Partition `ecmlink_data` by **month** using `RANGE` partitioning on `timestamp`. Monthly partitions enable:
- Fast partition pruning on time-range queries (the primary access pattern)
- Efficient bulk archival (detach old partitions to cold storage)
- Manageable backup units (~2-3 GB per active month)

```sql
CREATE TABLE ecmlink_data (
    id BIGINT AUTO_INCREMENT,
    timestamp DATETIME(3) NOT NULL,
    parameter_name VARCHAR(50) NOT NULL,
    value DOUBLE NOT NULL,
    unit VARCHAR(20),
    session_id VARCHAR(36),
    profile_id VARCHAR(36),
    PRIMARY KEY (id, timestamp),
    INDEX IX_ecmlink_data_param_timestamp (parameter_name, timestamp),
    INDEX IX_ecmlink_data_session (session_id)
) ENGINE=InnoDB
PARTITION BY RANGE (TO_DAYS(timestamp)) (
    PARTITION p2026_05 VALUES LESS THAN (TO_DAYS('2026-06-01')),
    PARTITION p2026_06 VALUES LESS THAN (TO_DAYS('2026-07-01')),
    PARTITION p2026_07 VALUES LESS THAN (TO_DAYS('2026-08-01')),
    PARTITION p2026_08 VALUES LESS THAN (TO_DAYS('2026-09-01')),
    PARTITION p2026_09 VALUES LESS THAN (TO_DAYS('2026-10-01')),
    PARTITION p_future VALUES LESS THAN MAXVALUE
);
```

**Partition maintenance**: At season start each year, `ALTER TABLE ... REORGANIZE PARTITION p_future` to add the new season's monthly partitions. Automate via cron or manual DBA task (low frequency — once per year).

#### Indexing for 21M+ Rows

| Index | Columns | Purpose |
|-------|---------|---------|
| PRIMARY KEY | `(id, timestamp)` | Required for RANGE partitioning — timestamp in PK enables partition pruning |
| `IX_ecmlink_data_param_timestamp` | `(parameter_name, timestamp)` | Primary query pattern: "parameter X between time A and B" |
| `IX_ecmlink_data_session` | `(session_id)` | Session-scoped queries: "all data from drive #47" |

**Not indexed**: `profile_id`, `unit` — low-cardinality columns better served by full-partition scans than index maintenance overhead at this volume.

InnoDB buffer pool recommendation: Allocate 64 GB to `innodb_buffer_pool_size` (50% of 128 GB RAM). At 6.5 GB/season, the entire active season's data + indexes fit in memory.

### 18.5 Sync Strategy (Pi → Chi-Srv-01)

#### Network Context

| Spec | Value |
|------|-------|
| WiFi network | DeathStarWiFi (10.27.27.0/24) |
| Pi 5 WiFi | 802.11ac (WiFi 5), ~100-200 Mbps practical |
| Chi-Srv-01 | Gigabit Ethernet to same LAN |
| Effective throughput | ~50-100 Mbps (WiFi bottleneck) |

#### Sync Bandwidth Estimate: 2-Hour ECMLink Drive

| Step | Value |
|------|-------|
| Rows generated | ~1,080,000 (540K/hr × 2) |
| Raw data size | ~1,080,000 × 270 bytes = ~292 MB |
| Compressed (gzip, ~3:1 on text/numeric data) | ~100 MB |
| Transfer time at 50 Mbps | ~16 seconds |
| Transfer time at 100 Mbps | ~8 seconds |
| **Practical estimate (with protocol overhead)** | **~20-30 seconds** |

A full season's sync (21.6M rows, ~6.5 GB raw, ~2.2 GB compressed) takes ~3-6 minutes. This is a one-time bulk transfer if the Pi was offline.

#### Sync Mechanism (Design)

Sync runs post-drive when Pi reconnects to WiFi (garage). The sync pipeline:

```
Pi (SQLite)                              Chi-Srv-01 (MariaDB)
    │                                         │
    │  1. Detect WiFi connection              │
    │  2. Query unsynced rows:                │
    │     SELECT * FROM ecmlink_data          │
    │     WHERE id > last_synced_id           │
    │  3. Batch export to compressed          │
    │     JSON/CSV chunks (10K rows each)     │
    │                                         │
    │  ──── compressed chunks over HTTP ────► │
    │                                         │
    │                   4. Bulk INSERT         │
    │                      (LOAD DATA INFILE  │
    │                       or batch INSERT)  │
    │                   5. Acknowledge receipt │
    │                                         │
    │  ◄──── ack (last_synced_id) ──────────  │
    │                                         │
    │  6. Update local sync watermark         │
    │                                         │
```

**Sync watermark**: Track `last_synced_id` per table in a local `sync_status` table on Pi. This avoids re-sending data after a partial sync.

```sql
-- Pi-side sync tracking
CREATE TABLE IF NOT EXISTS sync_status (
    table_name TEXT PRIMARY KEY,
    last_synced_id INTEGER NOT NULL DEFAULT 0,
    last_sync_time DATETIME,
    target_server TEXT NOT NULL DEFAULT 'chi-srv-01'
);
```

**Conflict resolution**: None needed — Pi is the sole writer, Chi-Srv-01 is append-only archive. No bidirectional sync.

#### Sync Frequency

| Trigger | Behavior |
|---------|----------|
| Post-drive (WiFi reconnect) | Auto-sync unsynced rows. Primary trigger. |
| Nightly (3 AM, with cleanup) | Catch any missed syncs. |
| Manual | `python src/main.py --sync` for on-demand sync. |

### 18.6 Retention Policy Validation

#### Can the 90-day Pi / forever-server policy handle Phase 2 volumes?

| Validation Check | Result | Notes |
|-----------------|--------|-------|
| Pi disk at 90 days (ECMLink) | ~6.5 GB max | Well within 64 GB SD card |
| Pi disk at 90 days (total) | ~7.0 GB max | Phase 1 + Phase 2 + overhead |
| Pi cleanup runtime | <30 sec | DELETE with timestamp index, then VACUUM |
| Chi-Srv-01 at 1 season | ~6.7 GB | Phase 1 + Phase 2, trivial for multi-TB RAID |
| Chi-Srv-01 at 10 seasons | ~67 GB | Fits in RAM buffer pool, no performance concern |
| Sync backlog after 90 days offline | ~6.5 GB / ~2.2 GB compressed | ~3-6 min sync, acceptable |
| WAL size during ECMLink ingestion | ≤64 MB (capped) | Checkpoint keeps WAL bounded |

**Conclusion**: The 90-day Pi retention / forever server retention policy is validated at Phase 2 volumes. No storage constraints on either platform. The main risk is WAL growth during heavy ingestion, mitigated by `PRAGMA journal_size_limit`.

### 18.7 Summary

| Metric | Phase 1 (OBD-II) | Phase 2 (ECMLink) | Combined |
|--------|-------------------|-------------------|----------|
| Sample rate | ~5/sec | ~150/sec | ~155/sec |
| Rows per hour | ~18K | ~540K | ~558K |
| Rows per season | ~720K | ~21.6M | ~22.3M |
| Disk per season (with indexes) | ~216 MB | ~6.5 GB | ~6.7 GB |
| Pi retention | 365 days | 90 days | — |
| Server retention | Forever | Forever | — |
| 2-hr drive sync time | <1 sec | ~20-30 sec | ~30 sec |
| Pi storage headroom (64 GB) | 92% free | 72% free | 72% free |

---

## 19. Future Considerations

### Planned Enhancements

- [ ] Custom PID support for turbo boost monitoring
- [ ] Web dashboard for remote monitoring
- [ ] Mobile app integration
- [ ] GPS tracking module

### Technical Debt

- [ ] Async OBD-II polling for better performance
- [ ] Connection pooling for database writes
- [ ] Display rendering optimization

---

## 20. Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-05-01 | Rex (US-257, Ralph) | Section 10 Display Architecture: added "Full-Canvas Status Overlay Redesign (US-257, B-052, Sprint 21)" subsection. Documents the new pure-geometry layout module `pi.hardware.dashboard_layout` (4-quadrant: engine NW / power NE / drive SW / alerts SE + footer band), proportional font scaling against a 1080-tall reference with a clamped minimum, the staged-shutdown stage banner wiring (`updateShutdownStage` setter on `StatusDisplay`, NE quadrant background tints with stage color so an operator several feet from the screen can read the stage), and the additive `pi.display.displayCanvas.{width,height,mode}` config surface (defaults 1920x1080 + mode='auto'; legacy 480x320 still works for dev/test). Test surface: 27 tests in `tests/pi/hardware/test_dashboard_layout.py` (parameterized over 1920x1080 / 1280x720 / 480x320) + 13 new canvas-size + shutdown-stage tests in `tests/pi/hardware/test_status_display.py`. |
| 2026-05-01 | Rex (US-253, Ralph) | Section 11 Deployment Architecture: added "Wake-on-Power EEPROM Contract (US-253, Sprint 21)" subsection.  Documents the `POWER_OFF_ON_HALT` Pi 5 bootloader setting (0 = SoC halts but PMIC stays awake to detect wall-power return → auto-boot; non-zero = deep sleep → requires button press) and the enforcement chain (`deploy-pi.sh` → `step_enforce_eeprom_power_off_on_halt` → SSH-invokes `deploy/enforce-eeprom-power-off-on-halt.sh` which reads via `rpi-eeprom-config`, idempotent rewrite via `--apply` only when the value is non-zero).  Pairs with US-216 + US-252 (staged shutdown) to close the post-B-043 in-vehicle drill: key-OFF → graceful poweroff → key-ON → auto-boot.  Test fidelity: PATH-mocked `rpi-eeprom-config` covers 7 scenarios (absent / =0 / =1 / =2 / tool missing / apply fails / two-run idempotency).  Real end-to-end drill (unplug/replug) remains a post-sprint mechanical action item. |
| 2026-05-01 | Rex (US-252, Ralph) | Section 10.6 Power-Down Orchestrator: added "Tick Driver Decoupled From Display (US-252, Sprint 21)" subsection documenting the architectural fix that closes the 5-drain-test silent-failure mode -- pre-US-252 `tick()` rode on `_displayUpdateLoop` so any display init failure or `displayEnabled=false` killed the safety ladder.  Post-US-252 `HardwareManager._powerDownTickLoop` runs on its own daemon thread spawned whenever upsMonitor + orchestrator are wired regardless of display state.  Added "power_log Forensic Trail (US-252)" subsection documenting the new `vcell` column + three new event types (`stage_warning`/`stage_imminent`/`stage_trigger`) + the `powerLogWriter` injection pattern (closure built in `_createPowerLogWriter`, mirrors `_createBatteryHealthRecorder`).  Story scope referenced "Section 11" but the actual home is 10.6 (Power-Down Orchestrator); 7th story-scope phantom-path drift in a row -- noted for Marcus's PRD-template generator follow-up. |
| 2026-05-01 | Rex (US-251, Ralph) | Section 13 Hardware Module Architecture: added "TelemetryLogger Data Trail" subsection between Component Wiring and Non-Pi Fallback. Documents the LIVE activation chain (`core.runLoop` -> `_startHardwareManager` -> `HardwareManager.start` -> init/wire/start), file path + rotation policy (`/var/log/carpi/telemetry.log`, 100 MB / 7 backups, 10 s cadence), JSON record shape (8 fields), Pi-only activation gate (`isRaspberryPi() AND pi.hardware.enabled`), and the drain-event forensic value answering Spool's TD-033 question. Closes TD-033 LIVE outcome. Code unchanged; specs-only. |
| 2026-04-29 | Rex (US-238, Ralph) | Section 5 Server Schema Migrations registry: added v0005 row -- `CREATE TABLE dtc_log` mirroring the Sprint 15 US-204 ORM that never reached live MariaDB.  Section 10.5 DTC Lifecycle "Server mirror" paragraph: appended v0005 deploy-time-migration context explaining why Sprint 15's ORM + sync-wiring shipped without a CREATE TABLE (US-204 predated the US-213 explicit registry), what V-2 caught (Drive 4 health check 2026-04-29: `Table 'obd2db.dtc_log' doesn't exist`), and how v0005 closes the silent-data-loss-on-next-DTC-drive risk via the same CREATE-TABLE-IF-NOT-EXISTS + post-condition probe pattern as v0002 (battery_health_log). |
| 2026-04-29 | Rex (US-237, Ralph) | Section 5 drive_summary "Server mirror" paragraph: added the v0004 reconciliation note explaining why 148 Pi-sync attempts failed silently (Sprint 7-8 table never had US-206/US-195/US-200 columns ALTERed; v0001 catch-up scope excluded `drive_summary`), what v0004 ADDs (11 columns + `IX_drive_summary_drive_id` + `uq_drive_summary_source`), and the V-4 namespace cleanup (truncate 9 sim rows + cascade `drive_statistics` children, CIO 2026-04-29).  Section 5 Server Schema Migrations: added a registry table listing v0001-v0004 with story + purpose, anchoring the migration history for future deploys. |
| 2026-04-29 | Rex (US-236, Ralph) | Section 5 Drive-Start Metadata subsection: rewrote the cold-start backfill paragraph for Sprint 19's defer-INSERT semantics.  Was "INSERT empty row at drive_start, UPDATE-backfill columns" (Sprint 18 US-228 -- empirically broken across drives 3/4/5).  Now "no row at drive_start; INSERT when first IAT/BATTERY_V/BAROMETRIC_KPA arrives, OR force-INSERT at 60s deadline tagged result.reason='no_readings_within_timeout'".  Added 5 invariants (no row at drive_start / warm-restart-payload-empty defers too / 60s hard upper bound / re-entry safety / backfillFromSnapshot semantics unchanged).  Updated capture-site narrative: `_armDriveSummaryDeferInsert` replaces `_captureDriveStartSummary` as the per-drive entry point; `_maybeProgressDriveSummary` runs the two-phase defer-then-backfill loop on each `processValue` tick.  Schema doNotTouch -- `reason` lives on `SummaryCaptureResult.reason` + logs only, not in the drive_summary row.  UPSERT semantics on existing rows preserved for US-206 idempotency tests. |
| 2026-04-29 | Rex (US-234, Ralph) | Section 10.6 Power-Down Orchestrator: rewrote the trigger-source narrative + state-machine diagram + threshold table for the SOC% → VCELL switch (3.70/3.55/3.45V with 0.05V hysteresis). Added "Trigger source (US-234, Sprint 19)" subsection with the abandonment justification (4 drain tests; 40-pt MAX17048 SOC% calibration error documented in Spool's sprint19-consolidated note). Added schema-reuse note: `battery_health_log.start_soc` and `end_soc` columns now hold VCELL volts post-US-234 (column unrenamed per doNotTouch list). Updated Legacy Timer Suppression paragraph to describe the parallel-rail regression test. The state-machine shape (NORMAL → WARNING → IMMINENT → TRIGGER + AC-restore + hysteresis + callback isolation) is unchanged. |
| 2026-04-27 | Rex (US-231, Ralph) | Section 11 Deployment Architecture: rewrote the systemd `Auto-Start` subsection. Was a single illustrative Pi-only ini block from project init; now documents both tiers (`eclipse-obd.service` US-210 / `obd-server.service` US-231) with shared invariants (Restart=always, RestartSec=5, flap protection in Unit section, User=mcornelison, no inlined secrets, journalctl as single source of truth) + tier-specific differences (After= deps, working dirs, venv paths, ExecStart). Added per-unit ini snippets and the cutover narrative (one-time pkill orphan + systemctl restart). Source of truth remains `deploy/*.service`; spec snippet is illustrative. |
| 2026-04-27 | Rex (US-227, Ralph) | Section 5 Drive Lifecycle invariant #4: appended "Second operational truncate 2026-04-27 (US-227, Sprint 18)" paragraph documenting the drive_id=1 / data_source='real' DELETE script (`scripts/truncate_drive_id_1_pollution.py`). Differs from US-205 in scope: only drive_id=1 real rows; Drive 3 + Drive 2 sim + NULL drive_id orphans preserved by the WHERE clause. Sync gate refuses --execute unless `sync_log.realtime_data.last_synced_id ≥ 3,439,960` (Drive 3 max id). drive_counter advances to 3 idempotently. Sentinel `.us227-dry-run-ok` distinct from US-205. Pollution-window orphan scan on `ai_recommendations` + `calibration_sessions`. Same fixture-hash + Pi-service-stop envelope as US-205. |
| 2026-04-21 | Rex (US-219, Ralph) | Section 5: added "Post-drive review ritual (US-219, Sprint 16)" paragraph after the US-208 validator entry. Describes `scripts/post_drive_review.sh` as the CIO-facing wrapper that orchestrates `scripts/report.py`, `scripts/spool_prompt_invoke.py` (new CLI reusing `src/server/services/analysis.py`'s prompt-loading + Jinja-render + response-parse helpers), the `offices/tuner/drive-review-checklist.md` display, and the "where to record findings" pointer. All "no data" outcomes (empty drive, missing tables, Ollama unreachable / HTTP error, empty JSON response) exit 0 so the checklist + pointer always emit. Procedural walkthrough in `docs/testing.md` → Post-Drive Review Ritual. |
| 2026-04-12 | Ralph (US-138) | Added Section 18: Data Volume Architecture (Phase 2) — Phase 1 vs Phase 2 volume estimates (~5 vs ~150 reads/sec), row size analysis (~270 bytes/row with indexes), Pi 5 SQLite strategy (90-day ECMLink retention, ~7 GB/season, 28% of 64GB SD), Chi-Srv-01 MariaDB strategy (forever retention, monthly RANGE partitioning, 64GB InnoDB buffer pool), sync estimates (2-hr drive syncs in ~20-30 sec over WiFi), retention validation. Design doc only. |
| 2026-04-12 | Ralph (US-137) | Added Section 17: ECMLink Data Architecture (Phase 2) — 15 priority parameters, 5 sample rate tiers, 3 new database tables (ecmlink_sessions, ecmlink_parameters, ecmlink_data), ingestion interface design, Phase 1/2 coexistence strategy. Design doc only, no runtime implementation. |
| 2026-02-01 | Marcus (PM) | Major update per I-010: Database schema 7→12 tables with 16 indexes, PRAGMAs, added VIN Decoder (S14), Component Init Order (S15), Hardware Graceful Degradation (S16). Updated Ollama to remote Chi-Srv-01. |
| 2026-01-29 | Marcus (PM) | Fixed 5 drift items per I-002: Adafruit→OSOYOO display, 240x240→480x320, added backup config section, added src/backup/ and src/hardware/ to component table |
| 2026-01-26 | Knowledge Update | Added Hardware Module Architecture section (Section 13) with components, initialization order, wiring, and fallback behavior |
| 2026-01-22 | Knowledge Update | Updated Core Services section with domain subpackage structure and implemented modules |
| 2026-01-22 | Knowledge Update | Added simulator subsystem architecture (Section 12) |
| 2026-01-21 | M. Cornelison | Initial architecture document for Eclipse OBD-II project |
