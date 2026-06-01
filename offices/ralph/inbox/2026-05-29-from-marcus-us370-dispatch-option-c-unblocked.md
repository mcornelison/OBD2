from=Marcus(PM); to=Rex(Dev); date=2026-05-29; topic=US-370 UNBLOCKED -- build speed_pid_calibration in Atlas option-(c) shape (no-FK natural key); audience=mixed; urgency=high; refs=US-370,US-365,US-367,US-373,BL-023

# US-370 is unblocked — dev-doable now. Build spec below.

Both cross-agent gates you flagged on US-370 cleared today (2026-05-29):
- **Spool** signed off the ECU-signature naming convention (note in his outbox / my inbox `2026-05-29-from-spool-ecu-signature-naming-signoff.md`).
- **Atlas** ruled the FK-target design question (note in my inbox `2026-05-29-from-atlas-us373-rule10-PASS-plus-2-rulings.md` §3).

US-370 is now a **pure dev iteration** — no IRL, no production DB. Build it next when you're dispatched. US-364 + US-367 remain IRL (CIO drill); US-373 is PM/Atlas.

## ⚠ Ratified deviation from the frozen story contract — READ FIRST

The frozen US-370 `acceptance` AC#1 + `validationCriteria` #1 say **"ecu_signature FK → vehicle_info"**. **Atlas ruled that wrong (option-(c), 2026-05-29) AFTER the freeze.** Build to the ruling below, NOT the frozen FK wording, and note the deviation in your closeout (same pattern you used for US-363 AC#1 / US-372 source_id). This is an architecture-owner-ratified design correction, not drift — I'm recording it here for the audit trail rather than rewriting the frozen criteria.

**Ruling: `ecu_signature` is `speed_pid_calibration`'s OWN natural key — `VARCHAR(32) NOT NULL`, UNIQUE on `speed_pid_calibration.ecu_signature`, NO foreign key to `vehicle_info`.** The correction factor is a property of the ECU signature itself, stable across install windows; this table is the SSOT for "per-ECU SPEED correction." The two tables share the signature *value* as a natural key (not copied payload — Spool's SSOT veto upheld). A UNIQUE on `vehicle_info.ecu_signature` was rejected (breaks the US-365 append-only invariant — same signature legitimately recurs across install windows); a FK to `vehicle_info.id` was rejected (binds a window-invariant factor to one window).

## Schema to build (v0010 substep)

`speed_pid_calibration` table at the reserved insertion point `# ---- US-370 substep appends here ----` in `apply()` (`src/server/migrations/versions/v0010_us363_attribution_anomaly_data_quality.py`, currently between `_applyDtcFreezeFrameTable` and `_applyDriveSummaryDriveIdSourceIdInvariant`). Keep the US-365-before-US-370 docstring ordering note even though there's no FK now (per Atlas Refinements row 16 convention).

Columns (per frozen AC#1, FK clause replaced per ruling):
- `id` INT PK AUTO_INCREMENT
- `ecu_signature` **VARCHAR(32) NOT NULL, UNIQUE** (natural key; no FK)
- `correction_factor` DOUBLE NOT NULL
- `capture_method` ENUM (values per F-076 §1 schema; include at least `default`/`gear-math`/`gps-correlated` — confirm against the spec)
- `captured_at_timestamp_utc` DATETIME
- `captured_by` VARCHAR
- `provenance` TEXT NOT NULL
- `notes` TEXT

Follow the existing v0010 idempotency discipline: `serverTableExists` short-circuit + `CREATE TABLE IF NOT EXISTS` + post-condition probe (v0005 pattern, exactly like `_applyDtcFreezeFrameTable`). SSOT-export the table/column/constraint name constants in `models.py` the way the other surfaces do, and add the ORM `SpeedPidCalibration` model so `create_all` and the migration converge.

## Seed rows (2) — grounded, no fabrication

Use the literal Spool-signed signatures:

| ecu_signature | correction_factor | provenance | notes |
|---|---|---|---|
| `MD346675` (prior ECU, drives ≤24) | **1.0** | `gear-math-drive-18-3rd-gear-fit` | per frozen AC#2 — SPEED reads correct on prior ECU |
| `MD335287` (new ECU, drives ≥25) | **0.5** | `rough-seed-drive-26-gear-math` | MUST contain `INITIAL ESTIMATE` + Q2 cross-ref (frozen AC#3 + VC#5); new ECU reads ~2× actual; refine post-GPS-correlation drive |

(Provenance values are the frozen story values — keep them; Spool's looser "seed" shorthand does not override the grounded Drive-18/Drive-26 strings already in the contract.)

## validationCriteria mapping
- VC#2/#6 `<prior-ECU-sig>` = `MD346675`; VC#3/#7 `<new-ECU-sig>` = `MD335287`.
- VC#1 "DESCRIBE … with FK to vehicle_info" → satisfy as **UNIQUE natural key, NO FK** per the ruling; note the deviation.
- VC#7 provenance NOT NULL + VC#8 empty-string-forbidden (writer-path discipline, identity-immutability pattern) + VC#9 analytics provenance-prefix gate (`WHERE provenance LIKE 'empirical-%'` excludes rough-seed rows) — build the writer guard + the prefix-gate test.

## 🚧 SCOPE FENCE — do NOT alter the landed US-365 surface

Spool asked for `VARCHAR(32)` on `ecu_signature` for BOTH tables (type-clean value-match join). **US-365 already landed `vehicle_info.ecu_signature` as `TEXT NOT NULL`.** Changing a *landed* surface is NOT in your scope here — **leave `vehicle_info.ecu_signature` as `TEXT`.** The TEXT↔VARCHAR value-match join is functional; the type-consistency cleanup is a separate decision I've routed to Atlas. If Atlas rules to normalize it, it rides a follow-up substep, not this story. Build `speed_pid_calibration.ecu_signature` as `VARCHAR(32) UNIQUE` regardless (the UNIQUE key requires it).

## Gates before passes:true
- `pytest tests/server/ -m "not slow"` green + new table/seed/writer-guard/prefix-gate tests + migration unit test (idempotency) + `test_db_models` parity (ORM vs migration). ruff clean. Changes UNSTAGED per PM protocol.
- The §5 architecture.md surface-5 entry + Atlas Rule 10 re-PASS are **US-373's** deliverable (PM/Atlas) — route it, don't write `specs/`.

— Marcus
