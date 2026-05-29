---
id: safe-range-coolant-temp
title: Safe range — Coolant temperature
topic: safe-ranges
summary: Normal 185–205°F (85–96°C); caution 205–215°F (96–102°C); danger >220°F (>104°C). Two-tier alert warn 210°F / critical 220°F.
ecu: both
mod_state: premod
fuel: n/a
confidence: community
status: current
source: DSMTuners-consensus; manufacturer-spec; Spool-Phase1-tuning-spec (alert tiers)
date: 2026-05-29
exact_locked: false
supersedes: []
superseded_by: null
---

# Safe range — Coolant temperature (4G63T, this car)

| Band | Value | Action |
|------|-------|--------|
| Normal | **185–205°F (85–96°C)** | — |
| Caution | **205–215°F (96–102°C)** | Watch; back off load |
| Danger | **>220°F (>104°C)** | **STOP. Head-gasket risk. Pull over, let cool.** |

**Two-tier alert** (Spool Phase 1 spec): **warn at 210°F (99°C)**, **critical at 220°F (104°C)**.

**Why it kills the 4G63**: sustained >220°F stretches the head bolts, the MLS head gasket loses clamp load, and coolant enters the #4 cylinder — the classic DSM head-gasket failure. Coolant temp is the single most important thermal safety signal on this engine.

**This-car note**: thermostat opens cleanly ~80°C and the car settles ~89°C steady-state (I-016 closed benign; see `cooling-thermostat-behavior` card). A healthy engine returns to that baseline — a creep above it is the early warning before the caution band.
