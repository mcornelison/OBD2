---
id: US-394
title: "F-103 shutdown splash -- ShutdownSequencer phase-emit hook + architecture.md §10.6"
type: normal
parent: F-103
epicId: E-001
size: M
status: sprint-ready
sourceRefs: [F-103, prd-V0.29.2, iris-f103-spec-v1.2, atlas-c5-2026-06-29]
created: 2026-06-29
---

# US-394 — F-103 shutdown splash (Iris US-B)

## Context

The shutdown counterpart to US-393. The `ShutdownSequencer` is a **load-bearing**
subsystem, so the design-gate DoD requires a `specs/architecture.md` §10.6 update
in-sprint (Atlas BLOCKs if the hook ships without it). Depends on US-393 (the boot
runtime). BENCH-ONLY validation.

## Goal

As the Pi during shutdown, I want a shutdown splash so the operator sees the staged
shutdown instead of a frozen/blank screen.

## Definition of Done

- `ShutdownSequencer` emits phase events [A-2] and the splash renders
- shutdown splash shows the staged shutdown
- sequencer docstring documents the timing invariant [A-6]
- `specs/architecture.md` §10.6 updated **in-sprint** (load-bearing ShutdownSequencer change — Atlas design-gate DoD; BLOCKs if the hook ships without the spec update, M-1a)
- **[ATLAS C-5 — shutdown-state survives eclipse-obd stop]** `shutdown-state` must remain readable **after** `eclipse-obd.service` has stopped: eclipse-obd's `RuntimeDirectory=eclipse-obd` is removed on stop, so if it exclusively owns `/run/eclipse-obd` the dir (and `shutdown-state`) vanish at the exact moment the shutdown splash needs them — `eclipse-states-http.service` (and the states dir) must be ordered/ref-counted (shared `RuntimeDirectory=eclipse-obd`) to **outlive** eclipse-obd during the shutdown sequence

## Validation Criteria (bench/shutdown drill)

- (trigger a shutdown) → (shutdown splash renders + transitions through the shutdown stages)
- (trigger a shutdown with `eclipse-obd.service` **already stopped**) → (shutdown splash still renders from `shutdown-state` — proves the dir/file survives the RuntimeDirectory cleanup, not just a warm path where eclipse-obd is still up)
- (inspect `specs/architecture.md` §10.6) → (documents the phase-emit hook + timing invariant)

## Conditional Outcomes

- ShutdownSequencer IS load-bearing → the §10.6 update is mandatory in-sprint (not a follow-up)

## Notes

Build chain: US-393 → **US-394** → US-395 → US-396. Atlas owns the architecture
design gate (§10.6 SSOT); Iris owns the splash design.
