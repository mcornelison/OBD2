# B-057: drive_annotations table for tuning context (fuel + weather + intent + Spool notes)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High                   |
| Status       | Pending                |
| Category     | database / analytics   |
| Size         | M                      |
| Related PRD  | None                   |
| Dependencies | B-056 mod_state enum (FK column)   |
| Created      | 2026-05-09             |

## Description

Spool 2026-05-09 Spec 2: tuning-relevant context that OBD telemetry doesn't record -- fuel grade, fuel level, ambient conditions, driving intent, Spool's seat-of-pants observations. Currently captured manually in `offices/tuner/drive-annotations.md` and replicated to a Spool-owned sidecar table on chi-srv-01 (`obd2db.drive_annotations`, populated for drives 3-7 per CIO authorization 2026-05-09).

This story formalizes the schema + migrates the existing 5 sidecar rows + makes it the canonical tuner-context table.

## Acceptance Criteria

- [ ] `drive_annotations` table created in `obd2db` with the schema below
- [ ] All 5 existing rows on Spool's sidecar table migrate cleanly (no field-shape mismatches)
- [ ] Pi (or server at sync-time) writes new rows at drive_end with NULLs in fuel/intent fields if no UI exists yet
- [ ] `SELECT * FROM drive_summary JOIN drive_annotations ON drive_id` returns full per-drive context in one query

## Schema (Spool's spec, frozen)

```sql
CREATE TABLE drive_annotations (
  id                    INT AUTO_INCREMENT PRIMARY KEY,
  drive_id              INT NOT NULL,
  source_device         VARCHAR(64) NOT NULL DEFAULT 'chi-eclipse-01',
  captured_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  captured_by           VARCHAR(32) NOT NULL DEFAULT 'spool',

  -- Fuel chronology
  fuel_grade            SMALLINT,                 -- octane (87/89/91/93); -1 = E85; -2 = blend
  fuel_level_at_start   VARCHAR(16),              -- enum: F, 3/4, 1/2, 1/4, E, <1/4
  last_fill_date        DATE,                     -- date of most recent fuel fill before this drive

  -- Environment
  ambient_temp_f        DECIMAL(5,1),             -- ground-truth ambient at start (sensor or weather API)
  weather               VARCHAR(64),              -- free-form: "cloudy / sunny / rain / overcast"
  engine_soak_state     VARCHAR(32),              -- enum: cold, warm-restart (<30 min), hot-restart (<5 min)

  -- Drive context
  route                 VARCHAR(255),             -- free-form: "city", "mixed city/highway", specific roads
  driving_intent        VARCHAR(64),              -- enum: commute, errand, spirited, datalog_pull, system_test
  anything_unusual      TEXT,                     -- seat-of-pants observations
  is_actual_drive       BOOLEAN DEFAULT TRUE,     -- false = parked/idle system test

  -- Tag (FK to B-056)
  mod_state             VARCHAR(32) NOT NULL DEFAULT 'premod',

  -- Spool overlay
  spool_notes           TEXT,                     -- Spool's interpretive notes per drive

  UNIQUE KEY unique_drive (source_device, drive_id),
  INDEX idx_drive_id (drive_id),
  INDEX idx_mod_state (mod_state)
);
```

## Field Semantics (where ambiguity is possible)

- `fuel_grade`: encode E85 as -1 and pump-gas blends as -2 so sort/aggregate stays sane on integer column
- `fuel_level_at_start`: enum-as-string; ordering rule `E < <1/4 < 1/4 < 1/2 < 3/4 < F` encoded in app code, not DB
- `engine_soak_state`: derivable from coolant_temp_at_start + barometric trend + last_drive_end_timestamp; future-scope auto-derive from drive_summary
- `is_actual_drive`: drives 3, 4, 5 are FALSE (parked-idle system tests); drives 6, 7 are TRUE

## Validation Script Requirements

- **Input**: completed drive with mod_state=premod
- **Expected Output**: drive_annotations row written with NULLable fields = NULL when no UI exists, mod_state='premod' inherited from B-056 config
- **Database State**: SELECT da.*, ds.* FROM drive_annotations da JOIN drive_summary ds USING (drive_id) WHERE drive_id = N -- single-query view of full context
- **Test Program**: migration apply test + writer integration test + JOIN-query test

## Population Path (sequencing)

1. **Phase 1 (this story)**: schema migration + writer that writes NULLs on UI-absent fields
2. **Phase 2 (B-055 weather API)**: ambient_temp_f + weather populated automatically
3. **Phase 3 (future, no story yet)**: simple form (web UI / slash command / sidecar markdown) for Mike to fill fuel + intent fields

## Notes

**Source**: `offices/pm/inbox/archive/2026-05/2026-05-09-from-spool-three-specs-mod-state-drive-annotations-drive-summary-contract.md` Spec 2

**Sequencing**: depends on B-056 (mod_state enum). Sprint 29+ candidate. Spool's existing sidecar table at `obd2db.drive_annotations` (populated for drives 3-7) serves as the prototype; migration plan should preserve those 5 rows.

**Spec 3 alignment**: this table is a JOIN-target for drive_summary; B-XXX drive_summary writer contract (separate story candidate, see Spool's Spec 3) defines what drive_summary itself must populate. The two tables together are the "full per-drive grading context" Spool needs.
