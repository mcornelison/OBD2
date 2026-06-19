---
id: US-376
parent: F-076
type: normal
size: M
status: complete
archivedFrom: backlog.json (no source Story.md -- synthesized at graduation)
---

# US-376 — B-076: normalized ecu identity table (pair-keyed) + vehicle_info.ecu_id FK wiring + v0011

## Goal
As the server schema (B-076 normalization), I want a normalized, immutable ecu identity dimension keyed on the (ecu_signature, cal_signature) pair that vehicle_info references by FK, so ECU identity is SSOT instead of duplicated free-text, and a reflash is its own identity row.

## Definition of Done
- v0011 (forward-only; v0010 untouched) CREATEs ecu(id INT PK AUTOINCREMENT, ecu_signature VARCHAR(32) NOT NULL, cal_signature VARCHAR(32) NOT NULL, UNIQUE(ecu_signature, cal_signature)) -- no lineage/timestamp columns; ORM Ecu model + SSOT name constants; create_all and migration converge (v0005 serverTableExists + post-probe pattern)
- v0011 backfills exactly 3 seed ecu rows idempotently (INSERT-IGNORE on the pair UNIQUE; re-run no-op): (MD346675,6675), (MD335287,UNKCAL), (PRE_TRACKING_UNKNOWN,PRE_TRACKING_UNKNOWN)
- v0011 adds vehicle_info.ecu_id INT FK->ecu.id; backfills ecu_id by matching each row's existing (ecu_signature, cal_signature) text to its ecu row; then MODIFY NOT NULL; a row matching no ecu row FAILS LOUDLY (MigrationError), never NULL ecu_id
- vehicle_info ecu_signature/cal_signature TEXT columns KEPT (transitional); append-only lineage cols + ecu_active_marker + single-active UNIQUE index UNCHANGED; append-only table comment extended to state ecu_id is an immutable per-lineage-row identity reference
- ecu-immutability carve-out (Atlas Rule 13 refinement): ecu table comment + architecture.md wording state ecu identity columns immutable EXCEPT the sanctioned UNKCAL->real-CALID same-row resolution (Spool Q5 edge -- write-once-when-known cal correction, distinct from a reflash which is a NEW row); NOT absolute immutability; resolution path is a future event (nothing builds it this slice) -- documentation honesty only
- transitional-coherence guard: regression test asserts for every vehicle_info row ecu_signature==ecu[ecu_id].ecu_signature AND cal_signature==ecu[ecu_id].cal_signature; writer stamp_ecu_swap (US-366) sets ecu_id authoritative + DERIVES text columns from the ecu row; code+table comment mark text columns deprecated-transitional (drop in later B-076 slice)
- (PM Rule 10; specs/ read-only for Ralph -- PM writes, Atlas signs) specs/architecture.md gets a NEW descriptive ### subsection 'V0.28.1 -- B-076 first slice' (NOT folded into the V0.28.0-pass narrative) documenting the ecu table (incl. immutability carve-out), vehicle_info.ecu_id FK + transitional-snapshot semantics, and jointly with US-374 the speed_pid_calibration re-key; Atlas Rule 10 PASS recorded BEFORE /sprint-deploy-pm
- pytest tests/server/ -m 'not slow' green (+ ecu-model, migration-idempotency, coherence-guard, writer-derives tests); ruff clean; changes unstaged per PM protocol

## Validation Criteria
- (DESCRIBE ecu post-v0011) -> (id PK, ecu_signature/cal_signature VARCHAR(32) NOT NULL, UNIQUE(ecu_signature, cal_signature); no timestamp/lineage columns)
- (SELECT ecu_signature, cal_signature FROM ecu) -> (the 3 seed rows present exactly (MD346675/6675, MD335287/UNKCAL, PRE_TRACKING_UNKNOWN/PRE_TRACKING_UNKNOWN))
- (INSERT a duplicate (MD335287, UNKCAL) into ecu) -> (UNIQUE violation)
- (INSERT an ecu row with cal_signature NULL) -> (NOT NULL violation)
- (DESCRIBE vehicle_info post-v0011) -> (ecu_id INT NOT NULL FK present; ecu_signature/cal_signature TEXT still present (transitional))
- (coherence test over all vehicle_info rows) -> (text columns equal the joined ecu row's values (zero drift))
- (re-run existing US-365 append-only + ecu_active_marker single-active tests) -> (still green (mechanism unchanged))
- (stamp_ecu_swap an ECU then inspect the row) -> (ecu_id set authoritatively; text columns derived from the ecu row)
- (grep specs/architecture.md for the V0.28.1 B-076 subsection) -> (ecu table + vehicle_info.ecu_id documented incl immutability carve-out; Atlas Rule 10 PASS recorded)

_Synthesized from backlog.json at graduation (2026-06-19); the original Story was filed directly into JSON without a Story.md._
