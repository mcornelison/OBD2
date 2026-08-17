# US-237 — drive_summary 3-way schema reconciliation SHIPPED

**From:** Rex (Ralph Agent 1)
**To:** Marcus (PM) + Spool (Tuner SME)
**Date:** 2026-04-29
**Re:** Sprint 19 US-237 closes V-1 + V-4 from the 2026-04-29 Drive 4 health check

## TL;DR

- **Migration v0004** registered in `src/server/migrations/__init__.py::ALL_MIGRATIONS`.  Idempotent, INFORMATION_SCHEMA-probed, post-condition-verified.
- **11 missing columns** ALTERed onto live `drive_summary`: `source_id`, `source_device`, `synced_at`, `sync_batch_id`, `drive_id`, `drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start`, `is_real`, `data_source`.
- **`IX_drive_summary_drive_id` + `uq_drive_summary_source` UNIQUE(source_device, source_id)** added so the Pi-sync upsert handler resolves on the Pi-sync natural key.
- **9 legacy sim rows truncated** (V-4) along with cascade `drive_statistics` children.  Sim device_ids: `sim-eclipse-gst`, `sim-eclipse-gst-multi`, `eclipse-gst-day1`.  Real-data rows preserved.
- **32 new tests** (25 migration unit + 7 sync round-trip).  All pass; full fast suite green.
- **Schema-only fix** — drive_summary data values for drives 3, 4, 5 stay NULL until US-236 lands defer-INSERT (per story scope clarification by Marcus).

## What deploys next

Marcus + CIO need to run `bash deploy/deploy-server.sh` (or `python scripts/apply_server_migrations.py --run-all`) on chi-srv-01 with the merged code.  Expected output:

    [run-all] 1 applied, 3 already applied
      applied: 0004

After the deploy:

    ssh mcornelison@10.27.27.10 'mysql obd2db -e \
      "SELECT version, description, applied_at FROM schema_migrations ORDER BY version"'

Should show 0001-0004 with the 0004 timestamp matching the deploy time.

## Pre/post-deploy verification queries

**Before re-running sync** (operator or PM): assert the 9 sim rows still exist and their drive_statistics FK rows still exist:

    SELECT id, device_id FROM drive_summary
    WHERE device_id IN ('sim-eclipse-gst','sim-eclipse-gst-multi','eclipse-gst-day1');
    -- expect 9 rows with auto-increment ids 1-10 (per Ralph Drive 4 health check)

    SELECT COUNT(*) FROM drive_statistics WHERE drive_id IN
      (SELECT id FROM drive_summary
        WHERE device_id IN ('sim-eclipse-gst','sim-eclipse-gst-multi','eclipse-gst-day1'));
    -- expect non-zero (depends on prior analytics run on 2026-04-16)

**After deploy + a Pi-side `sync_now`** (or auto-sync): assert the 148 silent failures stop and Pi-shape rows land:

    SELECT status, COUNT(*) FROM sync_history GROUP BY status;
    -- expect "completed" count to start increasing; "failed" count flat

    SELECT source_device, source_id, drive_id, ambient_temp_at_start_c,
           starting_battery_v, barometric_kpa_at_start
    FROM drive_summary
    WHERE source_device='chi-eclipse-01'
    ORDER BY source_id;
    -- expect rows for source_id=2,3,4,5 (the rows Pi has been retrying since
    --   Sprint 18 deploy); ambient/battery/baro stay NULL until US-236 deploys

    SELECT COUNT(*) FROM drive_summary
    WHERE device_id IN ('sim-eclipse-gst','sim-eclipse-gst-multi','eclipse-gst-day1');
    -- expect 0 (V-4 truncate landed)

## Synthetic-test fidelity (per `feedback_runtime_validation_required`)

The strong-test discriminator is **`test_staleShapeFailsWithUnknownColumnError`** in `tests/server/test_drive_summary_sync_post_reconcile.py`.  It builds a SQLite drive_summary with the exact Sprint 7-8 column list (no source_id / source_device) and asserts that `runSyncUpsert` fails with the same `Unknown column` error class that produced 148 production failures.  A pre-US-237 codebase passes this test trivially because the bug class is still present; a post-US-237 codebase that *reverses* the migration would also fail it; a post-US-237 codebase that *correctly* migrates also makes the partner test `test_freshOrmDbAcceptsSourceIdQueryDirectly` pass.  Together the pair locks the bug class.

Migration-level tests use the same `FakeRunner` SQL-capture pattern as `tests/server/test_migrations.py`, with a per-call counter so the post-condition column probe sees the post-ALTER shape (production parity).

## Known schema-misalignment (note to Spool, not blocker)

- **Pre-US-237 rows** in `drive_summary` (the 4 analytics-only rows from Sprint 7-8 era that were NOT in the sim list) have NULL `source_id` / `source_device`.  SQL's NULL-distinct UNIQUE semantics keeps them legal.  `_PRESERVE_ON_UPDATE` keeps them untouched on Pi sync.  This matches the US-214 dual-writer reconciliation contract.
- **Pi-sync rows post-deploy** will have `source_device='chi-eclipse-01'` + `source_id IN (2,3,4,5)` initially.  As US-236 ships defer-INSERT, future drives will land with metadata populated; older drives stay all-NULL (acceptable per Spool's grooming -- the focus is going-forward correctness).
- **drive_statistics regeneration** is a *separate* story (V-7 in the original variance report; not in Sprint 19).  Until analytics re-runs against real drive_ids, drive_statistics is empty post-truncate.

## Files changed

Production (2):
- Created: `src/server/migrations/versions/v0004_us237_drive_summary_reconcile.py` (190 lines including module docstring + idempotent apply + 11 column constants)
- Modified: `src/server/migrations/__init__.py` (registered v0004 in ALL_MIGRATIONS)

Tests (2 new):
- Created: `tests/server/test_migration_0004_drive_summary_reconcile.py` (25 tests covering: module exports, fresh-DB short-circuit, stale-DB ALTER emission, idempotent re-run, failure modes, post-condition probes, production-failure-mode discriminator)
- Created: `tests/server/test_drive_summary_sync_post_reconcile.py` (7 tests covering: stale-shape bug reproduction, Drive 4 warm-idle round-trip, drives 3/4/5 all-NULL round-trip, second-push UPSERT, analytics-writer preservation, ORM column contract, fresh-DB source_id query)

Specs (1):
- Modified: `specs/architecture.md` (Section 5 drive_summary "Server mirror" paragraph + Server Schema Migrations registry table + Modification History entry)

Sprint artifacts (3 -- to be updated next):
- `offices/ralph/sprint.json` (US-237 passes:true + completionNotes + filesActuallyTouched)
- `offices/ralph/ralph_agents.json` (Rex unassigned + Session close note)
- `offices/ralph/progress.txt` (this entry)

## Verification snapshot

| Command | Result |
|---------|--------|
| `pytest tests/server/test_migration_0004_drive_summary_reconcile.py tests/server/test_drive_summary_sync_post_reconcile.py -v` | 32 passed |
| `pytest tests/server/test_migration_0004_drive_summary_reconcile.py tests/server/test_drive_summary_sync_post_reconcile.py tests/server/test_migrations.py tests/server/test_drive_summary_sync.py tests/server/test_drive_summary_reconciliation.py tests/scripts/test_apply_server_migrations.py -v` | 134 passed |
| `pytest tests/ -m 'not slow' -q` | 3411 passed (was 3379 baseline post-US-236; +32 net new) |
| `ruff check src/server/migrations/versions/v0004_us237_drive_summary_reconcile.py src/server/migrations/__init__.py tests/server/test_migration_0004_drive_summary_reconcile.py tests/server/test_drive_summary_sync_post_reconcile.py` | All checks passed |
| `python validate_config.py` | All validations passed |
| `python offices/pm/scripts/sprint_lint.py` | 0 errors / 24 pre-existing warnings (US-237 introduced none) |

Sprint 19 status: 4/8 SHIPPED (US-234, US-235, US-236, US-237).  4 remain pending: US-238 (P0, V-2 dtc_log), US-239/240/241 (P1).
