---
id: US-390
title: "Regression lock + server-tripwire backstop confirmation"
type: issue
parent: F-107
epicId: E-002
size: S
status: pending
sourceRefs: [A-9, F-107]
created: 2026-06-28
---

# US-390 — Regression lock + server-tripwire backstop confirmation

## Context

The final Story of the A-9 sprint (Sprint 47 / V0.29.1). Once the Root-2 fix
(US-388) lands, the US-386 reproducer must be locked permanently into the
regression suite/manifest so a future Pi regression of the DriveDetector
close-signal defect is caught automatically. As belt-and-suspenders, this Story
also re-confirms that the V0.28.0 server-side `detect_overlapping_drives` tripwire
still stamps `data_quality=attribution_anomaly` on any residual overlap — so the
defect is still caught server-side even if the Pi fix ever regresses again.

## Goal

As the project, I want the US-386 reproducer locked into the regression
suite/manifest permanently, and the V0.28.0 server tripwire
(`detect_overlapping_drives`) confirmed to still flag any residual overlap —
belt-and-suspenders so a future Pi regression is still caught server-side even if
the Pi fix regresses again.

## Definition of Done

- US-386 reproducer added to the fast suite / regression manifest (permanent)
- a server-side test confirms detect_overlapping_drives still stamps data_quality=attribution_anomaly on a synthetic overlap
- Typecheck passes; tests pass

## Validation Criteria

- (pytest fast suite including the reproducer) → (green)
- (synthetic-overlap tripwire test) → (attribution_anomaly stamped (backstop intact))

## Notes

Depends on US-388 (the reproducer must be GREEN before it is locked as a
permanent regression guard).
