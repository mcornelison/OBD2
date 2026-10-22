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
| F-6 | Reset of since-reset MPG | **Long-press the tile (~2 s), with a confirm. Allowed when parked OR at a fresh SPEED ≤ 8 km/h in any gear** (CIO 2026-10-22; was parked only) |
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
│ ≈24 MPG        ≈26.3 MPG       ≈24.6 MPG     │   unit after every figure (US-922, §4.3)
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
| MPG unit | `--fs-label` (20), mono, `--text-secondary` | `MPG` after every MPG figure, the airflow `g/s` pattern (`.fuel-unit`, 4 px gap, same baseline). US-922, §4.3 |
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
- **The unit is on the glass** (US-922, CIO 2026-10-22: he did not recognise the row as fuel economy; *"just text, not new functionality"*). Every MPG figure is followed by **`MPG`**: mono, `--fs-label`, `--text-secondary`, on the figure's baseline with the 4 px `--fuel-unit-gap`. The same markup and class as the airflow's `g/s` (`.fuel-unit`), so the page has one unit idiom.
  - **Shown only with a figure.** `--` never carries a unit: its reason line already says why there's no number. `99+` carries it (`≈99+ MPG`).
  - **Why a unit per figure and not a row heading:** a heading is one more line (≈ 30 px with the grid gap) on a card body that already scrolls (measured on dev `c1b20e8e`: 239 px client, more content than that), and it would push the trend further down. The unit costs no height. The labels don't change, so `SINCE RESET` (141.3 of 141.33 px) is untouched.
  - **Fit, computed at the worst case** (DejaVu Sans Mono, the Pi's mono face, 0.602 em per character; a headless-Windows render uses Consolas and is narrower, so it can't prove this; column 141.33 px, 136 px when the body's scrollbar shows, which is the case to design for):
    - LAST 30 S at 34 px: `≈99+` 81.9 + 4 + `MPG` 36.1 = **122.0 px**.
    - THIS DRIVE / SINCE RESET at 26 px: `≈99.9` → 118.4 px; `≈100.0` (six characters) → **134.0 px**, 2 px inside 136.
    - Seven characters (≥ 1000 MPG) would be 149.7 px: the figure line may wrap, so `MPG` drops under the figure. It never clips, shrinks or ellipsizes (same rule as the reason texts).
  - Words, not a label change: `LAST 30 S`, `THIS DRIVE`, `SINCE RESET` stay as they are; `MPG NOW` stays retired. The reset confirm already says `Reset average MPG?`.
- **Every MPG figure comes from `states/fuel-economy`. The page never divides speed by MAF** (Atlas S104 ruling 2).
- Estimate = distance ÷ fuel, fuel from MAF at the stoichiometric ratio (`pi.fuel.stoichAfr`, `pi.fuel.densityGPerL`). ⚠ **Assumes stoichiometric burn.** Open loop on this car covers BOTH enrichment (overstates MPG) and decel fuel-cut (understates it; Spool: coasting reads LOW). So the provider's `approximate` flag shows **`open loop`** on its own line directly under the THIS DRIVE figure (the note slot, empty whenever a figure shows), never "rich, overstated", which is only half true. **Not beside the `≈`** (corrected 2026-10-15, US-890-d as built): `≈26.3` + gap + `open loop` is 163.5 px in a 141.3 px column. 9 characters, inside the 16-character MPG-row fit rule. Shown only with a figure; a `--` already carries its reason.
- **LAST 30 S** (was MPG NOW; Spool 2026-10-14):
  - **The label is `LAST 30 S`, never "instant".** SPEED and MAF are sampled ~2.2 s apart, so a per-sample ratio is two points and swings wildly.
  - The provider computes miles ÷ gallons summed over a rolling 30 s window. It never averages per-sample MPGs.
  - **It carries `≈` like the other two** (Iris RULED 2026-10-22, S112 I1; UIDEV-012): `≈27 MPG`, `≈99+ MPG`. Shipped `carousel.js` drops it (*"the label already says last 30 s"*, pinned by `test_fuel_page.py`); that is the build's to change. **Why:** `LAST 30 S` names the window, not the precision. The figure is the same stoichiometric MAF estimate as the other two, and the noisiest of the three, and it has no `open loop` note to say so. The sign is the only cue on it that the number is an estimate. It fits: `≈99+ MPG` is 122.0 px of 136. *If Spool's 2026-10-14 display rule (his s2) itself drops the sign, his rule wins and this line reverts; the shipped comment cites him only for the integer and `99+`.*
  - **Integer.** At ≥ 99 it shows `99+` (decel coasts produce big numbers: right direction, false precision).
  - `--` + reason when the window covers < 0.1 mi (idle, crawling), has < 10 MAF samples, or hits any drive-level null rule. About 55 % of in-drive windows are null on the corpus, which is expected.
  - **No provider field on dev yet** (the US-881 successor story; Atlas S104 ruling 2). Until it lands, the slot shows `--` + `not published`. The field name and any extra reason codes belong to the provider story; the page maps whatever codes it ships through the §4.6 table.
  - `stopped` at 0 mph comes from the provider's reason, not from the page reading speed.
- **THIS DRIVE:** `thisDrive.mpg`. `thisDrive` is null until the window opens, which shows `--` + `not started`. A null `mpg` shows `--` + the §4.6 text for `thisDrive.mpgNullReason`. The distance floor is `pi.fuel.minMiles` (1.0 mi on dev), so `too short yet` shows for the first mile.
- **SINCE RESET:** `sinceReset.mpg`, accumulated across drives until reset. `sinceReset` null (no row yet) shows `--` + `never reset`. The block carries **no reason field**, so a null `mpg` shows `--` + `too short yet`; the page does not guess between the provider's other causes.
- **Reset gate (CIO RULED 2026-10-22, V0.30; Marcus folded it into UIDEV-011). The one control with its own gate:**
  - **Allowed** when **parked** (System §4.7.2: gear `P` or `N`, held 8 s) **OR** when `states/obd-live` `params.SPEED` is **fresh** (≤ `pi.display.stale.obdLiveSec`) **and ≤ 8 km/h** (5 mph), in any gear. At 3 mph in 2nd it is allowed.
  - **Not allowed** otherwise: fresh SPEED > 8 km/h and not parked, or SPEED stale/absent and not parked. Unknown speed never allows it (fails closed, the §4.7.2 rule's direction).
  - The speed side has **no hold**: the CIO ruled none, and the page doesn't add one. The parked side keeps its 8 s / 3 s debounce.
  - The SERVER re-checks the same gate on the POST and refuses with its own reason (`driving`). It must not keep the old parked-only test, or the page offers a reset the server refuses at walking pace. That is the build's (Ralph/Atlas), recorded here so the two gates stay one.
- **Reset:** long-press ~2 s **while the gate allows it**, then an in-page confirm `Reset average MPG?`, then `POST /fuel-reset`, then show the **re-read** stored value (F-126 honest write; never optimistic success). Hint `hold to reset` appears **only while the gate allows it**, and the long-press is inert otherwise (R5: nothing to work at speed, so no word is drawn either).
  - **Its own refusal word: `slow to reset`** (13 characters, inside the 16-character row rule). It's what the server's 409 `driving` now shows. Not `park to reset` (false: parking isn't needed) and not `stop to …` (the System/Warnings word, false here: at 5 mph the reset works).
  - A refusal while the speed is unknown still shows the server's reason through the §4.6 table; if the server ever distinguishes it, `speed unknown` (13) is the word.
  - **`resetting…` shows from `Yes`, not from the 200** (Atlas 2026-10-15, S105 rulings Q4 UX note): the POST can take up to `pi.fuel.resetTimeoutSec` (5 s), and the single-threaded states server stalls the page's reads meanwhile. The confirm clock (`pi.display.stale.fuelResetConfirmSec`, default 6 s) starts at the 200.
  - **The page never holds a cached "old value".** It always renders the LATEST `states/fuel-economy` read, plus the outcome text; the only time it masks the provider is `resetting…`, bounded by the confirm window. 409 `driving` ⇒ provider value + `slow to reset`; 503 / `unavailable` / `reset failed: …` ⇒ provider value + `couldn't reset`; **504 ⇒ `couldn't confirm`** (the server doesn't know whether the reset landed, and the next read settles it, so if it did land the page shows the new total); confirm timeout ⇒ provider value + `couldn't confirm`.

### 4.4 Fuel-trim trend
- Source: the **US-661 trend contract** (epoch baseline, qualifying drives, 5-drive median).
- Dots = per-drive LTFT for **exactly the drives the headline median uses** (**closes US-730 by rule**: no chart may show a different window than its headline).
- Dashed line = epoch baseline. Solid line = **the current 5-drive median, drawn flat across the drives it uses** (`ltft-trend` publishes one `median`, not a per-drive series; corrected 2026-10-14 from "rolling median", which nothing provides).
- **Colour only from the provider's verdict** of Spool's rule; dots never colour. Neutral otherwise. Both coloured verdicts (`amber` and `down`) paint **`--amber-warn`**, never red (Spool per-surface ruling #4; TD-067: a degraded trend is WATCH, red is reserved for the STOP tier). *"amber/red" here earlier meant the provider's two verdicts, not two colours; US-890-a built it right.*
- **Labels, as built (US-890-a):** `AIRFLOW`, `TOTAL TRIM`, `FUEL TRIM TREND` are `--font-mono`; the frame rule wants Michroma (100.4 / 130.3 / 191.7 px at 15 px, all fit). Fidelity, not honesty: a later Fuel story widens `test_dashboard_fidelity_pass.py`'s `--font-display` pin. The MPG row labels are already Michroma (US-890-d); `SINCE RESET` is 141.3 px in a 141.33 px `1fr` column, and since `1fr` never shrinks below the nowrap label's min-content, a future overrun widens the column instead of clipping.
- **After an adaptive-memory reset the PROVIDER says so** (US-890-g, S106; Atlas 2026-10-15, CIO 2026-10-18, Spool 2026-10-19 S4). `states/ltft-trend.reason` = `ECU relearning` while the current epoch began at a reset and has fewer than 5 qualifying drives, including none. The page renders the reason **verbatim** in the trend's reason span (mono, `--fs-meta`; no `--` added, Atlas Q30) and draws no dot for it. *Superseded 2026-10-19: the page's per-point `isReset` branch could never fire (no provider sets it per point), so it is deleted with its hand-set fixture; the page derives nothing from a 0.00 % reading.*
  - **Precedence is the provider's** (Spool S4): `WARMING` wins only while the CURRENT drive is below the warm gate. Once warm, `ECU relearning` shows for the rest of that drive and every drive until 5 qualifying post-reset drives. A drive that fails the warm gate never counts toward the 5, and missing post-reset data is relearning, never warming.
  - It ends when the epoch reaches the 5-drive median (the normal `sufficient` transition).

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
| reset `driving` | `orchestrator/core.py`, fuel-reset outcome (refused by the §4.3 gate) | `slow to reset` (was `park to reset`, false since the CIO's 8 km/h clause) |
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
| Trend + verdict | `states/ltft-trend`: `median`, `level`, `reason`, `sufficient`, `baseline`, `points[].inMedian`, `epochBreak`; `reason` includes `ECU relearning` (US-890-g) | exists | — |
| THIS DRIVE, SINCE RESET | `states/fuel-economy` `{thisDrive{fuelL, mpg, sinceTs, approximate, openLoopAirPct, mpgNullReason?}, sinceReset{fuelL, distanceKm, mpg, resetAtTs}, ts}` | **exists** (US-881-b/c, `fuel_economy_emitter.py`) | — |
| MPG last 30 s | a `states/fuel-economy` field following Spool's ratio-of-sums rules a–c | **not on dev** (US-881 successor) | Atlas design · Marcus story |
| Reset write | token-gated `POST /fuel-reset` via `fuel_reset_channel`; outcome `{requestId, ok, reason, resetAtTs, completedAtEpoch}`, refused with `driving` while a drive records | **exists** (US-881-d) | — |

## 6. Acceptance criteria (draft; folded from the S104 brief + Atlas/Spool rulings 2026-10-14)
1. Fixtures (§7) render per §4 at 480×320, verified by screenshot.
2. Airflow is `--fs-hero`, steps with each reading, no interpolation. Above `params.MAF.scale.max`: the bar is exactly full, the number shows the unclamped reading, no `sensor limit` text, and nothing on the airflow element is amber or red. Grep gate: no MAF max literal in `carousel.js`.
3. Loop chip outlined, no state colour. Open loop: total trim `--` dimmed + `not applied in open loop`.
4. Total trim is the live LTFT + STFT sum, unbanded and neutral. It is never read from `ltft-trend.totalTrim`.
5. All MPG carry `≈`. The `approximate` flag shows `open loop` (`--amber-warn`, `--fs-meta`) on its own line under the THIS DRIVE figure. The text `rich, overstated` appears nowhere.
5a. **MPG unit (US-922):** every MPG figure, `99+` included, is followed by `MPG` in `.fuel-unit` (mono, `--fs-label`, `--text-secondary`); a `--` never is. Screenshot `≈100.0 MPG` in THIS DRIVE at 480×320 with the body scrollbar showing: one line, nothing clipped.
6. LAST 30 S: label `LAST 30 S`, never `instant`; integer; `99+` at ≥ 99; `--` + reason for every null. While the provider field is absent: `--` + `not published`. Grep gate: `carousel.js` never divides by a MAF value.
7. THIS DRIVE / SINCE RESET: every null shows `--` + the §4.6 text for the provider's code. An unknown code shows the raw code. Nothing is ever blank.
8. Reset: hint + long-press follow the §4.3 gate: present when parked (gear `N`, idling, held 8 s) and when fresh SPEED ≤ 8 km/h in a numbered gear (fixture: 5 km/h in 2nd); absent at fresh SPEED 9 km/h not parked, and with SPEED stale not parked. A 409 `driving` shows `slow to reset`; `park to reset` appears nowhere. Confirm, then `POST /fuel-reset`, then the shown value is the **re-read** stored value. `resetting…` from `Yes`. On `driving` / `unavailable` / failure / 504 / confirm timeout: the LATEST provider value + the §4.6 text, never a page-cached value. VC: a 504, then a read with `sinceReset.resetAtTs` = T and `mpg` null ⇒ `--` + `too short yet`, not the pre-reset MPG.
9. Trend dots are exactly the `inMedian` points (a > 5-drive fixture proves the window). Colour only from `level`. A relearning epoch shows the provider's `ECU relearning` reason and no dot for it; `isReset` does not appear in `carousel.js` (US-890-g). Grep gate: no trim threshold in `carousel.js`.
10. LAST 30 S and total trim ≥ 34 px; THIS DRIVE / SINCE RESET `--fs-secondary` (parked-read). No reason text wider than its MPG column (§4.6 fit rule).
11. Tokens-only CSS; geometry as scoped custom properties on the card (S103 G-4 rule).
12. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`idle-closed` · `cruise-closed` · `wot-open-above-scale-max` · `stopped` · `last30-null-crawl` · `last30-99-plus` · `last30-not-published` · `trend-healthy` · `trend-amber` · `ltft-relearning-after-reset` (built by `buildLtftTrendState`, replaces the hand-set `ltft-reset-zero-flat`) · `maf-null` · `mpg-null-reasons` (one per §4.6 code) · `sinceReset-never` · `parked-reset-available` · `slow-reset-available` (5 km/h in 2nd: hint shown) · `reset-gate-closed-9kmh` (no hint) · `reset-gate-speed-stale` (no hint) · `reset-refused-driving` (`slow to reset`) · `reset-write-fails` · `stale`.

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
