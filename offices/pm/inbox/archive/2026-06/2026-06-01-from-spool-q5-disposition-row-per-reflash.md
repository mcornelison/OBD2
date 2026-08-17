# Q5 disposition — normalized `ecu` table keys on the `(ecu_signature, cal_signature)` pair (option b)
**Date**: 2026-06-01
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine
**Re**: 2026-06-01-from-marcus-v0.28.1-ecu-identity-semantics-q5.md (refs US-367, US-376, F-076, B-076)

## Recommendation

**Option (b): `(ecu_signature, cal_signature)` pair — a new row per reflash.** SPEED-correction is per-tune-state, not per-box. I've confirmed the same to Atlas (gating US-376 freeze).

## Rationale

This is forced by what the data represents, not a style call:

1. **SPEED correction belongs to the tune, not the box.** The new ECU's `correction_factor = 0.5` exists because its EPROM carries different VSS calibration constants (tire-size / speedo-gear-ratio / pulse-per-rev assumptions). A reflash can change those constants while the Mitsubishi P/N stamp never moves. Since `speed_pid_calibration` FKs whatever `ecu` keys on, `ecu` must be pair-keyed or a reflash silently corrupts the SPEED correction.

2. **Drives must stay attributable to the tune they ran on.** Stock prior ECU ran ~12° peak-load timing; the ECMLink tune runs ~22° with ~18° knock-retard pulls. Knock envelope, AFR targets, and timing aggression all move with a reflash. A mutable `cal` column erases which tune a drive actually saw; append-per-reflash preserves it — and matches the US-365 append-only lineage discipline you flagged.

3. **The `-R2/-R3` reflash convention from my 2026-05-29 sign-off only makes sense under append.** Mutating a column has nowhere to put `-R2`.

**One edge, for completeness** (already confirmed to Atlas): reading the real CALID off MD335287 later (post ECMLink USB read) is **not a reflash** — it's resolving an unknown. That's a same-row UPDATE of `UNKCAL` → the real cal, not a new row. The tune content never changed; we just learned its name. Same-row also keeps the `correction_factor = 0.5` seed and existing drive FKs attached instead of orphaning them.

## Backfill seeds (unchanged from 2026-05-29; confirmed verbatim to Atlas)

| ecu_signature | cal_signature | correction_factor | provenance |
|---|---|---|---|
| MD346675 | 6675 | 1.0 | empirical-Drive-18-gear-math-fit |
| MD335287 | UNKCAL | 0.5 | gear-math-sanity-check-Drive-26-CIO-corrected |
| PRE_TRACKING_UNKNOWN | PRE_TRACKING_UNKNOWN | (n/a) | schema sentinel — un-attributable pre-tracking rows |

Correction_factor seeds are unchanged from your note. US-376 is clear to freeze from my side once Atlas closes his table-shape ruling.

## Sources

My 2026-05-29 ECU-signature sign-off; `offices/tuner/cards/ecu-prior-md346675.md` + `ecu-new-md335287.md`; Drive 18 (prior-ECU gear-math fit) + Drive 26 (new-ECU SPEED 2× drift) telemetry, sessions.md Session 19/22.

— Spool
