# PRD: Database Verify and Initialize Script

**Parent Backlog Item**: B-015
**Status**: Active

## Introduction

Create a standalone database verification and initialization tool for Pi deployment. The application already has a fully idempotent `ObdDatabase.initialize()` method (`src/obd/database.py:559`) that creates all 11 tables and 10 indexes. This PRD wraps that functionality in a CLI tool that can:

1. Initialize a fresh database (or verify an existing one)
2. Report detailed status (tables, indexes, WAL mode, record counts, file size)
3. Return proper exit codes for CI/CD integration (B-013 deploy script)
4. Be imported as a module for programmatic use

## Goals

- Standalone CLI tool for database health checking and initialization
- Clear pass/fail output for each verification check
- Idempotent -- safe to run on fresh or populated databases
- Usable in the deploy pipeline (`scripts/deploy.sh` post-sync step)
- Zero data loss when run against an existing database

## Existing Infrastructure

The developer does NOT need to create these -- they already exist:

| Component | File | Key Details |
|-----------|------|-------------|
| Database class | `src/obd/database.py` | `ObdDatabase` with `initialize()`, WAL mode, factory functions |
| Schema definitions | `src/obd/database.py:81-443` | `ALL_SCHEMAS` (11 tables), `ALL_INDEXES` (10 indexes) |
| Factory functions | `src/obd/database.py:732-779` | `createDatabaseFromConfig()`, `initializeDatabase()` |
| Config file | `src/obd_config.json:8-13` | Database path, WAL mode, vacuum settings |

### Authoritative Table List (from `ALL_SCHEMAS`)

1. `vehicle_info`
2. `profiles`
3. `static_data`
4. `realtime_data`
5. `statistics`
6. `ai_recommendations`
7. `calibration_sessions`
8. `alert_log`
9. `connection_log`
10. `battery_log`
11. `power_log`

### Authoritative Index List (from `ALL_INDEXES`)

1. `IX_realtime_data_timestamp`
2. `IX_realtime_data_profile`
3. `IX_realtime_data_param_timestamp`
4. `IX_statistics_analysis_date`
5. `IX_statistics_profile`
6. `IX_ai_recommendations_duplicate`
7. `IX_battery_log_timestamp`
8. `IX_battery_log_event_type`
9. `IX_power_log_timestamp`
10. `IX_power_log_event_type`

## User Stories

### US-DBI-001: Create Database Verify Script (CLI)

**Description:** As a developer, I need a CLI script that checks whether the database is correctly initialized and reports status.

**Acceptance Criteria:**
- [ ] Create `scripts/verify_database.py` with standard file header per `specs/standards.md`
- [ ] Accepts `--db-path` argument (default: value from `src/obd_config.json` database.path, resolved via secrets_loader)
- [ ] Accepts `--verbose` flag for detailed output
- [ ] Checks that the database file exists (or can be created)
- [ ] Verifies all 11 tables exist by querying `sqlite_master`
- [ ] Verifies all 10 indexes exist by querying `sqlite_master`
- [ ] Verifies WAL journal mode is active (`PRAGMA journal_mode`)
- [ ] Reports record count per table
- [ ] Reports database file size (human-readable: KB/MB)
- [ ] Reports WAL file size if present
- [ ] Prints a summary with PASS/FAIL for each check
- [ ] Returns exit code 0 if all checks pass, 1 if any check fails
- [ ] Uses camelCase naming per project standards
- [ ] All tests pass, typecheck passes

### US-DBI-002: Add Initialize Mode to Verify Script

**Description:** As a developer, I need the verify script to optionally create and initialize the database if it doesn't exist or is missing tables.

**Acceptance Criteria:**
- [ ] Accepts `--init` flag that triggers database initialization before verification
- [ ] When `--init` is set: calls `ObdDatabase.initialize()` from `src/obd/database.py`
- [ ] When `--init` is NOT set: only verifies (read-only, no schema changes)
- [ ] Initialization uses the existing idempotent `initialize()` method (CREATE IF NOT EXISTS)
- [ ] After initialization, runs the full verification from US-DBI-001
- [ ] Prints "[INIT] Created database at <path>" or "[INIT] Database already exists at <path>"
- [ ] No data is lost if `--init` is run on a database with existing data
- [ ] All tests pass, typecheck passes

### US-DBI-003: Make Script Importable as Module

**Description:** As a developer, I need the verify/init logic importable so the deploy script and orchestrator can call it programmatically.

**Acceptance Criteria:**
- [ ] Script uses `if __name__ == '__main__'` guard for CLI entry point
- [ ] Core logic in a `verifyDatabase(dbPath: str) -> dict` function that returns a results dict
- [ ] Results dict contains: `{"tables": {"name": bool}, "indexes": {"name": bool}, "walMode": bool, "recordCounts": {"name": int}, "fileSizeBytes": int, "allPassed": bool}`
- [ ] `initializeAndVerify(dbPath: str) -> dict` function that initializes then verifies
- [ ] Both functions are importable: `from scripts.verify_database import verifyDatabase, initializeAndVerify`
- [ ] Functions raise no exceptions on verification failure -- they return results with `allPassed: False`
- [ ] All tests pass, typecheck passes

### US-DBI-004: Write Tests for Database Verify Script

**Description:** As a developer, I need tests that verify the script works on fresh and populated databases.

**Acceptance Criteria:**
- [ ] Create `tests/test_verify_database.py` with standard file header
- [ ] Test: `verifyDatabase` on a fresh temp database returns `allPassed: False` (no tables)
- [ ] Test: `initializeAndVerify` on a fresh temp database returns `allPassed: True`
- [ ] Test: `verifyDatabase` on an initialized database returns `allPassed: True`
- [ ] Test: `verifyDatabase` on a database missing one table returns `allPassed: False` with that table marked `False`
- [ ] Test: `initializeAndVerify` on a populated database preserves existing records (insert test data before, verify after)
- [ ] Test: WAL mode verification returns `True` when enabled
- [ ] Test: record counts are correct after inserting test data
- [ ] Test: CLI returns exit code 0 on success, 1 on failure (subprocess test)
- [ ] Tests use `tmp_path` fixture for temp databases
- [ ] All tests pass, typecheck passes

## Functional Requirements

- FR-1: Script must work on both Windows (MINGW64) and Linux (Pi)
- FR-2: Script must not modify the database in verify-only mode (no `--init`)
- FR-3: Output must use colored status messages matching `pi_setup.sh` style: `[PASS]` green, `[FAIL]` red, `[INFO]` default
- FR-4: Script must handle missing database file gracefully (report "not found" instead of crashing)
- FR-5: Script must import from `src/obd/database.py` for schema definitions -- no duplicated table/index lists

## Non-Goals

- No schema migration support (adding/removing columns). That's future work.
- No backup before initialization (covered by B-002).
- No data seeding or sample data insertion.

## Design Considerations

- Import `ALL_SCHEMAS` and `ALL_INDEXES` from `src/obd/database.py` to get the authoritative list -- don't hardcode table names in the script.
- The script lives in `scripts/` (not `src/`) because it's a deployment tool, not part of the application runtime.
- Follow the output style of `scripts/pi_setup.sh` (colored log functions, section headers).
- The deploy script (B-013) will call `python scripts/verify_database.py --init --db-path data/obd.db` as a post-sync step.

## Success Metrics

- Developer can verify database health with `python scripts/verify_database.py`
- Deploy pipeline can initialize database with `python scripts/verify_database.py --init`
- All 4 user stories pass with tests

## Open Questions

- None
