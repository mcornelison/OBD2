# I-007: Simulate Mode Testing Findings

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Open                      |
| Category     | obd / hardware / display  |
| Found In     | `python src/main.py --simulate` |
| Found By     | Torque (Pi 5 Agent)       |
| Related B-   | None                      |
| Created      | 2026-01-31                |

## Summary

Ran `--simulate` mode on Pi 5 for ~35 seconds. The OBD simulation core works correctly -- simulated connection, data logging, drive detection all functional. However, three hardware subsystems spam errors every 2-5 seconds, flooding the logs and making it difficult to see actual application events.

## What Worked (PASS)

1. **Simulated OBD connection**: Connected after 2s delay, simulated engine started
2. **VIN decode**: Found existing 1991 Honda from database
3. **Component initialization**: All 12 components initialized in correct dependency order (2.04s startup)
4. **Profile management**: 2 profiles loaded (daily, performance), active profile set to daily
5. **Alert manager**: 3 thresholds for daily, 4 for performance
6. **Realtime data logging**: 13 parameters at 1000ms interval, data written to database
7. **Drive detection**: Drive detected at RPM=791.9 after 10s above 500 RPM threshold
8. **Database writes**: 62 new readings captured during simulation (13 params x ~5 cycles)
9. **Graceful degradation**: GPIO button failure did not crash the app, UPS unavailable did not crash
10. **Headless display**: Correctly fell back to headless mode for application display layer

## Issues Found

### Issue 1: Pygame GL Context Error Spam (31 errors in ~35s)

**Severity**: Medium
**Component**: `hardware.status_display._refreshLoop`
**Error**: `Could not make GL context current: BadAccess (attempt to access private resource denied)`
**Rate**: Every 2 seconds (matches refresh rate 2.0s)

**Root Cause**: The `StatusDisplay` initializes pygame with a 480x320 window (line 72: `_initializePygame`), but running via SSH/Claude Code has no X11/Wayland display session. Pygame initializes but can't render to the GL context.

**Impact**: Floods logs with ERROR lines, obscures real application events. No crash -- the error is caught in the refresh loop.

**Suggested Fix**:
- Check for `$DISPLAY` environment variable before initializing pygame in StatusDisplay
- If no display session, skip pygame init and log once at INFO level
- Or: Add a config flag `hardware.statusDisplay.enabled` defaulting to `true` on Pi, `false` when SSH-only

### Issue 2: UPS Polling Error Spam (21 errors in ~35s)

**Severity**: Low
**Component**: `hardware.ups_monitor._pollingLoop`
**Error**: `UPS device not found at address 0x36`
**Rate**: Every 5 seconds (matches poll interval 5.0s)

**Root Cause**: UPS HAT (INA219 at I2C address 0x36) is not connected. The UPS monitor starts polling regardless, and logs a WARNING every cycle.

**Impact**: Clutters logs. Not a crash -- graceful degradation works. But the repeated warnings are noise.

**Suggested Fix**:
- After N consecutive failures (e.g., 3), reduce poll frequency or stop polling entirely
- Log first failure as WARNING, subsequent as DEBUG
- Or: Add backoff -- if device not found, check every 60s instead of 5s

### Issue 3: GPIO Button Failure on Pi 5

**Severity**: Low
**Component**: `hardware.gpio_button.start`
**Error**: `Cannot determine SOC peripheral base address`
**One-time**: Yes (logged once, then stops)

**Root Cause**: gpiozero falls back from lgpio (Pi 5 native) because `lgpio` module is not installed. The fallback (`RPi.GPIO` or `pigpio`) can't determine the Pi 5's SOC base address.

**Impact**: No physical button support. Not a blocker for OBD testing. One-time error, not spammy.

**Suggested Fix**:
- Install `lgpio` package: `sudo apt install python3-lgpio` and `pip install lgpio`
- Or: Add to `requirements-pi.txt`

### Issue 4: Simulated Data Shows Zero Values for 5 Parameters

**Severity**: Low (simulator fidelity, not a bug)
**Parameters**: ENGINE_LOAD, LONG_FUEL_TRIM_1, MAF, SHORT_FUEL_TRIM_1, SPEED, THROTTLE_POS
**Observed**: All readings are 0.00 even during an active drive

**Root Cause**: The default simulator vehicle profile doesn't vary these parameters. SPEED stays 0 even though RPM is ~800 (idle scenario, not driving). ENGINE_LOAD should show some value at idle (typically 15-25%).

**Impact**: Drive detection works (uses RPM only), but post-drive statistics for these parameters will be meaningless. When real dongle data comes in, this won't be an issue.

**Suggested Fix**: Update the simulator vehicle profile to provide realistic idle values:
- ENGINE_LOAD: 15-25% at idle
- MAF: 2-5 g/s at idle
- SPEED: 0 at idle is correct
- THROTTLE_POS: 0-5% at idle is correct
- Fuel trims: slight positive/negative fluctuation around 0

## Database State After Test

| Table | Records |
|-------|---------|
| realtime_data | 962 total (62 new from this session) |
| connection_log | 1 drive_start event |
| alert_log | 0 (no thresholds exceeded) |
| vehicle_info | 1 (1991 Honda, from prior session) |
| profiles | 2 (daily, performance) |

## Recommendations

1. **Priority**: Fix log spam (Issues 1 & 2) before dongle testing -- the noise will hide real Bluetooth connection errors
2. **Nice-to-have**: Install lgpio for Pi 5 GPIO support (Issue 3)
3. **Later**: Improve simulator profiles for more realistic idle values (Issue 4)
