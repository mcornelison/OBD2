# PRD: Eclipse OBD-II Performance Monitoring System

**Parent Backlog Item**: B-011 (OBD2 Patterns and Requirements)
**Status**: Complete

## Introduction

A Raspberry Pi-based automotive diagnostics and performance monitoring system for a 1998 Mitsubishi Eclipse. The system connects to a Bluetooth OBD-II dongle to log vehicle data, provides real-time alerts on an Adafruit 1.3" 240x240 display, performs statistical analysis on logged data, and uses AI (ollama with Gemma2/Qwen2.5) to provide performance optimization recommendations focused on air/fuel ratios and engine tuning. The system supports multiple tuning profiles, data export, and includes a calibration mode for testing.

## Goals

- Reliably connect to Bluetooth OBD-II dongle and log vehicle data to local database
- Auto-start on Raspberry Pi boot and run headless or with minimal display
- Support multiple user profiles and tuning modes for different driving scenarios
- Provide real-time performance alerts (RPM, boost pressure thresholds)
- Store 7 days of raw data with indefinite statistical summaries
- Perform post-drive statistical analysis and detect outliers
- Use AI to analyze air/fuel data and provide ranked, non-duplicate performance recommendations
- Export data in CSV and JSON formats for external analysis
- Include calibration mode for testing new sensors and parameters
- Gracefully handle power loss with battery backup monitoring
- Decode and store VIN information automatically

## User Stories

### Phase 1: Core Connectivity and Logging

#### US-001: Create configuration system
**Description:** As a developer, I need a configuration file to store all system parameters so the application is easily customizable without code changes.

**Acceptance Criteria:**
- [ ] Create `config.json` with sections: database, bluetooth, vinDecoder, display, autoStart, staticData, realtimeData, analysis, aiAnalysis, profiles, calibration
- [ ] Configuration loader validates required fields on startup
- [ ] Invalid config causes graceful failure with clear error message
- [ ] Typecheck/lint passes

#### US-002: Set up SQLite database
**Description:** As a system, I need a local SQLite database to store vehicle data with minimal footprint and maximum performance.

**Acceptance Criteria:**
- [ ] Database schema includes tables: vehicle_info, static_data, realtime_data, statistics, ai_recommendations, profiles, calibration_sessions
- [ ] realtime_data table includes timestamp, parameter_name, value, unit, profile_id columns with index on timestamp
- [ ] statistics table includes parameter_name, analysis_date, profile_id, max, min, avg, mode, std_1, std_2, outlier_min, outlier_max
- [ ] ai_recommendations table includes id, timestamp, recommendation, priority_rank, is_duplicate_of (foreign key)
- [ ] Database initialization script creates all tables if not exists
- [ ] SQLite configured with WAL mode for better concurrent performance
- [ ] Typecheck/lint passes

#### US-003: Connect to Bluetooth OBD-II dongle
**Description:** As a system, I need to connect to the Bluetooth OBD-II dongle to read vehicle data.

**Acceptance Criteria:**
- [ ] Uses public OBD library (python-OBD or obd-serial recommended)
- [ ] Reads Bluetooth MAC address from config.json
- [ ] Implements retry logic with exponential backoff (1s, 2s, 4s, 8s, 16s max)
- [ ] Logs connection attempts and failures to database
- [ ] Connection status available for display/monitoring
- [ ] Typecheck/lint passes

#### US-004: Log simple test data to database
**Description:** As a developer, I need to verify end-to-end connectivity by logging a test entry to the database.

**Acceptance Criteria:**
- [ ] Successfully reads at least one OBD-II parameter (e.g., RPM)
- [ ] Stores reading with timestamp in realtime_data table
- [ ] Verifies data persists across application restarts
- [ ] Typecheck/lint passes

#### US-005: Implement graceful shutdown
**Description:** As a system, I need to shut down gracefully to prevent database corruption and ensure clean OBD-II disconnection.

**Acceptance Criteria:**
- [ ] Handles SIGTERM and SIGINT signals
- [ ] Closes database connections properly
- [ ] Disconnects from OBD-II dongle cleanly
- [ ] Flushes any pending writes before exit
- [ ] Logs shutdown event with timestamp
- [ ] Typecheck/lint passes

### Phase 2: Auto-Start and Display

#### US-006: Implement auto-start on boot
**Description:** As a user, I want the system to start automatically when the Raspberry Pi powers on so I don't need manual intervention.

**Acceptance Criteria:**
- [ ] Creates systemd service file for auto-start
- [ ] Service starts after network.target (for potential future wifi features)
- [ ] Service restarts on failure with limit (5 attempts)
- [ ] Installation script sets up service and enables it
- [ ] Typecheck/lint passes

#### US-007: Implement display modes (headless/minimal/developer)
**Description:** As a user, I want configurable display modes so I can run headless during normal operation or with full diagnostics during development.

**Acceptance Criteria:**
- [ ] Config.json has `displayMode` setting: "headless" | "minimal" | "developer"
- [ ] Headless mode: no display output, logs only
- [ ] Minimal mode: Adafruit 1.3" display shows status screen
- [ ] Developer mode: detailed console logging of all operations
- [ ] Display mode can be changed without code modification
- [ ] Typecheck/lint passes

#### US-008: Create Adafruit 1.3" 240x240 status display
**Description:** As a user, I want to see system status on the Adafruit 1.3" display so I know the system is working without connecting a full monitor.

**Acceptance Criteria:**
- [ ] Uses Adafruit CircuitPython or similar library for ST7789 display
- [ ] Shows: OBD-II connection status, database status, current RPM, coolant temp, active alerts, current profile name
- [ ] Updates display every 1 second
- [ ] Layout optimized for 240x240 resolution (readable fonts, clear icons)
- [ ] Gracefully handles display initialization failure (continues without display)
- [ ] Typecheck/lint passes
- [ ] Verify on actual Adafruit 1.3" hardware

#### US-009: Implement shutdown command mechanism
**Description:** As a user, I need a simple way to stop the auto-run process so I can perform maintenance or updates.

**Acceptance Criteria:**
- [ ] Creates shutdown script (e.g., `shutdown.sh` or button GPIO trigger)
- [ ] Sends SIGTERM to running process
- [ ] Waits for graceful shutdown (max 30 seconds)
- [ ] Optionally powers down Raspberry Pi after application stops
- [ ] Logs shutdown reason and timestamp
- [ ] Typecheck/lint passes

### Phase 3: Data Collection and Static Data

#### US-010: Configure static and realtime data parameters
**Description:** As a user, I want to configure which OBD-II parameters to log so I can control storage usage and focus on relevant metrics.

**Acceptance Criteria:**
- [ ] Config.json has `staticData` array: list of parameters to query once (e.g., VIN, fuel type)
- [ ] Config.json has `realtimeData` array: objects with `{parameter, logData: boolean}`
- [ ] Only parameters with `logData: true` are stored in database
- [ ] All available OBD-II parameters listed in config with clear names
- [ ] Typecheck/lint passes

#### US-011: Store static data on first connection
**Description:** As a system, I need to query and store static vehicle data once per VIN to avoid repeated queries.

**Acceptance Criteria:**
- [ ] Queries static parameters from config.json on first connection
- [ ] Stores in static_data table with VIN as foreign key
- [ ] Checks if VIN exists before querying static data
- [ ] Handles unavailable parameters gracefully (marks as NULL)
- [ ] Typecheck/lint passes

#### US-012: Log realtime data based on configuration
**Description:** As a system, I need to continuously log enabled realtime parameters to the database with timestamps.

**Acceptance Criteria:**
- [ ] Queries only parameters where `logData: true` in config
- [ ] Logs each reading with precise timestamp (millisecond accuracy)
- [ ] Handles missing/unavailable parameters without crashing
- [ ] Configurable polling interval in config.json (default: 1 second)
- [ ] Associates logged data with active profile_id
- [ ] Typecheck/lint passes

### Phase 4: VIN Decoder Integration

#### US-013: Decode VIN using NHTSA API
**Description:** As a system, I need to decode the vehicle VIN to store detailed vehicle information for context and reporting.

**Acceptance Criteria:**
- [ ] Queries VIN from OBD-II on first connection
- [ ] Calls NHTSA API: `https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json`
- [ ] Stores relevant fields in vehicle_info table (Make, Model, Year, Engine, etc.)
- [ ] Only queries API for new VINs (checks database first)
- [ ] Handles API failures gracefully (retry once, then log error)
- [ ] Typecheck/lint passes

### Phase 5: Statistical Analysis

#### US-014: Create statistics calculation engine
**Description:** As a system, I need to calculate statistics on realtime data to identify trends and outliers.

**Acceptance Criteria:**
- [ ] Separate analysis thread runs on schedule from config (default: after drive ends)
- [ ] Calculates for each logged parameter: max, min, avg, mode, std_1, std_2
- [ ] Calculates outlier_min (mean - 2*std), outlier_max (mean + 2*std)
- [ ] Stores results in statistics table with analysis_date timestamp and profile_id
- [ ] Typecheck/lint passes

#### US-015: Detect drive start/end for analysis trigger
**Description:** As a system, I need to detect when the car is running vs idle to trigger post-drive analysis.

**Acceptance Criteria:**
- [ ] Monitors RPM and vehicle speed to detect "engine running" state
- [ ] Considers drive "started" when RPM > 500 for 10 consecutive seconds
- [ ] Considers drive "ended" when RPM = 0 for 60 consecutive seconds
- [ ] Triggers statistical analysis after drive end
- [ ] Configurable thresholds in config.json
- [ ] Typecheck/lint passes

#### US-016: Implement data retention policy
**Description:** As a system, I need to automatically delete old raw data to manage storage while keeping statistical summaries indefinitely.

**Acceptance Criteria:**
- [ ] Scheduled job runs daily (configurable in config)
- [ ] Deletes realtime_data rows older than 7 days (configurable)
- [ ] Keeps statistics table data indefinitely
- [ ] Logs deletion activity (rows deleted, timestamp)
- [ ] Vacuum database after deletion to reclaim space
- [ ] Typecheck/lint passes

### Phase 6: Real-Time Alerts

#### US-017: Implement threshold-based alerts
**Description:** As a driver, I want real-time alerts for critical performance thresholds so I can react to dangerous conditions.

**Acceptance Criteria:**
- [ ] Config.json has `alerts` section with threshold definitions per profile
- [ ] Monitors: RPM redline, coolant temp critical, boost pressure (if turbo), oil pressure low
- [ ] Triggers visual alert on display when threshold exceeded
- [ ] Logs alert events to database with timestamp and profile_id
- [ ] Alert cooldown period to prevent spam (configurable, default 30s)
- [ ] Typecheck/lint passes
- [ ] Verify on actual display

### Phase 7: AI Analysis Integration

#### US-018: Install and configure ollama with models
**Description:** As a system, I need ollama with Gemma2 (2b) or Qwen2.5 (3b) installed to perform AI-based analysis.

**Acceptance Criteria:**
- [ ] Installation script checks for ollama, installs if missing
- [ ] Downloads specified model from config.json (gemma2:2b or qwen2.5:3b)
- [ ] Verifies model is accessible before enabling AI analysis
- [ ] Logs ollama status and model info
- [ ] Gracefully disables AI features if ollama unavailable
- [ ] Typecheck/lint passes

#### US-019: Perform AI analysis on post-drive data
**Description:** As a system, I need to feed drive data to the AI model to get performance optimization recommendations focused on air/fuel ratios.

**Acceptance Criteria:**
- [ ] Triggers after post-drive statistical analysis completes
- [ ] Prepares data window: last drive's air/fuel ratio, RPM, throttle position, MAF, etc.
- [ ] Formats data as prompt for ollama model
- [ ] Prompt asks model to identify optimization opportunities for performance
- [ ] Saves model response to ai_recommendations table with timestamp and profile_id
- [ ] Limits analysis to prevent excessive processing (max once per drive)
- [ ] Typecheck/lint passes

#### US-020: Create AI recommendation prompt template
**Description:** As a developer, I need an effective prompt template to get useful performance recommendations from the AI model.

**Acceptance Criteria:**
- [ ] Prompt includes context: 1998 Mitsubishi Eclipse, performance optimization goal
- [ ] Includes relevant metrics: air/fuel ratio trends, RPM ranges, throttle response
- [ ] Asks specifically about air/fuel tuning opportunities
- [ ] Requests actionable recommendations
- [ ] Prompt template stored in config or separate file
- [ ] Typecheck/lint passes

#### US-021: Rank and deduplicate AI recommendations
**Description:** As a user, I want AI recommendations prioritized by importance and filtered for duplicates so I can focus on unique, high-value insights.

**Acceptance Criteria:**
- [ ] After AI generates recommendation, system assigns priority_rank (1-5, 1=highest)
- [ ] Ranking based on keywords: safety issues=1, performance gains=2, efficiency=3, minor tweaks=4, informational=5
- [ ] Before saving, checks last 30 days of recommendations for semantic similarity
- [ ] If similar recommendation exists (>70% text similarity or same keywords), marks as duplicate with `is_duplicate_of` foreign key
- [ ] Display shows only non-duplicate recommendations sorted by priority_rank
- [ ] Typecheck/lint passes

### Phase 8: Battery and Power Management

#### US-022: Monitor battery backup voltage
**Description:** As a system, I need to monitor the battery backup voltage to detect low power conditions and shut down gracefully.

**Acceptance Criteria:**
- [ ] Reads battery voltage via GPIO ADC or I2C power monitor
- [ ] Config.json has `batteryMonitoring` section with voltage thresholds
- [ ] Warning threshold (e.g., 11.5V): logs warning, displays alert
- [ ] Critical threshold (e.g., 11.0V): initiates graceful shutdown
- [ ] Voltage logged to database every 60 seconds
- [ ] Typecheck/lint passes

#### US-023: Detect 12V adapter disconnect
**Description:** As a system, I need to detect when primary 12V power is lost to switch to battery backup mode.

**Acceptance Criteria:**
- [ ] Monitors primary power status via GPIO or power management HAT
- [ ] Logs power transition events (AC→Battery, Battery→AC)
- [ ] Displays power source on status screen
- [ ] Reduces power consumption when on battery (lower polling rate, dim display)
- [ ] Typecheck/lint passes
- [ ] Verify on actual hardware

### Phase 9: Profiles and Tuning Modes

#### US-024: Create profile management system
**Description:** As a user, I want multiple profiles/tuning modes so I can track data separately for different driving scenarios (e.g., daily driving vs track day).

**Acceptance Criteria:**
- [ ] Config.json has `profiles` array with objects: `{id, name, description, alertThresholds, pollingInterval}`
- [ ] Database has profiles table: id, name, description, created_at, alert_config_json
- [ ] Default profile "Daily" created on first run
- [ ] Each profile has independent alert thresholds and logging settings
- [ ] Typecheck/lint passes

#### US-025: Switch profiles via display or config
**Description:** As a user, I want to easily switch between profiles so I can adapt monitoring to current driving conditions.

**Acceptance Criteria:**
- [ ] Config.json has `activeProfile` setting (profile name or id)
- [ ] Profile switch takes effect on next drive start (not mid-drive)
- [ ] Display shows current active profile name
- [ ] Profile change logged to database with timestamp
- [ ] All subsequent data tagged with new profile_id
- [ ] Typecheck/lint passes
- [ ] Verify on actual display

#### US-026: Profile-specific statistics and analysis
**Description:** As a system, I need to calculate statistics separately per profile so comparisons between tuning modes are meaningful.

**Acceptance Criteria:**
- [ ] Statistics calculations filtered by profile_id
- [ ] Each profile maintains separate statistical history
- [ ] AI analysis considers only data from current profile
- [ ] Reports can filter/compare across profiles
- [ ] Typecheck/lint passes

### Phase 10: Data Export

#### US-027: Export realtime data to CSV
**Description:** As a user, I want to export logged data to CSV format so I can analyze it in Excel or other tools.

**Acceptance Criteria:**
- [ ] Export script/command accepts parameters: date range, profile_id, parameters to include
- [ ] Generates CSV with columns: timestamp, parameter_name, value, unit
- [ ] CSV includes header row with column names
- [ ] Saves to configurable export directory (default: `exports/`)
- [ ] Filename includes date range: `obd_export_YYYY-MM-DD_to_YYYY-MM-DD.csv`
- [ ] Typecheck/lint passes

#### US-028: Export data to JSON
**Description:** As a developer, I want to export data in JSON format for programmatic analysis and integration with other tools.

**Acceptance Criteria:**
- [ ] Export script accepts same parameters as CSV export
- [ ] Generates JSON with structure: `{metadata: {...}, data: [{timestamp, parameter, value, unit}, ...]}`
- [ ] Metadata includes: export_date, profile, date_range, record_count
- [ ] Saves to configurable export directory (default: `exports/`)
- [ ] Filename includes date range: `obd_export_YYYY-MM-DD_to_YYYY-MM-DD.json`
- [ ] Typecheck/lint passes

#### US-029: Export statistics and AI recommendations
**Description:** As a user, I want to export summary reports including statistics and AI recommendations so I can review insights offline.

**Acceptance Criteria:**
- [ ] Export generates combined report in CSV and JSON formats
- [ ] Includes: statistics summary (all parameters), AI recommendations with rankings, alert history
- [ ] Groups by profile if multiple profiles selected
- [ ] Filename: `obd_summary_YYYY-MM-DD.csv` or `.json`
- [ ] Typecheck/lint passes

### Phase 11: Calibration Mode

#### US-030: Implement calibration mode
**Description:** As a developer/tuner, I need a calibration mode to test new sensors, verify OBD-II parameters, and validate system accuracy.

**Acceptance Criteria:**
- [ ] Config.json has `calibrationMode: boolean` setting
- [ ] When enabled, system logs all available OBD-II parameters regardless of config
- [ ] Creates separate calibration_sessions table with session_id, start_time, end_time, notes
- [ ] Calibration data linked to session_id (not mixed with normal data)
- [ ] Display shows "CALIBRATION MODE" indicator prominently
- [ ] Typecheck/lint passes
- [ ] Verify on actual display

#### US-031: Calibration session management
**Description:** As a user, I need to manage calibration sessions so I can organize test runs and compare results.

**Acceptance Criteria:**
- [ ] Start calibration: Creates new session with timestamp and optional notes
- [ ] Stop calibration: Marks session as ended, calculates duration
- [ ] List sessions: Shows all past calibration runs with date, duration, parameter count
- [ ] Export session: Exports specific calibration session data to CSV/JSON
- [ ] Delete session: Removes session and all associated data
- [ ] Typecheck/lint passes

#### US-032: Calibration comparison tool
**Description:** As a user, I want to compare calibration sessions to validate sensor accuracy and identify parameter drift.

**Acceptance Criteria:**
- [ ] Comparison tool accepts 2+ session IDs
- [ ] Generates side-by-side statistics for each parameter across sessions
- [ ] Highlights significant differences (>10% variance)
- [ ] Exports comparison report to CSV/JSON
- [ ] Typecheck/lint passes

## Functional Requirements

**Core Connectivity:**
- FR-1: System must connect to Bluetooth OBD-II dongle using MAC address from config.json
- FR-2: System must retry failed connections with exponential backoff (1s, 2s, 4s, 8s, 16s)
- FR-3: System must store realtime data in SQLite database with millisecond-precision timestamps
- FR-4: System must handle SIGTERM/SIGINT for graceful shutdown

**Configuration:**
- FR-5: All parameters (database path, Bluetooth MAC, thresholds, etc.) must be in config.json
- FR-6: Config must define staticData (one-time queries) and realtimeData (continuous logging with enable flags)
- FR-7: Invalid config must cause startup failure with clear error message
- FR-8: Config must support multiple profiles with independent settings

**Data Storage:**
- FR-9: Raw realtime_data must be retained for 7 days (configurable)
- FR-10: Statistical summaries must be retained indefinitely
- FR-11: Database must include tables: vehicle_info, static_data, realtime_data, statistics, ai_recommendations, profiles, calibration_sessions
- FR-12: All logged data must be tagged with profile_id
- FR-13: SQLite must use WAL mode for concurrent performance

**Display:**
- FR-14: System must support three display modes: headless, minimal (Adafruit 1.3" 240x240), developer
- FR-15: Minimal display must show: connection status, RPM, coolant temp, active alerts, current profile
- FR-16: Display must update every 1 second
- FR-17: Calibration mode must show prominent "CALIBRATION MODE" indicator

**Auto-Start:**
- FR-18: System must auto-start via systemd service on Raspberry Pi boot
- FR-19: Service must restart on failure (max 5 attempts)
- FR-20: Shutdown script or GPIO button must trigger graceful shutdown

**VIN Decoder:**
- FR-21: System must query VIN from OBD-II on first connection
- FR-22: System must decode VIN via NHTSA API and store results
- FR-23: System must only query API for new VINs (check database first)

**Analysis:**
- FR-24: Statistical analysis must calculate: max, min, avg, mode, std_1, std_2, outlier_min, outlier_max
- FR-25: Analysis must trigger after drive end (RPM = 0 for 60s)
- FR-26: Analysis results must be stored in statistics table with profile_id
- FR-27: Statistics must be calculated separately per profile

**Alerts:**
- FR-28: System must monitor thresholds: RPM redline, coolant temp critical, boost pressure (if equipped)
- FR-29: Alert thresholds must be configurable per profile
- FR-30: Alerts must display on screen and log to database
- FR-31: Alert cooldown period (default 30s) must prevent spam

**AI Analysis:**
- FR-32: System must integrate with ollama (Gemma2:2b or Qwen2.5:3b from config)
- FR-33: AI analysis must run post-drive on air/fuel ratio data
- FR-34: AI recommendations must be ranked by priority (1-5 scale)
- FR-35: System must detect and mark duplicate recommendations (>70% similarity to last 30 days)
- FR-36: AI recommendations must be stored in ai_recommendations table with profile_id
- FR-37: System must gracefully disable AI features if ollama unavailable

**Battery Monitoring:**
- FR-38: System must monitor battery backup voltage every 60s
- FR-39: System must log warning at low voltage threshold (default 11.5V)
- FR-40: System must initiate graceful shutdown at critical threshold (default 11.0V)
- FR-41: System must detect and log primary power (12V adapter) connection/disconnection

**Profiles:**
- FR-42: System must support multiple named profiles (e.g., "Daily", "Track", "Dyno")
- FR-43: Each profile must have independent alert thresholds and polling intervals
- FR-44: Profile switching must take effect at next drive start (not mid-drive)
- FR-45: All data must be tagged with active profile_id

**Data Export:**
- FR-46: System must export realtime data to CSV format with date range filter
- FR-47: System must export realtime data to JSON format with metadata
- FR-48: System must export statistics and AI recommendations as summary reports
- FR-49: Export filenames must include date range for organization

**Calibration Mode:**
- FR-50: Calibration mode must log all available OBD-II parameters
- FR-51: Calibration data must be stored in separate sessions, not mixed with normal data
- FR-52: System must support session management (start, stop, list, export, delete)
- FR-53: Comparison tool must highlight significant variances (>10%) between sessions

## Non-Goals (Out of Scope)

- No cloud connectivity or remote monitoring (local only)
- No mobile app or web interface in initial version
- No CAN bus direct connection (OBD-II only)
- No video recording or camera integration
- No GPS tracking or location logging
- No real-time tuning adjustments (read-only, recommendations only)
- No custom gauge cluster replacement (supplementary system only)
- No boost controller integration in Phase 1 (planned for future)

## Design Considerations

**Hardware:**
- Raspberry Pi (3B+ or 4 recommended for performance, 4GB RAM for AI models)
- Adafruit 1.3" 240x240 Color TFT display (ST7789 driver)
- Bluetooth OBD-II dongle (ELM327-compatible)
- 12V to 5V adapter with battery backup (e.g., UPS HAT or similar)
- Voltage monitoring via ADC or I2C power monitor

**Display Layout (240x240):**
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
│ ⚠️ No Alerts        │
└─────────────────────┘
```

**Profile Examples:**
- **Daily**: Conservative thresholds, 1Hz polling, basic monitoring
- **Track**: Aggressive thresholds, 2-5Hz polling, performance focus
- **Dyno**: Maximum logging frequency, all parameters enabled
- **Calibration**: All parameters, high-frequency logging, test mode

**Recommended Tech Stack:**
- **Language:** Python 3.9+ (best OBD library support, ollama integration)
- **OBD Library:** python-OBD or obd-serial
- **Database:** SQLite 3 with WAL mode
- **Display:** Adafruit CircuitPython (ST7789)
- **AI:** ollama with REST API
- **Auto-start:** systemd service

## Technical Considerations

**Performance:**
- SQLite with WAL mode for better concurrent read/write performance
- Index on realtime_data.timestamp and realtime_data.profile_id for fast queries
- Batch inserts for realtime data (every 5-10 readings) to reduce I/O
- Consider separate thread for database writes to avoid blocking OBD-II polling
- Profile switching logic must not interrupt active drive session

**OBD-II Library:**
- ELM327 protocol standard for 1998 vehicle
- May need to handle incomplete parameter support (1998 pre-dates full OBD-II spec)
- Some parameters (e.g., boost pressure) may require custom PIDs when turbo added
- Calibration mode should attempt to read all PIDs to discover available parameters

**Power Management:**
- Battery backup should provide 2-5 minutes runtime for graceful shutdown
- Monitor Pi temperature, throttle analysis if overheating
- Consider write caching for SD card longevity
- UPS HAT with I2C communication preferred for voltage monitoring

**AI/ML Considerations:**
- Gemma2:2b preferred for Pi 4, Qwen2.5:3b if 4GB+ RAM available
- Limit AI analysis frequency (once per drive) to prevent thermal issues
- Consider deferring AI analysis to cooldown periods
- Recommendation deduplication prevents user fatigue from repeated suggestions
- Priority ranking helps users focus on high-impact changes first

**Data Retention:**
- 7 days of raw data at 1Hz polling ≈ 600K rows per parameter
- With multiple profiles and calibration sessions, database size management critical
- Vacuum database weekly to reclaim space
- Export and archive old calibration sessions periodically

**Export Functionality:**
- CSV format for Excel/spreadsheet analysis
- JSON format for programmatic access (Python, R, MATLAB)
- Consider compression for large exports (gzip)
- Metadata in JSON exports aids reproducibility

## Success Metrics

- System auto-starts successfully on 100% of boots
- OBD-II connection success rate > 95% within 30 seconds of engine start
- Zero database corruptions over 1 month continuous operation
- Display response time < 1 second for all screens
- Statistical analysis completes within 60 seconds of drive end
- AI analysis completes within 5 minutes of drive end
- AI recommendation deduplication reduces redundant suggestions by >80%
- Battery monitoring detects low voltage before unexpected shutdown
- Data retention policy maintains < 1GB database size indefinitely (excluding calibration)
- Profile switching works seamlessly without data loss
- CSV export completes within 10 seconds for 7 days of data
- Calibration mode captures 100% of available OBD-II parameters

## Open Questions Resolved

- ✅ **Multiple profiles/tuning modes**: YES - Phase 9
- ✅ **Data export (CSV/JSON)**: YES - Phase 10
- ✅ **AI recommendation ranking and deduplication**: YES - US-021
- ✅ **Boost controller support**: Not in Phase 1, plan for future expansion
- ✅ **Calibration mode**: YES - Phase 11

---

## Implementation Phases

**Phase 1 (Core - 5 user stories):** Connectivity, database, basic logging, graceful shutdown
**Phase 2 (Auto-start - 4 user stories):** Systemd service, display modes, Adafruit display, shutdown mechanism
**Phase 3 (Data - 3 user stories):** Static/realtime data configuration and storage
**Phase 4 (VIN - 1 user story):** NHTSA API integration
**Phase 5 (Analysis - 3 user stories):** Statistical engine, drive detection, data retention
**Phase 6 (Alerts - 1 user story):** Threshold monitoring and display
**Phase 7 (AI - 3 user stories):** Ollama integration, post-drive analysis, prompt engineering, ranking/deduplication
**Phase 8 (Power - 2 user stories):** Battery monitoring, power state detection
**Phase 9 (Profiles - 3 user stories):** Profile management, switching, profile-specific analysis
**Phase 10 (Export - 3 user stories):** CSV export, JSON export, summary reports
**Phase 11 (Calibration - 3 user stories):** Calibration mode, session management, comparison tool

**Total User Stories: 32**

---

**Next Steps:**
1. ✅ PRD saved as `specs/tasks/prd-eclipse-obd-ii.md`
2. Run `/ralph` to convert to `stories.json` for autonomous execution
3. Execute with `ralph/ralph.sh <iterations>` for incremental implementation
4. Prioritize Phase 1 (Core) and Phase 2 (Auto-start) for MVP functionality
