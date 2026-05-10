# RESOLVED — drive_summary Pi snapshot columns NULL is historical, not a bug
**Date**: 2026-05-10 (filed + resolved same day)
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — INFORMATIONAL ONLY, no action needed

## Summary

Filed earlier today as a Sprint 28 P3 candidate ("Pi-side cranking-entry snapshot writer might be missing"). **Verified clean — no bug, no story needed.** Marcus, you can skip this in grooming.

## What I verified

**Source code**: `src/pi/obdii/drive_summary.py` lines 593-617. The `_insertNew` writer DOES populate all three snapshot columns (`ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start`) from the per-tick PID snapshot dict. INSERT statement is correct, UPDATE statement at line 633 is correct, backfill path at line 740 is correct.

**Pi-local SQLite verified**: I SSH'd to chi-eclipse-01 and queried `/home/mcornelison/Projects/Eclipse-01/data/obd.db` directly. Drive_summary table on the Pi has rows for drives 2, 3, 4, 5 only — all with NULL snapshot columns — and NO rows for drives 6, 7, 8, 9, 10. **Server mirror is accurate.** The NULLs are not a sync issue.

## Why drives 2-5 have NULLs

US-237 (Sprint 19, 2026-04-29) added these columns to the schema. Drive 5 was 2026-04-29 evening — same day as the migration. Drives 2-5 are pre-writer historical rows: the schema migration ran (creating columns as NULL), but those drives were captured before the writer was fully wired up. **Acceptable historical artifact.**

## Why drives 6-10 have no rows at all

Already covered by Spec 3 from yesterday's PM note — the analytics/Pi-side `drive_summary` writer regression. **When Ralph fixes Spec 3, new drives will automatically populate the snapshot columns** because the writer code path is correct.

## Optional one-shot backfill (P4 only — consider during Sprint 28+ cleanup)

If we want pretty data, a one-shot script could backfill the snapshot columns on drives 6-10 from `realtime_data` (find the first IAT / BATTERY_V / BAROMETRIC_KPA reading per drive, write to drive_summary). Pre-Sprint-19 drives 2-5 stay NULL since they're historical. **Not worth a Sprint 28 story** — wait until at least one fully clean post-fuse-box-wiring drive lands and we see whether the issue even surfaces in practice.

## Net Sprint 28 grooming impact

**Zero.** Drop this from your inbox.

— Spool
