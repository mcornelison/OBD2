# PRD: OBD-II Simulator Mode

## Introduction

Add a simulation mode to the CLI that replaces the real Bluetooth OBD-II connection with a software simulator. The simulator models a configurable vehicle with physically plausible sensor behavior, realistic drive cycles, and injectable failure modes. This enables comprehensive testing of the entire system without requiring physical hardware (Model LX101 v2.1 or OBDLink dongle).

## Goals

- Enable full system testing without OBD-II hardware
- Provide physically plausible sensor values that respond realistically to simulated driving
- Support configurable vehicle profiles for different test scenarios
- Allow injection of failure modes (connection drops, sensor failures, DTCs)
- Integrate seamlessly with existing components via `--simulate` CLI flag
- Maintain API compatibility with real `ObdConnection` class

## User Stories

### US-033: Add --simulate CLI flag
**Description:** As a developer, I want to start the application in simulation mode via CLI so I can test without hardware.

**Acceptance Criteria:**
- [ ] `--simulate` / `-s` flag added to `src/main.py` argument parser
- [ ] When flag is present, system uses `SimulatedObdConnection` instead of real connection
- [ ] Simulation mode logged clearly at startup: "Running in SIMULATION MODE"
- [ ] All other CLI flags work normally with simulation mode
- [ ] `--simulate` flag documented in `--help` output
- [ ] Typecheck/lint passes

---

### US-034: Create SimulatedObdConnection class
**Description:** As a developer, I need a simulated connection class that matches the real ObdConnection interface so existing code works unchanged.

**Acceptance Criteria:**
- [ ] `SimulatedObdConnection` class in `src/obd/simulator/simulated_connection.py`
- [ ] Implements same interface as `ObdConnection`: `connect()`, `disconnect()`, `isConnected()`, `query()`, `getStatus()`
- [ ] `connect()` simulates connection delay (configurable, default 2 seconds)
- [ ] `query(command)` returns simulated sensor values from the vehicle simulator
- [ ] Returns `ConnectionStatus` dataclass matching real connection
- [ ] No actual Bluetooth or network calls made
- [ ] Typecheck/lint passes

---

### US-035: Create VehicleProfile dataclass
**Description:** As a developer, I need configurable vehicle profiles so the simulator can model different vehicles.

**Acceptance Criteria:**
- [ ] `VehicleProfile` dataclass in `src/obd/simulator/vehicle_profile.py`
- [ ] Fields: `vin`, `make`, `model`, `year`, `engineDisplacementL`, `cylinders`, `fuelType`, `maxRpm`, `redlineRpm`, `idleRpm`
- [ ] Fields for sensor ranges: `maxSpeedKph`, `normalCoolantTempC`, `maxCoolantTempC`
- [ ] `loadProfile(path)` function loads profile from JSON file
- [ ] `getDefaultProfile()` returns a generic 4-cylinder gasoline vehicle
- [ ] Profile JSON files stored in `src/obd/simulator/profiles/`
- [ ] Include `default.json` profile with sensible defaults
- [ ] Typecheck/lint passes

---

### US-036: Create SensorSimulator with physics model
**Description:** As a tester, I need sensor values that behave realistically so I can trust my test results reflect real-world behavior.

**Acceptance Criteria:**
- [ ] `SensorSimulator` class in `src/obd/simulator/sensor_simulator.py`
- [ ] Maintains internal vehicle state: `rpm`, `speedKph`, `coolantTempC`, `throttlePercent`, `engineLoad`, `fuelLevel`
- [ ] `update(deltaSeconds)` advances simulation by time delta
- [ ] Physics rules enforced:
  - RPM affects speed (via gear simulation or simple ratio)
  - Coolant temp rises from cold start (~20°C) toward operating temp (~90°C) over 5-10 minutes
  - Coolant temp rises faster under load, slower at idle
  - Engine load correlates with throttle position and RPM
  - Fuel level decreases gradually based on load
  - MAF correlates with RPM and throttle
- [ ] `getValue(parameterName)` returns current simulated value for any OBD parameter
- [ ] Values include realistic noise/variation (not perfectly smooth)
- [ ] Typecheck/lint passes

---

### US-037: Create DriveScenario system
**Description:** As a tester, I want pre-defined drive scenarios so I can run repeatable test cycles.

**Acceptance Criteria:**
- [ ] `DriveScenario` dataclass with `name`, `description`, `phases` list
- [ ] `DrivePhase` dataclass with `name`, `durationSeconds`, `targetRpm`, `targetSpeedKph`, `targetThrottle`
- [ ] `DriveScenarioRunner` class executes scenario phases in sequence
- [ ] Built-in scenarios in `src/obd/simulator/scenarios/`:
  - `cold_start.json`: Engine off → idle → warm up (5 min)
  - `city_driving.json`: Stop-and-go traffic pattern (10 min)
  - `highway_cruise.json`: Steady 70 mph cruising (10 min)
  - `full_cycle.json`: Cold start → city → highway → stop (20 min)
- [ ] `loadScenario(path)` loads custom scenarios
- [ ] Smooth transitions between phases (not instant jumps)
- [ ] Scenario runner emits callbacks: `onPhaseStart`, `onPhaseEnd`, `onScenarioComplete`
- [ ] Typecheck/lint passes

---

### US-038: Implement failure injection system
**Description:** As a tester, I want to inject failures so I can verify the system handles error conditions correctly.

**Acceptance Criteria:**
- [ ] `FailureInjector` class in `src/obd/simulator/failure_injector.py`
- [ ] Configurable failure modes:
  - `connectionDrop`: Simulate Bluetooth disconnect (duration configurable)
  - `sensorFailure`: Specific sensor returns NULL (list of affected sensors)
  - `intermittentSensor`: Sensor fails randomly (probability 0-1)
  - `outOfRange`: Sensor returns values outside normal range
  - `dtcCodes`: Inject specific diagnostic trouble codes
- [ ] `FailureConfig` dataclass for configuration
- [ ] `injectFailure(failureType, config)` activates a failure mode
- [ ] `clearFailure(failureType)` removes a failure mode
- [ ] `clearAllFailures()` resets to normal operation
- [ ] Failures can be scheduled: `scheduleFailure(failureType, startSeconds, durationSeconds)`
- [ ] Typecheck/lint passes

---

### US-039: Integrate simulator with existing OBD modules
**Description:** As a developer, I need the simulator to work with existing data logging, alerts, and analysis so I can test the full pipeline.

**Acceptance Criteria:**
- [ ] `createConnectionFromConfig()` returns `SimulatedObdConnection` when `--simulate` flag active
- [ ] Simulated connection works with `ObdDataLogger` and `RealtimeDataLogger`
- [ ] Simulated data triggers `AlertManager` when thresholds exceeded
- [ ] Simulated drives trigger `DriveDetector` start/end detection
- [ ] `StatisticsEngine` calculates valid statistics from simulated data
- [ ] Display modes (headless/minimal/developer) show simulated data correctly
- [ ] Typecheck/lint passes

---

### US-040: Add simulator configuration to config.json
**Description:** As a user, I want simulator settings in config so I can customize behavior without code changes.

**Acceptance Criteria:**
- [ ] New `simulator` section in `src/obd_config.json`:
  ```json
  "simulator": {
    "enabled": false,
    "profilePath": "src/obd/simulator/profiles/default.json",
    "scenarioPath": null,
    "connectionDelaySeconds": 2,
    "updateIntervalMs": 100,
    "failures": {
      "connectionDropProbability": 0,
      "sensorFailureProbability": 0,
      "dtcCodes": []
    }
  }
  ```
- [ ] Config loaded and validated by `obd_config_loader.py`
- [ ] `--simulate` flag overrides `simulator.enabled` to `true`
- [ ] Invalid config values produce clear error messages
- [ ] Typecheck/lint passes

---

### US-041: Create simulator status display
**Description:** As a developer, I want to see simulator state so I can understand what's being simulated.

**Acceptance Criteria:**
- [ ] Developer display mode shows "SIM" indicator prominently
- [ ] Developer display shows current scenario phase (if running scenario)
- [ ] Developer display shows active failure injections
- [ ] `getSimulatorStatus()` returns `SimulatorStatus` dataclass with current state
- [ ] Status includes: `isRunning`, `currentPhase`, `elapsedSeconds`, `activeFailures`, `vehicleState`
- [ ] Typecheck/lint passes

---

### US-042: Add simulated VIN decoding
**Description:** As a tester, I need VIN decoding to work in simulation so the full static data flow can be tested.

**Acceptance Criteria:**
- [ ] Simulated connection returns VIN from vehicle profile when queried
- [ ] VIN decoder can be bypassed in simulation (uses profile data directly)
- [ ] OR simulator includes mock NHTSA responses for test VINs
- [ ] Static data collection works with simulated VIN
- [ ] Vehicle info displayed correctly from simulated data
- [ ] Typecheck/lint passes

---

### US-043: Create simulator CLI commands
**Description:** As a developer, I want CLI commands to control the simulator while running.

**Acceptance Criteria:**
- [ ] During simulation, keyboard commands available:
  - `p` - Pause/resume simulation
  - `f` - Inject random failure
  - `c` - Clear all failures
  - `s` - Show current status
  - `q` - Quit simulation
- [ ] Commands work in developer display mode
- [ ] Commands logged to console
- [ ] Non-blocking input handling (doesn't pause data flow)
- [ ] Typecheck/lint passes

## Functional Requirements

- FR-1: `--simulate` flag activates simulation mode, replacing real OBD connection
- FR-2: `SimulatedObdConnection` implements identical interface to `ObdConnection`
- FR-3: Vehicle profiles define vehicle characteristics and sensor ranges in JSON
- FR-4: Sensor values follow physics rules (interdependent, time-varying)
- FR-5: Drive scenarios define repeatable test cycles with phases
- FR-6: Failure injection supports connection drops, sensor failures, out-of-range values, DTC codes
- FR-7: Simulator integrates with all existing components (logging, alerts, analysis, display)
- FR-8: Simulator configuration via `config.json` with CLI overrides
- FR-9: Status display shows simulation state, active failures, current phase

## Non-Goals

- No GUI for simulator control (CLI only)
- No network-based simulation (local only)
- No recording/playback of real OBD sessions (may be future feature)
- No fuel injection or ignition timing simulation (beyond basic load correlation)
- No transmission simulation beyond simple RPM-to-speed ratio
- No GPS or location simulation

## Technical Considerations

- **Module Location**: All simulator code in `src/obd/simulator/` subdirectory
- **No MVC**: Follow existing pattern of dataclasses + manager classes + helper functions
- **Dependency Injection**: Simulator injected via factory function, not global state
- **Thread Safety**: Simulator may run update loop in background thread
- **Pint Compatibility**: Simulated values must return `pint.Quantity` objects matching real OBD library
- **Profile Format**: JSON files for easy editing and version control

## Success Metrics

- Full test suite passes with `--simulate` flag
- Drive detection triggers correctly on simulated drives
- Alert thresholds trigger on simulated out-of-range values
- Statistics calculated from simulated data match expected patterns
- Developer can run complete system demo without hardware

## Open Questions

1. Should simulator support multiple simultaneous vehicles (fleet testing)?
2. Should we add a "record real session, replay in simulator" feature later?
3. What specific DTC codes should be injectable for testing?
