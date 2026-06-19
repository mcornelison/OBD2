---
id: US-374
parent: F-076
type: tech-debt
size: S
status: complete
archivedFrom: backlog.json (no source Story.md -- synthesized at graduation)
---

# US-374 — speed_pid_calibration re-key forward: option-(c) natural key -> ecu_id FK (reworks dev-shipped v0010 build)

## Goal
As server analytics, I want speed_pid_calibration keyed by FK ecu_id->ecu.id (not the transitional option-(c) ecu_signature natural key) so per-ECU SPEED correction references the SSOT ecu identity and a reflash gets its own calibration row.

## Definition of Done
- Starting point (explicit, per Atlas coherence finding): v0010 already creates speed_pid_calibration in option-(c) shape (ecu_signature VARCHAR(32) + uq_speed_pid_calibration_ecu_signature) and that build is on dev; US-374's v0011 substep reworks it FORWARD -- it does not create the table
- v0011 substep (after US-376 ecu substeps): ADD speed_pid_calibration.ecu_id INT FK->ecu.id + UNIQUE(ecu_id); backfill ecu_id by matching each existing row's ecu_signature to its ecu row; DROP uq_speed_pid_calibration_ecu_signature + the ecu_signature column; 2 v0010 seed rows PRESERVED re-pointed to ecu_id; a seed matching no ecu row FAILS LOUDLY
- ORM SpeedPidCalibration: replace ecu_signature natural key with ecu_id FK + relationship; SSOT constants updated; create_all + migration converge
- seeds per confirmed table: MD346675->1.0/empirical-Drive-18-gear-math-fit, MD335287->0.5/gear-math-sanity-check-Drive-26-CIO-corrected (provenance updated from v0010 strings per Spool 2026-06-01); provenance stays NOT NULL; empty/whitespace forbidden by writer (preserved from v0010)
- select_empirical_calibrations() empirical-prefix gate works over the FK shape (provenance LIKE 'empirical-%')
- pytest tests/server/ -m 'not slow' green (+ re-key migration test, ORM parity, gate test); ruff clean; changes unstaged; architecture.md §5 surface landed jointly via US-376 Rule-10 clause

## Validation Criteria
- (DESCRIBE speed_pid_calibration post-v0011) -> (ecu_id INT NOT NULL FK + UNIQUE(ecu_id); ecu_signature column ABSENT; old uq_speed_pid_calibration_ecu_signature gone)
- (SELECT correction_factor FROM speed_pid_calibration spc JOIN ecu e ON spc.ecu_id=e.id WHERE e.ecu_signature='MD346675') -> (1.0)
- (SELECT correction_factor ... JOIN ecu ... WHERE e.ecu_signature='MD335287') -> (0.5)
- (INSERT a speed_pid_calibration row with ecu_id not in ecu) -> (FK violation)
- (INSERT with empty provenance) -> (writer raises)
- (call select_empirical_calibrations()) -> (MD346675 row included (empirical- prefix), MD335287 excluded (rough seed))
- (re-run v0011 over an already-migrated DB) -> (idempotent no-op (no duplicate FK/column ops))

_Synthesized from backlog.json at graduation (2026-06-19); the original Story was filed directly into JSON without a Story.md._
