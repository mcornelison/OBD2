# B-061: Drop battery_health_log start_soc / end_soc legacy columns (BL-013 Step 3)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Low                    |
| Status       | Pending (V0.28.0+ reservation per CIO 2026-05-09) |
| Category     | database / schema migration |
| Size         | M                      |
| Related PRD  | None                   |
| Dependencies | B-060 must merge first (Step 2 wires SOC% so consumers can migrate)  |
| Created      | 2026-05-09             |

## Description

BL-013 Option A Step 3: once B-060 (Step 2) wires SOC% through to the recorder and Spool's analytics consumers fully migrate to reading `start_vcell_v` / `end_vcell_v`, drop the legacy `start_soc` / `end_soc` columns from `battery_health_log` on both Pi (SQLite) and server (MariaDB) schemas.

This is the architectural endpoint of the US-289 deprecation pattern (Sprint 25 added `start_vcell_v` / `end_vcell_v` columns + dual-write + deprecation comment).

## Acceptance Criteria

- [ ] Pre-grooming consumer audit confirms NO production reader depends on `start_soc` / `end_soc` (Spool analytics, dashboard, sync mappings, AI prompt construction all migrated to `start_vcell_v` / `end_vcell_v`)
- [ ] Pi SQLite migration: CREATE TABLE-AS-SELECT-DROP-RENAME idiom (SQLite doesn't support `ALTER TABLE DROP COLUMN`); preserves all existing rows minus the dropped columns
- [ ] Server MariaDB migration: `ALTER TABLE battery_health_log DROP COLUMN start_soc, DROP COLUMN end_soc`; new migration version (v0009+) in `src/server/migrations/versions/`
- [ ] Deploy-time migration discipline (US-249 schema-diff CI) confirms no schema drift between Pi + server post-drop
- [ ] All ~10 lock-down tests (Category B per BL-013) updated to no longer reference the dropped columns

## Validation Script Requirements

- **Input**: post-deploy on chi-srv-01 + chi-eclipse-01
- **Expected Output**: `PRAGMA table_info(battery_health_log)` (Pi) + `DESCRIBE battery_health_log` (server) show only `start_vcell_v` / `end_vcell_v` (no `start_soc` / `end_soc`)
- **Database State**: existing row data preserved minus the two dropped columns; new drain events INSERT cleanly without the legacy column
- **Test Program**: migration apply test asserts schema before + after; integration test asserts new drain events still write through new code paths

## Notes

**Why P3 (low)**: Schema hygiene; analytics correctness already restored in B-060. Dropping the legacy columns is cosmetic + reduces sync payload size + eliminates ambiguity about what the columns mean.

**Migration sequencing**: Pi migration MUST run BEFORE the corresponding sync push (Pi -> server) drops the columns from the wire format; otherwise sync_history shows TYPE mismatch errors. Coordinate with deploy ordering in `deploy-pi.sh` + `deploy-server.sh`.

**Source**: `offices/pm/blockers/BL-013.md` (full pre-flight audit + Step 3 spec) + US-289 deprecation pattern precedent

**Sprint reservation**: V0.28.0+ (next minor version after V0.27.X chain completes). Don't pull in earlier; depends on B-060 migration being deployed + production-validated first.
