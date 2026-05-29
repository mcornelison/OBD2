---
id: safe-range-timing-knock
title: Safe range — Timing advance & knock
topic: safe-ranges
summary: Timing normal 10–15° idle / 8–20° cruise; caution <8° under load; danger <5° or negative (knock retard). Knock count (future) 0 normal, >5/pull danger; knock sum >4 danger.
ecu: both
mod_state: premod
fuel: 93-octane
confidence: community
status: current
source: DSMTuners-consensus; this-car Drive-007 + Drive-011 (stock-ECU baselines)
date: 2026-05-29
exact_locked: false
supersedes: []
superseded_by: null
---

# Safe range — Timing advance & knock

**Timing advance (readable via OBD now):**

| Band | Value | Meaning |
|------|-------|---------|
| Normal | **10–15° idle, 8–20° cruise** | Healthy |
| Caution | **<8° under load** | ECU starting to pull timing |
| Danger | **<5° or negative** | Active knock retard — investigate fuel quality, carbon, IAT |

**Knock count / sum (future — requires ECMLink USB, NOT readable over the OBD pipe; Mode 22 silent):**

| Metric | Normal | Caution | Danger |
|--------|--------|---------|--------|
| Knock count | **0** | 1–3 per WOT pull | **>5 per pull** |
| Knock sum | **0–1** | 2–3 | **>4** |

**Why**: knock (detonation) is uncontrolled combustion that hammers ring lands and melts pistons — the 4G63 famously cracks the #4 piston. Any sustained knock is bad; isolated single counts can be sensor noise. Timing safety is **octane-dependent** — this car runs [EXACT: 93 octane — DO NOT CHANGE].

**This-car baselines (STOCK prior ECU, drives ≤24)**: cruise timing avg ~24.5°; under load (>80%) avg ~12–13° — i.e. 10–15° of retard under boost, concentrated in the **4500–5000 RPM mid-range knock window**. Drive 7 hit 34° BTDC at WOT with no knock pull. These are stock-factory references (see `drive-007-under-load-baseline`, `drive-011-knock-retard`). The new ECU's ECMLink tune (drives ≥25, [[ecu-new-md335287]]) runs ~10° more aggressive at sustained peak load — grade it against these, not community generics.
