# Spool's Tuning Knowledge Base

> This is the single source of truth for all engine tuning knowledge in the Eclipse OBD-II project.
> Maintained by Spool (Tuning SME). **2026-05-29 PRIOR ECU IDENTIFIED + CONFIRMED STOCK (Session 22):** CIO supplied photos of the original ECU — **MD346675** (ROM 6675, mfr E2T68273), the 1998 factory FWD-turbo ECU; flash-hardware but NOT ECMLink-flashable (copy-protected). CIO confirmed 100% it was **bone-stock, never flashed** — the swap happened precisely because it was not flash-enabled. CONSEQUENCE: all drives ≤24 (incl. Drive 11 + idle baselines from drives 3–12) are genuine **STOCK factory baselines**; prior "modified EPROM" attributions for the pre-swap ECU are SUPERSEDED. See `### ECU Identity` > Prior ECU subsection. **2026-05-27 ECU IDENTITY CLARIFIED + WIDEBAND PRE-WIRE PLAN LOGGED (Session 20):** CIO ECU confirmed P/N **MD335287** — 1997 DSM non-EPROM ECU with ECMLink V3 flash modification, plug-installed in 1998 chassis (per [ECMtuning Wiki](https://www.ecmtuning.com/wiki/use_ecmlink_in_98_99_dsm)). Prior "modified EPROM" framing throughout sessions/inboxes was loose terminology — the chip is flash-modified non-EPROM, not socketed EPROM. New `### ECU Identity` subsection added under The Vehicle. New `### Pre-Wire Plan for Wideband O2 (ECU-Side)` + `### Pre-Wire Plan for E85 Flex-Fuel Sensor — DO NOT pre-wire from ECU` subsections added in ECMLink V3 Reference: Pin 75 (Rear O2 signal) + Pin 92 (Sensor Ground reference) on Connector B-56 = the pre-wire plan; flex-fuel routes through MAF connector (not ECU) and requires Speed Density mode (now flagged as MANDATORY DEPENDENCY in Flex Fuel Support subsection). Prior major update: **2026-05-22 ECU SWAP (Session 19):** CIO swapped to a new modified-EPROM ECU (ECMLink-V3-friendly tune target). Drive 11 knock-retard reference ARCHIVED as prior-ECU historical; Drive 26 establishes the new working baseline (first knock-retard event observed during city tip-in: 18° pull, recovered cleanly). New tune ~10° more aggressive at sustained peak load vs prior. New OBD capability probe at `scripts/probe_obd_capabilities.sh` — Mode 09 silent, Mode 22 not implemented on this ECU, ECMLink USB+PC required for goldmine data. Two new caveats: SPEED PID reads ~2× actual ground speed on new ECU; cannot fingerprint EPROM via Mode 09. **2026-05-15 FUEL-GRADE CORRECTION (CIO directive):** all pre-mod shelf drives (3–16) were [EXACT: 93 octane — DO NOT CHANGE], NOT 91 as previously recorded. CIO misreported earlier; 93 octane is standard for all past + future fillings until E85 flex-fuel sensor install. Knock-retard baseline below is a 93-octane baseline; "creep up on 93" prediction VOID. Prior major update: 2026-05-12 (Session 12 — Drive 11 captured = **first clean car-coupled Pi-powered drive post-B-063 fuse-box install**; new under-load records (147 km/h = 91 mph, 5441 RPM, 100% load); first clean **knock-retard signature characterization** — ECU pulls timing ~12° from cruise-avg 24° to high-load 12° in 4500-5000 RPM mid-range knock window, correctly recovering above 5000 RPM; engine grade-A healthy across expanded envelope; 91 octane behaviour documented as new tuning baseline. Pre-mod shelf grows to 4 driving entries (drives 6/7/8/11). Prior update 2026-05-08 (Session 9 — Drive 6 + Drive 7 first under-load capture).

## SPEC-WRITING DISCIPLINE — DO NOT CHANGE Markers

When writing tuning specs with exact values (thresholds, limits, vehicle-specific numbers), mark them explicitly:

**Format**: `[EXACT: value — DO NOT CHANGE]`

**Example**:
> - Danger: > [EXACT: 7000 RPM — DO NOT CHANGE] (factory redline for 97-99 2G, valve float risk above)

**Use for**: alert thresholds, vehicle-specific values (redline, boost limits), AFR targets, anything where wrong value = mechanical damage.
**Do NOT use for**: descriptive ranges, rationale text, example scenarios.

**Why**: Prevents downstream drift during PM→architect→dev handoff. No interpretation, no rounding, no "close enough."

---

## Table of Contents

1. [Reference Sources](#reference-sources)
2. [The Vehicle — 1998 Eclipse GST](#the-vehicle)
3. [4G63 Engine Specifications](#4g63-engine-specifications)
4. [OBD-II on the 2G DSM](#obd-ii-on-the-2g-dsm)
5. [Safe Operating Ranges](#safe-operating-ranges)
6. [This Car's Empirical Baseline](#this-cars-empirical-baseline)
7. [PID Interpretation Guide](#pid-interpretation-guide)
8. [Datalog Analysis Methodology](#datalog-analysis-methodology)
9. [Fuel Trim Analysis](#fuel-trim-analysis)
10. [Timing and Knock](#timing-and-knock)
11. [Boost and Turbo](#boost-and-turbo)
12. [Cooling System](#cooling-system)
13. [Fuel System](#fuel-system)
14. [ECMLink V3 Reference](#ecmlink-v3-reference)
15. [Modification Priority Path](#modification-priority-path)
16. [Common Failure Modes](#common-failure-modes)
17. [DSM-Specific Quirks and Gotchas](#dsm-specific-quirks)
18. [Tuning Glossary](#tuning-glossary)
19. [UPS HAT Dropout Characteristics (Drain 7 baseline)](#ups-hat-dropout-characteristics-drain-7-baseline) — *Pi-side power-mgmt, not engine tuning*
20. [Regression Fixture Lock-Down](#regression-fixture-lock-down) — *project hygiene; protect tuning-data pipeline test inputs*

---

## Reference Sources

### Primary Sources
| Source | URL / Location | What It Covers |
|--------|----------------|----------------|
| **DSMTuners.com** | https://www.dsmtuners.com | THE community resource for 2G DSM. Forums, build threads, tuning guides, wiring diagrams, vendor reviews. Decades of collective knowledge from thousands of DSM owners. |
| **ECMLink Documentation** | https://www.ecmlink.com | Official ECMLink V3 tuning software docs. Parameter definitions, tuning procedures, wiring guides. |
| **Mitsubishi TSBs** | Factory service manual | OEM specs, torque values, fluid capacities, wiring diagrams |
| **OBDLink Documentation** | OBDLink LX manual | Adapter specs, protocol support, AT commands |
| **Project Specs** | `specs/obd2-research.md`, `specs/grounded-knowledge.md` | Project-specific OBD-II research and safe operating ranges |

### Community Knowledge (DSMTuners Forum Threads)
| Topic | Thread/Section | Key Takeaway |
|-------|---------------|--------------|
| Fuel trim analysis | DSMTuners Fuel Trim Guide | +/-5% normal, >10% investigate, >15% danger |
| Safe boost levels | DSMTuners "Stock turbo limits" | 12 psi stock wastegate, 14-15 max on stock turbo with supporting mods |
| Crankwalk | DSMTuners FAQ | 7-bolt 4G63 (1995.5+) susceptible, 6-bolt (pre-1995.5) generally safe. Our 1998 is a 7-bolt. |
| Head gasket failures | Multiple threads | Common above 18-20 psi on stock head bolts. ARP studs recommended for big turbo |
| #4 lean condition | DSMTuners common issues | #4 cylinder runs lean — farthest from intake, shortest runner, hottest cylinder |
| MAF saturation | DSMTuners sensor limits | Stock MAF maxes out ~300 HP. Frequency clips at ~2700 Hz |
| Oil starvation | DSMTuners oiling mods | Hard cornering starves oil pickup. Baffle or windage tray recommended for track use |

### Additional Resources
| Source | What It Covers |
|--------|----------------|
| **Innovate Motorsports** | Wideband O2 sensor technology, AFR interpretation |
| **AEM Electronics** | Wideband controllers, gauge options |
| **Injector Dynamics** | Fuel injector data sheets, flow rates, dead times |
| **Walbro / DeatschWerks** | Fuel pump specifications and flow curves |
| **Garrett / Forced Performance** | Turbo maps, compressor efficiency, sizing |

---

## The Vehicle

> **THIS-car facts are migrating to atomic cards (SSOT) for the MrSpool RAG layer** — see [`vehicle.md`](vehicle.md) (index) + `cards/`. General 4G63 / DSM / tuning craft stays here in `knowledge.md`. ECU Identity is migrated; the rest follows during the RAG sprint (manifest in `vehicle.md`). See `rag-readiness-assessment.md` for the plan.

### 1998 Mitsubishi Eclipse GST (2G DSM)

| Attribute | Value |
|-----------|-------|
| **VIN** | 4A3AK54F8WE122916 |
| **Year** | 1998 |
| **Model** | Eclipse GST (turbo, FWD) |
| **Engine** | 4G63 DOHC Turbo |
| **Displacement** | 1,997 cc (2.0L) |
| **Transmission** | Manual (assumed) |
| **ECU** | 1997 DSM ECU (P/N **MD335287**), non-EPROM with ECMLink V3 flash modification — see [ECU Identity](#ecu-identity) below |
| **OBD-II Protocol** | ISO 9141-2 (K-Line) |
| **Generation** | 2G DSM (1995-1999) |
| **Odometer** | ~76,000 miles (as of 2026) |
| **Usage** | Summer only, garage stored winters. Low-stress duty cycle. |
| **Crankshaft** | 7-bolt (1995.5+ production) |

### ECU Identity

> **MIGRATED TO ATOMIC CARDS (SSOT) — 2026-05-29.** Authoritative ECU facts now live as one-fact-per-card under `cards/`, indexed by [`vehicle.md`](vehicle.md). This section was collapsed to a pointer to keep a single version of the truth (no parallel copies).
>
> - **Prior ECU** (stock, drives ≤24): [`cards/ecu-prior-md346675.md`](cards/ecu-prior-md346675.md)
> - **New ECU** (ECMLink, drives ≥25): [`cards/ecu-new-md335287.md`](cards/ecu-new-md335287.md)
>
> Nav summary: stock **MD346675** (1998 factory, never flashed) on drives ≤24 → swapped 2026-05-22 to ECMLink-flashable **MD335287** (1997 board) on drives ≥25 per the [ECMtuning workaround](https://www.ecmtuning.com/wiki/use_ecmlink_in_98_99_dsm). Full detail + capability boundaries in the cards.

### Current Modifications (Installed)
| Mod | Tuning Impact |
|-----|---------------|
| Cold air intake | Slight improvement in IAT, potential MAF calibration shift |
| Blow-off valve (BOV) | Prevents compressor surge between shifts, may cause slight rich condition on throttle close |
| Fuel pressure regulator | Allows base pressure adjustment, critical for injector sizing |
| AN-6 E85-compatible fuel lines | Full E85-rated fuel feed and return lines installed. Supports higher flow and ethanol. |
| Oil catch can | Reduces oil vapor in intake, cleaner combustion |
| Coilovers | No tuning impact (suspension only) |
| Engine/trans mounts (new, summer 2025) | Fresh mounts = solid drivetrain, no flex under boost. No tuning impact but clean data. |
| Luke clutch (new, summer 2025) | Professional shop install. Fresh clutch = no slip under boost. Critical for reliable WOT datalog pulls. Full "while you're in there" service done (RMS, TOB, pilot bearing). |
| Tie rods (new, summer 2025) | No tuning impact (steering/suspension) |

### Dealer Service (Early 2025)
- Full timing belt and maintenance service performed at Mitsubishi dealer
- Timing belt verified fresh — well within service interval (60k mi / 5 yr)
- Mechanical baseline is solid: belts, clutch, mounts, drivetrain all recently serviced

### Parts In Hand (Not Yet Installed)
| Part | P/N / Details | Status |
|------|---------------|--------|
| **ECMLink V3** | Flash-based ECU tune | In box, back seat. Priority #1 install. |
| **Walbro GSS342G fuel pump** | 255lph, E85-rated | In hand. Drop-in replacement for stock in-tank pump. |
| **GM Flex Fuel Sensor** | Continental/GM ethanol content sensor | In hand. Wire inline on fuel feed before rail. 3 wires: 12V switched, ground, signal to ECMLink. |

### Parts To Order (Summer 2026)
| Part | Recommendation | Est. Cost | Priority | Notes |
|------|----------------|-----------|----------|-------|
| **Wideband O2 sensor** | AEM 30-0300 X-Series UEGO | ~$200 | Required | CIO approved. Gauge + controller in one. 0-5V output to ECMLink wideband input. Requires M18x1.5 bung welded in downpipe (~$20-30 at exhaust shop). |
| **Fuel injectors** | Injector Dynamics ID550 (550cc) | ~$350-400/set | Required | Minimum size for E85 on stock turbo. Well-characterized dead times for ECMLink. Not yet ordered. |
| **3" high-flow catted downpipe** | Quality aftermarket (see exhaust notes) | ~$200-400 | Required | Single biggest bolt-on power gain. MUST be catted (high-flow metallic substrate) — CIO is in Illinois with mandatory biennial OBD-II emissions testing. Catless will throw P0420 and fail emissions. Order with wideband bung pre-welded to save the exhaust shop trip. |
| **Cat-back exhaust (2.5-3")** | Mandrel-bent, quality muffler | ~$300-500 | Required | Completes exhaust from cat back. Mandrel-bent to maintain diameter through bends. Stock 2.25" crushed-bend piping restricts flow on a tuned car pushing more air/fuel on E85. |

### Nice To Have (Not Required, But Recommended)
| Part | Recommendation | Est. Cost | Notes |
|------|----------------|-----------|-------|
| **GM 3-bar MAP sensor** | GM 12223861 or equivalent | ~$30-40 | Enables ECMLink closed-loop boost control and accurate boost logging. Required for speed density mode. 3 wires: 5V ref, ground, signal to ECMLink MAP input. |
| **Mechanical boost gauge** | Prosport, GlowShift, or Autometer 52mm | ~$30-50 | Visual boost reference while driving. T-fitting off intake manifold vacuum source, 1/8" nylon line through firewall. Dead accurate, no electronics. |
| **Dual A-pillar gauge pod** | 52mm dual pod (fits 2G Eclipse) | ~$20-30 | Mount for boost gauge + AEM wideband gauge together. Classic DSM setup. |
| **Vacuum line + T-fittings** | 1/8" nylon line, barb T-fittings | ~$10 | Plumbing for boost gauge and MAP sensor. |

**Note on boost control**: ECMLink V3 has built-in boost control via the stock boost control solenoid (BCS) already on the car. A standalone EBC (GReddy Profec, AEM Tru-Boost, etc.) is redundant — skip it and save $200-400. ECMLink boost control gives you boost-by-gear, boost-by-RPM, wastegate duty cycle, and closed-loop control. The GM 3-bar MAP sensor above makes ECMLink boost control more accurate but is not strictly required to get started.

### Summer 2026 Install Plan (CIO-Approved Order)
| Step | What | Prerequisite | Safety Note |
|------|------|-------------|-------------|
| 1 | Walbro GSS342G fuel pump install | None | Safe on pump gas, no tune change needed. Drop-in. |
| 2 | Wire GM flex fuel sensor (inline, don't activate) | Pump installed | Hardware only — sensor sits idle until ECMLink reads it. |
| 3 | **3" high-flow catted downpipe + cat-back exhaust** | None | Can be done same day as pump. Order downpipe with wideband bung pre-welded. **MUST be catted — Illinois emissions.** Keep stock downpipe and cat-back in garage for emissions fallback. |
| 4 | ECMLink V3 install + base tune on pump gas | Pump + exhaust done | Set base timing 12 deg BTDC with timing light. Learn the software on gasoline first. |
| 5 | Wideband O2 install (AEM 30-0300) | ECMLink running | Screw into pre-welded bung on new downpipe, mount gauge, wire 0-5V signal to ECMLink. |
| 6 | Tune on pump gas with wideband data | Wideband installed | Get comfortable with ECMLink, verify fueling across RPM/load. |
| 7 | Swap injectors (ID550 550cc) + rescale in ECMLink | Stable pump gas tune | Rescale injector flow rate and dead times in ECMLink. Re-tune on pump gas. |
| 8 | Build E85 fuel map, enable flex fuel, start blending | Everything above complete | **DO NOT put E85 in tank until this step.** ECMLink reads sensor, interpolates between gas and E85 maps. |

**SAFETY RULE: No E85 in the tank until Step 8. The stock ECU cannot fuel for E85. Running E85 without a proper tune WILL cause catastrophic lean condition.**

### Illinois Emissions Compliance
CIO is in Illinois — mandatory OBD-II emissions test every 2 years.

**How Illinois tests a '98 Eclipse:**
- OBD-II port scan only (no tailpipe sniffer for OBD-II equipped vehicles)
- Checks for stored DTCs (diagnostic trouble codes) — any emissions-related code = fail
- Checks readiness monitors — all monitors must be "ready" (complete)
- Visual inspection of emissions equipment may apply

**What this means for our mods:**
| Concern | Solution |
|---------|----------|
| **Catless downpipe** | **DO NOT USE.** Will throw P0420 (catalyst efficiency below threshold). Guaranteed emissions fail. Use high-flow catted downpipe only. |
| **ECMLink CEL codes** | ECMLink can disable specific CELs. However, disabling the catalyst monitor may cause the readiness monitor to report "not ready" = fail. Keep the cat working, keep the monitor happy. |
| **Larger injectors** | Properly tuned in ECMLink = clean burn = no emissions codes. Poorly tuned = rich/lean codes. Tune must be dialed in. |
| **E85 / flex fuel** | E85 burns clean. With a proper tune, no emissions impact. The flex fuel sensor is invisible to the OBD-II emissions scan. |
| **Wideband O2 (AEM 30-0300)** | Independent system — does NOT replace the stock narrowband O2 sensors. Both front and rear stock O2 sensors must remain connected and functional for emissions monitors. |
| **Fallback plan** | Keep stock downpipe and cat-back in garage. If any emissions concern arises, bolt stock exhaust back on, clear codes, complete drive cycle, pass test, swap back. 2-hour job. |

**EMISSIONS RULE: All mods must pass Illinois OBD-II emissions. No catless pipes. No disabled readiness monitors. Stock O2 sensors stay connected. Keep stock exhaust as fallback.**

---

## 4G63 Engine Specifications

### Block and Rotating Assembly
| Spec | Value | Notes |
|------|-------|-------|
| **Bore** | 85.0 mm (3.35") | |
| **Stroke** | 88.0 mm (3.46") | Slightly oversquare — good for revving |
| **Compression Ratio** | 8.5:1 (turbo) | Low compression for boost headroom |
| **Displacement** | 1,997 cc | |
| **Block Material** | Cast iron | Strong, heavy, handles boost well |
| **Firing Order** | 1-3-4-2 | |
| **Cylinder Numbering** | #1 at timing belt end (passenger side) | #4 is rear, closest to firewall — runs hottest |
| **Crankshaft Type** | 7-bolt (1998) | Susceptible to crankwalk. See Failure Modes. |
| **Rod Type** | Stock I-beam, powder metal | Good to ~400 HP with proper tune. Limit is detonation, not rod strength (usually). |
| **Piston Type** | Cast aluminum | Adequate for stock boost levels. Forged needed above ~18-20 psi |

### Valvetrain
| Spec | Value |
|------|-------|
| **Configuration** | DOHC 16-valve |
| **Intake Valve Size** | 33.0 mm |
| **Exhaust Valve Size** | 29.0 mm |
| **Timing** | Belt-driven, hydraulic lash adjusters |
| **Timing Belt Interval** | 60,000 miles (INTERFERENCE engine — belt failure = bent valves) |
| **Cam Duration** | 248 intake / 248 exhaust (stock) |

### Timing Belt System (CRITICAL)

| Spec | Value |
|------|-------|
| **Belt type** | Toothed rubber, 150 teeth |
| **Replacement interval** | Every 60,000 miles — DO NOT SKIP |
| **Interference engine** | **YES** — belt failure = pistons hit valves = catastrophic damage |
| **Balance shaft belt** | Separate belt, 102 teeth (many tuners remove balance shafts entirely during builds) |
| **Tensioner** | Hydraulic auto-tensioner (ALWAYS replace with belt) |
| **Idler pulleys** | 2 pulleys (ALWAYS replace with belt) |
| **Water pump** | Driven by timing belt — replace during belt change |
| **Timing marks** | Cam sprocket marks align with valve cover mating surface; crank sprocket mark aligns with oil pump housing |

**On a 1998 car**: This belt has been replaced at least once (hopefully multiple times). If belt age/mileage is unknown, replace it before any tuning work. A $200 belt kit is cheap insurance against a $3,000+ engine rebuild.

### Fluids and Capacities
| Fluid | Capacity | Spec |
|-------|----------|------|
| **Engine Oil** | 4.5 quarts with filter | 5W-30 (OEM), many DSM owners run 5W-40 or 10W-40 synthetic for turbo use |
| **Coolant** | ~8.5 quarts total system | 50/50 mix, Mitsubishi long-life or equivalent |
| **Transmission** | ~2.3 quarts (manual) | GL-4 75W-85 synthetic recommended |
| **Transfer Case** | ~0.6 quarts (AWD only, N/A for GST) | — |

### Power Output
| Condition | HP (crank) | Torque | Notes |
|-----------|-----------|--------|-------|
| **Stock** | 210 HP @ 6,000 RPM | 214 lb-ft @ 3,000 RPM | Factory rating |
| **Stock turbo, bolt-ons, tuned** | 230-260 HP | 240-280 lb-ft | With ECMLink, exhaust, intake, boost increase to 14-15 psi |
| **16G turbo, stock internals** | 280-320 HP | 280-320 lb-ft | Sweet spot for stock bottom end |
| **20G turbo, stock internals** | 300-380 HP | 300-360 lb-ft | Pushing limits of stock rods/pistons |
| **Built motor** | 400-600+ HP | 400-500+ lb-ft | Forged internals, big turbo, E85, built trans |

---

## OBD-II on the 2G DSM

### Protocol: ISO 9141-2 (K-Line)

This is the **slowest** OBD-II protocol. Everything about data collection is constrained by this.

| Constraint | Value | Impact |
|------------|-------|--------|
| **Baud rate** | 10,400 bps | ~25-50x slower than CAN bus |
| **Communication** | Half-duplex, sequential | One PID at a time, no parallel requests |
| **Per-PID round-trip** | 120-200 ms (real-world) | Cannot be sped up |
| **Max PIDs/sec (BT)** | 4-5 | Hard limit of the protocol + Bluetooth overhead |
| **Max PIDs/sec (wired)** | 6-8 | Slightly faster without BT latency |

### PID Update Rate vs Count Tradeoff

This is the fundamental constraint of our system. More PIDs = slower updates per PID.

| PIDs Polled | Per-PID Update Rate | Full Cycle Time |
|-------------|--------------------:|----------------:|
| 1 | 5-6 Hz | 170-200 ms |
| 3 | 1.7-2 Hz | 500-600 ms |
| 5 | 1-1.2 Hz | 850 ms - 1 sec |
| 10 | 0.5-0.6 Hz | 1.7-2 sec |
| 15 | 0.33-0.4 Hz | 2.5-3 sec |

**Tuning Implication**: At 5 PIDs, we get ~1 Hz update rate. That's acceptable for monitoring but NOT for tuning. Real tuning needs 20-50 Hz data — which only ECMLink can provide. OBD-II on this car is a **monitoring** tool, not a tuning tool.

### Supported PIDs (Confirmed for 2G 4G63T)

#### Tier 1: High Confidence (Required by OBD-II, physically wired)

| PID | Name | Units | Tuning Relevance | Session 23 (2026-04-19) |
|-----|------|-------|------------------|-------------------------|
| 0x04 | Calculated Engine Load | % | HIGH — load + fuel trim = lean detection | ✅ supported |
| 0x05 | Engine Coolant Temp | C | HIGH — engine protection, thermostat function | ✅ supported |
| 0x06 | Short-Term Fuel Trim (B1) | % | HIGH — real-time lean/rich indicator | ✅ supported |
| 0x07 | Long-Term Fuel Trim (B1) | % | HIGH — persistent fuel correction drift | ✅ supported |
| 0x0B | Intake Manifold Pressure | kPa | **CAUTION** — may read MDP, not true MAP. See caveat below. | ❌ **CONFIRMED unsupported** on this 2G ECU |
| 0x0C | Engine RPM | rpm | HIGH — fundamental reference axis | ✅ supported |
| 0x0D | Vehicle Speed | km/h | Context — gear detection, load state | ✅ supported |
| 0x0E | Timing Advance | deg BTDC | HIGH — knock indicator (ECU pulls timing when it detects knock) | ✅ supported |
| 0x0F | Intake Air Temperature | C | Medium — heat soak detection, intercooler efficiency | ✅ supported |
| 0x10 | MAF Air Flow Rate | g/s | HIGH — airflow measurement, MAF saturation detection | ✅ supported |
| 0x11 | Throttle Position | % | HIGH — driver input, WOT detection | ✅ supported |
| 0x14 | O2 Sensor B1S1 (upstream) | V | **LIMITED** — narrowband, only rich/lean toggle at stoich | ✅ supported |

#### Tier 2: Likely Supported (Lower Confidence — not yet probed on this car)

| PID | Name | Notes |
|-----|------|-------|
| 0x01 | MIL + DTC count | Check engine light bit + count of stored codes. Test in Sprint 14 (US-199). |
| 0x03 | Fuel System Status | Open/closed loop detection. Test in Sprint 14 (US-199). |
| 0x0A | Fuel Pressure | ❌ **CONFIRMED unsupported** on this 2G ECU (Session 23) |
| 0x15 | O2 Sensor B1S2 (downstream) | Catalyst efficiency monitor. Test in Sprint 14 (US-199 probe). |
| 0x1F | Run Time Since Start | seconds. Test in Sprint 14 (US-199). |
| 0x33 | Barometric Pressure | kPa. Test in Sprint 14 (US-199). |
| 0x42 | Control Module Voltage | V — ❌ **CONFIRMED unsupported** on this 2G ECU (Session 23). Use ELM327 `ATRV` / `ELM_VOLTAGE` adapter-level query instead. |

#### Battery Voltage — NOT a standard OBD-II PID on this car

Because PID 0x42 is unsupported on the 2G ECU, battery voltage for the primary display comes from the **ELM327 adapter's `ATRV` command** (not an OBD-II Mode 01 PID at all — it's an adapter function). Every ELM327-compatible adapter measures the voltage on the OBD-II port's pin 16 and exposes it via `ATRV`.

- python-obd access: `obd.commands.ELM_VOLTAGE`
- Returns: battery voltage at the OBD port (engine off ≈ battery SOC; engine running ≈ charging system output)
- Resolution: ~0.1V typical
- **Not subject to OBD-II bandwidth constraints** — adapter-local measurement, responds instantly

Sprint 14 US-199 adds this to the Pi poll set as the battery voltage source.

### CRITICAL CAVEAT: PID 0x0B (Manifold Pressure)

**The 2G 4G63T does NOT use a traditional MAP sensor for fuel metering.** It uses:
- **MAF sensor** — primary fuel calculation input
- **MDP sensor** (Manifold Differential Pressure) — monitors EGR system, NOT for boost measurement
- **Barometric pressure sensor** — in air filter housing

**PID 0x0B will likely report MDP data, which is NOT accurate boost pressure.** For reliable boost measurement on this car, you need:
1. Aftermarket MAP sensor (GM 3-bar is DSM community standard)
2. Mechanical boost gauge
3. ECMLink with MAP sensor input wired

**Never use PID 0x0B raw data to set boost-related alerts on this vehicle without first validating what the ECU is actually reporting.**

### What OBD-II CANNOT Tell Us (Critical Gaps)

| Parameter | Why We Can't Get It | How to Get It |
|-----------|--------------------|----|
| **Knock count/sum** | Not an OBD-II standard PID. 2G ECU doesn't expose it. | ECMLink V3 only |
| **Actual AFR (wideband)** | Stock O2 is narrowband — only toggles at 14.7:1 | Wideband O2 + ECMLink or standalone gauge |
| **Injector duty cycle** | Not OBD-II accessible | ECMLink V3 only |
| **True boost pressure** | MDP ≠ MAP on this car | Aftermarket MAP sensor |
| **Oil pressure** | Not wired to ECU | Aftermarket gauge/sensor |
| **Oil temperature** | Not wired to ECU | Aftermarket gauge/sensor |
| **EGT (exhaust gas temp)** | Not wired to ECU | Aftermarket EGT probe |
| **Knock retard (degrees)** | Not OBD-II accessible | ECMLink V3 only |

### Capability Probe — Methodology and Tooling

The OBDLink LX dongle is **not** the bottleneck for getting ECU-internal tuning data — the dongle can forward arbitrary bytes via ELM327 raw-mode commands. The walls stack as:

1. **OBD-II protocol surface** — bounded by what the 1998 ECU implements. Stock 2G doesn't speak Mode 22 (vendor enhanced); it acknowledges Mode 09 (vehicle info) at the bitmap level but exposes zero sub-PIDs.
2. **MUT-II protocol** — Mitsubishi factory diagnostic, uses different init/framing, NOT what ELM327 firmware speaks natively. ECMLink Logger uses MUT-II with ECMLink-specific RAM-peek commands against ECMLink-exposed RAM addresses. That's the only practical path to per-cylinder knock retard, knock sum, base spark advance, and target AFR map. **Requires the ECMLink USB-to-serial cable + PC software, not the OBDLink-via-Pi pipe.**
3. **K-line bandwidth** — 10.4 kbps absolute ceiling regardless of what's queryable.

**Probe script**: `offices/tuner/scripts/probe_obd_capabilities.sh`. Run any time the ECU changes (swap, EPROM update, calibration change). Pauses `eclipse-obd` for ~60 sec, enumerates Mode 01 supported PIDs by name, attempts Mode 09 (VIN/calibration ID/CVN/ECU name), speculatively probes Mode 22 at common Mitsubishi/DSM addresses, and dumps adapter ATI/ATRV/AT@1/STDI info. Service restart triggers a new drive_id — expected, not a bug.

### 2026-05-22 — Capability Probe Result (Post-Modified-EPROM Swap)

CIO swapped from the stock ECU (MD346675) to the ECMLink-flash-modified ECU (MD335287). Probe run via `probe_obd_capabilities.sh` at 18:51:43Z during warm idle on Drive 25.

**Mode 01 (standard PIDs)**: 16 supported — **same set as pre-swap**. Same 3 historical unsupported (0x0A Fuel Pressure, 0x0B Intake Manifold Pressure, 0x42 Control Module Voltage). **Modified EPROM did NOT expand the standard OBD-II PID surface.**

**Mode 09 (calibration identity)**: ECU acknowledges Mode 09 bitmap exists but returns NO RESPONSE on 0902 (VIN), 0904 (Calibration ID), 0906 (CVN), 090A (ECU Name). Cannot fingerprint the EPROM via OBD-II. Normal for a 1998 ECU — Mode 09 VIN requirement came with later OBD-II revisions (~2008 with CAN).

**Mode 22 (vendor enhanced)**: NOT IMPLEMENTED at any of 8 probed addresses (2202, 2204, 2210, 2220, 2240, 2280, 22F101, 22F190). **Confirms the OBDLink-via-Pi pipe cannot reach ECMLink-internal data on this ECU.** ECMLink cable + PC software is the only path for the knock/AFR/advance goldmine.

**Bonus discoveries** (these existed pre-swap too but were never enumerated in `knowledge.md` — surfacing here for future use):

- **Mode 02 freeze-frame**: 16 PIDs mirroring Mode 01 (DTC_RPM, DTC_COOLANT_TEMP, DTC_TIMING_ADVANCE, etc.). State-at-DTC-trigger data is queryable. **Worth wiring into future diagnostic enrichment**: when MIL_ON goes high, snapshot the freeze-frame for forensic analysis.
- **Mode 06 monitor results**: MIDS_A bitmap supported. Catalyst efficiency, O2 heater response time, EGR flow monitor results. Useful for long-term emissions-health tracking. MIDs need separate enumeration.
- **Mode 03/07**: stored / pending DTC enumeration. Project currently counts DTCs only; could pull actual codes.

**Adapter inventory** (logged for record):
- ELM327 firmware **v1.4b**
- OBDLink **LX BT r2.1.1**
- Manufacturer: OBD Solutions LLC (AT@1)
- ATRV reports battery voltage at OBD port pin 16 (independent of K-line bandwidth)

### ⚠ NEW-ECU CAVEAT — SPEED PID reads ~2× actual ground speed (caught 2026-05-22, Session 19)

Drive 26 (first city-driving telemetry on new ECU) reported SPEED peak 84 mph. CIO confirmed actual ground speed was city-roads tip-in (~40 mph estimated). Gear math at RPM 3,788 places 2nd-gear ≈ 39 mph, 3rd-gear ≈ 55 mph — consistent with CIO's report, inconsistent with the 84 mph reading. **The new ECU's SPEED PID reads approximately 2× actual ground speed.**

Sanity check against prior-ECU Drive 18: RPM 3,937 / SPEED 60 mph = 3rd-gear math fit (theoretical 57 mph). The prior ECU's SPEED PID was calibrated correctly. The discrepancy is new-ECU-specific.

**Likely cause**: the new ECU's ECMLink tune has different VSS (vehicle speed sensor) calibration constants — non-OEM tire-size assumption, non-OEM speedometer-gear-ratio assumption, or different VSS pulse-per-rev expectation. Common for aftermarket tunes if the tuner anticipated different tires/gearing. (Note: the stock ECU MD346675 read SPEED correctly, factor 1.0 — this drift is specific to the new ECU's tune.)

**Until verified with a GPS-correlation drive**:
- Treat SPEED on new ECU as **directional only — divide by ~2 for ground-truth estimate**.
- Any analytics keyed off SPEED (distance, avg speed, gear inference) will be off by the same factor.
- **None of the engine-grade analysis depends on SPEED** (RPM, LOAD, MAF, TIMING, STFT, COOLANT all measured independently). Engine assessments remain trustworthy.

**Calibration check** (2-min exercise on next drive): cruise at a GPS-verified known speed (e.g., 30 mph on a straight road), record the SPEED PID reading at that moment, derive correction factor. Update this caveat with empirical ratio once captured.

---

## Safe Operating Ranges

### By Modification Level

These ranges are grounded in DSMTuners community consensus, manufacturer specifications, and decades of collective DSM ownership experience.

#### Current Setup: Stock Turbo, Stock Internals, No Wideband, No ECMLink

This is the most conservative level. We have limited monitoring capability.

| Parameter | Normal | Caution | Danger | Action |
|-----------|--------|---------|--------|--------|
| **Coolant Temp** | 185-205F (85-96C) | 205-215F (96-102C) | >220F (>104C) | STOP. Head gasket risk. Pull over, let cool. |
| **STFT (Bank 1)** | -5% to +5% | +/-5% to +/-10% | >+/-15% | Investigate immediately. Large positive = lean = danger. |
| **LTFT (Bank 1)** | -5% to +5% | +/-5% to +/-8% | >+/-10% | Persistent drift. Vacuum leak, failing sensor, or fuel delivery issue. |
| **RPM** | 700-800 idle, 0-6500 driving | 6501-7000 | >7000 (redline) | 97-99 2G factory redline is 7000 RPM. Valve float risk above on stock springs. |
| **Engine Load** | 15-25% idle, 30-50% cruise | 70-85% | >90% sustained | High load + positive STFT = lean under boost. |
| **Timing Advance** | 10-15 idle, 8-20 cruise | <8 under load | <5 or negative | ECU pulling timing = knock detection. Investigate fuel quality, carbon buildup. |
| **Coolant Temp (alert)** | — | 210F (99C) | 220F (104C) | Two-tier alert: warn at 210, critical at 220 |
| **IAT** | 20-40C (68-104F) | 40-55C (104-131F) | >60C (>140F) | Heat soak. Power loss. Intercooler upgrade needed at this point. |
| **MAF (g/s)** | 2-4 idle, varies with RPM/load | — | >~150 g/s | MAF saturation territory. Stock MAF tops out around here. |
| **Battery Voltage** | 13.5-14.5V running | 12.5-13.5V or >14.8V | <12.0V or >15.0V | Low = charging issue. High = regulator failure. |
| **O2 B1S1** | Oscillates 0.1-0.9V at 1-3 Hz | Stuck lean (<0.3V) or rich (>0.7V) | Fixed voltage | Lazy or dead O2 sensor. ECU can't closed-loop fuel. |

#### With ECMLink V3 + Wideband (Future)

| Parameter | Normal | Caution | Danger |
|-----------|--------|---------|--------|
| **AFR WOT (wideband)** | 11.0-11.8:1 | 12.0-12.5:1 | >12.5:1 LEAN or <10.0:1 overly rich |
| **AFR Cruise** | 14.5-15.0:1 | — | >16.0:1 misfire territory |
| **AFR Idle** | 14.7:1 +/-0.3 | — | Erratic = vacuum leak |
| **Knock Count** | 0 | 1-3 per WOT pull | >5 per pull |
| **Knock Sum** | 0-1 | 2-3 | >4 |
| **Injector Duty Cycle** | <80% | 80-85% | >85% — need bigger injectors |
| **Boost (stock turbo)** | 10-12 psi | 13-14 psi | >15 psi |
| **AirFlowPerRev** | ~0.27 idle | — | Significant deviation = metering issue |

#### With Upgraded Turbo (16G/20G, Future)

| Parameter | 16G Safe | 20G Safe | Notes |
|-----------|----------|----------|-------|
| **Boost** | 16-18 psi | 18-22 psi | With supporting fuel system and tune |
| **AFR WOT** | 11.0-11.5:1 | 10.8-11.5:1 | Richer is safer on pump gas |
| **EGT** | <1400F | <1500F | Monitor with aftermarket probe |
| **Injectors needed** | 550cc minimum | 660cc+ | Stock 450cc won't keep up |
| **Fuel pump** | Walbro 255lph | Walbro 450lph or AEM 340lph | Stock pump dies above ~300 HP |

---

## This Car's Empirical Baseline

> These are observed values from **this specific Eclipse** (1998 GST, 76k mi, stock turbo TD04-13G, stock internals, STOCK factory tune (MD346675, CIO-confirmed), coilovers/mounts/clutch/tie-rods fresh, no wideband, no ECMLink). Use these as the **comparison baseline** when grading future captures — community data informs us, this car's data grounds us.
>
> **Always check these against the current capture. A healthy engine returns to its own baseline.**

### Pre-Mod Baseline Shelf — `mod_state = premod`

> **Status as of 2026-05-12: 7 drives on the shelf (drives 3-7 + Drive 8 added 2026-05-10 + Drive 11 added 2026-05-12). Drive 9 + Drive 10 captured but HELD OUT from shelf (Drive 9 hardware-compromised; Drive 10 too short). Shelf is OPEN — accepting new drives until Walbro pump installs. BLOCKER CLEARED: B-063 fuse-box buck converter installed + validated on Drive 11. Car-coupled-fuse-box power era is now ACTIVE.**

The pre-mod baseline shelf is the canonical body of empirical data captured on the car in its **current bolt-on configuration** (stock turbo, stock internals, STOCK factory tune (prior ECU MD346675 — CIO-confirmed stock), current bolt-ons listed in *The Vehicle* section). All drives on this shelf share `mod_state = premod` per the [Spec 1 mod_state enum](../../offices/pm/inbox/2026-05-09-from-spool-three-specs-mod-state-drive-annotations-drive-summary-contract.md). Future-Spool grades any *future* `premod` capture against this shelf; once the first mod ships (Walbro pump per the Summer 2026 install plan), the shelf **closes** and a new shelf opens for the next `mod_state`.

**Why this matters**: comparing a future post-Walbro WOT pull against a pre-Walbro WOT pull without the shelf-tag is a category error. The shelf is the project's "what does healthy look like in *this* mod state" reference, frozen at the moment we move to the next state.

#### Current shelf contents

| drive_id | Date | Type | Authoritative for | Annotation source |
|---:|---|---|---|---|
| 3 | 2026-04-23 | parked-idle system test | First real engine data; LTFT -6.25% lock observed; cold-warm cycle | `drive-annotations.md` + `obd2db.drive_annotations` |
| 4 | 2026-04-29 AM | parked-idle system test | Pre-jump-start half of LTFT adaptation story | same |
| 5 | 2026-04-29 PM | parked-idle system test (post-jump) | **AUTHORITATIVE WARM-IDLE BASELINE** (idle-only, NOT driven). 489 samples/PID. Active LTFT re-learn captured. | same |
| 6 | 2026-05-08 AM | **first real driving capture** (cold-start city) | Cold-warm-up curve under driving load, idle LTFT re-lock at -6.25%, fuel system stability at low tank | same |
| 7 | 2026-05-08 PM | **first under-load capture** (highway + WOT pull) | **AUTHORITATIVE UNDER-LOAD BASELINE.** WOT to 100% load, MAF 158.69 g/s peak, timing 34° BTDC, no knock pull, fresh-fill [EXACT: 93 octane — DO NOT CHANGE] (corrected 2026-05-15; see Fuel-Grade Correction note below) | same |
| 8 | 2026-05-09 PM | cold-start city/highway, portable-inverter Pi power | True cold-start (coolant 23→92°C, ambient 75°F). Mixed city/highway, no WOT. 8,268 rows @ 459 rows/min. **NOT car-coupled — Pi was on its stock 5A supply via camping-battery AC inverter (same power model as Drives 6+7).** | same |
| 11 | 2026-05-12 AM | **first clean car-coupled drive post-B-063** (cold-start mixed city/highway with multiple boost pulls) | **AUTHORITATIVE KNOCK-RETARD CHARACTERIZATION.** 23:27 min, **10,839 rows @ 462 rows/min** (new project rows/min record). Cold-start (IAT 12→27°C, coolant 34→93°C). 5441 RPM peak / 147 km/h ≈ 91 mph / 100% engine load / MAF 135 g/s peak / 68.6% peak throttle. **Multiple boost pulls captured with ECU knock-retard signature**: cruise timing avg 24.5°, high-load (>80%) timing avg 12-13° — 10-15° of retard under boost. Specific knock event 01:22:30Z: timing dropped 16° in 3 sec at 4707 RPM, recovered to 23° above 5000 RPM (4G63 mid-range knock window). Fuel system pegged rich (O2 0.92-0.96V) under boost — correct safety target. No DTCs, no MIL, no thermal/fueling concerns. **B-063 fuse-box buck converter validated under sustained drive load.** | same (fuel grade [EXACT: 93 octane — DO NOT CHANGE] corrected 2026-05-15, ambient ~12°C from IAT) |

**HELD OUT (captured but NOT on the shelf)**:
- **Drive 9** (2026-05-10 early AM, ~30 min city pizza run) — USB-C connection worked loose; Pi cycling between wall and battery throughout drive; capture rate degraded 12× (36 rows/min). Hardware-induced data quality issue, not engine behavior. Engine itself fine (no DTCs, no MIL).
- **Drive 10** (2026-05-10 early AM, 2:10 garage pull-in) — too short for tuning use. Drain id=12 opened 8 sec into drive (smoking-gun confirmation of USB-C undersizing). Captured for completeness only.

Drives 3–5 are **idle-only / parked system tests** — they hold idle-cell data only, and are NOT comparable to load-cell data from drives 6–8. Drives 6, 7, 8 are the only valid driving captures on the shelf. Drives 9 and 10 are held out per above.

#### Per-drive details

Subsections below give the per-drive parameter tables and interpretation anchors. **Annotations (fuel grade, level, ambient, intent, etc.) live in `offices/tuner/drive-annotations.md` + `obd2db.drive_annotations`** — this section captures the OBD telemetry side, the annotations file captures the context side. Read both together for any drive analysis.

#### Rules for the shelf

1. **A drive joins the shelf when**: `mod_state = premod` at drive_start AND `drive_summary.is_real = TRUE` AND CIO seat-of-pants reports no anomalies. Manual review by Spool is required for promotion to "authoritative" status — auto-add is OK for the catalog, but "authoritative for X" tags are Spool's call.
2. **The shelf closes when**: the first non-`premod` mod is installed. The most recent `premod` drive at that moment becomes the **frozen shelf** — no more drives admitted. A new shelf opens for the new `mod_state`. The frozen pre-mod shelf becomes the historical reference for "what this car was before mods."
3. **A drive on the shelf is RETIRED only if**: a defect is later discovered that contaminated the data. Retire by adding a "RETIRED" row to the table above with rationale; do not delete the row from the database.
4. **Comparisons across shelves require explicit Spool sign-off** — pre-mod vs ECMLink-base data should not be averaged in any AI prompt or analytics rollup without a tuner-side review of whether the comparison is valid.

#### Wiring milestone — bench-tethered → car-coupled Pi power transition (2026-05-09)

The pre-mod shelf splits into THREE power-state eras (with a fourth pending):

| Era | Drives | Pi power source | Key-state coupling |
|---|---|---|---|
| **Bench-tethered (true wall AC)** | 3, 4, 5 | Pi at bench, wall AC + UPS HAT | INDEPENDENT — drives were parked-idle system tests anyway, no actual driving |
| **Portable inverter (camping-battery AC)** | 6, 7, 8 | Pi's stock 5A supply, plugged into a camping-battery + inverter setup; CIO had the portable battery in the car for the drive | INDEPENDENT — CIO unplugged manually to simulate "car off" / drain tests |
| **Car-coupled stereo USB-C** | 9 (compromised), 10 (compromised) | Stereo head unit's key-switched USB-C output (≤3A capacity) | COUPLED — key-on = Pi-on; key-off = Pi-on-UPS-then-graceful-shutdown. **PATH IS UNDERSIZED — both drives failed validation.** |
| **Car-coupled fuse-box wired (ACTIVE 2026-05-12)** | 11+ | 12V→5V/5A buck converter on switched fuse-box circuit (Mike-DIY install 2026-05-12) | COUPLED — same as USB-C but with adequate current capacity. **Drive 11 validated: one 5-sec AC blip during 23 min drive vs Drives 9/10's constant flicker.** |

**Why this transition matters for tuning interpretation**:

1. **Cold-boot Pi every key-on (car-coupled era only)** — drives 3-8 had a Pi that was already running before drive_start (bench or portable inverter). Drives 9+ have a Pi that cold-boots at key-on. Initial-seconds capture behavior differs (TD-036 "orchestrator blocks on initial BT-connect" gets exercised every drive — may delay first telemetry rows by up to 30s).
2. **First few seconds of every drive may be missing data (car-coupled era only)** — until the Pi finishes booting and DriveDetector wires up. Compare row counts in the first 30s of car-coupled drives vs the first 30s of bench/inverter-tethered drives; expect car-coupled to have fewer rows in that window.
3. **Drain events fire on every key-off (car-coupled era only)** — drives 3-8 had drains only when CIO deliberately unplugged for drill purposes. Drives 9+ have ≥1 drain per drive cycle. The `battery_health_log` table fills ~10× faster going forward.

**Hardware blocker CLEARED 2026-05-12**: B-063 fuse-box buck converter installed and validated on Drive 11 (one 5-sec AC blip mid-drive vs Drives 9/10's constant flicker — buck holds rock-steady at car system voltage 14.5V). Car-coupled-fuse-box path is now the active power era for all future drives. The car-coupled-stereo-USB-C path (Drives 9-10) is permanently retired.

#### Outstanding shelf gaps (drives we still need before Walbro install)

- **Sustained WOT** (>10 sec under load) — Drives 7 + 11 had brief pulls but not sustained; Drive 11 peaked at 68.6% throttle (not pinned). Need a longer high-load window for thermal-under-load behavior.
- **Hot-soak then re-start** — capture heat-soak fueling. >20 min hot drive + 10 min hot-soak + restart.
- **Wet-pavement under-load capture** — Drives 6 + 7 + 11 were dry. Wet-pavement under-load tells us whether traction events confound fueling/timing observations.
- **Cold-engine + WOT** — Drive 7 was warm-restart WOT; Drive 11 was cold-start but with conservative 68.6% throttle. Cold-engine WOT (not recommended for engine health, but informative) shows enrichment differences.
- ~~**93 octane A/B comparison**~~ **RETIRED 2026-05-15 (CIO fuel-grade correction)** — the entire shelf was already on [EXACT: 93 octane — DO NOT CHANGE] fresh-fill, not 91. No A/B comparison possible without a deliberate 91-octane run, which CIO will not do (93 standard until E85 sensor). The knock-retard baseline IS the 93-octane reference.
- **MAP PID (PID 0x0B) not currently captured** — without manifold absolute pressure, we cannot quantify boost pressure (psi) during pulls. Filed as feature request to PM 2026-05-12 (ride-along V0.27.7 OR V0.28.0 feature sprint). Until landed, boost inferred from MAF + engine_load.

If any of these get captured before the Walbro install, the shelf gains them. If not, the shelf closes incomplete and the project carries those gaps forward as known unknowns — interpret post-Walbro data with extra caution where the gaps exist.

---

### Drive 5 — 2026-04-29 — AUTHORITATIVE BASELINE (full cold→warm cycle, 17:39 min, 489 ECU samples/PID)

**Context**: Post-jump-start drive (CIO used Eclipse battery to jump another car earlier same day → alternator hard-charging). Full cold-start → warm-idle → shutdown captured. drive_id=5 in Pi DB.

| Parameter | Observed (warm steady) | Assessment |
|-----------|------------------------|------------|
| **RPM (warm idle)** | 753–785, avg 771 (±16) | **Tightest baseline yet.** Idles like new — only 32 RPM spread. |
| **LTFT** | -7.03 to -4.69, avg -6.42% (3 quantized notches) | **NEW BEHAVIOR**: ECU actively re-trimming after jump-start adaptation reset. Before jump: stuck at -6.25% across drives 3+4. After jump: live trimming in 6.25% notch quanta. **Healthy active-learning, not a defect.** Track new locked value across next 3-5 drives. |
| **STFT** | -4.69 to +10.16, avg +2.74% | Wider swing reflects cold→warm transition; in steady-state warm portion narrows to ±3%. |
| **O2 B1S1** | 0.06–0.94V, avg 0.53V | Healthy stoich switching, full-authority. |
| **O2 B1S2 (post-cat)** | 0.04–0.74V, avg 0.31V | Cat warming progression — low when cold, climbs as cat lights off. |
| **MAF (warm idle steady)** | 3.04–3.14 g/s (0.1 g/s spread!) | Pure steady-state. No transients. |
| **Engine Load (warm idle)** | 18.04–18.82%, avg 18.34% | Slightly lower than Drive 3's 19–22% (no warmup enrichment). |
| **Coolant Temp** | 31°C → 89°C ramp, ~6°C/min | **Thermostat opens cleanly at 80°C** (third confirmation across 3 drives — I-016 fully closed benign). Reaches 89°C steady-state. |
| **IAT (ambient)** | 17–22°C, avg 19.2°C | Tracking ambient, slight drift as drive proceeds. |
| **Throttle / Speed** | 0 / 0 | Idle, parked throughout. |
| **Timing Advance (warm idle)** | 4–7° BTDC, avg 5.3° | ⚠ Consistently below community 10–15° norm across 3 drives. Stable observation — this IS the stock 1998 GST factory idle calibration (CIO-confirmed stock ECU on drives ≤24), not a defect. |
| **BATTERY_V** | 13.8–14.4V, avg 14.16V | Alternator working harder than Drive 3 (post-jump charge of Eclipse 12V battery). |
| **DTC_COUNT / MIL_ON** | 0 / 0 | Clean across all 3 drives. |
| **FUEL_SYSTEM_STATUS** | 2.0 flat (closed-loop) | Fully settled, no open-loop excursions. |

### Drive 5 — Interpretation Anchors (use these as "healthy" baseline for future capture)

- If **LTFT drifts outside ±10% range** on a future capture, investigate. Currently re-learning post-jump from prior -6.25% lock.
- If **coolant plateaus below 80°C** after sustained warmup, thermostat is suspect (stuck open). 80°C-and-rising is healthy.
- If **idle RPM spread exceeds ±100 RPM** (vs. Drive 5's ±16), idle hunting — check IAC, TPS, fuel pressure.
- If **post-cat O2 (B1S2)** stays below 0.3V at fully warm steady-state for >5 min, cat efficiency may be degraded.
- If **timing advance increases significantly above 7°** at warm idle, revisit — may indicate ECMLink-flashed change or knock retreat.

### LTFT post-jump-start adaptation observation (NEW, 2026-04-29)

**Drive 3 (2026-04-23)**: LTFT_1 = -6.25% flat across 197 samples (one ECU notch).
**Drive 4 (2026-04-29 morning)**: LTFT_1 = -6.25% flat across 197 samples (still locked).
**Drive 5 (2026-04-29 evening, post-jump)**: LTFT_1 ranges -7.03 to -4.69, avg -6.42% across 489 samples (3 distinct quantized values).

**Interpretation**: 4G63 ECUs partially clear long-term fuel trim adaptation when battery voltage drops too low (jump-start scenario). After re-applying battery, ECU enters re-learning mode and trims actively until convergence. Drives 3+4 happened with battery at full health → ECU was running locked learned trim. Drive 5 happened ~2 hours after CIO used Eclipse battery to jump another car → ECU is now re-learning.

**Tracking plan**: Watch next 3-5 drives. Expected outcome: LTFT will lock at a new single value (possibly the same -6.25% if conditions are stable, possibly different if any combustion variable shifted). If LTFT keeps drifting drive-to-drive without ever locking, that's a different concern (sensor drift, fuel pressure variability, etc.) — but current data is healthy adaptation.

**RESOLUTION 2026-05-08 (Drive 6): TRACKING CLOSED.** Drive 6 idle LTFT_1 locked at -6.25% (same exact notch as Drives 3+4 pre-jump). The ECU re-learned to its natural baseline after the post-jump adaptation reset. **Engine's natural fueling baseline is `LTFT_1 = -6.25%` and this is consistent across pre-jump and post-re-learning conditions.** No further drives needed for this carryforward.

### Drive 6 — 2026-05-08 — Cold-Start City Drive (16 min, 7,085 rows, drive_id=6)

**Context**: First real-data capture in 10 days. Cold-start at ambient ~20°C → 16-min city driving → engine-off (Mike's first of two driving segments today). drive_id=6.

| Parameter | Observed (Drive 6 full window) | Assessment |
|-----------|-------------------------------|------------|
| **RPM** | 703–3367, avg 891 | Idle to mild driving — no high-RPM events |
| **Speed** | 0–46 mph, avg 1.83 | City driving, no highway |
| **Throttle** | 0–20.78%, avg 0.45% | Light pedal, mostly cruising |
| **Engine Load** | 7.06–42.75%, avg 19.36% | Light-to-moderate load, no boost-class events |
| **MAF** | 2.94–38.55 g/s, avg 4.09 | Wide range from idle (~3) to mild accel (~38) |
| **Coolant** | 38°C → 89°C ramp | **Thermostat opens at 80°C cleanly (4th confirmation across drives 3/4/5/6)** |
| **IAT** | 20–24°C, avg 21.12 | Tracking ambient, mild thermal drift only |
| **LTFT_1** | -6.25 → 0.0%, avg -5.92 | Adapting across load cells (idle cell at -6.25%, light-load cells higher); **idle baseline RE-LOCKED at -6.25%** (closes post-jump tracking) |
| **STFT_1** | -7.03 → 9.38, avg 1.82 | Active closed-loop |
| **O2_B1S1** | 0.02–0.98V, avg 0.55V | Full sweep, healthy switching |
| **O2_B1S2 (post-cat)** | 0.02–0.76V, avg 0.30V | Cat working — damped response with low max |
| **Timing** | 3–32° BTDC, avg 10.08° | Full healthy range across cold→warm + load variation |
| **BATTERY_V** | 13.1–14.4V, avg 14.02V | Alternator strong throughout |
| **DTC_COUNT / MIL_ON** | 0 / 0 | Clean |

**Engine grade**: HEALTHY warmup + light city drive. No concerns.

### Drive 7 — 2026-05-08 — AUTHORITATIVE UNDER-LOAD BASELINE (10 min, highway + WOT pull, drive_id=7)

**Context**: Mike's second driving segment today, ~40 min after Drive 6 ended. Engine started warm (74°C). **First WOT/100%-engine-load capture in project history.** Highway speeds reached. drive_id=7.

| Parameter | Observed (Drive 7 full window) | Assessment |
|-----------|-------------------------------|------------|
| **RPM** | 727–**5379**, avg 2272 | Idle through high-RPM under load |
| **Speed** | 0–**84 mph**, avg 48 | Highway driving included |
| **Throttle** | 0–**52.16%**, avg 6.73% | Moderate-aggressive pedal usage |
| **Engine Load** | 6.27–**100%**, avg 20.4 | **WOT / FULL BOOST EVENT** confirmed in this window |
| **MAF** | 2.94–**158.69 g/s**, avg 13.36 | Well above NA peak (~120 g/s) — turbo making boost (~10–12 psi estimated) |
| **Coolant** | 74–91°C, avg 87.95 | **Stayed below 220°F (104°C) danger ceiling** under sustained load ✓ |
| **IAT** | 19–26°C, avg 21.36 | **No heat-soak under load** ✓ |
| **LTFT_1** | -7.81 → 0.78, avg -3.89 | Load-cell drift — different cells than idle, ECU pulling slightly less negative under load (rich-correction adapted) |
| **STFT_1** | **-12.5 → 14.06**, avg 0.17 | Wide swings during WOT enrichment + transients = **NORMAL** behavior; net averages out across drive |
| **O2_B1S1** | 0–1.02V, avg 0.51V | Full authority including post-WOT switching |
| **O2_B1S2 (post-cat)** | 0–0.96V, avg 0.19V | Cat fully lit, working under load |
| **Timing** | 3–**34° BTDC**, avg 24.77 | Full ECU range exercised; **no knock-pull events flagged** (would show timing < 0° or DTC) |
| **BATTERY_V** | 13.2–14.4V, avg 13.97V | Alternator held under all loads |
| **DTC_COUNT / MIL_ON** | 0 / 0 | Engine survived clean across the WOT pull |

**Engine grade: HEALTHY UNDER FULL LOAD ENVELOPE.**

### Drive 7 — Interpretation Anchors (UNDER-LOAD BASELINE going forward)

Use these as "what a healthy under-load Drive looks like on THIS car" for future comparison:

- **MAF max ~159 g/s at WOT/5400 RPM = stock TD04-13G boost-making behavior.** If a future drive shows MAF ceiling significantly above 200 g/s, turbo may be over-spinning OR ECU is calling for more flow than it's getting (bad MAF signal).
- **STFT swings to ±12-14% during WOT = NORMAL.** Closed-loop is momentarily out of authority during enrichment. Net average should stay near 0%. If avg STFT trends consistently negative under load (rich) or consistently positive (lean), investigate.
- **Timing advance hit 34° BTDC under load** — within healthy stock 4G63 range. If a future capture shows timing pulled below 5° during WOT (with no knock-PID we can directly observe), suspect the ECU is doing knock-defense.
- **Coolant stayed at 91°C (196°F) max under sustained WOT** — your current cooling system is adequate for this turbo + driving profile. If future captures show coolant climbing past 100°C (212°F) under similar load, investigate fan operation, coolant level, water pump, or radiator condition.
- **IAT didn't heat-soak past 26°C under load** — short drive, no extended heat exposure. Watch IAT behavior on a longer (20+ min) hot-day drive — IAT climb above 50°C (122°F) starts pulling timing.
- **LTFT idle cell holds -6.25%, load cells drift positive (less negative) under load** — this is the natural shape of this engine's fuel trim table. Future captures should show the same shape.

### Drive 7 — Diagnostic Gaps Still Outstanding

- **Sustained WOT** at high speed — Drive 7 had a 100%-load event but not sustained for many seconds (just a pull). Need a longer high-load window for thermal-under-load + EGT-correlation behavior.
- **Hot-soak then re-start** — need a >20-min hot drive followed by 10-min hot-soak engine-off + restart to capture heat-soak fueling behavior.
- **Cold ambient + WOT** — Drive 7 was warm-engine-only WOT. A cold-engine WOT (not recommended for engine health but informative for ECU behavior) would show enrichment differences.

### Drive 11 — 2026-05-12 — PRIOR-ECU HISTORICAL REFERENCE (ARCHIVED 2026-05-22, was authoritative knock-retard characterization)

> **ARCHIVED 2026-05-22 (Session 19)**: CIO swapped to a different ECU (the ECMLink-flash-modified MD335287) mid-afternoon today. The new ECU's tune is materially more aggressive (runs ~10° more timing at sustained peak load, ~6° larger knock-retard pulls when fired). Drive 11's knock-retard envelope and timing observations no longer characterize the running ECU. **Use Drive 11 as PRIOR-ECU historical reference only. The new ECU baseline is being established starting Drive 26 (2026-05-22 spin); see `offices/tuner/knowledge/newecu-modified-eprom-first-impression-2026-05-22.md` for the first observation and forward updates.**

**Context (prior ECU, 2026-05-12)**: First clean car-coupled Pi-powered drive post-B-063 fuse-box buck-converter install. Cold-start (ambient ~12°C from IAT), 23:27 min mixed city → highway with multiple boost pulls peaking at 5441 RPM / 100% load / 91 mph. [EXACT: 93 octane — DO NOT CHANGE] fresh-fill (consistent with rest of shelf; corrected 2026-05-15 — was misrecorded 91). Mike at conservative 68.6% peak throttle (deliberately not WOT, awaiting ECMLink V3 + wideband). 10,839 realtime_data rows @ 462 rows/min — new project rows/min record.

| Parameter | Observed (Drive 11 full window) | Assessment |
|---|---|---|
| **RPM** | 613–5441, avg 2200 | Mixed city/highway driving. Peak 5441 = new under-load record (Drive 7 was 5379). |
| **ENGINE_LOAD** | 5.1–100%, avg 25.4% | Multiple full-load events. Average 25% = lots of cruise interspersed with pulls. |
| **MAF** | 3–135.14 g/s, avg 17.6 | 135 g/s peak ≈ 85% of Drive 7's 159 g/s peak (conservative throttle). |
| **THROTTLE_POS** | 0–68.6%, avg 7.7 | Peak 68.6% — Mike deliberately not WOT. Avg 7.7% = mostly cruise. |
| **COOLANT_TEMP** | 34–93°C, avg 84 | Clean cold-start curve. Operating temp ceiling 93°C — within envelope. No thermal events. |
| **INTAKE_TEMP** | 12–27°C, avg 15 | Cool ambient, 15°C rise under load. No heat-soak. |
| **TIMING_ADVANCE** | 2–34°, avg 21.9 | **CRITICAL — knock-retard signature present.** See breakdown below. |
| **SHORT_FUEL_TRIM_1** | -13.3 to +24.2%, avg +0.79 | Wide range, but avg near zero. Open-loop disabled STFT during boost (closed-loop suspended). Cruise STFT well-controlled. |
| **LONG_FUEL_TRIM_1** | -7.0 to +4.7%, avg -1.4 | Wider than Drive 5/6/7 — different load-cell LTFT values active. Idle-cell still ≈ -6.25%; load cells drift positive under boost (open-loop). |
| **O2_B1S1 (front)** | 0–0.96V, avg 0.49 | Under boost: pegged 0.92-0.96V = ECU targeting RICH for safety (~12-13 AFR equivalent on narrowband). Correct WOT/open-loop fueling. |
| **O2_BANK1_SENSOR2_V (rear)** | 0–0.92V, avg 0.23 | Cat doing its job (low oscillation downstream). |
| **FUEL_SYSTEM_STATUS** | 2.0–3.0, avg 2.22 | Mix of 2 (closed-loop) and 3 (open-loop drive). Transitions to OL during boost — correct 4G63 behavior. |
| **SPEED** | 0–147 km/h, avg 62.3 | **NEW UNDER-LOAD SPEED RECORD: 91 mph** (Drive 7 was 84 mph). |
| **DTC_COUNT / MIL_ON** | 0 / OFF | Clean throughout. |
| **BATTERY_V** (CONTROL_MODULE_VOLTAGE PID 0x42) | 13.2–14.6V, avg 14.25 | Alternator charging-voltage range. Healthy. |

#### Knock-retard signature characterization — TIMING_ADVANCE by load bucket

| Load bucket | Samples | Min timing | Avg timing | Max timing | Interpretation |
|---|---|---|---|---|---|
| 0-30% (idle/cruise) | 148 | 7° | **24.5°** | 33° | Normal cruise timing for 4G63. Modified-EPROM is conservative vs. some community tunes. |
| 30-60% (light load) | 34 | 9° | **23.9°** | 31° | Holding cruise timing through light acceleration. |
| 60-80% (medium load) | 3 | 16° | **22.3°** | 30° | Beginning to retard, but still close to cruise. |
| **80-95% (high/transitional)** | 6 | 8° | **12.0°** | 21° | **~12° of retard from cruise.** ECU actively pulling timing as load increases through the mid-range. |
| **95-100% (full load / boost)** | 5 | 7° | **13.2°** | 32° | Wide range — some retard events to 7-8°, some held at 32° (when cylinder conditions allowed). |

#### Smoking-gun knock event (3-sec resolution, peak-RPM pull at 01:22:27-33Z)

| Time | RPM peak | Timing | O2 voltage |
|---|---|---|---|
| 01:22:27Z | 5,094 | **28°** | 0.92V (rich) |
| 01:22:30Z | 4,707 | **12°** | 0.96V (rich) |
| 01:22:33Z | **5,441** (peak) | **23°** | 0.94V (rich) |

**16° of timing pulled in 3 sec, then 11° returned over the next 3 sec.** Classic 4G63 mid-range knock window: RPM 4500-5000 = VE peak / max cylinder fill BUT not enough crank speed to "rev past" detonation tendency. ECU's knock sensor detected the condition, pulled timing, restored it once RPM climbed past the knock zone.

### Drive 11 — Interpretation Anchors

> **⚠ FUEL-GRADE CORRECTION (2026-05-15, CIO directive):** Every drive on the pre-mod shelf (3–16) was run on **[EXACT: 93 octane — DO NOT CHANGE]**, NOT 91. CIO corrected the record 2026-05-15: he misreported 91 earlier; all past *and* future fillings are 93 octane until the E85 flex-fuel sensor is installed + wired. This recalibrates the entire knock-retard baseline below to a **93-octane baseline**. The prior "expect timing to creep up 4-8° on 93" prediction is **VOID** — we were already on 93; the 12-13° high-load figure *is* the 93-octane number. Inverse now holds: running 91 (won't happen — 93 is CIO standard) would show *more* retard, not less.

Use these as the project's reference for "what healthy knock-retard behavior looks like on this car + [EXACT: 93 octane — DO NOT CHANGE] + stock 14b":

1. **Cruise/idle timing 24-25° avg** — STOCK factory baseline. Don't expect ECMLink V3 to change this much at no-load (the stock idle table is already well-dialed).
2. **High-load (80%+) timing 12-13° avg with 7-8° minima** — characteristic of **93 octane** + stock 14b + STOCK factory tune. This IS the 93-octane baseline (correction 2026-05-15); there is no octane-uplift metric to extract since the shelf was never on 91. A deliberate 91 run would show *deeper* retard, but CIO runs 93 standard until E85 so no A/B is planned.
3. **4500-5000 RPM mid-range = knock-prone window** for this engine. Spec1 baseline. Future captures should show retard concentrated in this window; if retard appears at OTHER RPM ranges, that's a new finding worth investigating.
4. **Fuel system pegged rich (O2 0.92-0.96V) under boost** — open-loop targeting works correctly. No lean events under any pull. Pre-Walbro fuel system delivers within this throttle/RPM envelope.
5. **B-063 buck-converter performance baseline** = one 5-sec AC blip in 23 min of driving = 99.6% steady. Use this as the threshold for "buck-converter regressed" if a future drive shows more blips.

### Drive 11 — Diagnostic Gaps Still Outstanding

- **Sustained WOT** at 100% throttle (Drive 11 peak was 68.6% throttle) — would expand the knock-retard characterization to "what does this engine do when you actually pin it on [EXACT: 93 octane — DO NOT CHANGE]?"
- ~~**93 octane A/B comparison**~~ **RETIRED 2026-05-15** — the entire shelf was already on 93 octane (CIO fuel-grade correction). No A/B available; would require a deliberate 91-octane run, which CIO will not do (93 is standard until E85). No timing-creep metric to extract.
- **MAP PID gap** — without MAP (PID 0x0B) capture we cannot map timing-retard events against actual boost psi. Filed as feature request to PM (V0.27.7 ride-along OR V0.28.0).
- **Hot-soak + restart** still pending (was pending after Drive 7 too).
- **Wet-pavement** still pending.

### Drive 26 — 2026-05-22 — NEW-ECU FIRST KNOCK-RETARD OBSERVATION (18 min, post-swap spin around block, drive_id=26)

**Context**: CIO swapped to a different ECU — the ECMLink-flash-modified MD335287 — mid-afternoon today (2026-05-22, Session 19). Drive 26 = first city-driving telemetry on new ECU after ~16-min warm idle (drive 25). Fuel [EXACT: 93 octane — DO NOT CHANGE]. Coolant fully up at start, IAT heat-soaked (32-55 °C). Engine grade A (no DTC, no MIL, no harm), BUT surfaced a clear knock-retard event during a city-road tip-in.

**The event — 19:05:54 UTC** (reconstructed from same-second multi-PID alignment):

```
19:05:49  RPM 1948  THROTTLE 12.55%  LOAD 24%   TIMING 28.5°  STFT -0.78  LTFT +1.56   cruise
19:05:51  RPM 1948  THROTTLE 12.55%  LOAD 24%   TIMING 23.0°  STFT +7.03  LTFT  0.00   tip-in starts
19:05:53  RPM 2464  THROTTLE 32.94%  LOAD 57.65% MAF 62.29                              throttle pushed harder
19:05:54  RPM ~3300 THROTTLE ~35%    LOAD ~60%  TIMING  5.0°  STFT +17.19% LTFT  0.00  ▲ KNOCK RETARD + LEAN SPIKE
19:05:55  RPM 3928  THROTTLE ~35%    LOAD 67%                                          peak RPM
19:05:56  RPM 3928  THROTTLE 27.45%  LOAD 67%   TIMING 15.0°  STFT  0.00               recovering
19:05:58  RPM 3268  THROTTLE 41.96%  LOAD 96.08% MAF 107.82   TIMING 22.0° STFT 0      peak load, stable
19:05:59  RPM 3268  THROTTLE 41.96%  LOAD 96.08% MAF 107.82   TIMING 22.0° STFT 0      sustained at 22°
```

**Mechanism**: Classic 4G63 stock-MAF / stock-injector lean-tip-in-knock pattern.
1. Throttle opened rapidly during city tip-in (2nd-or-3rd gear estimated from RPM × gear ratio; see SPEED PID caveat below).
2. MAF reading **lagged** actual airflow during the sharp pressure transient (MAF physics — measurement latency on rapid load changes).
3. ECU underestimated air → injected too little fuel → **STFT spiked to +17.19% lean** (closed-loop demanding more fuel).
4. Brief lean moment under boost → ECU detected knock → **TIMING pulled 23° → 5° (~18° retard)**.
5. Recovery in 2 sec: STFT back to 0, TIMING 15° → 22° at sustained peak load. No DTC fired; no MIL; ECU saved the engine.

**Comparison: Drive 11 (prior ECU, archived) vs Drive 26 (new ECU)**

| Signature | Drive 11 (prior ECU) | Drive 26 (new ECU) |
|---|---|---|
| Sustained peak-load timing | ~12° (already retarding) | **22°** (more aggressive base) |
| Cruise timing | ~24-25° | 23-28° |
| Knock-retard pull magnitude | ~12° | **~18°** (when fired) |
| Knock-retard RPM window (first observation) | 4,500-5,000 RPM at 91-100% load | **~3,500 RPM at 60-67% load (city tip-in)** |
| LTFT settled value | −1.8 to −2.2 (prior baseline) | Still learning, drifting near 0 |
| STFT transient cap under load | Well-bounded ±5% | **+17.19% during tip-in** |

**Spool's read — new ECU is more aggressive than prior**: runs ~10° more advance at sustained peak load before knock retard fires; bigger pull (~18°) when knock IS detected; lean tip-in events on casual city driving = the tune is at the hardware ceiling on current stock-MAF / stock-injector / 93-octane configuration. **Functional but the canary is sounding.**

**Supporting hardware this tune wants** (consistent with Modification Priority Path; reinforced by Drive 26 observation):
1. **Wideband O2 + ECMLink V3** — first priority. Narrowband cannot show how lean 19:05:54 actually got. Without wideband, we're flying blind on AFR target under boost.
2. **Larger injectors (550 cc minimum)** — directly addresses the lean tip-in. Stock 450 cc cannot keep up with this tune's transient fuel demand.
3. **Walbro 255 lph fuel pump** — proactive for any boost increase.

**Until at least (1) + (2) land**: drive sensibly. No sustained WOT. No track-style runs. The lean tip-in signature says "the hardware is at its limit." More boost = bigger lean transient = bigger knock retard = bigger damage risk if a single retard event misses.

### Drive 26 — Interpretation Anchors (NEW-ECU WORKING BASELINE — in progress)

This is the FIRST observation on the new ECU. Anchors below are PROVISIONAL — will firm up after 2-3 more drives.

- **Idle RPM** ~830 (slightly elevated vs OEM target ~750). Watch across drives.
- **Idle LTFT swing characteristic** 0.00 → +2.34 → −2.34 (cold → warm → hot). Tune characteristic, not a fault. ±2.34 swing well within healthy ±5% band.
- **Idle timing** 5-11° BTDC (conservative for the new ECU's ECMLink tune).
- **Idle ENGINE_LOAD** 20-21% (slightly elevated vs OEM 15-18% — watch).
- **Sustained peak-load timing** 22° at 96.08% load / 3,268 RPM / 93 octane. **If timing drops below 18° at sustained peak load** on a future drive, the tune is starting to defensively retard — investigate fuel quality, carbon buildup, IAT trend.
- **Knock-retard event signature**: timing dropping below 10° simultaneously with STFT spiking above +10% during a tip-in = lean-induced knock retard, recovering within 2-3 sec is normal ECU behavior, not damage. **>3 events per drive** or **timing not recovering within 5 sec** = tune hunting too aggressively or fuel-delivery problem.
- **Idle coolant equilibrium** 99 °C with fan running on hot day, no airflow. Steady-state, not climbing = normal. **If climbs past 102 °C while idling with fan on** = investigate fan-relay, coolant-temp-sensor, or thermostat.

### Drive 26 — Diagnostic Gaps Still Outstanding

- **Cold-start on new ECU** — Drive 26 was warm continuation. Need full ambient-cold start for warmup-curve baseline.
- **Sustained cruise (steady-state 4th/5th gear)** — to characterize the tune's cruise timing target and LTFT settle behavior.
- **Stop + restart cycle** — does LTFT carry over (EEPROM-stored) or reset to 0.00 each start?
- **Mid-range knock-retard window** (3,500-5,000 RPM) — Drive 26 only sampled one tip-in; need to characterize the knock-retard frequency-of-fire across multiple acceleration events.
- **SPEED PID calibration verification** — see OBD-II section caveat. Need GPS correlation.

### Session 23 — 2026-04-19 — First Real OBD Data (Warm Idle, ~23s captured across 2 windows) [HISTORICAL]

**Context**: Cold-start → warm idle → shutdown wall-clock ~10 min, but real OBD-connected data capture was ~23 seconds due to TD-023 connection churn. Engine was already warm in the captured window. No warmup curve, no load, no drive. **Superseded by Drive 5 above as authoritative baseline; preserved here for historical comparison.**

| Parameter | Observed Value | Assessment |
|-----------|----------------|------------|
| **RPM (warm idle)** | 761–852, avg 793 (±45) | Normal. Not hunting (<150 RPM swing). Not stuck. |
| **LTFT** | **0.00% flat across 13 samples** | **TUNE IS DIALED.** Base fuel map does not need long-term correction. |
| **STFT** | −0.78% to +1.56%, avg +0.06% | Textbook. Tiny nudges around stoich. Closed-loop happy. |
| **O2 B1S1** | 0–0.82V switching, avg 0.46V | Healthy narrowband. Full-authority swing crossing stoich (~0.45V). |
| **MAF (warm idle)** | 3.49–3.68 g/s (tight range) | Plausible idle airflow for 2.0L/4-cyl. No drop-outs. |
| **Engine Load (warm idle)** | 19.22–20.78% | Tight clamp. Normal warm idle. |
| **Throttle Position (closed)** | 0.78% flat | Clean TPS zero offset. No stiction. |
| **Timing Advance (warm idle)** | 5–9° BTDC (avg 7°) | ⚠ Lower than stock 2G community norm (10–15° BTDC at idle). This IS the stock 1998 GST factory idle calibration (CIO-confirmed stock ECU on drives ≤24); earlier "modified EPROM" / adaptive-learning / rounding guesses are superseded. |
| **Coolant Temp (warm-ish idle)** | 73–74°C (163–165°F) flat | ⚠ **RECLASSIFIED Session 6 (2026-04-20)** — this was NOT steady-state warm idle, it was a mid-warmup snapshot. 23s window ended before thermostat-open temp (180°F) was reached. **I-016 closed benign** via Session 6 gauge drill: thermostat confirmed healthy at 15-min sustained idle. Do NOT use 73-74°C as a warm-idle baseline. |
| **IAT (short idle, cold ambient)** | 14°C (57°F) flat | Matches Chicago spring ambient. No heat-soak in short window. |
| **Speed** | 0 km/h | Parked. |

### Session 23 — Interpretation Anchors

Use these as "what a healthy warm idle looks like on THIS car" for future comparison:

- If **LTFT drifts away from 0.00%** on a future capture (either direction), something has changed — fuel pressure, injector flow, MAF drift, air leak. Investigate.
- If **STFT amplitude grows beyond ±3%** during steady-state closed-loop, same story.
- If **RPM idle variation exceeds ±75 RPM** (current baseline ±45), idle stability is degrading — IAC valve, vacuum leak, coil pack.
- If **coolant fails to climb past 180°F** after a 5+ min sustained warm idle (not a short capture), **thermostat is the first suspect** — but this car's thermostat is CONFIRMED HEALTHY as of Session 6 (2026-04-20), so this anchor applies to "has it failed since then" rather than "is it failing now."
- If **timing advance at idle drops below 5°** consistently, ECU may be pulling timing defensively — investigate knock history (once ECMLink is in).

### Session 23 — Diagnostic Gaps (Cannot Assess From This Capture)

These questions require the post-TD-023 longer drill:

- Cold-start enrichment behavior (fuel trim during warmup)
- Closed-loop transition timing (coolant temp at which O2 starts participating)
- Warmup coolant ramp rate — **critical for thermostat diagnosis** (✅ RESOLVED Session 6 via gauge — thermostat healthy)
- IAT thermal soak under sustained running
- Load response / any boost / any MAF ceiling behavior
- DTC/MIL status (PID 0x01 not captured)
- Fuel system state (PID 0x03 not captured — closed-loop was **inferred**, not observed)

### Session 6 — 2026-04-20 — Thermostat + Restart Drill (Engine confirmed healthy, no digital capture)

**Context**: CIO-led 5-phase drill (pre-crank / 15-min sustained idle / shutdown / restart / final shutdown). Pi collector was in `--simulate` mode, so ZERO real rows were captured. Engine-side observations via CIO's direct gauge reading.

**Tuning-domain findings**:

- ✅ **Thermostat confirmed healthy** — internal coolant gauge held normal operating position throughout 15-min sustained idle. Normal gauge ≈ 190-200°F (88-93°C), well above 180°F thermostat-open gate. **I-016 closed benign.**
- ✅ **Engine mechanically clean** across cold-crank → sustained-idle → shutdown → restart cycle. No rough idle, no warning lights, no anomalies reported.
- ❌ **No digital baseline captured** — `--simulate` mode meant collector was reading the physics simulator, not `/dev/rfcomm0`. Session 23's warm-idle fingerprint remains the only empirical data until a real-mode drill produces a replacement.

**What this changes about the baseline**:

- **Session 23 coolant value (73-74°C) is NOT a warm-idle reference.** It's a mid-warmup snapshot — the engine hadn't reached thermostat-open temp in the 23s capture.
- **Session 23 fuel trim / O2 / MAF values remain valid** — those don't depend on coolant reaching full op temp (closed-loop activates around 160°F/71°C, which the capture did reach).
- **Next real-mode drill** (post-Sprint-16 `--simulate` removal) produces the canonical warm-idle baseline to replace Session 23's coolant value.

**Summer 2026 E85 prep implication**: cooling system does NOT need a dedicated audit beyond standard coolant service. One open item closed.

---

## PID Interpretation Guide

### How to Read Each Key PID

#### STFT (Short-Term Fuel Trim) — PID 0x06
- **What it is**: Real-time ECU adjustment to fuel delivery based on O2 sensor feedback
- **Positive value** (+5%, +10%): ECU is ADDING fuel — it sees lean condition
- **Negative value** (-5%, -10%): ECU is REMOVING fuel — it sees rich condition
- **0%**: ECU is happy with current fuel delivery
- **Key insight**: Large positive STFT under boost = LEAN = engine damage risk. This is the #1 safety metric available via OBD-II on our car.
- **Context matters**: STFT varies by RPM and load. Evaluate at specific operating points, not as a single number.
- **Closed loop only**: STFT is only active in closed-loop fuel mode. Under WOT, the ECU goes open-loop and STFT freezes.

#### LTFT (Long-Term Fuel Trim) — PID 0x07
- **What it is**: Learned, persistent fuel correction. ECU adjusts this over time if STFT consistently needs correction.
- **Healthy engine**: LTFT stays within +/-5%
- **Drifting LTFT**: Indicates a persistent issue — vacuum leak, dirty MAF, failing injector, fuel pressure problem
- **LTFT + STFT combined**: Total fuel correction. If LTFT is +8% and STFT is +7%, the ECU needs +15% more fuel than its base table expects. Something is wrong.
- **Reset behavior**: LTFT resets when battery is disconnected. ECU needs to relearn — expect erratic behavior for 50-100 miles.

#### Timing Advance — PID 0x0E
- **What it is**: Ignition timing in degrees Before Top Dead Center (BTDC)
- **More advance** = more power (up to a point)
- **Less advance** = ECU is protecting against knock (detonation)
- **Normal idle**: 10-15 degrees BTDC
- **Normal cruise**: 15-25 degrees (varies with load)
- **Under boost**: 8-16 degrees (ECU pulls timing for safety)
- **Red flag**: Timing dropping below 5 degrees or going NEGATIVE under load = heavy knock. Investigate immediately.
- **Causes of low timing**: Bad gas (low octane), carbon buildup, excessive boost, cooling issue, failing knock sensor

#### Engine Load — PID 0x04
- **What it is**: Calculated value representing how hard the engine is working (percentage of theoretical maximum airflow)
- **Idle**: 15-25%
- **Light cruise**: 25-40%
- **Highway cruise**: 35-55%
- **Hard acceleration**: 70-90%
- **Full boost WOT**: 85-100%+
- **Key use**: Load + STFT correlation. High load with positive STFT = lean under boost. This is the most dangerous condition detectable via OBD-II.

#### MAF (Mass Air Flow) — PID 0x10
- **What it is**: Mass of air entering the engine per second (grams/second)
- **Idle**: 2-5 g/s
- **Cruise**: 10-30 g/s
- **WOT**: 80-150+ g/s
- **Saturation warning**: Stock MAF sensor output clips around 2700 Hz (~150 g/s, ~300 HP). Above this, MAF reports inaccurately and ECU under-fuels. Extremely dangerous.
- **Dirty MAF**: Reports lower than actual airflow → ECU under-fuels → lean. Clean with MAF-specific cleaner only (no carb cleaner or brake cleaner).

#### O2 Sensor B1S1 — PID 0x14
- **What it is**: Narrowband oxygen sensor upstream of catalytic converter
- **How it works**: Outputs ~0.1V (lean) to ~0.9V (rich), switching rapidly around 0.45V (stoichiometric 14.7:1)
- **Healthy sensor**: Oscillates 1-3 times per second between 0.1-0.9V in closed loop
- **Lazy sensor**: Slow switching (>1 second per cycle) — needs replacement
- **Stuck lean** (<0.3V constant): Exhaust leak before sensor, or genuinely lean condition
- **Stuck rich** (>0.7V constant): Leaking injector, high fuel pressure, or sensor failure
- **CRITICAL LIMITATION**: Narrowband O2 tells you NOTHING about actual AFR under boost. At WOT, the ECU goes open-loop and this sensor is ignored. A wideband is essential for any serious tuning.

---

## Datalog Analysis Methodology

### Step-by-Step: Reading an OBD-II Datalog

Even with OBD-II limitations (slow, no knock data, no wideband), useful analysis is possible:

#### 1. Establish Baseline
- Log 20-30 minutes of normal driving (warm engine, closed loop)
- Note typical idle STFT/LTFT values
- Note typical cruise timing advance
- Note coolant temp stabilization point
- This is your "healthy engine" reference

#### 2. Identify Operating Regimes
Split the log into segments:
- **Cold start** (coolant <170F): Ignore fuel trims — ECU is in open-loop enrichment
- **Warm idle** (coolant >185F, RPM 650-850, TPS <2%): Best place to evaluate LTFT
- **Light cruise** (TPS 5-15%, speed 30-55 mph): Best place to evaluate combined trims
- **Acceleration** (TPS >40%, load >60%): Watch timing advance behavior
- **Deceleration** (TPS 0%, RPM dropping): Fuel cut-off, normal

#### 3. Check for Red Flags
In order of severity:

| Red Flag | What It Means | Urgency |
|----------|---------------|---------|
| STFT > +15% at any point | Major lean condition | **Immediate** — stop driving, diagnose |
| Coolant temp > 215F | Overheating | **Immediate** — pull over |
| Timing < 5 deg under load | Heavy knock detection | **High** — bad gas, carbon, or mechanical issue |
| LTFT > +/-10% at warm idle | Persistent fuel delivery problem | **High** — vacuum leak, MAF, injector |
| O2 sensor not oscillating | Sensor failure or stuck condition | **Medium** — ECU can't closed-loop |
| IAT > 55C (131F) | Excessive heat soak | **Medium** — power loss, detonation risk |
| Battery voltage < 13.0V running | Charging system issue | **Medium** — alternator or belt |

#### 4. Trend Analysis (Multi-Session)
Compare baselines over time:
- **LTFT creeping positive**: Something is gradually reducing fuel delivery (clogging injector, weakening fuel pump, growing vacuum leak)
- **Idle RPM dropping**: IAC valve fouling, vacuum leak
- **Coolant temp rising over weeks**: Thermostat degrading, coolant level low, fan issue
- **Timing advance decreasing over time**: Carbon buildup, octane sensitivity increasing

---

## Fuel Trim Analysis

### Decision Tree: What Do My Fuel Trims Mean?

```
Is STFT + LTFT combined > +10% at idle?
├── YES → Likely vacuum leak
│   ├── Check: Brake booster hose, PCV valve, intake manifold gasket
│   ├── Check: Boost leak (cracked intercooler pipe, loose clamp)
│   └── Listen for hissing with engine running
├── NO → Is LTFT > +8% across all RPM ranges?
│   ├── YES → Fuel delivery issue
│   │   ├── Low fuel pressure (check with gauge — should be 43.5 psi base)
│   │   ├── Clogged injector (one or more)
│   │   ├── Dirty MAF sensor (under-reading airflow)
│   │   └── Weak fuel pump (check volume — should deliver >1 pint in 15 sec)
│   └── NO → Is LTFT positive at idle but negative at cruise?
│       ├── YES → Likely vacuum/boost leak (manifests at low manifold vacuum)
│       └── NO → Probably normal variation. Monitor trend over time.

Is STFT + LTFT combined > -10%?
├── YES → Rich condition
│   ├── Leaking injector (fuel smell at idle, possible misfire)
│   ├── High fuel pressure (regulator failure, kinked return line)
│   ├── Saturated charcoal canister (purge valve stuck open)
│   └── Coolant temp sensor reading too cold (ECU over-enriches)
└── NO → Normal operation
```

### Fuel Trim by Operating Condition (What's Normal)

| Condition | STFT Range | LTFT Range | Combined Max |
|-----------|-----------|-----------|--------------|
| **Warm idle** | -3% to +3% | -5% to +5% | +/-8% |
| **Light cruise** | -5% to +5% | -5% to +5% | +/-10% |
| **Hard acceleration** | Frozen (open loop) | Learned value | N/A — open loop |
| **Deceleration** | Frozen (fuel cut) | Learned value | N/A — fuel cut |

---

## Timing and Knock

### What Is Knock and Why It Kills Engines

Knock (detonation) is uncontrolled combustion — the air-fuel mixture ignites from pressure/heat instead of the spark plug. On a turbocharged engine:

1. **Boost increases cylinder pressure and temperature**
2. If pressure/temp exceed the fuel's octane rating, the mixture auto-ignites
3. The resulting pressure spike hammers the piston crown, rings, and rod bearings
4. Sustained knock cracks pistons, breaks ring lands, spins bearings, and destroys engines

**On the 4G63**: The #4 cylinder is most vulnerable because:
- Farthest from the intake manifold (shortest intake runner)
- Hottest cylinder (poorest cooling at rear of block)
- Tends to run leaner than cylinders 1-3

### Knock Detection on Our Car

| Method | Available Now | Available with ECMLink |
|--------|:---:|:---:|
| **Timing Advance (PID 0x0E)** | Yes | Yes |
| **Knock Count** | No | Yes |
| **Knock Sum** | No | Yes |
| **Audio (ear/headphones on block)** | Yes (manual) | N/A |

**Without ECMLink**, timing advance is our only knock indicator via OBD-II. Look for:
- Timing dropping >5 degrees suddenly under load
- Timing consistently lower than baseline at same RPM/load point
- Timing going near zero or negative under boost

### Safe Timing Ranges (Stock Turbo, Pump Gas 91-93 Octane)

| RPM | Load | Expected Timing | Concern Below |
|-----|------|:-:|:-:|
| Idle (800) | 15-25% | 10-15 deg | 5 deg |
| 2000 | 30-40% | 15-25 deg | 10 deg |
| 3000 | 50-70% | 12-20 deg | 8 deg |
| 4000+ | >70% (boost) | 8-16 deg | 5 deg |
| Any | >80% (full boost) | 8-14 deg | 5 deg |

---

## Boost and Turbo

### Stock Turbo: Mitsubishi TD04-13G (97-99 2G)

**Note**: The 95-96 2G uses the TD05H-14B (larger compressor, flows more, safe to ~16-17 psi). The 97-99 2G (our car) uses the smaller TD04-13G which spools faster but runs out of breath sooner. Some sources call the 97-99 turbo "TD04-09B" — verify by checking the tag on the turbo housing.

| Spec | Value |
|------|-------|
| **Common name** | "Small 14b" or "stock 97-99 turbo" or "13G" |
| **Compressor wheel** | ~42mm inducer |
| **Turbine wheel** | ~47mm |
| **Stock boost** | ~10-12 psi (wastegate setting) |
| **Max safe boost (with tune)** | 14-15 psi |
| **Efficiency range** | Drops off sharply above 14 psi |
| **Spool RPM** | ~2,500-3,000 RPM |
| **Peak power band** | 3,000-5,500 RPM |
| **Power ceiling** | ~250-260 HP (with supporting mods and tune) |
| **Wastegate** | Internal, stock actuator ~10 psi crack pressure |

### Boost Control Options

| Method | Complexity | Boost Range | Notes |
|--------|-----------|-------------|-------|
| **Stock wastegate** | None | 10-12 psi | No adjustment possible |
| **Manual boost controller (MBC)** | Low | 12-18 psi | Ball-and-spring valve, bleed type. Simple, reliable. ~$30. Good first step. |
| **Boost controller via ECMLink** | Medium | Programmable | Requires ECMLink + solenoid. Boost-by-gear, boost-by-RPM, anti-lag. |
| **Standalone EBC** | Medium-High | Programmable | GReddy Profec, AVC-R. Overkill when ECMLink does it. |

### Boost Creep and Boost Spike

- **Boost creep**: Boost exceeds target because exhaust flow overcomes the wastegate. Common with exhaust modifications (freer flowing) or upgraded turbo. Requires larger wastegate or external wastegate.
- **Boost spike**: Momentary overshoot when turbo spools and wastegate hasn't opened yet. Normal within 1-2 psi. Dangerous if >3 psi over target. MBC tuning or ECMLink duty cycle table fixes this.

---

## Cooling System

### Why Cooling Matters on the 4G63

Turbo engines generate significantly more heat than naturally aspirated. The 4G63's cooling system is adequate for stock power but becomes marginal with modifications:

- **Head gasket is the weak point**: The 4G63 uses a multi-layer steel (MLS) head gasket clamped by head bolts (not studs). Under high boost/heat, bolts stretch, clamp force drops, gasket weeps.
- **#4 cylinder runs hottest**: Farthest from water pump inlet, poorest coolant flow.
- **Symptoms of imminent failure**: Coolant temp climbing, white smoke (coolant in combustion), milky oil, bubbles in coolant overflow.

### Temperature Thresholds (Our Car)

| Temp (F) | Temp (C) | Status | Action |
|----------|----------|--------|--------|
| <170 | <77 | Cold | ECU in warm-up enrichment. Don't hit boost. |
| 170-185 | 77-85 | Warming | Getting close. Light driving OK. |
| **185-205** | **85-96** | **Normal** | **Healthy operating range. Thermostat regulates here.** |
| 205-215 | 96-102 | Warm | Still OK but watch trend. If climbing, investigate. |
| **215-220** | **102-104** | **Warning** | **Reduce load. Check cooling fans. Don't boost.** |
| **>220** | **>104** | **CRITICAL** | **Pull over. Engine OFF. Head gasket territory.** |
| >240 | >116 | Catastrophic | Warped head, blown gasket, possible seizure |

### Thermostat Behavior
- **Stock thermostat**: Opens at 190F (88C), fully open by 205F (96C)
- **If coolant never reaches 190F**: Thermostat stuck open (or missing). ECU never fully enters closed-loop fuel. Fuel trims will be off.
- **If coolant rises above 215F in normal driving**: Thermostat stuck closed, low coolant, fan failure, or radiator clogged.

---

## Fuel System

### Stock Fuel System Specifications

| Component | Stock Spec | Limit |
|-----------|-----------|-------|
| **Injectors** | 450cc/min (DSM community measured) | ~280 HP at 85% duty cycle |
| **Fuel pump** | ~190 lph | ~300 HP |
| **Fuel pressure (base)** | 43.5 psi (3 bar) | — |
| **Fuel pressure (1:1 rising rate)** | Base + boost psi | At 12 psi boost: 55.5 psi |
| **Fuel filter** | Inline, replaceable | Replace every 30k miles or when flow drops |
| **Fuel rail** | Stock, adequate to ~400 HP | — |

### Injector Duty Cycle

Injector duty cycle is the percentage of time the injector is open per engine cycle. This is the key fuel system health metric (available only via ECMLink).

| Duty Cycle | Status | Action |
|-----------|--------|--------|
| <80% | Normal | Adequate fuel delivery headroom |
| 80-85% | Caution | Nearing limit. Plan upgrade. |
| 85-90% | Danger | Inconsistent fuel delivery, lean risk at peak demand |
| >90% | Critical | Injectors cannot deliver enough fuel. LEAN. Upgrade immediately. |
| 100% (static) | Maxed | Injector is open constantly. Engine is fuel-starved. |

### Upgrade Path (In Order)

1. **Walbro 255lph fuel pump** (~$70) — Drop-in replacement, good to ~400 HP
2. **550cc injectors** (Injector Dynamics ID550 or similar) — Good to ~350 HP, requires ECMLink to tune
3. **Adjustable fuel pressure regulator** (already installed on our car)
4. **660cc injectors** — For 20G+ turbo builds, 350-450 HP range
5. **Return-style fuel system conversion** — For 500+ HP builds

---

## ECMLink V3 Reference

### What ECMLink V3 Unlocks

ECMLink V3 is a flash-based tuning solution for 1995-1999 DSM ECUs. It replaces the stock ECU programming via the diagnostic port. **This is the #1 most important upgrade for tuning our car.**

| Capability | Description |
|-----------|-------------|
| **Real-time datalogging** | 15,625 baud, ~50 parameters, 10-50 Hz sample rate |
| **Fuel tables** | Full 3D fuel maps (RPM x Load) |
| **Timing tables** | Full 3D ignition timing maps |
| **Boost control** | Closed-loop boost via stock solenoid or aftermarket |
| **Knock monitoring** | Knock count, knock sum, knock learn — THE critical safety data |
| **Wideband input** | Analog input for wideband O2 controller → real AFR |
| **Launch control** | RPM limiter with boost building on launch |
| **Flex fuel** | E85/pump gas blending with ethanol content sensor |
| **Speed density** | Bypass MAF entirely, use MAP sensor for fuel calc (eliminates MAF saturation limit) |
| **Anti-lag** | Retarded timing to keep turbo spooled (track use only) |
| **CEL management** | Clear/disable specific check engine codes |

### ECMLink Parameters Not Available via OBD-II

These are the parameters that make ECMLink transformative for tuning:

| Parameter | What It Tells You | Why It Matters |
|-----------|-------------------|----------------|
| **Knock Sum** | Accumulated knock intensity | THE #1 safety parameter. No OBD-II equivalent. |
| **Knock Count** | Number of knock events | How often knock occurs per pull |
| **Knock Learn** | Permanent timing retard learned by ECU | Shows if ECU has adapted to chronic knock |
| **Wideband AFR** | Actual air-fuel ratio (with wideband input) | Real AFR, not narrowband toggle |
| **Injector Duty Cycle** | % of time injectors are open | Fuel system headroom |
| **Boost (via MAP sensor)** | Actual manifold pressure | Real boost with aftermarket MAP |
| **AirFlowPerRev** | Volumetric efficiency indicator | Metering validation (stock idle: ~0.27) |
| **TPS Delta** | Rate of throttle change | Tip-in/tip-out enrichment tuning |
| **MAF Frequency (raw Hz)** | Raw MAF output | Detect MAF saturation at ~2700 Hz |
| **Target AFR** | What ECU is targeting | Verify tune is commanding correct AFR |

### ECMLink Deeper Details

**Speed Density Mode**:
- Eliminates MAF sensor entirely — uses MAP + IAT to calculate airflow
- Requires GM 3-bar MAP sensor wired to ECU
- Uses a VE (Volumetric Efficiency) table instead of MAF transfer function
- Mandatory for big turbo builds that exceed MAF saturation (~2700 Hz / ~350 whp)
- For stock turbo, MAF-based is fine. Speed density becomes important at 16G+.

**Per-Cylinder Fuel Trim**:
- ECMLink can add/remove fuel from individual cylinders
- Critical for addressing the #4 lean condition: add 3-5% fuel to cylinder #4
- Requires individual EGT probes or wideband per-cylinder to tune properly (advanced)

**Flex Fuel Support**:
- Accepts Continental/GM ethanol content sensor input
- Automatically interpolates between gasoline and E85 fuel maps
- E85 stoichiometric ratio: 9.8:1 (vs 14.7:1 for gasoline)
- E85 WOT target: 10.0-10.5:1 (Lambda 0.68-0.72)
- E85 requires ~30% more fuel volume — injector sizing must account for this
- E85 is more knock-resistant (higher octane equivalent ~105) — allows more timing advance

**⚠ MANDATORY DEPENDENCY — Speed Density mode required for 2G flex-fuel install**:
- ECMLink V3 reads the ethanol sensor frequency on the **ECU's existing MAF input pin** (Pin 90 on Connector B-56). The MAF stops being the MAF and starts being the flex-fuel sensor input.
- This means the MAF must be disabled in ECMLink config, and the ECU must run in Speed Density mode using a **GM 3-bar MAP sensor + tuned VE table** instead of measured MAF airflow.
- **There is no MAF-mode flex-fuel path on the standard ECMLink 2G install.** Going E85 = going SD.
- Required hardware: GM 3-bar MAP sensor (~$60-80) + vacuum line + Weatherpack pigtail (~$15). IAT sensor already present.
- Required tuning labor: VE table calibration across full RPM × MAP range. Plan 5-15 datalogged driving sessions to dial in before E85 hardware activation. Without a properly tuned VE table the car drives WORSE than stock — rich at low load, lean at high load, possible misfires.
- Decision trigger: SD mode is unnecessary on stock TD04-13G (MAF works fine at this power level). The ONE reason to go SD on our car is "I want E85 flex-fuel on ECMLink." If E85 is not on the near-term path, defer SD mode.

**Anti-Lag Warning**:
- Retards timing dramatically to combust fuel in the exhaust manifold
- Keeps turbine spinning during throttle lift
- Extremely destructive: cracks exhaust manifolds, kills turbo bearings, destroys catalytic converters
- Track/competition use ONLY. Not for street. Drastically shortens component life.

**Knock Sensor Details**:
- Piezoelectric sensor mounted on block between cylinders 2 and 3
- Detects acoustic signature of detonation
- ECMLink knock response: immediate timing retard (1-3 degrees per event)
- Recovery rate is configurable — how fast timing returns after knock stops
- Knock Learn: persistent learned retard that survives key cycles
- False knock sources: road vibration, loose heat shields, exhaust rattle, belt chirp
- ECMLink allows sensitivity/filtering adjustment to reduce false positives

**Wideband O2 Sensor Recommendations** (for ECMLink integration):

| Brand/Model | Notes |
|-------------|-------|
| **AEM 30-0300 (UEGO)** | Community favorite for DSMs. 0-5V output, direct ECMLink compatibility. Gauge + controller integrated. |
| **Innovate MTX-L PLUS** | Excellent accuracy, 0-5V analog + serial output. Well-proven in DSM community. |
| **PLX DM-6 / SM-AFR** | Good option, 0-5V output, modular system. |
| **Zeitronix Zt-2** | Popular for standalone logging without ECMLink. |

All use Bosch LSU 4.9 sensor. Mount bung in downpipe, 18-24" after turbo. Do NOT reuse stock narrowband location — weld a separate bung.

### Pre-Wire Plan for Wideband O2 (ECU-Side)

**Context**: CIO is doing a future-proof pre-wire of wideband leads while the new MD335287 ECU is accessible (2026-05-27 advisory). Goal: pull leads now, cap them, install AEM 30-0300 X-Series UEGO controller later without re-opening the ECU.

**Authoritative source for pin numbers**: [ECMtuning 2G ECU Pinout PDF](https://www.ecmtuning.com/images/forums/2GECUPinout.pdf) — viewed looking INTO the ECU with male pins pointing out. **Confirm connector orientation before cutting** (looking at the harness side mirrors the pin numbers).

**Two leads to pull, both on Connector B-56**:

| Lead | ECU Pin | Stock Wire Color | What it is | Future AEM 30-0300 Connection |
|---|---|---|---|---|
| Signal | **Pin 75** | W (White) | Rear O2 Sensor signal input | AEM **white** wire (0-5V analog AFR) |
| Signal-ground reference | **Pin 92** | B (Black) | Sensor Ground (analog ground reference) | AEM **brown** wire (signal ground) |

**Why Pin 75 (Rear O2), not Pin 76 (Front O2)**: ECMLink V3 documents Pin 76 as usable "only when Open Loop is selected or narrowband O2 simulation is enabled" — more complex config path. Pin 75 is the community consensus: wire wideband white to it, then disable rear O2 monitor in ECMLink config (suppresses CEL). Rear O2's only stock job is emissions readiness — fine to lose for tuning. If Illinois biennial emissions test flags it, swap the wideband output back to stock rear O2 for that day.

**Why Pin 92 (Sensor Ground) is non-negotiable**: Wideband signal grounded to chassis instead of the ECU's sensor-ground reference picks up alternator whine + ignition noise — AFR readings become garbage. Routing the AEM's brown wire back to Pin 92 makes the signal share the ECU's analog reference. Clean reading.

**Alternative signal pin if pre-wiring Pin 75 is impractical**: **Pin 73 (MDP, Light Green/Black)** — the "most freely available" general-purpose analog input per the ECMLink wiki. Many 2G builds don't use the MDP sensor at all. Trade-off: less community documentation but a truly unused pin.

**Wire spec**:
- 20-22 AWG twisted-pair or 2-conductor shielded cable (shielded preferred for the long A-pillar run)
- Length: **~8 feet** ECU to A-pillar gauge pod (5-7 ft actual + 50% safety margin for routing)
- Label both ends: "WB-SIG" (Pin 75 tap) and "WB-GND" (Pin 92 tap)
- Cap free ends with heat-shrink + electrical tape until install day

**Routing rules** (skip these and the wideband signal will be noisy):
- Route AWAY from ignition wires + alternator harness — induced noise ruins analog AFR
- Pass firewall through OEM grommet (driver's side) if free capacity exists, else add dedicated grommet
- A-pillar mounts use 52mm dual pod (standard DSM setup — boost gauge + wideband gauge together)

**Do NOT power the AEM controller from an ECU pin**: AEM 30-0300 controller draws ~2A on the heater circuit during warm-up — too much for any ECU sensor pin. Run controller 12V from a dedicated fused switched-ignition circuit (under-dash or via a relay off the fuel-pump trigger). Only the white **signal** wire returns to the ECU at Pin 75. Chassis ground for the controller goes to chassis ground (NOT Pin 92 — Pin 92 is for the signal-reference brown wire only).

**Sources**:
- [ECMtuning Wiki — External Sensor Input](https://www.ecmtuning.com/wiki/externalsensorinput) (Pin 75 / Pin 73 / Pin 76 documentation)
- [DSMtuners — AEM WB and ECMLink](https://www.dsmtuners.com/threads/aem-wb-and-ecmlink.382721/) (community consensus on routing)
- [DSMtuners — ECMLink V3 WBO2 Captured Value](https://www.dsmtuners.com/threads/ecmlink-v3-wbo2-captured-value.434274/)

### Pre-Wire Plan for E85 Flex-Fuel Sensor — DO NOT pre-wire from ECU

**Standard ECMLink V3 flex-fuel routing for 2G DSM does NOT touch the ECU connectors.** The GM/Continental ethanol sensor wires to the **MAF connector** under the hood:

| Sensor wire | MAF connector pin | Stock MAF wire color |
|---|---|---|
| Signal ("Out") | Pin 3 | Blue with yellow stripe |
| 12V power ("Vcc") | Pin 4 | Thick red |
| Ground | (chassis) | — |

The ECU "sees" the ethanol frequency on its existing **MAF input (Pin 90 — Light Yellow on Connector B-56)** because ECMLink software reinterprets that pin as the flex-fuel input when AuxMaps/EthSensor mode is enabled. **No ECU-side pre-wire helps with flex-fuel** — all the wiring lives at the MAF plug in the engine bay, accessible without opening the ECU.

**MAJOR PAIRED DEPENDENCY**: This standard ECMLink flex-fuel install **requires Speed Density mode** (MAF disabled, GM 3-bar MAP sensor installed and wired). See [Flex Fuel Support](#flex-fuel-support) below — same physical pin can't do both MAF airflow AND flex-fuel frequency. Going E85 on this ECU means committing to SD mode + VE table calibration work.

**Source**: [ECMtuning Wiki — Ethanol Sensor Support](http://www.ecmtuning.com/wiki/ethanolsupport)

### ECMLink Tuning Order (When Installed)

**Phase 1: Baseline and Idle**
1. Flash ECMLink base map, verify communication
2. Set base timing to 12 degrees BTDC, verify with timing light (non-negotiable)
3. Calibrate TPS: 0.63V at closed throttle
4. Tune idle fuel: target 14.7:1 AFR, stable 700-800 RPM
5. Verify STFT within +/-3% at warm idle
6. Adjust ISC stepper motor base position if idle RPM is off

**Phase 2: Cruise / Part-Throttle**
7. Drive at steady state, log AFR/trims/timing/knock
8. Adjust fuel map cells in cruise region to achieve 14.5-15.0:1
9. Advance timing slowly in cruise cells until knock appears, back off 2 degrees
10. Verify LTFT trending toward 0% (if consistently positive, base map is too lean)

**Phase 3: WOT (On Dyno, Carefully)**
11. WOT pulls in 3rd or 4th gear
12. Target 11.0-11.5:1 AFR on pump gas (93 octane)
13. Monitor knock sum — must be 0 across entire pull
14. Monitor injector duty cycle — must stay below 85%
15. Verify boost matches target, no spikes
16. Advance timing 1 degree at a time, always review knock between pulls

**Phase 4: Boost Tuning**
17. Set boost target conservative (12 psi) initially
18. Verify fueling matches at target boost
19. Increase boost in 1 psi increments, re-verify knock and AFR each time
20. Max 14-15 psi on stock turbo

**Phase 5: Verification**
21. Repeat WOT pulls in multiple gears
22. Test hot restart (heat soak) behavior
23. Test cold start enrichment
24. Drive multiple days, verify LTFT stability
25. Clear fuel trims after map changes so LTFT doesn't compound with adjustments

---

## Modification Priority Path

### Recommended Order for Our Eclipse GST

This is the smart upgrade path — each step unlocks capability for the next, and nothing is wasted.

#### Phase A: Safety and Monitoring (Before Any Power Mods)
| Priority | Mod | Cost Est. | Why First |
|----------|-----|----------|-----------|
| **A1** | **Wideband O2 sensor + gauge** | $150-250 | Cannot tune safely without knowing actual AFR. Period. Innovate MTX-L or AEM 30-0300 recommended. |
| **A2** | **Boost gauge** | $30-80 | Need to know actual boost pressure. Mechanical gauge is cheapest and most reliable. |
| **A3** | **ECMLink V3** | $350 | Unlocks tuning, datalogging, knock monitoring. Nothing else matters without this. |
| **A4** | **Timing light** | $30 | Verify base timing after ECMLink flash. Non-negotiable. |

#### Phase B: Supporting Mods (Headroom for Power)
| Priority | Mod | Cost Est. | Why |
|----------|-----|----------|-----|
| **B1** | **Walbro 255lph fuel pump** | $70 | Stock pump runs out of flow above ~280 HP. Drop-in, no tune change needed. |
| **B2** | **3" downpipe** (catless for off-road/track, high-flow cat for street) | $150-400 | Single biggest bolt-on power gain. Reduces exhaust backpressure, reduces EGTs, helps turbo spool. |
| **B3** | **Test pipe or high-flow cat** | $50-200 | Removes factory catalytic converter restriction. |
| **B4** | **Cat-back exhaust** (2.5-3") | $200-500 | Completes exhaust from cat-back. Less restriction = less heat = more power. |
| **B5** | **Manual boost controller** | $30 | Raise boost from 10-12 to 14-15 psi. Simple, reliable. Tune first! |
| **B6** | **GM 3-bar MAP sensor** | $30-50 | Wire to ECMLink for accurate boost reading and speed density capability |

#### Phase C: Power (After Supporting Mods and Tune Dialed In)
| Priority | Mod | Why |
|----------|-----|-----|
| **C1** | **Tune on dyno** | Dial in fuel and timing under load with wideband and knock data |
| **C2** | **FMIC (front-mount intercooler)** | Replace restrictive stock side-mount. Lower IAT = denser charge = more power + safety |
| **C3** | **550cc injectors + retune** | More fuel headroom for higher boost |
| **C4** | **Turbo upgrade (16G or 20G)** | When stock turbo efficiency is maxed |
| **C5** | **ARP head studs** | Required before >18 psi on stock head bolts |

#### Phase D: Built Motor (When Stock Internals Limit Goals)

A "built motor" replaces the rotating assembly weak links with forged/stronger components.

| Component | Stock | Built Replacement |
|-----------|-------|-------------------|
| **Connecting rods** | Forged steel OE (good to ~350 whp) | Manley H-beam, Eagle, Wiseco (~800+ whp) |
| **Pistons** | Cast aluminum OE | Forged (Wiseco, JE, CP) — lower compression 8.0-8.5:1 |
| **Rod bearings** | OE (ACL or NDC) | ACL Race series, King HP |
| **Main bearings** | OE | ACL Race series |
| **Head gasket** | OE MLS | Cometic MLS + ARP head studs |
| **Crankshaft** | Stock 7-bolt (crankwalk risk) | 6-bolt conversion or aftermarket billet |
| **Balance shafts** | Stock (vibration damping) | Eliminated — delete kit, plug oil passages |
| **Cams** | Stock 248/248 degree | 272 or 274 degree for more top-end flow |
| **Head** | Stock | Ported and polished for airflow |

**When you need a built motor**: Targeting >350 whp reliably, running >25 psi consistently, E85 at high boost, any competitive motorsport.

**Typical cost (parts only)**: $1,500-2,500 economy, $3,000-5,000 full build + machine work ($800-1,500 additional for bore/hone/deck/balance).

**Power ceiling**: A properly built 4G63 is reliable to 600-700+ whp. Cast iron block is strong to ~800 whp before needing sleeves or aftermarket block. Drag racing DSMs run 800-1,000+ whp on built 4G63s.

### Turbo Upgrade Hierarchy

| Turbo | Type | Spool RPM | WHP Range | Character |
|-------|------|-----------|-----------|-----------|
| **Stock TD04-13G** (97-99) | OEM | 2,500-3,000 | 200-250 | Quick spool, runs out by 5,500 RPM |
| **16G** (Mitsubishi) | Bolt-on upgrade | 2,800-3,200 | 270-320 | Best "bang for buck" — spools nearly stock, +30-40% power |
| **20G** (Mitsubishi) | Bolt-on upgrade | 3,200-3,800 | 320-400 | Classic DSM upgrade. Great mid-range. |
| **FP Green** (Forced Performance) | Modern wheel | 3,500-4,000 | 350-420 | Better efficiency than 20G at similar size |
| **FP Red** (Forced Performance) | Large | 4,000-4,500 | 400-500 | Big power, needs built motor |
| **FP Black** (Forced Performance) | Very large | 4,500+ | 500-600+ | Full race. Very slow spool. |
| **Precision PT6062/6266** | Frame turbo | 4,500+ | 450-600+ | Journal or ball bearing. Modern design. |

**Community upgrade path**: Stock → 16G → 20G → FP Green/Red → big frame. The 16G is the most popular first upgrade because it bolts onto stock manifold/exhaust housing and spools almost as quickly as stock.

---

## Common Failure Modes

### The 4G63 Hit List (What Breaks and Why)

#### 1. Crankwalk (7-bolt engines, 1995.5-1999)
- **What**: Crankshaft physically moves fore/aft in the block. Thrust bearing on the #3 main bearing cap wears through, allowing axial play.
- **Susceptible**: Our 1998 is a 7-bolt. Yes, it's at risk. 6-bolt engines (pre-1995.5) have a larger thrust bearing surface and are far less prone.
- **Symptoms**: Clutch pedal engagement point changes, metallic scraping at idle, CAS (crank angle sensor) signal dropout causing random stalling or no-start, timing errors in datalogs
- **Cause**: Smaller thrust bearing surface area in 7-bolt design vs 6-bolt
- **Prevention**: Don't dump the clutch aggressively (side-loads thrust bearing). Don't hold clutch in at stoplights for extended periods. Avoid aggressive launch control.
- **Fix**: Engine rebuild with 6-bolt crank swap (the gold standard fix), or Clevite TW-618S thrust bearing shims as a band-aid
- **Detection**: With trans in neutral, clutch depressed — push crank by hand. If you feel fore/aft play, crankwalk has begun.
- **Risk level**: Low for street driving. Higher for repeated hard launches.

#### 2. Head Gasket Failure
- **What**: MLS head gasket blows between cylinder and coolant/oil passage
- **Symptoms**: White smoke from exhaust, coolant loss with no visible leak, milky oil, bubbles in coolant, overheating
- **Common on**: Cars running >18-20 psi on stock head bolts
- **Prevention**: ARP head studs before high boost (~$100, massive improvement in clamping force). Proper tune (no detonation). Maintain cooling system. For builds above 25 psi: O-ring the block (machine a groove around each cylinder bore that compresses a copper/stainless wire ring into the gasket).
- **Risk for us**: Low at stock boost. Moderate if boost is raised without studs.

#### 3. #4 Cylinder Lean/Failure
- **What**: #4 runs leaner than 1-3 due to intake runner design
- **Why**: Shortest intake runner, farthest from plenum, hottest cylinder
- **Symptoms**: #4 spark plug whiter than others, #4 piston damage first in detonation events
- **Prevention**: Slightly richer overall tune (target 11.0:1 WOT, not 11.8:1), ensure fuel delivery to all cylinders
- **Risk for us**: Present. Cannot monitor per-cylinder without ECMLink and individual EGT probes.

#### 4. MAF Sensor Saturation
- **What**: Stock MAF maxes out at ~2700 Hz frequency output (~300 HP)
- **Result**: ECU can't see additional airflow, doesn't add enough fuel, engine goes lean at high RPM/boost
- **Symptoms**: Power falls off hard above a certain RPM, lean AFR (if wideband installed)
- **Prevention**: Speed density conversion via ECMLink + MAP sensor (eliminates MAF entirely)
- **Risk for us**: Low at stock boost. High if turbo is upgraded without addressing MAF limit.

#### 5. Fuel Pump Failure
- **What**: Stock pump can't keep up with fuel demand at higher power levels
- **Symptoms**: Lean AFR at WOT (especially at higher RPM where demand is greatest), stumble/cut-out at high RPM under boost
- **Prevention**: Walbro 255lph is the community-standard upgrade ($70, drop-in)
- **Risk for us**: Low at stock boost. Moderate above 14 psi.

#### 6. Timing Belt Failure
- **What**: Belt breaks → pistons hit valves (INTERFERENCE engine)
- **Result**: Bent valves, possible piston damage. Engine needs head rebuild minimum.
- **Interval**: Every 60,000 miles. Do NOT skip.
- **Risk for us**: Depends on belt age/mileage. On a 1998, this belt has been replaced at least once (hopefully).
- **Always replace**: Water pump, tensioner, and idler pulleys at the same time.

#### 7. Oil Starvation
- **What**: Oil pickup loses prime during hard cornering or sustained lateral G
- **Why**: Stock oil pan design allows oil to slosh away from pickup
- **Risk for us**: LOW — city driving, no track. Would matter for autocross/road course.
- **Prevention**: Oil pan baffle, windage tray, or accusump

---

## DSM-Specific Quirks

### Things That Confuse People New to 2G DSMs

1. **MDP ≠ MAP**: PID 0x0B reads the MDP sensor (EGR monitoring), not a true MAP sensor. Don't use it for boost readings.

2. **Narrowband ≠ Wideband**: Stock O2 sensor only tells rich/lean relative to 14.7:1 (switches at ~0.45V). It cannot tell you actual AFR. Under boost, 14.7:1 is dangerously lean — you need 11.0:1. The stock sensor is useless for tuning.

3. **IAT sensor is inside the MAF**: Pins 1 (5V), 5 (ground), 6 (signal). If IAT reads constant -40F/-40C, the MAF connector is bad or MAF is dead.

4. **ECMLink "Lock comms" checkbox**: When checked, NO OBD-II scanner can communicate with the ECU. If OBD-II connection fails after ECMLink install, check this setting first.

5. **1995 ECU ≠ 1996-1999 ECU**: If someone swapped in a '95 ECU, OBD-II won't work properly. The '95 uses a different implementation.

6. **Battery relocation**: Many DSMs have the battery relocated to the trunk. If grounds aren't properly run (dedicated 4-gauge ground wire), electrical gremlins and poor OBD communication result.

7. **OBD-II port power**: Pin 16 is unswitched +12V. Corrosion in the engine bay fuse box (common on 25+ year old cars) can cause intermittent OBD-II connection.

8. **OBDLink LX handles missing L-Line**: Pin 15 (L-Line) is absent on some 2G DSMs. The OBDLink LX handles this — some cheaper adapters don't.

9. **BOV vent-to-atmosphere on stock MAF**: If the BOV vents to atmosphere (not recirculated), the ECU has already metered that air via the MAF. When the BOV dumps it, the ECU injects fuel for air that's no longer there → rich condition between shifts. Minor on stock, can cause stumble on bigger turbos.

10. **Stock boost gauge is inaccurate**: The factory boost gauge (if equipped) reads manifold vacuum/pressure but is notoriously inaccurate. Don't trust it for tuning.

---

## Tuning Glossary

| Term | Definition |
|------|-----------|
| **AFR** | Air-Fuel Ratio. Stoichiometric is 14.7:1 for gasoline. Rich is <14.7, lean is >14.7. Under boost, target 11.0-11.8:1 for safety. |
| **BTDC** | Before Top Dead Center. Refers to ignition timing — how many degrees before piston reaches TDC the spark fires. |
| **Boost creep** | Condition where boost exceeds target because exhaust flow overcomes wastegate capacity. |
| **Boost spike** | Momentary overshoot of target boost during turbo spool-up. 1-2 psi normal, >3 psi dangerous. |
| **Closed loop** | ECU is actively adjusting fuel based on O2 sensor feedback. Normal at idle and cruise. |
| **Crankwalk** | Forward/rearward movement of crank in block, destroying thrust bearing. 7-bolt 4G63 issue. |
| **Datalog** | Time-series recording of engine parameters. The foundation of all tuning. |
| **Detonation** | See Knock. |
| **DSM** | Diamond Star Motors — joint venture between Mitsubishi and Chrysler. Eclipse, Talon, Laser. |
| **Duty cycle** | Percentage of time an injector is open per engine cycle. >85% is dangerously high. |
| **EGT** | Exhaust Gas Temperature. Measured with thermocouple in exhaust manifold or downpipe. |
| **FMIC** | Front-Mount Intercooler. Replaces stock side-mount. Better cooling, more piping. |
| **Knock** | Uncontrolled combustion from excessive cylinder pressure/heat. Destroys pistons and bearings. The #1 enemy. |
| **LTFT** | Long-Term Fuel Trim. Learned ECU correction over time. Drift indicates persistent issue. |
| **MAP** | Manifold Absolute Pressure sensor. Measures actual intake manifold pressure. |
| **MAF** | Mass Air Flow sensor. Measures airflow into engine. Primary fuel calculation input on 4G63. |
| **MDP** | Manifold Differential Pressure. EGR monitoring sensor on 4G63. NOT a MAP sensor. |
| **MLS** | Multi-Layer Steel (head gasket type). |
| **Open loop** | ECU runs from programmed tables, ignores O2 sensor. Occurs at WOT and during cold start. |
| **Speed density** | Fuel calculation method using MAP sensor + IAT instead of MAF. Eliminates MAF saturation. Requires ECMLink. |
| **Spool** | When the turbo builds boost. Low spool = boost comes early. Our stock turbo spools ~2,500-3,000 RPM. |
| **STFT** | Short-Term Fuel Trim. Real-time ECU fuel correction. Best lean/rich indicator via OBD-II. |
| **Stoich** | Stoichiometric ratio — 14.7:1 for gasoline. Chemically complete combustion. Not safe under boost. |
| **WOT** | Wide Open Throttle. Full throttle. TPS reads 95-100%. ECU goes open loop. |
| **2G** | Second generation DSM (1995-1999 Eclipse/Talon). Our car. |
| **4G63** | Mitsubishi's 2.0L 4-cylinder engine. Turbocharged version (4G63T) is legendary in tuning community. Cast iron block handles big power. |
| **7-bolt** | Crankshaft with 7 flywheel bolts (1995.5-1999). Known crankwalk risk. Vs 6-bolt (pre-1995.5) which is more desirable. |

---

## UPS HAT Dropout Characteristics (Drain 7 baseline)

> Pi-side power-management context, not engine tuning. Captured here per BL-009 / Sprint 23 US-278 resolution (CIO-approved Option 1B+2B, 2026-05-03) so future tuning + car-wiring scope decisions (US-169 / US-189 / US-190) reference empirical UPS HAT behavior instead of fabricating values.

### Hardware

The data-collection Pi 5 runs from a **Geekworm X1209-style UPS HAT** with a **MAX17048 fuel-gauge IC** managing a single LiPo cell. The HAT's **on-board buck converter** regulates the LiPo cell voltage up to the Pi's 5V rail. When the LiPo cell voltage falls below the buck converter's minimum input ("dropout knee"), the 5V rail collapses and the Pi loses power abruptly — there is no graceful low-voltage shutdown from the HAT itself; the project's `PowerDownOrchestrator` (US-216 ladder) is responsible for triggering `systemctl poweroff` *before* the dropout knee is reached.

### Empirical baseline — Drain Test 7 (2026-05-02 → 2026-05-03)

| Measurement | Value | Source |
|-------------|-------|--------|
| **Buck-converter dropout knee (Pi died)** | **VCELL ≈ 3.30 V** | Drain 7 CSV last reading 3.305 V @ T+959 s (Pi power loss immediately after) |
| **Runtime under typical load** | **~16 min** (959 s) on a fully-warmed-up cell starting at 3.57 V / 89% SOC | Drain 7 CSV first → last row (`seconds_on_battery`: 0 → 959) |
| **VCELL range observed during drain** | 3.71 V (peak, settling transient) → 3.26 V (last) | Drain 7 CSV `vcell_v` min/max |
| **SOC range** (MAX17048 fuel-gauge, known-uncalibrated) | 89% → 57% | Drain 7 CSV `soc_pct` first/last — note: SOC drift makes VCELL the authoritative trigger source per US-234 |
| **CPU temperature** | 37.8 – 40.6 °C | Drain 7 CSV `cpu_temp_c` min/max |
| **CPU load (1-min avg)** | 0.01 – 0.50 (idle-ish; BT scan + HDMI display + drain-forensics logger active) | Drain 7 CSV `load_1min` min/max |
| **Pi5 throttled_hex** | **`0x0` throughout (zero throttling, zero brownout)** | Drain 7 CSV `throttled_hex` set across all 161 rows |

### Drain 7 baseline ratified — Drains 8, 9, 10 (2026-05-03 → 2026-05-04)

Three additional drain tests since Drain 7 ratify the dropout knee and the brownout-disproof, and one of them inflects the runtime envelope.

**Drain Test 8** (2026-05-03 ~13:50 UTC → 14:08 UTC, V0.24.0):
- Started VCELL 3.91 V / 95% SOC (more headroom than Drain 7's 3.57 V start)
- Hard crash signature identical to Drain 7 — last VCELL 3.34 V @ T+1054 s
- 178 forensic CSV rows; `throttled_hex=0x0` all 178 rows
- Runtime to dropout: **17 min 29 sec** under same load profile
- Same conclusion: HAT-side hard cutoff at the dropout knee, no Pi5 brownout

**Drain Test 9** (2026-05-03 ~22:00 UTC, V0.24.0): bug-still-present regression baseline drain. CIO let it run to dropout. Same hard-crash signature, same `throttled_hex=0x0`. Useful as the last documented "ladder broken, hard crash" event before the V0.24.1 fix.

**Drain Test 10** (2026-05-04, V0.24.1 deployed): **inflection point.** First drain after the cross-module-PowerSource-enum fix. Ladder fired correctly. Graceful shutdown signature documented separately below.

**Cumulative observation across Drains 7 + 8 + 9** (~50 min combined runtime under battery, three independent drain events):
- `throttled_hex` stayed `0x0` for **every sample of every drain.** Zero Pi5 undervoltage events. Zero throttling. The "Pi5 brownout under heavy load" hypothesis is conclusively dead.
- CPU temperature envelope held 38 – 41 °C across all three drains.
- Buck-converter dropout knee reproducibly between **3.26 V and 3.34 V** depending on instantaneous load. Treat **3.30 V** as the working dropout midpoint.

### Post-fix signature — Drain Test 10 + May 4-5 cycles (V0.24.1 onward)

Once the V0.24.1 fix landed (cross-module PowerSource enum identity), the failure mode changed from "hard crash at dropout knee" to "graceful shutdown at TRIGGER threshold." Four power-down cycles on V0.24.1 captured cleanly:

| Cycle | Date (UTC) | Start VCELL | TRIGGER VCELL | Runtime (start → TRIGGER) | Outcome |
|-------|-----------|-------------|---------------|---------------------------|---------|
| Drain 10 + cycle 1 | 2026-05-04 13:21 → 13:34 | 4.149 V | 3.410 V | ~13 min | Graceful poweroff |
| Cycle 2 | 2026-05-04 18:58 → 19:09 | 4.219 V | 3.424 V | ~11 min | Graceful poweroff |
| Cycle 3 | 2026-05-04 19:32 → 19:39 | 4.204 V | 3.440 V | ~7 min (warm cell, less depleted) | Graceful poweroff |
| Cycle 4 | 2026-05-05 23:59 → 2026-05-06 00:10 | 4.220 V | 3.421 V | ~10 min | Graceful poweroff |

**Post-fix shutdown headroom realized**: TRIGGER fires at 3.41 – 3.44 V. Buck dropout is at 3.26 – 3.34 V. **Working margin during `systemctl poweroff` is ~80 – 180 mV (≈ 30 – 90 sec of additional drain time)** before the HAT collapses. Boot-table evidence shows graceful shutdown completing within ~3 min of TRIGGER, well inside the buck headroom.

**Runtime envelope under V0.24.1** (start of battery → TRIGGER, fully-charged cell):
- Best observed: ~13 min on a fresh cell starting at 4.15 – 4.22 V
- Operationally plan for **10 – 13 min from key-off to graceful poweroff** in-vehicle (US-169 / US-189 / US-190 future scope), versus the 16-minute hard-crash budget under the pre-fix ladder.
- The 3-minute gap between TRIGGER row and boot-table "LAST ENTRY" is the OS shutdown sequence flushing; it is observed consistently and should be budgeted as such.

### Why this matters

Drain Test 7 (2026-05-02) was the first drain after Sprint 22 deployed the discriminator-trio fix for the US-216 ladder failures. The forensic logger (US-262) confirmed the `throttled_hex` column stayed `0x0` for the entire 16-minute drain — eliminating CIO's earlier hypothesis that **Pi5 brownouts** were causing the hard crashes at the dropout knee. The actual failure mode is exactly what one would expect: the HAT's buck converter gives up cleanly at the LiPo dropout knee, and the Pi loses 5V immediately. There is no progressive degradation, no warning from the HAT, no Pi-side brownout indication — just a hard cutoff.

This means the staged shutdown ladder (US-216: WARNING / IMMINENT / TRIGGER at VCELL 3.70 / 3.55 / 3.45 V) **must** complete its `systemctl poweroff` work above the ~3.30 V dropout knee. The 3.45 V TRIGGER threshold leaves ~0.15 V of head-room (≈ 5 minutes at the observed drain rate) for the OS to flush filesystems and halt cleanly.

### Operational implications

- **In-car wiring (US-169 / US-189 / US-190 future scope)**: when the Pi is permanently wired to the car's accessory line, every key-off transitions the Pi to UPS battery. The 16-minute typical-load runtime is the upper bound on how long the staged shutdown has to run before the HAT collapses. With the 3.45 V TRIGGER threshold, expect ~10-12 minutes of "Pi still alive on battery after key-off" before `systemctl poweroff` fires.
- **Bench drain-test cadence**: a fully-charged cell should give ~16 minutes of useful drain-test window with the typical load profile above. Drain tests beyond 16 minutes need the HAT plugged back into AC.
- **MAX17048 SOC% is not authoritative**: the SOC-to-VCELL mapping drifted enough during Drain 7 (89% → 57% over 16 min, but VCELL fell from 3.57 V to 3.30 V — a steep proportional fall) that VCELL is the trigger source per US-234 / Sprint 19. Dashboards display VCELL primary, SOC secondary `(uncalibrated)` per US-264.
- **No Pi5 thermal protection trip**: CPU stayed in the 38–40 °C range (low-load envelope) and `throttled_hex` was `0x0` throughout. Any future hard crash with `throttled_hex != 0x0` should be diagnosed differently (load spike, thermal, voltage-droop on the 5V rail) rather than treated as another dropout-knee event.

### References

- **Drain 7 forensic CSV (Pi)**: `/var/log/eclipse-obd/drain-forensics-20260502T235909Z.csv`
- **Drain 7 forensic CSV (workstation copy)**: `offices/tuner/drain7-forensics.csv`
- **Drain 8 forensic CSV (Pi)**: `/var/log/eclipse-obd/drain-forensics-20260503T135023Z.csv`
- **Drain 10 + May 4-5 cycles**: `power_log` table (`stage_warning` / `stage_imminent` / `stage_trigger` rows) and `battery_health_log` table (drain-event-open/close pairs); per-cycle VCELL values pulled directly from those tables, no separate CSV
- **Sprint 24 saga-closeout writeup**: `offices/pm/inbox/2026-05-03-from-spool-sprint24-ladder-fix-bug-isolated.md`
- **Sprint 25 saga-closure (Ralph)**: `offices/tuner/inbox/2026-05-04-from-ralph-v0241-drain10-passed.md`
- **Original spec note**: `offices/pm/inbox/2026-05-02-from-spool-sprint23-ladder-fix-and-forensic-gaps.md` (Story 5)
- **Cross-link**: see `specs/grounded-knowledge.md` "Safe Operating Ranges" section for the project-wide PM Rule 7 pointer to this section.
- **Future-scope stories that reference this**: US-169 (UPS in-car ignition cycles), US-189 / US-190 (B-043 PowerLossOrchestrator lifecycle).

---

## Drain Test Procedure

Repeatable validation procedure for the Pi UPS HAT + V0.24.1 ladder + close-event writers lives in a sibling file:

**`offices/tuner/drain-test-procedure.md`**

Run this whenever a release ships that touches power management, drain handling, sync of `battery_health_log`, or `startup_log` writers — especially right after a fix lands, to validate the fix is actually in production. **Drain Test 13 (2026-05-10, V0.27.2)** is the canonical reference run with full pass/fail evaluation methodology. New tests append a row to the procedure file's "Historical Drain Test Log" section. Pre-V0.24.1 drain history (Drains 1-7) lives in this file's "UPS HAT Dropout Characteristics (Drain 7 baseline)" section above; the procedure file picks up from Drain 8 forward.

---

## Regression Fixture Lock-Down

> Locked-down SHA-256 hashes for the Pi-side regression fixtures in `data/regression/pi-inputs/`. These fixtures are inputs to the project's regression test suite and must NEVER be silently modified by cleanup scripts, deploys, or any other operation. The truncate scripts (`truncate_session23.py`, `truncate_drive_id_1_pollution.py`) already enforce the lock-down for `eclipse_idle.db`; this table extends the protection to all four fixtures.
>
> **Locked at**: 2026-05-09 (Spool Session 10) by CIO authorization.
> **Verify with**: `sha256sum data/regression/pi-inputs/*.db`
> **If a hash diverges**: STOP. Investigate why. Restore from git history. Do not proceed with whatever operation caused the change without explicit CIO approval.

| Fixture | Bytes | SHA-256 |
|---|---:|---|
| `eclipse_idle.db` | [EXACT: 188416 — DO NOT CHANGE] | [EXACT: `0b90b188fa31f6285d8440ba1a251678a2ac652dd589314a50062fa06c5d38db` — DO NOT CHANGE] |
| `cold_start.db` | [EXACT: 155648 — DO NOT CHANGE] | [EXACT: `45f342bbadd4e6ad36ab3585e3b1e62218dad264e2405e9fcb00c8ed748ccd1f` — DO NOT CHANGE] |
| `errand_day.db` | [EXACT: 458752 — DO NOT CHANGE] | [EXACT: `ee611f7483dd6393dee7e55ed18947401a66e9bb96c77b33536ef45a937b50c3` — DO NOT CHANGE] |
| `local_loop.db` | [EXACT: 266240 — DO NOT CHANGE] | [EXACT: `df175a21522ac9abe3d3f4fd3c10ffe154ac9a9e038990f7182154017ab3109d` — DO NOT CHANGE] |

**Cross-references**:
- `eclipse_idle.db` SHA is also pinned in `scripts/truncate_session23.py:110` (`FIXTURE_EXPECTED_SHA256`) — keep synchronized if either is updated through legitimate fixture regeneration.
- `eclipse_idle.metadata.json` (2,167 bytes, 2026-04-20) accompanies `eclipse_idle.db`; not hash-locked here because it's regenerable from the fixture itself, but worth knowing it exists.
- Three SQLite sidecar files may exist alongside `eclipse_idle.db` (`-shm`, `-wal`, `-journal`) and are NOT locked — those are runtime SQLite artifacts and may legitimately mutate when the fixture is read.

**Sister fixtures NOT yet hash-locked here** (other agents may add as needed): nothing under `data/regression/pi-inputs/` is unaccounted for as of 2026-05-09. If the project adds future fixtures, the new file should be hash-locked in this table the same day.

---

## Session Log

| Date | Notes |
|------|-------|
| 2026-04-09 | Spool agent created. Initial knowledge base populated from project specs (obd2-research.md, grounded-knowledge.md, architecture.md) and DSMTuners community knowledge. Vehicle profile established. Safe operating ranges defined. Added ECMLink deeper details (speed density, per-cylinder trim, flex fuel, anti-lag, knock sensor details, wideband recommendations). Added detailed tuning procedure (5-phase). Added built motor specs with costs. Added turbo hierarchy with Forced Performance models. Added timing belt system details. Clarified 97-99 vs 95-96 turbo designation. |
| 2026-04-19 | **Session 23 first-real-data update.** Confirmed PID 0x0B, 0x0A, 0x42 unsupported on this 2G ECU — moved 0x42 to Tier 2 with unsupported flag and documented battery voltage alternate path (ELM327 `ATRV` / `ELM_VOLTAGE` adapter query). Marked Tier 1 PIDs as ✅ confirmed Session 23. Added new top-level section **"This Car's Empirical Baseline"** capturing observed warm-idle values (LTFT 0% flat, STFT ±1.5%, RPM 761–852, coolant 73–74°C plateau, timing 5–9° BTDC at idle, IAT 14°C, MAF 3.5 g/s) with interpretation anchors for future-capture comparison. Flagged timing-advance observation (5–9° vs community 10–15° norm) and coolant-plateau observation (below 180°F op temp — revisit next drill for thermostat diagnosis). Documented diagnostic gaps the 23-second capture cannot address. **Pending Spool self-assigned research** (CIO: don't forget): (1) 2G DSM thermostat diagnostic procedure — higher priority, resolves at next drill; (2) 2G DSM DTC interpretation cheat sheet — lower priority, blocked on Ralph landing DTC capture. See auto memory `project_spool_pending_research.md`. |
| 2026-05-09 | **Spool Session 10 evening — Drives 8/9/10 captured; car-coupled stereo USB-C debut FAILED (drives 9+10).** Drive 8 = cold-start city/highway, 18 min, 8,268 rows @ 459 rows/min, captured CLEAN, JOINS pre-mod shelf. **POWER for Drive 8 = Pi stock 5A supply via camping-battery AC inverter (CIO had portable battery in car) — same power model as drives 6+7, NOT car-coupled.** Drive 9 (pizza run, 30 min) = **FIRST car-coupled drive ever** via stereo USB-C, immediately compromised: dashboard flickering between `power=car` and `power=battery`, capture rate degraded 12× to 36 rows/min, HELD OUT from shelf. Drive 10 (garage pull-in, 2:10) = drain id=12 opened 8 sec into drive, NOT ELIGIBLE. **Stereo USB-C path has 0/2 success rate** — undersized (≤3A) for Pi 5 (5A spec). Mike will proceed with fuse-box wiring (12V→5V/5A buck converter on switched circuit). **Until that ships, no further IRL drives.** Two bug priorities filed to PM: (a) NEW DriveDetector warm-restart-cranking gap — DriveDetector missed Mike's 2-3 min around-the-block test (1,078 NULL-drive_id orphan rows); (b) battery_health_log close-event-on-poweroff race BUMPED P3→P2 (4 of 4 drains tonight unclosed). Drive annotations 8/9/10 written to `drive-annotations.md` + `obd2db.drive_annotations`. Wiring milestone subsection added to "Pre-Mod Baseline Shelf" — drives split into THREE power eras: bench-tethered (3-5), portable-inverter (6-8), car-coupled stereo USB-C (9-10 broken), car-coupled fuse-box (future 11+). PID 0x2F (fuel level) probe story added to PM Sprint-28 P3 list. PM note `2026-05-10-from-spool-three-drives-tonight-power-blocker-drive-counter-clarification.md` filed. |
| 2026-05-09 | **Spool Session 10 morning — DB cleanup + housekeeping + pre-mod baseline shelf formalized.** Cleaned up `obd2db` on chi-srv-01 (dropped ~58k bench-poll orphan rows + ~28k connection-log spam + 84 stale stats + 4 stale trends; verified all 5 keep-drives intact via row counts). Captured drive annotations (fuel grade, level, ambient, intent, etc.) for drives 3–7 from CIO interview into both `offices/tuner/drive-annotations.md` and a new sidecar table `obd2db.drive_annotations` (CIO-authorized). **Major framing correction**: drives 3, 4, 5 are explicitly idle-only/parked system tests, NOT driving captures (knowledge.md previously had this for Drive 5; now correct for all three). Locked SHA-256 hashes for all 4 regression fixtures (`eclipse_idle.db` + `cold_start.db` + `errand_day.db` + `local_loop.db`) into a new "Regression Fixture Lock-Down" appendix section (TOC #20) with `[EXACT: hash — DO NOT CHANGE]` markers. Added "Pre-Mod Baseline Shelf" subsection above the per-drive details: 5 drives on shelf, shelf is OPEN until Walbro pump install, rules for joining/retiring/cross-shelf-comparison defined, outstanding shelf gaps enumerated (sustained WOT, hot-soak, wet-pavement, cold-engine-WOT). Sent 4 PM notes today: (1) post-cleanup housekeeping findings 4 items, (2) weather-API feature idea (free API at drive_end populates ambient/weather automatically — pairs with Spec 2 below), (3) three-specs bundle (mod_state enum + drive_annotations table + drive_summary writer contract). Saved 2 memories: feedback `protocol-timing specs validate against empirical baseline before pinning`, reference `chi-srv-01 obd2db direct query access + repo mount-point equivalence` (`Z:\O\OBD2v2` == `/z/O/OBD2v2` == `/mnt/projects/O/OBD2v2`, same NAS, same files). |
| 2026-05-05 | **Drain 8 + 9 + 10 ratify Drain 7 baseline; post-V0.24.1 graceful-shutdown signature documented.** Appended two subsections to "UPS HAT Dropout Characteristics": (1) "Drain 7 baseline ratified — Drains 8, 9, 10" — `throttled_hex=0x0` confirmed across ~50 min combined battery runtime + buck dropout knee reproducibly between 3.26-3.34 V across three independent drains; Pi5-brownout hypothesis conclusively dead; (2) "Post-fix signature — Drain Test 10 + May 4-5 cycles (V0.24.1 onward)" — 4 graceful-shutdown cycles with TRIGGER firing at 3.41-3.44 V, working margin 80-180 mV before buck dropout, 10-13 min runtime envelope key-off → graceful poweroff (vs prior 16-min hard-crash budget). References updated to point at Drain 8 CSV, Sprint 24 saga writeup, and Ralph's Sprint 25 closeout note. Per Marcus's standing invitation in `offices/tuner/inbox/2026-05-03-from-marcus-sprint24-loaded-us278-already-shipped.md` (Spool-side update, not a sprint story). |
| 2026-05-03 | **Sprint 23 US-278 — UPS HAT Dropout Characteristics section appended (Rex Session 152, Ralph dev work — Pi-side power-mgmt, not engine tuning).** Added new top-level section "UPS HAT Dropout Characteristics (Drain 7 baseline)" between Tuning Glossary and Session Log. Captures empirical Drain 7 measurements (2026-05-02 → 2026-05-03): buck-converter dropout knee at VCELL ≈ 3.30 V (Pi died at 3.305 V @ T+959 s); ~16-min runtime under typical load (Pi5 idle, BT scan, HDMI display); CPU 37.8–40.6 °C; load-1min 0.01–0.50; throttled_hex `0x0` throughout (DISPROVES the Pi5-brownout hypothesis from CIO 2026-05-01). All measurements grounded in `offices/tuner/drain7-forensics.csv` (workstation copy of `/var/log/eclipse-obd/drain-forensics-20260502T235909Z.csv` on Pi). Cross-links US-169 / US-189 / US-190 future scope. Resolves BL-009 with CIO-approved Option 1B+2B (single-file convention preserved; cross-link target = `specs/grounded-knowledge.md`). **Caveat for Spool**: cross-link in `specs/grounded-knowledge.md` was placed under existing "Safe Operating Ranges (Community-Sourced)" section as a one-line note rather than under a "MAX17048/UPS subsection" (which doesn't exist) — see `offices/pm/inbox/2026-05-03-from-rex-us278-grounded-knowledge-no-anchor-stop-condition.md` for the deliberate-divergence rationale + suggested future re-positioning if Spool prefers. |
