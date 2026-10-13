# V0.30 Fuel page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12 · **Status:** CIO-APPROVED design (brainstorm 2026-10-12), awaiting V0.30 DoD + grooming
**Mockup:** `proposals/2026-10-12-v030-fuel-page.html` → https://claude.ai/artifact/GVEYon8ST2TREiq3veQBfF (**layout A is the locked one**)
**DoD lines served:** 7 (themed pages: Fuel), 8 (real source or says why), 12 (closes US-730 by rule)
**Grounding:** `specs/grounded-knowledge.md` rows *MAF*, *Fuel Trims (LTFT/STFT)*, *LTFT trend contract (US-661)*. **Numbers live there, never here** (Spool/CIO ruling 2026-09-28).
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose (CIO)
**Live fuelling: "what is the engine doing right now?"** Airflow is the hero. The long-term health trend is present but secondary.

## 2. Decisions locked (CIO, 2026-10-12)

| # | Decision | CIO choice |
|---|---|---|
| F-1 | Purpose | Live fuelling |
| F-2 | Elements | LTFT trend (5-drive median) · total trim now (LTFT+STFT) · MAF + loop status · estimated MPG |
| F-3 | Trend colour | **Spool's rule exactly**: only the median, only when his amber/red rule is met; single drives never colour |
| F-4 | MPG figures | **Three: instant · this drive · continuous since last reset** |
| F-5 | Loop status | **Neutral label** (a mode, not a fault) |
| F-6 | Reset of since-reset MPG | **Long-press the tile (~2 s), parked only, with a confirm** |
| F-7 | Hero | **MAF airflow** |
| F-8 | Layout | **A · Airflow on top** |
| F-9 | Instant MPG at 0 mph | **"stopped"** |

## 3. Layout (480 × 320; body 258 px; ≈ 238 used)

```
┌──────────────────────────────────────────────┐
│ AIRFLOW                         [CLOSED LOOP] │
│ 16.2 g/s                          TOTAL TRIM  │ ~100
│ ▬▬▬▬▬▬▬░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│░░░    │        bar 0–160, mark at ~150
│                                     +1.6 %   │
├──────────────────────────────────────────────┤
│ MPG NOW        THIS DRIVE      SINCE RESET   │ ~70
│ ≈24            ≈26.3           ≈24.6         │
├──────────────────────────────────────────────┤
│ FUEL TRIM TREND  −1.6 %   •─•─•─•─•─•─•─•    │ ~44  dots + median line + dashed baseline
└──────────────────────────────────────────────┘
```

| Element | Type tier | Note |
|---|---|---|
| Airflow value | `--fs-hero` (44) | g/s, one decimal |
| Airflow bar | 10 px | 0–160 g/s, fixed mark at the **sensor ceiling** (number from the spec) |
| Loop label | `--fs-label`, outlined chip, **no colour** | `CLOSED LOOP` / `OPEN LOOP` |
| Total trim | `--fs-primary` (34) | signed, one decimal, % |
| MPG NOW | `--fs-primary` (34) | driver-read |
| THIS DRIVE / SINCE RESET | `--fs-secondary` (26) | parked-read, allowed under the F-127 tier rule |
| Trend headline | `--fs-secondary` | latest 5-drive median |

## 4. Behaviour

### 4.1 Airflow
- Steps with each reading; no interpolation.
- At or above the sensor ceiling: `sensor limit` in `--amber-warn` `--fs-meta`. **A measurement limit, never styled as a fault** (spec MAF row).

### 4.2 Loop + total trim
- Loop label from `FUEL_SYSTEM_STATUS`. Never coloured: open loop is normal at cold start and full throttle.
- Total trim = **LTFT + STFT, one current value, no trend** (spec: *do not trend STFT*).
- **Open loop ⇒ total trim `--`** (dimmed) + `not applied in open loop`: trims aren't being applied, so showing them would describe something not happening.
- Total trim is **not banded** (the spec gives no band for it). Neutral colour.

### 4.3 MPG (all three carry `≈`)
- Estimate = speed ÷ fuel flow, fuel flow from MAF at the stoichiometric ratio. ⚠ **Assumes closed-loop stoichiometric burn**; overstates economy when rich.
- **MPG NOW:** latest MAF + speed. `stopped` at 0 mph. In open loop: value shown + `rich, overstated` flag (`--amber-warn`, `--fs-meta`). **Subject to Spool's honesty ruling (§6):** MAF and speed are sampled seconds apart.
- **THIS DRIVE:** total fuel ÷ total distance since key-on. `--` until ~0.05 mi travelled.
- **SINCE RESET:** the same, accumulated across drives until reset. **Reset:** long-press ~2 s, **parked only** (R5), then an in-page confirm `Reset average MPG?` → re-read and show the stored value (F-126 honest-write pattern: never optimistic success). Hint `hold to reset` appears **only when parked**.

### 4.4 Fuel-trim trend
- Source: the **US-661 trend contract** (epoch baseline, qualifying drives, 5-drive median).
- Dots = per-drive LTFT for **exactly the drives the headline median uses** (**closes US-730 by rule**: no chart may show a different window than its headline).
- Dashed line = epoch baseline. Solid line = rolling 5-drive median.
- **Colour only from the provider's verdict** of Spool's rule (amber/red); dots never colour. Neutral otherwise.
- LTFT **exactly 0.00 % flat** ⇒ the provider reports *adaptive memory reset*; the page shows `ECU relearning` instead of a trend point (spec: 0.00 % flat = power history, not fuel).

### 4.5 Absent / stale
- Any null ⇒ `--` + reason on the glass. Stale (> the shared timeout key) ⇒ dim + age, same rule as the driving page.

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| MAF | OBD `MAF` (0x10) | 🔴 **not in polling tiers 1–4 of `config.json`** (only in the parameter list at :146). **Confirm it is in the live capture set.** If not, airflow and all MPG have no source | **Spool + Atlas** |
| Speed | OBD `SPEED` | exists (tier 2) | — |
| Loop | `FUEL_SYSTEM_STATUS` | exists | — |
| LTFT, STFT | `LONG_FUEL_TRIM_1`, `SHORT_FUEL_TRIM_1` | exist | — |
| Trend + verdict | US-661 contract | exists as contract; **confirm a state the kiosk reads** | Atlas |
| Fuel/distance accumulators (this drive, since reset) | **new provider**, persisted on the Pi | **not built** | **Atlas design · Marcus story** |
| Reset write | token-gated write path (F-126 / US-531 precedent) | **new** | Atlas |
| Instant-MPG honesty | ruling | **open** | **Spool** |

## 6. Acceptance criteria (draft)
1. Fixtures (§7) render per §4 at 480×320, verified by screenshot.
2. No clipping; MPG NOW and total trim ≥ 34 px; airflow = `--fs-hero`.
3. Open-loop fixture: total trim renders `--` + reason; loop chip has no severity colour.
4. MAF at or above the ceiling shows `sensor limit`, and no red anywhere on the page.
5. The trend's dots are exactly the headline median's drives (fixture with > 5 drives proves the window).
6. Trend colour changes **only** with the provider verdict field; grep gate: no trim threshold in `carousel.js`.
7. Reset: unavailable while moving; parked long-press → confirm → value shown is the **re-read** stored value.
8. No literal colour or px in this page's CSS.
9. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`idle-closed` · `cruise-closed` · `wot-open-at-ceiling` · `stopped` · `trend-healthy` · `trend-amber` · `ltft-reset-zero-flat` · `maf-null` · `parked-reset-available` · `stale`.

## 8. Out of scope
Fuel level (PID unsupported on this ECU) · AFR / wideband (no sensor) · boost inference (steady-state only, ±2 psi; not on a live page) · O2 voltage as AFR (narrowband is not AFR).

## 9. Open items
- **Spool:** MAF capture confirmation; instant-MPG honesty ruling.
- **Atlas:** accumulator provider + persistence; reset write path; trend-state location; shared stale key.
- **Marcus:** a producer story (MPG accumulators + reset) is new V0.30 work, a DoD admission question.
