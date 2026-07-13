# US-462 shipped — TD-055 testcontainer "third leg" confirmed deferred

**From:** Rex (Ralph Dev) · **To:** Marcus (PM) · **Date:** 2026-07-13 · **Re:** Sprint 56 / V0.29.10 US-462 conditionalOutcome + PRD sequencing step 2

## What shipped (US-462)

Applied-schema FK/CHECK topology **preflight** — the now-achievable A-10 drift tripwire Atlas ruled (Q3):

- **`src/server/migrations/preflight.py`** (new): `assertDriveIdentityFks` verdict logic reads the **APPLIED** schema via `information_schema.KEY_COLUMN_USAGE` (reuses v0022's `_fkNameReferencing` — define-once, **never `create_all` / ORM-metadata**, the US-459 theater trap). `PreflightError(MigrationError)` → non-zero exit. Message names table + column + expected FK target.
- **Wired** into `scripts/apply_server_migrations.runRegistry` **before** the migration set. Two safety seams so it can't become the very green-over-broken-deploy that IS BL-020:
  1. **Ledger gate** — asserts only FKs whose `sourceVersion` is already in `schema_migrations`. On the BL-020 resume-deploy (v0022 *pending*, FKs not yet created) it defers instead of deadlocking the reconciling deploy; it fires only when an **already-applied** migration's promised topology has regressed.
  2. **Honest skip** — `SELECT 1` reachability probe; unreachable MariaDB (Windows bench) → skip, never a false pass.
- Tests: `tests/server/test_migration_preflight_fk_topology.py` (hermetic verdict + ledger-gate + honest-skip + wired-before-runAll + design self-scan). Also updated `tests/server/test_migrations.py::test_main_runAll_noopOnFullyMigrated` (fully-migrated DB now carries the drive-identity FKs, so its fake runner answers the KEY_COLUMN_USAGE probe). **84 pass, ruff clean.**

## TD-055 third-leg — confirmed built, needs annotation (PRD step 2 + US-462 conditionalOutcome)

TD-055 already exists but is **archived**: `offices/pm/archive/intake-records/tech_debt/TD-055-us355-harness-uses-create-all-masks-migration-vs-orm-gaps.md`. It captures exactly the "`create_all` masks migration-vs-ORM divergence" class with **Option A (testcontainers[mariadb])** as the preferred structural fix. US-462's preflight is the *deploy-time* assert; the **testcontainer "third leg"** (run the real migration registry against a spun-up MariaDB in test, no SSH) is still deferred there.

**Requested (PM-lane):** annotate TD-055 with a US-462 back-reference — the preflight closed the deploy-time now-achievable slice; the testcontainer harness leg remains the open structural item (Atlas's 4th-cycle warning). Whether to reactivate it out of archive is your call; I'm flagging per the conditionalOutcome ("file it if not built" — it IS built, so confirming + handing off the annotation).

## PM/deploy gate (bench-only, owed at integration on chi-srv-01)

Couple with US-461's v0022 gate: after v0022 applies on the live drifted DB, the next `--run-all` preflight should verify `drive_statistics` + `drive_derived_signals` `summary_id` FK → `drives.drive_id` present (green); a drifted DB fails fast naming the delta. mypy strict = PM integration gate (not installed in dev).
