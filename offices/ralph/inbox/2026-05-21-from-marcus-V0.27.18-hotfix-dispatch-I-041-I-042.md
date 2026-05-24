# V0.27.18 hotfix dispatch — I-041 + I-042 (Sprint 41 deploy-revealed regressions)

**From**: Marcus (PM)
**To**: Ralph (Dev)
**Date**: 2026-05-21 (Session 42)
**Sprint**: 41 / V0.27.18 (patch loop per `/sprint-deploy-pm` Phase 5)

## Context

V0.27.17 deployed to Pi + chi-srv-01 (Pi `Chi-Eclips-01` @ V0.27.17 / `778522b`; server @ V0.27.17 / `466790c`). Deploy ran clean until Step 4.9 (US-352 backfill drives 11-20) failed **10/10** with:

```
sqlalchemy.exc.OperationalError: (pymysql.err.OperationalError)
(1054, "Unknown column 'data_quality' in 'INSERT INTO'")
```

Two issues filed (read both before starting):
- `offices/pm/issues/I-041-us351-missing-v0009-migration-data-quality-column.md` (CRITICAL)
- `offices/pm/issues/I-042-deploy-server-step49-backfill-marker-written-on-failure.md` (High)

## What you owe (V0.27.18 contract)

Both issues are deploy-revealed Sprint 41 regressions. CIO ratified the `/sprint-deploy-pm` skill's Phase-5 "drill-revealed regression" loop (mechanically identical to deploy-revealed): patch bump V0.27.17 → V0.27.18, fix on the same `sprint/sprint41-bugfixes-V0.27.17` branch, redeploy. No new sprint, no new sprint.json scope — this is a patch to the existing Sprint 41 contract.

### Three deliverables

1. **`src/server/migrations/versions/v0009_us351_drive_statistics_data_quality_column.py`** — additive ALTER TABLE: `data_quality VARCHAR(32) NOT NULL DEFAULT 'unknown'` + the CHECK constraint (mirror `models.py:686-693`) + the `idx_drive_statistics_quality` index. Idempotent. Mirror the structure of `v0008_us312_create_baselines.py`.

2. **Tests** (in the same migration test file or alongside `tests/server/analytics/test_drive_statistics_compute.py`):
   - Migration runs cleanly against a v0008-schema DB (no errors, column appears).
   - Re-running the migration is a no-op (idempotency).
   - Subsequent compute INSERT succeeds with `data_quality` populated.

3. **deploy-server.sh Step 4.9 marker logic fix** (I-042): parse the recompute_drive_analytics CLI's `success=N | skipped=N | failed=N` line; only write the marker when `failed == 0`. On partial/full failure, WARN + leave marker absent so next deploy retries.

### Bonus (if time, NOT V0.27.18-blocking)

4. **US-355 harness gap**: the deploy-context drive simulator uses `Base.metadata.create_all` which masks migration-vs-ORM drift (caught I-041 zero times). Refactor harness to apply migrations registry-only on a fresh DB (do NOT call `create_all`). Discuss with Atlas if scope unclear — this is a US-355 invariant refinement.

### What NOT to do

- Do NOT add a new US-XXX. This is a V0.27.18 patch loop on the existing Sprint 41 contract.
- Do NOT touch `sprint.json` `stories[]` (still 7 stories all passes:true). PM will handle `validation.bigDefinitionOfDone` + sprint version bump.
- Do NOT manually ALTER the production MariaDB. The migration is the canonical path.
- Do NOT delete the stale marker file on chi-srv-01. I'll handle that immediately before Phase 6b redeploy (per I-042 workaround).

## Reference

- Compute writer that needs the column: `src/server/analytics/drive_statistics_compute.py:214`
- Model definition (sole SSOT for the column): `src/server/db/models.py:711` + CHECK at 686-693 + index at 692
- Migration registry pattern: `src/server/migrations/versions/v0008_us312_create_baselines.py`
- Migration runner: `src/server/migrations/runner.py` (already invoked from `deploy-server.sh` Step 4.5)

## On completion

Commit + push to `sprint/sprint41-bugfixes-V0.27.17`. File a short note in `offices/pm/inbox/` confirming the three deliverables landed + any deviations. I'll re-run `/sprint-deploy-pm` Phase 5+ (RELEASE_VERSION V0.27.17 → V0.27.18 + redeploy + verify + Phase 8 summary).

— Marcus
