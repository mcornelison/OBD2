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

## 3. Layout (480 × 320; body 258; ≈ 246 used)

```
┌──────────────────────────────────────────────┐
│ PITCH        GRADE  LAST 15 MIN               │
│ +3.1°        ╭──╮      ╭──●  +5.0%           │ ~76
│ nose up   ─ ─│─ ─╰─ ─ ─╯─ ─ ─ ─ (zero)       │
├──────────────────────────────────────────────┤
│ ACCEL                   CORNER R              │
│ 0.31 g                  0.22 g                │ ~75
│ peak ▲0.31 ▼0.38        peak L0.27 R0.31      │
├──────────────────────────────────────────────┤
│ UPDATED                 COMPASS               │
│ 0 s ago                 calibrated            │ ~84
│ TILT FIX                GYRO                  │
│ −0.45° from 14 stops    plausible             │
└──────────────────────────────────────────────┘
```

| Element | Tier | Note |
|---|---|---|
| Pitch | `--fs-primary` | signed, 1 decimal, `°`; sub-line `nose up`/`nose down` `--fs-label` |
| Grade graph | 300 × 58 SVG | dashed zero line, end dot + end value `--fs-meta`; same scale for line, dot and label |
| ACCEL/BRAKE, CORNER | `--fs-primary` | 2 decimals, `g`; peak line `--fs-label` |
| Health values | `--fs-label` | parked-read; status colour `--green-ok` / `--amber-warn` |
| Health block | **2 × 2 grid**, label over value, columns **`1fr max-content`**, 8 px gap. Left column UPDATED / TILT FIX, right column COMPASS / GYRO | **Re-laid 2026-10-15 (S105 review B-2).** One row of 4 `max-content` cells needs 105.5 (`UPDATED`) + 139.5 (`not calibrated`) + 138.9 (`from 14 stops`) + 114.8 (`implausible`) = **498.7 px** in 448, before gaps. **Not equal columns:** at ~220 px each, `−0.45° from 114 stops` (229.4 px) clips. With `max-content` the right column is 139.5 px (`not calibrated`), so the left gets 300.5 px. That fits the worst case, `−10.00° from 9999 stops` = 254.9 px (DejaVu Sans 20 px, measured). +30 px height ⇒ 246 / 258 |
| Grade label | Michroma `--fs-meta` | `GRADE  LAST 15 MIN` (229 px). **No `·`**: the Michroma subset is A-Z 0-9 space hyphen only, so a middle dot would fall back to another font mid-label |

## 4. Behaviour
- **Step at the IMU's 1 Hz publish rate**; no interpolation (these are measurements, not a sweeping heading).
- **ACCEL/BRAKE:** `ACCEL` for `gLon > 0`, `BRAKE` for `< 0` (+ = accelerating, the `imu_state_bridge` contract). Peak line `▲accel ▼brake`; `▲ ▼` are `--font-body` glyphs (DejaVu carries them), never Michroma.
- **CORNER L/R:** word from the sign of the lateral g. Peak line `L… R…`.
- **Peaks reset at drive start, in the PROVIDER** (Atlas ruling 4, 2026-10-14; US-892-a): `states/imu.peaks` all null and `peaks.sinceTs` = the drive-start event time. A null peak shows `--`. No numbers are coloured (no g band exists).
- **Gyro implausible ⇒ pitch `--` + `gyro not plausible`** (amber). Pitch rides the gyro-fused path, so it cannot be trusted then.
- **Health block:**
  - `UPDATED`: seconds since `states/imu.ts`.
  - `COMPASS`: `calibrated` / `not calibrated` from `headingCalibrated`; the key ABSENT (legacy engine) ⇒ `--` + reason (Atlas 2026-10-14 s5). No abbreviations: the 2 × 2 grid (§3) has the room.
  - `TILT FIX`: `biasRad` in degrees + `from N stops` (`stopCount`). **0 stops ⇒ `--` + `no stops yet`**, because 0.0 means not measured (`imu_state_bridge.py:911-916`).
  - `GYRO`: `plausible` / `implausible` from the gyro reason.
- **Stale** (`pi.display.stale.imuSec`, the one IMU key shared with Navigation; strict `age > imuSec`): all motion values dim + age.
- **Absent:** `--` + reason on the glass.

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| pitch, gLon, gLat, gradePct | `states/imu` | exist | — |
| headingCalibrated, biasRad, stopCount, gyro reason, ts | `states/imu` | exist | — |
| **gLon sign** | + = accelerating (`imu_state_bridge` contract) | **confirmed** | — |
| **Peaks this drive** | `states/imu.peaks{accelG, brakeG, leftG, rightG, sinceTs}`, reset on drive start | **ruled** (Atlas 4, 2026-10-14); build US-892-a | Ralph (S105) |
| **15-min grade history** | `states/grade-history` (10 s points, 900 s window, null = gap) | **exists** (US-882-b) | — |
| Stale key | `pi.display.stale.imuSec`, default **3.0 s** (was 2.0; Atlas 2026-10-15, S105 rulings Q3, MEASURED: whole-second `ts` + 100 ms poll make a healthy file read up to 1.94 s old) | **exists** (US-882-c); default change in US-896-a | — |

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
10. Health block: no cell clips with the widest texts together (`not calibrated`, `−10.00° from 9999 stops`, `implausible`, `999 s ago`); `headingCalibrated` absent ⇒ COMPASS `--` + reason.
11. Right after a drive start, every peak reads `--` (peaks null).

## 7. Fixtures
`climb-accel` · `descent-brake` · `corner-left` · `corner-right` · `gyro-implausible` · `compass-uncalibrated` · `no-stops-yet` · `stale-imu` · `history-empty-after-restart` · `compass-legacy-engine` · `peaks-null-after-drive-start`.

## 8. Out of scope
Roll and yaw rate (not published) · altitude (no source) · g meter/dot/trail (US-733) · heading and grade number (Navigation page) · light (Light page).

## 9. Open items
~~gLon sign · peaks provider · grade-history ownership · shared stale key~~ **all RESOLVED 2026-10-15** (§5). None open.
