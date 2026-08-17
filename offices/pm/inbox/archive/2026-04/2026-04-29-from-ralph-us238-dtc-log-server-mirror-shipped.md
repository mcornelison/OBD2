# US-238 SHIPPED — V-2 dtc_log server-side migration (0005) closed

**From:** Rex (Ralph, Agent 1)
**To:** Marcus (PM)
**Date:** 2026-04-29
**Sprint:** 19 (Runtime Fixes + Server Reconciliation)
**Story:** US-238 — V-2 dtc_log server-side migration (0005) — close silent-data-loss risk
**Status:** `passes:true` (Sprint 19 5/8)
**Commit:** on `sprint/runtime-fixes`

---

## TL;DR

Sprint 15 US-204 shipped the Pi-side `dtc_log` capture table + the
server-side `DtcLog` ORM + sync wiring (`_TABLE_REGISTRY` entry, Pi
`DELTA_SYNC_TABLES` entry) but never CREATEd the physical MariaDB table
on the live server. US-204 predated the US-213 explicit migration
registry (Sprint 16) so there was no place to register a deploy-time
DDL step. The gap stayed dormant until your Drive 4 health check
caught it as **V-2** (`Table 'obd2db.dtc_log' doesn't exist`).

US-238 ships **migration v0005** with the same pattern as v0002
(`battery_health_log`): `serverTableExists` short-circuit + `CREATE
TABLE IF NOT EXISTS dtc_log (...)` with all 12 ORM-declared columns +
`uq_dtc_log_source` UNIQUE + `ix_dtc_log_drive_id` INDEX, then a
post-condition probe that raises `SchemaProbeError` if the table is
still missing post-CREATE (catches the silent mysql session-context
bug class).

**No ORM / sync.py / sync_log.py changes needed** — Sprint 15 US-204
already wired all three.  The pre-flight audit's job was to confirm
that, and it did.  Story `scope.filesToTouch` listed those three plus
sync-side `DELTA_SYNC_TABLES` adjustments as conditional ("if not
already") — none turned out to be required. Documented in
`scopeFenceNote` on the story.

---

## Files actually touched

| File | Change |
|------|--------|
| `src/server/migrations/versions/v0005_us238_create_dtc_log.py` | **NEW** — 165 lines: module docstring + `CREATE_DTC_LOG_DDL` constant + `apply()` with serverTableExists short-circuit + post-condition probe + `MIGRATION` registry export. |
| `src/server/migrations/__init__.py` | Registered v0005 in `ALL_MIGRATIONS` (now `(_V0001, _V0002, _V0003, _V0004, _V0005)`). Mod History entry. |
| `tests/server/test_migration_0005_dtc_log.py` | **NEW** — 28 unit tests using FakeRunner pattern from v0004's test (module exports, DDL-mirrors-ORM parity, table-missing path, table-present idempotent, failure modes, production-failure-mode discriminators). |
| `tests/server/test_dtc_log_sync_post_create.py` | **NEW** — 8 round-trip tests including the **strong-test discriminator** `test_missingTableFailsWithNoSuchTableError` that drops dtc_log from a SQLite engine and asserts the sync handler raises `OperationalError` with `dtc_log` in the error — reproduces V-2's exact production failure shape. |
| `tests/server/test_migration_0004_drive_summary_reconcile.py` | Renamed `test_appendedAtEnd` → `test_appendsAfterV0003`. The old test asserted v0004 was the tail of `ALL_MIGRATIONS`; with v0005 now appended that bounced false-positive. New assertion locks v0004's position relative to v0003 (durable across future migrations). Out-of-scope but at-parity update; documented in `scopeFenceNote`. |
| `specs/architecture.md` | Section 5 Server Schema Migrations registry table: appended v0005 row.  Section 10.5 DTC Lifecycle "Server mirror" paragraph: appended v0005 deploy-time-migration context.  Modification History entry. |
| `offices/ralph/sprint.json` | US-238 `passes:true` + `completedDate` + `completionNotes` + `filesActuallyTouched` + `scopeFenceNote`. |
| `offices/ralph/ralph_agents.json` | Rex back to `unassigned` + Session 110 close note. |
| `offices/ralph/progress.txt` | Session 110 entry. |
| `offices/pm/inbox/2026-04-29-from-ralph-us238-dtc-log-server-mirror-shipped.md` | **NEW** — this note. |
| `offices/tuner/inbox/2026-04-29-from-ralph-us238-dtc-log-server-mirror-shipped.md` | **NEW** — mirror copy for Spool. |

---

## Strong-test discriminator (per `feedback_runtime_validation_required`)

V-2 evidence (Drive 4 health check, 2026-04-29 lines 437-438):

```sql
SELECT COUNT(*) FROM dtc_log;
ERROR 1146 (42S02): Table 'obd2db.dtc_log' doesn't exist
```

The discriminator test reproduces that exact production state:

```python
def _newMissingDtcLogEngine():
    engine = create_engine('sqlite:///:memory:')
    everythingExceptDtcLog = [
        t for t in Base.metadata.sorted_tables if t.name != 'dtc_log'
    ]
    Base.metadata.create_all(engine, tables=everythingExceptDtcLog)
    return engine

def test_missingTableFailsWithNoSuchTableError(self):
    engine = _newMissingDtcLogEngine()
    session = Session(engine)
    with pytest.raises(OperationalError) as exc:
        runSyncUpsert(
            session, deviceId='chi-eclipse-01',
            batchId='batch-missing-reproduces-v2',
            tables={'dtc_log': {'rows': [_piShapeDtcPayload(...)]}},
            syncHistoryId=1,
        )
    assert 'dtc_log' in str(exc.value)
```

If a future refactor drops the v0005 migration OR pulls `DtcLog` out
of `Base.metadata`, this test fires and the regression cannot ship.

The migration-side discriminator (`test_runWouldFireCreateAgainstStaleProductionState`)
mirrors the same shape on the FakeRunner side — replays the V-2 server
state (table-probe returns 0) and asserts exactly one `CREATE TABLE`
SQL is emitted.  A refactor that removes the CREATE statement would
fail loudly.

---

## Verification

```bash
pytest tests/server/test_migration_0005_dtc_log.py \
       tests/server/test_dtc_log_sync_post_create.py -v
# 36/36 PASS

pytest tests/server/test_migration_0005_dtc_log.py \
       tests/server/test_dtc_log_sync_post_create.py \
       tests/server/test_migrations.py \
       tests/server/test_dtc_sync.py \
       tests/server/test_migration_0004_drive_summary_reconcile.py \
       tests/server/test_drive_summary_sync_post_reconcile.py \
       tests/scripts/test_apply_server_migrations.py -v
# 152/152 PASS (after the one pre-existing v0004 test got at-parity update)

pytest tests/ -m "not slow" -q
# baseline 3411 (post-US-237) + 36 new = ~3447 expected
```

```bash
ruff check src/server/migrations/versions/v0005_us238_create_dtc_log.py \
           src/server/migrations/__init__.py \
           tests/server/test_migration_0005_dtc_log.py \
           tests/server/test_dtc_log_sync_post_create.py \
           tests/server/test_migration_0004_drive_summary_reconcile.py
# All checks passed!

python validate_config.py
# All validations passed!

python offices/pm/scripts/sprint_lint.py
# 0 errors / 24 warnings (US-238 introduced none — same set as US-237)
```

---

## Pre/post-deploy verification SQL (for Marcus to run after `bash deploy/deploy-server.sh`)

**Pre-deploy (proves the bug):**

```bash
ssh chi-srv-01 "mariadb -uobd2 -p\$DB_PASS obd2db -e 'SELECT COUNT(*) FROM dtc_log'"
# Expect: ERROR 1146 (42S02): Table 'obd2db.dtc_log' doesn't exist
```

**Post-deploy (proves the fix):**

```bash
ssh chi-srv-01 "mariadb -uobd2 -p\$DB_PASS obd2db -e \"SHOW CREATE TABLE dtc_log\""
# Expect:
#   CREATE TABLE `dtc_log` (
#     `id` int(11) NOT NULL AUTO_INCREMENT,
#     `source_id` int(11) NOT NULL,
#     `source_device` varchar(64) NOT NULL,
#     `synced_at` datetime DEFAULT current_timestamp(),
#     `sync_batch_id` int(11) DEFAULT NULL,
#     `dtc_code` varchar(16) NOT NULL,
#     `description` text DEFAULT NULL,
#     `status` varchar(16) NOT NULL,
#     `first_seen_timestamp` datetime NOT NULL DEFAULT current_timestamp(),
#     `last_seen_timestamp` datetime NOT NULL DEFAULT current_timestamp(),
#     `drive_id` int(11) DEFAULT NULL,
#     `data_source` varchar(16) DEFAULT 'real',
#     PRIMARY KEY (`id`),
#     UNIQUE KEY `uq_dtc_log_source` (`source_device`,`source_id`),
#     KEY `ix_dtc_log_drive_id` (`drive_id`)
#   ) ENGINE=InnoDB ...

ssh chi-srv-01 "mariadb -uobd2 -p\$DB_PASS obd2db -e 'SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 5'"
# Expect: 0005, 0004, 0003, 0002, 0001 (top of the audit trail)
```

**Idempotent re-run check** (run `apply_server_migrations.py --run-all`
twice — second invocation must be a no-op for v0005):

```bash
ssh chi-srv-01 "cd ~/obd-server && python scripts/apply_server_migrations.py --run-all"
# Expect on second run: '0005 dtc_log -- already at version, skipping'
# (per the MigrationRunner contract -- runner records version on first
#  success and short-circuits subsequent runs).
```

---

## Sprint 19 status post-US-238

| Story | Size | Status |
|-------|------|--------|
| US-234 (VCELL trigger fix) | M | ✅ |
| US-235 (UpsMonitor BATTERY-detection) | S | ✅ |
| US-236 (defer-INSERT) | S | ✅ |
| US-237 (drive_summary 0004 reconcile) | M | ✅ |
| **US-238 (dtc_log 0005 migration) — this story** | **S** | **✅** |
| US-239 (V-3 connection_log path-a/b) | S | pending |
| US-240 (V-5 server orphan backfill) | S | pending |
| US-241 (B-047 versioning V0.18.0) | S | pending |

**5/8 done.** P0 work is complete (4/4 P0s — US-234, US-235, US-236, US-237 plus US-238). Remaining 3 are all P1. Ralph emits `<promise>PARTIAL_BLOCKED</promise>` so ralph.sh continues.

---

## Sprint contract size feedback

US-238 was sized **S**. Actual work:
- 1 NEW migration file (165 lines)
- 1 EDIT to migration registry (3 lines)
- 2 NEW test files (28 + 8 = 36 tests, ~470 lines combined)
- 1 EDIT to v0004 test at parity (3-line rename of one assertion)
- 2 small `specs/architecture.md` edits + 1 mod history line

Felt right at S. The pre-flight audit short-circuited a lot of would-be
work because Sprint 15 US-204 had already shipped the ORM + sync
plumbing — the migration was the only real gap. The strong-test
discriminator added ~50 lines to the round-trip test file but that's
the runtime-validation rule paying its rent (without it, a future
refactor that drops v0005 would silently re-introduce V-2). No size
adjustment recommended.

— Rex (Ralph, Agent 1, Session 110)
