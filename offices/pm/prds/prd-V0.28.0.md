---
sprint: 43
version: V0.28.0
status: draft
createdAt: 2026-05-28
createdBy: Marcus (PM)
selectedStories: [US-359, US-360, US-361, US-362, US-363, US-364, US-365, US-366, US-367, US-368, US-369, US-370, US-371, US-372, US-373]
argusReviewRequired: true
convertedAt: null
sprintJsonPath: null
---

# PRD — Sprint 43 (V0.28.0): DriveDetector data-integrity remediation + coherent V0.28 schema-pass first slice

## Sprint goal

Land F-107's data-integrity remediation (Pi-side DriveDetector + lifecycle hardening + server-side `detect_overlapping_drives` tripwire + historical anomaly stamping on drives 23+24) and the V0.28 coherent schema-pass first slice (F-108 ECU lineage + F-109 Mode 02 freeze-frame storage + F-076 SPEED-PID calibration table + the two `drive_summary`/`drive_statistics` smells) in **one Alembic v0010 migration cycle**. All landed on `sprint/sprint43-V0.28.0` branch forked from `dev` per the directive #1 dev/main workflow (`docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md`).

## Selected stories

| Story | Title | Feature | Epic | Type | Size |
|---|---|---|---|---|---|
| US-359 | Pi-side dual-attribution reproducer harness | F-107 | E-002 | normal | S |
| US-360 | RCA — git diff US-351 revert vs pre-US-349 + timing analysis | F-107 | E-002 | research | S |
| US-361 | Root-cause fix: DriveDetector + lifecycle dual-emission prevention | F-107 | E-002 | normal | M |
| US-362 | `detect_overlapping_drives(session, drive_id)` server compute helper | F-107 | E-002 | normal | S |
| US-363 | Server tripwire: `data_quality='attribution_anomaly'` integration | F-107 | E-002 | normal | S |
| US-364 | Backfill drives 23+24 via `recompute_drive_analytics --drive-id` | F-107 | E-002 | normal | S |
| US-365 | `vehicle_info` ECU + cal_signature columns + currently-active constraint | F-108 | E-OPS | normal | S |
| US-366 | `stamp_ecu_swap` + `show_ecu_lineage` server CLIs | F-108 | E-OPS | normal | S |
| US-367 | Backfill 2 ECU rows (prior + 2026-05-22 swap) + join verification | F-108 | E-OPS | normal | S |
| US-368 | `dtc_freeze_frame` table + Pi-side Mode 02 capture on MIL_ON | F-109 | E-OPS | normal | M |
| US-369 | Server sync + `show_dtc_freeze_frame` CLI | F-109 | E-OPS | normal | S |
| US-370 | `speed_pid_calibration` table + 2-ECU seed; FK to `vehicle_info.ecu_signature` | F-076 | E-002 | normal | S |
| US-371 | Column rename: `drive_statistics.drive_id` → `summary_id` + consumer updates | F-076 | E-002 | tech-debt | S |
| US-372 | `drive_summary.drive_id` NULL decision + implementation | F-076 | E-002 | normal | S |
| US-373 | PM Rule 10: `specs/architecture.md` update for V0.28 schema pass | E-OPS | E-OPS | housekeeping | S |

**Totals**: 15 stories. Sizes: 13 × S + 2 × M = 17 S-equivalents. Within sprint cap.
**Migration**: one Alembic v0010 covering US-363 + US-365 + US-368 + US-370 + US-371 + US-372.

## Open questions

| # | Question | Raised by | Resolution | Resolved by |
|---|---|---|---|---|
| 1 | **US-372 `drive_summary.drive_id` NULL** — option (a) backfill from `source_id` OR option (b) drop column server-side? | Spool 2026-05-22 (joint flag with Atlas) | pending | CIO + Atlas |
| 2 | **US-370 SPEED-PID new-ECU seed** — initial `correction_factor=0.5` (rough estimate) OR defer to GPS-correlation drive? | PM 2026-05-28 (sprint grooming) | pending | Spool |
| 3 | **US-361 Pi-side fix scope** — bounded to `src/pi/obdii/drive/detector.py` OR also touches `src/pi/obdii/orchestrator/lifecycle.py`? Affects PM Rule 10 scope (US-373). | PM 2026-05-28 (sprint grooming) | pending | Atlas (post-US-360 RCA) |
| 4 | **US-368 `ecu_signature` capture** — runtime FK to current `vehicle_info` row at capture time OR denormalized `ecu_signature_at_capture` text for historical immutability? | PM 2026-05-28 (sprint grooming) | pending | Atlas + Spool |

**All 4 questions must resolve before `prd_to_sprint.py` runs** — PM Rule 13 (Atlas validation-block sign-off) is gated on resolved Story validationCriteria.

## Atlas architecture review

*Date: TBD (pending Stories filed + PRD ready for Atlas brief)*

**Triggers**:
- **PM Rule 10** (load-bearing subsystem change): F-107 touches Pi DriveDetector + lifecycle (load-bearing); F-076/F-108/F-109 add 3 tables + rename columns (schema = load-bearing); US-373 is the in-sprint `specs/architecture.md` update artifact (PM Rule 10 DoD).
- **PM Rule 13** (validation-block sign-off): every Story's `validationCriteria` + the aggregated `bigDefinitionOfDone` requires Atlas reviewer-lane sign-off BEFORE `prd_to_sprint.py` cuts the freeze hash.

**Atlas brief** lands in `offices/architect/inbox/` once Stories are filed. Expected verdicts: per-Story gate criteria + bigDoD aggregation review + PASS or BLOCK on the 4 open questions above.

## Argus QA review

*Date: TBD*

**Why required** (`argusReviewRequired: true`):
F-107 is a data-integrity bug surfaced by Argus's V0.27.18 IRL drill. Argus reviews:
- The regression-test design (US-359 reproducer + US-362 server detector + US-364 backfill assertions)
- The IRL drill spec (drive count + recompute scope + backfill expectations)
- The `detect_overlapping_drives` tripwire signal shape (sufficient to flag the V0.27.18 pattern; not so loud it flags legitimate sequential drives)
- Coverage of Drive 25+ single-attribution clean state staying `data_quality='full'` post-recompute

## Sprint-level `validation.bigDefinitionOfDone`

**Aggregation rule** (per spec 2026-05-28 / CIO directive #2): `bigDefinitionOfDone` is generated by `prd_to_sprint.py` as the union of each Story's `validationCriteria` (formatted as `(action) → (outcome) [from US-XXX]`), plus the sprint-level IRL clauses below. The hash is cut at conversion; late additions are ERRORs in `sprint_lint.py`.

**Per-Story `validationCriteria` contribute** (~20 testable pairs, full content lands in Story.md files at filing time):
- US-359: Pi-side reproducer fixture replays Drive 23/24 timing → DriveDetector emits 2 drive_ids
- US-360: RCA doc cross-references US-351 revert diff + identifies residual race or timing shift
- US-361: Same reproducer fixture under fix → DriveDetector emits 1 drive_id; existing single-drive tests still pass
- US-362: `detect_overlapping_drives(session, 23)` returns `[24]`; `detect_overlapping_drives(session, 25)` returns `[]`
- US-363: `compute_drive_summary(23)` writes `data_quality='attribution_anomaly'`; `compute_drive_summary(25)` writes `'full'`
- US-364: Post-recompute, `SELECT drive_id, data_quality FROM drive_summary WHERE drive_id IN (23, 24)` returns both rows with `'attribution_anomaly'`; idempotent re-run = zero diff
- US-365: `vehicle_info` SELECT shows new columns; INSERT with valid signature succeeds; INSERT violating "exactly one row with NULL removal_timestamp" constraint fails
- US-366: `stamp_ecu_swap` round-trip closes prior row + opens new row; `show_ecu_lineage` lists both
- US-367: Post-backfill, `JOIN vehicle_info ON drive_summary.start_time_utc BETWEEN install/removal` correctly partitions drives 1-24 (prior ECU) from drives 25+ (new ECU)
- US-368: Synthetic MIL_ON event triggers Mode 02 enumeration; `dtc_freeze_frame` row written with 16-PID JSON
- US-369: Pi-to-server sync delivers freeze-frame row; `show_dtc_freeze_frame --dtc-log-id N` returns expected 16-PID dictionary
- US-370: SPEED-PID query with prior ECU returns `correction_factor=1.0`; with new ECU returns `0.5` (or empirical post-Spool refinement)
- US-371: Post-migration, all consumers of `drive_statistics.drive_id` reference `summary_id`; existing analytics queries return same results
- US-372: Per CIO+Atlas resolution (option a or b) — backfill OR column drop verified via query
- US-373: `specs/architecture.md` sections for F-107 + F-076 + F-108 + F-109 reflect new schema state; Atlas Rule 10 PASS recorded

**Sprint-level IRL clauses (added at freeze time on top of per-Story aggregation):**
1. **Drive 27+ IRL**: end-to-end OBD capture lands on chi-srv-01; `SELECT COUNT(DISTINCT drive_id) FROM realtime_data WHERE captured_at BETWEEN '<drive-27-start>' AND '<drive-27-end>'` returns exactly **1** (no dual-attribution under V0.27.18 trigger conditions).
2. **Server recompute pass**: `python -m server.cli.recompute_drive_analytics --all-drives` produces `data_quality='attribution_anomaly'` on drives 23+24 only; all other historical drives stay `'full'`; drive 25+ stay `'full'`.
3. **F-108 lineage smoke**: `python -m server.cli.show_ecu_lineage` returns 2 rows after Sprint 1 backfill (prior ECU + 2026-05-22 swap), with the current row carrying `ecu_removal_timestamp_utc=NULL`.
4. **F-109 freeze-frame smoke**: synthetic DTC trigger on Pi → row appears in chi-srv-01 `dtc_freeze_frame` post-sync; `show_dtc_freeze_frame` returns the 16-PID dictionary.

**`validatesFeatures` for `regression_manifest.json`**:
- F-005 (drive_summary insert + sync round-trip) — re-validated via US-363 + US-364 IRL Drive 27 + recompute
- F-007 (drive_statistics ship + sync) — re-validated via US-371 rename + recompute
- F-010 (DTC retrieval Mode 03/07) — re-validated via US-368 + US-369 (Mode 02 rides the same MIL_ON path)
- F-013 (V0.X deploy land + IRL Drive validation) — validated by definition (this sprint deploys)

## Before running `prd_to_sprint.py` (per spec 2026-05-28 / CIO directive #2)

1. **File 15 Story.md files** in `offices/pm/backlog/US-359.md` through `US-373.md` with full content: goal (Connextra or Gherkin), non-empty `definitionOfDone`, `conditionalOutcomes`, `validationCriteria` table (≥1 row per Story), `tasks`, dependencies, grounded references.
2. **Update `offices/pm/backlog.json`** to register all 15 Stories under their parent Features.
3. **Bump `offices/pm/story_counter.json`** to `nextId: US-374`.
4. **Resolve all 4 open questions** above with CIO/Atlas/Spool input; refine relevant Story validationCriteria with the answers.
5. **Route PRD to Atlas** for validation-block review per PM Rule 13. Atlas verifies criteria are testable, bigDoD aggregates faithfully, no coverage holes vs Story `goal`.
6. **Atlas PASS clears the freeze gate**; PM then runs `python offices/pm/scripts/prd_to_sprint.py offices/pm/prds/prd-V0.28.0.md offices/ralph/sprint.json` which pins the `frozenAt` + `bigDoDHash`.

After freeze: any `bigDefinitionOfDone` modification → `sprint_lint.py` ERRORs. Drill-discovered gap → patch sprint forks from `dev` (V0.28.1) per directive #1 workflow.

## Refinements made during grooming

| Story | Refinement | Made by | Date |
|---|---|---|---|

*(Empty — populated as Atlas + Spool + CIO refine during grooming review.)*

## Dependencies & sequencing

**Per-Feature dependency chains** (each chain is sequential under Ralph's single-threaded execution):

```
F-107: US-359 → US-360 → US-361        (Pi-side: reproducer → RCA → fix)
F-107: US-362 → US-363 → US-364        (server-side: detector → tripwire → backfill)
F-108: US-365 → US-366 → US-367        (schema → CLI → backfill)
F-109: US-368 → US-369                 (Pi capture → server sync + CLI)
F-076: US-365 → US-370                 (F-108 ecu_signature dependency)
F-076: US-371                          (independent rename)
F-076: US-372                          (independent, gated on CIO question 1)
E-OPS: US-373                          (depends on all schema-touching Stories above)
```

**Ralph execution order** (front-load research + low-risk independents; group Alembic v0010 contributors; backfills + architecture spec last):

1. US-359 (reproducer)
2. US-360 (RCA)
3. US-362 (detect_overlapping_drives — independent of Pi fix)
4. US-371 (drive_statistics rename — independent)
5. US-372 (drive_summary.drive_id decision — needs CIO answer; if blocked, skip and revisit)
6. US-361 (Pi fix — depends on US-360)
7. US-365 (vehicle_info schema)
8. US-370 (SPEED-PID table — depends on US-365)
9. US-368 (dtc_freeze_frame table + Pi capture)
10. US-363 (tripwire — depends on US-362)
11. US-366 (F-108 CLI — depends on US-365)
12. US-369 (F-109 sync + CLI — depends on US-368)
13. US-364 (F-107 backfill — depends on US-363)
14. US-367 (F-108 backfill — depends on US-366)
15. US-373 (PM Rule 10 architecture.md update — last; reflects final schema state)

**Cross-cutting Alembic v0010** accumulates: data_quality enum `attribution_anomaly` (US-363) + vehicle_info ECU columns + constraint (US-365) + dtc_freeze_frame table (US-368) + speed_pid_calibration table + FK (US-370) + drive_statistics column rename (US-371) + drive_summary.drive_id resolution (US-372).

## Conversion record

*(Populated when `prd_to_sprint.py` runs.)*

- `convertedAt`: null
- `sprintJsonPath`: null
- `frozenAt`: null (set in sprint.json by prd_to_sprint)
- `bigDoDHash`: null (set in sprint.json by prd_to_sprint)

## Audit trail

- 2026-05-28: draft created by Marcus (PM) Session 44; brainstorming per `superpowers:brainstorming` skill; design decisions = atomic Story granularity (15 stories) + one Alembic v0010 migration + IRL gate = one drive + recompute. F-103 splash explicitly deferred to V0.28.1 or its own sprint per Tier 3 evaluation.
