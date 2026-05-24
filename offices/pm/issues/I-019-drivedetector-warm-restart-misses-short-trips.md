# I-019: DriveDetector misses short warm-restart trips (<5 min after prior key-off)

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High                      |
| Status       | Open                      |
| Category     | obd / drive-detection     |
| Found In     | `src/pi/obdii/drive/detector.py` (drive-state-machine; root cause unknown)  |
| Found By     | Spool 2026-05-10 (3-drive evening test, chi-eclipse-01)  |
| Related B-   | B-063 (hardware blocker -- repro requires stable Pi power) |
| Created      | 2026-05-10                |

## Description

Mike captured Drives 8 + 9 cleanly tonight (5/9 evening) but a short 2-3 min around-the-block test BETWEEN them never fired drive_start / drive_end -- the data lives as **1,078 NULL-drive_id rows** in `realtime_data` for the orphan window 2026-05-09T23:40 → 2026-05-10T00:16Z (37 min span, ~3 min of which was actual driving).

This is systemic data loss for the new car-coupled lifecycle (Pi-to-ignition wiring landed 2026-05-09): the "key-off → wait 1-2 min → key-on → drive-around-block → key-off" pattern is exactly the routine "stop at gas station / drop something off / move the car" behavior the system MUST handle. Missing every short hop = silent telemetry gap.

## Steps to Reproduce (Spool's recommended deterministic protocol)

**REQUIRES**: Pi running on stable power (B-063 hardware fix must land first; running on flaky USB-C confounds DriveDetector behavior with brownout-throttling).

1. **Test A**: cold-start drive ~10-15 min. Should produce drive_id=N at 400+ rows/min.
2. **Test B**: within 2-5 min of A's key-off, key-on, drive 2-3 min, key-off. **THIS is the bug-isolation test.** Expected: drive_id=N+1 with 400+ rows/min. Bug-active: NULL-tagged orphan rows.
3. **Test C**: within 5-10 min of B's key-off, key-on, drive ~10-15 min. Should produce drive_id=N+2 at 400+ rows/min.

If A and C are clean and B is missing, the bug isolates to short-restart behavior.

## Expected Behavior

DriveDetector emits `drive_start` event + assigns drive_id whenever RPM > 500 sustained for the configured threshold, regardless of how soon after the prior `drive_end` the next key-on occurs (assuming >= MIN_INTER_DRIVE_SECONDS = 5 has passed).

## Actual Behavior (empirical evidence, 2026-05-10)

| drive_id | Window | Duration | Rows | Notes |
|---:|---|---:|---:|---|
| 8 | 5/9 23:21-23:39 | 18 min | 8,268 (459 rows/min) | Clean cold-start city drive |
| (missing) | 5/9 23:40 → 5/10 00:16 | 37 min orphan | 1,078 NULL-tagged | 2-3 min around-the-block within this window; **DriveDetector NEVER fired drive_start** |
| 9 | 5/10 00:16-00:46 | 30 min | 1,095 (36 rows/min, **12x lower than Drive 8**) | Compromised by USB-C power flicker |
| 10 | 5/10 01:12-01:14 | 2:10 | (small) | Garage pull-in |

So Drive 8 → orphan-window → Drive 9 spans ~37 min total; the around-the-block was buried in the middle ~3-min driving slice that DriveDetector ignored.

## Hypothesis Verification

**Spool's hypothesis** (in 2026-05-10 inbox note): "DriveDetector has a debounce window or cooldown timer that swallows new-drive detection if a key-on happens within N minutes of the prior key-off."

**PM verification (per `feedback_pm_verify_diagnostic_premises.md`)**: `src/pi/obdii/drive/types.py:54` defines `MIN_INTER_DRIVE_SECONDS = 5`. **Five seconds, not minutes.** Mike waited 1+ minute between Drive 8 end and around-the-block start; this debounce would NOT have fired.

**The bug exists** (1,078 NULL-drive_id rows confirm it) **but the hypothesized root cause is wrong.** Real root cause is somewhere else; possibilities to investigate:

1. PowerDownOrchestrator KEY_OFF state from Drive 8 didn't fully reset before around-the-block (orchestrator state machine race?)
2. Connection_log state-tracking didn't reset; DriveDetector consumes connection_log for drive boundaries?
3. RPM/SPEED parameter polling paused during the brief key-off window and did not resume cleanly on key-on
4. ApplicationOrchestrator init blocker (TD-036 / Sprint 25 territory) on warm-restart left DriveDetector unwired

Pre-flight audit by Ralph during V0.27.3 grooming should run `rg DriveDetector|drive_detector|MIN_INTER_DRIVE_SECONDS|driveCooldown` + read `src/pi/obdii/drive/detector.py` state machine to identify the actual gap.

## Impact

- Every short warm-restart drive (gas station / errand / move-the-car) silently loses telemetry
- Backfill is possible (timestamp_ms ranges + connection_log evidence) but not automatic
- Long-term: if this bug persists, every drive shorter than ~15 min between key-cycles is at risk; Mike's daily-use pattern hits this routinely
- Combined with Bug B (battery_health_log unclosed close-events), the post-wiring lifecycle has TWO failure modes that compound -- "every key-off leaves a row open + every short-restart drives data orphaned"

## Resolution

V0.27.3 candidate. Story scope (when groomed) should be:

1. Investigate via repro protocol (REQUIRES B-063 hardware fix to be live so power isn't a confound)
2. Identify root cause via pre-flight audit of DriveDetector state machine + ApplicationOrchestrator init path on warm-restart
3. Fix + ship integration test (synthetic warm-restart sequence A/B/C; Test B asserts drive_id=N+1)
4. Backfill the 1,078 NULL-drive_id orphan rows from 2026-05-09T23:40 → 2026-05-10T00:16Z (timestamp range query)

## Cross-references

- Spool's inbox note: `offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-three-drives-tonight-power-blocker-drive-counter-clarification.md` (Bug A section)
- B-063 hardware fix (must land first; repro is unstable on flaky USB-C power)
- `src/pi/obdii/drive/types.py:54` (MIN_INTER_DRIVE_SECONDS = 5; refutes Spool's debounce-window hypothesis)
- `feedback_pm_verify_diagnostic_premises.md` (PM applied this rule; saved going to sprint with wrong premise)
