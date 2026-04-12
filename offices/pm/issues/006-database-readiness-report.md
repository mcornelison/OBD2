# I-006: Database Readiness Report -- Pre-Dongle Verification

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Open                      |
| Category     | database / infrastructure |
| Found In     | data/obd.db, validate_config.py, specs/architecture.md |
| Found By     | Pi 5 Agent (pre-dongle readiness check) |
| Related B-   | B-016                     |
| Created      | 2026-01-31                |

## Summary

Comprehensive database verification performed ahead of Bluetooth OBD-II dongle integration. The database is **functionally ready** -- all CRUD operations, FK constraints, indexes, transactions, and WAL mode work correctly. However, several non-blocking issues were found that should be addressed.

## Test Results

### Unit Tests: PASS
- 1171/1171 tests passing (including 14 database-specific tests)

### Functional Tests: 22/22 PASS

| Test | Result |
|------|--------|
| FK enforcement (bad profile_id rejected) | PASS |
| FK cascade delete (vehicle_info -> static_data) | PASS |
| Realtime data insert/read (5 OBD params) | PASS |
| Statistics insert/read (post-drive analysis) | PASS |
| AI recommendations + dedup FK chain | PASS |
| priority_rank CHECK constraint (1-5) | PASS |
| Connection log (BT dongle workflow) | PASS |
| Alert log | PASS |
| No orphaned records (referential integrity) | PASS |
| Index usage -- timestamp lookup | PASS |
| Index usage -- param+time compound | PASS |
| Index usage -- profile filter | PASS |
| Index usage -- stats by date | PASS |
| createDatabaseFromConfig factory | PASS |
| initializeDatabase convenience function | PASS |
| getStats on production DB | PASS |
| All 11 tables have correct columns | PASS |
| Idempotent initialize() preserves data | PASS |
| vacuum() completes | PASS |
| Concurrent reads under WAL mode | PASS |
| Transaction rollback on FK violation | PASS |
| Dry-run application startup | PASS |

### PRAGMA Settings (via ObdDatabase class): Correct
- `foreign_keys`: ON (set per-connection, correct SQLite behavior)
- `journal_mode`: WAL
- `synchronous`: NORMAL

## Issues Found

### Issue 1: `validate_config.py` references deleted `src/config.json`

**Severity**: Medium
**Impact**: `python validate_config.py` fails with "src/config.json not found". The file was removed during housekeeping (consolidated to `src/obd_config.json`).
**Fix**: Update `validate_config.py` lines 163 and 183 to reference `src/obd_config.json`.

### Issue 2: Architecture spec lists 7 tables, actual schema has 11

**Severity**: Low (spec drift, not a code bug)
**Impact**: `specs/architecture.md` Section 5 documents only 7 tables. Four tables added later are not in the spec:
- `alert_log`
- `connection_log`
- `battery_log`
- `power_log`

**Fix**: Update architecture.md database section to document all 11 tables.

### Issue 3: Vehicle info record has 8 NULL columns

**Severity**: Low (data quality, not structural)
**Impact**: The existing vehicle_info record (VIN: 1HGBH41JXMN109186, 1991 Honda) has NULL values for: model, engine, fuel_type, transmission, drive_type, body_class, plant_city, plant_country. The NHTSA API returned ErrorCode 8 ("No detailed data available") for this 1991 VIN.
**Note**: This is expected behavior for older vehicles. The code correctly handles NHTSA N/A values as NULL per the codebase pattern. Not a bug -- just noting the data state.

### Issue 4: `OBD_BT_MAC` environment variable not set

**Severity**: Medium (blocks dongle connection)
**Impact**: `python src/main.py --dry-run` logs warning: "Environment variable OBD_BT_MAC not set and no default". This will be needed before Bluetooth dongle testing.
**Fix**: Set `OBD_BT_MAC=XX:XX:XX:XX:XX:XX` in `.env` once the dongle is paired.

### Issue 5: Lint and typecheck failures (pre-existing)

**Severity**: Low (not runtime bugs)
**Impact**: 2,267 ruff lint errors (1,984 auto-fixable -- mostly import sorting and Optional->X|None style). 194 mypy errors (mostly Returning Any, union-attr). These are code quality issues, not functional bugs.

## Database Statistics

| Metric | Value |
|--------|-------|
| File size | 136 KB |
| Tables | 11 |
| Indexes | 10 |
| WAL mode | Enabled |
| Profiles | 2 (daily, performance) |
| Vehicle info | 1 (1991 Honda) |
| Realtime data | 156 readings across 13 parameters |
| Other tables | Empty (ready for dongle data) |

## Verdict

**Database is READY for dongle testing.** The schema, constraints, indexes, transactions, and API all work correctly. The four issues above are non-blocking but should be addressed during the next sprint.

## Recommended Pre-Dongle Actions

1. Fix `validate_config.py` to point to `src/obd_config.json` (Issue 1)
2. Set `OBD_BT_MAC` in `.env` after pairing the dongle (Issue 4)
3. Auto-fix lint issues: `ruff check src/ tests/ --fix` (Issue 5, optional)
4. Update `specs/architecture.md` database section (Issue 2, optional)
