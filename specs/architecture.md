# System Architecture

## Overview

This document describes the system architecture, technology decisions, and design patterns for the Eclipse OBD-II Performance Monitoring System.

**Last Updated**: 2026-01-22
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
│  │   SQLite     │  │  Adafruit    │  │   Logs       │  │   Exports   │ │
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
| Display | CircuitPython | 8.x | Adafruit ST7789 driver |
| AI | ollama | latest | Local LLM inference |

### External Dependencies

| System | Purpose | Connection Method |
|--------|---------|-------------------|
| OBD-II Dongle | Vehicle data acquisition | Bluetooth (ELM327 protocol) |
| NHTSA API | VIN decoding | HTTPS REST API |
| ollama | AI recommendations | Local HTTP (port 11434) |

### Hardware

| Component | Platform | Notes |
|-----------|----------|-------|
| Processor | Raspberry Pi 3B+/4 | 4GB RAM recommended for AI |
| Display | Adafruit 1.3" TFT | ST7789, 240x240 resolution |
| Storage | SQLite (WAL mode) | Local file database |
| Power | 12V to 5V adapter | UPS HAT for battery backup |
| Monitoring | ADC/I2C | Battery voltage monitoring |

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

### Schema Overview

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
└─────────────────────┘                │
                                       │
┌─────────────────────┐     ┌──────────▼──────────┐
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
```

### Data Retention

- **realtime_data**: 7 days (configurable)
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

### Display Layout (240x240)

```
┌─────────────────────┐
│ Eclipse OBD-II      │
│ ▲ Connected   [D]   │ (status, profile initial)
├─────────────────────┤
│ RPM:    2500        │
│ Temp:   185°F       │
│ Speed:  45 mph      │
│ A/F:    14.7:1      │
├─────────────────────┤
│ Profile: Daily      │
│ No Alerts           │
└─────────────────────┘
```

### Display Modes

| Mode | Behavior |
|------|----------|
| headless | No display output, logs only |
| minimal | Adafruit display shows status screen |
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

## 13. Future Considerations

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

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-22 | Knowledge Update | Updated Core Services section with domain subpackage structure and implemented modules |
| 2026-01-22 | Knowledge Update | Added simulator subsystem architecture (Section 12) |
| 2026-01-21 | M. Cornelison | Initial architecture document for Eclipse OBD-II project |
