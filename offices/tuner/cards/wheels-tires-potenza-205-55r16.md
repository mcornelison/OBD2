---
id: wheels-tires-potenza-205-55r16
title: Mounted tires — Bridgestone Potenza 205/55R16 91H (stock size)
topic: wheels-tires
summary: Bridgestone Potenza (RE0_0 series) 205/55R16 91H on aftermarket 16" 5-lug wheels; STOCK SIZE → rolling circ ≈1.985 m, ~811 rev/mi (confirms new-ECU 2× SPEED drift is a tune VSS constant, not tires). Aged (DOT 1003 = March 2003, ~23 yr) but full tread + garaged + CIO-inspected no rot → CIO retaining; cleared for low-speed calibration drive, revisit before highway/spirited.
ecu: both
mod_state: premod
fuel: n/a
confidence: authoritative
status: current
source: CIO-photos-2026-06-01 (three sidewall/wheel images)
date: 2026-06-01
exact_locked: false
supersedes: []
superseded_by: null
---

# Mounted tires — Bridgestone Potenza 205/55R16 91H

Photo-identified 2026-06-01 from three CIO sidewall/wheel images.

| Attribute | Value |
|-----------|-------|
| Brand / line | **Bridgestone Potenza** |
| Model | **RE0_0 series** — reads `RE050` (possibly `RE050A`); exact suffix unconfirmed off these photos |
| Size | **205/55R16** |
| Load index | **91** → 1,356 lb (615 kg) max per tire |
| Speed rating | **H** → 130 mph (210 km/h) |
| Construction | Tubeless, steel-belted radial |
| Origin | Made in Japan |
| Plant/spec code | `V0002` / `H950HZ` (Bridgestone internal — NOT the DOT date) |
| DOT serial | `DOT EL 8K DFA 1003` (CIO read 2026-06-01) |
| **Manufacture date** | **Week 10 of 2003 — March 2003** (date code `1003`). **≈23 years old as of 2026.** |
| Wheel | Aftermarket, gunmetal/anthracite, twin-Y multi-spoke, **16"**, **5-lug (5×114.3 DSM)**. Script center-cap logo not definitively legible (possibly Enkei-family — unconfirmed). |

## ⚠️ SAFETY — aged tires (March 2003, ~23 yr); risk-tiered disposition

The DOT date code `1003` dates these tires to **March 2003** — **~23 years old**, well past the 6–10-year service-life window NHTSA, automakers, and Bridgestone cite (the ceiling is **regardless of tread depth**).

**CIO mitigating data (2026-06-01)**: < 10k miles, **full tread**, **never run on snow/salt**, summer-only + garage-stored. These are real risk-reducers — UV, ozone, heat cycling, and road salt are what *drive* rubber oxidation, and garaged storage slows it substantially. Not the worst-case sun-baked tire.

**What the mitigators do NOT fix**: tread depth + mileage measure *mechanical wear*, a different axis from *age*. The dangerous aged-tire failure is **steel-belt-to-carcass adhesion loss** — internal, invisible, and unaffected by tread. Full tread on an old tire is the classic pre-separation setup (feels trustworthy until it isn't). Rubber still oxidizes in storage, just slower; 23 yr is long even at the slow rate. The failure trigger is **heat**, built by sustained speed + load.

**CIO DECISION (2026-06-01): retaining the tires — not replacing.** CIO inspected and reports **no sign of tire rot**; combined with full tread, < 10k mi, and garaged/never-salted storage. Decision logged; CIO is the vehicle owner + final authority.

**Operating disposition under that decision:**
- **Cleared for the low-speed city calibration loop (drive-27, no WOT).** City speeds don't build the carcass heat that triggers separation, and the visual inspection is clean. This is the actual near-term use, so it's covered.
- **Standing Spool reservation (recorded, not re-argued):** before any *sustained highway speed, spirited summer driving, or a future higher-power tune*, revisit replacement — that's the heat+load regime where age (not tread) bites, and a visual inspection can't see internal belt-adhesion. If replaced later, **stay 205/55R16** to keep the rolling-circumference constant valid.

## Why this matters: STOCK SIZE

The 1998 Eclipse GST factory tire is **205/55R16** — exactly what is mounted. The wheels are aftermarket but the **overall diameter matches factory**, so the OEM VSS / speedometer assumption is satisfied.

**Calibration consequence**: the tires are **NOT** a contributor to the new-ECU 2× SPEED error. A correct-size tire is why the *stock* ECU [[ecu-prior-md346675]] read SPEED dead-on (factor 1.0). The ~2× drift on the ECMLink [[ecu-new-md326328]] tune is therefore confirmed a **scaling constant in the tune** (VSS pulse-per-rev or speedo-gear assumption), not a tire/gearing effect. Tire size moves a speedo a few percent at most — never 2×.

## Rolling-circumference constant (for the SPEED-PID gear-math cross-check)

From 205/55R16:
- Sidewall height = 205 × 0.55 = **112.75 mm**
- Overall diameter = 406.4 mm (16") + 2 × 112.75 = **631.9 mm (24.88 in)**
- **Geometric rolling circumference ≈ 1.985 m (1,985 mm / 78.2 in)**
- **Effective (loaded) ≈ 1.96 m** — subtract ~1.5% for tire deflection under load
- **Revs per mile ≈ 811 geometric / ~818–820 loaded** (manufacturer-typical for this size)

Use the geometric value in `speed = (RPM × circumference) ÷ (gear_ratio × final_drive × 60)`; the loaded value is the better number once a measured revs/mile is sourced. Gear ratios now sourced — see [[drivetrain-f5m33-gear-ratios]] (stock F5M33, final drive 4.153). This feeds the gear-math **cross-check** only — the **primary** SPEED calibration is the GPS-correlation run (tire-independent) per Atlas's procedure `offices/architect/findings/2026-06-01-speed-pid-gps-calibration-procedure.md`.

## Open items

- ~~Gear ratios needed for the cross-check~~ — **DONE 2026-06-01**: stock F5M33 ratios + final drive 4.153 sourced + cross-validated; see [[drivetrain-f5m33-gear-ratios]].
- **Exact model suffix** (RE050 vs RE050A vs other) — low priority; size fully determines the calibration math.
- **Confirm the DOT date digits** — conclusion rests on the trailing `1003`; worth a second look at the stamp to be certain (everything about age hinges on those 4 digits).
