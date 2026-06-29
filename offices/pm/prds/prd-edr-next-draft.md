---
status: staging-plan
createdAt: 2026-06-29
createdBy: Marcus (PM)
theme: EDR / Black-Box Recorder — hardware-independent foundation (next sprint, CIO-themed)
epic: E-006
forksFrom: dev (when groomed; post-Sprint-47)
authoritativeDesign: Atlas 2026-06-16 EDR-epic brief (offices/pm/inbox/2026-06-16-from-atlas-edr-epic-backlog-tracking-brief.md) + EDR-vs-B104 ruling (offices/architect/reports/2026-06-16-edr-vs-b104-architecture-ruling.md)
watchList: A-14
---

# Staging Plan — EDR Next Sprint (hardware-independent foundation)

CIO themed the next sprint **EDR** (2026-06-28/29). This is a **staging plan**, not a frozen contract — the EDR epic is a multi-sprint V0.3x+ effort whose architecture is **Atlas-owned**; the design content must come from Atlas (+ Spool for engine signals) before a real PRD freezes. This file maps what's groomable now.

## Epic structure (filed in backlog.json, E-006)

| Feature | Phase | HW-gated? | Owner | Groom now? |
|---|---|---|---|---|
| F-110 | Bus Slice 1 (shipped, dark) | no | — | done (awaiting flag-flip validation) |
| **F-112** | ECMLink datastream feasibility spike (knock reachability) | **no** | Spool + CIO; Atlas rules outcome | **YES** |
| **F-113** | Dedicated-reader + bus-contract design (full; A-4 versioned) | **no** | **Atlas (design-only)** | **YES** |
| F-114 | Single-reader consolidation + IMU/light raw channels | **yes** (i2cdetect) | Atlas (schema) + dev | after HW gate |
| F-115 | Event vault + on-Pi triggers + display surfaces | **yes** | Spool (triggers) + Iris (display) + Atlas (vault schema) | after F-112/113/114 |

## What the next EDR sprint can be (hardware-independent)

Per Atlas's phase order, two pieces are groomable/startable **now** (sensors not required):

1. **F-112 — ECMLink feasibility spike.** Determine whether **knock** (the #1 engine-killer signal) is reachable from the ECMLink datastream over the existing ECU/OBD path, and what else ECMLink exposes beyond OBD Mode 03/07. **Gates everything downstream** — do it early. *Shape:* research/spike, Spool + CIO led, Atlas rules the feasibility outcome (open gate #3). *Caveat:* ECMLink V3 is owned but **not yet installed** (planned summer 2026), and Mode 22 enhanced isn't implemented — confirm what's reachable on the CURRENT path before committing scope. Likely a Spool/CIO investigation + a small dev probe, not a large code story.
2. **F-113 — dedicated-reader / bus-contract design.** The load-bearing pub/sub bus contract everything subscribes to (per-subscriber QoS lossless-vs-lossy, bounded queues, producer-never-blocks, 100 Hz-IMU-vs-~6/s-OBD rate handling, ECMLink/OBDLink K-line arbitration). **This is an Atlas design artifact (gate #1), not primarily a Ralph code story** — F-110 already shipped the bus skeleton; F-113 is the full contract + the SSOT-bus graduation into `specs/ssot-design-pattern.md` (gate #4).

## Atlas's open architectural gates (he owns these when it grooms)
1. Dedicated-reader/bus contract (QoS, queues, rate handling, K-line arbitration) — F-113.
2. IMU raw table + event-vault schema under versioned `src/common/` discipline (A-4 family — don't repeat Pi↔server schema divergence) — F-114/F-115.
3. ECMLink feasibility-spike ruling (knock coverage) before its architecture commits — F-112.
4. Graduate the SSOT-bus direction into `specs/ssot-design-pattern.md` once CIO firms it.

## Hardware status (2026-06-27, Atlas)
Sensors **hardware-installed ahead of schedule**: TSL2591 light @0x29 + ICM-20948 9-DoF IMU @0x69, both I2C on bus-1 (shared w/ X1209 UPS MAX17048 @0x36, no collision). CIO **mid-wire**. Hardware gate = `i2cdetect` shows 29/36/69 (NOT yet passed). Hardware-dependent EDR work (F-114/F-115) unblocks on that pass. Spec: `docs/hardware-reference.md` EDR-Sensors + `docs/edr-sensors-wiring-reference.md` (dev 95d496a).

## Recommended grooming approach (PM)
- This is a **multi-agent groom** — per Atlas's brief, loop in **Atlas** (bus contract + schema architecture), **Spool** (ECMLink/knock + event triggers + PID budget), and **Iris** (display surfaces) before freezing.
- **Sequence the first EDR sprint as the hardware-independent foundation**: F-112 spike + F-113 bus-contract design. These shape everything; they don't need the car or the sensors.
- Sensor-dependent integration (F-114/F-115) grooms once `i2cdetect` passes — likely the following sprint(s).
- **Dependency on Sprint 47**: forks from `dev` after the V0.29.1 chain settles; no conflict with the in-flight data-integrity work.

## Open question for CIO
F-113 (bus-contract design) is mostly an **Atlas deliverable** (a design artifact), and F-112 (ECMLink spike) leans **Spool/CIO investigation** — neither is a typical Ralph code sprint. Decide whether the "EDR next sprint" is (a) an Atlas/Spool **design + spike sprint** (artifacts + a feasibility ruling, little Ralph code), or (b) deferred until the design lands so Ralph gets buildable stories. Recommend (a) — it's the critical-path foundation and it's unblocked today.
