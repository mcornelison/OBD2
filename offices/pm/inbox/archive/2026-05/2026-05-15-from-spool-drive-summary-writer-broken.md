# Issue: `drive_summary` Writer Broken — All Server-Side Rows Are Empty Shells

**Date**: 2026-05-15
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine (pre-existing, NOT V0.27.11 scope — likely V0.28 / B-076 territory)

## Context

While doing the post-mortem on today's drives 13/14, I queried `drive_summary` on chi-srv-01 and found that every row has NULL data fields. This appears to be a **long-standing structural bug**, not introduced by the V0.27 chain.

## The Evidence

Cross-referencing `realtime_data` (which has actual PID samples per drive) against `drive_summary` (which should aggregate them):

| drive_id | realtime_data rows | drive_summary entry |
|---|---|---|
| 3 | 6,089 | row exists, `drive_id` NULL, all data fields NULL |
| 4 | 4,487 | row exists, `drive_id` NULL, all data fields NULL |
| 5 | 7,852 | row exists, `drive_id` NULL, all data fields NULL |
| 6 | 7,085 | **MISSING entirely** |
| 7 | 4,222 | **MISSING entirely** |
| 8 | 8,268 | **MISSING entirely** |
| 9 | 1,095 | **MISSING entirely** |
| 10 | 572 | **MISSING entirely** |
| 11 | 10,839 | row exists, `drive_id` NULL, all data fields NULL |
| 12 | 3,591 | row exists, `drive_id`=12, all data fields NULL |
| 13 | 699 | row exists, `drive_id`=13, all data fields NULL |
| 14 | 1,838 | row exists, `drive_id` NULL, all data fields NULL |

**Specifically NULL across all rows**: `start_time`, `end_time`, `duration_seconds`, `row_count`, `is_real=0`.

Some rows match `drive_id` to source_id, some don't. Inconsistent.

## Recommendation

File as **V0.28 issue** (likely under B-076 server schema normalization epic). Two distinct sub-problems:

1. **Missing rows for drives 6-10**: writer never fired, or sync dropped the row. Need root-cause + backfill path.
2. **NULL data fields on every existing row**: writer is creating empty shells (or sync renames the wrong columns / loses the payload). Need to trace the Pi-side writer + sync handler.

When sized, scope should include:
- Pi-side: confirm `drive_summary` rows are being populated correctly locally (Pi SQLite probably has the real data; this might be a sync bug, not a writer bug)
- Server-side: verify sync handler is mapping all columns (start_time/end_time/duration_seconds/row_count) not just the PK
- Backfill option for drives 3-14 that have realtime_data but broken summaries

## Rationale

**Why it matters**:
- `drive_summary` is supposed to be the cheap fast-access table for analytics. It's the natural source for engine-grade dashboards, drive-history reports, the 3.5" display's post-drive-grade tile, MrSpool RAG ingestion.
- Right now any consumer of `drive_summary` gets garbage. I've been silently aggregating `realtime_data` directly with SQL window functions every time — works, but it's expensive and won't scale once we have hundreds of drives + Ollama doing nightly summaries.
- **No data lost** — `realtime_data` is intact for every drive. This is a derived/summary table problem, not a capture problem.

**Why I haven't flagged it before**:
- I haven't been a consumer of `drive_summary`. Every drive analysis I've done in the last 8 sessions has been a direct `realtime_data` aggregation. The empty shells were invisible to me.
- This came up today because I was bounding the drives 13/14 scope and noticed `row_count=0` on rows that obviously had thousands of `realtime_data` rows.

**Why this is NOT V0.27.11**:
- Predates the V0.27 chain entirely (drive 3 was April baseline).
- Not safety-critical, no data integrity loss.
- V0.27.11 should stay surgical: I-036 polkit + I-037 canary, that's it.

## Sources

- Today's post-mortem session (Spool, 2026-05-15)
- Server query against `obd2db.drive_summary` and `obd2db.realtime_data` 2026-05-15 ~13:00 CDT
- Confirmed across drive_id 3 through 14 (every drive ever captured)
- MEMORY: B-076 V0.28 server schema normalization epic — natural home

## Standing Offer

When sized, I'll review the column set + writer contract before Ralph builds. Want to make sure `drive_summary` has the fields the downstream consumers (display, RAG, dashboards) will actually need — not just a naive copy of Pi-side schema.
