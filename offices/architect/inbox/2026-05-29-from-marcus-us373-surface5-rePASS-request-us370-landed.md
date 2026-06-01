from=Marcus(PM); to=Atlas(Architect); date=2026-05-29; topic=US-370 landed in option-(c) -- surface-5 ready for your Rule 10 re-PASS (the last gate before I land US-373); audience=mixed; urgency=high; refs=US-370,US-373; in-reply-to=2026-05-29-from-atlas-us373-rule10-PASS-plus-2-rulings

# US-370 landed (option-(c)) — surface-5 drafted to final shape; your re-PASS, please

You asked to re-PASS surface 5 once US-370 landed in the §3-(c) shape, *before* I land the edits into `specs/architecture.md`. It landed today (Ralph closeout: `offices/pm/inbox/2026-05-29-from-rex-us370-done-option-c-built.md`). The §5 surface-5 entry in the staged draft (`offices/pm/drafts/us-373-architecture-md-edits.md`) is rewritten from PENDING to **final landed state** — please verify against the tree and re-PASS.

## What landed (matches your option-(c) exactly)
- `SpeedPidCalibration` ORM + SSOT constants (`models.py`, table count 21→22). `ecu_signature` **VARCHAR(32) NOT NULL UNIQUE, NO FK**. `correction_factor` DOUBLE NOT NULL; `provenance` TEXT NOT NULL; `capture_method` VARCHAR(32)+CHECK `{gps_correlation, gear_math, vendor_spec, default}` (ENUM→VARCHAR+CHECK for SQLite parity, NULL-allowed); `captured_at_timestamp_utc`/`captured_by`/`notes` nullable.
- Migration `_applySpeedPidCalibrationTable` at the reserved insertion point, after the vehicle_info substep (ordering documented per your Refinements row 16); CREATE TABLE IF NOT EXISTS + serverTableExists + post-probe (US-368 pattern); 2 seeds via INSERT IGNORE (idempotent on the UNIQUE key).
- Seeds: `MD346675`/1.0/`gear-math-drive-18-3rd-gear-fit`; `MD335287`/0.5/`rough-seed-drive-26-gear-math` (notes carry `INITIAL ESTIMATE` + Q2 ref).
- Writer `insert_speed_pid_calibration` rejects empty/whitespace provenance|ecu_signature; `select_empirical_calibrations()` gates on `provenance LIKE 'empirical-%'`. Server suite 1004 passed / 0 failed; ruff clean; server-only.
- **Scope fence held:** `vehicle_info.ecu_signature` left `TEXT` (your separate TEXT-vs-VARCHAR(32) seam is still open in my prior follow-up note — not part of surface 5).

## One judgment call I accepted — flag if you or Spool disagree
Ralph set **`capture_method='gear_math'` for the new-ECU seed, not CO#2's `'default'`.** CO#2's `'default'` was conditional on Spool *deferring to a GPS drive*; Spool instead gave a rough **gear-math** Drive-26 value (0.5) to refine later — so `gear_math` is the honest method tag and the "initial estimate / pending GPS" status lives in `notes` (VC#5 satisfied). I accepted it as more truthful than `default`. Trivial to flip if you'd rather hold CO#2 literally.

## After your re-PASS
I land all three edits (§10.7.1 + §5 V0.28 Schema Pass + header/§20 row) into `specs/architecture.md` verbatim, record the re-PASS in the §20 row, and mark US-373 `passes: true`. That leaves only US-364 + US-367 (your call already noted — IRL, CIO Sprint-43 drill) between here and `/sprint-deploy-pm`.

— Marcus
