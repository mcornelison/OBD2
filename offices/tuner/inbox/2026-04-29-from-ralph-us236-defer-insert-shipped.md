# US-236 SHIPPED — drive_summary defer-INSERT (Sprint 19, 3/8)

**To**: Spool
**From**: Rex (Ralph / Agent 1) — Session 108
**Date**: 2026-04-29
**Status**: passes:true, ralph.sh next iteration in progress

## What landed

Sprint 18's US-228 attempted to fix the Drive 3/4/5 cold-start NULL bug
with **Option (b) backfill-UPDATE**: INSERT empty row at drive_start,
UPDATE columns as readings arrive.  Empirically broken — every row
across drives 3, 4, 5 stayed all-NULL.

US-236 is the **Option (a) defer-INSERT** rewrite per your sprint19
consolidated note.  Code-level summary:

* `SummaryRecorder.captureDriveStart` no longer INSERTs immediately on
  empty snapshot.  Returns `inserted=False, deferred=True` instead.
* The detector's per-tick loop (`_maybeProgressDriveSummary`) calls
  `captureDriveStart` repeatedly with the latest snapshot.  First call
  where IAT/BATTERY_V/BAROMETRIC_KPA appears -> INSERT.  At the 60s
  deadline -> `forceInsert=True` + `reason='no_readings_within_timeout'`.
* Schema doNotTouch — `reason` lives on `SummaryCaptureResult.reason`
  + logs only, NOT in the drive_summary row.
* Warm-restart rule preserved: warm + IAT-only is correctly treated as
  "no relevant payload" (the IAT gets filtered by the cold-start rule
  before the INSERT decision), so it defers until BATTERY_V or
  BAROMETRIC_KPA arrives.
* Re-entry safety: a new `_startDrive` overwrites prior deferred state.
  Stateless recorder, no orphan listeners.

## Runtime-validation discriminator

Per `feedback_runtime_validation_required`, the synthetic test
`TestCase1EmptySnapshotProducesNoRow::test_emptySnapshotProducesNoRowAndNoInsert`
**MUST FAIL** against pre-US-236 code (which INSERTed an all-NULL row
at drive_start).  Passing requires the Option (a) change.  This is the
strong-test gate that Sprint 18's tests didn't have.

## Verification

* `pytest tests/pi/obdii/test_drive_summary_defer_insert.py` — 14/14 passing
* `pytest tests/ -m "not slow"` — 3379 passed / 0 failed (was 3366 baseline post-US-235)
* `ruff check` — clean on touched files
* `validate_config` — OK
* `sprint_lint` — 0 errors / 24 pre-existing warnings

## Next-drive expected behavior

After this lands on the Pi (CIO redeploy), Drive 6 onward:

* Cold-start (key off > 30s): drive_summary row appears within seconds of
  the first IAT/BATTERY_V/BARO arriving (typically tier-2 poll cycle 1-2),
  populated with whatever's available.  Subsequent ticks fill remaining
  NULLs via backfillFromSnapshot.  By drive-end, expect all 3 fields
  non-NULL on healthy ECU response.
* Warm restart (engine running before drive_start): row appears when
  BATTERY_V or BARO arrives (IAT gets filtered).  ambient_temp_at_start_c
  stays NULL (US-206 invariant preserved).
* ECU silent for full 60s window: row appears at the deadline with all 3
  NULL + log line `drive_summary INSERT | drive_id=N | ... | reason='no_readings_within_timeout'`
  in the Pi journal.  Distinct signature from a normal cold-start row.

## Open Sprint 19 items

5 stories remain (US-237 / US-238 P0 + US-239 / US-240 / US-241 P1) for
next agent.  Sprint 19 status post-US-236: 3/8 shipped.

## Observation for Sprint 20+

The doNotTouch on `drive_summary` schema means the timeout `reason` only
exists in logs + SummaryCaptureResult objects — not in queryable rows.
If you eventually want analytics to filter timeout-NULL rows from
no-data-yet-NULL rows, Sprint 20+ could add a `capture_reason` column
(or repurpose `data_source` enum to add `'timeout_no_readings'`).  Today
the distinction is operator-only via journal grep.
