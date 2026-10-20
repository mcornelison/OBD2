# V0.30 Motion page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12, S105 folds 2026-10-19 (UIDEV-006) · **Status:** CIO-APPROVED design; **built in S105** (US-892-a/b/c)
**Mockup:** OEM skin `proposals/2026-10-14-v030-motion-page-oem.html` → https://claude.ai/artifact/WMaKutBNqiFuhw37c12F4L (**build from this**); the pre-OEM layout study is https://claude.ai/artifact/75enppFLkdqrHAyjhRCMG4 (layout A)
**DoD lines served:** 7 (themed pages: Motion; R10 amended by the CIO 2026-10-12, "Motion + light" split into two pages), 8
**Canonical home:** `specs/` in the repo via a bench.

> **2026-10-19 fold (UIDEV-006).** This revision folds the S105 rulings: Iris M1–M7 (`pm/inbox/2026-10-19-from-iris-S105-rulings-Motion-M1-M7-Light-L1-L7.md`), Atlas B3/B5/C1–C3 (`…-from-atlas-RULED-S105-relaunch-gaps-…md`), and the CIO's US-911 choice (one `CALIBRATION_ABSENT_TEXT`). The S105 build agrees with it. **Fonts:** `--font-body` is not a token. Every non-Michroma text on this page is `--font-mono`; on the Pi that resolves to DejaVu Sans Mono (0.60205 em, the measured `ADVANCE_OBSERVED`). Every width below is measured in that face: 12.04 px per character at `--fs-label` (20 px), 9.03 at `--fs-meta` (15 px).

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
| Pitch | `--fs-primary` | signed, 1 decimal, `°`; sub-line `nose up` / `nose down` / `level` at `--fs-label` (§4.1) |
| Grade graph | 300 × 58 SVG | dashed zero line, end dot + end value `--fs-meta`; same scale for line, dot and label; null = gap (§4.2) |
| ACCEL/BRAKE, CORNER | `--fs-primary` | 2 decimals, `g`; peak line `--fs-label` (§4.3) |
| Health values | `--fs-label` | parked-read; colours per §4.4 |
| Health block | **2 × 2 grid**, label over value, columns **`1fr max-content`**, 8 px gap. Left column UPDATED / TILT FIX, right column COMPASS / GYRO | **Re-measured in mono 2026-10-19 (C3).** The right column's widest value is `not calibrated` = **168.6 px**, so the left column gets 448 − 8 − 168.6 = **271.4 px**. TILT FIX is split by size (§4.4): `−10.00°` at `--fs-label` (84.3 px) + 6 px + `from 999 stops` at `--fs-meta` (126.4 px) = **216.7 px**, 54.7 px spare. The worst case is set by the provider's bound, `pi.sensors.imu.zuptWindowStops` (20 as shipped), with 3 digits allowed, not by an invented 9,999 (Atlas C3). The spec's earlier 254.9 px figure was measured in DejaVu Sans, not the mono face the build uses, and is superseded |
| Reason sub-lines | `--fs-meta`, `--text-secondary` | **A reason never sizes a column** (Atlas C3): `contain: inline-size` on the reason element, so it adds 0 to max-content and wraps inside its own column. Measured: `calibration not published` = 225.8 px and `orientation unresolved` = 198.7 px would each push the left column under 265 px as max-content |
| Grade label | Michroma `--fs-meta` | `GRADE  LAST 15 MIN` (229 px). **No `·`**: the Michroma subset is A-Z 0-9 space hyphen only, so a middle dot would fall back to another font mid-label |

## 4. Behaviour
- **Read RAW `states/imu`. Step at the IMU's 1 Hz publish rate**; no interpolation and no page-side smoothing (these are measurements). The old 3 s page smoothing (US-662) retired with the old g tile (Atlas B3). If g jitters in the car, the fix goes in the provider, never back into the page.

### 4.1 Pitch
- Signed, 1 decimal, `°`. Negative is U+2212 `−`; positive is `+`, as NAV grade.
- **The sign comes from the ROUNDED value.** A value that rounds to `0.0` shows `0.0°` with no sign and the sub-line `level`. Never `−0.0°`, and never `nose up` at zero.
- **Gyro implausible ⇒ pitch `--` + `gyro implausible`** (the existing `IMU_REASON_TEXT.gyro_implausible`; one reason code, one text on every page — Atlas B5). Pitch rides the gyro-fused path, so it can't be trusted then.

### 4.2 Grade graph
- Source `states/grade-history` (10 s points, 900 s window).
- **A null point ends the polyline**; the next real point starts a new segment. A gap is never drawn as a straight interpolation.
- Empty history, or every point null: exactly `no grade history yet`, `--font-mono` `--fs-meta` `--text-tertiary`, above the dashed zero line (180.6 px of the 300 px graph).

### 4.3 g-force
- **ACCEL/BRAKE:** `ACCEL` for `gLon > 0`, `BRAKE` for `< 0` (+ = accelerating, the `imu_state_bridge` contract).
- **CORNER L/R:** word from the sign of the lateral g.
- **Peak lines:** `peak ▲0.31 ▼0.38` and `peak L0.27 R0.31`. Keep the word `peak`; no space after the marker. `--font-mono` at `--fs-label`, `--text-secondary`, never coloured. Widths 192.7 px; `peak ▲-- ▼--` 144.5 px; mid column 225 px. `▲ ▼` set no font-family (they inherit the mono face, which carries them), never Michroma.
- **Peaks reset at drive start, in the PROVIDER** (Atlas ruling 4, 2026-10-14; US-892-a): `states/imu.peaks` all null and `peaks.sinceTs` = the drive-start event time. A null peak shows `--`, e.g. `peak ▲-- ▼0.38`. No numbers are coloured (no g band exists).

### 4.4 Health block

| Cell | State | Text | Colour |
|---|---|---|---|
| UPDATED | fresh | `N s ago` | `--text-primary` |
| UPDATED | stale (`age > imuSec`) | `N s ago` | `--amber-warn` |
| UPDATED | `ts` null or unparseable | `--` + `no timestamp` | `--` `--text-tertiary`; reason `--text-secondary` `--fs-meta` |
| COMPASS | `headingCalibrated` true | `calibrated` | `--green-ok` |
| COMPASS | false | `not calibrated` | `--amber-warn` |
| COMPASS | key ABSENT | `--` + the published `reasons.headingCalibrated` text via `imuReason`, else `CALIBRATION_ABSENT_TEXT` = `not published` | `--` `--text-tertiary`; reason `--text-secondary` `--fs-meta` |
| TILT FIX | `stopCount` > 0 | `±n.nn°` + `from N stops` | value `--text-primary` `--fs-label`; provenance `--text-secondary` `--fs-meta`, one baseline, 6 px gap |
| TILT FIX | `stopCount` 0 | `--` + `no stops yet` | as COMPASS absent (0.0 means not measured, `imu_state_bridge.py:911-916`) |
| GYRO | `reasons.pitchDeg` == `gyro_implausible` | `implausible` | `--amber-warn` |
| GYRO | `pitchDeg` is a published finite number | `plausible` | `--green-ok` |
| GYRO | every other case (`sensor_absent`, `tilt_unresolved`, `pitch_unseeded`, not available) | `--` + `imuReason(data, "pitchDeg")` | as COMPASS absent. **A dead IMU never reads green** (Atlas C2). `pitch_unseeded` reads `starting up` |

- **Status colours** go on the status cells only: COMPASS, GYRO, and UPDATED when stale. TILT FIX is a measurement with no band, so it is never green or amber.
- **COMPASS absent is tertiary here, not NAV's amber chip, on purpose.** On NAV the badge qualifies the hero, so the driver has to doubt the tape. On Motion it is a parked-read fact cell, and the page's typed-absence style is a tertiary `--` plus a reason. Both agree on what matters: an unknown calibration is never green.
- **One absent-calibration text (CIO, US-911, 2026-10-19):** `CALIBRATION_ABSENT_TEXT = "not published"` is the only literal. Motion shows it under the COMPASS label, which supplies the context. NAV's badge has no label, so NAV builds `"calibration " + CALIBRATION_ABSENT_TEXT`, and its output stays `calibration not published` exactly.
- **TILT FIX number:** explicit `+` on positive (`+0.45°`), U+2212 on negative. The sign comes from the rounded value, so a zero shows `0.00°` with no sign; with `stopCount` > 0 that zero is a measured value. `from 1 stop` singular, `from N stops` plural, `N` through the fixed-`,` thousands formatter (`fmtThousands`, shared with Light).
- **UPDATED age:** `Math.floor((now − ts) / 1000)`, clamped at 0 (a future `ts` reads `0 s ago`). Written `N s ago` with a space (the V0.30 spaced-unit convention; NAV's `NO UPDATE n s` is the same rule). Above 999: `999+ s ago` (120.4 px). Never `fmtAgeSec` (`12s` / `1.2s`), which older cards use and which stays unchanged. The stale **decision** keeps the raw float (`age > imuSec`, strict); floor is for the displayed number only.

### 4.5 Stale and absent
- **Stale** (`pi.display.stale.imuSec`, the one IMU key shared with Navigation; strict `age > imuSec`; an undated payload counts as stale): the pitch cell, the grade graph and both g cells dim (opacity .4). **The age appears in exactly one place, the UPDATED cell, in amber.**
- **The health block never dims.** It is the evidence that the data is stale; dimming it would hide the reason exactly when it matters.
- **Absent:** `--` + reason on the glass.

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| pitchDeg, gLon, gLat, gradePct | `states/imu` | exist | — |
| headingCalibrated, biasRad, stopCount, `reasons.{pitchDeg, headingCalibrated}`, ts | `states/imu` | exist | — |
| **gLon sign** | + = accelerating (`imu_state_bridge` contract) | **confirmed** | — |
| **Peaks this drive** | `states/imu.peaks{accelG, brakeG, leftG, rightG, sinceTs}`, reset on drive start | **built** (US-892-a) | — |
| **15-min grade history** | `states/grade-history` (10 s points, `intervalS` / `windowS` as published; null = gap) | **exists** (US-882-b). The page reads the provider names; `intervalSec` / `windowSec` are only the config keys (Atlas B4) | — |
| Stale key | `pi.display.stale.imuSec`, default **3.0 s** (Atlas 2026-10-15, S105 Q3) | **exists** (US-882-c, US-896-a) | — |
| `stopCount` bound | `pi.sensors.imu.zuptWindowStops`, 20 as shipped | exists; a validator upper bound (≤ 999) is banked for S106 (Atlas C3) | Ralph |

## 6. Acceptance criteria
1. Fixtures render per §4 at 480×320 (screenshot).
2. No clipping; pitch and g values ≥ 34 px.
3. Longitudinal label is `ACCEL` for positive and `BRAKE` for negative (per the confirmed sign); lateral `L`/`R` likewise.
4. Gyro-implausible fixture ⇒ pitch `--` + `gyro implausible`; the health block shows `implausible` in amber.
5. `stopCount = 0` ⇒ TILT FIX `--` + `no stops yet`, never `0.00°`.
6. No g meter, dot or trail element exists in the DOM (US-733).
7. Grade graph: line, end dot and end label use one scale; the label value equals the last history point; a null point breaks the line.
8. No literal colour or px in this page's CSS.
9. **DoD (R15): CIO judgement in the car.**
10. Health block: no cell clips with the widest texts together (`not calibrated`, `−10.00°` + `from 999 stops`, `implausible`, `999+ s ago`), nor with `compass-legacy-engine` + the widest TILT FIX; `headingCalibrated` absent ⇒ COMPASS `--` + reason.
11. Right after a drive start, every peak reads `--` (peaks null).
12. Pitch that rounds to zero ⇒ `0.0°` + `level`, no sign.
13. A GYRO cell never reads `plausible` unless `pitchDeg` is a published finite number (`gyro-unjudged`).
14. Stale dims the top two bands only; the health block keeps full opacity.

## 7. Fixtures
As built in S105 (`tests/ui/fixtures/states/motion/`): `climb-accel` · `descent-brake` · `corner-left` · `corner-right` · `gyro-implausible` · `gyro-unjudged` · `compass-uncalibrated` · `compass-legacy-engine` · `health-trusted` · `no-stops-yet` · `stale-imu` · `history-empty-after-restart` · `peaks-null-after-drive-start`.

## 8. Out of scope
Roll and yaw rate (not published) · altitude (no source) · g meter/dot/trail (US-733) · heading and grade number (Navigation page) · light (Light page).

## 9. Open items
None. ~~gLon sign · peaks provider · grade-history ownership · shared stale key~~ resolved 2026-10-15; the S105 rulings are folded 2026-10-19.
