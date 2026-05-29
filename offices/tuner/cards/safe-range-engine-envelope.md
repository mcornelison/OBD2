---
id: safe-range-engine-envelope
title: Safe range — RPM, engine load, IAT, MAF
topic: safe-ranges
summary: Redline 7000 RPM (97-99 2G); engine load danger >90% sustained; IAT danger >60°C heat-soak; MAF saturation ~150 g/s.
ecu: both
mod_state: premod
fuel: n/a
confidence: community
status: current
source: manufacturer-spec (redline); DSMTuners-consensus; this-car captures (MAF peaks)
date: 2026-05-29
exact_locked: false
supersedes: []
superseded_by: null
---

# Safe range — Engine operating envelope

| Parameter | Normal | Caution | Danger | Note |
|-----------|--------|---------|--------|------|
| **RPM** | 700–800 idle, 0–6500 driving | 6501–7000 | **>7000 (redline)** | 97–99 2G factory redline = 7000. Valve float above on stock springs. |
| **Engine Load** | 15–25% idle, 30–50% cruise | 70–85% | **>90% sustained** | High load + positive STFT = lean under boost. |
| **IAT** | 20–40°C (68–104°F) | 40–55°C (104–131°F) | **>60°C (>140°F)** | Heat soak → power loss; intercooler territory. Interpret vs ambient at key-on. |
| **MAF** | 2–4 g/s idle, varies w/ RPM/load | — | **>~150 g/s** | Stock MAF saturation ceiling. |
| **AirFlowPerRev** | ~0.27 idle | — | Significant deviation | Metering-health check. |

**This-car peaks (stock prior ECU)**: MAF hit 158.69 g/s at WOT on Drive 7 (right at the saturation ceiling) and 135 g/s on Drive 11; load reached 100% on both WOT pulls with no thermal or knock distress. So this car *does* push the stock MAF to its limit at full load — a MAF reading pinned ~150+ during a pull is expected, not a fault. See `drive-007-under-load-baseline`, `drive-011-knock-retard`.
