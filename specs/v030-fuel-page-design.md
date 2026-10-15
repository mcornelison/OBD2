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
| F-4 | MPG figures | **Three: instant · this drive · continuous since last reset**. *"Instant" became **"last 30 s"** (Spool ruling 2026-10-14, §4.3)* |
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
│ ▬▬▬▬▬▬▬░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    │        bar 0–max (params.MAF.scale), no mark
│                                     +1.6 %   │
├──────────────────────────────────────────────┤
│ LAST 30 S      THIS DRIVE      SINCE RESET   │ ~70
│ ≈24            ≈26.3           ≈24.6         │
├──────────────────────────────────────────────┤
│ FUEL TRIM TREND  −1.6 %   •─•─•─•─•─•─•─•    │ ~44  dots + median line + dashed baseline
└──────────────────────────────────────────────┘
```

| Element | Type tier | Note |
|---|---|---|
| Airflow value | `--fs-hero` (44) | g/s, one decimal |
| Airflow bar | 10 px | 0 to the scale max from `params.MAF.scale` (about 160 g/s). **No ceiling mark** (Atlas S104 ruling 2, 2026-10-14) |
| Loop label | `--fs-label`, outlined chip, **no colour** | `CLOSED LOOP` / `OPEN LOOP` |
| Total trim | `--fs-primary` (34) | signed, one decimal, % |
| MPG LAST 30 S | `--fs-primary` (34) | driver-read. Label `LAST 30 S` is 110.6 px in Michroma at 15 px (advances JSON), narrower than the `MPG NOW` it replaces |
| THIS DRIVE / SINCE RESET | `--fs-secondary` (26) | parked-read, allowed under the F-127 tier rule |
| Trend headline | `--fs-secondary` | latest 5-drive median |

## 4. Behaviour

### 4.1 Airflow
- Steps with each reading; no interpolation.
- **Above the scale max: the bar pins full, the number stays unclamped, and both stay neutral.** No `sensor limit` label and no amber (Atlas S104 ruling 2, 2026-10-14). Spool doesn't know where the sensor clips, so the page can't say the reading has hit a limit. A full bar means "at least the scale max", and the number keeps the true reading.
- *Superseded:* the earlier `sensor limit` label in `--amber-warn` at a fixed ceiling mark.

### 4.2 Loop + total trim
- Loop label from `FUEL_SYSTEM_STATUS`. Never coloured: open loop is normal at cold start and full throttle.
- Total trim = **LTFT + STFT, one current value, no trend** (spec: *do not trend STFT*).
- **Source: the live `states/obd-live` values, `params.LONG_FUEL_TRIM_1.value + params.SHORT_FUEL_TRIM_1.value`.** `--` + reason when either is null or stale. The sum is display arithmetic, like the °F conversion: no threshold and no judgement.
- 🔴 **Not `states/ltft-trend.totalTrim`.** Verified on dev 2026-10-15 (`ltft_trend_emitter.py:640-656`): that field is the newest *qualifying drive's* `ltftAvg + stftMean`, a per-drive mean. It doesn't change in open loop and isn't "now". My S104 brief pointed at it; that pointer is withdrawn. **Atlas to confirm** the live sum, or to name a provider field instead.
- **Open loop ⇒ total trim `--`** (dimmed) + `not applied in open loop`: trims aren't being applied, so showing them would describe something not happening.
- Total trim is **not banded** (the spec gives no band for it). Neutral colour.

### 4.3 MPG (all three carry `≈`)
- **Every MPG figure comes from `states/fuel-economy`. The page never divides speed by MAF** (Atlas S104 ruling 2).
- Estimate = distance ÷ fuel, fuel from MAF at the stoichiometric ratio (`pi.fuel.stoichAfr`, `pi.fuel.densityGPerL`). ⚠ **Assumes stoichiometric burn.** Open loop on this car covers BOTH enrichment (overstates MPG) and decel fuel-cut (understates it; Spool: coasting reads LOW). So the provider's `approximate` flag shows **`open loop`** on its own line directly under the THIS DRIVE figure (the note slot, empty whenever a figure shows), never "rich, overstated", which is only half true. **Not beside the `≈`** (corrected 2026-10-15, US-890-d as built): `≈26.3` + gap + `open loop` is 163.5 px in a 141.3 px column. 9 characters, inside the 16-character MPG-row fit rule. Shown only with a figure; a `--` already carries its reason.
- **LAST 30 S** (was MPG NOW; Spool 2026-10-14):
  - **The label is `LAST 30 S`, never "instant".** SPEED and MAF are sampled ~2.2 s apart, so a per-sample ratio is two points and swings wildly.
  - The provider computes miles ÷ gallons summed over a rolling 30 s window. It never averages per-sample MPGs.
  - **Integer.** At ≥ 99 it shows `99+` (decel coasts produce big numbers: right direction, false precision).
  - `--` + reason when the window covers < 0.1 mi (idle, crawling), has < 10 MAF samples, or hits any drive-level null rule. About 55 % of in-drive windows are null on the corpus, which is expected.
  - **No provider field on dev yet** (the US-881 successor story; Atlas S104 ruling 2). Until it lands, the slot shows `--` + `not published`. The field name and any extra reason codes belong to the provider story; the page maps whatever codes it ships through the §4.6 table.
  - `stopped` at 0 mph comes from the provider's reason, not from the page reading speed.
- **THIS DRIVE:** `thisDrive.mpg`. `thisDrive` is null until the window opens, which shows `--` + `not started`. A null `mpg` shows `--` + the §4.6 text for `thisDrive.mpgNullReason`. The distance floor is `pi.fuel.minMiles` (1.0 mi on dev), so `too short yet` shows for the first mile.
- **SINCE RESET:** `sinceReset.mpg`, accumulated across drives until reset. `sinceReset` null (no row yet) shows `--` + `never reset`. The block carries **no reason field**, so a null `mpg` shows `--` + `too short yet`; the page does not guess between the provider's other causes.
- **Reset:** long-press ~2 s, **parked only** (R5), then an in-page confirm `Reset average MPG?`, then `POST /fuel-reset`, then show the **re-read** stored value (F-126 honest write; never optimistic success). Hint `hold to reset` appears **only when parked**.
  - **`resetting…` shows from `Yes`, not from the 200** (Atlas 2026-10-15, S105 rulings Q4 UX note): the POST can take up to `pi.fuel.resetTimeoutSec` (5 s), and the single-threaded states server stalls the page's reads meanwhile. The confirm clock (`pi.display.stale.fuelResetConfirmSec`, default 6 s) starts at the 200.
  - **The page never holds a cached "old value".** It always renders the LATEST `states/fuel-economy` read, plus the outcome text; the only time it masks the provider is `resetting…`, bounded by the confirm window. 409 `driving` ⇒ provider value + `park to reset`; 503 / `unavailable` / `reset failed: …` ⇒ provider value + `couldn't reset`; **504 ⇒ `couldn't confirm`** (the server doesn't know whether the reset landed, and the next read settles it, so if it did land the page shows the new total); confirm timeout ⇒ provider value + `couldn't confirm`.

### 4.4 Fuel-trim trend
- Source: the **US-661 trend contract** (epoch baseline, qualifying drives, 5-drive median).
- Dots = per-drive LTFT for **exactly the drives the headline median uses** (**closes US-730 by rule**: no chart may show a different window than its headline).
- Dashed line = epoch baseline. Solid line = **the current 5-drive median, drawn flat across the drives it uses** (`ltft-trend` publishes one `median`, not a per-drive series; corrected 2026-10-14 from "rolling median", which nothing provides).
- **Colour only from the provider's verdict** of Spool's rule; dots never colour. Neutral otherwise. Both coloured verdicts (`amber` and `down`) paint **`--amber-warn`**, never red (Spool per-surface ruling #4; TD-067: a degraded trend is WATCH, red is reserved for the STOP tier). *"amber/red" here earlier meant the provider's two verdicts, not two colours; US-890-a built it right.*
- **Labels, as built (US-890-a):** `AIRFLOW`, `TOTAL TRIM`, `FUEL TRIM TREND` are `--font-mono`; the frame rule wants Michroma (100.4 / 130.3 / 191.7 px at 15 px, all fit). Fidelity, not honesty: a later Fuel story widens `test_dashboard_fidelity_pass.py`'s `--font-display` pin. The MPG row labels are already Michroma (US-890-d); `SINCE RESET` is 141.3 px in a 141.33 px `1fr` column, and since `1fr` never shrinks below the nowrap label's min-content, a future overrun widens the column instead of clipping.
- LTFT **exactly 0.00 % flat** ⇒ the provider reports *adaptive memory reset*; the page shows `ECU relearning` instead of a trend point (spec: 0.00 % flat = power history, not fuel).

### 4.5 Absent / stale
- Any null ⇒ `--` + reason on the glass. Stale (> the shared timeout key) ⇒ dim + age, same rule as the driving page.

### 4.6 Reason texts
Codes are the provider's, verified on dev 2026-10-15. The texts are mine, and each is ≤ 16 characters for the MPG row fit.

| Code | Source | Text on glass |
|---|---|---|
| `maf_untrusted` | `fuel_economy_emitter.py:79` (speed-density fitted) | `MAF not fitted` |
| `maf_stale` | :80 | `no MAF reading` |
| `maf_zero_running` | :81 | `MAF reads zero` |
| `gaps` | :82 (gap time > `pi.fuel.maxExcludedPct`) | `too many gaps` |
| `too_short` | :83 (< `pi.fuel.minMiles`) | `too short yet` |
| `no_fuel` | :84 | `no fuel counted` |
| reset `driving` | `orchestrator/core.py`, fuel-reset outcome | `park to reset` |
| reset `unavailable` | same | `couldn't reset` |
| reset `reset failed: …` | same (free text) | `couldn't reset` (the raw text goes to the log; it doesn't fit) |
| reset HTTP 504, or no confirming read within `fuelResetConfirmSec` | `states_http_server.py:487-495` (outcome unknown) | `couldn't confirm` (16 chars), beside the LATEST provider value |
| any code not in this table | — | the raw code string, never blank (US-852 rule) |

**Fit rule:** every text here is ≤ 16 characters (longest `no fuel counted`, 15). A new code needs a text that fits, or its row wraps to two lines. It never shrinks (same rule as INTAKE AIR on Driving).

## 5. Data contract (re-verified on origin/dev 2026-10-15)

| Need | Source | Status | Owner |
|---|---|---|---|
| MAF | `states/obd-live` `params.MAF` | exists (Atlas MEASURED 33,269 rows, 0–158.69 g/s) | — |
| MAF scale max | `params.MAF.scale = {max}` from `pi.display.scale.mafMaxGs`, validator default 160 (Atlas S104 ruling 2; Spool's number) | **not on dev**: S104 story B, same publish path as `params.RPM.scale` | Ralph |
| Speed | OBD `SPEED` | exists (tier 2) | — |
| Loop | `params.FUEL_SYSTEM_STATUS` | exists | — |
| Total trim now | `params.LONG_FUEL_TRIM_1` + `params.SHORT_FUEL_TRIM_1` (live) | exist (STFT tier 1, LTFT tier 3) | **Atlas: confirm (§4.2)** |
| Trend + verdict | `states/ltft-trend`: `median`, `level`, `reason`, `sufficient`, `baseline`, `points[].inMedian`, `isReset`/`epochBreak` | exists | — |
| THIS DRIVE, SINCE RESET | `states/fuel-economy` `{thisDrive{fuelL, mpg, sinceTs, approximate, openLoopAirPct, mpgNullReason?}, sinceReset{fuelL, distanceKm, mpg, resetAtTs}, ts}` | **exists** (US-881-b/c, `fuel_economy_emitter.py`) | — |
| MPG last 30 s | a `states/fuel-economy` field following Spool's ratio-of-sums rules a–c | **not on dev** (US-881 successor) | Atlas design · Marcus story |
| Reset write | token-gated `POST /fuel-reset` via `fuel_reset_channel`; outcome `{requestId, ok, reason, resetAtTs, completedAtEpoch}`, refused with `driving` while a drive records | **exists** (US-881-d) | — |

## 6. Acceptance criteria (draft; folded from the S104 brief + Atlas/Spool rulings 2026-10-14)
1. Fixtures (§7) render per §4 at 480×320, verified by screenshot.
2. Airflow is `--fs-hero`, steps with each reading, no interpolation. Above `params.MAF.scale.max`: the bar is exactly full, the number shows the unclamped reading, no `sensor limit` text, and nothing on the airflow element is amber or red. Grep gate: no MAF max literal in `carousel.js`.
3. Loop chip outlined, no state colour. Open loop: total trim `--` dimmed + `not applied in open loop`.
4. Total trim is the live LTFT + STFT sum, unbanded and neutral. It is never read from `ltft-trend.totalTrim`.
5. All MPG carry `≈`. The `approximate` flag shows `open loop` (`--amber-warn`, `--fs-meta`) on its own line under the THIS DRIVE figure. The text `rich, overstated` appears nowhere.
6. LAST 30 S: label `LAST 30 S`, never `instant`; integer; `99+` at ≥ 99; `--` + reason for every null. While the provider field is absent: `--` + `not published`. Grep gate: `carousel.js` never divides by a MAF value.
7. THIS DRIVE / SINCE RESET: every null shows `--` + the §4.6 text for the provider's code. An unknown code shows the raw code. Nothing is ever blank.
8. Reset: hint + long-press are parked only and absent while moving. Confirm, then `POST /fuel-reset`, then the shown value is the **re-read** stored value. `resetting…` from `Yes`. On `driving` / `unavailable` / failure / 504 / confirm timeout: the LATEST provider value + the §4.6 text, never a page-cached value. VC: a 504, then a read with `sinceReset.resetAtTs` = T and `mpg` null ⇒ `--` + `too short yet`, not the pre-reset MPG.
9. Trend dots are exactly the `inMedian` points (a > 5-drive fixture proves the window). Colour only from `level`. A relearn shows `ECU relearning`, not a point. Grep gate: no trim threshold in `carousel.js`.
10. LAST 30 S and total trim ≥ 34 px; THIS DRIVE / SINCE RESET `--fs-secondary` (parked-read). No reason text wider than its MPG column (§4.6 fit rule).
11. Tokens-only CSS; geometry as scoped custom properties on the card (S103 G-4 rule).
12. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`idle-closed` · `cruise-closed` · `wot-open-above-scale-max` · `stopped` · `last30-null-crawl` · `last30-99-plus` · `last30-not-published` · `trend-healthy` · `trend-amber` · `ltft-reset-zero-flat` · `maf-null` · `mpg-null-reasons` (one per §4.6 code) · `sinceReset-never` · `parked-reset-available` · `reset-refused-driving` · `reset-write-fails` · `stale`.

## 8. Out of scope
Fuel level (PID unsupported on this ECU) · AFR / wideband (no sensor) · boost inference (steady-state only, ±2 psi; not on a live page) · O2 voltage as AFR (narrowband is not AFR).

## 9. Open items
- ~~Spool: MAF capture confirmation~~ (Atlas MEASURED: 33,269 rows, 0–158.69 g/s) · ~~Spool: instant-MPG honesty ruling~~ **RULED 2026-10-14: "last 30 s", ratio of sums (§4.3).**
- ~~Atlas: MAF ceiling~~ **RULED 2026-10-14: `params.MAF.scale = {max}`, no label (§4.1).**
- **Atlas:** confirm total trim now = live `LONG_FUEL_TRIM_1 + SHORT_FUEL_TRIM_1` (§4.2).
- **Marcus:** is the MPG last-30 s provider story in S104? If not, LAST 30 S ships as `--` + `not published`.
- ~~Atlas~~ (ruled 2026-10-13): NEW `states/fuel-economy` on ONE speed integrator shared with US-704; `sinceReset` persists in obd.db; reset via token-gated `POST /fuel-reset`; trend is `states/ltft-trend` + `inMedian` per point; stale key `pi.display.stale.obdLiveSec`.
- ~~Marcus: a producer story (MPG accumulators + reset)~~ **built: US-881-b/c/d on dev.**
- **Later, not S105 (Atlas flag, 2026-10-15):** THIS DRIVE MPG counts from the same since-point as the NAV trip (`fuel_economy_emitter.py:390`), so it has the same mid-drive-restart case. Same remedy when scheduled: carry a `partial` flag into `thisDrive` and label `SINCE h:mm` when true.
