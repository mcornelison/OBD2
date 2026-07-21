# I: startup_log US-263 7-column schema guard fails vs US-419 `data_quality` column

- **Found by:** Rex (Ralph agent), Sprint 60 / US-474, 2026-07-20
- **Type:** pre-existing test/schema drift (NOT a US-474 regression)
- **Severity:** medium — blocks a clean `pytest tests/pi -m "not slow"` (2 reds)
- **Owner routing:** whoever owns the US-263 startup_log schema guard vs US-419
  (F-080) `data_quality` reconciliation (diagnostics / boot-log). Out of scope
  for US-474 (DTC / connection-lock), so scope-fenced and filed here.

## Symptom

`pytest tests/pi -m "not slow"` has exactly 2 failures, both in
`tests/pi/diagnostics/test_boot_reason_boot_id.py::TestStartupLogSchema`:

- `test_startupLogSchema_matchesUs263CanonicalColumnSet`
- `test_startupLogSchema_columnCount_isSeven`

Both reproduce **in isolation** (`pytest .../test_boot_reason_boot_id.py::TestStartupLogSchema`),
so they are independent of the US-474 change (verified: the 7 US-474 files are
all `obdii/` DTC + the new concurrency test; none touch startup_log).

## Root cause

Production code adds an 8th column that the guard test still forbids:

- `src/pi/obdii/database_schema.py:750` —
  `ALTER TABLE startup_log ADD COLUMN data_quality TEXT` (US-419 / F-080
  post-reboot clock-drift flag), written by `src/pi/diagnostics/boot_progress.py`.
- `tests/pi/diagnostics/test_boot_reason_boot_id.py` `TestStartupLogSchema`
  still asserts the canonical set is **exactly 7 columns** (US-263 5-col +
  2026-05-15 honest-instrument `prior_boot_last_stage`/`prior_boot_reason`),
  with no allowance for the US-419 `data_quality` 8th column.

So US-419 shipped the column but the US-263 schema guard (and, per its own
failure message, the US-263 spec) was never updated to 8. The guard's message
says: "If this fails after a deliberate schema change, update both
EXPECTED_COLUMNS and the US-263 spec; do NOT relax the test." — i.e. the
canonical set should become 8 (`+ data_quality`), matching the shipped US-419
behavior. A PM/Atlas call is warranted (is `data_quality` intended to be part of
the canonical startup_log schema, or should it be a separate table?).

## Suggested fix (needs owner confirmation)

If US-419's `data_quality` on `startup_log` is intended canonical: update
`EXPECTED_COLUMNS` to include `('data_quality', 'TEXT', 0, 0)` and bump the
count guard 7 → 8, plus the US-263 spec section — do NOT relax the guard.
