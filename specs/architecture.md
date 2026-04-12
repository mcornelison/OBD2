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
| Ollama on Chi-Srv-01 | AI recommendations | HTTP (10.27.27.120:11434) -- GPU-accelerated, never local on Pi |

### Hardware

| Component | Platform | Notes |
|-----------|----------|-------|
| Processor | Raspberry Pi 5 Model B | 8GB RAM for application headroom |
| Storage | 128GB A2 U3/V30 microSD | High-endurance recommended |
| Display | OSOYOO 3.5" HDMI Touch | 480x320, capacitive touch |
| Database | SQLite (WAL mode) | Local file database |
| Power | Geekworm X1209 UPS HAT | 18650 battery backup |
| Monitoring | I2C | Battery voltage/current via UPS telemetry |

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
| `power/` | Power monitoring | PowerMonitor, BatteryMonitor |
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

### Schema Overview (12 Tables)

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
| `battery_log` | UPS battery voltage readings | No FK | — |
| `power_log` | AC/battery power transitions | No FK | — |
| `sqlite_sequence` | SQLite internal autoincrement tracking | — | — |

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

┌─────────────────────┐     ┌─────────────────────┐
│    battery_log      │     │     power_log       │
├─────────────────────┤     ├─────────────────────┤
│ id (PK)             │     │ id (PK)             │
│ timestamp           │     │ timestamp           │
│ voltage             │     │ event_type          │
│ current             │     │ source              │
│ soc                 │     │ details             │
│ event_type          │     └─────────────────────┘
└─────────────────────┘
```

### Indexes (16)

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
| `IX_battery_log_timestamp` | battery_log | timestamp |
| `IX_battery_log_event_type` | battery_log | event_type |
| `IX_power_log_timestamp` | power_log | timestamp |
| `IX_power_log_event_type` | power_log | event_type |
| `sqlite_autoindex_profiles_1` | profiles | id (auto) |
| `sqlite_autoindex_vehicle_info_1` | vehicle_info | vin (auto) |

### PRAGMAs (set per-connection by ObdDatabase.connect())

- `foreign_keys = ON`
- `journal_mode = WAL`
- `synchronous = NORMAL`

**Important**: PRAGMAs are per-connection, not persisted to the database file. Raw `sqlite3.connect()` does NOT set them -- always use `ObdDatabase.connect()`.

### Data Retention

- **realtime_data**: 365 days (configurable)
- **statistics**: Indefinite
- **ai_recommendations**: Indefinite
- **calibration_sessions**: Manual management

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

---

## 11. Deployment Architecture

### Environments

| Environment | Purpose | Configuration |
|-------------|---------|---------------|
| Development | Local development | `.env.local` |
| Test | Automated testing | `.env.test` |
| Production | Raspberry Pi | `.env.production` |

### Auto-Start (systemd)

```ini
[Unit]
Description=Eclipse OBD-II Monitor
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/obd2/src/main.py
Restart=on-failure
RestartSec=10
MaxRestart=5

[Install]
WantedBy=multi-user.target
```

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
UpsMonitor -> TelemetryLogger (battery data for logging)
```

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
| **UPS (INA219 at 0x36)** | UpsMonitor logs first failure as WARNING, backs off polling interval from 5s to 60s after 3rd failure, logs subsequent failures at DEBUG. No crash. |
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

## 18. Future Considerations

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

## 19. Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-04-12 | Ralph (US-137) | Added Section 17: ECMLink Data Architecture (Phase 2) — 15 priority parameters, 5 sample rate tiers, 3 new database tables (ecmlink_sessions, ecmlink_parameters, ecmlink_data), ingestion interface design, Phase 1/2 coexistence strategy. Design doc only, no runtime implementation. |
| 2026-02-01 | Marcus (PM) | Major update per I-010: Database schema 7→12 tables with 16 indexes, PRAGMAs, added VIN Decoder (S14), Component Init Order (S15), Hardware Graceful Degradation (S16). Updated Ollama to remote Chi-Srv-01. |
| 2026-01-29 | Marcus (PM) | Fixed 5 drift items per I-002: Adafruit→OSOYOO display, 240x240→480x320, added backup config section, added src/backup/ and src/hardware/ to component table |
| 2026-01-26 | Knowledge Update | Added Hardware Module Architecture section (Section 13) with components, initialization order, wiring, and fallback behavior |
| 2026-01-22 | Knowledge Update | Updated Core Services section with domain subpackage structure and implemented modules |
| 2026-01-22 | Knowledge Update | Added simulator subsystem architecture (Section 12) |
| 2026-01-21 | M. Cornelison | Initial architecture document for Eclipse OBD-II project |
