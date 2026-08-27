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
| Coolant Temp | ≤101 °C (214°F) | 🟡 ≥104 °C **sustained ≥30 s** · 🔴 ≥110 °C any duration, or ≥104 °C ≥120 s | **CORRECTED 2026-08-20 (Spool, measured).** Threshold+dwell, NOT a bare threshold — 101 °C is this car's normal **fan-cycle ceiling**. A bare 🟡 inside a cycling signal's oscillation band nuisance-fires (a bare 100 °C would have fired on 6 of the last 7 *healthy* captures). Derivation: `$FLEET_SHARE/tuner/knowledge/knowledge.md` §Cooling. |
| Boost (stock turbo) | ~12 psi | >15 psi on stock | Stock wastegate actuator limit |
| AFR at WOT | 11.0-11.8:1 | >12.5:1 under boost (lean danger) | Rich is safe, lean kills engines |
| Knock count | 0 | >0 sustained | Any knock is bad; transient single counts can be noise. **ECMLink USB+PC only — NOT readable over the OBD pipe** (Mode 22 silent on this ECU). |
| Oil pressure | Varies by RPM | Low at idle is concern | No OBD-II PID on stock ECU; future with ECMLink |
| **Timing Advance** | **5–10° idle · 18–32° cruise · tapers to ~18° under load** | ⚠ **No bare-level alarm is valid.** Judge **against load and RPM together** | **ADDED 2026-08-27 (Spool, measured — 10,909 samples).** 🔴 **The community band "10–15° idle normal, <5° or negative = danger" was WITHDRAWN: it fires on 696 of 10,909 samples (6.4%) on a healthy car, and only 1 sample in the entire corpus is actually negative.** Low advance at idle/decel/overrun is normal — the ECU has no reason to advance. Low advance **while load is high** is the signal. This car idles **5–9° (avg 7°)**, so a 10–15° "normal" grades it below-normal. All-time max 34.0° (Drive 7 WOT). ⚠ **`TIMING_ADVANCE` is BASE timing, not knock retard** — it cannot tell you whether the engine knocked. |
| **IAT (Intake Air Temp)** | **20–55 °C; heat-soak to ~62 °C is normal** | ⚠ **Informational only — no red** | **ADDED 2026-08-27 (Spool, measured — 10,917 samples).** 🔴 **A ">60 °C danger" threshold was WITHDRAWN: 157 samples exceed it on a healthy car** (all-time max 62 °C). That is heat soak — expected, benign, and it self-clears with airflow. 🔴 **IAT IS NOT AMBIENT** (US-206 DISPROVEN): runs 14–24 °C high always, cools with airflow, never nears true ambient. **No ambient source exists on this car.** Proven twice — speed-banded (drive 41: 48.1→40.6 °C by speed band) and stop-and-go heat-soak (drives 42→44: 26→45 °C while parked between legs). Label it **INTAKE AIR**, never "ambient". ⇒ `drive_summary.ambient_temp_at_start_c` is **MISLABELED**; rename owed. |
| **Engine Load** | **15–25% idle · 30–50% cruise · up to 100% at WOT** | ⚠ **Compound condition only** — high load **with** positive STFT under boost, or with knock | **ADDED 2026-08-27 (Spool, measured).** 🔴 **A ">90% sustained = danger" threshold was WITHDRAWN — this car reached 100% load on two WOT pulls with no thermal or knock distress.** **Load alone is not a danger signal on a turbo engine**; it is the *expected* reading at full throttle. Only meaningful paired with a lean indication or knock. |
| **MAF** | **2–4 g/s idle; scales with RPM/load** | ⚠ **~150 g/s = stock sensor SATURATION, not a fault** | **ADDED 2026-08-27 (Spool, measured).** All-time max **158.7 g/s** (Drive 7 WOT) — this car **does** reach the stock MAF ceiling at full load. A MAF pinned ~150+ during a pull is **expected**; treat it as a *measurement limit*, not an engine problem. ✅ Also the basis for the **MAF→VE boost inference** (below) on a car where boost is unreadable. |
| **RPM** | **700–800 idle; redline 7000 (97–99 2G)** | 🔴 >7000 (valve float on stock springs) | **ADDED 2026-08-27 (Spool).** ⚠ **Manufacturer spec — NEVER exercised on this car. All-time max is 5,441 RPM.** Everything above that is unmeasured. |
| **Battery Voltage** | see §Battery Voltage via ELM_VOLTAGE below | ⚠ **Engine-running only** — gate on `RPM > 0` and not within ~3 s of a crank | **QUALIFIER ADDED 2026-08-27 (Spool, measured — 14,221 samples).** The bands are correct but **unconditioned**: the <12.0 V floor **trips on cranking** (13 samples, all-time min 11.0 V), and 1,083 samples (7.6%) sit below the 13.5 V "normal" floor — key-on-engine-off, cranking, and immediate post-start. Without an engine-state gate the alert misgrades normal starting as a charging fault. Healthy reference: drives 42–44 cruised at **14.4 V**. |

**Important**: Rows marked *(Spool, measured)* are derived from **this car's own capture corpus** (~10,900 samples per parameter through drive 44) and **override community consensus** where they disagree (PM Rule 7). The unmarked rows remain community baselines awaiting real data.

⚠️ **The Session-23 "first-light" fingerprint below is NO LONGER a refinement source** — it was demoted 2026-08-27 (prior ECU, 23-second mid-warmup window, two inverted rows). Do not ground tests or prompts on it.

> **Standing method rule (2026-08-27): test every threshold against the healthy corpus before shipping it.**
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

⚠️ **This is an inference with a real ±2 psi band, never a measurement. Do not quote a single psi figure from it.** The band comes from the `VE_na` assumption, which is unmeasured on this engine; tightening it needs a WOT pull logged with ECMLink. The sample window was independently verified free of the duplicate-row artifact affecting other seconds in that drive. Full derivation: `$FLEET_SHARE/tuner/knowledge/knowledge.md` §Boost and Turbo.

### Active DTC — P0443 (as of 2026-08-27)

**P0443 — Evaporative Emission System Purge Control Valve Circuit. MIL is LIT.** Stored on every drive since at least 2026-08-20 (drive 41); `DTC_COUNT`=1, `MIL_ON`=1 across drives 42/43/44.

**Verdict: no engine risk, and it does NOT distort tuning data — assessed, not assumed.** A purge valve stuck *open* dumps unmetered fuel vapor into the intake and drags LTFT **negative** on a MAF-based car. This car's LTFT is drifting **positive** ⇒ the solenoid is **not flowing** ⇒ open circuit / stuck closed ⇒ the benign failure direction.

Consequences are emissions-only: the charcoal canister does not purge, readiness monitors will not complete, and the car will fail an emissions test. **Do not treat a lit MIL from this code as a capture-validity or engine-health signal.** Repair timing is the CIO's call.

**Pi-side power-management** (data-collection device, separate from vehicle engine ranges): Pi 5 UPS HAT (MAX17048-managed LiPo cell) — buck-converter dropout knee at VCELL ≈ 3.30 V; ~16-min runtime under typical load (Drain Test 7, 2026-05-02 empirical). Authoritative writeup with full empirical baseline + operational implications: `$FLEET_SHARE/tuner/knowledge/knowledge.md` § "UPS HAT Dropout Characteristics (Drain 7 baseline)".

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

## Usage Rules

1. **Never fabricate values.** If a threshold or range is not in this document or `specs/obd2-research.md`, the story is `blocked` until data is provided.
2. **Cross-reference DSMTuners advice.** Look for patterns across multiple threads, not single posts.
3. **This document is append-only for facts.** New grounded knowledge gets added here as it's discovered. Existing facts are only updated with better data, never removed without CIO approval.
4. **CIO is the final authority.** If CIO provides a value that contradicts community guidance, CIO's value wins (it's their car).
