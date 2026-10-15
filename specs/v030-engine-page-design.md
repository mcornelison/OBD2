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
│ RUN TIME     CHECK ENGINE                     │
│ 0:23         ON                               │
│              12 codes ›                       │
└──────────────────────────────────────────────┘
```

- Two vertical bars (26 × 120 px) for load and throttle, 0–100 %; numbers beside: load `--fs-hero`, throttle and timing `--fs-primary`.
- `↓ history and status below` cue + visible scrollbar (no silent clip). **Nothing needed while driving is below the fold** (R5).
- **Status row fit (measured 2026-10-15; O2 tile dropped 2026-10-15, S104 review G-3).** Labels are Michroma 15 px, measured from the advances JSON: `RUN TIME` 104.0, `CHECK ENGINE` 160.0 px.
  - **Two columns:** `max-content` for RUN TIME, `1fr` for CHECK ENGINE, 8 px gap = 104.0 + 160.0 + 8 = **272 px** of the 448 px inner width.
  - **No O2 tile until the O2 page exists (US-891).** A `-- not built yet` tile describes our backlog, not the car. When US-891 lands, the tile returns as a third `max-content` column (`O2 SENSORS` 142.4 px; three columns need 422.4 px, which fits).
  - CHECK ENGINE value is **two lines**: `ON` (lamp state), then `n codes ›`. A 2-digit count on one line, `ON · 12 codes ›`, is 15 mono characters ≈ 181 px (DejaVu Sans Mono 0.602 em at 20 px) and overflows. Two lines make the widest value `12 codes ›` ≈ 120 px. A 3-digit count still fits (≈ 132 px).
  - `OFF` when the lamp is off; no count line. Lamp on with count 0 (a pending code): `ON` / `0 codes ›`, which is true and still links to Warnings.

## 4. Behaviour
- **Each value steps at its own polling cadence** (load, timing every cycle; throttle ~every 3rd; IAT, run time ~every 10th). No interpolation.
- **Load is never coloured on its own:** 100 % at full throttle is expected on this turbo engine (spec *Engine Load* row; danger only as a compound condition, which belongs to the provider).
- **Timing** always carries `base timing · not knock` (TIMING_ADVANCE ≠ knock; no knock source without ECMLink).
- **Timing sign (S104 review G-2):** value ≥ 0 ⇒ `n° BTDC`; value < 0 ⇒ `|n|° ATDC`. A negative advance is AFTER top dead centre, so `−4° BTDC` would state the opposite of the truth. ⚠️ **Spool to confirm** the PID's sign convention on this ECU; until he does, this rule assumes the SAE J1979 convention (positive = before TDC).
- **History graphs** come from `states/engine-history` (Atlas S104 ruling 1, 2026-10-14; CIO pick (a) via Marcus 2026-10-15). Neutral lines, this drive, end value labelled.
  - **One point per bucket:** `{ts, value, band}`, buckets on the epoch grid `floor(ts / intervalSec)` (`pi.display.engineHistory.intervalSec`, 30 s).
  - **`value` = the LAST fresh sample in the bucket.** The line steps from point to point; the page never averages or smooths it.
  - **`band` = the WORST band held in the bucket** (red > amber > green > null). The page colours a bucket's span from that field only. **An amber or red span is drawn only where the provider says the band producer's dwell rule fired.** A line that merely crosses a number shows nothing (dwell-as-render-rule, Spool 08-21). The history copies the band producer's verdict, never re-judges it.
  - **A bucket with no fresh sample is omitted by the provider. The page breaks the line there: a gap is a gap, never a flat line or a bridge.**
  - **INTAKE_TEMP has no band** (`no_band_defined`), so its line is always neutral with no spans.
  - **Window = this drive.** The provider resets on drive start (driveId change). Above `pi.display.engineHistory.maxPoints` (240 = 2 h) the oldest bucket drops and `sinceTs` moves with it.
  - **The window label comes from the PROVIDER, never from the page's idea of key-on** (S104 review B-2). The provider publishes `states/engine-history.partial: bool` (Atlas S104 G3; the SAME name and polarity as NAV's `drive.distancePartial`, so every page reads one convention): `false` ⇒ `THIS DRIVE`; `true` (the history doesn't cover the drive from its start, e.g. orchestrator restarted mid-drive) ⇒ `SINCE h:mm` from `sinceTs`. `SINCE` is Michroma and the time is `--font-mono`: the Michroma subset has no `:` (same split as NAV §4.4). **The page never compares `sinceTs` with another provider's timestamp:** `sinceTs` is a bucket start on the 30 s grid and can sit before the drive start. A kiosk restart keeps the history (orchestrator memory + state file).
  - **Empty history** (no points yet, or just after an orchestrator restart) is a typed absence: `History not recorded yet. It starts with this drive's first readings.` Never an empty chart.
- **Units:** °F, mph (CIO). Bands judged in °C by the provider. History points carry the reading's own unit (`unit` map: C, V); the page converts by `unit` through the S103 G1 helper, display-only.
- **Check-engine lamp** (`MIL_ON`) + code count (`DTC_COUNT`) link to Warnings (parked tap); codes are not repeated here.
- **No O2 link on this page until US-891** (see §3 status row).
- Stale / null: dim + age / `--` + reason (shared rule).

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| ENGINE_LOAD, TIMING_ADVANCE, COOLANT_TEMP | tier 1 | exist | — |
| THROTTLE_POS, MIL_ON, DTC_COUNT | tier 2 | exist | — |
| INTAKE_TEMP, RUNTIME_SEC, BATTERY_V | tier 3 | exist | — |
| **This-drive history series** (coolant, IAT, battery) surviving a kiosk restart | **`states/engine-history`** `{ts, driveId, sinceTs, intervalSec, series{COOLANT_TEMP, INTAKE_TEMP, BATTERY_V: [{ts, value, band}]}, unit{pid: unit}}`. Producer: the obd-live emitter side of the orchestrator | **designed** (Atlas S104 ruling 1); **not on dev** | Ralph (S104) |
| Dwell-fired spans for the band colour | the per-bucket `band` above: a copy of the band producer's verdict (worst in bucket). No separate span provider | **designed** (same story) | — |
| History config | `pi.display.engineHistory.intervalSec` 30, `.maxPoints` 240; validator finite, > 0 | **not on dev** | Ralph |

## 6. Acceptance criteria (draft; folded from the S104 brief + Atlas ruling 1, 2026-10-14)
1. Fixtures render per §4 at 480×320; load/throttle/timing fully visible without scrolling.
2. Load at 100 % renders neutral (no state colour); the load and throttle bars use `--accent` (unbanded rule).
3. Timing label `base timing · not knock` present in every fixture.
4. Each value steps at its own sample; no interpolation, on the live values and on the history lines.
5. MIL + count link to Warnings, parked tap only; codes are not repeated here.
6. History colour comes **only** from each point's `band`. A coolant line crossing 104 °C with no amber/red `band` in its points shows no colour. A bucket whose `band` is amber shows an amber span even when its plotted `value` (the last sample) is below the number. Grep gate: no coolant/battery threshold in `carousel.js`.
7. An omitted bucket breaks the line; no segment is drawn across a gap.
8. Empty history is the typed absence text, not an empty or flat chart. `partial` true labels the window `SINCE h:mm` from `sinceTs`; false labels it `THIS DRIVE`. No page-side timestamp comparison.
9. IAT history is neutral in every fixture.
10. Scroll cue + scrollbar visible; no clipped element (DOM: every tile `scrollWidth <= clientWidth` and `scrollHeight <= clientHeight`), including the status row at a 2-digit and a 3-digit code count. No O2 tile in the DOM until US-891.
11. °F display-only, converted by the point's `unit` (bands judged in °C by the provider).
12. New CSS tokens-only; geometry as scoped custom properties on `#engine-card` (S103 G-4 rule).
13. **DoD (R15): CIO judgement in the car.**
14. Timing: a negative-advance fixture renders `|n|° ATDC`, never `−n° BTDC`.

## 7. Fixtures
`idle-warm` · `wot-pull-load-100` · `cold-start-history` · `fan-cycle-history` (101 °C peaks, no colour) · `coolant-dwell-fired` · `bucket-worst-band` (amber `band`, last sample below the number) · `history-gap` (omitted buckets) · `history-trimmed-2h` (`sinceTs` moved) · `history-empty-after-restart` · `mil-on-two-codes` · `mil-on-twelve-codes` · `mil-on-zero-codes` · `not-read-with-reason` · `stale` · `history-restarted-mid-drive` (`partial` true) · `timing-negative` (−4 ⇒ `4° ATDC`).

## 8. Out of scope
Boost (no source) · knock (no source) · AFR (no wideband) · MAF (Fuel page) · O2 (O2 page).

## 9. Open items
- ~~Atlas: the this-drive history provider~~ **RULED 2026-10-14 (ruling 1); CIO picked option (a) 2026-10-15: `states/engine-history`, §4 + §5.**
- ~~Atlas names the covers-drive-start field~~ **RULED: `partial: bool`** (Atlas S104 G3, same convention as `drive.distancePartial`, 2026-10-15).
- **Open (2026-10-15):** Spool confirms the timing sign convention.
- **Engine OEM mockup** (`proposals/2026-10-14-v030-engine-page-oem.html`) still uses the `1fr 1.3fr 1fr` status grid and the one-line `ON · n codes ›`; it is corrected to §3 at the same URL.
