# V0.30 O2 page — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 · **Status:** CIO-APPROVED design, awaiting V0.30 DoD + grooming. **Reworked 2026-10-13 to Spool's rulings:** no faster polling; front verdict from the voltage **distribution**; rear + catalyst verdicts **held** (CIO).
**Mockup:** `proposals/2026-10-13-v030-o2-page.html` → https://claude.ai/artifact/KEcFYZg9gmoWg7UtaTtHAy (**layout A, stacked, is the locked one**; chip wording on the mockup predates this rework, see §3)
**DoD lines served:** 7 (a new themed page; CIO added it 2026-10-13, out of the Engine page), 8
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose (CIO: "Both")
**Is closed-loop fuelling working** (front sensor switching) **and is the catalyst healthy** (rear steady while the front switches)? The second question is **held** until after the CIO's exhaust project (§4.3).

## 2. Decisions locked (CIO, 2026-10-13)

| # | Decision | CIO choice |
|---|---|---|
| O-1 | O2 gets its own page | Yes (between Fuel and Motion) |
| O-2 | Forms | **All three**: voltage · verdict · trace |
| O-3 | Sample rate | **Show the trace at the real rate.** ~~Upgrade when faster sampling arrives~~: **no faster polling** (Spool 2026-10-13; tiers banked, R34) |
| O-4 | Purpose | Both: closed-loop + catalyst (catalyst held, §4.3) |
| O-5 | Layout | **A · Front and rear stacked** (shared time axis) |
| O-6 | Rear + catalyst verdicts | **Held** (CIO 2026-10-13): chips read `not rated` (was `not rated yet`; `yet` dropped by the CIO 2026-10-26, no promise words) |

**Iris rule attached to O-3:** the trace draws **one dot per real sample, never a joined line.** At ~2.2 s per sample a line would still draw a swing that was never measured.

**Why no faster polling (Spool, MEASURED 2026-10-13, drives 115–117):** every PID, both O2 sensors included, samples at **0.446 Hz (~2.2 s)**; the K-line carries ~7.1 req/s shared by 16 PIDs. A 1 Hz front O2 is still below Nyquist for a ~1 Hz switch and buys nothing. 2 Hz pushes the others to 2.9 s, past gear derivation's 3.0 s max age, so gear flickers stale. 4 Hz breaks gear and the Driving page's 5 s stale dim. **The voltage distribution survives slow sampling** (samples are not phase-locked to the switching, so aliasing destroys the frequency, not the histogram), and the verdict is built on that.

## 3. Layout (480 × 320; body 258)

```
┌──────────────────────────────────────────────┐
│ FRONT  BEFORE CAT                 [SWITCHING] │
│ 0.78 V   2 s old · 1 sample / ~2.2 s          │ ~105
│ •  •    •  •   • •   •  •    •  • •   •  •   │ trace, last 5 min, dashed 0.45 V mid
├──────────────────────────────────────────────┤
│ REAR  AFTER CAT                   [not rated] │
│ 0.18 V   1 s old · 1 sample / ~2.2 s          │ ~105
│ • • •  • • • • • •  • • • • • • • •  • • •    │
├──────────────────────────────────────────────┤
│ CATALYST                          [not rated] │ ~30
└──────────────────────────────────────────────┘
```

- Section labels `FRONT  BEFORE CAT` / `REAR  AFTER CAT` / `CATALYST`: Michroma `--fs-meta`, a double space, no middle dot (OEM finding).
- Voltage `--fs-primary`, 2 dp + ` V`. Meta line `--font-mono` `--fs-meta`: `<n> s old · 1 sample / ~<N> s · last 5 min`, with N = the provider's `samplePeriodSec` to 1 dp (**the rate is always stated**, from the provider).
- Trace 456 × 44 (`--o2-trace-h: 44px`): the provider's window (5 min, ~136 dots at today's rate), 0–1 V, a dashed mid-line at the provider's **`midlineV`** (0.45, Atlas A1: one home in `o2_state.py`); dots only. The page holds no threshold number.
- **Live verdict** chip: `--fs-label` `--font-display`, **no state colour** (the verdict is a description, not a severity; STUCK is not a STOP).
- **Withheld verdict** chip: lower case, `--font-mono` `--fs-label` (the Michroma subset has no a–z), dashed outline, `--text-tertiary`. **The word is the provider's reason code with `_` → space:** `open_loop` → `open loop`, `not_enough_data` → `not enough data`, `unclear`, `not_rated` → `not rated`. Each is a different reason, and the chip says which. A new reason code renders readably with no page change.
- **No promise words** (CIO 2026-10-26: `yet` dropped): the chip says why there is no verdict, never that one is coming.

## 4. Behaviour

### 4.1 Values and trace
- Voltages step per reading with their age. **No AFR anywhere** (narrowband).
- **Trace:** one dot per real sample at its own timestamp; never interpolated or joined.
- Stale / null: dim + age / `--` + reason (shared rule: a stale value renders `last.value` dimmed, Driving §4.4).
- **`states/o2` missing or unreadable:** every value `--` with the reason `no source` (the Driving page's word), never `0.00 V`.

### 4.2 Front verdict (Spool 2026-10-13; provider-derived, the page renders the word)

**Gate:** a verdict only when `FUEL_SYSTEM_STATUS` = closed loop (value 2 on this car, encoding derived by correlation) **and** coolant ≥ 85 °C. Otherwise the chip reads `open loop`.
- **Per sample (Atlas + Spool, 2026-10-26):** a front sample is gated by the latest `FUEL_SYSTEM_STATUS` and `COOLANT_TEMP` readings at or before the sample's event ts, each not stale (Atlas), and from the same poll cycle, within 1.1 s of the sample (Spool). Otherwise the sample is ungated.

**Window:** the last 5 minutes, **≥ 60 gated front samples** (~2.2 min of closed loop). Fewer: `not enough data`.

| Verdict | Rule (fractions of gated samples in the window) |
|---|---|
| `SWITCHING` | frac(< 0.30 V) ≥ 0.20 **and** frac(> 0.60 V) ≥ 0.20 |
| `STUCK LEAN` | frac(< 0.45 V) ≥ 0.90 |
| `STUCK RICH` | frac(> 0.45 V) ≥ 0.90 |
| `unclear` | none of the above. **Never a guess.** |

- Basis: 15 drives (85–117) all read SWITCHING; the 0.20 floor clears the lowest by 1.45×.
- **The STUCK thresholds are convention and have never been exercised on this car.** Treat a first STUCK reading as something to check, not as proven.
- **What this rate cannot tell:** switching **speed** (a lazy, ageing sensor). That needs ≥ 4 Hz on one PID, which §2 rules out. The page must not imply it.

### 4.3 Rear and catalyst: held (CIO 2026-10-13)
- Both chips read **`not rated`**. The rear voltage and its dot trace stay.
- Why (Spool): the rear sits **low on all 15 drives** (avg 0.15–0.26 V, 63–88 % of samples < 0.3 V), and the catalyst monitor was NOT READY at the 09-26 test. A simple rule would show CHECK CATALYST from day one, and this data cannot separate a tired cat, an exhaust leak near the sensor and an old sensor. The CIO's exhaust project replaces the cat; Spool validates the rule after it is installed.
- Void if the rear readings turn out not to be the downstream sensor (config still calls 0x15 "support uncertain").

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| O2_B1S1 (front), O2_B1S2 (rear) | `states/obd-live` params (Atlas G-3; Sprint 98 US-874) | in Sprint 98 | Atlas · Ralph |
| Sample period (rate text) | **both ~2.2 s** (0.446 Hz, Spool MEASURED); the configured poll tiers are inert | provider states it | Atlas |
| Gate inputs | `FUEL_SYSTEM_STATUS`, `COOLANT_TEMP` in obd-live | exists in capture | — |
| Recent sample series (5 min) surviving a kiosk restart | provider ring buffer (same reason as `grade-history`, Atlas M-C) | **new, not yet ruled** | Atlas |
| Front verdict + reason (`switching`/`stuck_lean`/`stuck_rich`/`unclear`/`open_loop`/`not_enough_data`) | provider, rule §4.2 | **new** | Spool (rule, in his spec via Atlas) · Atlas (provider) |
| Rear + catalyst verdicts | — | **held**: provider publishes `not_rated` | Spool, after the exhaust project |

## 6. Acceptance criteria (draft)
1. Dots only: no polyline/path joins samples; rate text equals the provider's sample period.
2. Each front-verdict fixture shows the provider's word; the page computes no fraction (grep gate: no `0.30`, `0.45`, `0.60`, `0.90` and no `AFR` in O2 code in `carousel.js`). The mid-line is drawn from `midlineV`.
3. Open-loop and cold-closed-loop fixtures: front chip = the provider's reason (`open loop`, or the S1 ruling's word), by the `_` → space rule.
4. Under 60 gated samples: front chip `not enough data`.
5. Rear and catalyst chips read `not rated` in every fixture.
6. No AFR value or label anywhere on the page.
7. No clipping, **proven by rule** (the render harness resolves the cascade, not layout; precedent `test_engine_history_render.py`): no O2 box has a fixed height except the trace (`--o2-trace-h`), and no O2 rule sets `overflow: hidden`. On the glass: an on-Pi screenshot of the `switching` fixture shows both rows and both traces whole (bigDoD). Voltages ≥ 34 px. Live verdict chips carry no state colour.
8. No literal colour in this page's CSS; px only inside `#o2-card` custom properties.
8a. `states/o2` missing ⇒ `--` + `no source`, never `0.00 V`.
9. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`not-enough-data` · `switching` · `stuck-lean` · `stuck-rich` · `unclear` · `open-loop` · `cold-closed-loop` (closed loop, coolant 80 °C) · `rear-held` · `o2-null` · `stale`.

## 8. Out of scope
Wideband AFR (no sensor) · bank 2 sensors (4-cylinder, one bank) · switching-speed verdicts (rate) · catalyst verdict (held).

## 9. Open items
- **Atlas:** the 5-minute series provider; carry Spool's rule into the provider story.
- **Spool:** rear/catalyst rule after the exhaust project.
- **Mockup:** chip words on the published mockup predate this rework (`needs faster sampling`); refresh in the next mockup pass.

## OEM mockup findings (2026-10-15)
Mockup: `proposals/2026-10-15-v030-o2-page-oem.html`.
- **Section labels have no middle dot:** `FRONT  BEFORE CAT` (218.5 px at 15 px) and `REAR  AFTER CAT`, double-spaced, because the Michroma subset has no `·` (same as Motion's `GRADE  LAST 15 MIN`).
- **Chip fonts:** the live verdict chips (`SWITCHING`, `STUCK LEAN` …) are Michroma. The withheld chips are lower case (`not enough data`, `open loop`), so they are `--font-mono`: the Michroma subset has no a-z. *(Corrected 2026-10-26, S117 review: this line said `--font-body`, a token that doesn't exist; tokens.css has only `--font-mono` and `--font-display`.)*
- **Window on the glass:** `last 5 min` ends the meta line, since the trace has no axis labels.
- **Page dots** follow the page list. With O2 built, the strip has 10 dots (S105 order plus O2).
- ⚠️ **Open (Spool/Atlas): the cold-closed-loop fixture.** The loop is really closed and only the < 85 °C coolant gate fails, but the withheld chip reads `open loop`, which is false. Proposed: a separate reason `warming up`. The reason text is the provider's, not the page's.
