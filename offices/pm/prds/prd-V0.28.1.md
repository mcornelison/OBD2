---
sprint: 44
version: V0.28.1
status: draft
createdAt: 2026-06-01
createdBy: Marcus (PM)
selectedStories: [US-374, US-375, US-376]
argusReviewRequired: false
convertedAt: null
sprintJsonPath: null
forksFrom: dev @ bd1618c
---

# PRD — Sprint 44 (V0.28.1): ECU-identity normalization + Sprint-43 carry-forward close

## Sprint goal

Close the Sprint-43 carry-forward and normalize ECU identity. Three dev work-streams: (1) re-land `speed_pid_calibration` against a *correct, frozen-from-the-start* contract (the option-(c) code is already in dev — preserved at tag `us-370-option-c-preserved`); (2) normalize `vehicle_info.ecu_signature`; (3) **start B-076** — introduce a normalized `ecu` identity table (surrogate PK + UNIQUE signature) that `vehicle_info` and `speed_pid_calibration` reference. This is the FIRST deploy of the V0.28 chain — Sprint 43 was committed to dev but never deployed — so the V0.28.1 IRL drill validates the *accumulated* 43+44 chain (F-107 DriveDetector fix, the schema pass, the ECU backfill, attribution-anomaly recompute).

**Carry-forward scope discipline (CIO 2026-06-01):** human/IRL tasks are NOT stories — they are `validation.bigDefinitionOfDone` clauses. The Sprint-43 carry-forward items that are pure IRL (US-364 recompute, US-367 backfill *execution*, F-107 validation drive, F-005/F-007 HOLD release, the deploy, Pi power-cycle) live in the bigDoD, not `stories[]`. See `offices/pm/knowledge/feedback-pm-sprint-scope-no-human-irl-tasks.md`.

## Selected stories (DEV-doable; provisional pending Atlas design — see Open Questions)
| Story | Title | Feature | Epic | Type | Size |
|---|---|---|---|---|---|
| US-374 | `speed_pid_calibration` re-land against final frozen contract (option-(c) or `ecu` FK per Q1) + architecture.md §5 surface-5 + Atlas Rule 10 re-PASS | F-076 | E-002 | tech-debt | S |
| US-375 | `vehicle_info.ecu_signature` normalization (TEXT→VARCHAR(32), or FK→`ecu` per Q2) | F-076 | E-002 | tech-debt | S |
| US-376 | B-076: normalized `ecu` identity table (surrogate PK + UNIQUE signature) + FK wiring + migration | F-076 | E-002 | normal | M |

> **Decomposition is provisional.** The final story shapes/criteria depend on Atlas's `ecu`-table ruling (Q1–Q4). US-375 may be absorbed into US-376; US-374 may collapse to "confirm code matches the `ecu`-FK contract." PM finalizes decomposition + per-story `validationCriteria`/`definitionOfDone` AFTER Atlas resolves, BEFORE `prd_to_sprint.py`.

## Open questions (MUST resolve pre-freeze — A-11 discipline: do not freeze a story whose load-bearing criterion depends on an unrendered Atlas ruling)
| # | Question | Raised by | Resolution | Resolved by |
|---|---|---|---|---|
| Q1 | **`ecu` table shape.** Surrogate PK (`id`) + `ecu_signature VARCHAR(32) UNIQUE` + `cal_signature`? What else is identity vs annotation? Does it carry the append-only invariant, or is `ecu` immutable-per-signature with lineage living on `vehicle_info`? | Marcus | _pending_ | Atlas |
| Q2 | **`vehicle_info` ↔ `ecu` relationship.** FK `vehicle_info.ecu_id → ecu.id` (lineage = which ecu was installed when)? Or does `vehicle_info` keep `ecu_signature` and gain a FK? How does the US-365 append-only lineage + single-active marker coexist with a normalized `ecu`? | Marcus | _pending_ | Atlas |
| Q3 | **`speed_pid_calibration` re-key.** Does it move from the built option-(c) `ecu_signature VARCHAR(32) UNIQUE` natural key → **FK `ecu_id → ecu.id`**? This REWORKS the preserved build (tag `us-370-option-c-preserved`). If yes, US-374 = rework to FK; if no (keep natural key for now, FK later), US-374 = re-freeze option-(c) as-is. | Marcus | _pending_ | Atlas |
| Q4 | **Migration sequencing.** New migration (v0011) vs extend v0010? Substep order for `ecu` create → `vehicle_info` FK → `speed_pid_calibration` FK, with the legacy `PRE_TRACKING_UNKNOWN` + MD346675/MD335287 rows backfilled into `ecu` first. Idempotency contract per the v0010 pattern. | Marcus | _pending_ | Atlas |
| Q5 | **ECU identity semantics.** `ecu_signature` = Mitsubishi service P/N (`MDxxxxxx`); `cal_signature` = ROM/cal code (`6675` / `UNKCAL`); uniqueness from the `(ecu_signature, cal_signature)` pair (Spool 2026-05-29). Does the normalized `ecu` table key on signature alone, or the pair? Reflash convention (`-R2/-R3`) — row-per-reflash or mutable cal column? | Marcus | _pending_ | Spool (semantics) + Atlas (shape) |

## Atlas architecture review
*Date: TBD — Atlas owns Q1–Q4 (Rule 3). This PRD is routed to Atlas BEFORE story criteria are frozen (A-11 lesson Atlas logged from US-370). Spool consulted on Q5 ECU-identity semantics.*

## Argus QA review (only if required)
*Not required for grooming; Argus drives the IRL bigDoD drill post-deploy.*

## Sprint-level `validation.bigDefinitionOfDone` (IRL / human — post-deploy; validates the accumulated 43+44 chain)

1. **Deploy** V0.28.1 from `dev` to chi-srv-01 + Pi (FIRST V0.28-chain hardware deploy; RELEASE_VERSION bump on dev). Pi reconnect/power-cycle is a prerequisite human action — Pi `10.27.27.28` has been unreachable on recent deploys.
2. **F-107 validation drive (drive 27+):** a real multi-leg drive produces exactly ONE `drive_id` per physical leg (no dual-attribution). DriveDetector Mechanism A (ECU-silence continuation) confirmed live on hardware.
3. **Attribution-anomaly recompute (US-364):** `python -m server.cli.recompute_drive_analytics --drive-id 23/24/25` against chi-srv-01 production `obd2db`; drives 23+24 stamped `data_quality='attribution_anomaly'`; drive 25 clean; idempotent re-run zero-diff.
4. **ECU-row backfill (US-367):** `stamp_ecu_swap` writes the prior ECU (`MD346675`, cal `6675`, close) + new ECU (`MD335287`, cal `UNKCAL`, open) with install/removal derived from production `realtime_data` MIN/MAX; `vehicle_info` (or `ecu`, per Q2) shows the 2 lineage rows; `speed_pid_calibration` joins resolve for both signatures.
5. **Regression-manifest release:** F-005 + F-007 HOLDs released in `offices/pm/regression_manifest.json` on the observed (not assumed) drive-27 + recompute result.
6. **Schema-pass production verification:** `SHOW CREATE TABLE` on chi-srv-01 confirms the V0.28 schema surfaces landed (drive_summary/drive_statistics `data_quality`, `drive_statistics.summary_id`, `vehicle_info` ECU lineage, `dtc_freeze_frame`, `speed_pid_calibration`, the new `ecu` table) match the ORM.

## Before running `prd_to_sprint.py` (per spec 2026-05-28 / CIO directive #2)
1. **Resolve Q1–Q5 with Atlas (+ Spool on Q5)** and record resolutions in the Open Questions table. THEN finalize the story decomposition + per-story `validationCriteria` + `definitionOfDone`. (Do NOT freeze with the design unrendered — that is the exact A-11 failure US-370 hit.)
2. Verify each finalized Story carries non-empty `validationCriteria` + `definitionOfDone`.
3. Route the draft to Atlas for PM Rule 13 validation-block review. Atlas PASS clears the freeze gate.
4. PM runs `prd_to_sprint.py` (pins `bigDoDHash`); branch `sprint/sprint44-V0.28.1` forks from `dev` @ current tip.

## Refinements made during grooming
| Story | Refinement | Made by | Date |
|---|---|---|---|
| (all) | Decomposition held provisional pending Atlas Q1–Q4 per A-11 | Marcus | 2026-06-01 |

## Dependencies & sequencing
- Forks from `dev` @ `bd1618c` (carries all Sprint-43 code incl. the preserved option-(c) `speed_pid_calibration` build).
- US-376 (`ecu` table) is the design centerpiece; US-374 + US-375 depend on its resolved shape (Q1–Q4). Migration ordering: `ecu` create + backfill → `vehicle_info` relationship → `speed_pid_calibration` re-key.
- IRL bigDoD runs only after the dev stories land + V0.28.1 deploys. The 43+44 chain validates together (Sprint 43 never deployed).
- On full IRL green: `/sprint-validated` Sprint 43 + 44 → eventually `/chain-validated` merges `dev`→`main` for the V0.28 chain.

## Conversion record
*Not yet converted. `prd_to_sprint.py` runs after Q1–Q5 resolution + Atlas Rule 13 PASS.*

## Audit trail
- 2026-06-01 draft created (Marcus). Scope = CIO 2026-06-01 "Normalization + start B-076 ecu table" + no-human-tasks-as-stories directive. Open questions Q1–Q5 routed to Atlas (+Spool on Q5) before freeze.
