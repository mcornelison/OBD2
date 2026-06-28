---
id: US-386
title: "Deterministic in-process reproducer for the DriveDetector close-signal defect (RED)"
type: issue
parent: F-107
epicId: E-002
size: M
status: sprint-ready
sourceRefs: [A-9, F-107, atlas-rca-ruling-2026-06-19, spool-corroboration-29-vs-18-2026-06-18]
created: 2026-06-28
---

# US-386 — Deterministic in-process DriveDetector reproducer (RED)

## Context

A-9 (DriveDetector dual-attribution) reopened when it recurred on drives 28/29.
Atlas's 2026-06-19 RCA ruling identified two roots: Root 1 = two concurrent
orchestrator processes (mitigated out-of-band), and Root 2 = a stale-open-drive
leak (a drive never closes → a later key-on inherits the stale `drive_id`;
`connection_log` showed `drive_start=29` but `drive_end=18`). Spool independently
corroborated Root 2 from `connection_log` and ruled out comms-drop as the cause —
the K-line is stable mid-drive and there is zero `drive_id` on any connection
failure. The server-side `detect_overlapping_drives` tripwire already flags 28/29
as `attribution_anomaly`, so this is HIGH severity but NOT a chain/deploy block.
This story builds the in-process reproducer (no hardware) that the RCA and fix
will hang off of.

## Goal

As the regression suite, I want an in-process harness that drives DriveDetector
through the failure scenarios via synthetic RPM / engine-on-off / timing inputs
(NO comms events — Spool ruled out comms-drop; `connection_log` shows zero
`drive_id` on any failure/disconnect), asserting CORRECT behavior so the
drives-28/29 defect (overlap + stale-open leak) reproduces deterministically
WITHOUT the car.

## Definition of Done

- feeds a synthetic engine-state sequence for: (a) short ~3-min drive, (b) two back-to-back drives ~1 min apart, (c) key-on AFTER a drive whose close never fired
- asserts: exactly ONE drive_id per physical drive (no overlap), each drive closes on key-off, a key-on after a stale-open opens a NEW drive_id (no absorption)
- FAILS (RED) on current detector.py, reproducing the 28/29 signature (overlap + missed-close)
- pure in-process; no IRL/hardware dependency
- Typecheck passes; the RED test runs and its failure is documented

## Validation Criteria

- (run the reproducer against current detector.py) → (RED — reproduces overlap + missed-close in-process)
- (inspect the back-to-back scenario) → (two overlapping drive_ids minted (the defect); ids possibly out of temporal order)

## Conditional Outcomes

- if the defect will NOT reproduce at the detector unit level (manifests only with the real orchestrator loop/threads/timing), STOP + escalate to Atlas — reproduction needs the real lifecycle loop

## Notes

In-process reproducer only — no hardware. This is the foundation Story for the
A-9 sprint (Sprint 47 / V0.29.1); US-387 (RCA) and US-388 (fix) build on it.
