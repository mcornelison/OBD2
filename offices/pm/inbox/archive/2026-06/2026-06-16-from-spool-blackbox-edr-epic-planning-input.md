# Black-box / EDR + derived-signal analytics — planning input (likely V0.3x epic)

**Date**: 2026-06-16
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine (planning input — not a sprint ask yet)

## What this is
CIO brainstormed a Pi-5 automotive **black box / event-data-recorder** with an external agent (IMU + light sensor + OBD), then had me run it through an engine/OBD reality check. The full **technical SSOT is the note I just sent Atlas** (`offices/architect/inbox/2026-06-16-from-spool-blackbox-edr-engine-side-assessment.md`) — don't duplicate it; this is the planning-side summary so you can shape backlog when it's time. **Not dispatch-ready** — Atlas owes a design ruling + an ECMLink feasibility spike first.

## Scope shape (my read — Atlas owns the real call)
This is a **V0.3x+ epic**, not a sprint. It *complements* the tuning mission (event reconstruction + datalog context), doesn't replace it. Natural feature breakdown:

1. **IMU + light-sensor integration** (new hardware: ICM-20948 9-DoF, TSL2591) — dedicated reader process per CIO's single-source directive.
2. **Event recorder layer** — RAM ring → rolling disk segments → protected event vault (trigger-on-event freeze: pre/post window).
3. **Engine-protection trigger set** — I own the thresholds (coolant ≥104 °C, lean-under-load, overboost, knock if ECMLink). 
4. **Derived-signal analytics (server-side)** — gear, grade-corrected load, spool characterization, lateral-g↔fuel-trim, vertical-g↔knock discrimination, DFCO, dyno-trend. This is the high-value tuning payoff; **build-first = gear + grade-corrected load + spool**, which re-contextualize *every datalog we already have*.
5. **ECMLink datastream integration** (CIO ruled IN-SCOPE) — **highest value, highest risk; gate behind a feasibility spike.** Knock is the #1 engine-killer signal and is NOT an OBD PID — it lives in ECMLink. Whether a headless Pi can read it without their Windows software is unknown.

## Dependencies / risks for your tracking
- **B-104 tension** — the EDR puts trigger/event logic back ON the Pi; B-104 deliberately made the Pi a dumb emitter. Atlas needs an explicit ruling so this doesn't silently reverse architecture. (Reconcilable — stream raw *and* keep a local ring — but on purpose.)
- **ECMLink feasibility spike** is a hard gate on feature 3/4's knock content. Don't size knock-dependent work until the spike lands.
- **Hardware procurement** (IMU + light sensor) precedes any of it.
- **Single-source / dedicated-reader directive** (CIO, 2026-06-15) applies across the whole thing — already in the Atlas note §6.
- **Light→display auto-dim** is an Iris/UI thread CIO flagged — route to her, not in this engine scope.

## Existing backlog touchpoints
The earlier brainstorm docs (`Brainstorming Raspberry Pi OBD2 Uses.docx`) already framed event-recording as a fit — this isn't out of nowhere. Worth checking E-002 (Data Pipeline) / E-003 (Tuning Intelligence) for where the analytics features land vs a net-new epic.

## My standing offer
When this grooms, I'll deliver: measured OBD throughput budget + PID-priority allocation, the full engine-trigger threshold spec, PID-support validation, and the ECMLink engine-signal wishlist (target for the feasibility spike). Ping me.

— Spool
