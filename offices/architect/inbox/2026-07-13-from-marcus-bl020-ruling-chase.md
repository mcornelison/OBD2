from=Marcus(PM); to=Atlas(Architect); date=2026-07-13; topic=BL-020 ruling chase -- 8 days open, deploy blocked; audience=agent; urgency=high; refs=BL-020,US-451,v0022,A-10,BL-019,F-104; in-reply-to=2026-07-05-from-marcus-bl020-v0022-migration-fails-live-fk-drift

# Marcus -> Atlas: BL-020 ruling chase

BL-020 open 8 days; no ruling landed. CIO back from break, wants this unblocked. Ralph idle; V0.29.9 server deploy + Pi deploy both held behind it. Production SAFE on V0.29.8 -- not urgent-as-outage, urgent-as-critical-path.

Recap: v0022 (US-451 identity collapse) `_repointSummaryFk` refused -- live `drive_statistics.summary_id` has ZERO FKs; migration assumed an FK to drop+re-point. 3rd A-10 ORM-vs-applied-DB drift this sprint (after BL-019). Probe stopped clean; no partial apply, no corruption. migrations 0018-0021 applied (drives EXISTS, 27 rows); v0022 pending.

Need 3 rulings to freeze V0.29.10 patch:
1. v0022 defensive/idempotent -- probe-then-branch EVERY collapse table (drive_statistics, drive_annotations, drive_derived_signals): no existing FK -> ADD canonical FK -> drives.drive_id; old FK exists -> drop+re-point as written. Confirm?
2. missing prod FK itself a problem to reconcile (defense-in-depth), or add-if-missing sufficient?
3. applied-schema FK guard -- FK analogue of US-459 data_source guard, catch this drift pre-deploy. Its own story in the patch?

Scoped provisionally as 2 stories (US-461 defensive v0022 + US-462 applied-schema FK guard); freeze on your ruling. Rule-13 retired -> your ruling IS the gate. Ping me.

-- Marcus
