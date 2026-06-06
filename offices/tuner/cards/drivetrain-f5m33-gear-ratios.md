---
id: drivetrain-f5m33-gear-ratios
title: Transmission gear ratios — F5M33 5-speed (2G FWD turbo, stock)
topic: drivetrain
summary: Stock F5M33 5-speed (2G FWD turbo) ratios 3.090/1.833/1.217/0.888/0.741, final drive 4.153; cross-validated against prior-ECU Drive 18 (57.6 mph computed vs recorded). Feeds the SPEED-PID gear-math cross-check. ~24 mph/1000rpm in 5th.
ecu: both
mod_state: premod
fuel: n/a
confidence: authoritative
status: current
source: roadraceengineering.com DSM gear-ratio table (factory Shop Manual CD) + cross-check vs Drive-18 prior-ECU realtime_data
date: 2026-06-01
exact_locked: false
supersedes: []
superseded_by: null
---

# Transmission gear ratios — F5M33 5-speed (2G FWD turbo)

CIO confirmed a **stock, unmodified 5-speed**. The 2G Eclipse GST (FWD turbo) uses the **F5M33** transaxle (driver-side mount). *Not* the W5MG1/W5M33 — that is the AWD (GSX/Talon TSi AWD) Getrag-family box, and an earlier project note that said "W5MG1" for this car was wrong.

| Gear | Ratio |
|------|-------|
| 1st | 3.090 |
| 2nd | 1.833 |
| 3rd | 1.217 |
| 4th | 0.888 |
| 5th | 0.741 |
| **Final drive** | **4.153** |

Total reduction = gear × final drive: 1st 12.83 · 2nd 7.61 · 3rd 5.05 · 4th 3.69 · **5th 3.077**.

## Cross-validated against our own data

Using these ratios + the stock-size tire rolling circumference (≈1.985 m, see [[wheels-tires-potenza-205-55r16]]):

- **Drive 18 (prior STOCK ECU [[ecu-prior-md346675]], SPEED read correctly):** RPM 3,937 in 3rd → 3,937 ÷ 5.054 = 779 wheel-rev/min × 1.985 m = **57.6 mph computed** vs 60 mph recorded (theoretical-57 note). **Reproduces** → ratios + circumference both confirmed.
- **Drive 26 (new ECU [[ecu-new-md326328]]):** the SPEED PID reported **84** — which is **84 km/h = 52 mph** (consistent with this gear math), NOT 84 mph. The old "~2× drift" was a **unit mislabel** (km/h recorded as mph in Session 19), DISPROVEN by GPS on Drive 27 (factor **1.00**). Gear math here corroborates the tire circ + ratios, not any drift.

Quick reference: **~24 mph per 1,000 RPM in 5th** (≈72 mph @ 3,000 RPM).

## Use

This is data ask #2 for the SPEED-PID calibration gear-math **cross-check** (`speed = RPM × circumference ÷ (gear × final_drive × 60)`). The **primary** calibration remains the GPS-correlation run (tire/gear-independent) per Atlas's procedure; the gear math is the scalar-vs-curve sanity check. Mirror of these ratios pinned to `specs/grounded-knowledge.md` (PM Rule 7).
