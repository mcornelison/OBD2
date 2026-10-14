# V0.30 Engine page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 · **Status:** CIO-APPROVED design, awaiting V0.30 DoD + grooming
**Mockup:** `proposals/2026-10-13-v030-engine-page.html` → https://claude.ai/artifact/RiqWXfdDVJiLS5TGrodKgA (**layout B, vertical bars, is the locked one**)
**DoD lines served:** 7 (themed pages: Engine), 8 · **Retires** F-129's Engine-card concept (its MAF centrepiece moved to the Fuel page)
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose (CIO: "Both")
**The ECU's view:** how hard the engine is working right now (above the fold), plus this drive's temperature and voltage history and engine status (scroll, parked).

## 2. Decisions locked (CIO, 2026-10-13)

| # | Decision | CIO choice |
|---|---|---|
| E-1 | Keep R10's Engine page | **Yes, as "the ECU's view"** |
| E-2 | Page order | **Driving · Nav · Engine · Fuel · O2 · Motion · Light · System · Warnings** |
| E-3 | Purpose | Both: live + parked health |
| E-4 | Elements | Load + throttle · timing advance · temp + voltage history · run time + lamp + O2 |
| E-5 | Fit | **Live above the fold; scroll for the rest** (Warnings scroll rule) |
| E-6 | History window | **This drive** |
| E-7 | O2 | **Its own page** (see O2 spec) |
| E-8 | Layout | **B · Vertical bars** |

## 3. Layout (480 × 320; body 258 visible; content scrolls)

```
┌──────────────────────────────────────────────┐
│ ┃█┃   ┃ ┃    LOAD                             │  above the fold
│ ┃█┃   ┃█┃    71 %             (--fs-hero)     │
│ ┃█┃   ┃█┃    THROTTLE  48 %   (--fs-primary)  │  ~180
│ LOAD  THR    TIMING 22° BTDC                  │
│              base timing · not knock          │
│        ↓ history and status below             │
├──────────────────────────────────────────────┤  ── scroll ──
│ COOLANT · THIS DRIVE   ╱‾‾‾╲╱‾‾   214°F       │
│ INTAKE AIR · THIS DRIVE  ~~~~~~   88°F        │
│ BATTERY · THIS DRIVE   ‾‾‾‾‾‾‾‾   14.1V       │
│ RUN TIME 0:23 · CHECK ENGINE ON · 2 codes ›   │
│ O2 SENSORS › (O2 page)                        │
└──────────────────────────────────────────────┘
```

- Two vertical bars (26 × 120 px) for load and throttle, 0–100 %; numbers beside: load `--fs-hero`, throttle and timing `--fs-primary`.
- `↓ history and status below` cue + visible scrollbar (no silent clip). **Nothing needed while driving is below the fold** (R5).

## 4. Behaviour
- **Each value steps at its own polling cadence** (load, timing every cycle; throttle ~every 3rd; IAT, run time ~every 10th). No interpolation.
- **Load is never coloured on its own:** 100 % at full throttle is expected on this turbo engine (spec *Engine Load* row; danger only as a compound condition, which belongs to the provider).
- **Timing** always carries `base timing · not knock` (TIMING_ADVANCE ≠ knock; no knock source without ECMLink).
- **History graphs:** neutral lines, this drive (key-on → now), end value labelled. **An amber band is drawn only where the provider's dwell rule actually fired**, never where the line merely crossed a number (dwell-as-render-rule, Spool 08-21).
- **Units:** °F, mph (CIO). Bands judged in °C by the provider.
- **Check-engine lamp** (`MIL_ON`) + code count (`DTC_COUNT`) link to Warnings (parked tap); codes are not repeated here.
- **O2 SENSORS ›** opens the O2 page.
- Stale / null: dim + age / `--` + reason (shared rule).

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| ENGINE_LOAD, TIMING_ADVANCE, COOLANT_TEMP | tier 1 | exist | — |
| THROTTLE_POS, MIL_ON, DTC_COUNT | tier 2 | exist | — |
| INTAKE_TEMP, RUNTIME_SEC, BATTERY_V | tier 3 | exist | — |
| **This-drive history series** (coolant, IAT, battery) surviving a kiosk restart | **provider** | **new** | **Atlas** |
| Dwell-fired spans for the amber band | band provider (Spool's unfiled story) | **new** | Spool + Atlas |

## 6. Acceptance criteria (draft)
1. Fixtures render per §4 at 480×320; load/throttle/timing fully visible without scrolling.
2. Load at 100 % renders neutral (no severity colour).
3. Timing label `not knock` present in every fixture.
4. A coolant line crossing a band number **without** a dwell-fired span shows no amber band.
5. Scroll section reachable; scrollbar + cue visible; no clipped element.
6. No literal colour or px in this page's CSS.
7. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`idle-warm` · `wot-pull-load-100` · `cold-start-history` · `fan-cycle-history` · `coolant-dwell-fired` · `mil-on-two-codes` · `history-empty-after-restart` · `stale`.

## 8. Out of scope
Boost (no source) · knock (no source) · AFR (no wideband) · MAF (Fuel page) · O2 (O2 page).
