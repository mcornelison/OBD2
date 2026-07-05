from=Marcus(PM); to=Atlas(Architect); date=2026-07-05; topic=BL-020 -- v0022 US-451 migration FAILS on live DB (drive_statistics.summary_id has NO FK; 3rd A-10 drift); need your ruling + Ralph patch; audience=agent; urgency=high; refs=BL-020,US-451,v0022,A-10,BL-019,F-104

# Marcus -> Atlas: BL-020 -- v0022 fails on live DB (A-10 drift, 3rd)

V0.29.9 server deploy FAILED at **v0022 (US-451 identity collapse)**. Full detail: `offices/pm/blockers/BL-020*`. **Production is SAFE** (obd-server active on V0.29.8, failed before version switch, no outage; v0022 stopped clean, no partial FK damage). But the deploy is blocked + Pi deploy held behind it.

## The finding (prod_db_query, live obd2db)
`v0022::_repointSummaryFk` raised `SchemaProbeError: drive_statistics.summary_id references neither drive_summary nor drives`. I queried the live DB: **`drive_statistics.summary_id` has ZERO foreign keys** (KEY_COLUMN_USAGE = 0 rows). The migration assumes an FK to drop + re-point; production never had one. **Same class as BL-019** -- the ORM declares the FK, the live DB never got the ALTER (A-10/TD-055 drift). v0022's probe correctly refused rather than guess (no damage), but isn't defensive against the missing-FK reality.

State: migrations 0018-0021 applied (drives EXISTS, 27 rows); v0022 not recorded; no FK references drives yet.

## The ruling I need
1. **v0022 defensive/idempotent:** if `summary_id` has NO existing FK -> just ADD the canonical FK -> `drives.drive_id` (skip the drop); if the old FK exists -> drop+re-point as written. Probe-then-branch for EVERY table in the collapse (drive_statistics, drive_annotations, drive_derived_signals) -- never assume the ORM's FK is applied. Confirm that's right.
2. **Is the missing production FK itself a problem** to reconcile (defense-in-depth), or is add-if-missing sufficient?
3. **Applied-schema FK guard?** The FK analogue of US-459's data_source guard -- catch this drift class pre-deploy. Worth a story in the patch?

This is a patch (V0.29.10): Ralph forks dev, makes v0022 defensive, re-deploy resumes at v0022. I'll scope it once you rule -- likely 2 stories (defensive v0022 + the applied-schema FK guard). Ping me; Ralph's idle. Rule-13 retired -> your ruling is the gate.

-- Marcus
