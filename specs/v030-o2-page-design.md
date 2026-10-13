# V0.30 O2 page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 · **Status:** CIO-APPROVED design, awaiting V0.30 DoD + grooming. **Verdicts gated on Spool's polling ruling.**
**Mockup:** `proposals/2026-10-13-v030-o2-page.html` → https://claude.ai/artifact/KEcFYZg9gmoWg7UtaTtHAy (**layout A, stacked, is the locked one**)
**DoD lines served:** 7 (a new themed page; CIO added it 2026-10-13, out of the Engine page), 8
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose (CIO: "Both")
**Is closed-loop fuelling working** (front sensor switching) **and is the catalyst healthy** (rear steady while the front switches)?

## 2. Decisions locked (CIO, 2026-10-13)

| # | Decision | CIO choice |
|---|---|---|
| O-1 | O2 gets its own page | Yes (between Fuel and Motion) |
| O-2 | Forms | **All three**: voltage · switching verdict · trace |
| O-3 | Slow polling today | **Show the trace and update it at the current sample rate**; upgrade when faster sampling arrives |
| O-4 | Purpose | Both: closed-loop + catalyst |
| O-5 | Layout | **A · Front and rear stacked** (shared time axis) |

**Iris rule attached to O-3 (stated to the CIO):** the trace draws **one dot per real sample, never a joined line.** At ~15 s per sample a line would draw a ~1 Hz swing that was never measured. Dots densify into the real wave at a faster rate, with no design change.

## 3. Layout (480 × 320; body 258)

```
┌──────────────────────────────────────────────┐
│ FRONT · BEFORE CAT        [needs faster sampling]│
│ 0.78 V   4 s old · 1 sample / ~15 s           │ ~105
│ •      •           •     •            •      │ trace, last 5 min, dashed 0.45 V mid
├──────────────────────────────────────────────┤
│ REAR · AFTER CAT          [needs faster sampling]│
│ 0.62 V   1 s old · 1 sample / ~5 s            │ ~105
│ • • • • • • • • • • • • • • • • • • • • • •   │
├──────────────────────────────────────────────┤
│ CATALYST  [comparison needs faster sampling]  │ ~30
└──────────────────────────────────────────────┘
```

- Voltage `--fs-primary`; age + sample rate `--fs-meta` (**the rate is always stated**).
- Trace 456 × 44: 5-minute window, 0–1 V, dashed mid-line at 0.45 V; dots (+ stems when sparse).
- Gated verdicts: dashed outline chip, `--text-tertiary`, with the reason. Live verdicts: `--fs-label` `--font-display`.

## 4. Behaviour
- Voltages step per reading with their age. **No AFR anywhere** (narrowband; spec).
- **Trace:** one dot per real sample, positioned at its own timestamp; never interpolated or joined.
- **Verdicts are provider-derived** and **gated by sample rate**:
  - Front: `SWITCHING` / `STUCK LEAN` / `STUCK RICH`, only when the rate supports it.
  - Rear: `STEADY` / `SWITCHING` (a rear that switches like the front = tired catalyst).
  - Catalyst: `CATALYST OK` / `CHECK CATALYST`, only when both rates support it.
  - Below the rate: chip `needs faster sampling`.
- **Open loop** (cold start, full throttle): front verdict suppressed with `open loop` (the ECU isn't using O2 then).
- Stale / null: dim + age / `--` + reason.

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| O2_B1S1 (front) | tier 3 (~every 10th cycle) | exists, **too slow for verdicts** | — |
| O2_B1S2 (rear) | tier 2 (~every 3rd cycle) | exists | — |
| **Faster O2 polling** + its cost to RPM/speed/trims | K-line budget | **ruling needed** | **Spool** |
| Recent sample series (5 min) surviving kiosk restart | provider | **new** | Atlas |
| Verdicts + "rate sufficient" flag | provider, rule from Spool | **new** | Spool (rule) · Atlas (provider) |

## 6. Acceptance criteria (draft)
1. Today-rate fixture: dots only (no polyline element), rate text matches the provider's sample period, verdict chips read `needs faster sampling`.
2. Fast-rate fixture: same layout, verdicts live; no layout change between the two.
3. No AFR value or label anywhere on the page.
4. Open-loop fixture: front verdict `open loop`.
5. No clipping; voltages ≥ 34 px.
6. No literal colour or px in this page's CSS.
7. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`today-rate` · `fast-rate-healthy` · `fast-rate-tired-cat` · `stuck-lean` · `open-loop` · `o2-null` · `stale`.

## 8. Out of scope
Wideband AFR (no sensor) · bank 2 sensors (4-cylinder, one bank).
