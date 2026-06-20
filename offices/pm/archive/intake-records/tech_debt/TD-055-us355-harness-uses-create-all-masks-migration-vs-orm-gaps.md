# TD-055 — US-355 deploy-context drive simulator uses `create_all` which masks migration-vs-ORM divergence

**Status**: Open — bonus deferral from US-357 V0.27.18 hotfix loop. Tracked-not-silently-dead via two compensating tests in `tests/integration/test_deploy_context_drive_simulator.py::TestHarnessIntegrity` (see "Compensating coverage" below). Not chain-blocking. Pick up post-V0.27 chain merge to main; appropriate sprint for the refactor is V0.28+ when B-104 Step 2+ grooming adds more analytics surface that this harness would need to cover.
**Filed**: 2026-05-21 (Sprint 41 V0.27.18 hotfix, by Ralph during US-357 bonus deliverable)
**Origin**: I-041 root cause analysis: US-355's `tests/integration/test_deploy_context_drive_simulator.py` `serverEngine` fixture uses `Base.metadata.create_all(engine)`. That helper builds the schema from the live SQLAlchemy ORM declarations on every test run — so a new ORM column (US-351's `data_quality`) silently appears in every test fixture's schema regardless of whether a migration was filed for it. Production MariaDB has historical tables that pre-date the column; `create_all` is a no-op on existing tables (never ALTERs). The harness designed to catch the V0.27.7/V0.27.16 false-pass class shipped with its own structural blind spot for the migration-vs-ORM divergence class — caught I-041 zero times.

## The debt

`tests/integration/test_deploy_context_drive_simulator.py:174-205` (post-US-357 V0.27.18 update):

```python
@pytest.fixture
def serverEngine():
    """... [docstring documents the limitation + cites TD-055] ..."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)   # <-- the gap
    try:
        yield engine
    finally:
        engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)
```

The structural fix per US-357 PM dispatch (`offices/ralph/inbox/2026-05-21-from-marcus-V0.27.18-hotfix-dispatch-I-041-I-042.md` bonus #4): "Refactor harness to apply migrations registry-only on a fresh DB (do NOT call `create_all`)." This is the right shape but it requires infrastructure that V0.27.18 cannot bring in scope:

- The migration runner (`src/server/migrations/runner.py` + `scripts/apply_server_migrations.py`) executes DDL via `_runServerSql` which **SSHes to chi-srv-01 and pipes MariaDB DDL through `mysql`**. There is no path to invoke it against a local SQLite engine.
- The DDL itself uses **MariaDB-specific syntax**: `VARCHAR(N)`, `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`, `information_schema.CHECK_CONSTRAINTS` probes, `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)` syntax that varies between MariaDB versions. SQLite cannot execute most of this.

## Why not fix in V0.27.18

V0.27.18 is a focused hotfix loop on the `sprint/sprint41-bugfixes-V0.27.17` branch with three load-bearing deliverables (v0009 migration + tests + Step 4.9 marker gate fix). The PM dispatch explicitly tags this refactor "**Bonus (if time, NOT V0.27.18-blocking)**". The structural close requires infrastructure work (real MariaDB in test) that would expand the patch loop's scope significantly. Better to ship the focused fix + file this TD + move on.

## Compensating coverage shipped in US-357 V0.27.18

Two tests in `TestHarnessIntegrity` close the bug-class gap structurally without doing the full infrastructure refactor:

1. **`test_serverEngineFixture_documentsCreateAllLimitation`** — pins the `serverEngine` fixture's known-limitation docstring (must cite TD-055 + `create_all` + the I-041 / schema-vs-ORM-divergence class). Tripwire: a future PR that deletes the docstring caveat without replacing it with the actual fix trips RED here, forcing the next maintainer to either land the refactor or update the test deliberately.

2. **`test_harnessTooling_canCatchSchemaVsOrmDivergence_synthetic`** — builds a separate SQLite engine, runs `Base.metadata.create_all`, then DROPs + re-CREATEs the `drive_statistics` table with the pre-v0009 historical shape (no `data_quality` column). Asserts that the **production ORM**'s `DriveStatistic` INSERT path through a real `Session` MUST raise `OperationalError` mentioning the missing column (the exact I-041 production symptom). Then re-ADDs the column via raw DDL (simulating v0009) and asserts the same INSERT now succeeds. This proves the harness's **seam visibility is sound** for this class — the default fixture just doesn't exercise it. If a future change to the production `DriveStatistic` model adds a try/except that swallows OperationalError, this test trips RED — the I-041 symptom would no longer surface even when the schema is correctly divergent.

These two compensating tests don't close the gap (the default fixture still uses `create_all`) but they pin the **awareness** (#1) + the **capability** (#2) so the bug class is structurally visible to the next reader.

## Proposed cleanup (deferred to V0.28+ or appropriate housekeeping sprint)

Two options to consider when this is picked up:

### Option A: real MariaDB via testcontainers (preferred)

1. Add `testcontainers[mariadb]` to `requirements-dev.txt`.
2. Replace `serverEngine` fixture with a `MariaDbContainer` + `create_engine` against the spun-up MariaDB.
3. Replace `Base.metadata.create_all(engine)` with `MigrationRunner(ALL_MIGRATIONS).runAll(ctx)` using a local-execution `CommandRunner` that pipes SQL directly via `mysql -h <container-host> -P <container-port> ...` (no SSH).
4. The `_runServerSql` helper can be wrapped to switch SSH vs. local-pipe based on a fixture-provided context.

Pros: deploy-faithful; catches the schema-vs-ORM class natively; future analytics stories don't need the same workaround.
Cons: ~3-5s per-test fixture spin-up; requires Docker on the test host (Windows dev + CI both have it but adds a dependency); larger refactor surface.

### Option B: per-migration SQLite-portable DDL fallback paths

1. Add a `_runLocalSql(engine, sql)` companion to `_runServerSql` that executes against a passed-in SQLAlchemy engine.
2. Per migration, ship a "SQLite-portable" variant alongside the MariaDB DDL — e.g., for v0009 the variant uses `VARCHAR(16)` (compatible) + skips the `information_schema.CHECK_CONSTRAINTS` probe (use INFORMATION_SCHEMA-portable PRAGMA or `sqlite_master` introspection instead).
3. Migration `apply` functions check `ctx.dialect` (new field on `RunnerContext`) and dispatch.

Pros: no Docker dependency; faster tests.
Cons: doubles the migration-author surface area; SQLite-portable DDL drifts from MariaDB reality (the FALSE-pass class is now distributed across two DDL flavors instead of consolidated); fragile.

Atlas + Marcus + Ralph design at grooming time. Option A is the structural answer; Option B is the band-aid.

## Acceptance for close

- `serverEngine` fixture no longer calls `Base.metadata.create_all`.
- Fixture uses the migration registry (real MariaDB via Option A; SQLite via Option B; Atlas at grooming).
- `test_serverEngineFixture_documentsCreateAllLimitation` either passes against the new docstring (TD-055 cited) OR is deleted with a one-line `git log` reference to this TD's close commit.
- `test_harnessTooling_canCatchSchemaVsOrmDivergence_synthetic` stays as-is (it's a real coverage test; not specific to the gap).
- I-041 retroactive proof: temporarily revert the v0009 migration's registration in `src/server/migrations/__init__.py` and confirm the integration suite trips RED somewhere in the deploy-context harness (proves the new approach catches the I-041 class going forward).

## Cross-links

- **I-041** (`offices/pm/issues/I-041-us351-missing-v0009-migration-data-quality-column.md`) — the production failure that exposed this gap.
- **US-357** (Sprint 41 V0.27.18 hotfix in `offices/ralph/sprint.json`) — the hotfix sprint that landed v0009 + filed this TD.
- **US-355** (Sprint 41 V0.27.17 in `offices/ralph/sprint.json`) — the original harness story whose invariants this TD refines.
- **B-104** (`offices/pm/backlog/B-104-server-side-analytics-authority.md`) — V0.28+ Step 2+ will add more analytics surface; this TD should land **before** Step 2's first story to avoid re-shipping the gap on a wider blast radius.
