# Spool's Tuning Knowledge Base

> This is the single source of truth for all engine tuning knowledge in the Eclipse OBD-II project.
> Maintained by Spool (Tuning SME). Last major update: 2026-04-20 (Session 6 — I-016 thermostat closed benign via gauge drill; Session 23 coolant reframed as mid-warmup snapshot, not steady-state baseline).

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

### 1998 Mitsubishi Eclipse GST (2G DSM)

| Attribute | Value |
|-----------|-------|
| **VIN** | 4A3AK54F8WE122916 |
| **Year** | 1998 |
| **Model** | Eclipse GST (turbo, FWD) |
| **Engine** | 4G63 DOHC Turbo |
| **Displacement** | 1,997 cc (2.0L) |
| **Transmission** | Manual (assumed) |
| **ECU** | Stock with modified EPROM |
| **OBD-II Protocol** | ISO 9141-2 (K-Line) |
| **Generation** | 2G DSM (1995-1999) |
| **Odometer** | ~76,000 miles (as of 2026) |
| **Usage** | Summer only, garage stored winters. Low-stress duty cycle. |
| **Crankshaft** | 7-bolt (1995.5+ production) |

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

> These are observed values from **this specific Eclipse** (1998 GST, 76k mi, stock turbo TD04-13G, stock internals, modified EPROM, coilovers/mounts/clutch/tie-rods fresh, no wideband, no ECMLink). Use these as the **comparison baseline** when grading future captures — community data informs us, this car's data grounds us.
>
> **Always check these against the current capture. A healthy engine returns to its own baseline.**

### Session 23 — 2026-04-19 — First Real OBD Data (Warm Idle, ~23s captured across 2 windows)

**Context**: Cold-start → warm idle → shutdown wall-clock ~10 min, but real OBD-connected data capture was ~23 seconds due to TD-023 connection churn. Engine was already warm in the captured window. No warmup curve, no load, no drive.

| Parameter | Observed Value | Assessment |
|-----------|----------------|------------|
| **RPM (warm idle)** | 761–852, avg 793 (±45) | Normal. Not hunting (<150 RPM swing). Not stuck. |
| **LTFT** | **0.00% flat across 13 samples** | **TUNE IS DIALED.** Base fuel map does not need long-term correction. |
| **STFT** | −0.78% to +1.56%, avg +0.06% | Textbook. Tiny nudges around stoich. Closed-loop happy. |
| **O2 B1S1** | 0–0.82V switching, avg 0.46V | Healthy narrowband. Full-authority swing crossing stoich (~0.45V). |
| **MAF (warm idle)** | 3.49–3.68 g/s (tight range) | Plausible idle airflow for 2.0L/4-cyl. No drop-outs. |
| **Engine Load (warm idle)** | 19.22–20.78% | Tight clamp. Normal warm idle. |
| **Throttle Position (closed)** | 0.78% flat | Clean TPS zero offset. No stiction. |
| **Timing Advance (warm idle)** | 5–9° BTDC (avg 7°) | ⚠ Lower than stock 2G community norm (10–15° BTDC at idle). Possible causes: modified EPROM programmed conservative, ECU adaptive still learning, or python-obd integer rounding. Revisit at ECMLink baseline. |
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

## Session Log

| Date | Notes |
|------|-------|
| 2026-04-09 | Spool agent created. Initial knowledge base populated from project specs (obd2-research.md, grounded-knowledge.md, architecture.md) and DSMTuners community knowledge. Vehicle profile established. Safe operating ranges defined. Added ECMLink deeper details (speed density, per-cylinder trim, flex fuel, anti-lag, knock sensor details, wideband recommendations). Added detailed tuning procedure (5-phase). Added built motor specs with costs. Added turbo hierarchy with Forced Performance models. Added timing belt system details. Clarified 97-99 vs 95-96 turbo designation. |
| 2026-04-19 | **Session 23 first-real-data update.** Confirmed PID 0x0B, 0x0A, 0x42 unsupported on this 2G ECU — moved 0x42 to Tier 2 with unsupported flag and documented battery voltage alternate path (ELM327 `ATRV` / `ELM_VOLTAGE` adapter query). Marked Tier 1 PIDs as ✅ confirmed Session 23. Added new top-level section **"This Car's Empirical Baseline"** capturing observed warm-idle values (LTFT 0% flat, STFT ±1.5%, RPM 761–852, coolant 73–74°C plateau, timing 5–9° BTDC at idle, IAT 14°C, MAF 3.5 g/s) with interpretation anchors for future-capture comparison. Flagged timing-advance observation (5–9° vs community 10–15° norm) and coolant-plateau observation (below 180°F op temp — revisit next drill for thermostat diagnosis). Documented diagnostic gaps the 23-second capture cannot address. **Pending Spool self-assigned research** (CIO: don't forget): (1) 2G DSM thermostat diagnostic procedure — higher priority, resolves at next drill; (2) 2G DSM DTC interpretation cheat sheet — lower priority, blocked on Ralph landing DTC capture. See auto memory `project_spool_pending_research.md`. |
