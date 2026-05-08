# Sprint 26 P0 — Engine Telemetry Capture Regression
**Date**: 2026-05-05
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: P0 — Pi's primary mission is broken

## TL;DR

The 9-drain saga closed cleanly with V0.24.1. **But a separate regression has been hiding behind it: `ApplicationOrchestrator._initializeConnection` is blocking the orchestrator init thread for hours, so DriveDetector + the OBD-PID polling loop don't start until long after the ignition is keyed on. Result: zero engine telemetry captured for both of CIO's recent engine-on test cycles (May 4 + May 5).** Drive 5 (April 29) was the last drive successfully captured. Drives 6+ never happened despite the engine running.

This is a **regression** — drives 2-5 worked. CIO confirmed engine WAS keyed on for both recent cycles. Sprints 20-25 are the suspect window. US-244 "non-blocking BT-connect" was designed to prevent this; it isn't doing its job in production.

## Forensic Evidence (Pi journalctl, boot -1, 28-hour boot)

```
2026-05-04 14:41:08  pi.obdii.orchestrator | _initializeProfileManager  | ProfileManager started successfully
2026-05-04 14:41:08  pi.obdii.obd_connection | createConnectionFromConfig | Creating real ObdConnection
                                          ┊
                            ┊  27 HOURS OF SILENCE  ┊
                                          ┊
2026-05-05 18:03:52  pi.obdii.orchestrator | _initializeVinDecoder      | VinDecoder started successfully
2026-05-05 18:03:52  pi.obdii.orchestrator | _initializeDriveDetector   | Starting driveDetector...
2026-05-05 18:03:52  pi.obdii.orchestrator | _initializeDriveDetector   | DriveDetector started successfully
2026-05-05 18:03:52  pi.obdii.drive.detector | start                    | Drive detector started | startThreshold=500RPM | startDuration=10s | endDuration=60s
```

**The 27-hour blocking gap is not RTC drift.** Both timestamps are real wall-clock UTC after NTP sync. The orchestrator init thread was genuinely blocked for ~27 hours on `_initializeConnection`.

Boot 0 (current) shows the same pattern, smaller magnitude: **82-minute gap** between `_initializeConnection` start and `Initial connect timed out after 30.0s` WARNING. Per the documented behavior the timeout should fire at 30 sec; reality is 82 min.

## Cross-correlation with the engine-on events

| Event | Wall time (CDT) | Orchestrator state at that moment |
|---|---|---|
| May 4 engine on | 14:24 (connect_success in DB) | **STILL BLOCKED in `_initializeConnection` for 22 more hours** — DriveDetector never running. No polling, no RPM read, no drive_start. |
| May 5 engine on | 18:04 (connect_success in DB) | DriveDetector init finished at 18:03:52 — **10 seconds before** key-on. In theory could capture; in practice did not (drive_summary shows no Drive 6). |

**Both engine runs were on the wrong side of the orchestrator init blocker.** The May 4 cycle had no chance — orchestrator was hung on connect. The May 5 cycle had a 10-second margin and still didn't capture.

## What the data integrity damage looks like

Aggregate state of engine-data tables since the regression:

| Table | Last fresh data | Status |
|---|---|---|
| `drive_summary` | 2026-04-29T23:45:00Z (Drive 5) | Frozen — no drives 6+ |
| `realtime_data` (PID samples) | 2026-05-01T10:30:32Z | Frozen — no engine PIDs since |
| `connection_log` `drive_start` events | 2026-04-29 23:45:00 (drive_id=5) | Frozen |
| `statistics` (per-drive analytics) | 2026-04-30 00:02:39 | Frozen |
| `power_log` | Active ✓ | Working — UPS/ladder events flowing |
| `battery_health_log` | Active ✓ | Working — drain events captured |

Pi has been running and capturing power-management data for 6+ days, but **zero engine data**. The whole reason the Pi exists in this car is engine data capture.

## Suspect Window (Sprints 20-25)

Drive 5 (April 29) was the last successful capture, so the regression landed AFTER April 29. Sprints in flight since:

| Sprint | Released | Likely-relevant changes |
|---|---|---|
| Sprint 20 | ~April 30 | **US-244 non-blocking BT-connect** ← prime suspect by name; **US-242 idle-poll escalation**; touched `core.py`, `event_router.py`, `lifecycle.py` |
| Sprint 21 | May 1 (V0.21.0) | US-252 PowerDownOrchestrator decoupled from display loop; touched `lifecycle.py` |
| Sprint 22 | ~May 3 | Forensic logger, dashboard stage label; minimal `lifecycle.py` impact |
| Sprint 23 | May 3 | US-265 tick-thread liveness instrumentation; touched `lifecycle.py` |
| Sprint 24 | May 3 (V0.24.0) | US-279 event-driven callback wiring; touched `lifecycle.py` |
| **Sprint 25 (V0.24.1)** | **May 3 23:19** | Cross-module enum fix; touched `lifecycle.py` AND `hardware_manager.py` |

**My read: most likely Sprint 20 (US-244) introduced the bug; Sprints 21-25 didn't catch it because none of them ran the actual ECU on the workbench.** All drain testing was done with the engine OFF (just pulling wall power from the bench Pi). The bug requires "engine on, OBD connected, expect data capture" — a path none of the 9 drain tests exercised.

## Sprint 26 Recommended Stories

### Story 1 (M, P0) — Diagnose `_initializeConnection` blocker
**File:** `src/pi/obdii/orchestrator/lifecycle.py` (`_initializeConnection`) + `src/pi/obdii/obd_connection.py`

**Investigation steps:**
1. Time the actual call sites in `_initializeConnection`. Where does the 30-sec-spec → multi-hour-actual blocker live?
2. Verify US-244's "non-blocking BT-connect daemon thread" is actually being spawned. The commit-vs-claim verifier from US-282 should have caught this if the implementation matched the spec.
3. Inspect `obd.OBD()` init — the python-obd library may be doing synchronous I/O for protocol detection that ignores the 30-sec timeout.
4. Check whether `_initializeConnection` is actually configured with the 30-sec timeout, or if a config default is wrong.

**Acceptance:** boot-to-DriveDetector-ready time is under 60 seconds when no engine is present (currently 82+ min on boot 0; 27 hours on boot -1).

### Story 2 (M, P0) — Restore engine telemetry capture
**File:** `src/pi/obdii/drive/detector.py` + the OBD polling loop

**Investigation steps:**
1. After Story 1's fix, confirm DriveDetector starts within 60 sec of boot.
2. Confirm OBD polling loop starts after DriveDetector. (Or before? Check init order.)
3. Confirm RPM samples flow into DriveDetector's threshold logic.
4. Confirm `drive_start` event fires when RPM > 500 for 10 sec.

**Acceptance:** Drive 6 captures cleanly when CIO keys on the engine. drive_summary gets a new row with drive_id=6. realtime_data accumulates RPM/COOLANT_TEMP/MAF/etc samples for the duration of the run.

### Story 3 (S, P0) — Bench-test harness for "engine + OBD" path
**File:** new `tests/pi/integration/test_engine_drive_capture_e2e.py`

**Behavior:** an integration test that:
- Spawns the real ApplicationOrchestrator with mocked-only-at-the-I2C-and-BT-edge
- Simulates an OBD-connect-success
- Feeds RPM=750 samples through the data path
- Asserts within 60 sec: drive_start fires, drive_summary INSERT happens, realtime_data accumulates

**Why:** the 9-drain saga closed via Drain Tests, but those tests never exercised the engine-on path. The next test discipline level needs to cover "engine running, OBD connected, expect data" — without it, this regression class is invisible to CI. Mirror US-282's commit-vs-claim verifier philosophy: tests must exercise the real path.

### Story 4 (S, P1) — `startup_log` writer
**File:** `src/pi/diagnostics/boot_reason.py` (or wherever `startup_log` table is meant to be populated)

**Status:** Sprint 22 US-265 schema audit + Sprint 24 US-283 closure-in-fact-pre-existed shipped the SCHEMA. No rows have ever been written. Schema-audit only ≠ writer. Wiring this would have made post-mortem easier across all 9 drains.

**Acceptance:** every boot writes one `startup_log` row with `prior_boot_clean`, `prior_last_entry_ts`, `current_boot_first_entry_ts`. Drain Test 11 (next ladder verification) confirms `prior_boot_clean=true` for all the V0.24.1-era graceful shutdowns.

### Story 5 (S, P2) — Stage state-machine latching fix
**File:** `src/pi/power/orchestrator.py` (`PowerDownOrchestrator`)

**Behavior:** when the orchestrator enters `WARNING`, it must NOT re-fire WARNING on subsequent ticks even if VCELL fluctuates back above the threshold. Same for IMMINENT and TRIGGER. Pattern: **monotonic stage progression**; once advanced, never revert.

**Why:** Drain analysis shows 7 WARNING + 6 IMMINENT but only 4 TRIGGER. Multiple stage rows per actual power-down cycle are noise that pollutes downstream analytics. TRIGGER is atomic (good); WARNING/IMMINENT need the same treatment.

**Acceptance:** next test cycle produces exactly 1 row of each stage type (WARNING + IMMINENT + TRIGGER) per power-down event. battery_health_log produces exactly 1 drain event per power-down (no orphans, no 5-second false starts).

### Story 6 (S, P2) — `battery_health_log` column semantics fix
**File:** `src/pi/power/types.py` + DB migration

**Behavior:** `start_soc` / `end_soc` columns currently hold VCELL voltage values (3.4-4.2V range) but schema comment says "0..100 (MAX17048 integer % scale)." Either:
- Rename columns to `start_vcell_v` / `end_vcell_v`, OR
- Fix the writer to emit actual SOC percentage (decimal byte from MAX17048 reg 0x04)

I'd recommend the rename — VCELL is the real trigger value the ladder reads, and SOC is known-broken on this chip. Don't lie about column contents; document what we actually have.

## My Honest Disclosure

I owe a correction CIO already saw. **My Drain 9 inbox note last week diagnosed the wrong root cause** ("US-279 wiring silently bails"). The actual root cause Ralph + CIO found was cross-module PowerSource enum identity — a Python module-path issue I didn't consider. My "wiring bails" theory was a partial truth (one of the silent-skip paths could have been the bug; it wasn't) that pointed Ralph in roughly the right code area but at the wrong layer of abstraction.

Specifically I confused two similar-named subscribe log lines (`_subscribePowerMonitorToUpsMonitor` for the older PowerMonitor wiring, vs the new US-279 `_subscribeOrchestratorToUpsMonitor`). I claimed only the old one fired; in reality both fired correctly. **Do not weight my P0 diagnosis on this Sprint 26 ask too heavily before Ralph reproduces the 27-hour blocker on the bench.** The data above is solid (journal timestamps don't lie); my interpretation of WHICH code change introduced it is still hypothesis.

## Sources / Forensic Artifacts

- Boot -1 journal: `journalctl -b -1 -u eclipse-obd` on Pi — confirms 27-hour gap between ProfileManager and VinDecoder init
- Boot 0 journal: `journalctl -b 0 -u eclipse-obd` — confirms 82-min gap between `_initializeConnection` start and timeout WARNING
- `drive_summary` last row: `drive_id=5, drive_start_timestamp=2026-04-29T23:45:00Z`
- `realtime_data` MAX timestamp: `2026-05-01T10:30:32Z`
- `connection_log` shows 5 connect_success events ever; only 4 mapped to drives (2/3/4/5); the May 4 + May 5 connect_successes have NULL drive_id
- US-244 spec: "non-blocking BT-connect" — does not behave as specified

---

When Ralph reproduces this on the bench (engine off, just `start eclipse-obd` and watch the init log line timing), the regression is in front of his face within 60 seconds. The fix may be smaller than the diagnosis effort.

— Spool
