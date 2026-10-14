# V0.30 Motion page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12 · **Status:** CIO-APPROVED design (brainstorm 2026-10-12), awaiting V0.30 DoD + grooming
**Mockup:** `proposals/2026-10-12-v030-motion-page.html` → https://claude.ai/artifact/75enppFLkdqrHAyjhRCMG4 (**layout A is the locked one**)
**DoD lines served:** 7 (themed pages: Motion; R10 amended by the CIO 2026-10-12, "Motion + light" split into two pages), 8
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose (CIO: "Both")
How the car is moving right now, **and** whether the motion sensor can be trusted. Live motion on top, IMU health below.

## 2. Decisions locked (CIO, 2026-10-12)

| # | Decision | CIO choice |
|---|---|---|
| M-1 | Purpose | Both: live motion + sensor health |
| M-2 | Elements | Pitch · grade trend graph · g-force as numbers |
| M-3 | Page split | **Motion and Light are two pages** (amends R10) |
| M-4 | g-force | **Now + peak this drive**; numbers only (US-733's meter stays removed) |
| M-5 | Pitch | **Degrees only** |
| M-6 | g labels | **ACCEL/BRAKE** (flips with sign) + **CORNER L/R** |
| M-7 | Health | **A full health block** |
| M-8 | Layout | **A · Pitch and trend first** |
| M-9 | Trend window | **15 minutes** |

## 3. Layout (480 × 320; body 258; ≈ 216 used)

```
┌──────────────────────────────────────────────┐
│ PITCH        GRADE · LAST 15 MIN              │
│ +3.1°        ╭──╮      ╭──●  +5.0%           │ ~76
│ nose up   ─ ─│─ ─╰─ ─ ─╯─ ─ ─ ─ (zero)       │
├──────────────────────────────────────────────┤
│ ACCEL                   CORNER R              │
│ 0.31 g                  0.22 g                │ ~75
│ peak ▲0.31 ▼0.38        peak L0.27 R0.31      │
├──────────────────────────────────────────────┤
│ UPDATED   COMPASS     TILT FIX       GYRO     │
│ 0 s ago   calibrated  −0.45°         plausible│ ~54
│                       from 14 stops           │
└──────────────────────────────────────────────┘
```

| Element | Tier | Note |
|---|---|---|
| Pitch | `--fs-primary` | signed, 1 decimal, `°`; sub-line `nose up`/`nose down` `--fs-label` |
| Grade graph | 300 × 58 SVG | dashed zero line, end dot + end value `--fs-meta`; same scale for line, dot and label |
| ACCEL/BRAKE, CORNER | `--fs-primary` | 2 decimals, `g`; peak line `--fs-label` |
| Health values | `--fs-label` | parked-read; status colour `--green-ok` / `--amber-warn` |

## 4. Behaviour
- **Step at the IMU's 1 Hz publish rate**; no interpolation (these are measurements, not a sweeping heading).
- **ACCEL/BRAKE:** word from the sign of the longitudinal g (**sign convention to confirm, §5**). Peak line `▲accel ▼brake`.
- **CORNER L/R:** word from the sign of the lateral g. Peak line `L… R…`.
- **Peaks reset at key-on.**
- **Gyro implausible ⇒ pitch `--` + `gyro not plausible`** (amber). Pitch rides the gyro-fused path, so it cannot be trusted then.
- **Health block:**
  - `UPDATED`: seconds since `states/imu.ts`.
  - `COMPASS`: `calibrated` / `not calib.` from `headingCalibrated`.
  - `TILT FIX`: `biasRad` in degrees + `from N stops` (`stopCount`). **0 stops ⇒ `--` + `no stops yet`**, because 0.0 means not measured (`imu_state_bridge.py:911-916`).
  - `GYRO`: `plausible` / `implausible` from the gyro reason.
- **Stale** (shared timeout key): all motion values dim + age.
- **Absent:** `--` + reason on the glass.

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| pitch, gLon, gLat, gradePct | `states/imu` | exist | — |
| headingCalibrated, biasRad, stopCount, gyro reason, ts | `states/imu` | exist | — |
| **gLon sign** (+ = accelerating?) | convention | **confirm** | Atlas |
| **Peaks this drive** | **provider** (survives kiosk restart; providers derive, Atlas 08-20) | **new** | Atlas |
| **15-min grade history** | today held client-side by the live card ⇒ lost on kiosk restart | **decide: provider or page** | Atlas |

## 6. Acceptance criteria (draft)
1. Fixtures render per §4 at 480×320 (screenshot).
2. No clipping; pitch and g values ≥ 34 px.
3. Longitudinal label is `ACCEL` for positive and `BRAKE` for negative (per the confirmed sign); lateral `L`/`R` likewise.
4. Gyro-implausible fixture ⇒ pitch `--` + reason; the health block shows `implausible` in amber.
5. `stopCount = 0` ⇒ TILT FIX `--` + `no stops yet`, never `0.00°`.
6. No g meter, dot or trail element exists in the DOM (US-733).
7. Grade graph: line, end dot and end label use one scale; the label value equals the last history point.
8. No literal colour or px in this page's CSS.
9. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`climb-accel` · `descent-brake` · `corner-left` · `corner-right` · `gyro-implausible` · `compass-uncalibrated` · `no-stops-yet` · `stale-imu` · `history-empty-after-restart`.

## 8. Out of scope
Roll and yaw rate (not published) · altitude (no source) · g meter/dot/trail (US-733) · heading and grade number (Navigation page) · light (Light page).

## 9. Open items (Atlas)
gLon sign · peaks provider · grade-history ownership · shared stale key.
