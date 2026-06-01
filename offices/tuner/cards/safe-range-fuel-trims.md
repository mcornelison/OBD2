---
id: safe-range-fuel-trims
title: Safe range — Fuel trims (STFT/LTFT) & narrowband O2
topic: safe-ranges
summary: STFT/LTFT normal ±5%; STFT danger >±15%, LTFT danger >±10%. O2 B1S1 healthy oscillates 0.1–0.9V at 1–3 Hz.
ecu: both
mod_state: premod
fuel: n/a
confidence: community
status: current
source: DSMTuners-consensus; this-car Drive-003/005/006 LTFT observations
date: 2026-05-29
exact_locked: false
supersedes: []
superseded_by: null
---

# Safe range — Fuel trims & narrowband O2

| Parameter | Normal | Caution | Danger | Action |
|-----------|--------|---------|--------|--------|
| **STFT (Bank 1)** | −5% to +5% | ±5% to ±10% | **>±15%** | Investigate now. Large positive = lean = danger. |
| **LTFT (Bank 1)** | −5% to +5% | ±5% to ±8% | **>±10%** | Persistent drift = vacuum leak, failing sensor, or fuel-delivery issue. |
| **O2 B1S1** (narrowband) | Oscillates **0.1–0.9V at 1–3 Hz** | Stuck lean (<0.3V) or rich (>0.7V) | Fixed voltage | Lazy/dead O2 — ECU can't closed-loop fuel. |

**Why**: positive fuel trims mean the ECU is adding fuel to correct a lean condition; large positive trims under load are the lean-before-knock warning. Negative trims mean it's pulling fuel (rich/leak). On a stock-turbo car with no wideband, the narrowband O2 + trims are the only fueling-health signal available.

**This-car note**: this car shows a characteristic **LTFT ~−6.25% lock** at warm idle (observed drives 3/5/6), and a clean cold→warm→hot idle swing well within the ±5% band. That −6.25% is *this engine's normal*, not a fault — grade against it. Under boost the system correctly pegs rich (O2 0.92–0.96V) — the right safety target.
