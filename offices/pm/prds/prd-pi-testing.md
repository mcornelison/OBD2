# PRD: Pi 5 Testing -- Simulated and Real OBD2

**Parent Backlog Item**: B-014
**Status**: Planned (blocked by B-012, B-013, B-015)

## Introduction

Once the application is deployed to the Pi 5 (via B-013 CI/CD pipeline), it must be validated in two modes:

1. **Simulated OBD2**: Using the built-in simulator (`--simulate`) to verify the full stack works on Pi hardware without needing a vehicle. This can be run at a desk.
2. **Real Bluetooth OBD2**: Using a physical ELM327 Bluetooth dongle in a running vehicle to verify real-world connectivity and data flow.

This PRD creates automated verification scripts that Ralph can build, plus a manual testing checklist for the CIO to follow during real-world testing.

## Goals

- Automated Pi deployment verification script (simulator mode)
- Manual Bluetooth testing checklist
- Confidence that the full application stack works on the target platform
- Catch Pi-specific issues (file paths, permissions, display, I2C) before real-world use

## Prerequisites

These must be complete before B-014 work begins:

| Dependency | Item | Status |
|-----------|------|--------|
| Pi setup | B-012 | Pi OS installed, SSH working, pi_setup.sh run |
| CI/CD | B-013 | Code deployed to Pi via `make deploy` |
| Database | B-015 | Database initialized on Pi via `verify_database.py --init` |

## Existing Infrastructure

| Component | File | Status |
|-----------|------|--------|
| Simulator system | `src/obd/simulator/` | Complete (physics-based, scenarios, profiles) |
| Simulator activation | `--simulate` CLI flag or `simulator.enabled` config | Complete |
| Platform checker | `scripts/check_platform.py` | Complete |
| Hardware verifier | `scripts/verify_hardware.py` | Complete |
| Database verifier | `scripts/verify_database.py` | Created by B-015 |
| Drive scenarios | `src/obd/simulator/scenarios/*.json` | 4 scenarios available |
| systemd service | `deploy/eclipse-obd.service` | Complete |

## User Stories

### US-PIT-001: Create Pi Deployment Verification Script

**Description:** As a developer, I need an automated script that runs on the Pi and verifies the full application stack works in simulator mode.

**Acceptance Criteria:**
- [ ] Create `scripts/verify_pi_deployment.py` with standard file header per `specs/standards.md`
- [ ] Script checks prerequisites: Python version, database exists, config loadable
- [ ] Starts the application in simulator mode as a subprocess: `python src/main.py --simulate --verbose`
- [ ] Lets it run for 30 seconds (configurable via `--duration` argument, default 30)
- [ ] Sends SIGINT (or equivalent) to trigger graceful shutdown
- [ ] After shutdown, verifies:
  - Process exited with code 0
  - Database has new records in `realtime_data` table (timestamp within last 60 seconds)
  - Log file exists and contains expected entries (e.g., "Starting", "Simulator", sensor data)
- [ ] Reports PASS/FAIL for each check with details
- [ ] Returns exit code 0 if all checks pass, 1 if any fail
- [ ] Uses camelCase naming per project standards
- [ ] All tests pass, typecheck passes

### US-PIT-002: Create Bluetooth Pairing Verification Script

**Description:** As a developer, I need a script that checks whether a Bluetooth OBD2 dongle is paired and reachable from the Pi.

**Acceptance Criteria:**
- [ ] Create `scripts/verify_bluetooth.py` with standard file header
- [ ] Checks if Bluetooth is enabled on the Pi (`bluetoothctl show`)
- [ ] Lists paired Bluetooth devices
- [ ] Checks if an OBD2 dongle is paired (looks for common names: "OBDII", "OBD", "ELM327", "V-LINK")
- [ ] If paired: attempts to check if the device is reachable (ping via `l2ping` or `rfcomm`)
- [ ] Reports: Bluetooth status, paired devices list, OBD2 dongle found (yes/no), reachable (yes/no)
- [ ] Returns exit code 0 if dongle is paired and reachable, 1 otherwise
- [ ] Graceful fallback on Windows (prints "Bluetooth verification requires Raspberry Pi" and exits 0)
- [ ] Uses camelCase naming per project standards
- [ ] All tests pass, typecheck passes

### US-PIT-003: Create Manual Testing Checklist Document

**Description:** As the CIO, I need a printed checklist to follow when testing the system in my vehicle with a real OBD2 dongle.

**Acceptance Criteria:**
- [ ] Create `docs/pi-testing-checklist.md`
- [ ] Section 1 - Pre-Drive Setup (at home):
  - Verify Pi boots and connects to home WiFi
  - Run `scripts/verify_pi_deployment.py` (simulator test)
  - Run `scripts/verify_bluetooth.py` (Bluetooth check)
  - Pair Bluetooth dongle if not already paired (step-by-step instructions)
  - Ensure `.env` is on Pi with correct values
- [ ] Section 2 - In-Vehicle Testing:
  - Connect Pi to vehicle power (USB-C)
  - Plug OBD2 dongle into vehicle port
  - Start application: `python src/main.py --verbose`
  - Verify: dongle connects (check log output)
  - Verify: VIN is read and decoded
  - Verify: sensor data appears (RPM, speed, coolant temp)
  - Drive for 5+ minutes
  - Stop vehicle, wait 60 seconds for drive-end detection
  - Verify: statistics calculated (check log)
  - Verify: AI analysis runs if on WiFi (check log)
  - Ctrl+C to stop, verify graceful shutdown
- [ ] Section 3 - Post-Drive Verification (at home):
  - SSH to Pi: `ssh pi@eclipse-pi.local`
  - Run: `python scripts/verify_database.py --db-path data/obd.db`
  - Check `realtime_data` table has records from the drive
  - Check `statistics` table has new entries
  - Check logs for errors or warnings
- [ ] Section 4 - Troubleshooting:
  - Bluetooth won't pair
  - Dongle connects but no data
  - Application crashes on start
  - Display not rendering
  - WiFi not connecting (for AI analysis)
- [ ] Typecheck passes (n/a for docs)

### US-PIT-004: Write Tests for Pi Verification Scripts

**Description:** As a developer, I need tests for the verification scripts that can run on Windows (mocking Pi-specific operations).

**Acceptance Criteria:**
- [ ] Create `tests/test_verify_pi_deployment.py` with standard file header
- [ ] Test: Verification script detects successful simulator run (mock subprocess with exit code 0, mock database with recent records)
- [ ] Test: Verification script detects failed simulator run (mock subprocess with non-zero exit, no database records)
- [ ] Test: Verification script handles missing database gracefully
- [ ] Test: Verification script handles subprocess timeout
- [ ] Create `tests/test_verify_bluetooth.py` with standard file header
- [ ] Test: Bluetooth script returns graceful message on non-Pi platform
- [ ] Test: Bluetooth script parses `bluetoothctl` output correctly (mock subprocess)
- [ ] Test: Bluetooth script detects paired OBD2 dongle by name pattern
- [ ] Tests use `monkeypatch` or `unittest.mock` for subprocess and platform operations
- [ ] All tests pass, typecheck passes

## Functional Requirements

- FR-1: All verification scripts must work on both Windows (graceful skip) and Pi (full functionality)
- FR-2: Scripts must import from project modules where possible (don't reinvent database queries)
- FR-3: Output must use colored status messages matching `pi_setup.sh` style
- FR-4: No scripts should require internet access (except AI analysis, which is optional)
- FR-5: Simulator verification must complete within 60 seconds (30s run + 30s overhead)

## Non-Goals

- No performance benchmarking (just functional verification)
- No load testing or stress testing
- No automated Bluetooth pairing (manual CIO task)
- No display UI testing automation (manual visual check)
- No continuous monitoring or alerting

## Design Considerations

- The simulator test runs the real application as a subprocess -- this is an integration test, not a unit test. It validates the full stack on Pi hardware.
- Bluetooth operations require Linux-specific tools (`bluetoothctl`, `l2ping`). Scripts must detect the platform and skip gracefully on Windows.
- The manual checklist is deliberately not automated -- real-world OBD2 testing requires a human in a vehicle.
- The 30-second simulator run should generate enough data to verify the pipeline (5-10 sensor readings per second = 150-300 records).

## Success Metrics

- `verify_pi_deployment.py` passes on Pi after `make deploy`
- CIO completes the vehicle testing checklist with all checks passing
- Real sensor data appears in the database from a live drive

## Open Questions

- None
