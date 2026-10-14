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
│                        ┊      ╭──╯     ●       │ ~110  curve 210×104, log lux
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
| Curve | 210 × 104 SVG | log-lux x axis (0.3 … 30 000), brightness y; dashed verticals at the two curve ends; live dot. **One scale for line, dot and labels** |
| Raw cells | `--fs-label` values, `--fs-meta` labels | parked-read |
| Status | `--fs-label` | amber when overridden |
| Shortcut | ≥ 32 px tall hit target, outlined | **parked only** (R5) |

## 4. Behaviour
- **Word:** `NIGHT` below the curve's low end, `DAY` above its top end, `DUSK` between. **Derived by the provider** from the config values (one set of numbers, so dimming and the word cannot disagree after a re-tune).
- **Curve:** drawn from the live config (`curve` type, `luxMin`, `luxFull`, `minLevel`). The dot sits at (current lux, current brightness level). **Override ⇒** a dashed amber horizontal line at the forced level, and the dot moves onto it.
- **Status:** `BRIGHTNESS AUTO nn %` / `BRIGHTNESS FIXED nn % (override)` in `--amber-warn`. A forced brightness is never invisible.
- **Shortcut:** parked only; opens the F-126 overlay **at the brightness row**.
- **Channel at the ADC limit** ⇒ that cell reads `at limit` (amber), never a number. Lux derived from a limited channel ⇒ the provider's typed reason, shown on the glass.
- **Visible** = full − IR, floored at 0.
- **Stale / null:** dim + age / `--` + reason (shared rule).

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| lux, ts | `states/light` | exists | — |
| **IR count, full count** | sensor reader already reads them (`sensor_reader.py`) | **not published** | **Atlas: add to `states/light`** |
| **gain, integration ms** | reader's range context (ARCH-009, `sensor_reader.py:151`) | **not published** | **Atlas** |
| **channel-at-limit flag** | reader | **not published** | **Atlas** |
| **word** (DAY/DUSK/NIGHT) | provider, from `pi.display.autoDim` ends | **new** | **Atlas** |
| **brightness level + mode (auto/fixed)** | whatever applies auto-dim | **not published** | **Atlas** |
| Curve parameters | `config.json pi.display.autoDim` | exist | — |
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
8. Curve line, dot and labels share one scale (dot sits on the line in auto mode).
9. No literal colour or px in this page's CSS.
10. **DoD (R15): CIO judgement in the car, day and night.**

## 7. Fixtures
`night-0.6lux` · `dusk-22lux` · `day-1400lux` · `sun-at-limit` · `override-60` · `parked-shortcut` · `light-stale` · `light-null`.

## 8. Out of scope
Editing the curve on this page (F-126 holds settings) · colour temperature / night-mode palette (not requested) · auto-dim re-tuning itself (a separate measurement task this page enables).

## 9. Open items
- **Atlas:** the `states/light` fields in §5; the F-126 override key + write path; the deep link.
- **Iris (next):** the F-126 settings band design inside the System pages, which now holds the override.
