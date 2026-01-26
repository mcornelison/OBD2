# PRD: Application Orchestration and Raspberry Pi Deployment

## Introduction

The Eclipse OBD-II Performance Monitoring System has all individual components implemented and tested (129 Python modules, 324 passing tests), but lacks the main application orchestration layer that wires everything together into a running system. This PRD covers the work needed to create the main application loop, integrate all components, and prepare the system for deployment on a Raspberry Pi 5.

The `main.py` file currently has a placeholder `runWorkflow()` function with TODO comments. This work will implement the actual orchestration logic that initializes, runs, and gracefully shuts down all system components.

## Goals

- Create a fully functional main application loop that orchestrates all components
- Support both real OBD-II hardware and simulator mode via `--simulate` flag
- Implement graceful startup and shutdown sequences
- Enable automatic service deployment via systemd on Raspberry Pi
- Provide clear operational logging and error handling
- Support all configured features: data logging, drive detection, alerts, statistics, and AI analysis
- Create deployment documentation and verification scripts for Raspberry Pi

## Non-Goals

- Web dashboard or remote monitoring (future enhancement)
- Mobile app integration (future enhancement)
- Multi-vehicle support (single vehicle focus)
- Custom PID support (standard OBD-II PIDs only for now)

## Dependencies

All required components already exist and are tested:

| Component | Module | Status |
|-----------|--------|--------|
| Database | `src/obd/database.py` | ✅ Complete |
| OBD Connection | `src/obd/obd_connection.py` | ✅ Complete |
| Simulated Connection | `src/obd/simulator/` | ✅ Complete |
| Data Logger | `src/obd/data/logger.py` | ✅ Complete |
| Realtime Logger | `src/obd/data/realtime.py` | ✅ Complete |
| Drive Detector | `src/obd/drive/detector.py` | ✅ Complete |
| Alert Manager | `src/obd/alert/manager.py` | ✅ Complete |
| Display Manager | `src/obd/display/manager.py` | ✅ Complete |
| Statistics Engine | `src/obd/analysis/engine.py` | ✅ Complete |
| Profile Manager | `src/obd/profile/manager.py` | ✅ Complete |
| VIN Decoder | `src/obd/vehicle/vin_decoder.py` | ✅ Complete |
| Config Loader | `src/obd/obd_config_loader.py` | ✅ Complete |

---

## User Stories

### US-OSC-001: Implement Application Orchestrator Class

**Description:** As a developer, I need a central orchestrator class that manages the lifecycle of all system components so they work together as a cohesive application.

**Acceptance Criteria:**
- [ ] Create `ApplicationOrchestrator` class in `src/obd/orchestrator.py`
- [ ] Constructor accepts `config: dict` and `simulate: bool` parameters
- [ ] Maintains references to all managed components:
  - `database: ObdDatabase`
  - `connection: ObdConnection | SimulatedObdConnection`
  - `dataLogger: RealtimeDataLogger`
  - `driveDetector: DriveDetector`
  - `alertManager: AlertManager`
  - `displayManager: DisplayManager`
  - `statisticsEngine: StatisticsEngine`
  - `profileManager: ProfileManager`
  - `vinDecoder: VinDecoder` (optional)
- [ ] Provides `start()` method to initialize and start all components
- [ ] Provides `stop()` method to gracefully shutdown all components
- [ ] Provides `isRunning()` method to check application state
- [ ] Provides `getStatus()` method returning current state of all components
- [ ] All component initialization failures logged with clear error messages
- [ ] Components initialized in correct dependency order
- [ ] Typecheck passes with `mypy src/obd/orchestrator.py`
- [ ] Lint passes with `ruff check src/obd/orchestrator.py`

---

### US-OSC-002: Implement Startup Sequence

**Description:** As a user, I want the application to start up in a predictable order so components that depend on each other are ready when needed.

**Acceptance Criteria:**
- [ ] Startup sequence follows this order:
  1. Load and validate configuration
  2. Initialize database (create tables if needed)
  3. Initialize profile manager and ensure default profile exists
  4. Create OBD connection (real or simulated based on flag)
  5. Connect to OBD-II adapter (with retry logic)
  6. Query static data on first connection (VIN, fuel type, etc.)
  7. Decode VIN via NHTSA API (if enabled and not cached)
  8. Initialize display manager
  9. Initialize drive detector
  10. Initialize alert manager
  11. Initialize statistics engine
  12. Start realtime data logger
  13. Display "Ready" status
- [ ] Each step logged with INFO level: "Starting [component]..."
- [ ] Each successful step logged: "[Component] started successfully"
- [ ] Failed steps logged with ERROR level and clear message
- [ ] Connection retry uses exponential backoff from config
- [ ] Startup can be aborted with Ctrl+C at any point
- [ ] Partial startup state cleaned up on failure
- [ ] Total startup time logged at completion
- [ ] Typecheck/lint passes

---

### US-OSC-003: Implement Shutdown Sequence

**Description:** As a user, I want the application to shut down gracefully so no data is lost and hardware is left in a safe state.

**Acceptance Criteria:**
- [ ] Shutdown sequence follows this order (reverse of startup):
  1. Log "Shutdown requested..."
  2. Stop realtime data logger (finish current cycle)
  3. Stop alert manager
  4. Stop drive detector
  5. Stop statistics engine (wait for any running analysis)
  6. Display "Shutting down..." on display
  7. Stop display manager
  8. Disconnect OBD-II connection
  9. Backup database (if configured)
  10. Close database connection
  11. Log "Shutdown complete"
- [ ] Each step has configurable timeout (default 5 seconds)
- [ ] Components that don't stop in time are force-stopped with warning
- [ ] Double Ctrl+C forces immediate exit (skip graceful shutdown)
- [ ] SIGTERM handled same as Ctrl+C (SIGINT)
- [ ] No data loss for completed logging cycles
- [ ] Exit code 0 for clean shutdown, non-zero for forced/error
- [ ] Typecheck/lint passes

---

### US-OSC-004: Implement Signal Handlers

**Description:** As a system administrator, I need the application to respond correctly to system signals so it can be managed by systemd and manual intervention.

**Acceptance Criteria:**
- [ ] SIGINT (Ctrl+C) triggers graceful shutdown
- [ ] SIGTERM triggers graceful shutdown (for systemd stop)
- [ ] Second SIGINT/SIGTERM forces immediate exit
- [ ] Signal handlers registered in `main()` before starting orchestrator
- [ ] Original signal handlers restored on shutdown
- [ ] Signal received logged: "Received signal [SIGNAME], initiating shutdown"
- [ ] Works correctly on both Windows and Linux
- [ ] Typecheck/lint passes

---

### US-OSC-005: Implement Main Application Loop

**Description:** As a user, I want the application to run continuously, monitoring my vehicle until I stop it.

**Acceptance Criteria:**
- [ ] Main loop in `runWorkflow()` replaced with actual implementation
- [ ] Loop runs until shutdown signal received
- [ ] Loop handles component callbacks:
  - Drive start → log event, update display
  - Drive end → trigger statistics analysis
  - Alert triggered → log alert, update display
  - Analysis complete → log results
  - Connection lost → attempt reconnection
- [ ] Loop includes health check every 60 seconds (configurable)
- [ ] Health check logs: connection status, data rate, error count
- [ ] Loop catches and logs unexpected exceptions without crashing
- [ ] Memory-efficient (no unbounded growth over hours of running)
- [ ] Typecheck/lint passes

---

### US-OSC-006: Wire Up Realtime Data Logging

**Description:** As a user, I want my vehicle's sensor data continuously logged to the database so I can analyze it later.

**Acceptance Criteria:**
- [ ] `RealtimeDataLogger` created from config in orchestrator
- [ ] Logger connected to OBD connection for data queries
- [ ] Logger connected to database for storing readings
- [ ] Logger uses profile-specific polling interval
- [ ] Only parameters with `logData: true` are logged
- [ ] Parameters with `displayOnDashboard: true` sent to display
- [ ] Logger `onReading` callback updates display with latest values
- [ ] Logger `onError` callback logs warning and continues
- [ ] Logger `onCycleComplete` callback available for metrics
- [ ] Data logging rate logged every 5 minutes (records/minute)
- [ ] Typecheck/lint passes

---

### US-OSC-007: Wire Up Drive Detection

**Description:** As a user, I want the system to automatically detect when I start and stop driving so it can trigger post-drive analysis.

**Acceptance Criteria:**
- [ ] `DriveDetector` created from config in orchestrator
- [ ] Detector receives RPM values from realtime logger
- [ ] Detector `onDriveStart` callback:
  - Logs "Drive started at [timestamp]"
  - Updates display to show "Driving" status
  - Stores drive start time for session tracking
- [ ] Detector `onDriveEnd` callback:
  - Logs "Drive ended at [timestamp], duration: [X] minutes"
  - Triggers statistics analysis for the drive period
  - Triggers AI analysis if enabled
  - Updates display to show "Drive Complete" status
- [ ] Drive sessions logged to database for history
- [ ] Detector state survives brief RPM dropouts (configurable debounce)
- [ ] Typecheck/lint passes

---

### US-OSC-008: Wire Up Alert System

**Description:** As a user, I want to be alerted when sensor values exceed safe thresholds so I can take action before damage occurs.

**Acceptance Criteria:**
- [ ] `AlertManager` created from config in orchestrator
- [ ] Manager receives all realtime values from logger
- [ ] Manager uses active profile's alert thresholds
- [ ] Alert `onAlert` callback:
  - Logs alert at WARNING level
  - Sends alert to display manager
  - Records alert in database
- [ ] Alerts respect cooldown period (no repeated alerts for same condition)
- [ ] Alert priorities displayed correctly (critical > warning > info)
- [ ] Visual alerts shown on display if enabled
- [ ] Alert history queryable from database
- [ ] Typecheck/lint passes

---

### US-OSC-009: Wire Up Statistics Engine

**Description:** As a user, I want automatic statistical analysis after each drive so I can see trends and anomalies in my vehicle's performance.

**Acceptance Criteria:**
- [ ] `StatisticsEngine` created from config in orchestrator
- [ ] Engine connected to database for data retrieval and storage
- [ ] Engine `scheduleAnalysis()` called on drive end
- [ ] Engine calculates configured statistics: max, min, avg, mode, std_1, std_2, outlier bounds
- [ ] Engine `onComplete` callback:
  - Logs "Analysis complete: [X] parameters analyzed"
  - Notifies display of completion
- [ ] Engine `onError` callback logs error and continues operation
- [ ] Analysis runs in background thread (non-blocking)
- [ ] Analysis results stored with profile_id association
- [ ] Typecheck/lint passes

---

### US-OSC-010: Wire Up Display Manager

**Description:** As a user, I want to see my vehicle's current status on the connected display so I can monitor while driving.

**Acceptance Criteria:**
- [ ] `DisplayManager` created from config in orchestrator
- [ ] Display mode selected from config: headless, minimal, developer
- [ ] Display initialized on startup with welcome screen
- [ ] Display receives status updates:
  - Connection status (connected/disconnected/connecting)
  - Current RPM, speed, coolant temp (dashboard parameters)
  - Active profile name
  - Drive status (stopped/driving)
  - Alert messages (with priority coloring)
- [ ] Display refreshes at configured rate (default 1Hz)
- [ ] Display shows "Shutting down..." during shutdown
- [ ] Graceful fallback to headless if display hardware unavailable
- [ ] Typecheck/lint passes

---

### US-OSC-011: Wire Up Profile System

**Description:** As a user, I want my selected driving profile to control alert thresholds and polling rates so I can customize behavior for different driving situations.

**Acceptance Criteria:**
- [ ] `ProfileManager` created from config in orchestrator
- [ ] Profiles from config synced to database on startup
- [ ] Active profile loaded from config
- [ ] Profile change updates:
  - Alert manager thresholds
  - Data logger polling interval
  - Display shows new profile name
- [ ] Profile switch queued if driving (activated on next drive start)
- [ ] Profile changes logged: "Profile changed from [A] to [B]"
- [ ] Typecheck/lint passes

---

### US-OSC-012: Implement Connection Recovery

**Description:** As a user, I want the system to automatically reconnect if the OBD-II connection is lost so I don't have to manually restart.

**Acceptance Criteria:**
- [ ] Connection loss detected within 5 seconds
- [ ] Automatic reconnection attempted with exponential backoff
- [ ] Backoff delays from config: [1, 2, 4, 8, 16] seconds
- [ ] Maximum retry attempts from config (default 5)
- [ ] During reconnection:
  - Data logging paused (no errors logged for missing data)
  - Display shows "Reconnecting..." status
  - Alerts paused
- [ ] On successful reconnection:
  - Data logging resumes
  - Display shows "Connected" status
  - Event logged: "Connection restored after [X] seconds"
- [ ] On max retries exceeded:
  - Error logged
  - Display shows "Connection Failed"
  - System continues running (allows manual reconnect trigger)
- [ ] Typecheck/lint passes

---

### US-OSC-013: Implement First-Connection VIN Decode

**Description:** As a user, I want my vehicle's information automatically decoded from its VIN on first connection so I don't have to enter it manually.

**Acceptance Criteria:**
- [ ] On first successful connection, check if VIN exists in database
- [ ] If VIN not cached, query VIN from vehicle
- [ ] If VIN valid and vinDecoder enabled, call NHTSA API
- [ ] Decoded vehicle info (make, model, year, engine) stored in database
- [ ] Vehicle info displayed on startup: "Connected to [Year] [Make] [Model]"
- [ ] API timeout handled gracefully (continue without decode)
- [ ] API errors logged but don't block operation
- [ ] Subsequent connections skip decode (use cached data)
- [ ] Typecheck/lint passes

---

### US-OSC-014: Update main.py with Orchestrator Integration

**Description:** As a developer, I need main.py to use the new orchestrator so the application actually runs.

**Acceptance Criteria:**
- [ ] `runWorkflow()` function creates `ApplicationOrchestrator` instance
- [ ] Orchestrator receives parsed config and simulate flag
- [ ] `orchestrator.start()` called to begin operation
- [ ] Main thread waits for shutdown signal
- [ ] `orchestrator.stop()` called on shutdown
- [ ] Exit code reflects orchestrator status
- [ ] All existing CLI flags continue to work
- [ ] `--dry-run` validates config without starting orchestrator
- [ ] Typecheck/lint passes

---

### US-OSC-015: Create Integration Test Suite

**Description:** As a developer, I need integration tests that verify the orchestrator works correctly with all components in simulator mode.

**Acceptance Criteria:**
- [ ] Create `tests/test_orchestrator_integration.py`
- [ ] Test: Orchestrator starts successfully in simulator mode
- [ ] Test: Orchestrator stops gracefully on signal
- [ ] Test: Data is logged to database during simulated drive
- [ ] Test: Drive detection triggers on simulated RPM changes
- [ ] Test: Statistics calculated after simulated drive ends
- [ ] Test: Alerts trigger on simulated threshold violations
- [ ] Test: Connection recovery works on simulated disconnect
- [ ] Test: Profile switch works correctly
- [ ] Tests use temporary database (not production)
- [ ] Tests complete within 60 seconds total
- [ ] All tests pass: `pytest tests/test_orchestrator_integration.py -v`

---

### US-OSC-016: Create systemd Service File

**Description:** As a system administrator, I need a systemd service configuration so the application starts automatically on Raspberry Pi boot.

**Acceptance Criteria:**
- [ ] Create `deploy/eclipse-obd.service` file
- [ ] Service type: simple
- [ ] Working directory configurable
- [ ] Virtual environment path configurable
- [ ] Restart on failure with 10 second delay
- [ ] Logging to file (stdout and stderr)
- [ ] After: network.target, bluetooth.target
- [ ] User: configurable (default: pi)
- [ ] Create `deploy/install-service.sh` script
- [ ] Create `deploy/uninstall-service.sh` script
- [ ] Document installation steps in `docs/deployment-checklist.md`

---

### US-OSC-017: Create Production Environment Template

**Description:** As a system administrator, I need a production environment configuration template for Raspberry Pi deployment.

**Acceptance Criteria:**
- [ ] Create `.env.production.example` file
- [ ] Include all required environment variables with comments
- [ ] Include placeholders for secrets (Bluetooth MAC, etc.)
- [ ] Document how to find OBD-II dongle MAC address
- [ ] Document display mode options
- [ ] Document log file location
- [ ] Include recommended production values

---

### US-OSC-018: Create Hardware Verification Script

**Description:** As a system administrator, I need a script to verify all hardware is working on the Raspberry Pi before running the full application.

**Acceptance Criteria:**
- [ ] Create `scripts/verify_hardware.py`
- [ ] Check: Python version >= 3.11
- [ ] Check: SQLite version and connectivity
- [ ] Check: Bluetooth adapter present and enabled
- [ ] Check: OBD-II dongle discoverable (optional MAC param)
- [ ] Check: Display hardware (if configured)
- [ ] Check: GPIO access (if power monitoring enabled)
- [ ] Check: I2C access (if voltage monitoring enabled)
- [ ] Print clear PASS/FAIL for each check
- [ ] Exit code 0 if all critical checks pass
- [ ] Document usage in deployment checklist

---

### US-OSC-019: Create Bluetooth Pairing Documentation

**Description:** As a user, I need clear instructions for pairing my OBD-II Bluetooth dongle with the Raspberry Pi.

**Acceptance Criteria:**
- [ ] Create `docs/bluetooth-setup.md`
- [ ] Document: How to find dongle MAC address
- [ ] Document: bluetoothctl pairing steps
- [ ] Document: Trust device for auto-reconnect
- [ ] Document: Verify pairing with rfcomm or python-OBD
- [ ] Document: Common troubleshooting steps
- [ ] Include example commands with expected output
- [ ] Document: How to set MAC in .env file

---

### US-OSC-020: End-to-End Simulator Test

**Description:** As a developer, I need to verify the complete application works end-to-end in simulator mode before deploying to hardware.

**Acceptance Criteria:**
- [ ] Application starts with `python src/main.py --simulate`
- [ ] Database created and initialized
- [ ] Simulated connection established
- [ ] Data logging visible in logs
- [ ] Drive detection works (simulate RPM > 500 for 10+ seconds)
- [ ] Statistics generated after simulated drive
- [ ] Graceful shutdown on Ctrl+C
- [ ] No errors in logs during 5-minute test run
- [ ] Database contains expected records after run
- [ ] Document test procedure in `docs/testing.md`

---

## Technical Notes

### Component Initialization Order

```
1. Database (no dependencies)
2. ProfileManager (depends on Database)
3. OBD Connection (no dependencies)
4. VinDecoder (depends on Connection, Database)
5. DisplayManager (no dependencies)
6. DriveDetector (depends on Database, optionally StatisticsEngine)
7. AlertManager (depends on Database, DisplayManager)
8. StatisticsEngine (depends on Database)
9. RealtimeDataLogger (depends on Connection, Database)
```

### Shutdown Order (Reverse)

```
1. RealtimeDataLogger (stop polling)
2. AlertManager (stop monitoring)
3. DriveDetector (stop detection)
4. StatisticsEngine (wait for running analysis)
5. DisplayManager (show shutdown message)
6. VinDecoder (no action needed)
7. OBD Connection (disconnect)
8. ProfileManager (no action needed)
9. Database (backup if configured, close)
```

### Thread Safety Considerations

- `RealtimeDataLogger` runs in background thread
- `StatisticsEngine.scheduleAnalysis()` runs in background thread
- `DisplayManager` may have auto-refresh thread
- All database access must use context managers
- Component state accessed from callbacks must be thread-safe

### Error Handling Strategy

| Error Type | Handling |
|------------|----------|
| Connection lost | Automatic retry with backoff |
| Query timeout | Log warning, continue with next parameter |
| Database error | Log error, attempt recovery |
| Display error | Fallback to headless mode |
| Analysis error | Log error, continue operation |
| Config error | Fail fast on startup |

---

## Success Metrics

- Application runs for 8+ hours without memory leak or crash
- Graceful shutdown completes within 10 seconds
- Connection recovery succeeds within 30 seconds
- All 324 existing tests continue to pass
- New integration tests pass
- Deployment to Raspberry Pi successful following documentation

---

## Timeline Estimate

| Phase | User Stories | Estimated Effort |
|-------|-------------|------------------|
| Core Orchestration | US-OSC-001 to US-OSC-005 | 2-3 days |
| Component Wiring | US-OSC-006 to US-OSC-013 | 2-3 days |
| Integration | US-OSC-014 to US-OSC-015 | 1 day |
| Deployment Prep | US-OSC-016 to US-OSC-020 | 1-2 days |
| **Total** | 20 user stories | **6-9 days** |

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Thread synchronization bugs | Medium | High | Use established patterns, thorough testing |
| Bluetooth reliability issues | Medium | Medium | Connection recovery logic, clear documentation |
| Memory leaks in long runs | Low | High | Profile memory usage, stress testing |
| Hardware compatibility | Low | Medium | Hardware verification script |

---

## Appendix: File Structure

```
src/obd/
├── orchestrator.py          # NEW: ApplicationOrchestrator class
├── ...existing modules...

deploy/
├── eclipse-obd.service      # NEW: systemd service file
├── install-service.sh       # NEW: service installation script
├── uninstall-service.sh     # NEW: service removal script

scripts/
├── check_platform.py        # EXISTS: platform verification
├── verify_hardware.py       # NEW: hardware verification

docs/
├── deployment-checklist.md  # EXISTS: deployment steps
├── bluetooth-setup.md       # NEW: Bluetooth pairing guide
├── testing.md               # NEW: testing procedures

tests/
├── test_orchestrator_integration.py  # NEW: integration tests
```

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-23 | Claude | Initial PRD for application orchestration |
