# Session 23 Data Cleanup — Truncate + Reset drive_counter (supersedes backfill decision)

**Date**: 2026-04-20
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine

## Context

Ralph's US-200 inbox question asked Spool to arbitrate the Session 23 drive_id backfill disposition (one drive / two drives / leave NULL). CIO reviewed the three options and chose **a fourth path**: truncate Session 23's operational rows from Pi SQLite + server MariaDB, rather than backfill.

CIO's rationale (paraphrased):
> *"The system is functioning now. Session 23's 149 rows were first-light test data to prove the pipeline end-to-end — not data we need to preserve in operational stores. The regression fixture already captured the raw bytes for future tests. Clean slate for real data beats an awkward NULL-drive_id island."*

This decision supersedes US-200 Invariant #4 ("Session 23's 149 rows stay NULL; Spool arbitrates disposition"). The arbitration outcome is now: **truncate, not backfill**.

## What gets truncated

**Scope filter**: `data_source = 'real'` — real-vehicle-captured rows only. Any rows with `data_source IN ('replay','physics_sim','fixture')` stay untouched (development test rows, if any, are orthogonal to this cleanup).

### Pi side — `chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db`

| Table | Action | Expected row count |
|-------|--------|--------------------|
| `realtime_data` | DELETE WHERE data_source = 'real' | 149 (all Session 23) |
| `connection_log` | DELETE WHERE data_source = 'real' | 16 (5 failed BT + 2 success windows + drive events) |
| `statistics` | DELETE WHERE data_source = 'real' | 11 |
| `alert_log` | DELETE WHERE data_source = 'real' | unknown — any alert rows from Session 23 |
| `drive_counter` | UPDATE last_drive_id = 0 | 1 row reset |

### Server side — `chi-srv-01` MariaDB `obd2db`

| Table | Action | Notes |
|-------|--------|-------|
| `realtime_data` | DELETE WHERE data_source = 'real' | mirror of Pi-side 149 rows |
| `connection_log` | DELETE WHERE data_source = 'real' | mirror of Pi-side |
| `statistics` | DELETE WHERE data_source = 'real' | mirror of Pi-side |
| `alert_log` | DELETE WHERE data_source = 'real' | mirror of Pi-side |
| `drive_counter` | UPDATE last_drive_id = 0 (if server has one) | Ralph verifies |

## Pre-truncate orphan scan (REQUIRED before DELETE)

Before dropping the source rows, verify no downstream tables hold FKs or derived data from Session 23. Two specific checks on the server side:

1. **`ai_recommendations`** — the server's auto-analysis pipeline (Sprint 9 / B-036) may have run against Session 23's 23-second warm-idle slice and produced recommendations. Likely output is "insufficient data" (11 stat rows is below any useful threshold), but verify before truncating source data.

   ```sql
   -- Scan query (server side)
   SELECT id, drive_id, drive_start, recommendation_json
   FROM ai_recommendations
   WHERE drive_start BETWEEN '2026-04-19 07:18:50' AND '2026-04-19 07:20:41';
   ```

   If rows exist: delete them alongside source rows (same migration). They were generated from data we're removing, so they have no grounding anymore.

2. **`calibration_sessions`** — spec describes this as "manual management" but check if Session 23 seeded any baseline rows.

   ```sql
   SELECT id, session_start, session_end, source_drive_id
   FROM calibration_sessions
   WHERE session_start BETWEEN '2026-04-19 07:18:50' AND '2026-04-19 07:20:41';
   ```

   If rows exist: Ralph decides whether to delete or null out the source reference, based on whether the calibration values derived from Session 23 were ever promoted into production thresholds. My guess: they weren't (too little data), so delete is fine.

Any other tables that reference `drive_id` or derive from `realtime_data` should also get scanned. Ralph knows the schema better than me — flag for him to walk the FK graph once before executing.

## What is NOT affected (preserved regardless)

1. **`data/regression/pi-inputs/eclipse_idle.db`** — Session 23 regression fixture (shipped by US-197). **Standalone SQLite file, not an operational DB.** The truncate does NOT touch this. Raw bytes preserved for future regression runs.
2. **`specs/grounded-knowledge.md`** — "Real Vehicle Data" section with Session 23 warm-idle fingerprint.
3. **`specs/obd2-research.md`** — empirical PID support columns.
4. **`offices/tuner/knowledge.md`** — "This Car's Empirical Baseline" section.
5. **`offices/tuner/sessions.md`** — Session 23 narrative.

All the durable value of Session 23 lives in those five places. The operational DB rows were the most disposable part — proof-of-pipeline, job done.

## Suggested acceptance criteria (for Marcus to shape into story form)

1. Orphan scan runs first on both Pi and server. Any `ai_recommendations` / `calibration_sessions` / other-dependent rows are enumerated before DELETE executes.
2. DELETE statements on Pi and server use `WHERE data_source = 'real'` filter. No other data_source values affected.
3. `drive_counter.last_drive_id` is reset to 0 on both Pi and server.
4. Verification query after truncate: `SELECT COUNT(*) FROM realtime_data WHERE data_source = 'real'` returns 0 on both Pi and server. Same for other affected tables.
5. Regression fixture file `data/regression/pi-inputs/eclipse_idle.db` is untouched — verify file hash before and after.
6. Next real drive after truncation mints `drive_id = 1` (confirms counter reset worked).
7. `specs/architecture.md` §5 Drive Lifecycle updated: invariant #4 ("no retroactive backfill") replaced with a note that Session 23 was truncated per CIO directive 2026-04-20, and that the clean-slate operational state is the current baseline.
8. Ralph's closeout note to Spool's inbox confirms the truncation and any orphan cleanup he performed.

## Size / priority guidance (your call)

I'd guess S-size (mostly SQL + verify), no safety or tuning risk — purely operational hygiene. Priority: whenever Ralph has cycles before the next live-drive drill. Getting this done before the next real drive means first real drive = `drive_id = 1` cleanly, which is nice for the historical record.

## Why this matters (tuning-lens summary)

Session 23 proved the pipeline. It did NOT prove engine health at a useful confidence level — 23 seconds of warm idle is a fingerprint, not a baseline. The durable value of Session 23 already lives in specs/ and knowledge.md. Keeping the row-level data in operational stores with NULL drive_ids would be a permanent small mess; truncating it gives us a cleaner foundation for the first real multi-minute drill (which is the capture that will actually give us tuning-useful data).

After truncate + next drill: `drive_id = 1` will be a real drive, captured with the full US-199/200/202/203 toolchain (6 new PIDs + ELM_VOLTAGE + canonical timestamps + drive-scoped analytics). That's the data worth keeping.

## Sources

- Ralph's original question: `offices/tuner/inbox/2026-04-19-from-ralph-us200-session23-backfill-question.md`
- Session 23 fixture: `data/regression/pi-inputs/eclipse_idle.db` (149 rows, 2 BT windows, warm-idle snapshot)
- US-200 state machine spec: `specs/architecture.md` §5 Drive Lifecycle
- CIO directive: 2026-04-20 PM+tuner conversation (via `/init-tuner` session)

— Spool
