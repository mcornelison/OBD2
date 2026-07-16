---
sprint: 47
version: V0.29.1
status: superseded
supersededBy: prd-V0.29.14.md (2026-07-15, Session 55 -- same F-107 chain, version + scope refreshed to the 5-story 386..390; US-367/391/392/379 split out)
createdAt: 2026-06-28
createdBy: Marcus (PM)
selectedStories: [US-386, US-387, US-388, US-389, US-390, US-367, US-391, US-392, US-379]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-002
feature: F-107
theme: Data-integrity hardening
atlasRule13: PENDING
freezeGate: "CLOSED 2026-06-28 -- Atlas ruled US-367=2 rows (option a, supersede placeholder) + US-391 quick-read + RCA C-3 + re-drain deploy-gate (inbox 2026-06-28-from-atlas-sprint47-rulings-us367-us391); US-367 DoD re-groomed in backlog.json. Ready for prd_to_sprint.py freeze."
---

# PRD — Sprint 47 / V0.29.1 — Data-Integrity Hardening

## Summary

A data-integrity sprint forking from `dev` (opens a patch on the V0.29 chain;
`main` is at `V0.28.2`). Nine stories across four features, themed: **make the
drive-lifecycle, the ECU lineage spine, and the sync queue tell the truth.**

1. **A-9 DriveDetector** (US-386–390, F-107) — RCA + fix for the dual-attribution
   + stale-open-drive defect that reopened on drives 28/29.
2. **ECU lineage spine** (US-367, F-108) — backfill the real ECU eras; self-heals
   the live `dtc_freeze_frame` sync orphan.
3. **Sync quarantine** (US-391, F-076) — stop a single unresolvable record from
   retrying forever and masking a real failure.
4. **Cleanup** (US-392 A-15 config de-dup, F-044; US-379 test fixture, F-076).

This is **HIGH severity but NOT a chain/deploy block** — the V0.28.0 server
tripwire (`detect_overlapping_drives`) already flags drives 28/29 as
`attribution_anomaly`, and failed `dtc_freeze_frame` pushes do not advance the
sync high-water (no corruption). Schedule deliberately; the long pole is the A-9
IRL re-gate (needs the car).

## Authoritative design

- **A-9 RCA ruling:** Atlas `offices/architect/reports/2026-06-19-a9-drivedetector-rca-ruling.md`
  (summarized in PM inbox `2026-06-19-from-atlas-a9-rca-ruling-sprint-scope.md`).
- **A-9 reopen finding:** `offices/architect/findings/2026-06-18-drivedetector-defect-recurs-28-29.md`
  + Spool's 2-table corroboration (`2026-06-18-from-spool-drivedetector-corroboration-29-vs-18.md`).
- **dtc orphan + lineage spine:** Spool `offices/pm/inbox/2026-06-28-from-spool-dtc-freezeframe-sync-orphan.md`.
- **A-15 address SSOT:** Atlas `2026-06-18-from-atlas-a15-mirror-lint-built-and-followups.md`.
- **Sprint blueprint:** `docs/superpowers/plans/2026-06-28-sprint47-V0.29.1-data-integrity.draft.json`.

Atlas owns the architecture; this PRD packages his rulings + Spool's findings into
the Ralph sprint contract. Story-level detail (goal / DoD / validation criteria /
conditional outcomes) is the single source of truth in `backlog.json` and the
`offices/pm/backlog/US-3xx-*.md` mirrors.

## Stories (build order follows `deps`)

| Story | Feat | Size | What it does |
|-------|------|------|--------------|
| **US-386** | F-107 | M | In-process DriveDetector reproducer (RED) — short / back-to-back / key-on-after-missed-close. No hardware. |
| **US-387** | F-107 | M | RCA: root-cause the close/drive-end path (premise: comms-drop ruled out). Gates US-388. |
| **US-388** | F-107 | M | **Root-2 fix** — guaranteed-close + stamp-only-when-RUNNING + gap-fence the drive_id latch. **SHAPE-PENDING, build-blocked on US-387 (A-11).** |
| **US-389** | F-107 | S | **Root-1 closure** — bake the single-instance guard + `RuntimeDirectory` as a matched-pair tested deploy invariant (C-5) + version-stamp the out-of-band change. |
| **US-390** | F-107 | S | Regression lock + confirm the server tripwire backstop. |
| **US-367** | F-108 | S | **ECU lineage-spine backfill** — **supersede the `PRE_TRACKING_UNKNOWN` placeholder** + write 2 real eras (close `MD346675`, open `MD326328`), FK=`ecu_id`, swap-instant as param; self-heals the stuck June-5 freeze-frame. **Atlas ruled 2 rows (option a) 2026-06-28.** |
| **US-391** | F-076 | S | `dtc_freeze_frame` sync quarantine after N failures (stop silent infinite retry). |
| **US-392** | F-044 | S | A-15 config.json server-address de-dup (derive base URLs from `serverHost:serverPort`). |
| **US-379** | F-076 | S | Test-only: fix the stale harness fixture from the US-371 `drive_id`→`summary_id` rename. |

Build chain: US-386 → US-387 → US-388 → US-390 (A-9 core); US-389, US-367, US-391,
US-392, US-379 are independent.

## Freeze-gates

1. **US-367 — Atlas 2-vs-3-row ruling — CLOSED 2026-06-28.** Atlas ruled **2 rows
   (option a)**: supersede the degenerate `PRE_TRACKING_UNKNOWN` placeholder (3 rows
   = resolver overlap hazard at `sync.py:605`). DoD re-groomed in `backlog.json` to
   the 5 conditions (FK=`ecu_id` via `resolveOrCreateEcu` + derived TEXT snapshots;
   swap-instant as script param; `MD346675` install = start-of-tracking/NULL;
   placeholder→log-not-row; bless the one-shot bootstrap script). Coherence +
   resolver no-overlap added to validation.
2. **US-388 — stays shape-pending.** Its `validationCriteria` are stable (reproducer
   green + 3-scenario behavior) but the implementation shape is deliberately
   unfrozen; keep the build-blocked conditionalOutcome. (Atlas confirmed correct as
   drafted.)
3. **US-391 — Atlas quick-read — CLOSED 2026-06-28.** Ralph-pickable with the 4
   invariants now encoded in DoD (stop-after-N / preserve-raw / surface-once /
   re-drainable); the conditionalOutcome routes back to Atlas only if it needs a
   **new cross-tier table** (A-4-family versioned-contract change).
4. **US-387/389 — RCA condition C-3 added.** Confirm the 06-06 02:25 spawn-source
   for the two concurrent `eclipse-obd` PIDs (now an explicit acceptance criterion
   on US-389).

## Validation (Argus)

The frozen `validation.bigDefinitionOfDone` aggregates each Story's
validationCriteria (see `sprint.json` after conversion). The **sprint-level IRL
clause is the true A-9 acceptance gate** and is CIO-gated (needs the car):

> Drive a **short / back-to-back drive pair** + a **key-on after a missed close**
> + a **deploy double-start**, then `recompute_drive_analytics` → each physical
> drive = a single `drive_id`, all closed, `attribution_anomalies=0`, and the
> guard refuses the 2nd process on the double-start.

A single clean drive is explicitly insufficient — that narrowness is exactly what
falsely re-closed A-9 on drive-27.

## Design-gate DoD (PM Rule 10)

- **US-388** — if the Root-2 fix is load-bearing, `specs/architecture.md`
  DriveDetector section is updated in-sprint (Atlas design-gate DoD).
- **US-389** — enabling the guard is a load-bearing boot-path change;
  `specs/architecture.md` boot-path section updated in-sprint (Atlas Rule-10
  signed off in the 2026-06-19 ruling — this story actions it).

## Post-merge deploy gate (separate; PM/CIO call)

The A-9 IRL re-gate and the US-367 self-heal verification (confirming
`dtc_freeze_frame` COUNT > 0 + no recurring sync failures on chi-srv-01) are
deploy-time validations, not part of the merge.

**US-367 ↔ US-391 cross-story (Atlas §3, 2026-06-28):** US-367 self-heals the
June-5 orphan by making it resolve on the next sync cycle — but if US-391 has
already quarantined that record, the self-heal only lands if quarantine is
re-drainable (US-391 invariant 4). So the post-merge gate must, **alongside the
existing `COUNT(*) > 0` check, re-drain the quarantine after US-367 lands** and
confirm the orphan clears.

Also fold the still-pending **Sprint 46 / V0.29.0 Pi flag-flip validation**
(`pi.bus.enabled`) into this deploy window if convenient — both target the same Pi.

## Sizing note (PM)

Nine stories is a large sprint, but the A-9 cluster is mostly investigative
(US-386 reproducer + US-387 RCA carry the weight; US-388 is build-blocked until
the RCA lands). Run `/resize-sprint` at freeze to confirm the 60%-context fit; if
tight, split into **47a** (A-9: US-386–390) and **47b** (US-367 + US-391 + US-392
+ US-379). CIO directed a single full sprint 2026-06-28.

## Sequencing

Forks from `dev`. Does not conflict with the EDR epic (E-006, hardware-gated) or
US-367's parallel Atlas ruling. The V0.28 chain is already on `main` at `V0.28.2`.
