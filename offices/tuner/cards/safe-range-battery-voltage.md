---
id: safe-range-battery-voltage
title: Safe range — Battery voltage (ELM ATRV)
topic: safe-ranges
summary: Running normal 13.5–14.5V; caution 12.5–13.5V or >14.8V; danger <12.0V or >15.0V. Read via ELM ATRV by choice; PID 0x42 is LIVE (corrected 2026-08-20) but ATRV is off-K-line.
ecu: both
mod_state: premod
fuel: n/a
confidence: authoritative
status: current
source: Spool-Phase1-tuning-spec (locked, PM Rule 7); DSMTuners-consensus
date: 2026-05-29
exact_locked: false
supersedes: []
superseded_by: null
---

# Safe range — Battery / charging voltage

| Band | Value (engine running) | Meaning |
|------|------------------------|---------|
| Normal | **13.5–14.5V** | Alternator charging correctly |
| Caution | **12.5–13.5V or >14.8V** | Low = charging weak; high = regulator drifting |
| Danger | **<12.0V or >15.0V** | <12 = not charging; >15 = regulator failure (boils battery, fries electronics) |

**Source path**: ⚠️ **CORRECTED 2026-08-20 — PID 0x42 (control-module voltage) IS LIVE on this ECU** (drive 33: 76 rows, 29 distinct, 12.975–14.451 V). The earlier "unsupported" verdict was a probe artifact and is withdrawn. Voltage is nonetheless read from the **ELM327 `ATRV` command** *by deliberate choice, not necessity* — `ATRV` is adapter-local at pin 16 and costs nothing against the ~6.3 samples/s K-line budget, whereas 0x42 would consume a poll slot. Keep `ATRV`; do not claim 0x42 is dead. (`obd.commands.ELM_VOLTAGE` in python-obd) — measured at OBD-II pin 16, independent of ECU bandwidth. All voltage code/tests must use this path (see `battery-voltage-via-elm`). Thresholds match Spool's Phase 1 tuning spec (locked source of truth, PM Rule 7).
