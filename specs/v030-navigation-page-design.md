# V0.30 Navigation page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12 · **Status:** CIO-APPROVED design (brainstorm 2026-10-12), awaiting V0.30 DoD + grooming
**Mockup:** `proposals/2026-10-12-v030-navigation-page.html` → https://claude.ai/artifact/ETqqi2sYC7fkV2cDqJt9A7 (option A is the locked layout)
**DoD lines served:** 7 (themed pages: Navigation), 8 (real source or says why), 10 (compass shows a true bearing)
**Canonical home:** this is teammate-facing spec ⇒ `specs/` in the repo via a bench (CLAUDE.md §5a). This share copy is the working copy.

---

## 1. Purpose (CIO, 2026-10-12)

**A driving glance: "which way am I heading", in under a second, with no touch (R5).**
The bearing tape is the focal element. Everything else on the page is secondary.

## 2. Decisions locked in the brainstorm

| # | Decision | CIO choice |
|---|---|---|
| N-1 | Page purpose | Driving glance |
| N-2 | Elements around the tape | Heading digits + compass point · road grade % · trip (distance + elapsed). **No speed** (the driving page owns it) |
| N-3 | Tape | The July-locked tape (90° window), made bigger as the hero |
| N-4 | Motion between 1 Hz readings | **Glide** |
| N-5 | Doubtful heading (uncalibrated / starting up) | **Tape drawn normally + a legible badge** |
| N-6 | Trip meaning | **This drive**, resets at key-on |
| N-7 | Grade form | Number + slope glyph, **one decimal** |
| N-8 | Layout | **A · Tape on top** |
| N-9 | Centre reference | **Thin hairline** (not the triangle caret removed by US-715) |
| N-10 | Distance unit | **Miles**, here and on every V0.30 page unless the CIO says otherwise |
| N-11 | Trip distance source | **Request US-704 into V0.30** |
| N-12 | Compass points | **8** (N NE E SE S SW W NW) |
| N-13 | Stale feed | **Freeze + amber `NO UPDATE n s` badge**, distinct from sensor dead |
| N-14 | Before the car moves | `0.0 mi · 0:00` |

**Iris condition attached to N-5:** the badge is `--fs-label` (20 px) on `--amber-warn`, never a corner speck. **A dead sensor still draws no tape**: there is no heading to draw, so N-5 does not apply to it.

## 3. Layout (480 × 320; body = 320 − `--bar-h` 34 − `--dots-h` 16 − 12 padding = 258 px)

```
┌──────────────────────────────────────────────┐  top bar (V0.30 page-set design, not this spec)
│                               [NOT CALIBRATED]│  22   BADGE ROW: state badge only, --fs-label
│   SW  ·  ·  |  ·  ·  W  ·  ·  |  ·  ·  NW     │
│   ┃     ╷     ╷     ┃     ╷     ╷     ┃       │  70   TAPE (hero) · hairline at centre
│                    247° SW                    │  46   --fs-hero digits · --fs-primary point
│                                               │       (~35 px deliberate slack)
│ GRADE                            THIS DRIVE   │
│ ⟋ +4.1 %                            12.4 mi   │  ~79  values --fs-primary
│                                  0:23 elapsed │       elapsed --fs-label
└──────────────────────────────────────────────┘  page dots
```

| Band | Content | Type tokens | Height |
|---|---|---|---|
| Badge row | State badge, right-aligned (`--amber-warn` fill). Empty when trusted; height kept | `--fs-label` | 22 |

> **Superseded 2026-10-14 (title row):** the frame spec (§3) removes every page's title row, and the page name moves into the top bar. **This page's bar name is `NAV`** (CIO 2026-10-14; `NAVIGATION` at 135 px doesn't fit the 122 px slot, frame §3.2). **Badge home DECIDED 2026-10-15 (S105 review G-1): the 22 px row stays, as a BADGE ROW above the tape, badge right-aligned.** Measured in `--font-body` at 20 px: `NOT CALIBRATED` 175.3 px, `NO UPDATE 12 s` 166.3, `STARTING UP` 134.0. On the tape band's right end the badge would cover ~37° of the 90° window, including the W/NW letters: it would hide the hero to label it. The row keeps its height when empty (trusted), so the tape never jumps when a badge appears or clears. Budget unchanged (223 / 258).
| Tape | Full width (456 px). 90° window. Ticks every 5° (fine), 15° (minor), 45° (major + compass letter). `N` in `--text-primary`, others `--text-secondary`. Centre **hairline** 2 px `--text-primary` | letters `--fs-secondary` | 70 |
| Heading readout | `247°` (zero-padded 3 digits) + 8-point compass letter, centred under the hairline. **8-point rounding:** sector = round(deg / 45) mod 8, half up: `22.5` ⇒ `NE`, `337.5` ⇒ `N` (wraps 8 → 0). A NEW 8-point function; the interim card's 16-point `headingCardinal` retires with that card | `--fs-hero` / `--fs-primary` | 46 |
| Bottom row | **GRADE**: slope glyph + `+4.1 %` · **THIS DRIVE**: `12.4 mi` over `0:23 elapsed` | `--fs-primary` values, `--fs-meta` labels, `--fs-label` elapsed | ~79 |

**Total ≈ 223 / 258.** The slack is deliberate: F-132's clip came from a budget spent to the pixel.
**Every driver-read value is ≥ 34 px** (F-127 floor). Labels (`GRADE`, `THIS DRIVE`) are `--fs-meta`: they are read once, not at a glance.
**All colours and sizes bind tokens** from `src/pi/ui/tokens.css`. No literals.

## 4. Behaviour

### 4.1 Motion
- Each new heading reading starts a **1 s ease-in-out glide** from the currently drawn bearing to the new one.
- **Shortest arc:** 350° → 10° crosses north (+20°), never sweeps back −340°.
- A new reading mid-glide starts a fresh glide **from where the tape is now**, so it never snaps.
- `prefers-reduced-motion` ⇒ **step** to each reading.
- Digits and compass point follow the drawn bearing, so they always agree with the hairline.
- **Why this is not fabrication:** the anti-interpolation rule (Spool 08-07) protects ECU values the ECU never sent. A heading physically sweeps through every intermediate bearing during a turn, so the path between two real readings is the truth, not an invention.

### 4.2 Heading states (precedence top to bottom; first match wins)

| State | Detected from | Tape | Digits | Badge |
|---|---|---|---|---|
| **Sensor dead** | `headingDeg` null **and** reason ≠ `heading_unseeded` | **not drawn**: `NO HEADING` + reason text in its place | `---°` | none (the block is the message) |
| **Stale** | `states/imu.ts` age **> `pi.display.stale.imuSec`** (strict; the ONE IMU stale key, shared with Motion, see §5) | **frozen** at last reading, no glide | last value | `NO UPDATE n s` (counts up) |
| **Starting up** | `headingDeg` null **and** reason = `heading_unseeded` | **frozen/blank** until the first reading, then normal | `---°` until first reading | `STARTING UP` |
| **Not calibrated** | `headingCalibrated == false`, **or the key ABSENT** (legacy engine, Atlas 2026-10-14 s5) | **normal** (N-5) | normal | `NOT CALIBRATED` (false) · `--` + reason (absent); never `not calib.` |
| **Trusted** | otherwise | normal | normal | none |

Reason-code → text mapping lives in one table in `carousel.js` (it already has `imuReason()`); `heading_unseeded` gets text here, **which closes US-821**.

### 4.3 Grade
- `gradePct`, one decimal, signed (`+4.1`, `−2.4`). Slope glyph tilts with the sign: up = climbing.
- `gradePct` null ⇒ `--` + its reason text in `--fs-label`, **on the glass** (the US-852 rule: a reason that exists only in the DOM tells nobody anything).

### 4.4 Trip (this drive)
- Resets at key-on. Before the car moves: `0.0 mi · 0:00`.
- Distance: **US-704** producer. Until it exists, the slot shows `-- mi` with `not measured yet`. Never a fabricated zero mid-drive.
- Elapsed: from the drive-start time (field named by Atlas, §5). Format `h:mm`.
- Miles, one decimal.

### 4.5 Parked
Heading and grade stay live: parked, the IMU heading is **correct**, not unavailable (F-127 idle-face ruling). Nothing greys out because the car stopped.

## 5. Data contract (needs from other lanes)

| Need | Source | Status | Owner |
|---|---|---|---|
| True heading | `states/imu.headingDeg` (0–360 cw from TRUE north, declination applied, `ahrs_fusion.py:492`) | exists | — |
| Calibration flag | `states/imu.headingCalibrated` (`imu_state_bridge.py:989`) | exists | — |
| Startup / dead reasons | `states/imu` reasons map, `heading_unseeded` (`imu_state_bridge.py:505`) | exists | — |
| Grade | `states/imu.gradePct` + reason | exists | — |
| Staleness | `states/imu.ts` age vs `pi.display.stale.imuSec` (2.0 s), injected as `window.DISPLAY_STALE.imuSec` | **exists** (US-882-c) | — **reused 2026-10-15** (Iris/Marcus, S105 Q3). My earlier "3 missed readings" was intent, not a number. One provider ⇒ one key: two keys would let NAV freeze while Motion shows live on the same fact. At a 1 Hz publish 2.0 s is 2 missed readings; if it nuisance-flashes in the car, the fix is config |
| Trip distance | US-704 producer | **not built** | **Marcus: admit to V0.30** |
| Drive start time | a drive-state field | **unconfirmed** | **Atlas: name it** |

**Rule kept from Atlas's 2026-08-20 WiFi ruling:** the page **renders what providers derive** and applies no threshold of its own. The one page-side judgement (staleness) has its number in config.

**Depends on, not built here:** US-695 calibration (DoD 10). Until it passes, the `NOT CALIBRATED` badge is the expected state.

## 6. Acceptance criteria (draft for grooming)

1. Given each fixture in §7, the page at 480×320 shows the tape / digits / badge in the §4.2 table, verified by screenshot.
2. No element clips: every tile/band `scrollHeight <= clientHeight` (DOM check, all fixtures).
3. Computed font-size of heading digits, grade value and trip distance ≥ 34 px.
4. Glide (fake clock, JS unit): reaches the target within 1000 ms; 350→10 moves +20°; a mid-glide reading starts from the current drawn bearing; reduced-motion steps.
5. Stale: with `ts` held, once its age exceeds `imuSec` (strict `>`) the tape stops moving and `NO UPDATE n s` appears and counts.
6. A dead sensor draws **no** tape element at all, not a hidden or zero-opacity one.
7. Every null value shows its reason text on the glass (no reason only in the DOM).
8. **No literal colour or px** in the page's CSS (grep gate, extends US-539/US-557).
9. **DoD (R15): the CIO, in the car, reads the bearing at a glance with no touch.**
10. Compass point: `22.5` ⇒ `NE`, `337.5` ⇒ `N`, `247` ⇒ `SW` (8-point, R25).
11. The badge sits in its own row above the tape; no badge overlaps any tape element (DOM rect check).

## 7. Fixtures (static state files; no replay rig, per R20)

`trusted-247` · `uncalibrated` · `legacy-engine-no-flag` · `boundary-022.5` · `boundary-337.5` · `unseeded` · `dead-mag` · `stale-imu` · `wrap-350-to-010` (two consecutive files) · `parked-engine-off` · `grade-null`.

## 8. Out of scope

Speed (driving page) · altitude (no source: no baro, GPS on hold) · position/route/destination (no GPS) · a resettable trip · soft-iron calibration (CIO Q-B: out) · the top bar and page dots (page-set design, next).

## 9. Open items

- **US-704 admission** to V0.30: Marcus, at the DoD.
- ~~Stale-threshold config key~~ **RESOLVED 2026-10-15: `pi.display.stale.imuSec`** (§5).
- **Trip (§4.4) is OPEN, S105 review B-1:** (a) elapsed needs an END: `distanceKm`/`distanceSinceTs` hold after the drive ends, so `now − sinceTs` would keep counting while parked; (b) `distanceSinceTs` is the drive start OR the first SPEED reading after a mid-drive restart, so `THIS DRIVE` needs a provider flag; (c) no page-side zero: at drive start the provider publishes 0.0. **Atlas** names the fields; **CIO** rules Q1 (does a parked trip slot read `LAST DRIVE`?). §4.4 is rewritten once both land.
- **DoD 10 pass numbers** (90 % vs 95 %): already raised in my DoD review.
