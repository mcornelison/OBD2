# I-008: Simulate Mode Retest — Log Spam Fixed, Pipeline Verified

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Info (report)             |
| Status       | Closed                    |
| Category     | obd / hardware / testing  |
| Found In     | `python src/main.py --simulate` |
| Found By     | Torque (Pi 5 Agent)       |
| Related      | I-007 (original findings) |
| Created      | 2026-02-01                |

## Summary

Retest of `--simulate` mode after fixing the three log spam sources identified in I-007. All three fixes confirmed working. Full OBD connection pipeline verified end-to-end.

## Log Spam Fix Results

| Component | Before (35s) | After (40s) | Fix |
|-----------|-------------|-------------|-----|
| StatusDisplay._refreshLoop | 31 ERROR lines | 1 ERROR + 1 suppression WARNING | Consecutive error counter, demote to DEBUG after 3rd |
| UpsMonitor._pollingLoop | 21 WARNING lines | 1 WARNING + 1 backoff WARNING | Consecutive error counter, backoff 5s→60s, demote to DEBUG after 3rd |
| TelemetryLogger.getTelemetry | ~4 WARNING lines | 1 WARNING + 1 suppression WARNING | Consecutive error counter, demote to DEBUG after 2nd |
| **Total** | **~52 lines** | **10 one-time lines** | **~80% noise reduction** |

## OBD Connection Pipeline — Full Pass

| Stage | Status | Details |
|-------|--------|---------|
| Config load | PASS | 15 env vars loaded, secrets resolved, config validated |
| Component init | PASS | 12 components in dependency order, 2.05s startup |
| Simulated OBD connect | PASS | 2s delay, engine started, connected |
| VIN decode | PASS | Found 1991 HONDA from existing database |
| Display manager | PASS | Headless mode (no X11 session) |
| Hardware manager | PASS | Graceful degradation for absent UPS/GPIO/display |
| Data logging | PASS | 13 parameters @ 1000ms, 38 cycles, 494 readings, 0 errors |
| Drive detection | PASS | Drive started at RPM=794.5, ended after 27.8s |
| Statistics analysis | PASS | 13 params, 3926 samples, completed in 53.7ms |
| Alert manager | PASS | 3 thresholds (daily), 4 thresholds (performance), 0 triggered |
| Health check | PASS | data_rate=783/min, 0 errors |
| Graceful shutdown | PASS | SIGTERM → all 12 components stopped in 0.11s, exit_code=0 |

## Remaining Expected Warnings (Not Bugs)

These will resolve when hardware is available:

| Warning | Cause | Resolution |
|---------|-------|------------|
| `OBD_BT_MAC not set` | No dongle MAC in .env | Set when BT dongle arrives |
| `UPS device not found at 0x36` | UPS HAT not installed (on order) | Test when UPS arrives |
| `Cannot determine SOC peripheral base address` | Needs `lgpio` package | `sudo apt install python3-lgpio && pip install lgpio` |
| `Could not make GL context current: BadAccess` | No X11/Wayland via SSH | Works with display connected directly |

## Open Items from I-007

| Issue | Status | Notes |
|-------|--------|-------|
| Issue 1: GL context spam | **FIXED** | Suppressed after 3rd consecutive error |
| Issue 2: UPS polling spam | **FIXED** | Suppressed + backoff to 60s |
| Issue 3: GPIO button on Pi 5 | Open (Low) | Needs lgpio install |
| Issue 4: Simulated zero values | Open (Low) | Simulator fidelity, not a bug |

## Test Gap Identified

There is **no automated test** that validates simulate mode output was successfully logged to the database with all 13 parameters and correct attributes. Filed as TD-005.

## Conclusion

The OBD simulation pipeline is fully operational end-to-end. The application is ready for real Bluetooth dongle integration testing once the hardware arrives.
