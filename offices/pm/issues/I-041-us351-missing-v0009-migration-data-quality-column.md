# I-041: US-351 ships drive_statistics.data_quality column in model but no v0009 migration

| Field | Value |
|---|---|
| Filed | 2026-05-21 (Session 42, V0.27.17 deploy) |
| Filed By | Marcus (PM) |
| Severity | **CRITICAL** (Sprint 41 US-351 compute path 0% functional in production) |
| Status | Open -- Ralph hotfix dispatched (V0.27.18 patch loop) |
| Related | US-351 (Sprint 41), Sprint 41 `validation.bigDefinitionOfDone` clauses 1+2+3 (all gated on the broken compute) |
| Severity-precedent | Same false-pass class as US-326/US-328/US-348/US-349 -- writer wired in code but trigger/precondition never materializes in production |

## Symptom

V0.27.17 server deploy (`/sprint-deploy-pm` Phase 6b) ran clean through Step 4.7 + 4.8. Step 4.9 backfill (10 drives, 11-20) failed **10/10** with identical SQLAlchemy error:

```
sqlalchemy.exc.OperationalError: (pymysql.err.OperationalError)
(1054, "Unknown column 'data_quality' in 'INSERT INTO'")
[SQL: INSERT INTO drive_statistics (drive_id, parameter_name, min_value,
      max_value, avg_value, std_dev, outlier_min, outlier_max,
      sample_count, data_quality)
      VALUES (...)
      RETURNING drive_statistics.computed_at, drive_statistics.drive_id,
                drive_statistics.parameter_name]
```

Despite 0/10 success, deploy continued (best-effort Step 4.9 pattern) and Step 5+6+7 marked deploy "complete". Server obd-server.service active + health check passed -- but the new B-104 Step 1 compute path is functionally broken on **every** drive synced post-deploy.

## Root Cause

US-351 (Sprint 41) added `data_quality` field to the `drive_statistics` SQLAlchemy model in `src/server/db/models.py:711`:

```python
data_quality: Mapped[str] = mapped_column(
    ...,
)
```

Plus a CHECK constraint at `models.py:686-693` and an index at line 692. New compute writer at `src/server/analytics/drive_statistics_compute.py:214` references the column on INSERT.

**No corresponding migration was added to `src/server/migrations/versions/`.** Latest migration on disk is `v0008_us312_create_baselines.py` from 2026-05-10. The new column exists in the ORM model but not in the production MariaDB table.

The Step 4.5 migration runner ran clean ("[run-all] 0 applied -- registry fully applied (8 already applied; idempotent no-op)"). It had nothing new to apply.

## Why Tests Didn't Catch It

Ralph's US-351 unit tests use `Base.metadata.create_all(engine)` against a fresh sqlite/MariaDB in `tests/server/analytics/`. That helper creates the table from the live ORM definition -- including the new `data_quality` column -- so writes succeed in tests. Production MariaDB has historical tables that pre-date the column; ORM `create_all` is a no-op on existing tables (won't ALTER).

**This is the same false-pass class as US-326/US-328/US-348/US-349**: writer wired correctly in code, mock/test-DB precondition matches code, production precondition does not. US-355 (deploy-context drive simulator, I-040 structural close) was designed to catch this. The test surface uses `Base.metadata.create_all` for the server side as well -- same blind spot.

## Why US-355 Didn't Catch It

US-355 harness creates a fresh temp MariaDB via `Base.metadata.create_all(engine)`. That's the SAME failure mode as the unit tests -- fresh ORM-derived table has the new column. The harness needs to test against a database with **historical schema** to expose migration gaps. This is a US-355 design refinement (option A: run migrations registry-only on fresh DB, do NOT call create_all; option B: snapshot V0.27.16 production schema + replay).

## Fix Plan (V0.27.18 patch loop)

Per `/sprint-deploy-pm` skill Phase 5 "drill-revealed regression" pattern (this is deploy-revealed but mechanically identical):

1. **Ralph writes `v0009_us351_drive_statistics_data_quality_column.py`** -- additive ALTER TABLE adding `data_quality VARCHAR(32) NOT NULL DEFAULT 'unknown'` + the CHECK constraint + the index. Idempotent (IF NOT EXISTS or registry-controlled).
2. **Ralph writes a test** asserting the migration runs cleanly against a v0008-schema DB and that subsequent INSERTs succeed with `data_quality` populated.
3. **Bonus**: Ralph updates US-355 harness to expose this class of gap (option A above -- migration-only fresh DB, no `create_all`).
4. **PM `/sprint-deploy-pm` re-runs Phase 5+ only**: bump V0.27.17 → V0.27.18, redeploy. Step 4.5 migration runner picks up v0009. Step 4.9 backfill re-runs (after manual marker delete -- see I-042) and succeeds 10/10.
5. **Re-verify** Phase 7 + final summary.

## Side issue (filing separately)

The deploy-server.sh Step 4.9 wrote the marker file `/mnt/projects/O/OBD2v2/.backfill-V0.27.17-drives-11-20-complete` despite 0/10 backfill success. The marker logic should require a `success > 0` condition before persistence. Filing as I-042.

## Cross-links

- `offices/architect/inbox/2026-05-21-from-marcus-sprint41-architecture-brief.md` (US-351 was Atlas-pre-gated; the gate criteria did not include "production schema migration verified")
- US-355 harness invariants need revision; folded into the fix plan above
- Skill: `/sprint-deploy-pm` Phase 5 hotfix loop is the prescribed remediation pattern
