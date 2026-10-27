# V0.30 Driving page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12 · **Status:** CIO-APPROVED design (brainstorm 2026-10-12), awaiting V0.30 DoD + grooming. **Reworked 2026-10-13:** Spool's RPM bands + gear-hint rule, Atlas's `states/obd-live` + key names, R31 takeover.
**Mockup:** `proposals/2026-10-12-v030-driving-page.html` → https://claude.ai/artifact/NGQYx33xXbfcCeUecgscfW (**layout B is the locked one**)
**DoD lines served:** 6 (driving page: RPM + gear central, speed), 8 (real source or says why) · **Feature:** F-140
**Reference:** `pm/evidence/v030-dashboard-reference/2026-09-06-aem-dash-1999-eclipse-gsx-CIO-reference.png` (AEM digital dash), the hierarchy only; 4 of its 9 elements have no source on this car (boost, AFR, oil pressure, fuel pressure) and are absent, not faked.
**Canonical home:** `specs/` in the repo via a bench (CLAUDE.md §5a). This share copy is the working copy.

---

## 1. Purpose

The **default page** (R5): readable at a glance while driving with **no touch**. A driver's hierarchy, not a data hierarchy: gear and RPM dominate, speed is readable but subordinate, engine health sits at the edges.

## 2. Decisions locked in the brainstorm (CIO, 2026-10-12)

| # | Decision | CIO choice |
|---|---|---|
| D-1 | RPM treatment (every PID arrives at 0.446 Hz = **~2.2 s**, Spool MEASURED 2026-10-13; tiers banked for V0.30, R34) | **Big number + segmented bar**, stepping |
| D-2 | Peripheral readings | **Coolant · battery voltage · intake air** |
| D-3 | Temperature unit | **°F** (converted from the ECU's °C) |
| D-4 | Speed prominence | **Subordinate** (34 px, boxed) |
| D-5 | Shift cue | **Redline zone + flash** (Iris recommended none because of the lag; CIO chose the flash knowingly) |
| D-6 | Periphery colour | **Always colour-coded** (green / amber / red) |
| D-7 | Stale OBD value | **Dim + age after 5 s** |
| D-8 | Between gears | **Hollow hint of the likely next gear + arrow**, solid when the measured gear confirms; **glide** on change. Hint rule: Spool 2026-10-13 (§4.2) |
| D-9 | Layout | **B · Side columns** |
| D-10 | Gear size | **100 px** (`--fs-giant`; was 120, CIO 2026-10-27 in car: *"slightly smaller … to increase the size of the number mph value"*) |
| D-11 | RPM number placement | **Right column**. R9 ("RPM + gear central") is met by the **central RPM bar** |
| D-12 | Column assignment | **Left: coolant + intake air · Right: RPM + battery** |
| D-13 | Distance/speed unit | **mph** (CIO: miles on every V0.30 page) |

**On D-8, why not a solid prediction** (CIO asked first for "anticipate the next gear"): speed falling doesn't mean a downshift (coasting, braking to a light and climbing a hill all lose speed in gear), so a solid prediction would show a gear you are not in. Spool's standing rule is *never a wrong number*. The outlined hint keeps the CIO's idea and keeps measured visually separate from guessed.

## 3. Layout (480 × 320; body 258 px)

```
┌──────────────────────────────────────────────┐ top bar (page-set design)
│▮▮▮▮▮▮▮▮▮▮▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯ ▯▯│ 22  RPM bar, 16 seg to 8,000: 11 green · 3 yellow (5,500–6,999) · 2 red (≥7,000)
│ COOLANT    │                     │       RPM   │
│ 199 °F     │        ████         │      2,850  │
│            │       ██  ██        │             │ ~220
│ INTAKE AIR │          ██  (120px)│     BATTERY │
│ 88 °F      │   ┌────────┐        │     14.1 V  │
│            │   │ 47 mph │        │             │
└──────────────────────────────────────────────┘ page dots
   120 px            centre              120 px
```

- Every value `--fs-primary` (34 px), **except speed: `--fs-hero` (44 px)** (CIO 2026-10-27). Labels `--fs-meta`; units `--fs-label`.
- **Gear `--fs-giant` = 100 px** (was 120; CIO 2026-10-27, relay: *"the gear to be slightly smaller … and align top with the words coolant and RPM … to increase the size of the number mph value"*). It is still the top tier above `--fs-hero`, so the scale stays descending (`tests/ui/test_dashboard_type_scale.py`). **MOVED PIN:** `tests/ui/test_dashboard_type_scale_values.py:48` `"fs-giant": 120` → `100`.
- **Top-aligned:** the gear glyph's cap top lines up with the cap tops of the `COOLANT` and `RPM` labels, within 2 px on a screenshot. **All three columns align to the start** (`justify-content: flex-start` on `.drv-col` and the centre; R2, UIDEV-021, S119 review 2026-10-27): with the side columns `space-around`, the label cap tops moved 13.5 px between the plain, wrapped and note states, so no constant could hold 2 px. The offset is ONE token, **`--drv-gear-top: -15px`**, declared in the `#driving-card` block. It is measured from the repo's `michroma-brand.woff2`: unitsPerEm 2048, OS/2 `sCapHeight` 1536, typo/hhea ascender 2368, descender −544, line gap 0, USE_TYPO_METRICS set. Cap top below the line-box top = (L·fs − 1.421875·fs)/2 + 0.40625·fs: gear (100 px, L 1) 19.53 px; label (15 px, L 1.2) 4.43 px; so −15.10, rounded to −15 px.
- **Speed fit:** the widest is `120 mph`: 3 mono digits at 44 px = 79.5 px + `--drv-unit-gap` 4 + `mph` at 20 px = 36.1 px (no leading space, as built), + 2 × 8 box padding + 2 border = **137.6 px of 208** (corrected, UIDEV-021, S119 review 2026-10-27).
- **Height:** the gear's 20 px pays for the speed's +10. Total ≤ 248 of the real 254 px body (320 − 34 − 16 − 2 × 8; this spec's 258 predates the corrected budget).

## 4. Behaviour

### 4.1 RPM
- Number + bar **step** with each reading. **No interpolation** (Spool 08-07: it fabricates values the ECU never sent).
- Bar: 16 segments × 500 rpm, zoned by each segment's lower edge (R35, Spool 2026-10-13):
  | Zone | RPM | Token | Meaning |
  |---|---|---|---|
  | green | < 5,500 | `--green-ok` | normal |
  | yellow | 5,500–6,999 | `--amber-warn` | **the CIO's display cue, not an engine threshold** (stock peak power is at 6,000) |
  | red | ≥ 7,000 | `--critical-red` | the spec's valve-float limit |
- **Never call yellow a shift light.** RPM is ~2.2 s old, so at WOT in 1st/2nd the bar can lag the engine by **2,000+ rpm**.
- The zone edges come from the **provider**, never literals in the page: proposed `obd-live.params.RPM.scale {amberFrom, redFrom}` (Sprint 98 review S-6, to Marcus + Atlas 2026-10-13). Source of the numbers: `specs/grounded-knowledge.md` :84 (Atlas keeps it).
- RPM ≥ red-zone start ⇒ lit red segments **flash** (0.5 s, 2-step) and the number turns `--critical-red`. `prefers-reduced-motion` ⇒ no flash, colour only. The number stays white in the yellow zone (style spec rule 4).

### 4.2 Gear
| Gear state | Glyph |
|---|---|
| Measured gear (1–5, N, P per the emitter) | solid, `--text-primary` |
| Between gears **with** a hint | **hollow outline** of the hinted gear + an up/down arrow, `--text-secondary` (drawn as below) |
| Between gears, **no** hint | `--` |
| Measured gear changes | 0.35 s **glide** (fade + 14 px rise), on change only, not on every reading; reduced-motion ⇒ instant |

The reason line under `--` is **dropped on this page** (glance view); detail keeps it.

**How the hint is drawn (S117 review, 2026-10-26).** The gear face is Michroma, and its 38-glyph subset has no arrow characters, so the arrow is a **shape**, never text:
- **Hollow digit:** `.drv-gear-hint { color: transparent; -webkit-text-stroke: var(--drv-hint-stroke) var(--text-secondary); }`, with `--drv-hint-stroke: 3px` declared on `#driving-card`. Same face, size and position as the solid gear, so a hint and a measured gear differ only in fill. They are never identical.
- **Arrow:** an inline SVG triangle, `<svg class="drv-hint-arrow" viewBox="0 0 10 10">`, path `M5 0 L10 10 L0 10 Z` for up and the same path flipped for down, `fill: currentColor` in `--text-secondary`, in a `var(--drv-hint-arrow)` = 30px square box. It is absolutely positioned at `left: calc(100% + var(--drv-gap))`, centred vertically on the digit, so the digit sits exactly where a solid gear draws and nothing moves when the hint turns solid.
- **Fit (computed, at 100 px, 2026-10-27; corrected UIDEV-021, S119 review 2026-10-27):** the widest hint digit is **`4`, 1.000 em** × 100 px = 100 px (`1`, `2`, `3`, `5` are 0.951 em; `michroma-advances.json`). Centred in the 208 px centre column (448 body − 2 × 120), its right edge is at x 154, and the 30 px arrow runs 160–190: inside 208, with 18 px spare. *(At 120 px it was 120 px wide, arrow 170–200, 8 px spare.)*
- carousel.js and dashboard.html contain no `↑`/`↓` character. The only new px are `--drv-hint-stroke` and `--drv-hint-arrow`, in the `#driving-card` custom-property block.

**Hint rule (Spool 2026-10-13; computed by `gearHint` in `gear_derivation.py`, published by `gear_state_emitter` as `hintGear` + `hintDirection` on `states/gear`, names approved by Atlas G-2).** A hint exists only when **all** hold:
- the gear reason is in {`no_band_match`, `ambiguous`, `settling`};
- the last **solid** gear G was ≤ 5 s ago;
- speed > 15 km/h.

| Condition | Glyph |
|---|---|
| latest RPM < RPM at G, and speed not falling (≥ previous − 2 km/h) | hollow **G+1** + `↑` |
| latest RPM > RPM at G, and speed falling | hollow **G−1** + `↓` |
| anything else (e.g. braking with the clutch in drops both) | `--` |

**A hint outside 1..5 is no hint (null); a hint never equals G** (Spool 2026-10-26, replacing "clamped to 1..5": a clamp would show a hollow 5 while in 5th). **A hint never becomes solid**; only gear derivation makes a solid gear. The page renders the two fields and computes nothing.

### 4.3 Engine numbers (coolant, intake air, battery)
- **Always colour-coded**: `--green-ok` / `--amber-warn` / `--critical-red`.
- **The band is derived by the PROVIDER, never by the page** (Atlas 08-20 rule). The page maps `band → token`. This keeps the dwell rules in one place:
  - Coolant: amber only after the dwell; **red ≥ 110 °C on the first sample**; reset floor below the trigger (Spool 08-21).
  - Intake air: **never red** (Spool).
  - Battery: banded **only while the engine runs** (Spool's engine-running gate); engine off ⇒ neutral `--text-primary` with no band.
- Temperatures display in **°F**, converted from °C **for display only**. Bands are always judged in °C by the provider, so a rounding edge can't flip a colour.
- Absent value ⇒ `--` + reason **on the glass** (US-852 rule).
- **Live coolant red ⇒ the full-screen takeover** (R31, scope ruled 2026-10-14; Warnings spec §4.4) covers this page with `PULL OVER` + value + unit. The tile underneath still goes red, so the page is correct the moment the takeover closes.
- **Battery red and RPM red never take over** (CIO 2026-10-14). The tile goes red from its band, and the top-bar icon shows WATCH (Warnings §4.4a). A red tile with an amber icon is correct: the band and the alert tier are different facts.

### 4.4 Staleness
- After **5 s** without a new reading (**`pi.display.stale.obdLiveSec` = 5**, Atlas 2026-10-13; 0.3 % of RPM gaps over 57 drives exceed it, and those are real stalls), a value **dims** (opacity ≈ 0.4) and shows its age in `--amber-warn` `--fs-meta` (`12 s`). Applies to RPM, speed, coolant, intake air, battery and gear.
- **A stale value still arrives with its number** (review B-3, shape ruled by Atlas and folded into US-874, 2026-10-13): a stale PID publishes `{value: null, ts, stale: true, band: null, last: {value, band}}`. The page renders **`last.value` dimmed**, coloured by `last.band`, with age = now − `ts` (clock arithmetic, not a threshold). `value: null` **without** `stale: true` means not read ⇒ `--` + reason (`noBandReason` / reason field).
- Covers the ARCH-061 case (Bluetooth up, ECU silent): the page shows **old numbers that admit their age**, never fresh-looking ones.

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| RPM, speed, coolant, intake air, battery | **NEW `states/obd-live`**: `params.<PID>.{value, unit, ts, band}` (Atlas G-3; Sprint 98 US-874) | **in Sprint 98** | Atlas · Ralph |
| Battery | `BATTERY_V` via adapter `ATRV` (not 0x42), in obd-live | exists | — |
| Gear | `states/gear` (`gear_state_emitter.py`) | exists | — |
| Gear hint | `hintGear`, `hintDirection` on `states/gear` | **names approved** (G-2); rule ruled (§4.2) | Ralph builds |
| Per-value band | provider band incl. dwell / reset floor / red bypass / voltage gate (US-875 / R26) | **in Sprint 98**; Spool spec sent 2026-10-13 | Spool · Atlas |
| RPM zone edges | `params.RPM.scale {amberFrom: 5500, redFrom: 7000}` | **in US-874/875** (review S-6) | — |
| Stale shape | `{value: null, ts, stale: true, band: null, last: {value, band}}` | **ruled** (Atlas, folded in US-874) | — |
| `--fs-giant` | `tokens.css` | **approved** (G-1) | Ralph |
| Staleness timeout | `pi.display.stale.obdLiveSec` = 5 | **named** | — |

## 6. Acceptance criteria (draft for grooming)

1. Given each fixture in §7, the page at 480×320 shows the gear / RPM / speed / band colours in §4, verified by screenshot.
2. No element clips (DOM `scrollHeight <= clientHeight`, all fixtures).
3. Computed font-size: gear = `--fs-giant` (100 px); speed = `--fs-hero` (44 px); RPM, coolant, intake air, battery ≥ 34 px. The gear's cap top is within 2 px of the COOLANT/RPM label cap tops (on-Pi screenshot, bigDoD).
4. RPM never renders a value absent from the state (no interpolation): with a state change from 2,000 to 4,000, no intermediate value is ever painted.
5. The gear glide fires only when the gear changes (two readings with the same gear ⇒ no animation).
6. A hinted gear renders hollow, with arrow; a measured gear renders solid. They are never visually identical.
7. Band colour comes only from the provider's band field. Grep gate: no threshold number in `carousel.js` for this page.
8. Stale fixture (`stale: true`, `last.value` set): every value shows **`last.value`**, dimmed, with age; never `--`. Not-read fixture (`value: null`, no `stale`): `--` + reason.
8a. RPM zones: fixtures at 5,499 / 5,500 / 6,999 / 7,000 light green / yellow / yellow / red segments; zone edges come from the provider (grep gate: no `5500` or `7000` in `carousel.js`).
8b. Gear hint fixtures render exactly the provider's `hintGear` + `hintDirection`; with the hint null, `--`.
8c. Live-coolant-red fixture: the takeover covers this page with `PULL OVER` + value + unit (Warnings AC 3). Battery-red and redline fixtures: red tile / red segments, **no takeover**. *(Takeover ACs land with the Warnings stories; out of Sprint 103.)*
9. No literal colour or px in this page's CSS.
10. **DoD (R15): the CIO, in the car, reads gear, RPM and speed at a glance with no touch.**

## 7. Fixtures

`idle-neutral` · `gear-1..5` · `between-gears-hint-up` · `between-gears-hint-down` · `between-gears-no-hint` · `rpm-yellow-5500` · `redline` · `coolant-amber` · `coolant-red-takeover` · `iat-hot-never-red` · `engine-off-voltage-unbanded` · `ecu-silent-stale` · `value-null-with-reason`.

## 8. Out of scope
Boost, AFR, oil pressure, fuel pressure (no sensor, hardware deferred) · a shift *light* beyond the red-zone flash · trip/heading (Navigation page) · fuel trims (Fuel page) · top bar and page dots (page-set design).

## 9. Open items
- ~~Spool: gear-hint logic~~ (ruled 2026-10-13, §4.2) · ~~RPM yellow start~~ (5,500). **Still Spool:** band producer (in Sprint 98).
- ~~Atlas: `--fs-giant`, hint names, OBD state file, stale key~~ (all ruled 2026-10-13). ~~Still Atlas: stale shape, RPM scale~~ (both ruled and folded into Sprint 98, 2026-10-13).
- **Marcus:** R9 is read as "the RPM **bar** is central" (CIO D-11), recorded so it is not raised later as a deviation.
- **Revisit after the first drive:** D-5 shift flash with ~2 s lag (Iris's standing recommendation: remove if it fires after the shift).
