# V0.30 Light page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12 · **Status:** CIO-APPROVED design (brainstorm 2026-10-12), awaiting V0.30 DoD + grooming
**Mockup:** `proposals/2026-10-12-v030-light-page.html` → https://claude.ai/artifact/KsQ5iXCdsxZRahiJU7Bbsd (**layout A + glyph is the locked one**)
**DoD lines served:** 7 (themed pages: Light; R10 amended, Motion and Light split), 8
**Related:** F-126 settings **brought into V0.30 by the CIO 2026-10-12** (holds the brightness override). Auto-dim re-validation for the window placement is owed (shared MEMORY: ARCH-005 tuned against the old position).
**Canonical home:** `specs/` in the repo via a bench.

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
| L-5 | Raw readings | **IR · full spectrum · visible (full − IR) · gain + integration time** |
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
│ 1,400 lux              3            300 lx     │
├──────────────────────────────────────────────┤
│ IR       FULL        VISIBLE      RANGE        │ ~50
│ 4300     12400       8100         low 1× 100ms │
├──────────────────────────────────────────────┤
│ BRIGHTNESS AUTO 100 %               SETTINGS › │ ~34   (shortcut parked only)
└──────────────────────────────────────────────┘
```

| Element | Tier | Note |
|---|---|---|
| Glyph | 34 × 34 SVG, `--text-primary` stroke | sun / dusk / moon by the word |
| Word | `--fs-hero`, `--font-display`, **neutral colour always** | |
| Ambient | `--fs-primary` | <10 lux one decimal; ≥10 integer with thousands separator |
| Curve | **200** × 104 SVG (was 210: `NIGHT` in Michroma at 44 px is 197 px, so word + glyph + gap need ~241 px; measured 2026-10-14) | log-lux x axis (0.3 … 30 000), brightness y with labels at `minLevel` and 100 %; dashed verticals at the two curve ends; live dot. **One scale for line, dot and labels** |
| Raw cells | `--fs-label` values, `--fs-meta` labels | parked-read |
| Status | `--fs-label` | amber when overridden |
| Shortcut | ≥ 32 px tall hit target, outlined | **parked only** (R5) |

## 4. Behaviour
- **Word:** `NIGHT` below the curve's low end, `DAY` at/above its top end, `DUSK` between. **Derived by the provider** (`states/light.lightBand`, `night`/`dusk`/`day`/null, Atlas ruling 3, 2026-10-14; US-893-a) from the same autoDim read as the brightness level, so dimming and the word cannot disagree after a re-tune. `lightBand` null ⇒ `--` + reason.
- **Curve:** drawn from **provider curve data, never page maths** (Atlas ruling 3(b) deletes the page's curve copy). **RULED (Atlas 2026-10-15, S105 rulings Q5; build US-893-a/b):** `states/light.curve {points: [[lux, level], ...], luxMin, luxFull, minLevel}`. Points are computed BY the bridge's own `brightnessLevel()`: 10 log-spaced per decade over 0.3–30 000 lux, UNION the exact breakpoints `luxMin`, the clamp knee and `luxFull`, sorted, de-duplicated. The log curve is piecewise-linear on a log-lux axis, so with the breakpoints it is drawn EXACTLY; a `linear` type is approximated at 10/decade. The page draws a polyline through the points (no `Math.log` on lux, no curve maths); dashed verticals and their `3` / `300 lx` labels come from `curve.luxMin` / `curve.luxFull`. ⚠️ **Fact the CIO should know before the in-car check:** as shipped (`luxMin` 3, `luxFull` 300, `minLevel` 0.75) the line is FLAT at 75 % up to the knee at ≈ 94.9 lux, so **NIGHT and DUSK both dim to 75 %**. The graph shows that honestly; whether it is the wanted behaviour is an auto-dim tuning question, not a page defect. The dot sits at (current lux, `brightnessLevel`), so it lies on the line by construction. lux null ⇒ no dot. **Override ⇒** (once F-126 is built) a dashed amber horizontal line at the forced level, and the dot moves onto it.
- **Status:** shows the level the kiosk **APPLIED**, never only the provider's `brightnessLevel`. A forced brightness is never invisible. Measured in `--font-body` 20 px, all within the 448 px row:
  - auto: `BRIGHTNESS AUTO nn %`.
  - no reading (`brightnessMode` `default`): `BRIGHTNESS nn % (default, no reading)` (412.1 px). **Never `AUTO`:** with no reading the level is not auto. (`BRIGHTNESS AUTO 100 % (default, no reading)` is 474.7 px and false.)
  - STOP alarm forcing full brightness (page-side override, US-893-a): `BRIGHTNESS 100 % (alert)` (267.4 px). Without it, the page could read `AUTO 80 %` while the panel sits at 100 %.
  - F-126 override (once built): `BRIGHTNESS FIXED nn % (override)` in `--amber-warn`.
- **Shortcut:** parked only; opens the F-126 overlay **at the brightness row**. ⏸ **Ships with F-126, not before** (Atlas 2026-10-14 s3): until then the status row is full width, with no override line and no shortcut. The CIO decisions L-2/L-7 stand; only the build order changes.
- **Channel at the ADC limit** ⇒ that cell reads `at limit` (amber), never a number. Lux derived from a limited channel ⇒ the provider's typed reason, shown on the glass.
- **Visible** = full − IR, floored at 0.
- **Stale / null:** dim + age / `--` + reason (shared rule).

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| lux, ts | `states/light` | exists | — |
| **IR count, full count, visible** | `states/light.irCount` / `fullCount` / `visibleCount` | **exist** (PM MEASURED dev 972cb038, 2026-10-15) | — |
| **gain, integration ms** | `states/light.gain` / `integrationMs` | **exist** | — |
| **channel-at-limit flag** | `states/light.channelAtLimit` | **exists** | — |
| **word** (DAY/DUSK/NIGHT) | `states/light.lightBand` | **ruled** (Atlas 3, 2026-10-14); build US-893-a | Ralph (S105) |
| **brightness level + mode** | `states/light.brightnessLevel` + `brightnessMode` (`auto` / `default`; `fixed` with F-126). The bridge is the ONE applier; the kiosk applies it | level exists; `default` mode **ruled** (US-893-a) | Ralph (S105) |
| Curve data for the graph | `states/light.curve {points, luxMin, luxFull, minLevel}` (§4) | **ruled** (Atlas 2026-10-15, S105 rulings Q5); build US-893-a | Ralph (S105) |
| Override setting | **F-126** settings (new key) | **new** (F-126 now IN) | **Atlas: key + write path; Iris: F-126 band design** |
| Deep link to the brightness row | F-126 overlay | **new** | Atlas / Ralph |

## 6. Acceptance criteria (draft)
1. Fixtures render per §4 at 480×320 (screenshot).
2. No clipping; word = `--fs-hero`; ambient ≥ 34 px.
3. Word boundaries come from config: a fixture with changed `luxMin`/`luxFull` moves the boundary with **no page code change**.
4. Word and glyph never take a severity colour.
5. Override fixture: amber status + dashed line + dot on the line; auto fixture: neither.
6. Shortcut absent while moving, present when parked, and opens F-126 at the brightness row.
7. Channel-at-limit fixture shows `at limit`, never the clipped count.
8. Curve line, dot and labels share one scale (dot sits on the line in auto mode). The page draws only provider points (dot within 1 px of the polyline in every fixture): grep gate, no `Math.log` on lux, no `luxMin`/`luxFull`/`minLevel` literal or curve maths in `carousel.js`.
9. No literal colour or px in this page's CSS.
10. **DoD (R15): CIO judgement in the car, day and night.**
11. Status text: no-reading fixture ⇒ `BRIGHTNESS 100 % (default, no reading)`, never `AUTO`; STOP-forced fixture ⇒ `BRIGHTNESS 100 % (alert)`. No status variant clips.

## 7. Fixtures
`night-0.6lux` · `dusk-22lux` · `day-1400lux` · `sun-at-limit` · `override-60` · `parked-shortcut` · `light-stale` · `light-null` (mode `default`) · `stop-alert-forced` · `config-retuned-boundaries`. (`override-60` and `parked-shortcut` wait for F-126.)

## 8. Out of scope
Editing the curve on this page (F-126 holds settings) · colour temperature / night-mode palette (not requested) · auto-dim re-tuning itself (a separate measurement task this page enables).

## 9. Open items
- ~~Atlas: the `states/light` fields in §5~~ **raw fields exist; lightBand + mode ruled 2026-10-14.** ~~Atlas S105 Q5, the curve data shape~~ **RULED 2026-10-15 (§4).** F-126 override key + write path + deep link: with F-126.
- **Iris (next):** the F-126 settings band design inside the System pages, which now holds the override.
