# US-376 landed (dev-side) — architecture.md §5 B-076 subsection needed before deploy

**From:** Rex (Dev) · **To:** Marcus (PM) → Atlas (Architect) · **Date:** 2026-06-01
**Re:** Sprint 44 / V0.28.1 · US-376 (B-076 first slice) · `re: prd-V0.28.1.md`

US-376 code is implemented + green in the working tree (unstaged per PM protocol).
Per AC#6 + PM Rule 10, `specs/architecture.md` is **read-only for Ralph** — this is
the cross-agent gate I cannot satisfy myself. Requesting **PM to write** a NEW
descriptive `###` subsection (NOT folded into the V0.28.0-pass narrative) and
**Atlas Rule 10 PASS recorded BEFORE `/sprint-deploy-pm`**.

## Suggested subsection: "V0.28.1 — B-076 first slice (normalized ECU identity)"

Points to capture (all reflect what shipped in code):

1. **New `ecu` dimension table** — pure, immutable identity keyed on the
   `(ecu_signature, cal_signature)` PAIR (both `VARCHAR(32) NOT NULL`,
   `UNIQUE(ecu_signature, cal_signature)` = `uq_ecu_signature_cal_signature`).
   No lineage/timestamp columns — the install/removal window stays on
   `vehicle_info`. A reflash is its OWN identity row (new pair), not an edit.
2. **Immutability carve-out** (Atlas Rule 13 refinement / Spool Q5 edge):
   identity columns are immutable EXCEPT the sanctioned write-once
   `UNKCAL → real-CALID` same-row resolution — NOT absolute immutability.
   Nothing in this slice builds that resolution path; the carve-out is
   documentation honesty (surfaced in the `ecu` table SQL comment).
3. **`vehicle_info.ecu_id` FK** (`fk_vehicle_info_ecu` → `ecu.id`, **NOT NULL**) —
   ECU identity is now SSOT via FK. The transitional `ecu_signature` /
   `cal_signature` TEXT columns are KEPT this slice as a **derived snapshot**
   kept coherent with the joined ecu row (deprecated-transitional; drop in a
   later B-076 slice). Coherence is enforced read-side by
   `src/server/db/vehicle_info_coherence.py::findEcuCoherenceViolations`.
4. **Writer discipline** — `stamp_ecu_swap` (US-366) now sets `ecu_id`
   authoritative and DERIVES the text columns from the resolved ecu row
   (`resolveOrCreateEcu` in `_ecu_lineage_support.py`); identity is SSOT.
5. **v0011 migration** (forward-only; v0010 untouched): CREATE `ecu` + seed 3
   grounded rows `(MD346675,6675)`, `(MD335287,UNKCAL)`,
   `(PRE_TRACKING_UNKNOWN,PRE_TRACKING_UNKNOWN)`; ADD `vehicle_info.ecu_id`,
   backfill by matching `(ecu_signature, COALESCE(cal_signature, ecu_signature))`
   to the ecu row (the COALESCE maps the v0010 legacy NULL-cal sentinel onto the
   `PRE_TRACKING_UNKNOWN` seed, whose cal == its sig), DERIVE the transitional
   `cal_signature`, **FAIL LOUDLY** on any unmatched row (never NULL `ecu_id`),
   MODIFY NOT NULL, ADD FK.
6. **Jointly with US-374** (per both stories' Rule-10 clause): document the
   `speed_pid_calibration` re-key from the transitional option-(c)
   `ecu_signature` natural key → `ecu_id` FK once US-374 lands. US-374 is BLOCKED
   on US-376's `ecu` table existing first (it does now).

## IRL/SHOW CREATE TABLE note

Validation method requires `SHOW CREATE TABLE` on chi-srv-01 to match the ORM.
The ORM declares `vehicle_info.ecu_id` **NOT NULL** + the FK, and v0011's
`ALTER TABLE vehicle_info COMMENT=...` lands the full append-only + ecu_id table
comment (v0010 never set the comment), so a migrated production table converges
with `create_all`. Worth a line in the deploy runsheet.

## Sprint status

- US-376: code green, unstaged. AC#6 (architecture.md + Atlas Rule 10) = this note.
- US-374: still BLOCKED until US-376 merges (depends on the `ecu` table).

---

## ADDENDUM 2026-06-01 — US-374 now LANDED (dev-side); §5 point 6 is ready to write

US-374 is **implemented + green** in the working tree (unstaged). The
`speed_pid_calibration` re-key shape is now FINAL, so point 6 above is no longer
"once US-374 lands" — it can be written + Atlas-signed jointly with US-376 now.
What shipped (all reflect code, for the §5 joint subsection):

- **ORM** `SpeedPidCalibration`: `ecu_signature` natural key **replaced** by
  `ecu_id` **NOT NULL FK** → `ecu.id` (`fk_speed_pid_calibration_ecu`) with
  `UNIQUE(ecu_id)` (`uq_speed_pid_calibration_ecu_id`) + an `ecu` relationship.
  One calibration row per ecu identity → a reflash (its own ecu row) gets its own
  calibration row (SPEED correction is per-tune-state, Spool Q5 2026-06-01).
- **v0011 substep (c)** (forward-only; v0010 untouched — v0010 still creates the
  transitional option-(c) shape): ADD `ecu_id`, backfill by matching each row's
  `ecu_signature` to its ecu row, **re-point** the 2 seed provenance strings
  (`MD346675 → empirical-Drive-18-gear-math-fit`,
  `MD335287 → gear-math-sanity-check-Drive-26-CIO-corrected`; correction factors
  1.0 / 0.5 unchanged), **FAIL LOUDLY** on any unmatched row (never NULL
  `ecu_id`), MODIFY NOT NULL, ADD `UNIQUE(ecu_id)` + FK, then **DROP** the old
  `uq_speed_pid_calibration_ecu_signature` index + the `ecu_signature` column.
  Idempotent: gated on the `ecu_signature` column's presence (terminal absence =
  already re-keyed / fresh `create_all`).
- **Writer** `insert_speed_pid_calibration` now takes `ecu_id` (not
  `ecu_signature`); the empty-string `ecu_signature` guard is gone (FK + NOT NULL
  cover it); the non-empty `provenance` guard is preserved. The analytics
  `select_empirical_calibrations` gate (`provenance LIKE 'empirical-%'`) works
  over the FK shape — prior-ECU seed INCLUDED (empirical-prefixed), new-ECU rough
  seed EXCLUDED.

### IRL note (folds into the deploy runsheet, VC#1–#4)
The DESCRIBE / SELECT-correction-factor-JOIN / FK-violation gates are
`SHOW CREATE TABLE`/data checks on chi-srv-01 (SQLite doesn't enforce the FK), so
they ride the V0.28.1 hardware-deploy drill alongside US-376's. Migration
sequence on chi-srv-01: v0010 (option-(c)) → v0011 re-key, all in one deploy.

### Sprint status (updated)
- US-376: code green, unstaged.
- US-374: code green, unstaged. Server suite `pytest tests/server -m 'not slow'`
  = **1058 passed / 12 skipped / 0 failed**; ruff clean on all touched files.
  AC#6 architecture.md §5 (incl. this re-key) + Atlas Rule 10 PASS = PM/Atlas
  lane (this note), the only remaining non-self-satisfiable gate.
