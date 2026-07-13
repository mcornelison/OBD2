# BL-020: v0022 (US-451 identity collapse) migration FAILS on live DB — drive_statistics.summary_id has NO FK (3rd A-10 drift)

| Field | Value |
|---|---|
| Severity | High (blocks V0.29.9 server deploy) |
| Status | RESOLVED (deployed V0.29.11 2026-07-13) |
| Blocking | V0.29.9 server deploy (Pi deploy held behind it); drive-33 re-tag |
| Waiting On | ~~Atlas A-10 ruling~~ FILED 2026-07-13 → Ralph migration fix (patch V0.29.10) |
| Atlas ruling | `offices/architect/reports/2026-07-13-bl020-v0022-fk-repoint-defensive-ruling.md` (A2AL note in PM inbox 2026-07-13). Verdict: 3-state defensive `_repointSummaryFk` (drop+re-point / no-op / **ADD-only**), verified add-safe on prod (0 orphans, all `int(11)`); no BLOCK. Story1 = defensive v0022 (unblock); Story2 = applied-schema FK guard (TD-055 third leg). |
| Created | 2026-07-05 |
| Class | ORM-vs-applied-DB drift (A-10/TD-055) — 3rd occurrence this sprint (after BL-019) |

## What happened
`deploy-server.sh` applied spine migrations 0018→0021 (drives table created + 27 rows back-filled) then FAILED at **v0022_us451_drive_identity_collapse.py::_repointSummaryFk** (line 344):

```
SchemaProbeError: drive_statistics.summary_id references neither drive_summary nor drives;
the expected FK is missing. Investigate the MariaDB session context.
```

## Live-DB assessment (prod_db_query.sh)
- **Production SAFE:** obd-server active on **V0.29.8** (failed before version switch, no outage).
- **`drives` EXISTS, 27 rows** (v0018-21 back-fill applied).
- **`drive_statistics.summary_id` has ZERO foreign keys** — `KEY_COLUMN_USAGE` returns 0 rows. The migration assumes an FK to drop+re-point; none exists.
- **No partial v0022 apply** — 0 new FKs referencing `drives`; v0022 not in `schema_migrations` (last = 0021). Clean stop, no corruption.

## Root cause
Same class as BL-019: the ORM/model declares `drive_statistics.summary_id` FK → `drive_summary`, but the **live DB never had that FK ALTERed in** (drift). v0022 was written against the ORM's assumed schema, not the applied one. Its schema-probe correctly refused to guess (good — no silent damage), but it's not defensive against the missing-FK reality.

## The fix (Atlas ruling + Ralph patch V0.29.10)
- **Atlas:** confirm the approach + whether the missing production FK is itself a problem to reconcile. Likely: v0022 becomes **defensive/idempotent** — if `summary_id` has NO existing FK, just **ADD** the canonical FK → `drives.drive_id` (don't require a drop); if it has the old FK, drop+re-point as written. Same treatment for any other table in the collapse (drive_annotations, drive_derived_signals) — probe-then-branch, never assume.
- **Consider an applied-schema guard** for FKs (the FK analogue of US-459's data_source guard) so this drift class is caught pre-deploy, not at deploy.
- **Ralph:** implement in a patch (fork dev → fix v0022 → V0.29.10 → re-deploy). Re-deploy resumes at v0022 (0018-21 already applied).

## State to resume from
Server DB at migration 0021 (drives populated); v0022 pending. Pi deploy HELD (server must land first). dev = V0.29.9 (600b628) with the broken v0022.

## RESOLVED 2026-07-13
Fixed + deployed to production. V0.29.11 server deploy applied the migration on the real DB (chi-srv-01), obd-server active on V0.29.11 / 282c40a, health OK. v0022 applied cleanly (US-461 3-state defensive re-point). schema_migrations=0022 then chain continued.
