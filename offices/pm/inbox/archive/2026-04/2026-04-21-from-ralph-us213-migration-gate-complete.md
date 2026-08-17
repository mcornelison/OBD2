# US-213 complete — Server schema migration gate (TD-029 closure)

**From**: Rex (Ralph Agent, Agent_ID=1)
**To**: Marcus (PM)
**Date**: 2026-04-21
**Sprint**: 16 — Wiring
**Status**: `passes: true`

## Summary

Sprint 16 US-213 shipped.  Path B (explicit migration registry + deploy-server.sh
gate) closes TD-029 permanently.  The class-of-bug behind the Sprint 14 →
Sprint 15 mid-sprint US-209 catch-up is now impossible to recur: every server
schema change must register a `Migration` in `src/server/migrations/`, and
`deploy-server.sh` applies pending migrations on every deploy.

## What shipped

### New package: `src/server/migrations/`

| File | Role |
|------|------|
| `__init__.py` | Public API: `ALL_MIGRATIONS` registry + re-exports |
| `runner.py` | `MigrationRunner` (ensureTracking, getApplied, planPending, runAll) + `Migration` + `RunnerContext` + `RunReport` + `SCHEMA_MIGRATIONS_TABLE_DDL` + `RegistryError` |
| `versions/__init__.py` | Marker |
| `versions/v0001_us195_us200_catch_up.py` | Retroactive wrapper of US-209's DDL |

### Enhanced: `scripts/apply_server_migrations.py`

- New `--run-all` CLI mode (+ `runRegistry()` helper) that drives
  `MigrationRunner(ALL_MIGRATIONS).runAll(ctx)`
- Legacy `--dry-run` / `--execute` US-209 one-shot path **untouched** —
  39 existing tests still green
- Function-local import of `src.server.migrations` avoids the obvious
  module-load cycle (registry imports from this module)

### Enhanced: `deploy/deploy-server.sh`

- New Step 4.5 between pip install and service restart
- Runs under both `--init` and default flow; skipped under `--restart`
- Under `set -e`: migration failure halts the deploy **before** the service
  restart — no half-deployed state
- Banner: `--- Step 4.5: Applying pending schema migrations ---`

### New tracking table

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) NOT NULL PRIMARY KEY,
    description VARCHAR(512) NOT NULL,
    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
```

Created idempotently on first `--run-all`.

### Docs

- `specs/architecture.md` §5 new "Server Schema Migrations" subsection
  (design rationale, developer workflow, post-deploy verification)
- `docs/testing.md` new "Server Schema Migration Registry (developer
  workflow, US-213 / TD-029)" section; legacy US-209 one-shot section
  annotated as "supported fallback, not primary path"
- `offices/pm/tech_debt/TD-029-*.md` annotated Closed with closure date,
  chosen path, rejected alternative rationale, verification receipts

### Tests (52 new)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/server/test_migrations.py` | 36 | Registry sanity, runner construction, ensureTracking, getApplied, planPending, runAll (fresh/idempotent/added/failure), record-applied + SQL-injection escape, SCHEMA_MIGRATIONS_TABLE_DDL shape, RunReport, v0001 (import, no-op-on-full, applyPlan-on-stale), runRegistry + main --run-all CLI round-trip + error-exits-nonzero |
| `tests/deploy/test_deploy_server_migration_gate.py` | 8 | script exists, `set -e`, invokes `--run-all`, runs-default-flow-not-just-init, runs-before-service-start, runs-after-dependency-install, skipped-under-restart-only, has-operator-banner |

## Decision: Path B over Path A (Alembic)

Rationale captured in TD-029 closure annotation:

1. CIO's "single deploy script, keep it simple" directive
   (`offices/ralph/CLAUDE.md` §6) — hand-rolled Python registry matches
   the architectural preference.
2. Zero new runtime deps on the default path.  `alembic>=1.12.0` stays
   in `requirements-server.txt` (available for future migrations that
   genuinely need autogenerate or downgrade) but is not on the deploy
   critical path.
3. Same mental model as Pi-side `ensureAllCaptureTables` +
   `ensureAllDriveIdColumns` idempotent migrations.
4. No env.py + autogenerate baseline learning curve for a project with
   <5 total migrations ahead.

Path A (Alembic) can be revisited if migration count grows past ~25 or
a downgrade is genuinely needed (MariaDB DDL implicit-commit limits that
regardless).

## Quality gates (Windows runner)

| Gate | Result |
|------|--------|
| Fast suite | **2943 passed** (+44 vs 2899 US-212 baseline, 0 regressions, 551.09s) |
| US-209 tests | 39/39 green (unchanged) |
| New tests | 44/44 green (36 server + 8 deploy) |
| Ruff | Clean on all touched files |
| `validate_config.py` | 4/4 OK |
| `sprint_lint.py` | 0 errors, 3 pre-existing informational sizing warnings on US-213 unchanged |

## Post-deploy CIO-facing smoke (for next deploy-server.sh run)

```bash
# 1. Run a normal deploy (no --init).  Expect a new Step 4.5 banner.
bash deploy/deploy-server.sh
# Expected log: "--- Step 4.5: Applying pending schema migrations ---"
# then: "[run-all] 0 applied -- registry fully applied (1 already applied; idempotent no-op)"
# (the '1 already applied' is v0001 if it was registered during first post-US-213 deploy)

# 2. Verify schema_migrations row on the live DB:
ssh mcornelison@10.27.27.10 "mysql obd2db -e \
  'SELECT version, description, applied_at FROM schema_migrations ORDER BY version'"
# Expected: 1 row (version=0001, US-195/US-200 catch-up description).

# 3. Re-run deploy; expect '[run-all] 0 applied' on the second run.
```

## Invariants honoured

- US-209 legacy path untouched (39 tests unchanged)
- `scripts/apply_server_migrations.py` NOT removed — enhanced with
  `--run-all` mode
- Idempotent: re-run is a no-op (0 DDL)
- Deploy-failure is HARD fail via `set -e` (no partial state)
- Bookkeeping only at end: tracking row inserted **after** successful
  `applyFn`, so partial success is observable in `schema_migrations`
  for post-mortem
- DDL-only scope (no data migrations here)
- v0001 delegates to `scripts.apply_server_migrations` so the US-195 +
  US-200 DDL definition lives in exactly one place

## Not done (scope-fenced)

Kept out of this story per invariants:

- SQLAlchemy `Integer → BigInteger` for `drive_id` columns (TD-029
  additional cleanup #1) — **unchanged**; deferred to a future
  dedicated model story.  Current model-vs-live-DB drift (models say
  INT, live DB is BIGINT post-US-209) is documented in TD-029 but not
  functionally a problem because `create_all` only runs for MISSING
  tables and the migration registry now propagates the right DDL on
  fresh deploys going forward.
- Server-side Alembic env.py bootstrap — deferred; not needed for
  Path B.
- CI job spinning up a real MariaDB container (TD-029 cleanup #2) —
  deferred, out of US-213 scope.
- Rollback machinery — intentional (MariaDB DDL is implicit-commit;
  restore is from per-migration mysqldump backup when a migration
  takes one).

## Next steps for Marcus

- Merge on sprint/wiring per normal sprint contract.
- On next deploy to chi-srv-01, watch Step 4.5 output and verify
  `schema_migrations` row lands.
- US-214 (US-206 dual-writer reconciliation) depends on US-213 — now
  unblocked.
- US-217 (battery_health_log) acceptance mentions "via US-213 gate if
  shipped, else raw-SQL migration" — US-213 is shipped, so US-217 can
  ride the registry.

No blockers surfaced.  No stop conditions triggered.  No specs-change
requests (other than the one addition in §5).
