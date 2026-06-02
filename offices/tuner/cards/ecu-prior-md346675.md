---
id: ecu-prior-md346675
title: Prior ECU — MD346675 (stock, drives ≤24)
topic: ecu
summary: 1998 factory FWD-turbo ECU; 100% stock, never flashed; flash-hardware but not ECMLink-flashable; drives ≤24 are stock baselines.
ecu: prior
mod_state: premod
fuel: n/a
confidence: authoritative
status: current
source: CIO-confirmation-2026-05-29; CIO-photos-2026-05-29; DSMTuners-sourcing
date: 2026-05-29
exact_locked: false
supersedes: []
superseded_by: null
---

# Prior ECU — MD346675

The original ECU in the car, in service for **drives ≤24**, pulled during the 2026-05-22 swap to the ECMLink-capable [[ecu-new-md326328]].

| Attribute | Value |
|-----------|-------|
| Service P/N | **MD346675** (case-top barcode label) |
| ROM / cal code | **6675** (connector-end label — last 4 of the service P/N, standard DSM convention) |
| Mfr P/N | **E2T68273** (Mitsubishi Electric internal manufacturing P/N) |
| Other markings | code **150**; "Mitsubishi Electric Corp., Japan" |
| Application | 1998 model-year 2G DSM **FWD turbo** (Eclipse GST / Talon TSi FWD), production ~7/97–5/98. AWD sibling = MD346676. |
| Year base | **1998** — the correct factory ECU for this 1998 GST chassis |
| Memory type | **Flash hardware**, but **NOT ECMLink-flashable** (98/99 family copy protection). Not a socketed EPROM. |
| Tune status | **100% STOCK — factory calibration, never flashed (CIO-confirmed 2026-05-29).** |
| SPEED PID | Read **correct** (calibration factor 1.0) — unlike the new ECU. |

**Why it was swapped**: MD346675's copy protection blocks ECMLink V3 — it is not ECMLink-flashable ("not flash-enabled" for tuning). CIO replaced it with the ECMLink-flashable 97 board ([[ecu-new-md326328]]) per the [ECMtuning workaround](https://www.ecmtuning.com/wiki/use_ecmlink_in_98_99_dsm). The swap was about flash capability, not a bad tune.

**Consequence for baselines**: because this ECU was bone-stock, **all drives ≤24 (incl. the Drive 11 knock-retard reference and the drives 3–12 idle baselines) are genuine STOCK FACTORY baselines** — the clean reference for grading the new ECU's modified ECMLink tune. The conservative idle timing (~5–7° BTDC) on these drives IS the stock 1998 GST calibration, NOT a "modified EPROM signature" as earlier project lore guessed (that framing is superseded).

**Identity provenance**: photo-identified 2026-05-29 from two CIO photos of the pulled ECU; stock/never-flashed status confirmed directly by CIO same day.
