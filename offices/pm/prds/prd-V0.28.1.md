---
sprint: 44
version: V0.28.1
status: draft
createdAt: 2026-06-01
createdBy: Marcus (PM)
selectedStories: [US-374, US-376]
argusReviewRequired: false
convertedAt: null
sprintJsonPath: null
forksFrom: dev @ bd1618c
---

# PRD — Sprint 44 (V0.28.1): ECU-identity normalization (B-076 first slice) + Sprint-43 carry-forward close

## Sprint goal

Normalize ECU identity (B-076 first slice) and close the Sprint-43 carry-forward. **Two dev stories:** (US-376) create a normalized `ecu` identity dimension keyed on the `(ecu_signature, cal_signature)` pair, wire `vehicle_info` to it via `ecu_id` FK (keeping the TEXT columns as a transitional FK-derived snapshot); (US-374) re-key `speed_pid_calibration` from its option-(c) natural key to an `ecu_id` FK. All human/IRL work (the deploy, F-107 validation drive, US-364 recompute, US-367 ECU backfill, F-005/F-007 HOLD release, Pi power-cycle) is `validation.bigDefinitionOfDone`, NOT stories (CIO 2026-06-01; see `offices/pm/knowledge/feedback-pm-sprint-scope-no-human-irl-tasks.md`).

**This is rework-forward, not greenfield (Atlas coherence finding 2026-06-01).** The Sprint-43 option-(c) `speed_pid_calibration` build was committed to `dev` (commit `72172a2` = the same commit tag `us-370-option-c-preserved` points at). Nothing has deployed (chi-srv-01 is still on V0.27.19; `v0010` has never run on production), so no uncontracted schema reached hardware — but on the FIRST V0.28.1 deploy, `v0010` WILL create `speed_pid_calibration` in option-(c) natural-key shape, and the new `v0011` reworks it forward to the `ecu_id` FK. US-374's criteria own that starting point explicitly.

**First V0.28-chain hardware deploy.** Sprint 43 merged to `dev` without deploying, so the V0.28.1 IRL drill validates the accumulated **43+44** chain (F-107 DriveDetector fix, the V0.28 schema pass, the ECU backfill, attribution-anomaly recompute).

## Selected stories (DEV-doable)
| Story | Title | Feature | Epic | Type | Size |
|---|---|---|---|---|---|
| US-376 | B-076: normalized `ecu` identity table (pair-keyed) + `vehicle_info.ecu_id` FK wiring + transitional-snapshot guard + v0011 migration + architecture.md §5 | F-076 | E-002 | normal | M |
| US-374 | `speed_pid_calibration` re-key forward: option-(c) natural key → `ecu_id` FK (reworks the dev-shipped v0010 build) | F-076 | E-002 | tech-debt | S |

> **US-375 DROPPED.** Atlas's ruling folded `vehicle_info.ecu_id` FK-add into US-376 (it's part of the ecu-table wiring, not a separable change). The optional `vehicle_info.ecu_signature` TEXT→VARCHAR(32) cleanup is low-value while the column is transitional, so it's deferred (not a story this slice). US-375 ID retired for V0.28.1; do not reuse.

## Open questions — ALL RESOLVED 2026-06-01 (Atlas Q1–Q4 + decomposition; Spool Q5)
| # | Question | Resolution | Resolved by |
|---|---|---|---|
| Q1 | `ecu` table shape | `ecu(id INT PK, ecu_signature VARCHAR(32) NOT NULL, cal_signature VARCHAR(32) NOT NULL, UNIQUE(ecu_signature, cal_signature))`. Immutable identity dimension — **no lineage/timestamp columns** (lineage stays on `vehicle_info`). `cal_signature` NEVER NULL (sentinels `UNKCAL` / `PRE_TRACKING_UNKNOWN`) — MariaDB allows duplicate NULLs in composite UNIQUE, which would break the one key that must not collide. SPEED correction factor does NOT move onto `ecu` (stays in `speed_pid_calibration`). | Atlas |
| Q2 | `vehicle_info` ↔ `ecu` | Add `vehicle_info.ecu_id INT` FK→`ecu.id` (backfill from existing text, then NOT NULL). **KEEP** `ecu_signature`/`cal_signature` TEXT this slice as a transitional FK-derived snapshot (drop deferred to a later B-076 slice — CIO scope call; avoids dropping a US-365 surface on the first deploy). Append-only lineage + `ecu_active_marker` UNCHANGED; append-only invariant now also covers `ecu_id`. **Transitional-coherence guard required** (see US-376 AC). TEXT→VARCHAR(32) optional, not load-bearing this slice. | Atlas |
| Q3 | `speed_pid_calibration` re-key | **YES → FK `ecu_id → ecu.id`, UNIQUE(`ecu_id`)**, drop the option-(c) `ecu_signature` natural key. This is the SSOT-pure destination named in the original option-(c) ruling; option-(c) was a transitional scaffold because `ecu` didn't exist yet. US-374 = **rework the dev-shipped build forward** (NOT re-freeze as-is). | Atlas |
| Q4 | Migration sequencing | **New forward-only `v0011`; do NOT edit `v0010`** (migrations are immutable once applied in any env; dev/test SQLite already ran v0010). On fresh prod: v0010 creates `speed_pid_calibration` (option-c), v0011 reworks it — uniform + idempotent. Substep order: (1) CREATE `ecu`; (2) backfill 3 `ecu` rows; (3) `vehicle_info` ADD `ecu_id` FK + backfill + NOT NULL; (4) `speed_pid_calibration` ADD `ecu_id` FK UNIQUE + backfill + DROP old natural key. FK target `ecu` first; document cross-substep deps in docstrings (v0010 convention). | Atlas |
| Q5 | ECU identity semantics | **Pair `(ecu_signature, cal_signature)`, row-per-reflash (append-identity).** SPEED correction is per-tune-state, not per-box (a reflash changes VSS constants while the P/N stamp doesn't). Mutable-cal would erase which tune a drive ran on + has nowhere to put `-R2/-R3`. **Edge:** reading the real CALID off `MD335287` later is NOT a reflash — it's a same-row `UNKCAL`→cal UPDATE (resolving an unknown; keeps the 0.5 seed + drive FKs attached). | Spool |

**Backfill seeds (Spool, confirmed verbatim to Atlas):**
| ecu_signature | cal_signature | correction_factor | provenance |
|---|---|---|---|
| MD346675 | 6675 | 1.0 | `empirical-Drive-18-gear-math-fit` |
| MD335287 | UNKCAL | 0.5 | `gear-math-sanity-check-Drive-26-CIO-corrected` |
| PRE_TRACKING_UNKNOWN | PRE_TRACKING_UNKNOWN | (n/a) | schema sentinel — un-attributable pre-tracking rows |

> Provenance strings above are Spool's 2026-06-01 confirmed values and **supersede the v0010 seed provenance strings**; US-374's re-key substep updates them (note: `MD346675` carries the `empirical-` prefix → included by the `select_empirical_calibrations()` gate; `MD335287` does not → excluded as a rough seed).

---

## Story specifications (freeze-ready — for Atlas Rule 13 review)

### US-376 — normalized `ecu` identity table + `vehicle_info.ecu_id` wiring (F-076, type: normal, size M)

**goal:** As the server schema (B-076 normalization), I want a normalized, immutable `ecu` identity dimension keyed on the `(ecu_signature, cal_signature)` pair that `vehicle_info` references by FK, so ECU identity is SSOT instead of duplicated free-text, and a reflash is its own identity row.

**acceptance:**
1. `v0011` (forward-only; v0010 untouched) CREATEs `ecu(id INT PK AUTOINCREMENT, ecu_signature VARCHAR(32) NOT NULL, cal_signature VARCHAR(32) NOT NULL, UNIQUE(ecu_signature, cal_signature))` — no lineage/timestamp columns. ORM `Ecu` model + SSOT name constants; `create_all` and the migration converge (v0005 `serverTableExists` + post-probe pattern).
2. `v0011` backfills exactly the 3 seed `ecu` rows (table above) idempotently (INSERT-IGNORE on the pair UNIQUE; re-run is a no-op).
3. `v0011` adds `vehicle_info.ecu_id INT` FK→`ecu.id`; backfills `ecu_id` by matching each row's existing `(ecu_signature, cal_signature)` text to its `ecu` row; then `MODIFY ... NOT NULL`. A row whose text matches no `ecu` row → migration FAILS LOUDLY (`MigrationError`), never NULL `ecu_id`.
4. `vehicle_info.ecu_signature`/`cal_signature` TEXT columns are KEPT (transitional). The append-only lineage columns + `ecu_active_marker` generated column + single-active UNIQUE index are UNCHANGED; the append-only table comment is extended to state `ecu_id` is an immutable per-lineage-row identity reference.
4b. **`ecu`-immutability carve-out (Atlas Rule 13 refinement 2026-06-01 — avoid the A-6 false-guarantee class):** the `ecu` table comment + the §5 wording must state `ecu` identity columns are immutable **EXCEPT** the sanctioned `UNKCAL`→real-CALID **same-row** resolution (Spool Q5 edge — a write-once-when-known cal correction, semantically distinct from a reflash, which is a NEW row). Do NOT word it as absolute immutability. The CALID-resolution path is a FUTURE event (`MD335287` stays `UNKCAL` this slice; nothing builds the resolution now) — this clause is documentation-honesty, not new build scope.
5. **Transitional-coherence guard:** a regression test asserts, for every `vehicle_info` row, `ecu_signature == ecu[ecu_id].ecu_signature` AND `cal_signature == ecu[ecu_id].cal_signature` (text can't drift from the FK). The writer path `stamp_ecu_swap` (US-366) sets `ecu_id` as authoritative and DERIVES the text columns from the `ecu` row — never sets them independently. A code-comment + table-comment mark the text columns deprecated-transitional (authoritative source = `ecu` via `ecu_id`; drop slated for a later B-076 slice).
6. **(PM Rule 10 — specs/ is read-only for Ralph; PM writes this clause + Atlas signs)** `specs/architecture.md` gets a NEW descriptive `###` subsection **"V0.28.1 — B-076 first slice"** (per Atlas's US-373 doc-structure ruling; NOT folded into the V0.28.0-pass narrative, which US-373 closed at 5 surfaces) documenting the `ecu` table (incl. the §4b immutability carve-out), the `vehicle_info.ecu_id` FK + transitional-snapshot semantics, and (jointly with US-374) the `speed_pid_calibration` re-key. Atlas Rule 10 PASS recorded BEFORE `/sprint-deploy-pm`.
7. `pytest tests/server/ -m "not slow"` green (+ new ecu-model, migration-idempotency, coherence-guard, writer-derives tests); ruff clean; changes unstaged per PM protocol.

**validationCriteria:**
- action: `DESCRIBE ecu` post-v0011 → outcome: `id` PK, `ecu_signature`/`cal_signature` VARCHAR(32) NOT NULL, `UNIQUE(ecu_signature, cal_signature)`; no timestamp/lineage columns.
- action: `SELECT ecu_signature, cal_signature FROM ecu` → outcome: the 3 seed rows present exactly (MD346675/6675, MD335287/UNKCAL, PRE_TRACKING_UNKNOWN/PRE_TRACKING_UNKNOWN).
- action: INSERT a duplicate `(MD335287, UNKCAL)` → outcome: UNIQUE violation.
- action: INSERT an `ecu` row with `cal_signature` NULL → outcome: NOT NULL violation.
- action: `DESCRIBE vehicle_info` post-v0011 → outcome: `ecu_id INT NOT NULL` FK present; `ecu_signature`/`cal_signature` TEXT still present (transitional).
- action: coherence test over all `vehicle_info` rows → outcome: text columns equal the joined `ecu` row's values (zero drift).
- action: re-run existing US-365 append-only + `ecu_active_marker` single-active tests → outcome: still green (mechanism unchanged).
- action: `stamp_ecu_swap` an ECU then inspect the row → outcome: `ecu_id` set authoritatively, text columns derived from the `ecu` row.
- action: `grep specs/architecture.md` §5 → outcome: `ecu` table + `vehicle_info.ecu_id` documented; Atlas Rule 10 PASS recorded.

**conditionalOutcomes:**
- if a `vehicle_info` row's `(signature, cal)` matches no `ecu` row at backfill → FAIL LOUDLY (surface bad data), do not NULL `ecu_id`.
- if Atlas requests the TEXT-column drop this slice → OUT of scope (CIO deferred to a later B-076 slice); leave columns + guard.
- if the optional TEXT→VARCHAR(32) cleanup is wanted → fold into this story's v0011, not a new story.

**definitionOfDone:** `ecu` table + `vehicle_info.ecu_id` FK live in ORM + v0011; 3 seeds backfilled; coherence guard test green; writer derives text from FK; architecture.md §5 updated + Atlas Rule 10 PASS; server suite green; ruff clean.

---

### US-374 — `speed_pid_calibration` re-key forward to `ecu_id` FK (F-076, type: tech-debt, size S)

**goal:** As server analytics, I want `speed_pid_calibration` keyed by FK `ecu_id → ecu.id` (not the transitional option-(c) `ecu_signature` natural key) so per-ECU SPEED correction references the SSOT `ecu` identity and a reflash gets its own calibration row.

**acceptance:**
1. **Starting point (explicit, per Atlas coherence finding):** `v0010` already creates `speed_pid_calibration` in option-(c) shape (`ecu_signature VARCHAR(32)` + `uq_speed_pid_calibration_ecu_signature`) and that build is on `dev`; US-374's `v0011` substep reworks it FORWARD — it does not create the table.
2. `v0011` substep (after US-376's `ecu` substeps): ADD `speed_pid_calibration.ecu_id INT` FK→`ecu.id` + `UNIQUE(ecu_id)`; backfill `ecu_id` by matching each existing row's `ecu_signature` to its `ecu` row; DROP `uq_speed_pid_calibration_ecu_signature` + the `ecu_signature` column. The 2 v0010 seed rows are PRESERVED, re-pointed to `ecu_id`. A seed whose `ecu_signature` matches no `ecu` row → FAIL LOUDLY.
3. ORM `SpeedPidCalibration`: replace the `ecu_signature` natural key with `ecu_id` FK + relationship; SSOT constants updated; `create_all` + migration converge.
4. Seed `correction_factor`/`provenance`/`capture_method`/`notes` per the confirmed table: MD346675→1.0/`empirical-Drive-18-gear-math-fit`, MD335287→0.5/`gear-math-sanity-check-Drive-26-CIO-corrected` (provenance updated from the v0010 strings per Spool 2026-06-01). `provenance` stays `NOT NULL`; empty/whitespace forbidden by the writer (preserved from v0010).
5. `select_empirical_calibrations()` empirical-prefix gate works over the FK shape (`provenance LIKE 'empirical-%'`).
6. `pytest tests/server/ -m "not slow"` green (+ re-key migration test, ORM parity, gate test); ruff clean; changes unstaged. The architecture.md §5 surface-5 entry is landed jointly via US-376's Rule-10 clause.

**validationCriteria:**
- action: `DESCRIBE speed_pid_calibration` post-v0011 → outcome: `ecu_id INT NOT NULL` FK + `UNIQUE(ecu_id)`; `ecu_signature` column ABSENT; old `uq_speed_pid_calibration_ecu_signature` gone.
- action: `SELECT correction_factor FROM speed_pid_calibration spc JOIN ecu e ON spc.ecu_id=e.id WHERE e.ecu_signature='MD346675'` → outcome: `1.0`.
- action: same join for `MD335287` → outcome: `0.5`.
- action: INSERT a `speed_pid_calibration` row with `ecu_id` not in `ecu` → outcome: FK violation.
- action: INSERT with empty `provenance` → outcome: writer raises.
- action: `select_empirical_calibrations()` → outcome: MD346675 row included (empirical- prefix), MD335287 excluded (rough seed).
- action: re-run v0011 over an already-migrated DB → outcome: idempotent no-op (no duplicate FK/column ops).

**conditionalOutcomes:**
- depends on US-376's `ecu` table existing first; if US-376 is deferred/incomplete, US-374 BLOCKS (do not partially re-key).
- if a seed's `ecu_signature` matches no `ecu` row at backfill → FAIL LOUDLY, do not NULL `ecu_id`.

**definitionOfDone:** `speed_pid_calibration` re-keyed to `ecu_id` FK in ORM + v0011; old natural key + column dropped; 2 seeds re-pointed with updated provenance; empirical gate works on the FK shape; server suite green; ruff clean.

---

## Atlas architecture review
**Q1–Q5 rendered 2026-06-01** (`offices/pm/inbox/2026-06-01-from-atlas-v0.28.1-ecu-normalization-rulings-Q1-Q5.md`; Spool Q5 `2026-06-01-from-spool-q5-disposition-row-per-reflash.md`). Scope = CIO-ratified B-076 minimal first slice. **PM Rule 13 validation-block sign-off is still OWED** — this freeze-ready PRD is routed back to Atlas; his PASS clears the `prd_to_sprint.py` freeze gate.

## Argus QA review
*Not required for grooming; Argus drives the IRL bigDoD drill post-deploy.*

## Sprint-level `validation.bigDefinitionOfDone` (IRL / human — post-deploy; validates the accumulated 43+44 chain)
1. **Deploy** V0.28.1 from `dev` to chi-srv-01 + Pi (FIRST V0.28-chain hardware deploy; RELEASE_VERSION bump on `dev`). Pi reconnect/power-cycle is a prerequisite human action (Pi `10.27.27.28` has been unreachable on recent deploys). `v0010`+`v0011` apply in sequence on chi-srv-01.
2. **F-107 validation drive (drive 27+):** a real multi-leg drive produces exactly ONE `drive_id` per physical leg (DriveDetector Mechanism A ECU-silence continuation confirmed live).
3. **Attribution-anomaly recompute (US-364):** `recompute_drive_analytics --drive-id 23/24/25` on chi-srv-01 → drives 23+24 stamped `attribution_anomaly`, drive 25 clean, idempotent re-run zero-diff.
4. **ECU-row backfill (US-367):** `stamp_ecu_swap` writes prior ECU `(MD346675, 6675, close)` + new ECU `(MD335287, UNKCAL, open)` with install/removal derived from production `realtime_data` MIN/MAX; `vehicle_info` shows 2 lineage rows pointing at the correct `ecu` rows via `ecu_id`; `speed_pid_calibration` joins resolve for both.
5. **Regression-manifest release:** F-005 + F-007 HOLDs released in `offices/pm/regression_manifest.json` on the OBSERVED drive-27 + recompute result.
6. **Schema-pass production verification:** `SHOW CREATE TABLE` on chi-srv-01 confirms all V0.28 surfaces + the new `ecu` table + the `ecu_id` FKs match the ORM.

## Before running `prd_to_sprint.py`
1. ✅ Q1–Q5 resolved + recorded above. ✅ Decomposition final (2 stories; US-375 dropped). ✅ Per-story `validationCriteria` + `definitionOfDone` written above.
2. **Route this freeze-ready PRD to Atlas for PM Rule 13 sign-off** (owed). Atlas PASS clears the freeze gate.
3. PM runs `prd_to_sprint.py` (pins `bigDoDHash`); branch `sprint/sprint44-V0.28.1` forks from `dev` @ current tip. **At fork: land the US-374/US-376 + counter + finalized PRD onto `dev`** so the sprint branch inherits them (the one reconciliation flagged at Sprint-43 close).

## Refinements made during grooming
| Story | Refinement | Made by | Date |
|---|---|---|---|
| (all) | Decomposition held provisional pending Atlas Q1–Q4 per A-11 | Marcus | 2026-06-01 |
| US-375 | DROPPED — `vehicle_info.ecu_id` folded into US-376 per Atlas; optional TEXT→VARCHAR(32) deferred | Atlas → Marcus | 2026-06-01 |
| US-374 | Reframed from "re-land" to "rework-forward" — option-(c) build is on dev (v0010 creates it); v0011 re-keys | Atlas (coherence finding) → Marcus | 2026-06-01 |
| US-374 seeds | Provenance strings updated to Spool's 2026-06-01 confirmed values (supersede v0010) | Spool → Marcus | 2026-06-01 |

## Dependencies & sequencing
- Forks from `dev` @ `bd1618c` (carries all Sprint-43 code incl. the dev-shipped option-(c) `speed_pid_calibration` build).
- **US-376 before US-374** — the `ecu` table is US-374's FK target. v0011 substep order: `ecu` create+backfill → `vehicle_info.ecu_id` → `speed_pid_calibration` re-key.
- IRL bigDoD runs only after both dev stories land + V0.28.1 deploys; the 43+44 chain validates together (Sprint 43 never deployed).
- On full IRL green: `/sprint-validated` Sprint 43 + 44 → `/chain-validated` merges `dev`→`main` for the V0.28 chain.

## Conversion record
*Not yet converted. `prd_to_sprint.py` runs after Atlas Rule 13 PASS.*

## Audit trail
- 2026-06-01 draft created (Marcus); Q1–Q5 routed to Atlas (+Spool on Q5) before freeze.
- 2026-06-01 FINALIZED (Marcus): Atlas Q1–Q4 + Spool Q5 rulings recorded; premise corrected to rework-forward per Atlas coherence finding; decomposition collapsed to 2 stories (US-375 dropped); freeze-ready per-story criteria written. Routed back to Atlas for PM Rule 13 sign-off.
