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
source: DSMTuners-consensus; this-car Drive-003/005/006 LTFT observations (OLD ECU); drives 25-38 LTFT re-baseline 2026-08-07 (NEW ECU)
date: 2026-08-07
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

**This-car note — ECU-SPECIFIC, do not carry across the swap:**

- **OLD ECU (MD346675, drives ≤24, stock factory flash)**: characteristic **LTFT ≈ −6.25% lock** at warm idle (observed drives 3/5/6). That was *that ECU's* normal, not a fault.
- **NEW ECU (MD326328, ECMLink flash, drives ≥25) — the current car**: the −6.25% lock is **GONE**. Re-baselined 2026-08-07 across drives 25–38 (server `realtime_data`, n≈2,700 LTFT samples): per-drive averages span **−2.6% to +1.5%**, full range **−3.9% to +3.1%** — comfortably inside the ±5% 🟢 band, including warm parked idle (drives 37/38, 2026-08-07: avg −2.6% / −2.4%).

**Consequence**: do NOT design alerting or UI banding around a −6.25% idle offset on this car. It is superseded. A naive ±5% band does **not** false-alarm at idle on the current ECU.

**Watch item (unresolved)**: drives **35/36** (2026-07-31) report LTFT **exactly 0.00 across all 232 samples**, zero variance. Two plausible readings — (a) genuine ECU adaptive-memory reset (LTFT zeroes then relearns; drives 37/38 a week later do show −2.4%, which fits), or (b) a decode/default artifact of the same class as the Session-27 freeze-frame floor-decode bug. Not resolved; do not use drives 35/36 for fuel-trim baselining until it is.

Under boost the system correctly pegs rich (O2 0.92–0.96V) — the right safety target.
