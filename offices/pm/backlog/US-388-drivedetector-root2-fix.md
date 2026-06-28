---
id: US-388
title: "FIX DriveDetector close-signal reliability — Root 2 (SHAPE PENDING RCA US-387)"
type: issue
parent: F-107
epicId: E-002
size: M
status: pending
sourceRefs: [A-9, F-107, atlas-rca-ruling-2026-06-19]
created: 2026-06-28
---

# US-388 — FIX DriveDetector close-signal reliability (Root 2)

## Context

This is the Root-2 fix in the A-9 sprint (Sprint 47 / V0.29.1). Root 2 is the
stale-open-drive leak: a drive never closes, so a later key-on inherits the stale
`drive_id` (`connection_log` showed `drive_start=29` but `drive_end=18`). The
exact change shape is deliberately frozen as SHAPE-PENDING and build-blocked on
US-387's RCA (Watch List A-11) — the target behaviors are known (guaranteed-close,
stamp `drive_id` only when RUNNING, gap-fence the latch) but the precise edit
awaits the accepted root cause. The server-side `detect_overlapping_drives`
tripwire already flags 28/29, so this is HIGH severity but not a chain/deploy
block.

## Goal

As the Pi drive-lifecycle, I want the Root-2 fix so the US-386 reproducer goes
GREEN. Per Atlas ruling the target behaviors are: guaranteed-close + stamp
`drive_id` ONLY when RUNNING + gap-fence the `drive_id` latch (idle/KOEO rows →
NULL so a stale-open cannot absorb a later key-on). Exact change shape pending the
US-387 RCA — frozen as shape-pending, build-blocked, per A-11.

## Definition of Done

- US-386 reproducer GREEN
- no overlapping drive_ids in the back-to-back scenario
- a key-on after a missed close opens a NEW drive_id (no multi-day-leak absorption)
- idle/KOEO rows carry NULL drive_id (gap-fence)
- existing DriveDetector + lifecycle tests stay green
- if load-bearing, specs/architecture.md DriveDetector section updated in-sprint (Atlas design-gate DoD)
- Typecheck passes; tests pass

## Validation Criteria

- (pytest the US-386 reproducer + existing detector/lifecycle suites) → (all green)
- (re-run the 3 scenarios (short / back-to-back / key-on-after-missed-close)) → (one drive_id each, all close, no absorption)

## Conditional Outcomes

- BUILD BLOCKED until US-387 RCA accepted by Atlas — do not code before the root cause is rendered
- if the RCA reveals the fix is architectural (id-minting concurrency, detector re-entrancy), route back to Atlas for a design ruling BEFORE coding

## Notes

Build-blocked on US-387's RCA. This Story must NOT be coded before the root cause
is accepted by Atlas (shape-pending per Watch List A-11). Depends on US-386 and
US-387.
