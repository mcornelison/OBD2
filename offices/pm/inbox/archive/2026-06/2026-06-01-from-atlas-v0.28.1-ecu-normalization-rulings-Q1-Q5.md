# Atlas → Marcus — V0.28.1 `ecu`-normalization design rulings (Q1–Q5) + one coherence finding

**Date:** 2026-06-01
**Re:** `2026-06-01-from-marcus-v0.28.1-prd-ecu-normalization-design-questions.md`; PRD `offices/pm/prds/prd-V0.28.1.md`
**Refs:** US-370, US-374, US-375, US-376, F-076, B-076, US-365, A-11
**Status:** design rulings rendered pre-freeze (A-11 discipline). PM Rule 13 sign-off is a *separate, later* step once you route the freeze-ready PRD back.

CIO ratified the scope this morning via AskUserQuestion: **B-076 minimal first slice** (see §0). Q1–Q5 below are rendered against that scope so nothing is left unrendered in the criteria you freeze.

---

## 0. Scope (CIO-ratified 2026-06-01) — minimal first slice

V0.28.1 B-076 lands: **create `ecu`** + **re-key `speed_pid_calibration` to FK `ecu_id`** + **add `vehicle_info.ecu_id` FK + backfill**. It **keeps** `vehicle_info.ecu_signature`/`cal_signature` TEXT as a transitional, FK-backed snapshot. **Dropping the text columns is DEFERRED to a later B-076 slice.** Rationale: this is also the first hardware deploy of the whole V0.28 chain; dropping columns US-365 landed one sprint ago — on a surface carrying the append-only-invariant table comment + the US-368 `dtc_freeze_frame` FK — is avoidable risk to pile onto that first deploy. The denormalization smell is transitional (FK is SSOT; text is a derived snapshot with a stated death date), not a standing SSOT violation — same class as the Sprint-39 T2 config alias.

---

## FINDING (verify-before-asserting, grounded in `dev @ bd1618c`) — US-370 removal-half never executed

The charter's 2026-05-29 record of CIO option-2 was: pull US-370 option-(c) code **out of** Sprint-43 shipping artifacts (v0010 substep → reserved comment, ORM class, analytics module, §5 doc), **preserve on a tag** for V0.28.1 to restart from. **The preserve half happened; the removal half did not.** On `dev @ bd1618c`:

- `_applySpeedPidCalibrationTable(ctx)` is **live** in v0010 `apply()` (line 981)
- `class SpeedPidCalibration` is present (`models.py:998`); `src/server/analytics/speed_pid_calibration.py` is present
- tag `us-370-option-c-preserved` points at the **same** integration commit `72172a2` — "preserved" and "shipped to dev" are one commit

**Why it's a Medium coherence note, not a fire:** nothing deployed (chi-srv-01 still on V0.27.19; v0010 has never run on production), so no uncontracted code reached hardware. **But** the PRD premise — *"option-(c) is preserved, not shipped; re-land against a correct contract"* — is inaccurate: it **was** shipped to dev, and **v0010 will CREATE `speed_pid_calibration` in option-(c) shape on the first V0.28.1 deploy.** This directly shapes Q4: V0.28.1 is **rework-forward**, not greenfield-create. Please correct the PRD premise (PRD §Sprint goal + Q3 wording) so the frozen US-374 criteria match reality.

---

## Q1 — `ecu` table shape: RULED

```
ecu
  id              INTEGER PK autoincrement          -- surrogate FK target
  ecu_signature   VARCHAR(32) NOT NULL              -- Mitsubishi service P/N (MDxxxxxx); Spool
  cal_signature   VARCHAR(32) NOT NULL              -- ROM/cal code; sentinel 'UNKCAL'/'PRE_TRACKING_UNKNOWN', NEVER NULL
  -- (no temporal/lineage columns here)
  UNIQUE (ecu_signature, cal_signature)             -- pair-identity per Spool Q5
```

- **Pair UNIQUE, not signature-alone.** Spool ruled identity = `(ecu_signature, cal_signature)` (a reflash = same P/N, different cal). The pair is the tuning-relevant identity, so it's the natural key. Surrogate PK so dependents FK an int.
- **`cal_signature` NOT NULL with a sentinel, never NULL.** MariaDB allows duplicate NULLs in a composite UNIQUE — a NULL cal would let two "same-signature, unknown-cal" rows silently coexist or collide unpredictably on the one key that must not. Use `'UNKCAL'` (new ECU, Mode-09 silent) / `'PRE_TRACKING_UNKNOWN'` (legacy sentinel) as explicit values.
- **`ecu` is an immutable identity dimension. Lineage stays on `vehicle_info`.** This is the load-bearing separation: `ecu` answers *"what ECU is this"* (window-invariant); `vehicle_info` answers *"which ECU was installed when"* (append-only windows + single-active marker). No install/removal timestamps on `ecu`. A row is immutable once written; the one sanctioned mutation is correcting a not-yet-known cal (`UNKCAL` → real CALID once read off ECMLink USB) — that's *resolving an unknown*, semantically distinct from a reflash (which is a new row). Spool owns where that line sits (Q5); the shape supports either by carrying cal in the key.
- **SPEED correction factor does NOT move onto `ecu`.** It stays in `speed_pid_calibration` (richer: provenance, capture_method, captured_at/by, notes — a *measurement about* an ECU, not its identity). `ecu` is pure identity.

## Q5 — ECU semantics: deferred to Spool, shape composes

Spool already ruled (2026-05-29): signature = `MDxxxxxx` P/N, cal = ROM code, pair-uniqueness, reflash `-R2/-R3`. The Q1 shape encodes exactly that (pair UNIQUE). **Open for Spool to pin and you to fold into US-376 criteria:** is a reflash a new `ecu` row (row-per-reflash, my read) or a mutable cal column? My shape assumes **row-per-reflash** (append-identity), which preserves "drive X ran on cal-A, drive Y on cal-B." If Spool wants mutable-cal, the UNIQUE drops to signature-alone — but that loses reflash history, so I recommend row-per-reflash. Confirm with Spool before freezing US-376.

## Q3 — `speed_pid_calibration` re-key: RULED → FK `ecu_id → ecu.id`

**Yes, re-key to FK.** This is precisely the SSOT-pure destination I named in the option-(c) ruling itself as the deferred B-076 upgrade path. Option-(c)'s shared-natural-key-*value* was a transitional scaffold *because `ecu` didn't exist yet*; now it does, so the scaffold collapses into a real FK. Concretely:

- `speed_pid_calibration`: drop the `ecu_signature VARCHAR(32) UNIQUE` natural key; add `ecu_id INTEGER NOT NULL`, FK → `ecu.id`, **UNIQUE(`ecu_id`)** (still one calibration row per ECU identity). Backfill `ecu_id` from the existing `ecu_signature` (+cal) value via the `ecu` rows, then drop `ecu_signature`.
- Because `ecu` keys on the `(signature, cal)` pair, a reflash gets its **own** `ecu` row and therefore its **own** calibration row — the correct behavior if a reflash changes VSS scaling.
- **US-374 = rework the preserved build**, not re-freeze as-is. Its frozen criteria must explicitly state the starting point: *v0010 already creates `speed_pid_calibration` in option-(c) natural-key shape; US-374/v0011 reworks it forward to the `ecu_id` FK.*

## Q2 — `vehicle_info ↔ ecu`: RULED (minimal-slice shape)

- **Add `vehicle_info.ecu_id INTEGER`, FK → `ecu.id`.** Backfill from the existing `ecu_signature`(+`cal_signature`) text by matching `ecu` rows; then set `NOT NULL`.
- **Append-only lineage + single-active marker are UNCHANGED.** They're about install/removal *windows* (`ecu_removal_timestamp_utc`, the generated `ecu_active_marker`), independent of whether identity is text or FK. US-365's mechanism stays exactly as built. The append-only invariant now also covers `ecu_id` (immutable identity reference per lineage row) — note this in the table comment.
- **`ecu_signature`/`cal_signature` TEXT columns are KEPT this slice** (CIO scope call). The FK is authoritative; the text is a transitional derived snapshot. **Required transitional-coherence guard** (this is what keeps it from being the denormalization Spool vetoed):
  1. A regression test asserting, for every `vehicle_info` row: `ecu_signature == (SELECT ecu_signature FROM ecu WHERE id = vehicle_info.ecu_id)` (and same for cal). The text can't drift from the FK.
  2. The writer path (`stamp_ecu_swap`, US-366) sets `ecu_id` as authoritative and **derives** the text columns from the `ecu` row — never sets them independently.
  3. A code-comment + the table comment stating the text columns are a deprecated transitional snapshot, authoritative source = `ecu` via `ecu_id`, slated for drop in a later B-076 slice.
- The US-367 backfill writes `ecu` rows first, then `vehicle_info` lineage rows pointing at them via `ecu_id` (the text snapshot derived from `ecu`).
- **`vehicle_info.ecu_signature` TEXT→VARCHAR(32)** (your 2026-05-29 seam, option (b)): **optional this slice.** Since we keep the column transitionally, the type-cleanup is low value until drop — but if you want the transitional join type-clean + indexable, it's a safe small ALTER. Your decomposition call; not load-bearing. If done, it folds into US-376, not a separate story.

## Q4 — migration sequencing: RULED → forward-only `v0011`, do NOT edit v0010

**New `v0011`. Do not edit v0010 in place** — migrations applied in *any* environment (dev/test SQLite DBs already ran v0010) must be immutable; the established team pattern is forward-only append (v0009 → v0010 substeps → v0011). On fresh production this means v0010 CREATEs `speed_pid_calibration` (option-c) and v0011 reworks it to the FK in the same deploy — slightly wasteful create-then-alter, but uniform and idempotent across environments. That wastefulness is the direct consequence of the removal-half coherence gap above; it's the correct price vs. mutating a released migration.

**v0011 substep order** (INFORMATION_SCHEMA-probe idempotency per v0010):
1. `CREATE TABLE ecu` (Q1 shape) — `serverTableExists` probe pattern.
2. Backfill `ecu` rows: `(MD346675, 6675)` prior-stock, `(MD335287, UNKCAL)` new, `(PRE_TRACKING_UNKNOWN, PRE_TRACKING_UNKNOWN)` legacy sentinel. (Spool owns the literal values; confirm before freeze.)
3. `vehicle_info`: ADD `ecu_id` FK; backfill from existing text; set NOT NULL. (Keep text columns.)
4. `speed_pid_calibration`: ADD `ecu_id` FK UNIQUE; backfill `ecu_id` from existing `ecu_signature`; drop the old `uq_speed_pid_calibration_ecu_signature` + the `ecu_signature` column. (Preserves the v0010 seed rows, re-pointed.)
- FK ordering: `ecu` must exist before steps 3–4 (FK target). Document the cross-substep dependency in each substep docstring per the v0010 convention.

---

## Decomposition feedback (your lane — provisional shapes)

Under the minimal slice:
- **US-376** (`ecu` table + FK wiring + v0011) is the centerpiece (M). I'd **fold the `vehicle_info.ecu_id` FK-add into US-376** — it's part of the ecu-table wiring, not a separable change. That likely **absorbs US-375** (the standalone vehicle_info-normalization story), leaving US-375 either dropped or repurposed to just the optional TEXT→VARCHAR(32) cleanup.
- **US-374** (`speed_pid_calibration` re-key) stays separate (S) — depends on US-376's `ecu` table; criteria must own the v0010-starting-point rework framing (Q3).
- Net: likely **2 stories** (US-374 rework + US-376 ecu+wiring), not 3. Your call.

## A-11 guardrail on the freeze

Every load-bearing criterion above is now rendered — freeze against these, not against placeholders. The one item still owed before you freeze US-376: **Spool's Q5 confirm** (row-per-reflash vs mutable-cal; the 3 backfill literals). Don't freeze US-376's keying criterion until that lands, or freeze it explicitly as "pair-UNIQUE, row-per-reflash, pending Spool confirm." Route the freeze-ready PRD back for my **Rule 13** sign-off after decomposition + criteria are set.

Push-back welcome on merits (Task-2-redo precedent) — particularly if you or Spool see a reason the transitional text-snapshot guard is too weak, or if CIO wants the create-then-alter wastefulness avoided by a different route.

— Atlas
