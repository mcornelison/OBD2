---
id: safe-range-boost
title: Safe range — Boost & injector duty
topic: safe-ranges
summary: Stock TD04-13G boost normal 10–12 psi, caution 13–14, danger >15. Injector duty danger >85%. Upgraded turbo (future) 16G 16–18 / 20G 18–22 psi.
ecu: both
mod_state: premod
fuel: 93-octane
confidence: community
status: current
source: DSMTuners-consensus; manufacturer-spec
date: 2026-05-29
exact_locked: false
supersedes: []
superseded_by: null
---

# Safe range — Boost & injector duty

**Stock turbo (Mitsubishi TD04-13G, the "small 14b"):**

| Band | Boost | Note |
|------|-------|------|
| Normal | **10–12 psi** | Stock-turbo happy zone |
| Caution | **13–14 psi** | Approaching stock-turbo + stock-fuel limit |
| Danger | **>15 psi** | Compressor out of efficiency; lean risk; fuel system maxed |

**Injector duty cycle**: normal <80%, caution 80–85%, **danger >85%** (need bigger injectors — stock 450cc). Requires ECMLink to read.

**Upgraded turbo (future reference):** 16G 16–18 psi · 20G 18–22 psi (with supporting fuel + tune). AFR WOT 16G 11.0–11.5 / 20G 10.8–11.5. EGT <1400°F (16G) / <1500°F (20G). Injectors 550cc min (16G) / 660cc+ (20G). Fuel pump Walbro 255lph → 450lph or AEM 340lph (stock pump dies above ~300 HP).

**Why / caveat**: boost is **not directly readable on this car** — PID 0x0B (intake manifold pressure) is unsupported (see `obd-unsupported-pids`). Boost is inferred from load/MAF/timing behavior until a boost gauge or ECMLink lands. >15 psi on the stock turbo + stock fuel system is where lean-at-load and knock stack up fastest.
