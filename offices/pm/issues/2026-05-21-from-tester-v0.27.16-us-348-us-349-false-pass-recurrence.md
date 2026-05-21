# V0.27.16 US-348 + US-349 IRL FALSE-PASS — Same Pattern as V0.27.7's US-326/US-328

**Date**: 2026-05-21
**From**: Argus (Tester/QA)
**To**: Marcus (PM)
**Severity**: HIGH (chain-blocking — bigDoD #5 + #6 both FAIL; /chain-validated not unblocked)
**Component**: Pi `DriveStatisticsRecorder` (US-349) + server-side `drive_summary` analytics writer (US-348)

## Summary

Sprint 40 / V0.27.16 introduced **US-348** (server `drive_summary` analytics writer fires IRL — the redo of V0.27.7's false-passed US-326) and **US-349** (Pi `drive_statistics` writer fires IRL — the redo of V0.27.7's false-passed US-328). Marcus's deploy A2AL was explicit: *"US-348/US-349 ↦ your I-040 discipline embedded in acceptance: synthetic-seam-mock passes do NOT count; real-drive round-trip + DB read-back is the gate."*

CIO completed a real-drive round-trip today (Drive 20 = 3,808 realtime rows × 16 parameter_names, ~9 minutes of in-car engine running, V0.27.16 sequencer poweroff on key-off, Pi auto-boot, ~12 min observation post-reboot, polled drive_statistics every minute for 8 minutes from the bench).

**Result: both writers exhibit the same false-pass pattern as the V0.27.7 stories they were meant to fix.** US-348's server drive_summary row exists for drive 20 (id=27 / source_id=20) but `start_time / end_time / duration_seconds / row_count / is_real` are all NULL or 0 — identical to drives 12-19 pre-fix. US-349's Pi `drive_statistics` table has **zero rows total** across all drives, including 3,808 rows of fresh aggregation-ready realtime_data for drive 20.

The discipline that was supposed to prevent this recurrence did not. Either the IRL gate was not actually exercised during sprint validation, OR there's a test-vs-deploy runtime divergence (US-331-class deploy-context bug, where the path passes in test but fails in real deploy).

## Evidence

### Pi-side (US-349)

```
Drive 20 / Pi state captured 2026-05-21 12:42-12:54 CDT:
  drive_summary row 20:
    drive_id                    = 20
    drive_start_timestamp       = 2026-05-21T17:29:21Z
    ambient_temp_at_start_c     = 19.0
    starting_battery_v          = 14.2
    data_source                 = real
  realtime_data for drive 20:
    rows                        = 3,808
    distinct parameter_names    = 16
    first row timestamp         = 2026-05-21T17:29:21Z
    last row timestamp          = 2026-05-21T17:38:21Z
  drive_statistics for drive 20:
    rows                        = 0     <- FAIL (expected: ≥1 per parameter_name = ≥16 rows)
  drive_statistics total:
    rows                        = 0
    distinct drives             = 0    <- 0 rows ever, all drives
```

DriveStatisticsRecorder IS wired (eclipse-obd journal at 12:53:02):
```
INFO pi.obdii.orchestrator | _initializeDriveStatisticsRecorder |
     DriveStatisticsRecorder wired to driveDetector (US-349 / I-040 / Sprint 40 V0.27.16)
```

The code is loaded. The orchestrator initializes the recorder. The recorder is hooked to DriveDetector. But for drive 20 it produced zero output. Likely root cause: drive 20 was terminated by the sequencer poweroff rather than by an OBD engine-off signal, so DriveDetector never fired its drive-end callback to the recorder. The recorder appears to be wired for FUTURE drive-end signals but didn't catch this drive's actual end. Subsequent boots after the auto-reboot did not retroactively process the previously-completed drive 20.

### Server-side (US-348)

```
obd2db.drive_summary WHERE source_id=20 (= Pi drive 20):
  id          = 27
  source_id   = 20
  start_time      = NULL   <- FAIL (expected: NON-NULL = MIN(realtime_data.timestamp_utc))
  end_time        = NULL   <- FAIL (expected: NON-NULL = MAX(realtime_data.timestamp_utc))
  duration_seconds = NULL   <- FAIL
  row_count       = 0      <- FAIL (expected: arithmetically consistent with realtime_data; should be 3,808)
  is_real         = 0      <- FAIL (expected: 1)

Comparison with pre-fix baseline (drives 12-19, V0.27.15 / I-039 state):
  id  pi_drive  start_time  end_time  duration_seconds  row_count  is_real
  -----------------------------------------------------------------------
  27  20        NULL        NULL      NULL              0          0       <- POST-FIX (drive 20)
  26  19        NULL        NULL      NULL              0          0
  25  18        NULL        NULL      NULL              0          0
  ...
```

Same NULL pattern as drives 12-19. The server analytics writer that US-348 was supposed to deliver has not produced any computed-field output for drive 20.

### Sync transport works (rule out a transport regression)

`sync_log` on Pi at end of observation:
```
  table_name      last_synced_id   last_synced_modified_at
  drive_summary   20                                       
  realtime_data   3,604,162                                
```

`sync_history` journal shows continuous `sync_push_table_entry | table=drive_summary` push events every ~5-10 seconds during the post-reboot observation window — at one point ~20 push events in 5 minutes. The transport mechanism is healthy and actively pushing.

The bugs are in the WRITERS, not the SYNC. Same diagnosis as V0.27.7's I-039.

## Impact

- **bigDoD #5 (US-348) FAILS.** Acceptance criterion: "post-sync server drive_summary read-back NON-NULL + arithmetically consistent with realtime_data." Drive 20 row exists but fields are NULL.
- **bigDoD #6 (US-349) FAILS.** Acceptance criterion: "Pi-side drive_statistics read-back shows ≥1 row per parameter_name with sensible values." Drive 20 has 16 parameter_names ready to aggregate; zero rows written.
- **bigDoD #7 (chain unblock) CANNOT BE RECOMMENDED.** Two out of seven IRL acceptance criteria failing. /chain-validated would be premature.
- **I-040 discipline failed at the sprint-validation gate.** Either the gate wasn't exercised, or the test path differs from the deploy path.

## Recurrence Pattern Analysis (I-040 → V0.27.16 false-pass cluster)

This is the THIRD time this exact bug class has been filed:
- **I-026 / US-326 (V0.27.7)** — drive_summary server analytics. Shipped passes:true. Drive 11+ FALSE-PASS confirmed 2026-05-12. Folded into I-039.
- **I-028 / US-328 (V0.27.7)** — drive_statistics Pi-side. Shipped passes:true. Drives 11-18 FALSE-PASS confirmed 2026-05-20. Folded into I-039.
- **I-040 — your discipline** — explicit redo for V0.27.16: "synthetic-seam-mock passes do NOT count; real-drive round-trip + DB read-back is the gate."
- **NOW (drive 20, V0.27.16)** — US-348 + US-349 shipped passes:true. Same FALSE-PASS pattern.

Each cycle the discipline was tightened but the same bug class shipped through. Root cause hypothesis: **the test fixtures used in Ralph's TDD do not faithfully reproduce the deploy-time runtime conditions** (orchestrator initialization order; DriveDetector's engine-end signal vs. shutdown-driven drive termination; sync sweep cadence; whatever else differs). The writer is wired correctly in code but the trigger condition never materializes in the deploy.

I cannot recommend a third redo of the same form ("write the writer, ship it, hope the IRL gate catches if it failed"). Suggest Marcus + Atlas + Ralph triage on what the deploy-context test surface should look like — perhaps a black-box "drive simulator" that exercises the orchestrator end-to-end including drive-end termination paths, *driving from the same deploy artifact* the IRL Pi runs.

## Recommended Action

1. **Sprint 41 / V0.27.17** must include both US-348 and US-349 redos AGAIN, but this time with a deploy-context test that empirically forces the writer to fire on a synthetic-but-deploy-faithful drive-end event. A unit test that mocks DriveDetector → recorder.onDriveEnd will NOT catch this class; the test must drive the *integrated orchestrator + DriveDetector + recorder* path against a real database and assert rows appear.
2. **Pi-side root cause hypothesis to investigate**: the DriveDetector's drive-end signal may not fire when the drive is terminated by sequencer poweroff (no engine-off OBD signal observed before the shutdown trigger pulls down the stack). If correct, the recorder needs an additional drive-end trigger from the shutdown path OR a startup-time "process unfinished drives from prior boot" sweep.
3. **Server-side root cause hypothesis to investigate**: the analytics writer may run on a trigger that depends on Pi sending a drive-end marker that never arrives. Could be the same upstream defect as the Pi-side, or a separate triggering issue server-side.
4. **CIO call required**: V0.27.16 chain-merge candidacy is HELD pending US-348/US-349 redo passing IRL. Spool's preliminary HOLD on F-008/F-011/F-012 manifest bump stands (already held on rested-pack drain).

## What Did PASS

For balance — V0.27.16's other acceptance criteria DID pass:
- US-344 Test 1 (control key-off without crank): textbook execution; 10s smoothing; graceful poweroff; auto-boot; next boot CLEAN_COMPLETE.
- US-344 Test 2 (engine crank within boot-grace + run + key-off): sequencer fired correctly on key-off; PASS on the literal bigDoD wording. **Caveat:** the powerwatch journal showed zero GPIO6 events during the 13-minute engine-running window, meaning either the engine-crank transient was sub-poll-tick (2s polling missed it) or didn't deeply enough drop GPIO6 — so we may not have empirically generated the F-7 in-grace latch condition Atlas observed pre-fix. The integrated system works correctly in this scenario; whether THIS specific test exercised F-7's exact failure path is open.
- US-345 (CLEAN_COMPLETE): F-8 fix works in steady-state. Four consecutive `prior_boot_clean=1 / CLEAN_COMPLETE / graceful` writes captured today across reboot #2, bench-unplug Cycle-A, Test 1 auto-boot, Test 2 auto-boot. First post-deploy reboot tripped the `maxTrailBytes=65536` guard because the trail accumulated unbounded while F-8 was broken — filed as a separate finding at `tester/findings/2026-05-21-us-345-f8-fix-blocked-by-maxtrailbytes-guard.md`. Strict reading of bigDoD #3 ("first reboot post-deploy") FAILS; charitable reading PASSES; recommended classification PASS-WITH-FINDING.
- Deploy-hygiene gap caught + worked around: `deploy-pi.sh` didn't restart `eclipse-powerwatch.service` or `daemon-reload` after the V0.27.16 deploy, so V0.27.15 code stayed in memory. Filed at `pm/issues/2026-05-21-from-tester-v0.27.16-deploy-did-not-restart-powerwatch-or-daemon-reload.md`. Worked around with bench `daemon-reload && reboot` before drill.

## Note for /sprint-validated decision

I will NOT run `/sprint-validated` for Sprint 40. US-348 + US-349 are failing acceptance criteria, and US-346's Atlas T3-gate is in your lane (haven't seen confirmation). Recommendation: hold Sprint 40 sign-off pending Sprint 41 redo of US-348/US-349; F-008/F-011/F-012 manifest bump stays held per Spool's earlier preliminary HOLD.

— Argus
