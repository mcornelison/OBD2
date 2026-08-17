# From Rex (Ralph / Agent 1) → Marcus (PM) — US-214 complete

**Date:** 2026-04-21
**Branch:** `sprint/wiring`
**Story:** US-214 — US-206 dual-writer reconciliation, one DriveSummary row per drive
**Status:** `passes: true`

## TL;DR

Option 1 (Pi writes first, analytics updates) shipped. `_ensureDriveSummary`
now finds-or-creates by `(source_device, drive_id)` and updates the
existing Pi-sync row in place. `extractDriveBoundaries` extended to carry
`drive_id` through from connection_log. New `scripts/reconcile_drive_summary.py`
one-shot migration merges pre-existing dual rows on the live DB. 18 new
tests, 2943 → 2961 fast suite (0 regressions, 572s). Sprint 16 now 5/10 shipped.

## What changed

| File | Change |
|---|---|
| `src/server/services/analysis.py` | `extractDriveBoundaries` 3-tuple return (start, end, drive_id\|None); `_ensureDriveSummary` find-or-create by (source_device, drive_id); `enqueueAutoAnalysisForSync` passes driveId |
| `src/server/db/models.py` | `DriveSummary` docstring rewritten for US-214 contract + invariants. NO schema changes (nullable columns preserved for race safety) |
| `specs/architecture.md` | Section 5 Drive-Start Metadata subsection replaces dual-writer prose with Reconciled single-writer semantics (4-step contract + migration procedure + invariants) |
| `scripts/reconcile_drive_summary.py` | NEW one-shot migration: `--dry-run` / `--execute` / `--window-seconds` (default 60). Redirects DriveStatistic + AnomalyLog drive_id refs before DELETE. Idempotent. |
| `tests/server/test_drive_summary_reconciliation.py` | NEW 16 tests (extractor × 4, Pi-first × 2, analytics-first × 3, row_count × 1, migration × 6) |
| `tests/server/test_drive_report_single_row.py` | NEW 2 tests verifying single row per drive post-reconciliation |
| `tests/server/test_sync_auto_analysis.py` | 3 existing boundary tests updated from 2-tuple to 3-tuple return |

## Verification

- `pytest tests/ -m "not slow" -q`: **2961 passed / 17 skipped / 19 deselected** (US-213 baseline 2943 → +18 new, 0 regressions, 572s)
- `ruff check`: clean across all 6 touched files
- `validate_config.py`: 4/4 OK
- `sprint_lint.py`: 0 errors (33 unchanged informational warnings on other stories)
- CLI smoke: `python scripts/reconcile_drive_summary.py --dry-run --database-url sqlite:///<empty>` → `merged=0 orphaned_analytics=0 orphaned_pi_sync=0 (mode=dry-run, window=60s)` — end-to-end wiring confirmed

## Post-deploy procedure (CIO/PM)

Once Sprint 16 merges and deploys to chi-srv-01:

```bash
# 1. Dry-run to see the merge plan
python scripts/reconcile_drive_summary.py --dry-run

# 2. Execute when the plan looks right
python scripts/reconcile_drive_summary.py --execute

# 3. Verify one row per drive post-reconciliation
ssh mcornelison@10.27.27.10 'mysql obd2db -e "SELECT COUNT(*), COUNT(DISTINCT (source_device, drive_id)) FROM drive_summary WHERE source_device IS NOT NULL"'
# Counts must be equal after reconciliation
```

Pre-US-200 analytics-only rows (no Pi partner) stay as-is — the migration
reports them as `orphaned_analytics` so you can decide whether to manually
adjust. Orphaned Pi-sync rows likewise preserved.

## Scope manifest drift (informational)

US-214 `scope.filesToTouch` lists `src/server/models/__init__.py` but
server models actually live at `src/server/db/models.py`. Touched the
correct path. Noted in US-214 `completionNotes`.

## Design notes worth capturing

- **UNIQUE + NULL semantics is load-bearing**: legacy analytics-only rows
  (source_device NULL) coexist with Pi-sync rows via SQL's NULL-is-distinct
  UNIQUE. If a future story ever tightens to NOT NULL, the reconciliation
  migration must run first.
- **is_real was never populated in production code pre-US-214**: grep showed
  it only set in tests. Calibration filter `is_real.is_(True)` was effectively
  filtering out all analytics-created rows. US-214 sets `is_real=True` in
  the reconciled update path — calibration baselines should start seeing
  real drives after the next auto-analysis run.
- **DriveStatistic/AnomalyLog have integer drive_id without FK**: the
  migration issues UPDATE statements on those tables BEFORE the delete to
  redirect pointers. Future consumers that reference DriveSummary.id need
  the same treatment.

## Sprint 16 status

5/10 shipped: US-210, US-211, US-212, US-213, US-214. Remaining: US-215 (S,
pygame TD audit), US-216 (L, Spool-audit-gated — still waiting on
`offices/pm/inbox/<DATE>-from-spool-power-audit.md`), US-217 (S,
independent of US-216), US-218 (S, I-017 doc dedup), US-219 (S, Spool
review ritual).

Exiting to let ralph.sh start the next iteration.

— Rex
