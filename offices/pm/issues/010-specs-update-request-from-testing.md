# I-010: Specs Update Request — Findings from Pi 5 Testing

| Field        | Value                          |
|--------------|--------------------------------|
| Severity     | Info (spec update request)     |
| Status       | Closed                         |
| Category     | specs / documentation          |
| Found By     | Torque (Pi 5 Agent)            |
| Related      | I-006, I-009                   |
| Created      | 2026-02-01                     |

## Summary

During Pi 5 readiness testing (database inspection, simulate mode, VIN decoder, smoke test), I discovered project-wide knowledge that should be documented in `specs/` for all developers. Since `specs/` is read-only for agents, requesting PM to update the relevant spec files.

## Requested Updates

### 1. `specs/architecture.md` — Database Schema (CRITICAL)

**Current state**: Lists 7 tables.
**Actual state**: Database has **12 tables** and **16 indexes**.

Please update the database section with:

**Tables (12):**
| Table | Purpose | FK to profiles? |
|-------|---------|----------------|
| vehicle_info | NHTSA-decoded vehicle data, keyed by VIN | No |
| profiles | Driving profiles (daily, performance) | — (parent) |
| static_data | One-time OBD parameters (FUEL_TYPE, ECU_NAME) | FK to vehicle_info |
| realtime_data | Time-series OBD sensor readings | FK to profiles (SET NULL) |
| statistics | Post-drive statistical analysis results | FK to profiles (CASCADE) |
| ai_recommendations | AI-generated driving recommendations | FK to profiles (SET NULL), self-FK for duplicates |
| calibration_sessions | Calibration session tracking | FK to profiles (SET NULL) |
| alert_log | Threshold violation alerts | FK to profiles (SET NULL) |
| connection_log | OBD connection events (drive_start/end) | No FK |
| battery_log | UPS battery voltage readings | No FK |
| power_log | AC/battery power transitions | No FK |
| sqlite_sequence | SQLite internal autoincrement tracking | — |

**Indexes (16):**
| Index | Table | Column(s) |
|-------|-------|-----------|
| IX_realtime_data_timestamp | realtime_data | timestamp |
| IX_realtime_data_profile | realtime_data | profile_id |
| IX_realtime_data_param_timestamp | realtime_data | parameter_name, timestamp |
| IX_statistics_analysis_date | statistics | analysis_date |
| IX_statistics_profile | statistics | profile_id |
| IX_ai_recommendations_duplicate | ai_recommendations | is_duplicate_of |
| IX_alert_log_profile | alert_log | profile_id |
| IX_alert_log_timestamp | alert_log | timestamp |
| IX_connection_log_event_type | connection_log | event_type |
| IX_connection_log_timestamp | connection_log | timestamp |
| IX_battery_log_timestamp | battery_log | timestamp |
| IX_battery_log_event_type | battery_log | event_type |
| IX_power_log_timestamp | power_log | timestamp |
| IX_power_log_event_type | power_log | event_type |
| sqlite_autoindex_profiles_1 | profiles | id (auto) |
| sqlite_autoindex_vehicle_info_1 | vehicle_info | vin (auto) |

**PRAGMAs (set per-connection by ObdDatabase.connect()):**
- `foreign_keys = ON`
- `journal_mode = WAL`
- `synchronous = NORMAL`

Note: PRAGMAs are per-connection, not persisted to the database file. Raw `sqlite3.connect()` does NOT set them — always use `ObdDatabase.connect()`.

### 2. `specs/architecture.md` — VIN Decoder Behavior

Please add a VIN Decoder section:

- **API**: NHTSA vPIC at `https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json`
- **Timeout**: 30s (configurable via `vinDecoder.apiTimeoutSeconds`)
- **Retry**: 1 retry on transient failures
- **Caching**: Results stored in `vehicle_info` table. Subsequent lookups return cached data (`fromCache=True`).
- **Validation**: VIN must be exactly 17 characters, no I/O/Q (per ISO 3779). Invalid VINs return `success=False` without API call.
- **Pre-1996 VINs**: NHTSA returns ErrorCode 8 ("No detailed data available"). Make/year may be present but model, engine, transmission, etc. will be NULL. This is expected, not a bug.
- **TransmissionStyle**: Frequently empty in NHTSA data even for modern vehicles. Do not treat NULL transmission as an error.
- **Field mapping**: Make, Model, ModelYear, EngineModel, FuelTypePrimary, TransmissionStyle, DriveType, BodyClass, PlantCity, PlantCountry → stored in vehicle_info columns.

### 3. `specs/architecture.md` — Component Initialization Order

Please document the 12-component dependency chain:

```
Database → ProfileManager → Connection → VinDecoder → DisplayManager →
HardwareManager → StatisticsEngine → DriveDetector → AlertManager →
DataLogger → ProfileSwitcher → BackupManager
```

Shutdown is reverse order. Startup takes ~2s. Shutdown takes ~0.1s.

### 4. `specs/architecture.md` — Hardware Graceful Degradation

When hardware is absent, the system degrades gracefully:
- **UPS not connected**: UpsMonitor logs first failure as WARNING, backs off to 60s polling, logs subsequent failures at DEBUG. No crash.
- **GPIO button unavailable**: One-time ERROR logged, button feature disabled. No crash.
- **Display not available (no X11)**: StatusDisplay logs first GL error, suppresses repeats at DEBUG. Falls back to headless mode. No crash.
- **Bluetooth dongle not connected**: Connection manager handles via configurable retry with exponential backoff.

### 5. `specs/standards.md` — Database Coding Patterns

Please add these database coding guidelines:

- **Always use `ObdDatabase.connect()` context manager** — never raw `sqlite3.connect()`. The context manager sets required PRAGMAs (foreign_keys, WAL, synchronous).
- **`ObdDatabase.initialize()` is idempotent** — uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. Safe to run on populated databases.
- **ObdDatabase has no `close()` method** — uses context managers for connections. The database object itself is lightweight and doesn't hold open connections.
- **New indexes must be added to `ALL_INDEXES` list** in `src/obd/database.py` to be created automatically on `initialize()`.
- **FK constraints use `ON DELETE SET NULL` or `ON DELETE CASCADE`** — check the schema before inserting rows with profile_id references.

### 6. `specs/anti-patterns.md` — Log Spam in Polling Loops

Please add this anti-pattern:

**Anti-pattern**: Logging at ERROR/WARNING level inside polling loops for known-absent hardware.

**Example (bad)**:
```python
while not self._stopEvent.is_set():
    try:
        self.pollDevice()
    except DeviceNotFoundError as e:
        logger.warning(f"Device not found: {e}")  # Fires every 5 seconds!
    self._stopEvent.wait(timeout=5.0)
```

**Solution**: Use consecutive error counter. Log first occurrence at WARNING/ERROR, demote to DEBUG after N failures. Optionally back off poll interval.

```python
consecutiveErrors = 0
while not self._stopEvent.is_set():
    try:
        self.pollDevice()
        consecutiveErrors = 0
    except DeviceNotFoundError as e:
        consecutiveErrors += 1
        if consecutiveErrors == 1:
            logger.warning(f"Device not found: {e}")
        elif consecutiveErrors == 3:
            logger.warning("Device unreachable, suppressing further warnings")
        else:
            logger.debug(f"Device error (repeated): {e}")
    self._stopEvent.wait(timeout=self._pollInterval)
```

## Priority

Medium — these are documentation updates, not code changes. But the database schema drift (7 tables in spec vs 12 actual) should be corrected soon to avoid confusion for new developers.
