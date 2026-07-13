# US-464 shipped — TD-055 real-MariaDB migration-chain test + CI-enablement follow-up

**From:** Rex (Dev) · **To:** Marcus (PM) · **Date:** 2026-07-13 · **Sprint 57 / V0.29.11**
**re:** US-464 (TD-055 graduates to funded); companion to US-463 (BL-021)

## What landed

A real-MariaDB migration-chain test that applies the **real** server migrations
against a **real MariaDB 11.x** (NOT SQLite/create_all — precisely what shipped
BL-020 + BL-021 green). Two layers, mirroring US-462's proven pattern:

- **Hermetic (always-runs, in-loop gate):** `formatMysqlBatchOutput` (the
  `mysql -B -N` shape the migration parsers depend on), the
  `MariaDbCommandRunner` adapter over a fake DB-API connection (SELECT→batch
  stdout, DDL→empty, DB-error→returncode 1), the honest-skip acquisition, and
  the drifted-seed DDL shape. **16 tests, all pass in-loop.** Tests the ALARM,
  not a DB.
- **Live integration (`@pytest.mark.integration|slow`):** seeds the exact
  drifted historical shape on a real MariaDB and runs the real
  `v0022.apply` / `v0023.apply` / `MigrationRunner.runAll`, asserting the chain
  fixes the drift or fails loudly. Provably catches **both** classes:
  - **BL-020** — `drive_statistics.summary_id` state-3 (no FK) +
    `drive_derived_signals` state-1 (FK→legacy `drive_summary`) → v0022 repoints
    both onto `drives.drive_id`.
  - **BL-021** — 5 tables carrying the stale inline `data_source` CHECK →
    `data_source='foreign'` rejected pre-migration, accepted after v0023's
    MODIFY-COLUMN strip; 0 surviving CHECKs.
  - Plus a full `runAll` resume (0001-0021 seeded applied, 0022/0023 pending —
    the V0.29.10 shape) and a clean-schema no-op case (validationCriterion 2).

The crux is `MariaDbCommandRunner`: every migration issues SQL via
`ctx.runner(argv, input=<sql>)` and parses `mysql -B -N` output, so a single
adapter that pipes `input` into a live MariaDB and re-emits `-B -N`-shaped output
lets the **unmodified** real chain run against real DDL.

## Files

- `tests/server/_mariadb_chain_harness.py` (new — reusable harness: adapter,
  acquisition, seeders; underscore-prefixed so pytest doesn't collect it)
- `tests/server/test_migration_chain_real_mariadb.py` (new — hermetic + live)

## Honest skip in-loop (why, and the CI-enablement follow-up)

The dev bench has **no `testcontainers` and no Docker**. Per the AC's
`conditionalOutcome` ("deliver the test runnable locally against a MariaDB
service + document the CI-enablement follow-up; do NOT silently skip"), the live
layer **skips with a loud, explicit reason** naming both acquisition paths and
refusing the create_all substitute — it is NOT a silent skip and NOT a SQLite
fallback.

**CI-enablement follow-up (PM to schedule — this is the "do not silently skip"
documentation):**

1. Add `testcontainers` to a dev/CI requirements set (e.g. a new
   `requirements-dev.txt` or `requirements-server.txt` test extra). It is NOT a
   runtime dep — Pi/server production installs must not pull it.
2. Wire a Docker-enabled CI job (or a MariaDB **11.x** service container —
   Atlas TIGHTEN-2 pins the major to prod 11.8.6) that runs
   `pytest tests/server/test_migration_chain_real_mariadb.py -m integration`.
3. Alternatively / immediately: run locally by pointing
   `OBD2_MARIADB_TEST_DSN=mysql+pymysql://user:pass@host:3306/db` at a MariaDB
   11.x service — the live layer then executes and gates.

Until (2) lands, the live layer runs on demand via (3). **Recommend running (3)
against chi-srv-01's MariaDB (or a throwaway 11.x) as part of the US-463
deploy-gate** — the same drift the deploy proves, now reproducible on demand.

## TD-055 status

TD-055 is now **addressed by US-464** (Atlas: graduated to funded). The
`serverEngine` create_all-limitation caveat in
`tests/integration/test_deploy_context_drive_simulator.py` (which filed TD-055)
still stands for *that* harness, but the migration-chain drift class it deferred
is now covered here. PM: close/annotate TD-055 with this pointer at integration.
