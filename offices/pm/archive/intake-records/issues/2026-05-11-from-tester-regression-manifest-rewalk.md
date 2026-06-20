# Regression manifest re-walk (F-001…F-014) — 4 recommended edits

**Date**: 2026-05-11
**From**: Tester agent
**To**: Marcus (PM)
**Priority**: Low — manifest accuracy / freshness; no feature is broken that wasn't already known.

Full report: `offices/tester/test-reports/2026-05-11-regression-manifest-rewalk.md`. `pm_regression_status.py` today reports 10 OK / 0 STALE / 4 NEVER (F-005, F-007, F-013, F-014). Walked all 14 features against live Pi/server + DB evidence this session.

## Bottom line
- Manifest is broadly accurate. **F-005 stays REGRESSED** — confirmed live: Pi `drive_summary` has rows for drives 2-5 only; 6-10 still missing; the V0.27.2/V0.27.3 fixes are deployed but never exercised by a real `drive_end`. Drive 11 is the test; if it fails, that's a V0.27.7 bug-fix sprint.
- **3 power-management features are under-rated** — they have fresher real evidence than the manifest records (Drain Test 16 on 2026-05-10, not Drain 8 on 2026-05-08). Drain Tests 11-16 all post-date the recorded evidence; Pi `power_log` + `battery_health_log` + `startup_log` corroborate the full ladder→poweroff→clean-reboot chain on the recent drains.
- **F-007** is fine as a *mechanism* (the Pi pushed a `connection_log` delta to the server during this session; `battery_health_log` row 16 closed on the server via the US-315 UPDATE-sync; the dual-cursor is populated) — but the manifest's preferred validation (a fresh post-V0.27.4 drive round-trip + the drive_summary-metadata/drive_counter UPDATE fixes on a real drive) is still outstanding, and is partly blocked upstream by F-005 (no drive_summary row exists to sync). Recommend leaving `lastValidated` null but refreshing the wording so it stops reading like the sync pipeline is dead.

## Recommended edits to `regression_manifest.json`

| Feature | Change |
|---|---|
| F-008 | `lastValidated` 2026-05-08 → **2026-05-10**; `validatedBy` → "Drain Test 16 (2026-05-10): full VCELL ladder stage_warning@3.696V → stage_imminent@3.541V → stage_trigger@3.44V → graceful poweroff → prior_boot_clean=1 on reboot" |
| F-011 | `lastValidated` 2026-05-08 → **2026-05-10**; `validatedBy` → "Drain Test 16 (2026-05-10): exactly one stage_warning/imminent/trigger per drain, monotonic; no flapping across drains 13-16 (power_log event counts 16/14/12)" |
| F-012 | `lastValidated` 2026-05-08 → **2026-05-10**; `validatedBy` → "Drain Test 16 (2026-05-10): battery_health_log row 16 closed start_vcell 3.889V / end_vcell 3.44V / runtime 811s; rows 11-16 all closed with end_timestamp non-NULL (V0.27.2 drain-close fix)" |
| F-007 | `lastValidated` stays **null**; `validatedBy` → "Sync delta-push MECHANISM confirmed working live 2026-05-11 (Pi pushed connection_log delta to chi-srv-01 16:06:07Z; battery_health_log row 16 closed on server via US-315 UPDATE-sync; dual-cursor populated). NOT YET validated: a fresh post-V0.27.4 drive's data round-trip + drive_summary-metadata/drive_counter UPDATE-sync (US-314/US-315) on a real drive — gated on Drive 11, itself gated on F-005." |
| F-001 | *optional*: `lastValidated` 2026-05-08 → 2026-05-11; `validatedBy` → "observed eclipse-obd.service active running V0.27.5 (bb744d1), uptime 3h+, startup_log fresh row prior_boot_clean=1" |

No other changes. F-002/F-003/F-004/F-006/F-009/F-010 stay OK (3 days old, not stale, re-confirmed on Drive 11). F-013/F-014 stay synthetic-only (gated on B-066 — recommend scheduling B-066 alongside/soon after B-063, since post-fuse-box every key-on becomes a Pi power-on and the B-047 power-on update trigger will fire on every car start).

## One non-manifest observation
Pi `power_log` shows power-source flicker (`transition_to_ac`/`transition_to_battery`) at ~70/day on 2026-05-10 and ~23 already on 2026-05-11, vs ~10-15/day on calmer days — i.e. **B-063 is still active** ("fix is imminent" = not done). Not a manifest item, but it's the gate on F-005's re-validation and the V0.27 chain merge.
