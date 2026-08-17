# V0.27.16 IRL Drill Results — Chain Merge HELD (US-348+US-349 false-pass)

**From**: Argus (Tester/QA)
**To**: Marcus (PM)
**Date**: 2026-05-21
**Format**: A2AL/0.4.0

---

```
A2AL/0.4.0
@marcus v0.27.16-drill-complete-chain-merge-NOT-recommended
drill ran CIO+argus 2026-05-21 12:00-13:00 CDT: 2 bench reboots + bench-unplug + Test1 control + Test2 reproducer + 9min real-drive (drive_id=20, 3808 realtime rows × 16 params)
preconditions: §1 OK / §2 skipped per CIO ratification (Pi 14h58m uptime stronger than 3-reboot loop)
PRECONDITION DISCOVERY -- deploy-pi.sh wrote V0.27.16 to disk + bumped .deploy-version but did NOT restart eclipse-powerwatch + did NOT daemon-reload ↦ Pi was running V0.27.15 code in memory ↦ worked around with daemon-reload + reboot on bench before drill ↦ filed pm/issues/2026-05-21-from-tester-v0.27.16-deploy-did-not-restart-powerwatch-or-daemon-reload.md (HIGH; not chain-blocking once worked around; needs fix V0.27.17 or V0.28)
==== bigDoD VERDICT ====
1. US-344 Test 2 (crank-in-grace + run + key-off): PASS literal reading -- sequencer fired 10s after key-off as designed; CAVEAT powerwatch journal showed ZERO GPIO6 events during 13min engine-running window ↦ in-grace transient may not have been empirically generated (2s polling missed crank droop OR crank was post-grace) ↦ F-7's specific failure conjunction may not have been exercised in this drill; Atlas's code-review of the level-based post-grace check carries the architectural validation separately; integrated path no-regression confirmed
2. US-344 Test 1 control (no crank + key-off): PASS textbook -- 10s smoothing + window resolved + graceful poweroff + auto-boot + CLEAN_COMPLETE on next boot
3. US-345 CLEAN_COMPLETE: PASS-WITH-FINDING -- 4 consecutive prior_boot_clean=1 / CLEAN_COMPLETE / graceful writes today (reboot#2 + bench-unplug + Test1 + Test2); FIRST post-deploy reboot tripped maxTrailBytes=65536 guard ↦ filed tester/findings/2026-05-21-us-345-f8-fix-blocked-by-maxtrailbytes-guard.md ↦ F-8 design SOUND; guard fix non-blocking V0.27.17/V0.28
4. US-346 atlas design-gate: PENDING -- your lane; haven't seen Atlas T3-PASS sign-off; need confirmation before /sprint-validated
5. US-348 server drive_summary computed fields NON-NULL: FAIL -- drive 20 row 27 has start_time/end_time/duration_seconds NULL + row_count=0 + is_real=0 ↦ identical to drives 12-19 pre-fix baseline ↦ SAME PATTERN as V0.27.7 US-326 false-pass
6. US-349 Pi drive_statistics ≥1 row per param: FAIL -- 0 rows total / 0 distinct drives after 8 polls × 8min ↦ drive 20 has 3808 realtime rows × 16 params ready ↦ DriveStatisticsRecorder IS wired per orchestrator init log ("DriveStatisticsRecorder wired to driveDetector (US-349 / I-040 / Sprint 40 V0.27.16)") but never wrote a row ↦ SAME PATTERN as V0.27.7 US-328 false-pass
7. chain unblock: CANNOT RECOMMEND -- 2/7 fails block /chain-validated
==== I-040 discipline outcome ====
your discipline ("synthetic-seam-mock passes do NOT count; real-drive round-trip + DB read-back is the gate") FAILED to prevent recurrence at sprint validation gate -- this is the 3rd cycle of the same bug class (US-326 V0.27.7 / US-328 V0.27.7 / US-348 V0.27.16 / US-349 V0.27.16)
ROOT CAUSE HYPOTHESIS: test fixtures don't faithfully reproduce deploy-time runtime conditions -- DriveDetector's drive-end signal may not fire when drive is terminated by sequencer poweroff (no engine-off OBD signal observed pre-shutdown) ↦ recorder is wired for FUTURE drive-end events but didn't catch THIS drive's actual end; subsequent boots don't retroactively process prior-boot unfinished drives
SUGGEST sprint41/V0.27.17 triage with atlas + ralph: deploy-context black-box "drive simulator" that exercises integrated orchestrator + DriveDetector + recorder against real DB; unit test mocking DriveDetector.onDriveEnd will NOT catch this class
==== filed deliverables ====
- pm/issues/2026-05-21-from-tester-v0.27.16-deploy-did-not-restart-powerwatch-or-daemon-reload.md (HIGH; deploy-hygiene)
- pm/issues/2026-05-21-from-tester-v0.27.16-us-348-us-349-false-pass-recurrence.md (HIGH; chain-blocking)
- tester/findings/2026-05-21-us-345-f8-fix-blocked-by-maxtrailbytes-guard.md (HIGH; non-chain-blocking)
- tester/test-reports/2026-05-21-v0.27.16-validation.md (full report)
==== argus-lane decisions ====
- /sprint-validated for Sprint 40: NOT RUNNING -- US-348+US-349 fail acceptance; US-346 pending your lane
- regression_manifest F-008/F-011/F-012: stays HELD -- Spool's preliminary HOLD on rested-pack drain + my US-348/349 fail = sprint41 redo + populated stats writer + real-drive round-trip = unblock trigger
- chain stays HELD per Mike 2026-05-08/10 chain-end-merge rule (main = fully validated stable)
==== what V0.27.16 DID earn ====
empirical validation that F-7 + F-8 are no longer reproducible in the integrated system (Sprint 39's chain-blocker findings resolved); 4 clean Cycle-A poweroff cycles today; sequencer behavior textbook on Test 1 + bench-unplug + Test 2; auto-boot via POWER_OFF_ON_HALT=1 works
==== pre-existing observations (not new; not blocking) ====
- powerwatch_outcome.json still NOT PRESENT post-sequencer-fire (same as Sprint 39; sync short-circuit on no-new-data US-332 guard; today even with real drive data still absent ↦ may need investigation but not chain-blocking)
- drive_summary sync chattiness post-Test2 (~20 push events / 5min in journal); possibly normal sweep cadence; possibly retry loop; future look
- eclipse-obd "PldSensor unavailable on GPIO6 ('GPIO busy')" boot warning -- orchestrator secondary reader; primary sequencer in eclipse-powerwatch reads GPIO6 fine; failsafe correctly defaults PRESENT
no deliverable owed in your lane until US-348/349 redo lands in V0.27.17; standing by
— argus
```

---

(End A2AL block. Plain text below for any skim-reader.)

Summary: V0.27.16 drill complete. F-7 + F-8 fixes validated in steady-state. **US-348 + US-349 false-pass — same pattern as V0.27.7's US-326/US-328**. Chain merge HELD; Sprint 40 `/sprint-validated` NOT running; manifest bump stays held. Sprint 41 needs another US-348/US-349 redo with a deploy-context test surface (synthetic seam mocks aren't catching this class). Pre-drill caught a deploy-hygiene gap (deploy didn't restart powerwatch or daemon-reload); filed separately, worked around with bench `daemon-reload && reboot`. US-345 boot-progress trail has a guard interaction worth fixing in V0.27.17 but it's not chain-blocking. Full evidence + analysis in `tester/test-reports/2026-05-21-v0.27.16-validation.md`. PM call on US-346 design-gate and what scope to give Sprint 41.

— Argus
