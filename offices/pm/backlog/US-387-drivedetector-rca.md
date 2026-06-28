---
id: US-387
title: "RCA: root-cause the DriveDetector close / drive-end path"
type: research
parent: F-107
epicId: E-002
size: M
status: sprint-ready
sourceRefs: [A-9, F-107, atlas-rca-ruling-2026-06-19]
created: 2026-06-28
---

# US-387 — RCA: DriveDetector close / drive-end path

## Context

A-9 (DriveDetector dual-attribution) reopened when it recurred on drives 28/29,
and Atlas's 2026-06-19 RCA ruling split the defect into two roots: Root 1 = two
concurrent orchestrator processes (mitigated out-of-band), Root 2 = a stale-open
drive leak (a drive never closes → a later key-on inherits the stale `drive_id`;
`connection_log` showed `drive_start=29` but `drive_end=18`). Spool corroborated
Root 2 from `connection_log` and ruled out comms-drop — the K-line is stable
mid-drive, with zero `drive_id` on any connection failure. With the US-386
reproducer in hand, this Story renders the exact mechanism; it build-gates US-388
(Watch List A-11).

## Goal

As the architect-gated investigation, with the reproducer in hand I want the
exact mechanism for BOTH defects rendered. Opening premise (Spool, 2-table
corroborated): comms-drop is RULED OUT — the K-line is stable mid-drive; the
drive never closing is purely the DriveDetector close-signal state machine not
firing. Trace `src/pi/obdii/drive/detector.py` + `orchestrator/lifecycle.py`
drive-start/-end/close logic.

## Definition of Done

- RCA names the exact code path + mechanism (file:line) for BOTH (1) drive fails to close and (2) a second drive_id opens over an open one (ids out of temporal order)
- RCA explains the US-386 reproducer's RED behavior
- RCA confirms/refutes the one-root hypothesis (defects 1+2 share the unreliable-close root) with evidence; incorporates Spool's connection_log finding (drive_start 29 / drive_end 18; zero drive_id on comms failures)
- no fix in this story

## Validation Criteria

- (read the RCA against the reproducer) → (mechanism identified, maps to the RED test, cites file:line)
- (Atlas review of the RCA) → (root cause accepted (gate for US-388))

## Conditional Outcomes

- if the real root differs from the unreliable-close-signal hypothesis, document what it ACTUALLY is — do not force-fit

## Notes

Depends on US-386. This RCA is the build gate for US-388 — the fix must not be
coded before Atlas accepts the root cause.
