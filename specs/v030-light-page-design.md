# V0.30 Light page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12, S105 folds 2026-10-19 (UIDEV-006) · **Status:** CIO-APPROVED design; **built in S105** (US-893-a/b) except the F-126 override and shortcut
**Mockup:** OEM skin `proposals/2026-10-14-v030-light-page-oem.html` → https://claude.ai/artifact/XVJUtniMmi7Rg9Smhf8x8B (**build from this**); the pre-OEM layout study is https://claude.ai/artifact/KsQ5iXCdsxZRahiJU7Bbsd (layout A + glyph)
**DoD lines served:** 7 (themed pages: Light; R10 amended, Motion and Light split), 8
**Related:** F-126 settings **brought into V0.30 by the CIO 2026-10-12** (holds the brightness override). Auto-dim re-validation for the window placement is owed (shared MEMORY: ARCH-005 tuned against the old position).
**Canonical home:** `specs/` in the repo via a bench.

> **2026-10-19 fold (UIDEV-006).** This revision folds the S105 rulings: Iris L1–L7 (`pm/inbox/2026-10-19-from-iris-S105-rulings-Motion-M1-M7-Light-L1-L7.md`) and Atlas A3/A7/L1–L6 (`…-from-atlas-RULED-S105-relaunch-gaps-…md`), as I acked them (X1–X3). Where L1–L7 and Atlas differ, Atlas's later ruling stands: per-channel `atLimit` (X2), the dot at the APPLIED level (X1), the helper `luxAxisX` (X3). The S105 build agrees with it. **Fonts:** `--font-body` is not a token; every non-Michroma text is `--font-mono` (DejaVu Sans Mono on the Pi, 0.60205 em). Widths are measured in that face: 12.04 px per character at `--fs-label`, 9.03 at `--fs-meta`.

---

## 1. Purpose
**What the light around the car is, and why the screen is as bright as it is.** Also the tool for re-tuning auto-dim now the sensor sits in the windshield.

## 2. Decisions locked (CIO, 2026-10-12)

| # | Decision | CIO choice |
|---|---|---|
| L-1 | Elements | Ambient lux · screen brightness % · DAY/DUSK/NIGHT · brightness override · **IR and every other sensor reading** |
| L-2 | Override | **A persistent setting in F-126** (F-126 now IN V0.30, living with the System pages) |
| L-3 | Hero | **DAY / DUSK / NIGHT** |
| L-4 | Word boundaries | **The auto-dim curve's ends** (today `luxMin` 3, `luxFull` 300) |
| L-5 | Raw readings | **IR · full spectrum · visible · gain + integration time** |
| L-6 | Curve graph | **Yes, small, with a live dot** |
| L-7 | Override display | **Status line + parked-only shortcut** to the F-126 brightness row |
| L-8 | Layout | **A · Word and curve** |
| L-9 | Glyph | **Sun / dusk / moon glyph beside the word** |

## 3. Layout (480 × 320; body 258; ≈ 230 used)

```
┌──────────────────────────────────────────────┐
│ ☀ DAY                  ┊         ╭──────────── │
│                        ┊      ╭──╯     ●       │ ~110  curve 200×104, log lux
│ AMBIENT                ┊ ─────╯        ┊       │
│ 1,400 lux              3            300 lux    │
├──────────────────────────────────────────────┤
│ IR       FULL        VISIBLE      RANGE        │ ~50
│ 4,300    12,400      8,100        low          │
│                                   100 ms       │
├──────────────────────────────────────────────┤
│ BRIGHTNESS AUTO 100 %               SETTINGS › │ ~34   (shortcut parked only, with F-126)
└──────────────────────────────────────────────┘
```

| Element | Tier | Note |
|---|---|---|
| Glyph | 34 × 34 SVG, `--text-primary` stroke via a class | sun / dusk / moon by the word. The three SVGs are copied unchanged from the OEM mockup (viewBox `0 0 34 34`, `fill: none`, `stroke-width` 2.5, round caps). Never coloured |
| Word | `--fs-hero`, `--font-display`, **neutral colour always** | |
| Ambient | `--fs-primary` | below 10 lux one decimal (`0.6`); 10 and above `Math.round` with the fixed `,` separator. The format is chosen from the raw value, so 9.96 shows `10.0`. Worst `30,000 lux` = 171.0 px of the 248 px tile |
| Curve | **200** × 104 SVG (`NIGHT` in Michroma at 44 px is 197 px, so word + glyph + gap need ~241 px; measured 2026-10-14) | log-lux x axis, brightness y. **One scale for line, dot and labels.** Labels per §4.2 |
| Raw cells | `--fs-label` values, `--fs-meta` labels | parked-read; 108 px each. `at limit` 96.3 px, `65,535` 72.2 px |
| Status | `--fs-label` | per §4.3; amber only for the F-126 override |
| Shortcut | ≥ 32 px tall hit target, outlined | **parked only** (R5); ships with F-126 |

## 4. Behaviour

### 4.1 Word, glyph and ambient
- **Word:** `NIGHT` below the curve's low end, `DAY` at/above its top end, `DUSK` between. **Derived by the provider** (`states/light.lightBand`, `night` / `dusk` / `day` / null; US-893-a) from the same resolved autoDim as the brightness level and the curve, so dimming and the word can't disagree after a re-tune. The provider tests day first (`lux >= luxFull`), then night (`lux < luxMin`), else dusk (Atlas A5).
- **`lightBand` null ⇒ word `--`, no glyph**, even if a lux value somehow exists. The page never derives a band.
- **One predicate decides whether a lux is a reading** (Atlas A3): finite and ≥ 0. A failed read (−1, non-finite) publishes `lux` null, the same as saturation. Never a wrong number.
- **Reasons**, checked in this order, `--font-mono` `--fs-meta` `--text-secondary` under AMBIENT's `--` (the AMBIENT tile is 248 px). The text table is `LIGHT_REASON_TEXT`, mapping the provider's `reasons.lux` code:

| Condition | Word | AMBIENT | Reason |
|---|---|---|---|
| no `states/light` payload (file absent or fetch fails) | `--` (no glyph) | `--` | `no light data` (117.4 px) |
| `ts` null or unparseable | as published, dimmed | as published, dimmed | `no timestamp` (108.4 px), in place of the age |
| `reasons.lux` = `at_limit` (`channelAtLimit` true, `lux` null) | `--` (no glyph) | `--` | `sensor at limit` (135.5 px) |
| `reasons.lux` = `no_reading`, or an unknown code | `--` (no glyph) | `--` | `no reading` (90.3 px) |

- Retired: `from a limited channel` (the provider never publishes a lux from a limited channel) and `sensor not found` (the page can only see that the file is missing, not that the sensor is).

### 4.2 Curve
- Drawn from **provider curve data, never page maths:** `states/light.curve {points: [[lux, level], ...], luxMin, luxFull, minLevel}`. Points come from the bridge's own `brightnessLevel()` on a log grid (`0.3 × 10^(i/10)`, i = 0..50) plus the exact breakpoints `luxMin`, the knee and `luxFull`, sorted, with a grid point within relative 1e-9 of a breakpoint dropped so the exact config values are published (Atlas A4: 51 points with the shipped config).
- **`luxAxisX(lux, luxLo, luxHi, widthPx)` is the ONE function in `carousel.js` that may call `Math.log10`**, and only to place a lux on the x axis. `luxLo` / `luxHi` are the published curve's first and last lux. A lux at or below `luxLo` pins to the left edge (night reads ~0.35 lux, and 0 is a reading), at or above `luxHi` to the right edge; a non-numeric lux has no x. No level or band is ever computed from lux on the page.
- **y domain:** `[max(0, curve.minLevel − 0.25), 1.0]`. The 0.25 is presentation headroom (the named constant `CURVE_Y_HEADROOM`) so the flat floor doesn't sit on the x axis; with today's 0.75 that gives 0.5–1.0. Reading the `curve.minLevel` field is allowed; a `0.75` literal is not. `minLevel` null ⇒ 0–1.
- **Labels**, all `--font-mono` `--fs-meta` `--text-tertiary` (never a px literal):
  - y: `100%` at y(1.0) and `${Math.round(minLevel × 100)}%` at y(minLevel). No space: these are axis furniture. The status line keeps `100 %`, which is a reading. `100%` is 36.1 px, so the left pad is about 40 px.
  - x: `curve.luxMin` as a bare number (`3`); `curve.luxFull` + ` lux` (`300 lux`, or `1,000 lux` once re-tuned). **The unit is `lux`, never `lx`**: one unit word per page.
  - Dashed verticals at `curve.luxMin` / `curve.luxFull`.
- **The dot** (Atlas L3, X1): x = `luxAxisX(lux)`, drawn only when lux is numeric; **y = `appliedBrightness().level`**, the level the kiosk applied, not the published `brightnessLevel`. Those differ exactly under a stale fallback. So:
  - fresh auto: on the line;
  - fallback (stale): the injected `defaultLevel`, off the line, dimmed with the age;
  - STOP alert: 1.0.
  - The page never snaps the dot onto the polyline and never recomputes the level.
- ⚠️ **Fact the CIO should know before the in-car check:** as shipped (`luxMin` 3, `luxFull` 300, `minLevel` 0.75) the line is FLAT at 75 % up to the knee at ≈ 94.9 lux, so **NIGHT and DUSK both dim to 75 %**. The graph shows that honestly; whether it is the wanted behaviour is an auto-dim tuning question, not a page defect.
- **Override** (once F-126 is built): a dashed amber horizontal line at the forced level, and the dot moves onto it.

### 4.3 Status
- **One applier** (Atlas A7): `appliedBrightness(lightData, injectedAutoDim, nowMs, alarmActive) -> {level, basis}`. In order: alarm ⇒ `{1.0, alert}`; FRESH (an object, not `sourceUnavailable`, `ts` parseable with age ≤ `luxStaleSec`, `brightnessLevel` finite in [0, 1]) ⇒ `{brightnessLevel, brightnessMode}`; otherwise ⇒ `{injected defaultLevel, fallback}`. An out-of-range level is fallback, never clamped. The panel, the status line and the dot all read this one return.
- **The text comes from `basis`, never from `data.brightnessMode`**, so a stale file that says `auto` can never show AUTO. Measured in the mono face at `--fs-label`, all within the 456 px row:
  - `auto`: `BRIGHTNESS AUTO nn %`.
  - `default` or `fallback`: `BRIGHTNESS nn % (default, no reading)` (worst 405.6 px). **Never `AUTO`.**
  - `alert`: `BRIGHTNESS 100 % (alert)`. Without it, the page could read `AUTO 80 %` while the panel sits at 100 %.
  - F-126 override (once built): `BRIGHTNESS FIXED nn % (override)` in `--amber-warn`.
- Percent is `Math.round(level × 100)`.
- **Shortcut:** parked only; opens the F-126 overlay **at the brightness row**. ⏸ **Ships with F-126, not before** (Atlas 2026-10-14 s3): until then the status row is full width, with no override line and no shortcut. The CIO decisions L-2/L-7 stand; only the build order changes.

### 4.4 Raw row
- **IR, FULL, VISIBLE:** counts with the fixed `,` thousands separator (`fmtThousands`, shared with Motion's stop count), never `toLocaleString()`: the kiosk's locale is not ours to assume.
- **At the ADC limit** (Atlas L2, X2), from `atLimit {ir, full}`: IR / FULL read `at limit` in `--amber-warn` when their own flag is true; **VISIBLE reads `at limit` when either is true**, because it is derived from a clipped count. A null flag (ceiling unknown) shows the count and claims nothing. The page never compares against a ceiling; it holds none.
- **VISIBLE** reads the provider's `visibleCount` and **never subtracts**. The provider already turns a negative visible count into null; null shows `--` in `--text-tertiary`. **Never a floored 0**, which would assert total darkness when the reading failed.
- **RANGE:** line 1 the gain word **exactly as published** (`low`, `med`, `high` or `max`), `--fs-label`, **no multiplier** (a multiplier would need a page gain table, a second SSOT; `max` has none in the datasheet). Line 2 `100 ms` from `integrationMs`, `--fs-meta` `--text-secondary`. A null `gain` or `integrationMs` shows `--` in that line.

### 4.5 Stale and absent
- **Stale age:** `14 s`, `Math.floor`, `--font-mono` `--fs-meta` `--amber-warn`, under AMBIENT. The same rule as Motion and NAV; never `fmtAgeSec`'s `12s`.
- Stale dims the word tile, the curve and the raw row. **The status row does not dim**: it reports what the kiosk applied, not the sensor.
- Absent: §4.1's reasons.

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| lux, ts | `states/light` | exists; `lux` null when not a reading (A3) | — |
| IR count, full count, visible | `states/light.irCount` / `fullCount` / `visibleCount` (null when negative) | exist | — |
| gain, integration ms | `states/light.gain` (`low` / `med` / `high` / `max`) / `integrationMs` | exist | — |
| channel at limit | `states/light.channelAtLimit` (bool or null, the OR of the two) **+ `atLimit {ir, full}`** (bool or null each) | **built** (US-893-a) | — |
| lux reason | `states/light.reasons.lux` = `at_limit` / `no_reading`, present only when `lux` is null | **built** (US-893-a) | — |
| word | `states/light.lightBand` | **built** (US-893-a) | — |
| brightness level + mode | `states/light.brightnessLevel` + `brightnessMode` (`auto` / `default`; `fixed` with F-126). The bridge is the ONE level source; `appliedBrightness` is the one applier | **built** (US-893-a) | — |
| Curve data | `states/light.curve {points, luxMin, luxFull, minLevel}` | **built** (US-893-a) | — |
| Override setting | **F-126** settings (new key) | **new** (F-126 now IN) | **Atlas: key + write path; Iris: F-126 band design** |
| Deep link to the brightness row | F-126 overlay | **new** | Atlas / Ralph |

## 6. Acceptance criteria
1. Fixtures render per §4 at 480×320 (screenshot).
2. No clipping; word = `--fs-hero`; ambient ≥ 34 px.
3. Word boundaries come from config: a fixture with changed `luxMin`/`luxFull` moves the boundary with **no page code change**.
4. Word and glyph never take a severity colour.
5. Override fixture: amber status + dashed line + dot on the line; auto fixture: neither. *(With F-126.)*
6. Shortcut absent while moving, present when parked, and opens F-126 at the brightness row. *(With F-126.)*
7. A channel at the limit shows `at limit` on its own cell and on VISIBLE, never the clipped count.
8. Curve line, dot and labels share one scale. **Grep gate (corrected 2026-10-19; my earlier "no `Math.log` on lux" was impossible on a log axis):** `Math.log` / `Math.log10` appear in `carousel.js` **only inside `luxAxisX`**; no `luxMin` / `luxFull` / `minLevel` numeric literal; no level or band computed from lux. The dot is at (`luxAxisX(lux)`, `appliedBrightness().level`); it is on the line for a fresh auto fixture and off it for `dot-off-curve`.
9. No literal colour or px in this page's CSS (the mockup's old 11 px and 12 px axis text is not copied).
10. **DoD (R15): CIO judgement in the car, day and night.**
11. Status text: a no-reading or stale fixture ⇒ `BRIGHTNESS nn % (default, no reading)`, never `AUTO`; STOP-forced ⇒ `BRIGHTNESS 100 % (alert)`. No status variant clips.
12. VISIBLE null ⇒ `--`, never `0`.

## 7. Fixtures
As built in S105 (`tests/ui/fixtures/states/light/`): `night-0.6lux` · `dusk-22lux` · `day-1400lux` · `sun-at-limit` · `light-stale` · `light-null` (mode `default`) · `stop-override` (was `stop-alert-forced` here) · `dot-off-curve` · `config-retuned-boundaries`. **`dot-off-curve`** = a file built by `buildLightState` (lux 22, level 0.75, ts T) read at `nowMs = T + luxStaleSec + 1` with an injected `defaultLevel` 1.0 ⇒ dot y 1.0, dimmed, with the age: the provider writes the file, the clock makes it stale. Waiting for F-126: `override-60` · `parked-shortcut`.

## 8. Out of scope
Editing the curve on this page (F-126 holds settings) · colour temperature / night-mode palette (not requested) · auto-dim re-tuning itself (a separate measurement task this page enables).

## 9. Open items
- F-126 override key + write path + deep link: with F-126.
- **Iris (next):** the F-126 settings band design inside the System pages, which now holds the override.
