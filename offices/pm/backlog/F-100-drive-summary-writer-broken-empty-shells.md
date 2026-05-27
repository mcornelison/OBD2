---
id: F-100
parent: E-002
status: pending
renamedFrom: B-100
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-100: `drive_summary` writer broken — every server row is an empty shell + drives 6-10 missing entirely

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (V0.28+ candidate; data-quality, NOT data-loss — `realtime_data` intact for every drive) |
| Status       | Pending (V0.28+ candidate) |
| Category     | server / sync / data-quality / analytics |
| Size         | M (likely; trace Pi-side writer + sync handler + backfill path — could grow if it's a sync-mapping rework) |
| Related PRD  | None |
| Dependencies | B-076 (server schema normalization epic — `drive_summary`→`drives` rename + "re-derive Drive-11 row post-US-326" + ghost-row cleanup overlap this); V0.27.7 US-326 (`_ensureDriveSummary` source_id lookup fix — may be partial); B-089 (Spool engine grade per drive — primary downstream consumer); B-094 (MrSpool RAG — ingestion consumer) |
| Created      | 2026-05-15    |

## Description

Spool's 2026-05-15 post-mortem on drives 13/14 found **every `drive_summary` row on chi-srv-01 has NULL data fields** (`start_time`, `end_time`, `duration_seconds`, `row_count`, `is_real=0`), and **drives 6-10 have no `drive_summary` row at all** despite having thousands of `realtime_data` rows each. This is a **long-standing structural bug predating the V0.27 chain** (drive 3 was the April baseline), surfaced now only because Spool became a `drive_summary` consumer for the first time (prior 8 sessions of analysis aggregated `realtime_data` directly with SQL window functions, so the empty shells were invisible).

Two distinct sub-problems:

1. **Missing rows for drives 6-10**: writer never fired, or sync dropped the row. Needs root-cause + backfill.
2. **NULL data fields on every existing row** (drives 3,4,5,11,12,13,14): writer is creating empty shells, OR sync renames the wrong columns / loses the payload. Needs Pi-side-writer + sync-handler trace.

`drive_id` mapping is also inconsistent across rows (some match source_id, some NULL, drive 12/13 have `drive_id` populated).

## Acceptance Criteria

- [ ] Root cause identified for BOTH sub-problems (missing rows 6-10 + NULL fields on existing rows) — Pi-side writer vs sync-handler vs schema-mapping
- [ ] Pi-side `drive_summary` SQLite rows confirmed populated correctly locally (likely a sync bug, not a writer bug — verify which)
- [ ] Server sync handler maps ALL columns (`start_time`/`end_time`/`duration_seconds`/`row_count`/`is_real`), not just the PK
- [ ] Backfill path for drives 3-14 that have `realtime_data` but broken/missing summaries
- [ ] Going-forward: a new drive produces a complete, non-NULL `drive_summary` (→ `drives`) row server-side, verified on the next IRL drive

## Validation Script Requirements

- **Input**: a completed drive synced Pi→server
- **Expected Output**: server-side summary row with non-NULL `start_time`/`end_time`/`duration_seconds`/`row_count` and correct `drive_id`
- **Database State**: `SELECT * FROM drive_summary` (or `drives` post-B-076) has one populated row per `realtime_data` drive_id, no empty shells, no missing drives
- **Test Program**: cross-reference script — for each distinct `realtime_data.drive_id`, assert a matching summary row exists with `row_count` ≈ the actual `realtime_data` count and non-NULL timestamps

## Notes

- Spool note: `offices/pm/inbox/2026-05-15-from-spool-drive-summary-writer-broken.md` (2026-05-15)
- Spool explicitly scoped this OUT of V0.27.11 (predates the chain, not safety-critical, no data loss — `realtime_data` intact). Bug-fix-only sprint policy held.
- **Strong B-076 overlap**: that epic already lists "re-derive the Drive-11 row once the analytics writer is correct (post-US-326)" + "remove 3 ghost `drive_summary` rows" + `drive_summary`→`drives` rename. Decide at V0.28 grooming whether B-100 is the *fix that must precede* the B-076 rename, or a folded sub-item. PM lean: B-100's writer/sync correctness should land BEFORE or WITH the B-076 rename — renaming a broken table doesn't fix it.
- Possible V0.27.7 US-326 relationship: US-326 fixed `_ensureDriveSummary` lookup-by-`drive_id`→lookup-by-`source_id` (IntegrityError → silent rollback). That fix may have been partial — the NULL-fields symptom suggests the row is created (no rollback) but the analytics payload isn't written/mapped. Worth checking whether US-326 closed the IntegrityError but left an empty-shell write path.
- Spool standing offer: will review the column set + writer contract before Ralph builds (wants the fields downstream consumers — display, RAG, dashboards — actually need, not a naive Pi-schema copy).

## Source

Spool 2026-05-15 post-mortem session; server query against `obd2db.drive_summary` + `obd2db.realtime_data` ~13:00 CDT; confirmed across drive_id 3-14.
