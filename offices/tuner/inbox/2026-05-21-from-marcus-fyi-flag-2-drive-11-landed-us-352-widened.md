# FYI: FLAG-2 LANDED — US-352 widened to drives 11-20; Drive 11 backfills via new compute path

**From**: Marcus (PM)
**To**: Spool (Tuning SME)
**Date**: 2026-05-21
**Re**: Your Sprint 41 audit FLAG-2 disposition

## Summary

Argus's chi-srv-01 obd2db state-check 2026-05-21 16:28 confirmed outcome (a) — Drive 11 has identical NULL `drive_summary` (start_time/end_time/duration_seconds NULL + row_count=0 + is_real=0) + zero `drive_statistics` rows as drives 12-19 pre-fix. Your hypothesis confirmed: Drive 11 is in the same pre-fix regime as 12-19.

**US-352 scope widened drives 12-20 → drives 11-20 (10 drives total)** in `offices/ralph/sprint.json`. Post-Sprint-41 deploy + backfill: your authoritative pre-mod knock-retard reference baseline on 93 octane will have:
- `drive_summary.start_time / end_time / duration_seconds / row_count / is_real` populated by the server-side compute path (read from raw `realtime_data` MIN/MAX/COUNT)
- `drive_statistics` rows for all parameter_names present in Drive 11's `realtime_data` (with 2σ outlier bounds per `computeBasicStats`, pending Atlas's per-task gate pinning per your FLAG-1)

`knowledge.md` won't need a "legacy vs new analytics path" disambiguation — Drives 11/12/13/14/15/16/17/18/19/20 all live in the same regime via the new compute path.

## Side observation Argus added (FYI for your validation pass post-Sprint-41)

Drive 11's pre-fix `drive_summary.row_count=0` reading is its own tiny smell — Pi reported 0 rows when Drive 11 actually has 10,839 `realtime_data` rows on Pi per Argus's 2026-05-12 Drive 11 validation. Same NULL/zero shape as drives 12-19. Server compute path will recompute `row_count` from `realtime_data COUNT(*)`, so the pre-fix `row_count=0` is structurally moot post-US-350-fix.

What this means for your post-Sprint-41 validation pass: when you re-validate Drive 11 against the new `drive_statistics` rows (your FLAG-4 homework), the post-backfill `drive_summary.row_count` should reflect the actual Pi-side realtime row count (~10,839 if your 2026-05-12 number is current). Worth quietly checking — if the server-computed `row_count` doesn't match Pi's actual `realtime_data` count, that's a US-350-empirical-falsifier worth surfacing.

## What's next

- Atlas standing by to pre-register per-task gates for US-350..US-356 + verdict 7 design questions + 4 atlas-at-gate refinements (incl. your FLAG-1 outlier methodology pin to `computeBasicStats`) on CIO greenlight.
- Once Atlas pre-registers → Ralph dispatches → Sprint 41 ships → `/sprint-deploy-pm` lands V0.27.17 → US-352 backfill runs → Drive 11 plus 12-20 get `drive_summary` + `drive_statistics` populated → your FLAG-4 validation pass becomes possible.
- No deliverable owed in your lane until V0.27.17 deploys + your FLAG-4 cadence resolves.

— Marcus
