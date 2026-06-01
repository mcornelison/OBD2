# US-371 DONE -- drive_statistics.drive_id -> summary_id rename verified complete

from=Rex(Dev); to=Marcus(PM); date=2026-05-28; topic=US-371 closeout + cross-agent gates; refs=US-371,F-076,US-373

## Summary
US-371 (Sprint 43 / V0.28.0 / F-076): the misleading `drive_statistics.drive_id` column
renamed to `summary_id` (it always held a `drive_summary.id` FK, never a Pi drive_id).
COMPLETE rename, no alias. SERVER-ONLY (no Pi file touched -- Pi-side drive_statistics
retired in US-351).

The ORM + v0010 migration substep + all live consumer updates were ALREADY in the tree
from the prior US-365-era session (per my own last close note). This iteration RECONCILED
+ VERIFIED completeness and closed the one gap that verification surfaced:

- **Found + fixed a stale live ORM reference**: `tests/server/test_drive_statistics_writer.py:429`
  still did `s.drive_id` on a `DriveStatistic` row (would `AttributeError` if un-skipped).
  The suite was GREEN only because that test is `@pytest.mark.skip` (superseded by US-350).
  Updated -> `s.summary_id`.
- **V-4 grep zero-match achieved** in `src/` + `tests/`: reworded the descriptive
  comments/docstrings that used the dotted `drive_statistics.drive_id` form (migration
  mod-history/docstring/section-comment; the dedicated rename-test header/docstring; the
  deploy-context integration-test comment). The integration test's raw-SQL historical-shape
  reconstruction (pre-US-351 `drive_id`) was LEFT INTACT -- it intentionally models old
  production and does not contain the dotted form.

## Gates (runnable, GREEN)
- `pytest tests/server/ -m "not slow"` = **969 passed, 12 skipped, 0 failed** (V-5).
- Targeted re-run (test_db_models + test_migration_0010_us371 + writer + analytics_basic)
  = 117 passed, 3 skipped.
- `ruff check` clean on all touched files.
- `test_db_models.py` carries the locked-in regression net: asserts `summary_id` present AND
  `drive_id` absent on `DriveStatistic` (AC#4 / no-alias at the ORM level).
- ORM `DriveStatistic` has no `drive_id` attribute; migration RENAME substep idempotent +
  wired into `apply()`; all live consumers (basic.py, analysis.py, drive_statistics_compute.py,
  recompute_drive_analytics.py, reports/drive_report.py) use `summary_id`.

## Cross-agent gate NOT self-satisfiable (routed)
- **AC#6 Atlas Rule 10 sign-off**: owned by US-373's `specs/architecture.md` amendment +
  Atlas (same in-sprint precedent as US-361/363/365/372). PENDING. `specs/` is read-only for
  Ralph. The architecture.md schema entry for the drive_statistics rename rides US-373.

## IRL-only (deferred to sprint validationMethod drill -- not runnable from Windows dev box)
- V-1 `DESCRIBE drive_statistics` on chi-srv-01 (shows summary_id, no drive_id).
- V-2/V-3 `SELECT summary_id ... ` succeeds / `SELECT drive_id ...` FAILS against obd2db.
- V-6 `python -m server.cli.recompute_drive_analytics --drive-id 11` post-rename returns
  identical row content (the rename is column-name-only; values unchanged).
  Unit-level equivalent is covered by the green server suite + migration tests.

## A2AL routed
- Spool notified (offices/tuner/inbox/) per conditionalOutcome: his historical session prose
  in `offices/tuner/` mentions the old name -- left as accurate history; he uses `summary_id`
  in any future ad-hoc SQL.

Marked `passes: true` per the in-sprint precedent (all runnable validation GREEN; Atlas Rule 10
gate routed via US-373). Changes UNSTAGED per PM protocol.

## MariaDB note
v0010 uses `ALTER TABLE drive_statistics RENAME COLUMN drive_id TO summary_id` (MariaDB
10.5.2+; chi-srv-01 is well above). The ADD+UPDATE+DROP fallback (conditionalOutcome 2) is
NOT needed.
