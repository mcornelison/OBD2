---
id: ecu-new-md335287
title: New ECU — MD335287 (ECMLink, drives ≥25)
topic: ecu
summary: 1997 ECMLink-V3-flash-modifiable board, plug-installed in the 98 chassis 2026-05-22; running prior-tuner ECMLink tune; Mode 09/22 silent; SPEED reads ~2× actual.
ecu: new
mod_state: premod
fuel: n/a
confidence: authoritative
status: current
source: CIO-2026-05-22-swap; probe-Drive-25-2026-05-22; ECMtuning-wiki
date: 2026-05-29
exact_locked: false
supersedes: []
superseded_by: null
---

# New (current) ECU — MD335287

The ECU in the car since the **2026-05-22 swap**, in service for **drives ≥25**. Replaced the stock [[ecu-prior-md346675]].

| Attribute | Value |
|-----------|-------|
| Service P/N | **MD335287** |
| Year base | 1997 DSM |
| Memory type | Non-EPROM (factory flash, NOT a socketed EPROM chip) |
| Modification | **ECMLink V3 flash-module modification** — allows ECMLink reflash via diagnostic port |
| Currently loaded | Prior tuner's custom ECMLink tune (specific calibration ID **unread** — Mode 09 silent; ECMLink USB+PC required to read it). `cal_signature = UNKCAL` until that read. |
| Connector layout | Identical to 1998/1999 OEM (B-53/B-54/B-55/B-56) — direct plug-in, no harness mod |
| Cam angle sensor | Compatible with 98/99 cam angle sensor (no harness swap or ECMLink checkbox) |
| Sibling P/N | MD326328 (equivalent, same ECMLink-supported workaround) |

**Why it's here**: the stock [[ecu-prior-md346675]] (a 1998 board) is not ECMLink-flashable due to copy protection. This 1997 board IS, so it was plug-installed in the 98 chassis per the [ECMtuning workaround](https://www.ecmtuning.com/wiki/use_ecmlink_in_98_99_dsm).

## Capability boundaries (established Drive 25, 2026-05-22)

- **Mode 09** (calibration identity): SILENT — cannot fingerprint the loaded tune via OBD-II.
- **Mode 22** (vendor enhanced): NOT IMPLEMENTED — cannot reach ECMLink-internal data (knock retard, knock sum, per-cylinder fuel/timing, target AFR, base advance) via the OBDLink-via-Pi pipe.
- **The project pipe is for monitoring only**; ECMLink V3 software + USB-to-serial cable is the only path to deep tuning data.
- **SPEED PID drift**: this ECU reads **~2× actual ground speed** (likely modified VSS calibration constants in the loaded tune). Divide by ~2 for a ground-truth estimate until a GPS-correlation run lands. Seeded as `correction_factor = 0.5`, `provenance = 'seed'` per US-370; refine post-GPS-correlation. (Contrast: the stock prior ECU read SPEED correctly, factor 1.0.)

This ECU's tune is **modified** (ECMLink) — the only modified tune in the project history. Use "ECMLink V3 flash mod" or "97 non-EPROM ECU conversion" — never "modified EPROM."
