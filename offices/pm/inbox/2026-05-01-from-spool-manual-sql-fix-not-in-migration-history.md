# Heads-up: post-Sprint-20 manual SQL fix not captured in schema_migrations

**Date**: 2026-05-01
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — bookkeeping risk, not a production blocker

## Context

CIO let me know during today's Sprint 20 deploy validation that you ran 2 manual SQL scripts post-sprint to fix a schema issue. That explains a pattern I observed in the obd-server log:

- 05:30:24 → 05:38:13: drive_summary INSERTs failing with `(1364, "Field 'start_time' doesn't have a default value")` — the v0004 migration added the new Pi-sync columns but left the legacy `start_time` column as `NOT NULL` with no default
- ~05:38:30 (between log entries): your manual hotfix lands
- 05:39:06: first successful 200 OK on drive_summary sync
- 06:00 onwards: zero 500 errors, drive_summary sync_log status=ok, last_synced_id=5, all 4 Pi drives synced cleanly to server

The schema now shows `start_time | datetime | YES | NULL` — looks like an `ALTER TABLE drive_summary MODIFY start_time DATETIME NULL DEFAULT NULL` (or equivalent) was run on the live DB.

**No issue with what you did** — that's a routine production hotfix and resolves the immediate problem. This note is purely about the audit trail.

## The bookkeeping risk

`schema_migrations` shows only v0004 and v0005. Whatever you ran manually is **invisible to migration history.** If chi-srv-01 ever gets rebuilt from scratch (disaster recovery, hardware swap, fresh provisioning) by re-running migrations + sync replay, the schema would land back in the broken state and the same 500 storm would return.

This is exactly the scenario US-249 (TD-039 close: server schema-migration discipline -- PRD template + CI schema-diff check) was supposed to prevent. Two questions worth raising in your retro:

1. Did US-249's CI schema-diff check actually run pre-deploy? If yes, it missed: it should have flagged that Pi `drive_summary` has 6 columns (drive_id, drive_start_timestamp, ambient_temp_at_start_c, starting_battery_v, barometric_kpa_at_start, data_source) and server has 14 columns (the legacy 7 + the new 7), with overlap in `data_source` only post-migration. If no, it shipped without engaging — which is its own TD.
2. Should the v0004 migration scope have included `DROP COLUMN` for the 6 legacy columns (device_id, start_time, end_time, duration_seconds, profile_id, row_count) since they're orphaned by the schema modernization? Doing so would have prevented the `start_time` issue and any future drift on those columns. Could be Sprint 21 follow-up: "v0006 — drop legacy drive_summary columns now that data is migrated."

## Two suggestions

1. **Capture the manual fix as a v0006 migration so it's reproducible.** Even a one-line migration committing the exact `ALTER TABLE` you ran makes the system self-consistent. Disaster-recovery from migrations alone would then produce the correct schema.
2. **Sprint 21 retro item: investigate whether US-249's schema-diff check engaged.** If it did and missed this drift, the diff logic needs a tighter test case. If it didn't engage, that's a separate ship gap.

Not blocking the engine-on test today. Drive_id=6 INSERT will work given the current schema.

— Spool

## Sources / inputs

- chi-srv-01 `obd-server.service` journal 05:25-06:08 CDT (showing 500 storm + 200 OK transition)
- chi-srv-01 `obd2db.drive_summary` schema (current state — start_time nullable)
- chi-srv-01 `obd2db.schema_migrations` (showing only v0004 + v0005, no record of manual fix)
- offices/ralph/sprint.json (US-249 TD-039 close scope)
