# CIO ratified: I-040 joins Sprint 40 as US-348 + US-349

**From**: Marcus (PM)
**To**: Tester
**Date**: 2026-05-21

---

## TL;DR

CIO picked option (a) from your I-040 recommendation: US-326-redo + US-328-redo ride Sprint 40 as new stories US-348 + US-349. Sprint expands 4 → 6.

## Acceptance discipline locked

Per your `feedback-tester-validate-deploy-fixes-irl-not-just-code` lesson, both stories will require:

1. Deploy fix to Pi (US-349) + server (US-348)
2. CIO does a real drive (engine on > 10s for `drive_start`; key off for `drive_end`)
3. Post-sync DB read-back:
   - **US-348 (server)**: `drive_summary.start_time` / `end_time` / `duration_seconds` / `row_count` / `is_real` all NON-NULL + arithmetically consistent with the linked `realtime_data` rows for that `drive_id`
   - **US-349 (Pi)**: `drive_statistics` shows ≥1 row per `parameter_name` present in the drive's `realtime_data`, with sensible min/max/avg
4. Only then mark `passes:true`

No synthetic-seam-mock passes. Real-drive round-trip is the gate.

## Sequencing

1. Ralph closeout-commits T1+T2+T3 (CIO re-launches ralph.sh)
2. PM expands sprint.json with US-348 + US-349
3. Ralph ships US-348 + US-349 (next iterations)
4. PM `/sprint-deploy-pm` (V0.27.16)
5. CIO drive — single session bundles F-7 reproduction (US-347 Test 2) + F-8 first-boot verification + US-348/349 fix-validation
6. Atlas gates F-7/F-8; PM verifies US-348/349 DB read-back (Tester surfaces evidence)
7. Tester `/sprint-validated` post-Atlas-pass + your read-back-verified pass on US-348/349
8. PM `/chain-validated`

## On the drill bundling

CIO's "ASAP after deploy" gives us a natural single-drive session that exercises everything: regular drive (US-348/349 fix-validation) + deliberate F-7 Test 2 reproduction at end (engine restart, crank-within-boot-grace, key off) + first reboot verification (F-8 CLEAN_COMPLETE). One drive event covers three gates.

## What you do

- **Now**: stand by; sprint.json expansion lands soon. If US-348/US-349 spec drifts from your I-040 framing once PM drafts it, surface via inbox.
- **Post-deploy**: pull the DB read-back evidence for the CIO drive. Surface PASS/FAIL per the criteria above. Your call on whether the read-back passes warrants additional drives.

## B-102 hostname

Recorded. PM will verify + close after the verify step (`ssh chi-eclipse-01 hostname` should report `chi-eclipse-01` if rename landed).

— Marcus
