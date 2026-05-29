---
id: safe-range-afr
title: Safe range — AFR (wideband, future)
topic: safe-ranges
summary: (Requires wideband — not yet installed) AFR WOT 11.0–11.8 normal, >12.5 LEAN danger / <10.0 over-rich; cruise 14.5–15.0; idle 14.7±0.3.
ecu: both
mod_state: premod
fuel: 93-octane
confidence: community
status: current
source: DSMTuners-consensus
date: 2026-05-29
exact_locked: false
supersedes: []
superseded_by: null
---

# Safe range — AFR (wideband)

**Applicability**: requires a wideband O2 (AEM 30-0300 planned; pin 75/92 pre-wire staged — see `prewire-wideband-o2`). NOT readable today — the stock narrowband only does closed-loop fueling health (see `safe-range-fuel-trims`). This card is the reference for when the wideband lands.

| Condition | Normal | Caution | Danger |
|-----------|--------|---------|--------|
| **WOT** | **11.0–11.8:1** | 12.0–12.5:1 | **>12.5:1 LEAN** or <10.0:1 over-rich |
| **Cruise** | 14.5–15.0:1 | — | >16.0:1 misfire territory |
| **Idle** | 14.7:1 ±0.3 | — | Erratic = vacuum leak |

**Why**: under boost, lean = detonation = dead engine. On pump gas (this car: [EXACT: 93 octane — DO NOT CHANGE]) richer is safer — 11.0–11.8 at WOT keeps combustion temps down and gives knock margin. Lean-at-load is the #1 way DSMs grenade. These targets shift when E85/flex-fuel lands (future).
