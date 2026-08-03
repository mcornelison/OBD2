# "Full Advantage of Existing Sensors" — 4 Prototypes — Design Spec

| | |
|---|---|
| **Author** | Iris (UI/UX) |
| **Date** | 2026-08-03 |
| **Status** | DRAFT — 4 prototypes for CIO to pick priorities (design-before-build). GPS + baro sensor ON HOLD (CIO). |
| **Directive** | CIO 2026-08-03: take full advantage of the sensor data we already have; **fact-check every readout against what the OBDLink actually returns; NO dead "no source" displays.** |
| **Companion** | `proposals/2026-08-03-full-advantage-sensor-prototypes.html` + hosted artifact |
| **Palette** | `specs/UI/tokens.css` |

## 0. Fact-check — what data is actually available (the "no dead displays" gate)

Grounded in `config.json` poll list + the ECU facts (MD326328 = 97 DSM board + ECMLink V3).
**Only the CONFIRMED column may drive a live readout; SUSPECT signals are omitted until Spool
confirms they return on this ECU** (routed to Spool).

| Signal | Source | Confidence | Notes |
|---|---|---|---|
| RPM · SPEED | OBD | ✅ confirmed | already used (gear) |
| **MAP** (INTAKE_PRESSURE) | OBD | ✅ confirmed | → **BOOST** (the turbo number) |
| COOLANT_TEMP · IAT (INTAKE_TEMP) | OBD | ✅ confirmed (IAT very likely) | temps; IAT = turbo heat-soak |
| THROTTLE_POS · ENGINE_LOAD | OBD | ✅ confirmed | driving feel |
| VOLTAGE (CONTROL_MODULE_VOLTAGE / ATRV) | OBD | ✅ confirmed | already in alerts |
| STFT · LTFT (short/long fuel trim) | OBD | ✅ confirmed | LTFT already on Health card |
| g-force · heading · grade | IMU accel/mag | ✅ confirmed | already on live card |
| **gyro** (yaw/pitch/roll rate) | IMU | ✅ confirmed | **collected, not yet shown** |
| MAF | OBD | ⚠️ SUSPECT | 4G63 often speed-density / no MAF sensor → likely dead |
| BAROMETRIC_PRESSURE | OBD | ⚠️ SUSPECT | OBD 0x33 usually unsupported on DSM → likely dead |
| O2_B1S1 | OBD | ⚠️ SUSPECT (crude) | narrowband only — no numeric AFR (Spool); a swinging voltage, not a gauge |
| TIMING_ADVANCE | OBD | ⚠️ MISLEADING | returns, but base timing swings ±10-15° normally — NOT knock; do not gauge it (Spool) |

**Boost math:** boost(psi) = (MAP − atmospheric) × 0.145. Baro is on hold + OBD baro is suspect, so
atmospheric is **assumed ~101 kPa** (a small honest caveat on the readout); a confirmed baro would
refine only the zero-point. Boost **bands** (what's normal/spirited/over) are Spool's.

## 1. The four prototypes (all in the mockup)

- **P1 · Boost + vitals on the driving view** — augments the live card: a **boost bar** + a compact
  vitals row (coolant · IAT · RPM · throttle). Lowest complexity, highest turbo value; surfaces only
  confirmed signals.
- **P2 · Dedicated "Engine" card** — a full engine screen: **boost gauge** (arc) + RPM + coolant/IAT +
  throttle/load + STFT/LTFT + voltage. Richer, but adds a 5th card to the consolidated 4-card set.
- **P3 · Post-drive review** — server-analytics surface from logged data: **boost/spool trace**,
  **g-force trace**, **corner-lean**, **grade profile** over the drive. Deepest value; server-tier build.
- **P4 · IMU dynamics (gyro)** — the underused gyro: **lean/roll + yaw-rate** cornering readout and a
  gyro-sharpened compass. IMU-only, small.

## 2. Rules honored
- **No dead displays:** every readout maps to a CONFIRMED signal; a signal that isn't available is
  **omitted, not shown as NA** (NA/`no source` is reserved for a normally-present signal dropping).
- **Layout mine, semantics Spool's:** boost bands, coolant/IAT thresholds, fuel-trim meaning → Spool.
- **Honest boost:** the assumed-atmospheric caveat is shown; timing/O2/MAF/baro stay off until confirmed.

## 3. Routing
- **Spool:** confirm the per-PID **returns on MD326328** (esp. MAF / BAROMETRIC / O2 / IAT) + boost bands
  + which engine values are worth a live gauge. `tuner/inbox/2026-08-03-...` (this note's companion).
- **CIO:** pick which prototype(s) to prioritize → I take those to a build-ready spec.
- **Marcus/Ralph/Atlas:** on the CIO's pick — P1/P2 are display-only consumers of existing OBD state;
  P3 is a server-tier build (Atlas contract); P4 needs the gyro exposed in `states/imu` (Atlas/Ralph).
