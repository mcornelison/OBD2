# Grounded Knowledge Sources

Authoritative, fact-based sources for the Eclipse OBD-II Performance Monitoring System. All thresholds, ranges, technical specs, and community guidance referenced in this project MUST trace back to one of these sources, real vehicle data, or explicit CIO input (see PM Rule 7 in `pm/projectManager.md`).

---

## Authoritative Sources

### 1. DSMTuners Community
- **URL**: https://www.dsmtuners.com/
- **What it is**: The primary online community for Diamond Star Motors (DSM) vehicles — Mitsubishi Eclipse, Eagle Talon, Plymouth Laser (1989-1999). Forum-based knowledge with decades of accumulated tuning experience.
- **What we use it for**:
  - Safe operating ranges (coolant 190-210F, boost ~12 psi stock, AFR 11.0-11.8 WOT, knock count 0 ideal)
  - 2G DSM-specific OBD-II quirks and limitations
  - Community consensus on monitoring approaches ("OBDII loggers suck on 2G's" but adequate for health monitoring)
  - Mod compatibility and tuning advice
  - PiLink concept validation (community member's Pi-based OBD-II logger)
- **Reliability note**: High volume of posts — look for common success patterns, not one-off advice. Cross-reference across multiple threads.
- **Referenced in**: `specs/obd2-research.md` (Sections 5, 7, 8, 10)

### 2. OBDLink LX (ScanTool.net)
- **URL**: https://www.obdlink.com/products/obdlink-lx/
- **What it is**: Official product page for the OBDLink LX Bluetooth OBD-II adapter — the hardware dongle used in this project.
- **What we use it for**:
  - Hardware specifications and protocol support
  - Firmware version reference (current: 5.6.19)
  - Bluetooth connectivity specs (MAC: `00:04:3E:85:0D:FB`, Serial: 115510683434)
  - Supported OBD-II protocols (ISO 9141-2 for our 1998 Eclipse)
  - ELM327-compatible AT command set
- **Reliability note**: Manufacturer source — authoritative for hardware specs. Community forums supplement with real-world performance data.
- **Referenced in**: `specs/architecture.md` (External Dependencies), `specs/glossary.md`, `specs/OBDLink-LX-Info.txt`

### 3. ECMLink V3 (ECMTuning)
- **URL**: https://ecmlink.com/
- **What it is**: Official site for ECMLink V3 — the industry-standard programmable ECU tuning software for 1990-1999 DSM vehicles. Made by ECMTuning.
- **What we use it for**:
  - Phase 2 integration planning (after programmable ECU installation)
  - Understanding MUT protocol (proprietary Mitsubishi, 15,625 baud — 10x faster than OBD-II)
  - Available tuning parameters: fuel maps, timing maps, airflow tables, boost control
  - Datalogging capabilities (1000+ samples/sec vs OBD-II's ~4-5 PIDs/sec)
  - Wideband O2 integration, speed density mode, GM MAF translation
  - Data export format (Excel-compatible, copy-paste)
- **Reliability note**: Manufacturer source — authoritative for ECMLink capabilities and requirements. CIO owns ECMLink V3 (not yet installed).
- **Referenced in**: `pm/projectManager.md` (Project Vision, ECMLink V3 Context), `pm/backlog/B-025.md`, `specs/obd2-research.md` (Section 12)

---

## Vehicle Facts

| Fact | Value | Source |
|------|-------|--------|
| Vehicle | 1998 Mitsubishi Eclipse GST (2G DSM) | CIO |
| VIN | `4A3AK54F8WE122916` | CIO (Eclipse 1998 Projects spreadsheet) |
| Engine | 4G63 turbocharged | CIO / DSMTuners |
| OBD-II Protocol | ISO 9141-2 (K-Line, 10,400 bps) | OBD-II spec + DSMTuners |
| Max polling rate | ~4-5 PIDs/sec via Bluetooth | Research (specs/obd2-research.md) |
| Core PIDs (Phase 1) | STFT (0x06), Coolant (0x05), RPM (0x0C), Timing (0x0E), Load (0x04) | Research + CIO approval |
| Current ECU | **MD326328** (mfr **E2T61683**) — 1997 2G DSM ECU, ECMLink V3 flash-modifiable, plug-installed in 98 chassis 2026-05-22 (drives ≥25). Running prior-tuner ECMLink tune; Mode 09 + Mode 22 silent over OBD. Earlier mis-recorded as MD335287; corrected 2026-06-01 from case label + mfr P/N (same physical box). | CIO + Spool knowledge.md (ECU Identity) |
| Prior ECU | **MD346675** — 1998 factory FWD-turbo ECU (ROM 6675, mfr E2T68273), drives ≤24. **100% STOCK factory tune, never flashed (CIO-confirmed 2026-05-29).** Flash-hardware but NOT ECMLink-flashable (copy-protected) — which is why it was swapped. Photo-identified 2026-05-29. | CIO photos + CIO confirmation + DSM sourcing |
| ECMLink V3 | Flash modification PRESENT on current ECU (MD326328). USB+PC cable required for deep tuning data (knock/AFR/per-cyl) — not reachable via the OBD pipe. Active ECMLink logging = next-phase goal. | CIO + Spool |
| OBD Dongle | OBDLink LX BT, MAC `00:04:3E:85:0D:FB`, FW 5.6.19 | CIO hardware |
| Installed bolt-on mods | Cold air intake, BOV, fuel pressure regulator, fuel lines, oil catch can, coilovers, engine/trans mounts | CIO (Eclipse 1998 Projects spreadsheet) |
| Mounted tires | **Bridgestone Potenza 205/55R16 91H** (RE0_0 series), made in Japan — **STOCK SIZE**. Rolling circ ≈ **1.985 m** geometric (~1.96 m loaded), ~811 rev/mi. Stock size confirms tires aren't a speed-cal factor. (The new-ECU "2× SPEED drift" was DISPROVEN 2026-06-05 — GPS Drive-27 shows the PID reads TRUE, factor 1.00; the "2×" was a km/h-read-as-mph mislabel.) **Age note: DOT `1003` = made March 2003 (~23 yr). Full tread, <10k mi, garaged/never-salted; CIO inspected no rot → CIO retaining (2026-06-01). Cleared for low-speed calibration drive; Spool reservation stands for highway/spirited use.** | CIO sidewall photos + DOT + inspection 2026-06-01 + Spool (`cards/wheels-tires-potenza-205-55r16.md`) |
| Wheels | Aftermarket gunmetal 16" twin-Y multi-spoke, 5-lug (5×114.3 DSM). Center-cap brand not confirmed. | CIO photos 2026-06-01 |
| Transmission | **Stock F5M33 5-speed** (2G FWD turbo; driver-side mount — NOT the AWD W5MG1). Ratios: 1st **3.090** / 2nd **1.833** / 3rd **1.217** / 4th **0.888** / 5th **0.741**; **final drive 4.153**. ~24 mph/1000rpm in 5th. Cross-validated vs prior-ECU Drive 18 (57.6 mph computed in 3rd @ 3937 RPM ≈ recorded). | Road Race Engineering (factory Shop Manual CD) + Spool cross-check; CIO confirmed stock unmodified |

---

## Safe Operating Ranges (Community-Sourced)

Source: DSMTuners community consensus, compiled in `specs/obd2-research.md` Section 7.

| Parameter | Safe Range | Alert Threshold | Notes |
|-----------|-----------|-----------------|-------|
| Coolant Temp | ≤101 °C (214°F) | 🟡 ≥104 °C **sustained ≥30 s** · 🔴 ≥110 °C any duration, or ≥104 °C ≥120 s | **CORRECTED 2026-08-20 (Spool, measured).** Threshold+dwell, NOT a bare threshold — 101 °C is this car's normal **fan-cycle ceiling**. A bare 🟡 inside a cycling signal's oscillation band nuisance-fires (a bare 100 °C would have fired on 6 of the last 7 *healthy* captures). **RE-VALIDATED a 4th time 2026-08-28** (drives 45–51): peak **101.0 °C**, and **zero samples >=102 °C in 16,166** across the entire corpus. The withdrawn bare 100 °C absolute would have nuisance-fired across the whole session. ⚠ Every drive on file is a ~24–27 °C ambient day — **re-check after a ~35 °C day.** The 30 s dwell remains untested against a real excursion because the engine never gets there. Derivation: `$FLEET_SHARE/tuner/knowledge/knowledge.md` §Cooling. |
| Boost (stock turbo) | ~12 psi | >15 psi on stock | Stock wastegate actuator limit |
| AFR at WOT | 11.0-11.8:1 | >12.5:1 under boost (lean danger) | Rich is safe, lean kills engines |
| Knock count | 0 | >0 sustained | Any knock is bad; transient single counts can be noise. **ECMLink USB+PC only — NOT readable over the OBD pipe** (Mode 22 silent on this ECU). |
| Oil pressure | Varies by RPM | Low at idle is concern | No OBD-II PID on stock ECU; future with ECMLink |
| **Timing Advance** | **5–10° idle · 18–32° cruise · tapers to ~18° under load** | ⚠ **No bare-level alarm is valid.** Judge **against load and RPM together** | **ADDED 2026-08-27, REFRESHED 2026-08-28 (Spool, measured — 16,145 samples).** 🔴 **The community band "10–15° idle normal, <5° or negative = danger" was WITHDRAWN, and the refresh strengthens it: it now fires on 1,606 of 16,145 samples (9.9%)**, up from 6.4 % — while **still only 1 sample in the entire corpus is actually negative.** Low advance at idle/decel/overrun is normal — the ECU has no reason to advance. Low advance **while load is high** is the signal. This car idles **5–9° (avg 7°)**, so a 10–15° "normal" grades it below-normal. All-time max **34.5°** (drive 48; supersedes 34.0° from Drive 7). ⚠ **Compute this with `drive_id IS NOT NULL`** — see Corpus Hygiene below. **Current-ECU WOT behaviour MEASURED 2026-08-28 (drive 51):** 23–26.5° approaching the pull -> **13.5° at peak airflow (147.7 g/s)** -> 25.5° recovery within ~2 s; across all 8 high-load events the minimum sat **6.5–22°** against **23–33.5° at cruise**. A sane map under load. ⚠ **`TIMING_ADVANCE` is BASE timing, not knock retard** — it cannot tell you whether the engine knocked, and drive 51 does **not** close the knock gap. Only ECMLink can. |
| **IAT (Intake Air Temp)** | **20–55 °C; heat-soak to ~62 °C is normal** | ⚠ **Informational only — no red** | **ADDED 2026-08-27, REFRESHED 2026-08-28 (Spool, measured — 16,156 samples).** 🔴 **A ">60 °C danger" threshold was WITHDRAWN, and the refresh makes the case far stronger: it now fires on 2,115 of 16,156 samples = 13.1 % of the healthy corpus**, up from 157/10,917 (1.4 %) at withdrawal. **All-time max is now 64 °C** (was 62), set during drive 48 — an 81-minute *deliberate stationary idle* whose bay heat-soak drove IAT to a 61.5 °C average with the car never moving. That is heat soak — expected, benign, and it self-clears with airflow. 🔴 **IAT IS NOT AMBIENT** (US-206 DISPROVEN): runs 14–24 °C high always, cools with airflow, never nears true ambient. **No ambient source exists on this car.** Proven **four** ways now — speed-banded (drive 41: 48.1→40.6 °C by speed band), stop-and-go heat-soak (drives 42→44: 26→45 °C while parked between legs), sustained stationary idle (drive 48: avg 61.5 °C / max 64 °C on a far cooler day), and **inversely under load** (drive 51: IAT *fell* 43→36 °C during the WOT pull as airflow rose, then climbed back). Label it **INTAKE AIR**, never "ambient". ⇒ `drive_summary.ambient_temp_at_start_c` is **MISLABELED**; rename owed. |
| **Engine Load** | **15–25% idle · 30–50% cruise · up to 100% at WOT** | ⚠ **Compound condition only** — high load **with** positive STFT under boost, or with knock | **ADDED 2026-08-27, REFRESHED 2026-08-28 (Spool, measured).** 🔴 **A ">90% sustained = danger" threshold was WITHDRAWN — this car has now reached 100% load on THREE WOT pulls with no thermal or knock distress** (drives 7 and 11 on the prior ECU; **drive 51 on the current ECU, 2026-08-28**). 35 samples exceed 90 % across the corpus. **Load alone is not a danger signal on a turbo engine**; it is the *expected* reading at full throttle. Only meaningful paired with a lean indication or knock. |
| **MAF** | **2–4 g/s idle; scales with RPM/load** | ⚠ **~150 g/s = stock sensor SATURATION, not a fault** | **ADDED 2026-08-27, REFRESHED 2026-08-28 (Spool, measured).** All-time max **158.7 g/s** (Drive 7 WOT) — unchanged; this car **does** reach the stock MAF ceiling at full load. The current-ECU WOT pull (drive 51) peaked at **147.7 g/s — just *below* saturation**, which is why that sample is usable for the VE inference and Drive 7's is not. A MAF pinned ~150+ during a pull is **expected**; treat it as a *measurement limit*, not an engine problem. ✅ Also the basis for the **MAF→VE boost inference** (below) on a car where boost is unreadable. |
| **RPM** | **700–800 idle; redline 7000 (97–99 2G)** | 🔴 >7000 (valve float on stock springs) | **ADDED 2026-08-27, REFRESHED 2026-08-28 (Spool).** ⚠ **Manufacturer spec — still NEVER exercised. All-time max is now 5,896 RPM** (drive 51, 2026-08-28 — the first WOT under the current ECU; supersedes 5,441 from Drive 11, which was the *prior* ECU). Everything above 5,896 remains unmeasured. |
| **Fuel Trims (LTFT / STFT)** | **LTFT ±4 pp of the CURRENT EPOCH's baseline · STFT oscillates, judge only its mean** | 🟡 5-drive median ≥ **4.0 pp** from epoch baseline, sustained ≥3 qualifying drives · 🔴 \|LTFT\| ≥ **10 %** *(convention, NEVER fired here — untested)* | **ADDED 2026-08-31 (Spool, measured — 17,634 LTFT + 17,638 STFT samples, 56 drives).** 🔴 **Resolution is 0.78125 pp** (one raw ECU count, 100/128); the parameter has taken **18 distinct values in this engine's recorded lifetime** — any threshold finer than one count is below the instrument. 🔴 **Noise floor: drive means spread up to 3.72 pp BETWEEN DRIVES ON THE SAME DAY** on a healthy engine (drives 45–51); between-drive SD **1.43 pp**; worst healthy deviation from epoch mean **2.50 pp**. ⇒ **a single-drive delta carries no information and must trigger nothing.** ⚠ **Epoch-scoped, always** — see the trend contract below. |

| **Battery Voltage** | see §Battery Voltage via ELM_VOLTAGE below | ⚠ **Engine-running only** — gate on `RPM > 0` and not within ~3 s of a crank | **QUALIFIER ADDED 2026-08-27 (Spool, measured — 14,221 samples).** The bands are correct but **unconditioned**: the <12.0 V floor **trips on cranking** (13 samples, all-time min 11.0 V), and 1,083 samples (7.6%) sit below the 13.5 V "normal" floor — key-on-engine-off, cranking, and immediate post-start. Without an engine-state gate the alert misgrades normal starting as a charging fault. Healthy reference: drives 42–44 cruised at **14.4 V**; drives 50/51 (2026-08-28) cruised at **13.8 V avg, 14.2 V max**, min 12.3 V (engine state at that sample not established — do not read a cause into it). |

**Important**: Rows marked *(Spool, measured)* are derived from **this car's own capture corpus** (~16,150 samples per parameter through drive 51) and **override community consensus** where they disagree (PM Rule 7). The unmarked rows remain community baselines awaiting real data.

⚠️ **The Session-23 "first-light" fingerprint below is NO LONGER a refinement source** — it was demoted 2026-08-27 (prior ECU, 23-second mid-warmup window, two inverted rows). Do not ground tests or prompts on it.

> **Standing method rule (2026-08-27; sharpened 2026-08-28): test every threshold against the healthy
> corpus before shipping it — and RE-TEST it as the corpus grows.**
>
> **A bad threshold's false-positive rate GROWS with the corpus; it does not average out.** One day's data
> (drives 45–51) moved the withdrawn IAT band from **1.4 % -> 13.1 %** and the timing band from
> **6.4 % -> 9.9 %**. A band that looks marginally acceptable on a small corpus is not marginal — it is
> merely under-sampled.
> Four of the bands above were withdrawn for the same reason — a bare threshold placed *inside* the
> signal's normal operating range. **If it fires on data from a car the owner reports runs fine, it is
> wrong.** This is the same failure as the withdrawn 🟡100 °C coolant band, repeated four more times.

### Boost inference on a car that cannot read boost (MAF→VE) — ADDED 2026-08-27

**Why**: `INTAKE_PRESSURE` **0x0B is probe-dead *and* wired to the MDP/EGR monitor — it reports the wrong quantity.** "Unsupported" understates it: an unsupported PID returns nothing, whereas 0x0B can return a *plausible number that is not manifold pressure*. A real reading needs a **GM 3-bar sensor + ECMLink**.

Until then MAF gives a proxy, because **volumetric efficiency above 100% *is* positive manifold pressure**:

1. Displacement flow at 100% VE: `L/s = displacement_L × (RPM / 2) / 60` → 2.0 L at 3,300 RPM = 55.0 L/s
2. Charge density from IAT: `ρ = P / (R·T)`, R = 287 J/kg·K → at 31 °C, 101.3 kPa: 1.161 g/L
3. Expected mass flow at 100% VE, 1 atm: 55.0 × 1.161 = **63.9 g/s**
4. `VE = MAF_observed ÷ MAF_expected`
5. `boost_gauge ≈ (VE ÷ VE_na − 1) × 14.7 psi`

**Worked example — drive 42 @ 00:02:35Z, the first positive-boost evidence in the corpus:**
MAF 85.0 g/s @ 3,300 RPM, IAT 31 °C, throttle 28%, coolant 88 °C → **VE = 133%** → **~5–7 psi inferred**
(4.9 psi at `VE_na`=100%, 7.5 psi at `VE_na`=88%).

⚠️ **This is an inference with a real ±2 psi band, never a measurement. Do not quote a single psi figure from it.** The band comes from the `VE_na` assumption, which is unmeasured on this engine.

🔴 **STEADY-STATE ONLY — hard limit established 2026-08-28 (drive 51).** The first real WOT pull arrived and **the method could not use it.** MAF 147.69 g/s was sampled at 22:30:57, sitting between RPM samples of **4,148 (:56)** and **5,896 (:58)**:

| MAF 147.69 paired with | VE | inferred boost |
|---|---|---|
| 4,148 RPM | 188 % | **12.9 psi** |
| 5,896 RPM | 132 % | **4.7 psi** |

**Same sample, 8 psi of spread**, decided entirely by which neighbouring row is joined. At **0.44 Hz/PID** this car cannot co-locate MAF and RPM closely enough to infer VE while RPM is moving — and RPM moves **1,750 between adjacent samples** in a pull. => **Apply this method at steady cruise ONLY.**

=> **Planning consequence: more WOT drives will NOT narrow the band.** It needs a **GM 3-bar MAP sensor + ECMLink** — a hardware answer, not an analysis one. Do not schedule drives against it.

The drive-42 sample window was independently verified free of the duplicate-row artifact affecting other seconds in that drive. Full derivation: `$FLEET_SHARE/tuner/knowledge/knowledge.md` §Boost and Turbo.

### LTFT trend contract (US-661) — ADDED 2026-08-31

**Ralph builds against this section, not against the office advisory.** Derivation and the
reproducible SQL: `$FLEET_SHARE/tuner/ltft-trend-card-semantics-advisory.md` and
`$FLEET_SHARE/tuner/scripts/ltft_trend_analysis.sql` (7 sections, verified).

**Verdict: the card is buildable — but NOT as a per-drive trend line.** A naive implementation (mean
LTFT per drive, plot the points, join them) draws a chart that **wanders up to 3.72 pp between drives on
the same day with nothing wrong**. Anyone reading that for drift finds drift, every time.

#### The gate — all three ANDed. A sample failing any of them is not eligible.

```
COOLANT_TEMP        >= 85 °C
FUEL_SYSTEM_STATUS  == 2        (closed loop)
qualifying samples  >= 20       (~100 s of qualifying operation)
```

🔴 **`FUEL_SYSTEM_STATUS` alone is NOT a warm-up gate on this car, and gating on it is the mistake this
section exists to prevent.** The O2 sensor is heated, so the ECU enters closed loop within seconds:
**only 8 samples of "open loop, insufficient temperature" exist in 17,624**, and at 30–40 °C coolant
**65 of 68 buckets already report closed loop**. Loop status is **necessary but not sufficient** —
**coolant is the load-bearing condition.**

⚠ **Encoding derived by correlation, not read off a spec sheet:** `1` = open loop / cold (mean coolant
38.5 °C, n=2) · `2` = **closed loop** (88.9 °C, O2 switching) · `3` = open loop under **load or decel**
(89.0 °C, mean RPM 2515 — a warm state, *not* a temperature state).

#### While the gate is unmet

Publish a **typed absence with a reason** — `"WARMING — NOT YET MEANINGFUL"` — following the `altitude`
and `ambientTempC` pattern. **Never publish a number that failed the gate.**

🔴 **This is the resting state for roughly one drive in four, permanently.** Measured: **5 of the 22
drives since the adaptive reset never accumulate 20 qualifying samples** (drives 37, 42, 54, 55, 56).
That is not a defect and not a temporary condition pending the producer — those drives are too short or
too cold to say anything true.

#### Window and epoch boundaries

- **One point per drive**, from qualifying samples only.
- **Display a rolling 5-drive MEDIAN**, never the raw per-drive line. At SD 1.43 pp a 5-drive median
  resolves to roughly **±0.6 pp**; a single drive resolves to nothing.
- **Never join a line across an epoch boundary.** Break the series and label the break.

| Boundary | Detector | Confidence |
|---|---|---|
| ECU identity change | `(part_number, cal_rom)` changes — already tracked in `vehicle_info` | Certain |
| Adaptive memory reset | LTFT **bit-identical to exactly `0.000`** for a whole drive | Measured |

🔴 **The reset detector must test bit-identity TO ZERO, not zero variance.** Zero variance alone
false-positives: **drive 33 has zero variance at −2.344** (a short drive parked in one load cell) and is
**not** a reset, while drives 35/36 are bit-identical `0.000` and **are**. Bit-identity needs no tuned
threshold and cannot false-positive — the same rule `specs/ssot-design-pattern.md` applies to latched
channels, applied here.

**Epoch baselines, measured** (warm closed-loop samples, hygiene applied):

| Epoch | Drives | n | Grand mean | SD between drives |
|---|---|---|---|---|
| Prior ECU `MD346675` | 3–24 | 15 | **−2.311 %** | 2.161 |
| New ECU `MD326328` | 25–34 | 7 | **+0.545 %** | 0.753 |
| Adaptive reset (flat battery) | 35–36 | — | **0.000 %** | — |
| Post-reset relearn | 37–58 | 17 | **+0.009 %** | **1.429** |

The prior→new ECU step is **2.86 pp** and is a *different ECU*, not a fault. A trend spanning it
compares two engines.

#### Short-term trim

**Do not trend STFT.** It oscillates around its mean by design — a trend line would picture the O2
sensor switching, not the engine. Within-drive SD **0.6–3.2** against LTFT's 0.7–0.9.

**Show instead: total trim = LTFT + STFT, as ONE current value, no trend.** That is what a tuner reads —
the total correction being applied now. Healthy post-reset range: **−1.37 to +4.05**.

⚠ **Filed, not alarmed:** STFT drive means are **positive on every qualifying drive** (+0.50 … +3.90,
mean ≈ +1.3). Well inside safe range; a consistent one-sided bias worth watching once a baseline exists.

#### What this card cannot do, and must not claim

**Usable dynamic range is only ~6 pp** — noise floor ~4, conventional fault line 10. **Fine-grained
drift detection is not available on this car and must not be promised.** What the card *can* do is catch
a real fault: a vacuum leak, failing injector, clogged filter or MAF drift moves LTFT by **10–25 pp**,
not 3.

⚠ **Open caveat — a drive's mean is confounded by how the car was driven.** Within single drives LTFT
varies across RPM bands by up to **3.4 pp** (drive 48) and **2.65 pp** (drive 52), but only **0.30 pp**
(drive 51). Two mechanisms could produce this — **cell indexing** (the 4G63 stores trims per load/RPM
cell and reports the active one) or **within-drive relearn** — and they **could not be separated** with
this data. The implication is identical either way, so it does not block the build; it is a further
argument for the 5-drive median. Resolving it needs **ECMLink** per-cell trim tables, not another drive.

### 🔴 Corpus hygiene — read before computing ANY statistic from `realtime_data` (ADDED 2026-08-28)

**Four** defects in the stored corpus will silently corrupt an aggregate. All are invisible unless excluded explicitly, because every affected value sits *inside* the plausible range.

**1. Always scope `WHERE drive_id IS NOT NULL`.** The unattributed pool contains bench-probe artefacts: `TIMING_ADVANCE` holds repeated **61.0°** samples from 2026-05-20/21, physically impossible on a 4G63 (raw byte `0xFA` through the `A/2 − 64` decode). An unscoped `MAX(TIMING_ADVANCE)` returns **61°** instead of the true **34.5°** — wrong by 27°.

**2. EXCLUDE drives 45 and 46 between `2026-08-28 16:32:30` and `16:35:35` UTC** (2,643 rows). The window logs the car at **0 km/h and 16 km/h at identical timestamps**, and an apparent combined **14.3 rows/s** against an ISO 9141-2 K-line that physically delivers **~7 rows/s** across 16 PIDs.

> ### ⚠ CAUSE CORRECTED 2026-08-31 — the exclusion stands, the reason changed
>
> This item previously read *"two capture pollers ran concurrently."* **That explanation was WITHDRAWN by Spool on 2026-08-31**, and with it the claim that drives 45/46 were an **A-9 Root 1 regression**.
>
> Atlas named a falsifiable condition — concurrent writers sharing one SQLite autoincrement must **interleave** their `source_id` values — and Spool ran it:
>
> ```
> drive 45  source_id 3708564–3709931
> drive 46  source_id 3709998–3711272
> 46-rows below max(45) = 0      45-rows above min(46) = 0
> ```
>
> **Perfectly disjoint, a 66-row gap, zero crossings in either direction.** Two concurrent pollers cannot produce that.
>
> 🔴 **The real cause is A-23 — the Pi 5 RTC has no charged backup cell, so every boot starts at 1970 and NTP repairs it only where a network is reachable. In the car there is no network and nothing repairs it.** The timestamps are wrong; the rows are not duplicated. **A-9 Root 1 stays CLOSED — do not groom a refix.**
>
> ⚠ **This also retires the "three occurrences" framing below.** Drives **23/24** and **28/29** were counted as the same defect on the strength of the same rows/s reasoning, which is exactly the reasoning a bad clock defeats. Their true cause is **unestablished**; they are not evidence for a concurrency defect.

> ### 🔴 The `>8 rows/s` tripwire must NOT ship unpaired
>
> A proposed invariant — *"a recorded row-rate above ~8 rows/s is prima facie fabrication, because the bus cannot deliver it"* — was attractive because it looked like a physical bound needing no tuned threshold.
>
> **It is not usable alone.** Row-rate is computed as `rows ÷ elapsed`, and **A-23 corrupts the denominator.** A wrong clock and a genuine double-read produce the same reading, so the tripwire **cannot discriminate between the two failures it exists to separate** — and the corpus's only three "occurrences" are now believed to be clock faults, meaning the tripwire would have fired on all of them for the wrong reason.
>
> ⇒ **Ship it only paired with a `clockSynced` flag on drive segments** (Atlas; independently caught by Marcus). Unpaired, it is a check that cannot do the job it is cited for.

**Why a tuning spec carries a pipeline caveat:** every threshold in the table above is validated against this corpus. **Fabricated samples silently widen the apparent normal band of every parameter they touch**, and the corruption is undetectable from the values alone.

**3. Cross-check row-rate against duration before trusting a drive.** Healthy is **~420–440 rows/min** across 16 PIDs. ⚠ `data_quality` is **not** a quality signal — it defaults to `full` pre-batch (US-563) *and* stays `full` post-batch with a gap already detected (the inert gap guard, filed 2026-08-27).

**4. Establish that the capture is FINISHED before concluding anything from it.** Compare `MAX(synced_at)` against the server clock **and** against the drive's last timestamp. A drive whose sync trails the wall clock is **in flight**, and a partial capture reads exactly like a short one. This is not hypothetical: on 2026-08-30 a drive was graded mid-sync and a wrong conclusion published; it subsequently grew **6,998 → 11,054 rows** and the car had been travelling at 60 km/h throughout the window reported as stationary.

**5. ⚠ Query trap — `timestamp` and `synced_at` are UTC, but MariaDB `NOW()` on `obd2db` returns CDT.** Any `WHERE timestamp > NOW() - INTERVAL ...` is off by five hours. Check `@@system_time_zone` before trusting a recency filter; this has already produced one phantom clock fault.

### Active DTC — P0443 (as of 2026-08-27)

**P0443 — Evaporative Emission System Purge Control Valve Circuit. MIL is LIT.** Stored on every drive since at least 2026-08-20 (drive 41); `DTC_COUNT`=1, `MIL_ON`=1 across drives 42/43/44.

**Verdict: no engine risk, and it does NOT distort tuning data — assessed, not assumed.** A purge valve stuck *open* dumps unmetered fuel vapor into the intake and drags LTFT **negative** on a MAF-based car. **No negative excursion is present** ⇒ the valve is not dumping vapour ⇒ the benign failure direction.

> ⚠ **INFERENCE WEAKENED 2026-08-31 (Spool, self-correction).** This read *"LTFT is drifting **positive** ⇒ the solenoid is **not flowing** ⇒ open circuit / stuck closed."* **Two defects.** (a) Trims can only rule the stuck-*open* case **out** — a non-flowing valve and a never-commanded valve are **identical** in trim data, so the electrical state does not follow. (b) *"Drifting positive"* was thin: across drives 37–58 the LTFT mean swings **−2.60 → +2.17 → −0.80**, and of the three drives it was read from, **two are negative**. **The conclusion survives on "no negative excursion"; the argument that supported it did not.**

**Since corrected (2026-08-31):** the fault is **INTERMITTENT** (clean drive cycles before onset, and one clean cycle after a code clear), which points at a **connector or wiring** fault rather than the solenoid; and the **2026-05-22 ECU swap is EXONERATED**. 🔴 **Never let a shop replace the PCM** — `MD326328` is a 1997 board *because* 1998 boards cannot be ECMLink-flashed. Full diagnosis: `$FLEET_SHARE/tuner/cards/dtc-p0443-evap-purge-diagnosis.md`.

Consequences are emissions-only: the charcoal canister does not purge, readiness monitors will not complete, and the car will fail an emissions test. **Do not treat a lit MIL from this code as a capture-validity or engine-health signal.** Repair timing is the CIO's call.

**Pi-side power-management** (data-collection device, separate from vehicle engine ranges): Pi 5 UPS HAT (MAX17048-managed LiPo cell) — buck-converter dropout knee at VCELL ≈ 3.30 V; ~16-min runtime under typical load (Drain Test 7, 2026-05-02 empirical). Authoritative writeup with full empirical baseline + operational implications: `$FLEET_SHARE/tuner/knowledge/ups-drain-characteristics.md` (split out of `knowledge.md` on 2026-09-01; the old section anchor no longer resolves).

---

## Real Vehicle Data

Authoritative empirical observations from this specific Eclipse. These values win over community baselines when they disagree (PM Rule 7 — real vehicle data beats community consensus). Append-only, timestamped.

### PID Support — Empirically Confirmed (Session 23, 2026-04-19)

**Confirmed SUPPORTED** on this 2G ECU (responded correctly under python-obd query):

| PID | Name | Authority |
|-----|------|-----------|
| 0x04 | Calculated Engine Load | Session 23 live capture |
| 0x05 | Engine Coolant Temperature | Session 23 live capture |
| 0x06 | Short-Term Fuel Trim (B1) | Session 23 live capture |
| 0x07 | Long-Term Fuel Trim (B1) | Session 23 live capture |
| 0x0C | Engine RPM | Session 23 live capture |
| 0x0D | Vehicle Speed | Session 23 live capture |
| 0x0E | Timing Advance | Session 23 live capture |
| 0x0F | Intake Air Temperature | Session 23 live capture |
| 0x10 | MAF Air Flow Rate | Session 23 live capture |
| 0x11 | Throttle Position | Session 23 live capture |
| 0x14 | O2 Sensor B1S1 (upstream narrowband) | Session 23 live capture |
| 0x42 | Control Module Voltage | **Drive 33 live capture (2026-08-20)** — 76 rows / 29 distinct / 12.975–14.451 V. Supersedes the Session-23 "unsupported" verdict. |
| 0x1F | Run Time Since Engine Start | Drive 33 live capture — 75 rows, 75 distinct, monotonic 53→196 s |

**Live capture set = 16 parameters** (drives 39/40/41, 24,342 rows, 2026-08-20). The 11 rows above are the
Session-23 subset, not the ceiling. **A PID is "supported" only when it appears in a live capture** — the
config poll list proves nothing (this is how both the 0x42 and the 0x33 errors were made). Full 16-param
table with per-PID row counts: `$FLEET_SHARE/tuner/knowledge/knowledge.md` §"OBD-II on the 2G DSM".


**Confirmed UNSUPPORTED** on this 2G ECU (did not respond or returned no-data):

| PID | Name | Workaround |
|-----|------|-----------|
| 0x0A | Fuel Pressure | None via OBD-II. ECMLink or aftermarket sensor in future phases. |
| 0x0B | Intake Manifold Pressure (MAP) | None via OBD-II. Aftermarket 3-bar MAP (GM) or ECMLink in Phase 2. |
| _(0x42 moved — see correction below)_ | | |

> **⚠️ CORRECTION 2026-08-20 (Spool, Session 37): PID `0x42` CONTROL_MODULE_VOLTAGE IS LIVE on this ECU.**
> The Session-23 "confirmed unsupported" verdict above is **WRONG** and is retained only for the diagnostic trail.
> Drive 33 holds **76 real samples across 29 distinct values, 12.975–14.451 V** — a textbook charging curve, not a
> stuck or defaulted value. The `ATRV` path (below) still works and remains in production; the *claim of
> unsupported* is what was false. Do not re-derive "0x42 is dead" from the Session-23 row.
>
> **`0x33` BAROMETRIC remains genuinely UNRESOLVED** — 75 real rows exist, all on drive 33, all exactly 99.0 kPa.
> Flatness is *expected* at 1 kPa resolution over 143 s, so it neither proves nor disproves liveness. Settle with
> `offices/tuner/scripts/probe_obd_capabilities.sh` on a bench session **with capture stopped** (single serial
> channel). Until then: **do not render baro, and do not derive altitude from it.**
>
> **Method rule that produced both errors:** a config poll list is NOT a capability list. Only the live capture
> set proves a PID returns. Probe, or say unknown.

### Battery Voltage — NOT a PID on this car

*(Heading retained for the link trail. **PID 0x42 is LIVE** — see the correction above.)* The battery voltage source for the primary display and all voltage alerts remains the **ELM327 adapter's `ATRV` command** — by choice, because it is adapter-local and free of the K-line budget (accessed in python-obd as `obd.commands.ELM_VOLTAGE`). This is an adapter function, not an OBD-II Mode 01 PID — it measures voltage directly at the OBD-II port's pin 16 and is independent of ECU bandwidth. All code and tests that reference battery voltage must use this path.

### Battery Voltage via ELM_VOLTAGE (2G workaround) — Thresholds

Sprint 14 US-199 promoted `BATTERY_V` to a first-class parameter_name polled from ELM_VOLTAGE (tier 3, ~0.1 Hz). Thresholds apply to the *battery voltage as seen at the OBD-II connector while the ECU is powered*; they match Spool's Phase 1 tuning spec (`offices/pm/inbox/2026-04-10-from-spool-system-tuning-specifications.md` §Battery Voltage, locked source of truth per PM Rule 7).

| Level | Range | Action |
|-------|-------|--------|
| Normal | 13.5-14.5V (engine running) | Charging system healthy |
| Caution | 12.5-13.5V OR 14.5-14.8V | Low = weak alternator. High = voltage regulator starting to fail. |
| Danger | <12.0V OR >15.0V | **Low = charging failure, engine may stall. High = regulator failed, will cook battery and electronics.** |

Config path: `pi.tieredThresholds.batteryVoltage` in `config.json`. Consumers must read from config — do not hard-code thresholds. `BATTERY_V` rows carry `unit='V'` and are independent of the K-line bandwidth envelope (ELM327 pin-16 read is an adapter-local operation).

### Real-World K-Line Throughput (Session 23)

| Metric | Theoretical (from research) | Measured (Session 23) |
|--------|----------------------------|----------------------|
| Per-PID update rate | ~0.5-1 Hz per PID | **~0.6 Hz per PID** (6.4 rows/sec across 11 PIDs) |
| Total PID throughput | ~6-8 PIDs/sec | **~6.4 rows/sec** |
| Per-request round trip | 120-200 ms | Consistent with measured throughput |

**Theoretical and empirical match.** Polling strategy designed against theoretical numbers is sound. Adding the Sprint 14 PIDs (fuel system status, runtime, barometric, MIL) will proportionally reduce per-PID rate on the bus — account for this in tiered polling design.

### K-Line Cold Protocol-Detection Time (Drive 6 / V0.27.1, 2026-05-08)

ISO 9141-2 K-line at 10,400 bps requires the ELM327 / OBDLink LX to negotiate the protocol on a fresh connection (`ATZ` reset → `ATE0` echo-off → `ATSP0` auto-detect → wakeup pattern → first protocol probe). On the 1998 4G63 ECU this is **NOT instantaneous** — the protocol-detect handshake walks through the ISO 9141-2 / KWP2000 / J1850 candidate list before locking onto K-line.

| Measurement | Value |
|-------------|-------|
| Empirical cold-connect time (engine-on, healthy adapter) | **~6-10 seconds** |
| Sprint 27 morning test (pre-V0.27.1 successful initial connect) | 8 seconds |
| US-301 original heartbeat wall-clock cap (TOO TIGHT) | 5.0 seconds — would have timed out even on a healthy connection |
| V0.27.1 corrected heartbeat wall-clock cap | 30.0 seconds (aligned with `_initializeConnection`'s budget) |

**Operational rules**:
- **Any** wall-clock cap on a fresh connect attempt against a cold (just-powered) OBDLink LX must be **≥ 10 seconds** to allow the K-line negotiation envelope to close on a healthy ECU. 5 seconds is below the working envelope and produces false negatives indistinguishable from a real failure.
- Once connected, per-PID query times settle into the ~120-200 ms round-trip envelope (Session 23 measurement above) — the cold-detect cost is amortized over the session.
- The cost only re-applies on full disconnect→reconnect (e.g. engine cycle or BT flap recovery via `BtResilienceMixin.handleCaptureError`).

**Why this matters for design**: every story that pins a connect-side timeout / heartbeat-cap / probe-wait must check this number first. Spool's US-301 spec ("single attempt + short timeout (5s)") was a spec error precisely because it didn't account for the K-line envelope; it was caught at the engine-on test #2 IRL drill rather than in any tests. The number is now a checked-in spec to prevent the same class of error in future stories.

**Source**: 2026-05-08 Drive 6 IRL drill journal — first connect_success at 19:41:43 CDT, ~8s after the leaked-daemon's first attempt against the just-powered OBDLink. V0.27.1 hotfix RELEASE_VERSION + `offices/ralph/progress.txt` Session 180 entry.

### Warm-Idle Fingerprint (Session 23) — 🔴 DEMOTED, historical record only

> **DEMOTED 2026-08-27 (Spool). This was labelled "Authoritative Baseline" and marked for use in
> "range-check tests, sim fixture validation, regression tests, and AI prompt grounding."**
> **Do not ground anything on it.** It is a **23-second, prior-ECU, mid-warmup snapshot**, and two of
> its rows were actively inverted. Retained as a dated observation and link-trail anchor.
>
> Three reasons it cannot carry that weight:
> 1. **Wrong ECU.** Captured 2026-04-19 on **MD346675**, replaced 2026-05-22. The current car runs
>    **MD326328** with an ECMLink tune. Fuel-trim and timing behaviour differ by design.
> 2. **Not steady-state.** 23 seconds. No cold-start, no warmup curve, no load.
> 3. **Two rows were backwards** — corrected inline below.

Observed on this specific vehicle, 2026-04-19, ~23 seconds across 2 windows. **Historical record for the PRIOR ECU (MD346675) only.**

| Parameter | Observed | Interpretation Anchor |
|-----------|----------|----------------------|
| RPM (warm idle) | 761–852 rpm (±45 around 793) | Healthy idle stability. >±75 variation = IAC/vacuum/coil investigation. |
| LTFT | **0.00% flat** | 🔴 **CORRECTED 2026-08-27 — the old reading, "Tune is dialed. Any drift from 0.00% = investigate", was BACKWARDS.** LTFT pinned at *exactly* 0.00% with **zero variance** is the signature of **RESET ECU ADAPTIVE MEMORY** (battery disconnect, power interruption, code clear) — not a good tune. The current ECU's natural LTFT is **−1…−3%**. Proven 2026-07-31: the battery went flat from disuse, drives 35/36 logged LTFT exactly 0.00 across all 232 samples, then relearned to ≈−2.5% (drives 37/38) and settled near −1.0% (drives 42/43). **A test or AI prompt grounded on the old line flags every healthy drive as faulty and treats the one genuinely anomalous state as the target.** Rule: 0.00% flat ⇒ investigate the ECU's **power history**, not the fuel system. |
| STFT | −0.78% to +1.56% (avg +0.06%) | Normal closed-loop noise *for this 23 s window*. ⚠ Real-world STFT swings ±10% on throttle transients (drives 42–44). Do not band on this narrow sample. |
| O2 B1S1 | 0–0.82V switching, avg 0.46V | Healthy narrowband, stoich-crossing. |
| MAF (warm idle) | 3.49–3.68 g/s | Plausible idle airflow for 2.0L/4-cyl. Consistent with drives 42–44 (3.2–3.5 g/s). |
| Engine Load (warm idle) | 19.22–20.78% | Normal warm idle. |
| Throttle Position (closed) | 0.78% flat | Clean TPS zero offset. |
| Timing Advance (warm idle) | 5–9° BTDC (avg 7°) | ✅ **CONFIRMED as this car's real idle timing** (drive 42 idle: 6.5–10°). The "conservative vs community 10–15°" note stands, but the conclusion is the **opposite** of what it implies: the **community band is wrong for this car**, not the car. A 10–15° "normal" grades this engine's healthy idle as below-normal. See Timing Advance in Alert Thresholds. |
| Coolant (warm-ish idle) | 73–74°C (163–165°F) flat | 🔴 **NOT a warm-idle baseline — RECLASSIFIED Session 6 (2026-04-20) as a MID-WARMUP SNAPSHOT.** The 23 s window ended before thermostat-open temp. The thermostat was subsequently confirmed **healthy** at 15-min sustained idle (I-016 closed benign). This car's real steady-state is **88–90°C**, fan-cycle ceiling **101.0°C**. That correction was made in `tuner/knowledge/knowledge.md` four months ago and never reached this file. |
| IAT (short idle, cold ambient) | 14°C (57°F) flat | ⚠ **Do NOT generalise to "IAT ≈ ambient".** It matched ambient *here* only because the engine was barely warm. **IAT is NOT ambient on this car** (US-206 DISPROVEN) — it runs 14–24°C high and cools with airflow. See IAT in Alert Thresholds. |

**Data-capture context**: Engine-on wall-clock ~10 min; real OBD-connected data-capture time ~23 sec across 2 windows due to TD-023 connection churn. Captured window was steady-state warm (no cold-start, no warmup curve, no load). Pipeline integrity verified end-to-end Pi SQLite → chi-srv-01 MariaDB byte-for-byte.

**Sources for this section**:
- Raw data: `chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db` (synced to `chi-srv-01:obd2db`)
- Review note: `offices/pm/inbox/2026-04-19-from-spool-real-data-review.md`
- Deep interpretation: `$FLEET_SHARE/tuner/knowledge/knowledge.md` section "This Car's Empirical Baseline"

### Measured Eclipse 4G63 Idle Values (2026-04-19) — checked-in regression fixture

US-197 snapshots the Session 23 capture into a committed, regenerable regression fixture so these measurements are reproducible without re-driving the car:

| Asset | Path | Purpose |
|-------|------|---------|
| Fixture DB | `data/regression/pi-inputs/eclipse_idle.db` | 149 real rows, 11 PIDs, post-US-195/US-200 schema, `data_source='real'`, `drive_id=NULL` |
| Metadata | `data/regression/pi-inputs/eclipse_idle.metadata.json` | Drive context, PID list, capture window, tune context |
| Range tests | `tests/pi/obdii/test_live_idle_ranges.py` | Warm-idle tolerance bands (Spool-approved) assert on every CI run |
| Replay-shape tests | `tests/pi/regression/test_eclipse_idle_replay.py` | Determinism + replay-harness contract |
| Regenerate | `scripts/export_regression_fixture.sh` | SCPs live Pi db → applies US-195/US-200 migrations → writes fixture + metadata |
| Live re-verify | `scripts/verify_live_idle.sh` | SSH-driven in-vehicle capture + threshold check (CIO-runnable) |

Per-parameter measured values (Session 23 raw, authoritative):

| Parameter | Samples | Min | Max | Avg |
|-----------|---------|------|------|------|
| RPM | 15 | 761.5 | 851.5 | 793.1 |
| COOLANT_TEMP (°C) | 14 | 73.0 | 74.0 | 73.7 |
| LONG_FUEL_TRIM_1 (%) | 13 | 0.00 | 0.00 | 0.00 |
| SHORT_FUEL_TRIM_1 (%) | 13 | -0.78 | +1.56 | +0.06 |
| O2_B1S1 (V) | 13 | 0.000 | 0.820 | 0.458 |
| TIMING_ADVANCE (°BTDC) | 13 | 5.0 | 9.0 | 7.1 |
| MAF (g/s) | 13 | 3.49 | 3.68 | 3.57 |

These anchor future range-check tests and Spool AI grounding. Drift from these bands on a future capture is a signal, not a failure — update this table with new empirical values (append-only per Usage Rule #3) and investigate the delta.

---

## 2G DSM DTC Behavior (US-204)

### Confirmed supported modes

| Mode | python-obd command | 2G DSM (1998 Eclipse GST) | Notes |
|------|--------------------|---------------------------|-------|
| 03 | `GET_DTC` | ✅ supported | Stored DTCs. Universal OBD-II. |
| 07 | `GET_CURRENT_DTC` | ⚠ probe-first | Pending DTCs. May return null on 2G — pre-OBD2-full-compliance. The Pi `DtcClient.readPendingDtcs` returns a `Mode07ProbeResult` so callers cache the verdict per connection. |

When the Mode 07 probe lands `unsupported`, document it here per Usage Rule
#3. Until that empirical evidence is captured against the live Eclipse,
the production code treats it as a runtime probe — no assumption baked in.

### Unknown DTC descriptions

`python-obd`'s `DTC_MAP` covers the standard SAE J2012 set
(`P0XXX`, `B0XXX`, `C0XXX`, `U0XXX`). Mitsubishi-specific codes
(`P1XXX`) lack mapped descriptions and land in `dtc_log.description`
as the empty string per US-204 Invariant #6 (never fabricate). When
real DSM codes are captured, append the code → description mapping
under this section as the canonical source-of-truth — the schema does
NOT auto-update from this document.

| DTC | Description | Provenance |
|-----|-------------|------------|
| _(none captured yet)_ | _(populate after first MIL event on the live car)_ | _(source link required per Usage Rule #1)_ |

---

## Ambient Temperature Proxy via IAT at Key-On (US-206) — 🔴 DISPROVEN 2026-08-20

> **🔴 THIS SECTION'S PREMISE IS DEAD. IAT IS NOT AMBIENT ON THIS CAR — NOT EVEN AT KEY-ON.**
> Spool, Session 37, moving-vehicle proof (drive 41): IAT ran **48.1 → 40.6 °C banded by road speed** — it
> *cools with airflow* and **never approaches the 24–27 °C real ambient**, sitting **14–24 °C high at all times**.
> The sensor is radiant engine-bay heat-soak dominated. The "cold-soaked intake ≈ ambient" assumption below
> does not survive contact with the data.
>
> **Consequences (binding):**
> - **Never use IAT as ambient anywhere** — not for display, not for IAT-caution interpretation, not for
>   density/grade correction, not for AI grounding.
> - **`drive_summary.ambient_temp_at_start_c` is MISLABELED.** Drive 41 logged **47 °C (117 °F)** into that
>   column as "ambient" on a Chicago August afternoon. Rename owed (filed to Marcus 2026-08-20). Any analysis
>   keyed on that column is reading a heat-soaked intake, not weather.
> - **There is no ambient source on this vehicle.** PID 0x46 is unsupported and no external sensor is fitted.
>   The honest-instrument answer is **"ambient unknown"** — the alternative is fabrication, so nothing here
>   gets a substitute proxy.
> - **Display rule:** label the value **INTAKE AIR**, informational only, no red tier.
>
> The `fromState` capture rule below is retained **only** as the record of what US-206 shipped. It is not a
> recommendation and must not be cited as one.

### Superseded rationale (record only — do not implement)

The 2G Eclipse does not support PID 0x46 (ambient air temperature). Spool's Phase 1 spec references ambient for IAT-caution interpretation (e.g., "IAT > 131°F = caution IF ambient was cold; 90°F ambient means heat-soaked IAT > 130°F is less alarming"). The workaround is to capture IAT (PID 0x0F) at drive-start and store it as `drive_summary.ambient_temp_at_start_c` — but only when the engine was genuinely off beforehand.

**Cold-start capture rule (US-206, Spool Priority 7)**:

* `fromState ∈ {UNKNOWN, KEY_OFF}` → cold-soaked intake ≈ ambient. Capture IAT as `ambient_temp_at_start_c`.
* `fromState = RUNNING` (warm restart; stall-and-go without hitting the 30s KEY_OFF debounce) → intake is heat-soaked from the hot engine bay. **Store NULL, not the IAT value.** Analytics treat NULL as "ambient unknown" and skip any IAT-caution interpretation that relies on ambient.

**Operational caveat**: on a cold morning with a cold-soaked engine, IAT-at-key-on is a solid ambient proxy. On a 90°F day after a 10-minute shutdown the engine bay is still holding heat — "cold-start" in the state-machine sense (KEY_OFF transition) does NOT guarantee ambient accuracy. Spool's downstream analytics should flag `ambient_temp_at_start_c > 40°C` as UNRELIABLE_HEATSOAK even when fromState was cold-qualifying; the capture-time rule is the first filter, not the last.

**Source**: Spool note `offices/pm/inbox/2026-04-19-from-spool-data-collection-gaps.md` Priority 7. PM Rule 7: cold-start rule is an [EXACT: fromState ∈ {UNKNOWN, KEY_OFF}] spec; the UNRELIABLE_HEATSOAK downstream flag is Spool's call and out of scope for US-206.

---

## Magnetic Heading (`headingDeg`) — REAL since US-565, but UNCALIBRATED

> **Status 2026-08-28 (US-571).** This entry supersedes the 2026-08-20
> fabricated-compass fact, which was correct when written and is no longer the
> channel's current state. Both halves matter and neither survives alone: the
> acquisition defect is **fixed**, and the bearing is **still uncalibrated**.

### What US-565 fixed — acquisition

The ICM-20948's AK09916 magnetometer is no longer read through the ICM's
auxiliary-I²C shadow. It is read as its own I²C device at **0x0C** on the primary
bus, with the aux master disabled and `INT_PIN_CFG.BYPASS_EN` set. The burst runs
**ST1..ST2 inclusive**: the AK09916 loads a new measurement only once the previous
one is released by a read extending through ST2, so a "tidier" 6-byte data-only
read silently re-creates the original defect. That extent is pinned by test.

**The channel varies now**, measured on the shipping code path (chi-eclipse-01,
2026-08-21, 90 s stationary on the bench):

```
mag_x       :    27 distinct / 2,108 samples, 1,942 changes, DRDY set 2,108/2,108
mag vectors :   350 distinct 3-vectors / 500 samples, longest bit-identical run 2
old path    :     1 distinct / 20,000 samples        <- same chip, same day
```

Accel and gyro were never affected and are untouched — still read from the ICM at
0x69, and bypass does not disturb them.

### What is still NOT true — the bearing is uncalibrated

From the same bench run:

```
mag = (-59.25, 67.95, -0.3) uT   ->   |B| ~= 90.2 uT
Earth's total field at this latitude ~= 52 uT
```

The excess is a **hard-iron offset roughly the size of the field being measured** —
expected, with the sensor sitting beside a display, a buck converter and vehicle
steel. An offset that size does not shift a bearing by a few degrees; it can swing
it by **tens of degrees**, and because the error is direction-dependent it does
**not average out**. **No hard/soft-iron calibration has been performed** — owed,
tracked as TD-087 → US-616.

Two further limits, both by contract rather than by defect:

* **Magnetic, not true.** No declination correction is applied; `headingDeg` is a
  magnetic bearing (Atlas Q-A contract).
* **Rendered to more precision than it has.** `imu_state_bridge` publishes
  `headingDeg` rounded to **0.1°** (`_HEADING_DECIMALS = 1`) and the card renders
  it that way. A tenth of a degree is a precision claim this measurement cannot
  support: a bearing accurate to "roughly north-east" should not read `43.7`.

**Trust the direction as an indication, not as an instrument.** Do not use
`headingDeg` where an accurate absolute bearing is required until calibration
lands.

### Historical — drives ≤ 41 (this half of the old fact is STILL TRUE)

Drives **≤ 41** were captured before the fix and carry a fabricated bearing.
Discard `headingDeg`, the compass tape and the direction ribbon for all of them.
Drive 40 alone held 29,148 samples at **1 distinct** magnetometer value while
accel showed 1,292 distinct and `gyro_z` reached 7.5 rad/s — the car was turning
and the compass was not. Nothing retroactively repairs those drives. The fixed
acquisition reached the car with the **V0.29.30** Pi deploy, verified 2026-08-23.

### Two things this entry does NOT license

1. **Do not re-suppress `headingDeg`.** It is a real reading now, and hiding a real
   measurement is the opposite failure to the one US-565 fixed. The open question
   is how precisely to state the bearing, not whether to state it (TD-087).
2. **Do not relax the bit-identity plausibility gate** on the magnetometer channel.
   That gate is what would catch a silent return of the 2026-08-20 defect, and it
   is why a channel that froze again would go typed-NA instead of onto the glass.

**Provenance:** `src/pi/sensors/ak09916_bypass.py` module header (the full
measurement trail) · `tests/fixtures/mag_bypass_90s_2026-08-21.csv` +
`tests/fixtures/imu_stationary_90s_2026-08-21.csv` (both captures, each with its
own provenance header) · `offices/ralph/scripts/characterize_magnetometer.py`
(reproducible probe) · TD-087 (the calibration debt) ·
`offices/architect/findings/2026-08-20-magnetometer-latched-heading-fabricated.md`
(the original defect — superseded as current state, retained as the record).

---

## IMU boot state — TWO discrete states, and the accel SCALE differs between them (US-783 / A-34)

**Measured by Spool 2026-09-21 against `edr_imu_sample`, server tier.**

The ICM-20948 latches into one of two states at every power-on. The gyro half is already
documented in `src/pi/sensors/gyro_recovery.py` (A-34). **What is new here: the ACCELEROMETER
SCALE differs between the two states by ~1.9 percentage points**, and nothing in the schema
records which state produced a given row.

| At rest, parked (`drive_id IS NULL`) | FAULTED | HEALTHY |
|---|---|---|
| `gyro_x` mean (**rad/s**) | +0.2436 | −0.0008 |
| `gyro_y` mean (**rad/s**) | −0.5222 (≈ −29.9 °/s) | +0.0130 (≈ +0.745 °/s) |
| `gyro_z` mean (**rad/s**) | −0.3211 | +0.0039 |
| **‖a‖ mean (m/s²)** | **9.79492** | **9.98255** |
| ‖a‖ sample SD (m/s²) | 0.13460 | 0.03598 |
| n | 379,527 | 5,706,847 |

⚠️ **UNIT CORRECTED 2026-09-21 (Spool).** This table first went out labelled °/s, and so did the
office's S44 boot-state finding. **The column is rad/s** — `UNIT_GYRO = "rad/s"`
(`sensor_reader.py:130`) and `-- rad/s` (`sensor_schema.py:56`). 🟢 **Fact-checked to the source:**
the installed driver, `adafruit_icm20x` 2.1.10, documents `gyro` as *"radians / second"* and
converts at line 313 by `_ICM20X_RAD_PER_DEG = 0.017453293`. ⚠️ **The vendor's own breakout guide
is internally inconsistent** — its prose says *"gyro … in degrees/sec"* while its example code prints
`"rads/s"`. **The driver source is the authority; the guide's prose is wrong.** Anyone checking only
the PDF would re-introduce this error. Swept the same session:
`facts/imu-and-motion.md` and shared `MEMORY.md`, both with verified backups. **It is the SPEED
km/h-as-mph phantom's shape — pin the unit before the magnitude — and it matters here for a reason
that only appears once the unit is right** (next section).

🔴 **The gyro fault biases ALL THREE axes, not only `gyro_y`.** The office record named `gyro_y`
alone; `gyro_x` (+0.24) and `gyro_z` (−0.32) are also displaced. Classifying a boot by `gyro_y`
alone still works — the gap between −0.10 and −0.25 is empty — but a consumer correcting bias must
correct three axes.

⚠️ **The state split is NOT a mount or temperature artefact.** Three days carry both states, and
within each day — same mount, same ambient — HEALTHY reads higher every time:

    2026-09-11   FAULTED 9.89104 (n= 86,242)   HEALTHY 10.00925 (n=  1,249)   +0.118
    2026-09-15   FAULTED 9.84102 (n= 76,513)   HEALTHY  9.98916 (n= 53,696)   +0.148
    2026-09-16   FAULTED 9.79748 (n= 62,131)   HEALTHY  9.98706 (n=318,759)   +0.190

**‖a‖ is orientation-invariant, so a remount cannot move it.** Three same-day pairs in a consistent
direction is the control.

🟢 **The A-34 recovery works and is deployed.** Journal, 2026-09-08 → 09-21: **10 latched faults
detected at startup, 10 cleared by the `PWR_MGMT_2` power cycle, 0 failures, 0 starts where
recovery was skipped.** ⚠️ **But the fault is present on 100 % of observed starts** — the recovery
is a working workaround, not a repair — and **its outcome is written only to the journal, never to
the database.** ⇒ A consumer cannot tell from the data which state a row came from.

**`void if`** — the IMU is replaced, the A-34 recovery is removed or changed, or any boot is
observed publishing rows after recovery failed.

---

## THREE pitch defects, not one — and the grade error on a parked car is the one nothing fixes

**Spool, 2026-09-21. Once the gyro unit is pinned to rad/s, three findings recorded separately
turn out to be one quantity.**

    HEALTHY residual gyro_y bias      0.01304 rad/s  =  0.747 deg/s     (n = 5,332,340, parked)
    x DEFAULT_PITCH_TAU_S             5.0 s
    => predicted pitch error          3.74 deg
    S42 finding (office, 2026-09-01)  0.7145 deg/s bias -> 3.57 deg predicted, 3.81 deg observed
    live, parked, 2026-09-22 03:15Z   pitchDeg -2.91 .. -4.02 deg;  gradePct -5.1 .. -7.0 %
                                      tan(3.3 deg) = 5.8 %  -- consistent

🔴 **The grade that moves on a stationary car is the HEALTHY-state residual gyro bias, integrated
through the 5 s pitch time constant and never cancelled.** It is **not** the latch.

⇒ **The three mechanisms, kept separate because each has a different fix:**

| # | Mechanism | Size | Status |
|---|---|---|---|
| 1 | **Latched gyro** (FAULTED, 0.2457–0.52 rad/s) → runaway to ~70° | catastrophic | 🟢 **FIXED by A-34 recovery (US-778)** — 10/10 cleared since 09-08 |
| 2 | **Guard on the runaway** (US-749 / US-750) — withhold pitch/grade when implausible | defence | ✅ correct; now defends against a *failed* recovery |
| 3 | **HEALTHY residual bias** 0.013 rad/s → 3.7° → ~6 % phantom grade | chronic | 🔴 **UNFIXED — and neither US-749 nor US-778 addresses it** |

🔴 **Fixing #1 cannot fix #3.** The recovery takes the gyro from FAULTED to HEALTHY; HEALTHY still
carries 0.747 °/s of bias. **ZUPT is the mechanism meant to cancel it, and ZUPT needs ≥ 5 confirmed
stops — `stopCount = 0` after hours parked, because a parked car never accumulates stops.**

🟢 **Datasheet check (DS-000189 Table 1): the bias is ORDINARY, not a fault.** Initial zero-rate
offset tolerance is **±5 dps**; our 0.747 °/s is **15 % of it.** ⇒ **#3 is not a defective part —
it is the zero-rate offset every MEMS gyro has and every fusion must subtract.** ZRO also drifts
**±0.05 dps/°C**, so a 20 °C swing can move it ~1 °/s — **larger than the offset itself**, which is
a second reason the estimate must be re-taken at every boot rather than stored as a constant.

### 🟢 The input to fix #3 is ALREADY COMPUTED AT EVERY BOOT, and thrown away

`gyro_recovery.gyroLooksFaulted()` takes **20 stationary samples at startup** and computes
**`axisMeans` on all three axes** — which is a per-boot gyro bias estimate. It compares the largest
to 0.10 rad/s to classify the state, and **discards the means.** The post-recovery check samples
again, on a HEALTHY gyro, and discards those too.

🔴 **Atlas's precise reading (verified in code, 2026-09-21): `axisMeans` is not merely discarded —
it is COLLAPSED TO A BOOLEAN on the next line** (`gyro_recovery.py:103-104`). A three-axis bias
estimate becomes one bit, and the bit is all that survives.

**RULED (Atlas, 2026-09-21): #3 is TWO obligations with different gates.**

**(a) 🔴 LAND IT — a compliance duty, independent of any fusion change.** `ssot-design-pattern.md`
§A′ (CIO 2026-08-29): *"if we read, touch, or HAVE ACCESS TO any data we must land it."* **Land the
PRE-recovery and POST-recovery `axisMeans` separately** — the pair is the only record of what
recovery did to the bias — **stamped with SAMPLE time, not write time**, per the CIO's standing
rule A″ issued 2026-09-21 (*event time is the record for ALL data*; `ARCH-043`). **This also closes
the US-778 gap below** — the recovery outcome is otherwise journal-only.

**(b) ⚠️ USE IT as pitch fusion's initial bias — accepted in principle, GATED on fixing the
sampler first.** An estimate whose error bar cannot be stated must not be injected as a correction.
Two further conditions:
1. **ONLY the POST-recovery means.** The pre-recovery sample is taken on a FAULTED gyro
   (0.25–0.52 rad/s); feeding it to fusion would inject the fault as a correction. The two call
   sites (`before = _sampleGyro(...)`, `after = _sampleGyro(...)`) are eleven lines apart.
2. **The estimate is valid for THAT boot only, and fusion must record which estimate it used** —
   the same attribution requirement as `fusion_version` in the US-805 ruling. *A correction that
   cannot be attributed cannot be audited.*

**Precision — MEASURED, and it settles the range I left open.**

    _sampleGyro: for _ in range(count): readings.append(tuple(icm.gyro))   -- no delay (Atlas, verified)
    gyro ODR:    1100 / (1 + 10) = 100 Hz   -- adafruit_icm20x 2.1.10 initialize(), installed on the Pi
    measured:    20 raw reads of GYRO_XOUT (0x33) take 18.3-22.8 ms, 6 trials,
                 and return only 2-3 DISTINCT samples each time    (BANK_SEL 0x00 before and after)

**Effective N ≈ 3, not 20** — the loop finishes inside two or three 10 ms output periods. HEALTHY
per-sample SD is 0.00279 rad/s, so at N = 3 the mean's SE is 0.00161 rad/s and the residual pitch
error is **~0.46° — an ~8× improvement, not ~20×.** 🔴 ***Withdrawn: the "~20× / 0.18°" figure I
published earlier the same day. It assumed N = 20 and the device does not deliver it.*** ⚠️ The
raw `smbus2` loop is likely a little faster than the driver's `busio` path, so the driver may catch
one or two more samples — **N ≈ 2–5 in practice, still nowhere near 20.**

⇒ **The sampler fix is required, not optional:** sample across a deliberate **2–5 s window paced
at the 100 Hz ODR** (200–500 genuinely independent samples) and **state N in the landed record.**

⚠️ **Precondition, owned by the caller and already true at startup:** the car must be stationary.
`gyroLooksFaulted`'s own docstring makes the same point — at key-on the car has not moved.

🔴 **Neither half is filed.** #3 needs the CIO's permission to join the punch list (standing rule,
2026-09-21). Routed to Marcus by Atlas.

### Story consequences

- **US-778** (latch recovery) — 🟢 **the work exists, is deployed, and is validated in the field:
  10 detected, 10 cleared, 0 failed, 0 skipped, journal 2026-09-08 → 09-21.** It reads `pending`
  on the punch list. ⇒ **Candidate for closure against that evidence**, subject to the PM checking
  its acceptance criteria. ⚠️ **One gap if the ACs require it: the outcome is journal-only** — which
  obligation (a) above closes.
- **US-749** (70° runaway guard) — **RULED NOT OBSOLETE (Atlas, 2026-09-21), and it must not be
  closed on the evidence above.** Its trigger has stopped firing because recovery succeeds; **that
  shows the guard is UNEXERCISED, not UNNECESSARY.** `0 failed` and `no guard needed` write an
  identical journal — the quiet-counter ambiguity of F-076 (`consecutive_failures = 0` reads the
  same on a working quarantine and on one that is never called). **US-749 exists for the boot where
  recovery FAILS.** Its dependency on US-778 is met; **what fences it is the PM's to state.**
- 🔴 **Neither story fixes the defect Atlas saw on 09-21 and I reproduced the same night.** That is
  #3, and it needs its own item — see the two obligations above.
- **US-782** — **DROPPED** (Atlas, 2026-09-21). See below.

---

## US-782 — DROPPED. It measures NOISE, and the pitch error is BIAS.

**RULED (Atlas, 2026-09-21): dropped from V0.29, not re-scoped.** Re-scoping a spike into a fix is
shape drift — US-782 is sized and justified as a measurement, and #3 is a code change with a
precondition. #3 gets its own row or none.

🔴 **CORRECTION — the first version of this section gave a false reason alongside the true one.**
It said reaching DLPF meant *"writing bank-2 registers behind the driver on a live bus."* **False.**
The installed driver, `adafruit_icm20x` 2.1.10, exposes **`gyro_dlpf_cutoff` and
`accel_dlpf_cutoff` as supported properties with setters**, and handles the bank switch itself. Our
code never sets them, so the chip runs at its power-on default — **which makes the story's "config
0" premise coherent, not empty.** ⇒ **US-782 was executable through the supported API.** The drop
rests on the argument below **alone**, which is sufficient; the feasibility objection is withdrawn.

⚠️ **One real caution the correction does not remove:** the driver's DLPF setters write
`REG_BANK_SEL` to reach bank 2. Any code doing so at runtime must own the IMU exclusively for that
moment. **I have NOT established how many processes read the IMU** — the two-process finding is
about the MAX17048, and I should not have carried it across to this device.

🔴 **Why the drop stands anyway — it would tune the wrong term.** At the current (default) config:

    per-sample gyro SD  (HEALTHY, parked)   x 0.00342   y 0.00279   z 0.00295  rad/s
    residual gyro BIAS  (HEALTHY, parked)   x -0.00088  y 0.01304   z 0.00392  rad/s

On `gyro_y` **the bias is 4.7× the per-sample noise — and it is systematic, so it does not average
out, while the noise does**, under the same 5 s filter that turns the bias into a 3.7° error. **A
DLPF change moves the noise and leaves the bias untouched.** ⇒ **US-782 cannot move the error that
is actually breaking pitch and grade.**

🟢 **DLPF default VERIFIED against the datasheet (DS-000189 §10.2, §10.15):** `GYRO_CONFIG_1` and
`ACCEL_CONFIG` both reset to **`0x01`** — DLPF **enabled**, `DLPFCFG = 0`. The driver's
`initialize()` writes only the range bits, so the running configuration is **config 0**, exactly
the story's premise.

🟢 **Its baseline is on the record** — the SDs above, n = 5,332,340, at the power-on-default DLPF —
**so if the DLPF question is ever asked again, the "before" arm already exists.** Nothing is lost by
dropping it.

**`void if`** — the IMU is replaced or its DLPF is ever set explicitly.

---

## Accelerometer scale factor (US-783)

🔴 **`ACCEL_SCALE_CORRECTION = 0.98200`** — multiply every raw accelerometer component by this
before use. Equivalent statement: **the ICM-20948 reads +1.83 % HIGH in the HEALTHY state.**

**Derivation.** At rest the accelerometer measures local gravity. Reference from the Somigliana
formula plus the free-air correction, at 41.88 °N and 180 m (Chicago):

    g_local = 9.7803267715 * (1 + 0.0052790414 sin^2(phi) + 0.0000232718 sin^4(phi))
              - 3.086e-6 * h
            = 9.8028 m/s^2

    observed (HEALTHY, at rest)   9.98255 m/s^2
    ratio                         1.01833         => +1.833 % high
    correction factor             0.98200

🟢 **The reference is not a weak link.** g varies ~0.0009 m/s² per degree of latitude near 42 °N and
~0.0003 m/s² per 100 m of elevation — **±1° and ±100 m move the answer by under 0.01 %, against a
1.83 % effect.** Location uncertainty cannot explain this and is not a live objection.

**Sample: n = 5,706,847.** **Exclusions, stated because a filter that removes the rows which would
contradict you is indistinguishable from not having the data:**

- EXCLUDED `drive_id IS NOT NULL` — any drive-attributed row (vehicle motion adds to ‖a‖).
- EXCLUDED every FAULTED-state and intermediate row (`gyro_y <= -0.10`). **This is the load-bearing
  exclusion** — see below.
- EXCLUDED all rows before 2026-09-08 (they predate the current mount era).
- Window 2026-09-08 → 2026-09-21, server tier.

🔴 **THE CORRECTION IS STATE-DEPENDENT AND MUST NOT BE APPLIED BLIND TO HISTORICAL DATA.** In the
FAULTED state the same instrument reads **9.79492 m/s², i.e. −0.08 % — essentially correct.**
Applying the +1.83 % HEALTHY correction to a FAULTED row introduces a **1.91 percentage-point
error** where there was almost none.

⇒ **Rule for consumers.** Apply `ACCEL_SCALE_CORRECTION` **only** to rows known to be HEALTHY-state.
Going forward that is every row, because A-34 recovery runs at startup and has succeeded 10/10.
**For the historical corpus, classify by resting `gyro_y` first** (the −0.10 / −0.25 gap is empty)
**or exclude rows before 2026-09-16.**

⚠️ **Do NOT read the FAULTED figure as "the faulted state is better calibrated."** That state fails
the factory self-test (0.062/0.087/0.126 against a 0.5 floor), its ‖a‖ SD is **3.7× larger**, and
its daily means scatter across 9.694–9.891 where HEALTHY holds 9.972–9.989. **It is unstable and
happens to straddle g. Stability, not proximity to the expected answer, is what makes a reference
trustworthy.**

⚠️ **Supersedes the office's earlier `+1.56 %`**, which stated neither its state-split nor its
exclusions and cannot be reproduced from the current corpus. The band Atlas carried (+1.6–2.0 %)
contains this result.

🔴 **KNOWN LIMITATION OF THIS NUMBER — THERE IS NO TEMPERATURE TERM.** `edr_imu_sample.temp_c` is
**NULL on all 6,275,515 rows since 2026-09-08.** MEMS accelerometer sensitivity is
temperature-dependent, so `ACCEL_SCALE_CORRECTION` is a single figure over whatever thermal range
the Pi actually saw. ⚠️ **State this whenever the number is quoted.**

⚠️ *Corrected 2026-09-21: this paragraph first said the temperature "channel is already read — it is
the persistence that is missing." **False.** US-500 (`sensor_reader.py:594-602`): the
`adafruit_icm20x` driver raises on `.temperature`, the read degrades to `None`, and **nothing is
read at all.** See the `temp_c` section below.*

🟢 **BUT THE TEMPERATURE TERM CAN BE BOUNDED WITHOUT A TEMPERATURE CHANNEL — and it is small.**
HEALTHY-state, parked, daily mean ‖a‖:

    2026-09-17   9.98850      2026-09-20   9.97616
    2026-09-18   9.97650      2026-09-21   9.97150
    2026-09-19   9.98318
    spread       0.01700 m/s^2   =  0.173 % of g

**Everything that varied across those five days — temperature included — moved the scale by at most
0.17 %, against a 1.83 % static error.** ⇒ **The static correction captures ~91 % of the error in
the conditions observed.** ⇒ 🟢 **US-783 does NOT need to block on a temperature term.** Ship the
static factor; a temperature term is a refinement.

⚠️ **What this bound does and does NOT say.** It bounds the *combined* day-to-day effect over one
September week with the car mostly parked. **It is not a temperature coefficient**, because the
thermal range across those days is unknown — no ambient source exists on this car (IAT is not
ambient, US-206). **A cold winter start is outside the observed range and the bound does not
extend to it.** Re-check the first time the car is driven below ~5 °C.

### 🔴 DATASHEET CHECK (2026-09-22) — the error is probably an OFFSET, not a SCALE. HOLD the constant.

**Checked against TDK DS-000189 rev 1.3, Table 2** (`hardware/datasheets/icm-20948/`):

    accel sensitivity, initial tolerance        +/-0.5 %        (component-level)
    accel zero-g offset, initial tolerance      +/-25 mg component, +/-50 mg board-level
    zero-g change vs temperature                +/-0.80 mg/degC
    sensitivity change vs temperature           +/-0.026 %/degC

**Our resting excess is +0.180 m/s² = +18.3 mg on the up-facing axis.**

| Reading of the same +18.3 mg | Against the datasheet |
|---|---|
| a **sensitivity (scale)** error of +1.83 % | 🔴 **3.7× outside** the ±0.5 % typical tolerance |
| a **zero-g offset** of +18.3 mg on the up axis | 🟢 **inside** ±25 mg (component) and ±50 mg (board) |

⇒ 🔴 **The multiplicative model this section was built on is the LESS likely one.** ‖a‖ at rest
cannot tell scale from offset — they give **identical** corrections parked. **In motion they
diverge:** under 0.5 g braking a scale correction trims the longitudinal axis by 1.8 % that an
offset would leave alone, and an offset stays constant through bumps that a scale would stretch.
**"Trust gravity while the car moves" is US-783's entire purpose, so the model is load-bearing.**

⇒ **RECOMMENDATION (Spool): HOLD `0.98200` for any in-motion use until the model is settled.**
Nothing parked is lost by waiting — the two models agree at rest.

🟢 **The falsifier is a tumble test and needs hands, not code:** read ‖a‖ with a **different axis
pointing up** (board on its side, then on its end). **Offset ⇒ each orientation reads g plus that
axis's own offset, differently. Scale ⇒ every orientation reads the same g × 1.018.** Six
orientations give a full per-axis offset + scale calibration. ⚠️ The IMU is mounted in the car ⇒
**human task**, and it voids the mount-4 characterisation, so pair it with the next remount.

🔴 **And the temperature bound above says less than it appeared to.** The five-day spread was
**1.7 mg**; at the datasheet's ±0.80 mg/°C zero-g drift that implies a **nearly isothermal week**
(≈ 2 °C effective). ⇒ **It bounds little about temperature.** A 20 °C seasonal swing could move the
zero-g level ~16 mg — **as large as the whole effect.** That strengthens Atlas's attestation
condition below: **the measurement window is not a footnote, it is most of the meaning.**

🟢 **ACCEPTED (Atlas, 2026-09-21): ship `0.98200` without a temperature term — WITH ONE CONDITION.
⚠️ Superseded in part by the datasheet check immediately above — for at-rest use only until the
scale-vs-offset question is settled.**
The constant must carry the WINDOW IT WAS MEASURED OVER, in the config, not only in this spec.**
Record alongside it: *HEALTHY state only · n = 5,706,847 parked samples · 2026-09-08 → 09-21 ·
one September week, car mostly parked · not a temperature coefficient.* **Otherwise a January
measurement that disagrees will read as a REGRESSION rather than as the out-of-bound case already
predicted here.** ⚠️ The config file is not this office's surface — the attestation is specified
here and **the config half belongs to whoever implements US-783.**

**Measurement conditions, fact-checked against the installed driver** (`adafruit_icm20x` 2.1.10,
`initialize()`): accelerometer range **±8 g**, accelerometer ODR **~53.6 Hz** (divisor 20), gyro
range **±500 dps**, gyro ODR **100 Hz** (divisor 10). *Corrected: an earlier line here said the
range was unset because our code passes no range argument — the driver's own `initialize()` sets
it explicitly. The factor is valid at ±8 g.*

**`void if`** — the IMU is replaced or moved to different hardware, the A-34 recovery changes, or the
accelerometer range is ever changed from the driver's ±8 g default.

---

## UPS slow-drain detection (F-051) — THIS NEEDS A STATE GATE, NOT A THRESHOLD

🔴 **No value of `declineThresholdVolts`, `windowSeconds` or `debounceSeconds` makes this instrument
work. Do not ship a replacement number.**

**Measured by Spool 2026-09-21** from the detector's own journal output, 2026-09-14 → 09-21
(7.7 days). Tool: `offices/tuner/scripts/slow_drain_episode_analysis.py`.

    episodes                                    77   (~10 per day)
    duration      min 40 s   median 340 s   max 1580 s
    lasting >= one full 300 s detector window   58/76  (76 %)

**The false verdicts are SUSTAINED, not transient.** A dwell — sliding `k`-of-`n` or consecutive —
counts duration, and the duration is already long.

🔴 **The disqualifying arithmetic:** suppressing a 1580 s false episode needs a dwell longer than
1580 s, but the Pi survives **12–14 min below ~1.9 W and under one second above ~2.1 W** (Atlas,
measured). **The dwell required to be quiet is longer than the battery lives.** A detector that can
only be trusted after its subject is dead is not a detector.

🔴 **The actual defect is a threshold grounded in one regime and evaluated in another.** The
module's own docstring grounds `0.005 V / 300 s` on **drain tests** — on battery — then asserts it
"stays quiet on AC-fed float noise". `_pollOnce()` (`src/pi/hardware/ups_monitor.py:889-890`) feeds
the detector **unconditionally, including while the charger is live.** 77 episodes in 7.7 days
falsify the quiet-on-float claim.

🟢 **Live confirmation, 2026-09-21:** a `slow_drain` episode ran **22:21:05Z → 22:26:55Z (350 s)**
with the Pi on external power throughout — `power_log` carries `power_source='ac_power',
on_ac_power=1` on every row of the session, `states/power-source.json` read
`externalPowerPresent: true` at 22:30Z and again at 22:46Z, and **no power-loss transition appears
anywhere in the journal after 13:51 CDT.** The verdict was produced about a cell sitting on a
charger.

⚠️ **The sample-level trip mechanism is NOT directly observed and this spec does not claim it.**
Direct MAX17048 reads show VCELL moving in **discrete steps with long plateaus**: it fell
**4.15375 V → 4.15125 V (32 LSB ≈ 2.5 mV) over ~4.8 minutes**, then held **bit-identical at raw
53136 across 40 consecutive reads spanning 400 s** — a plateau longer than the detector's whole
window. **A single 2.5 mV step over ~290 s is half the 5 mV threshold and would NOT trip it.**
⇒ The float signal is plainly capable of moving the detector, but **which excursion trips it has
not been caught at sample resolution, because nothing persists VCELL at poll cadence.** The
77 episodes are the observation; the per-sample mechanism is inferred and is labelled as such.

🟢 **QUIESCENT FLOAT BAND, 2000 mAh cell, measured 2026-09-21 22:39–22:51Z:** 72 reads at 10 s
spacing over **710 s** returned exactly **two** distinct values — raw 53136 and 53120, a single
**16 LSB = 1.25 mV** step. ⇒ **Between excursions the float signal is far quieter than 5 mV per
300 s**, which is why the detector is not permanently latched. **The ~10 events per day are
excursions against this quiet baseline, not a continuously noisy signal.** ⚠️ **One 12-minute
window on one cell: it bounds the quiet state, it does not characterise the excursions** — and the
excursions are the thing that matters. Characterising those needs VCELL persisted at poll cadence,
which nothing currently does.

⇒ **RULING (Spool, 2026-09-21): do not evaluate cell-drain health while external power is present.**
Gate on **`PowerSourceProvider.isExternalPowerPresent()`**
(`src/pi/power/power_source_provider.py:56`) — the GPIO6 PLD SSOT. On external power the verdict is
**`UNKNOWN`, not `STABLE`**: nothing has been measured, and `UNKNOWN` is the answer the rest of this
UI already gives. **On transition to battery, start a fresh window.**

⚠️ **A correct verdict changes no behaviour yet:** `getSlowDrainState()` has zero callers in `src/`.
**Wiring is an architecture item, not a tuning one.** Do not read a shipped gate as a working
feature.

⚠️ **If a threshold is ever wanted anyway, it must be re-derived on the CURRENT cell.** Post-swap
episodes run **515–615 s** against a pre-swap median of **340 s** — the 2000 mAh cell's falling limb
is LONGER, so any number carried across the 2026-09-21 18:50Z swap is wrong in the direction that
still fires. **n = 3 post-swap episodes at time of writing; that is not a sample.**

**`void if`** — the X1209 charger is replaced, or `getSlowDrainState()` acquires a consumer whose
requirements differ.

---

## MAX17048 SOC after a cell change (F-048)

🔴 **`REGISTER_MODE` (0x06) — the QuickStart register — is DEFINED at
`src/pi/hardware/ups_monitor.py:248` and NEVER WRITTEN ANYWHERE IN THE REPOSITORY.** QuickStart is
the MAX17048's designed remedy for exactly the event that occurred on 2026-09-21: a cell swapped
underneath a running gauge. Without it the ModelGauge algorithm re-converges slowly from the
previous cell's state.

**Measured, 2026-09-21:**

    18:50Z   cell swapped 450 mAh -> 2000 mAh (CIO)
    ~18:52Z  VCELL 4.2062 V  ->  SOC 65.9 %, then 67.9 % a minute later   (Atlas)
    +15 min  still not converged                                          (Atlas)
    22:30Z   VCELL 4.1537 V  ->  SOC 95 %                                 (Spool, +3 h 40 m)

🟢 **The "gauge is ~30 points out" reading was a TRANSIENT of re-convergence, not a standing
calibration error, and it has self-corrected.** VCELL fell 52 mV while SOC rose 29 points — that is
re-convergence, not a voltage/SOC curve. **95 % at 4.154 V is plausible for a single-cell LiPo.**

⚠️ **Convergence time is BOUNDED, NOT MEASURED: longer than 15 min, complete by 3 h 40 min.**
Nothing sampled the interval. **Do not quote a convergence time.**

⚠️ **`socColdStartWindowSeconds = 180` is still the provisional guess the protocol was written to
replace, and 180 s is now known to be far shorter than the observed convergence.** It must be
re-derived against the 2000 mAh cell; the 450 mAh corpus does not transfer.

🔴 **THREE INERT FIELDS ON THE SAME CARD — confirmed live 2026-09-21 22:30Z:**

    socCalibrated  false   (hardcoded)
    charging       false   } both derived from CRATE, which reads 0xFFFF on this chip
    draining       false   }

**All three were false while the cell was demonstrably on a charger.** Any calibration protocol must
say what it does about them, or it calibrates a number nobody can act on.

⇒ **RECOMMENDATION (Spool): issue a QuickStart on detected cell change**, then re-derive
`socColdStartWindowSeconds` from the settling behaviour that follows. ⚠️ **QuickStart must be issued
with the cell at rest, not under load** — it initialises from the instantaneous terminal voltage, so
a loaded reading initialises the gauge low and manufactures a wrong SOC. **That is a
land-what-you-read violation waiting to happen: it would not fail, it would answer confidently.**

### 🔴 The MAX17048 HAS NO TEMPERATURE REGISTER — and it expects the HOST to supply one

**Researched 2026-09-21 (Spool), confirming the 2026-08-01 ruling rather than assuming it.**

🔴 **PROVENANCE — read this before building on anything in this subsection.** **No MAX17048
datasheet is held in this repository or on the share** (checked 2026-09-21: `specs/`, `docs/`,
`hardware/`, share `examples/`, `facts/`). Two tiers of fact below, and they must not be mixed:

- 🟢 **CORROBORATED in-repo** (`ups_monitor.py:246-251`, written against the part and exercised in
  production): `VCELL 0x02` (78.125 µV/LSB) · `SOC 0x04` (high byte = integer %) · `MODE 0x06`
  (write-only) · `VERSION 0x08` · `CONFIG 0x0C` (*"boots to 0x971C"*) · `CRATE 0x16`
  (0.208 %/hr/LSB; reads `0xFFFF` on this chip).
- ⚠️ **RECALLED from the Maxim MAX17048 datasheet, NOT held locally — VERIFY BEFORE ANY STORY
  BUILDS ON THEM:** `HIBRT 0x0A` · `VALRT 0x14` · `VRESET/ID 0x18` · **`STATUS 0x1A` and its `RI`
  bit** · `CMD 0xFE` · **the RCOMP temperature formula and both `TempCo` coefficients below.**
  *Corrected: the first version of this section said "the datasheet specifies" for all of these.
  It did not have the datasheet. That breaks this document's own Usage Rule 1.*

**There is no temperature register and the part has no thermistor input** — a voltage-only
ModelGauge. ⇒ **Any temperature tile fed from this chip is fabricated. Do not add one.** 🟢 This
conclusion does **not** depend on the recalled tier: none of the six corroborated registers is a
temperature, and the in-repo driver reads none.

🔴 **The part is designed on the assumption that the HOST compensates for temperature.** The
`CONFIG` register's high byte is **RCOMP** — 🟢 corroborated: `0x971C` puts **`0x97`** there at
boot. ⚠️ The compensation law, **recalled, not verified**:

    RCOMP = RCOMP0 + (T - 20 degC) * TempCoUp      for T > 20 degC     (recalled typ. -0.5)
    RCOMP = RCOMP0 + (T - 20 degC) * TempCoDown    for T < 20 degC     (recalled typ. -5.0)

🔴 **We never write it.** `ups_monitor.py:250` defines `REGISTER_CONFIG = 0x0C` and records that it
boots to `0x971C`, and **no code anywhere in the repository writes that register** — so the gauge
has run at its boot-default RCOMP for the life of the project. **That part is corroborated.**

⚠️ **How large the SOC error is cannot be stated from here** — it depends on the recalled
coefficients and on a cell temperature nobody has measured. A car cabin in summer can plausibly run
well above the 20 °C calibration point, **but no cabin temperature has ever been measured on this
car**, so treat the magnitude as unknown rather than large.

🔴 **BUT IT IS HARDWARE-GATED, AND THE OBVIOUS FIX IS FABRICATION.** RCOMP needs the **CELL's**
temperature. **This car has no cell-temperature sensor.** ⇒ **Do NOT substitute the ICM-20948 die
temperature, the Pi CPU temperature, or IAT.** Each is a different body with its own self-heating,
and feeding one into RCOMP would not fail — **it would confidently mis-model the cell.** This is the
IAT-as-ambient ruling (US-206) applied to a second instrument: **the absence of a source is not a
licence to use the nearest available number.**

⇒ **Backlog, not a fix:** *(a)* add a cell-temperature source, then *(b)* apply RCOMP compensation.
**(b) without (a) is worse than doing nothing.**

**`void if`** — the cell is changed again, or the X1209's gauge is replaced with a part whose CRATE
register works, or a cell-temperature sensor is fitted.

### 🔴 The cold-start guard asks SYSTEM UPTIME a question only the GAUGE can answer

`soc_calibration.py` guards the register SOC read against a cold-start window, and it derives "has
the gauge finished calibrating?" from **`/proc/uptime`**. Its own docstring states the assumption:
*"the MAX17048 fuel gauge starts calibrating when the rig powers up, so system uptime is the
available proxy."*

🔴 **RULED (Atlas, 2026-09-21): `/proc/uptime` measures the SYSTEM; the question is about the
GAUGE.** Uptime is a proxy for a different quantity from the one the guard needs, and a register
that answers directly exists. **That is the ruling, and it holds regardless of power topology.**

⚠️ *Corrected: this section first argued that the gauge is "powered by the cell", so pulling the
cell always resets it while the Pi keeps running. **That is a plausible hypothesis and it is NOT
verified** — no local source states what supplies the MAX17048 (`architecture.md` says only that
the X1209 holds up the **Pi's** 5 V rail). The ruling does not rest on it. Its falsifier stays
useful: pull and reinsert the cell on a running Pi and watch whether `RI` sets while uptime climbs.*

⚠️ **On 2026-09-21 system and gauge happened to power up together** — the Pi died at 18:45:14Z and
the cell went in at 18:50Z — **so this did not bite. A guard that is correct by coincidence has not
been tested.**

🟢 **The designed instrument: `STATUS` (0x1A), `RI` (Reset Indicator) bit — set on power-on-reset,
held until the host clears it.** 🟢 **Verified by Atlas: `STATUS` is not merely unread — it is
ABSENT from the register map** (`ups_monitor.py:246-251`; zero hits for `0x1A`/`STATUS`/`RI` in
`src/pi/power`). ⚠️ **`RI`'s semantics are in the RECALLED tier above — verify against the Maxim
datasheet before building.**

🔴 **CONDITION OF THE RULING (Atlas): clearing `RI` is a WRITE, and the MAX17048 is polled by TWO
processes** (`power_watch` and `main.py` — measured 2026-09-21 from the slow-drain journal: two
logger families, 95 pids, one gauge). **Whoever clears `RI` first destroys the evidence for the
other reader**, which then sees a clean bit on a gauge that has just reset. **The story must name ONE
owner of the clear, and every other reader treats `RI` as read-only.** Atlas recommends the
calibration guard owns it; the alternative is that **nobody clears it** and the guard latches its
own "seen-reset-at" timestamp. **Either is acceptable. Silence on the question is not.** ⚠️
Whether both processes would actually read `STATUS` depends on where the guard lands — **check
before sizing.**

### F-048 cold-start protocol — THE PROTOCOL ALREADY EXISTS. This section amends it.

🔴 *Corrected: the first version of this section wrote a new protocol. **One already exists and is
better grounded:** `docs/max17048-soc-calibration-protocol.md` (US-431), with tooling
`scripts/calibrate_max17048.py`. It is the SSOT for the procedure. I wrote mine without reading
it — which is exactly how two versions of one truth are made.*

**What the existing protocol already does — and did before I proposed it:** 600 s at 5 s,
**logged to a CSV file** (so "persist to a file, not the journal" was already met), settle =
**±2 pct held ≥ 30 s** (grounded: the SOC register is integer-percent, so ±2 is 2 LSB), window padded
**×1.5** and rounded up to 10 s, CIO runs the physical cycle, Spool interprets.
⚠️ **My ±1 % is withdrawn** — it is one LSB of an integer register, tighter than the instrument can
resolve. **The existing ±2 pct is correct.**

🟢 **It also holds independent corroboration of the 2026-09-21 transient:** *Drive 5 — SOC 60 % at
VCELL 4.200 V, a 40-point error* at cold power-up. Atlas's 65.9 % at 4.2062 V is the **second
recorded instance** of the same ModelGauge behaviour, which strengthens the "re-convergence
transient, not a standing error" reading.

**AMENDMENTS — these are new and belong in that doc (not this office's surface; for its owner):**

1. 🔴 **HOLD — do not run it now** (Atlas, 2026-09-21). A **third cell epoch** is coming:
   `→18:50Z` 450 mAh pouch · `18:50Z→` 2000 mAh pouch · **then an 18650 pack, ordered, not
   fitted.** Measuring now characterises a cell that is about to leave. **Run it on the cell we
   keep.** 🟢 Design intent agrees: `architecture.md:243` specifies the X1209 as **"18650 battery
   backup"** — that is what the board is built for. *(`facts/power-and-battery.md:89` calls the
   docs' "18650" WRONG — correctly, as a description of the pouch that was actually fitted. Both
   are true about different things; it becomes true of the fitted cell again when the pack lands.)*
2. 🔴 **Record the window WITH THE CELL IT WAS MEASURED ON**, and make the config key
   re-derivable — otherwise a well-measured number silently expires on the next cell change.
3. **The settle clock is system uptime** (*"start promptly"*) — the same proxy the ruling above
   retires. **Record `STATUS.RI` alongside each sample**, once verified against the datasheet.
4. **n ≥ 3 cold starts.** One run gives a curve, not a window.
5. **Add the two-minute falsifier:** pull and reinsert the cell on a running Pi; record `RI` and
   `/proc/uptime`.

⚠️ **The existing `180` does not survive** — 2026-09-21 showed convergence past 15 minutes after a
cell change. **Do not carry it forward.**

🔴 **What the protocol must say about the three inert fields — Atlas's point, and it is decisive:**

- **`socCalibrated`** is hardcoded `false`. ⇒ **This protocol's output is what makes it meaningful.**
  It must become a real verdict — `true` only once `RI` is clear *and* the measured window has
  elapsed — or the calibration produces a number no consumer can act on.
- **`charging` / `draining`** derive from `CRATE`, which reads `0xFFFF` on this chip. 🔴 **They must
  be typed-NA with a reason, not `false`.** On 2026-09-21 at 22:30Z both read `false` while the cell
  was demonstrably on a charger — **`false` is an assertion, and the truthful answer is "this chip
  cannot tell you."** ⇒ Derive charge direction from the **VCELL trend** under the F-051 state gate,
  or publish NA. **Do not leave a field that is wrong in a knowable way.**

⚠️ **The protocol needs a powered-off cold start, which is a CIO action, not a keyboard one.** It is
written so it can be executed without me.

**`void if`** — the gauge is replaced, or `CRATE` is ever found to return valid data on this part.

---

## `states/imu` PUBLISHES `pitchDeg`, `stopCount` and `biasRad` — they are UNPERSISTED, not absent

🔴 **CORRECTION, 2026-09-21 (Spool), to a claim Atlas made and I repeated twice.** The record says
these three channels *"are not logged, so no pitch or grade fix is verifiable by anyone"* and that
*"no grade defect can be reproduced"* until US-805 lands. **The first half is right about the
DATABASE and the second half is wrong.**

**They are published live, every second, in `/run/eclipse-obd/states/imu`.** `edr_imu_sample` has no
such columns — that part is correct — but **the values exist and can be read right now.**

🟢 **REPRODUCTION OF THE GRADE DEFECT, on a stationary car, 2026-09-22 03:14–03:17Z, 15 s sampling:**

    ts                     pitchDeg   gradePct   stopCount   biasRad   gMag
    03:14:57Z              -4.02      -7.0       0           0.0       0.005
    03:15:26Z              -3.10      -5.4       0           0.0       0.009
    03:16:12Z              -3.62      -6.3       0           0.0       0.002
    03:17:12Z              -2.91      -5.1       0           0.0       0.004

**`gMag` 0.002–0.009 — the car is not moving. `gradePct` swings 1.9 points and `pitchDeg` 1.11°.**

⇒ 🔴 **The defect is reproducible TODAY, at any resolution, by anyone with SSH — US-805 is NOT a
precondition for reproducing it.** What US-805 *is* required for: **historical analysis, and
verifying a fix across time.** ⇒ **US-805 is a PERSISTENCE story, not a compute-and-expose story.**
Nothing needs to be calculated; the numbers already exist and are thrown away.

🟢 **Two standing findings confirmed live in the same capture:** `biasRad = 0.0` (ZUPT never engages
below 5 confirmed stops) and `stopCount = 0` **after hours parked** — the stop deque is empty and
the correction has never had the inputs it needs. **A parked car never accumulates stops**, so the
bias is never cancelled, exactly as the mechanism predicts.

**`void if`** — `states/imu` stops carrying these fields, or US-805 lands and persists them.

---

## `edr_imu_sample.temp_c` — why it is NULL, and it is NOT an oversight

**Researched 2026-09-21 (Spool).** `temp_c` is NULL on **all 6,275,515 rows since 2026-09-08**.
**The cause is already known and the code is already honest about it:** `sensor_reader.py:594-602`
records **US-500 — the genuine `adafruit_icm20x.ICM20948` does NOT expose `.temperature`** (a clone
and the test fake did, which is how the assumption got in). The read is wrapped, the
`AttributeError` degrades to `None`, and the burst is **not** dropped. ⇒ **This is honest-null, not
a wiring defect. Nothing is being hidden.**

### 🟢 RECONCILED BY THE VENDOR'S OWN DOCUMENT — the DRIVER we run has no temperature; the CHIP does

**Two statements appeared to conflict on 2026-09-21:**

- **CIO:** *this version of the IMU does not have a temperature register.*
- **Spool, direct I²C read** at `0x69`, bank 0, no bank switch: `WHO_AM_I = 0xEA`,
  `BANK_SEL = 0x00`, `TEMP_OUT (0x39/0x3A)` raw 1952 / 1968 / 2016 / 2064 / 1952 — a plausible,
  **dithering** value (≈ 26.9–27.2 °C by `TEMP_degC = ((TEMP_OUT − RoomTemp_Offset)/333.87) + 21`
  — 🟢 **verified 2026-09-22 against DS-000189 rev 1.3**, now held at `hardware/datasheets/icm-20948/`;
  `WHO_AM_I` reset value `0xEA` verified there too).

**Settled by `hardware/enclosures/case-imu-icm20948/datasheets/adafruit-tdk-invensense-icm-20948-9-dof-imu.pdf`
(the Adafruit guide for this breakout) plus the installed driver source:**

| Layer | Temperature? | Source |
|---|---|---|
| **The part** — Adafruit ICM-20948 breakout, default I²C `0x69` | 🟢 **yes** | guide p.3 (`0x69`, `SDO/ADR` → `0x68`); `WHO_AM_I 0xEA` read live |
| **Adafruit's Arduino driver** | 🟢 **yes** | guide: `icm.getEvent(&accel, &gyro, &temp, &mag)` → `temp.temperature` |
| **Adafruit's CircuitPython driver — the one we run** | 🔴 **NO** | guide lists only `acceleration`, `gyro`, `magnetic`; installed `adafruit_icm20x` **2.1.10** has **no `def temperature`** |

⇒ 🟢 **The CIO is right about the version we use — our driver has no temperature.** The chip under
it does. **Both statements were true; they were about different layers.** This is US-500's exact
finding, now confirmed from the vendor's own document.

⇒ 🟢 **Part identity is settled.** Atlas raised (2026-09-21) that a dithering register on a part
said to lack one could mean *the part is not what we believe*, which would put A-34's register
assumptions in doubt. **It is what we believe:** genuine Adafruit ICM-20948 breakout, `WHO_AM_I
0xEA`, default address as documented. **A-34's register assumptions are not undermined by this.**

🔴 **RULING UNCHANGED — the CIO's call: whether to read `TEMP_OUT` by going past the driver** (the
`ak09916_bypass` / `gyro_recovery` precedent) **is a decision, not a derivation.** No story reads it
until he says so.

🟢 **Nothing is blocked by leaving it open:** US-783 ships without a temperature term (the static
factor captures ~91 % of the error, bounded above), so this is a refinement, not a gate.

⚠️ **If it is ever resolved in favour of the register:** it is the IMU's **die** temperature — the
right input for accel scale compensation and the **WRONG** input for the UPS cell's RCOMP. **Do not
let one story serve both.**

---

## Usage Rules

1. **Never fabricate values.** If a threshold or range is not in this document or `specs/obd2-research.md`, the story is `blocked` until data is provided.
2. **Cross-reference DSMTuners advice.** Look for patterns across multiple threads, not single posts.
3. **This document is append-only for facts.** New grounded knowledge gets added here as it's discovered. Existing facts are only updated with better data, never removed without CIO approval.
4. **CIO is the final authority.** If CIO provides a value that contradicts community guidance, CIO's value wins (it's their car).
