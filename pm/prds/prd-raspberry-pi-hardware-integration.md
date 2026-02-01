# PRD: Raspberry Pi Hardware Integration

**Parent Backlog Item**: B-007 (Touch Screen Display Support)
**Status**: Planned

## Introduction

This PRD documents the target hardware platform and defines the implementation plan for deploying the OBD2 application to a Raspberry Pi 5 car-powered system. The hardware includes a Geekworm X1209 UPS HAT for battery backup and safe shutdown, plus an OSOYOO 3.5" capacitive touch display for status monitoring.

Understanding the target hardware helps developers make informed decisions about resource usage, power considerations, and UI design throughout development.

## Goals

- Document target hardware specifications for developer reference
- Integrate OBD2 functionality with Raspberry Pi hardware
- Create deployment scripts for system setup and configuration
- Implement simple status display showing battery, connection, and errors
- Add power management for graceful shutdown on power loss
- Follow existing codebase patterns in `src/` structure

## Hardware Reference

### Core Components

| Component | Model | Purpose |
|-----------|-------|---------|
| Computer | Raspberry Pi 5 (8GB) | Main computing platform |
| UPS HAT | Geekworm X1209 | Battery backup, I²C telemetry, safe shutdown |
| Display | OSOYOO 3.5" HDMI Capacitive Touch | Status display, touch input |
| Storage | 128GB A2 U3/V30 microSD | High-endurance storage |

### Key Interfaces

| Interface | Purpose | Notes |
|-----------|---------|-------|
| USB-C | Power input from car | Via ignition-switched outlet |
| I²C | UPS telemetry | Battery voltage, current, charge %, power source |
| GPIO | Shutdown button | Physical button for manual shutdown |
| HDMI | Display output | 480x320 resolution |
| USB | Touch input | HID device, plug-and-play |
| USB/Bluetooth | OBD2 adapter | ELM327 connection |

### Power Behavior

- **Car On**: USB-C supplies 5V → Pi runs normally
- **Car Off**: UPS switches to battery → Software detects via I²C → Graceful shutdown within 30-60 seconds
- **Car Restart**: UPS auto-powers Pi when external power restored

### I²C Telemetry (X1209)

| Data Point | Description |
|------------|-------------|
| Battery Voltage | Current voltage (shutdown if < 3.0V) |
| Battery Current | Charge/discharge rate in mA |
| Battery Percentage | Estimated charge level |
| Power Source | External (car) or battery |

## User Stories

### US-RPI-001: Create Hardware Reference Documentation
**Description:** As a developer, I want hardware specifications documented in the codebase so that I understand the target platform constraints.

**Acceptance Criteria:**
- [ ] Create `docs/hardware-reference.md` with component specs
- [ ] Document I²C addresses and telemetry data points
- [ ] Document GPIO pin assignments
- [ ] Include wiring/connection diagram (text-based)
- [ ] Reference the detailed specs in `specs/samples/piSpecs.md`

---

### US-RPI-002: Verify OBD2 Module Compatibility with Raspberry Pi
**Description:** As a developer, I want to verify the existing OBD2 code runs on Raspberry Pi so that we can deploy to the target hardware.

**Acceptance Criteria:**
- [ ] Review existing OBD2 modules for Pi compatibility
- [ ] Document any platform-specific code paths needed
- [ ] Ensure `obd` library works on ARM64/Raspberry Pi OS
- [ ] Update `requirements.txt` with Pi-compatible versions if needed
- [ ] Add platform detection utility to `src/common/`

---

### US-RPI-003: Create Raspberry Pi Setup Script
**Description:** As a developer, I want a setup script that configures a fresh Raspberry Pi so that deployment is repeatable and documented.

**Acceptance Criteria:**
- [ ] Create `scripts/pi_setup.sh` for initial system configuration
- [ ] Enable I²C interface via `raspi-config` non-interactive
- [ ] Install system dependencies (i2c-tools, python3-smbus, etc.)
- [ ] Install Python dependencies from `requirements.txt`
- [ ] Create required directories (`/var/log/carpi/`, etc.)
- [ ] Script is idempotent (safe to run multiple times)
- [ ] Document usage in `docs/deployment.md`

---

### US-RPI-004: Create Pi-Specific Requirements File
**Description:** As a developer, I want a separate requirements file for Pi-specific dependencies so that the main requirements stays clean for development machines.

**Acceptance Criteria:**
- [ ] Create `requirements-pi.txt` with Pi-specific packages
- [ ] Include: `smbus2`, `RPi.GPIO`, `gpiozero`, `evdev`
- [ ] Include: `pygame` for display (if not in main requirements)
- [ ] Document installation order in setup script
- [ ] Ensure no conflicts with main `requirements.txt`

---

### US-RPI-005: Implement Platform Detection Utility
**Description:** As a developer, I want to detect whether code is running on Raspberry Pi so that Pi-specific features are only enabled on the target hardware.

**Acceptance Criteria:**
- [ ] Create `src/common/platform_utils.py`
- [ ] Implement `isRaspberryPi()` function
- [ ] Implement `getPlatformInfo()` returning OS, architecture, model
- [ ] Handle graceful fallback on non-Pi systems
- [ ] Add unit tests with mocked platform detection
- [ ] Follow existing `src/common/` patterns and standards

---

### US-RPI-006: Implement I²C Communication Module
**Description:** As a developer, I want an I²C communication module so that we can read telemetry from the X1209 UPS HAT.

**Acceptance Criteria:**
- [ ] Create `src/hardware/i2c_client.py`
- [ ] Implement read/write operations with retry logic (3 retries, exponential backoff)
- [ ] Handle I²C not available gracefully (non-Pi systems)
- [ ] Use `smbus2` library
- [ ] Add unit tests with mocked I²C bus
- [ ] Follow error classification system (retryable errors)

---

### US-RPI-007: Implement UPS Telemetry Module
**Description:** As a developer, I want to read battery status from the X1209 UPS so that we can monitor power and trigger safe shutdown.

**Acceptance Criteria:**
- [ ] Create `src/hardware/ups_monitor.py`
- [ ] Read battery voltage, current, percentage, power source
- [ ] Implement polling at configurable interval (default 5 seconds)
- [ ] Emit events on power source change (external → battery)
- [ ] Add configuration options to `config.json`
- [ ] Add unit tests with mocked I²C responses
- [ ] Log telemetry data using existing logger

---

### US-RPI-008: Implement Graceful Shutdown Handler
**Description:** As a developer, I want the system to shut down gracefully when car power is lost so that data is not corrupted.

**Acceptance Criteria:**
- [ ] Create `src/hardware/shutdown_handler.py`
- [ ] Monitor UPS for power source change to battery
- [ ] Configurable shutdown delay (default 30 seconds)
- [ ] Cancel shutdown if power restored before delay expires
- [ ] Initiate system shutdown via `systemctl poweroff`
- [ ] Log shutdown events with timestamps
- [ ] Add unit tests for shutdown logic

---

### US-RPI-009: Implement GPIO Shutdown Button Handler
**Description:** As a developer, I want a physical button to trigger safe shutdown so that users can manually power off the system.

**Acceptance Criteria:**
- [ ] Create `src/hardware/gpio_button.py`
- [ ] Monitor configurable GPIO pin for button press
- [ ] Debounce button input (ignore rapid presses)
- [ ] Trigger graceful shutdown on long press (3 seconds)
- [ ] Short press could show status or be configurable
- [ ] Handle GPIO not available gracefully (non-Pi systems)
- [ ] Add unit tests with mocked GPIO

---

### US-RPI-010: Implement Simple Status Display
**Description:** As a user, I want to see system status on the touch display so that I know the system is working and can see battery level.

**Acceptance Criteria:**
- [ ] Create `src/hardware/status_display.py`
- [ ] Display: Battery percentage and voltage
- [ ] Display: Power source (Car / Battery)
- [ ] Display: OBD2 connection status
- [ ] Display: Current errors or warnings
- [ ] Display: System uptime and IP address
- [ ] Use large, readable fonts (touch-friendly)
- [ ] Refresh display every 1-2 seconds
- [ ] Handle display not available gracefully (non-Pi systems)
- [ ] Use `pygame` for rendering

---

### US-RPI-011: Create systemd Service Files
**Description:** As a developer, I want systemd services so that the application starts automatically on boot and shuts down cleanly.

**Acceptance Criteria:**
- [ ] Create `deploy/obd2-app.service` for main application
- [ ] Create `deploy/ups-monitor.service` for power monitoring
- [ ] Services start after network is available
- [ ] Services restart on failure with backoff
- [ ] Proper shutdown ordering (app before UPS monitor)
- [ ] Document installation in `docs/deployment.md`

---

### US-RPI-012: Add Hardware Configuration to Config System
**Description:** As a developer, I want hardware settings in the config system so that GPIO pins, I²C addresses, and intervals are configurable.

**Acceptance Criteria:**
- [ ] Add `hardware` section to `config.json` schema
- [ ] Include: `i2c.address`, `i2c.bus`
- [ ] Include: `gpio.shutdownButton`, `gpio.statusLed`
- [ ] Include: `ups.pollInterval`, `ups.shutdownDelay`, `ups.lowBatteryThreshold`
- [ ] Include: `display.enabled`, `display.refreshRate`
- [ ] Add defaults to config validator
- [ ] Document settings in config example

---

### US-RPI-013: Implement System Telemetry Logging
**Description:** As a developer, I want system telemetry logged so that we can diagnose issues and track battery health over time.

**Acceptance Criteria:**
- [ ] Log to `/var/log/carpi/telemetry.log` (or configurable path)
- [ ] Log: timestamp, power source, battery V/mA/%, CPU temp, disk space
- [ ] Log every 10 seconds (configurable)
- [ ] Use rotating file handler (7 days or 100MB max)
- [ ] JSON format for easy parsing
- [ ] Integrate with existing logging patterns

## Functional Requirements

- FR-1: System must detect if running on Raspberry Pi and enable hardware features accordingly
- FR-2: System must read UPS telemetry via I²C at configurable intervals
- FR-3: System must initiate graceful shutdown within 60 seconds of power loss
- FR-4: System must cancel pending shutdown if power is restored
- FR-5: System must shut down immediately if battery drops below 10%
- FR-6: System must support physical shutdown button via GPIO
- FR-7: System must display status information on attached HDMI display
- FR-8: System must log telemetry data with rotation policy
- FR-9: All hardware modules must fail gracefully on non-Pi systems
- FR-10: System must start automatically on boot via systemd

## Non-Goals

- No complex touch UI with menus or settings (simple status only)
- No cloud sync or remote monitoring in this phase
- No OTA update mechanism in this phase
- No audio/buzzer alerts
- No automatic priority changes based on battery level
- No multi-display support

## Technical Considerations

### Directory Structure
```
src/
  hardware/
    __init__.py
    i2c_client.py
    ups_monitor.py
    shutdown_handler.py
    gpio_button.py
    status_display.py
    platform_utils.py  (or in src/common/)
deploy/
  obd2-app.service
  ups-monitor.service
scripts/
  pi_setup.sh
docs/
  hardware-reference.md
  deployment.md
```

### Dependencies (Pi-specific)
- `smbus2` - I²C communication
- `RPi.GPIO` or `gpiozero` - GPIO handling
- `pygame` - Display rendering
- `evdev` - Touch input (if needed beyond pygame)

### Configuration Schema Addition
```json
{
  "hardware": {
    "enabled": true,
    "i2c": {
      "bus": 1,
      "upsAddress": "0x36"
    },
    "gpio": {
      "shutdownButton": 17,
      "statusLed": 27
    },
    "ups": {
      "pollInterval": 5,
      "shutdownDelay": 30,
      "lowBatteryThreshold": 10
    },
    "display": {
      "enabled": true,
      "refreshRate": 2
    }
  }
}
```

### Error Handling
- I²C errors: Retryable (3 retries with backoff)
- GPIO errors: Configuration error (fail fast on Pi, ignore on non-Pi)
- Display errors: Log and continue without display
- Power loss: System error (immediate action required)

## Success Metrics

- OBD2 application runs successfully on Raspberry Pi 5
- System survives simulated power cuts without data corruption
- Battery status accurately displayed within 5% of actual charge
- Shutdown completes within 60 seconds of power loss
- All hardware modules have >80% test coverage
- Non-Pi development workflow unaffected by hardware code

## Open Questions

1. Should the status display show OBD2 live data (RPM, speed) or just connection status?
2. What GPIO pins are available after X1209 HAT is attached?
3. Should we implement a "demo mode" that simulates hardware for testing?
4. Is there a preference for pygame vs tkinter for the display?

## Implementation Priority

Based on user requirements, implement in this order:

1. **OBD2 Integration** (US-RPI-002) - Verify existing code works on Pi
2. **System Setup** (US-RPI-003, US-RPI-004, US-RPI-005) - Deployment scripts and platform detection
3. **Status Display** (US-RPI-010, US-RPI-012) - Simple status UI
4. **Power Management** (US-RPI-006, US-RPI-007, US-RPI-008, US-RPI-009, US-RPI-011, US-RPI-013) - UPS monitoring and safe shutdown

## Reference Documents

- Detailed hardware specs: `specs/samples/piSpecs.md`
- Coding standards: `specs/standards.md`
- Error handling patterns: `specs/methodology.md`
