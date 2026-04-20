# OBD-II Research Reference: 1998 Mitsubishi Eclipse GST (4G63T)

**Date**: 2026-02-05 (Session 10)
**Author**: Marcus (PM), compiled from 4 parallel research tasks
**Purpose**: Grounding document for all PRDs and user stories involving OBD-II data collection
**Vehicle**: 1998 Mitsubishi Eclipse GST, 2G DSM, 4G63 turbo, stock ECU with modified EPROM
**Adapter**: OBDLink LX Bluetooth (FW 5.6.19, MAC 00:04:3E:85:0D:FB)

---

## Table of Contents

1. [Protocol & Throughput Constraints](#1-protocol--throughput-constraints)
2. [Supported PIDs](#2-supported-pids)
3. [Recommended Core PID Set](#3-recommended-core-pid-set-phase-1)
4. [Expanded PID Set](#4-expanded-pid-set-phase-2)
5. [Tiered Polling Strategy](#5-tiered-polling-strategy)
6. [Safe Operating Ranges](#6-safe-operating-ranges)
7. [Known Limitations & Quirks](#7-known-limitations--quirks)
8. [Mobile App Recommendations](#8-mobile-app-recommendations)
9. [Hardware Troubleshooting](#9-hardware-troubleshooting)
10. [Future: ECMLink V3 Upgrade Path](#10-future-ecmlink-v3-upgrade-path)
11. [Design Implications for Our System](#11-design-implications-for-our-system)
12. [CIO Context](#12-cio-context)
13. [Sources](#13-sources)

---

## 1. Protocol & Throughput Constraints

### Protocol: ISO 9141-2 (K-Line)

The 1998 Eclipse GST communicates via **ISO 9141-2**, one of the slowest OBD-II protocols. Modern cars use CAN bus at 250-500 kbps; this car runs at **10,400 bps** -- roughly 25-50x slower.

| Metric | Value |
|--------|-------|
| Protocol | ISO 9141-2 (K-Line, Pin 7) |
| Baud rate | 10,400 bps |
| Per-PID round trip (real-world) | 120-200 ms |
| Max PIDs/second (wired) | ~6-8 |
| Max PIDs/second (Bluetooth) | ~4-5 |
| Bluetooth SPP added latency | 10-30 ms per round trip |

### Key Protocol Timing

| Parameter | Value |
|-----------|-------|
| Inter-byte delay (P1) | 0-20 ms |
| ECU response delay (P2) | 25-50 ms |
| Inter-message delay (P3) | 55+ ms |
| OBD-II minimum message gap | 100 ms |

### PIDs vs. Per-PID Update Rate (The Critical Tradeoff)

ISO 9141-2 is strictly **sequential** -- no multi-PID requests. Each PID requires a full request-response cycle.

| PIDs Polled | Per-PID Update Rate | Total Cycle Time |
|-------------|---------------------|------------------|
| 1 | ~5-6 Hz | ~170-200 ms |
| 3 | ~1.7-2 Hz | ~500-600 ms |
| 5 | ~1-1.2 Hz | ~850-1000 ms |
| 6 | ~0.8-1 Hz | ~1000-1200 ms |
| 10 | ~0.5-0.6 Hz | ~1700-2000 ms |
| 15 | ~0.3-0.4 Hz | ~2500-3000 ms |

**The OBDLink LX is NOT the bottleneck** -- the car's ECU and K-Line protocol are. The adapter supports 62+ PIDs/sec on CAN vehicles.

### Session 23 Empirical Measurement (2026-04-19)

First live-car data capture. Measurements from `chi-eclipse-01` SQLite + `chi-srv-01` MariaDB confirm the theoretical numbers above.

| Metric | Measured | Theoretical Match |
|--------|----------|-------------------|
| PIDs polled concurrently | 11 | — |
| Total throughput | 6.4 rows/sec | ✅ within predicted 6-8 PIDs/sec (wired-equivalent) |
| Per-PID update rate | ~0.58 Hz | ✅ within predicted 0.5-0.6 Hz for 10 PIDs |
| Rows captured | 149 in ~23 seconds of connected time | — |

**Regression fixture (US-197)**: The 149 rows are preserved at `data/regression/pi-inputs/eclipse_idle.db` with `specs/grounded-knowledge.md` as the narrative source-of-truth. Regenerate via `scripts/export_regression_fixture.sh` after future drills. The fixture carries `data_source='real'` + `drive_id=NULL` (pre-US-200 rows are not retroactively tagged per US-200 Invariant #4).

**Implication for Sprint 14+ polling design**: Adding the 6 PIDs from US-199 (fuel system status, runtime, MIL/DTC-count, barometric, ELM_VOLTAGE, optional post-cat O2) brings concurrent PID count to ~17. Expected per-PID rate drops to ~0.3-0.4 Hz for non-tiered polling. **Tiered polling strategy (Section 5) becomes essential** — do not simply add all new PIDs to the same fast-poll tier. Recommend: fuel system status on fast-poll (needed for trim interpretation), runtime on moderate-poll, barometric on slow-poll (changes slowly), MIL bit on moderate-poll, ELM_VOLTAGE on moderate-poll (adapter-local, not on K-line anyway).

---

## 2. Supported PIDs

### Tier 1: High-Confidence Supported

These correspond to sensors physically wired to the ECU and required by OBD-II regulation. **Session 23 empirical column** shows live-car confirmation status as of 2026-04-19.

| PID (Hex) | Name | Units | Stock Range | Tuning Use | Session 23 |
|-----------|------|-------|-------------|------------|------------|
| 0x00 | Supported PIDs [01-20] | Bitmap | N/A | Query first to confirm support | probed at connection open (US-199) |
| 0x01 | Monitor status since DTC cleared | Bitmap | MIL bit + DTC count | Emissions readiness; live CEL detection | ✅ polled (US-199 — exposes MIL_ON + DTC_COUNT) |
| 0x03 | Fuel system status | Enum | Open/Closed loop | Detects WOT open-loop transition; gates STFT/LTFT interpretation | ✅ polled (US-199 — exposes FUEL_SYSTEM_STATUS) |
| 0x04 | Calculated engine load | % | Idle: 15-25%, Cruise: 30-50%, WOT: 70-95% | **High** | ✅ supported |
| 0x05 | Engine coolant temperature | deg C | Normal: 85-95C (185-205F) | **High** -- engine protection | ✅ supported |
| 0x06 | Short-term fuel trim (Bank 1) | % | Normal: -5% to +5% | **High** -- lean/rich indicator | ✅ supported |
| 0x07 | Long-term fuel trim (Bank 1) | % | Normal: -5% to +5% | **High** -- persistent drift | ✅ supported |
| 0x0A | Fuel rail pressure | kPa | N/A | Fuel system health | ❌ **confirmed unsupported** |
| 0x0B | Intake manifold pressure | kPa | Idle: 25-35, Atmo: 101, 7psi: ~150 | **See caveat below** | ❌ **confirmed unsupported** (stronger than prior "may report MDP" — PID does not respond at all) |
| 0x0C | Engine RPM | rpm | Idle: 700-800, Redline: 7000 | **High** -- baseline | ✅ supported |
| 0x0D | Vehicle speed | km/h | 0-240 | Context/gear detection | ✅ supported |
| 0x0E | Timing advance | deg BTDC | Idle: 10-15, Boost: 8-16 | **High** -- knock indicator | ✅ supported |
| 0x0F | Intake air temperature | deg C | Normal: 20-40C | Heat soak detection | ✅ supported |
| 0x10 | MAF air flow rate | g/s | Idle: ~3, WOT: up to ~150 | **High** -- MAF saturation | ✅ supported |
| 0x11 | Throttle position | % | Idle: 0-2%, WOT: 95-100% | **High** -- driver input | ✅ supported |
| 0x13 | O2 sensors present | Bitmap | Bank 1: 2 sensors | Configuration info | not explicitly probed |
| 0x14 | O2 Sensor B1S1 (upstream) | Voltage | 0.0-1.0V, switches around 0.45V | Narrowband only | ✅ supported |

### Tier 2: Likely Supported (Lower Confidence)

| PID (Hex) | Name | Units | Notes | Session 23 |
|-----------|------|-------|-------|------------|
| 0x15 | O2 Sensor B1S2 (downstream) | Voltage | Post-catalyst monitoring | ✅ polled conditionally (US-199) — probe-gated, silent-skip if unsupported |
| 0x1F | Run time since engine start | seconds | Warmup tracking; anchors rows to drive time | ✅ polled (US-199 — exposes RUNTIME_SEC) |
| 0x20 | Supported PIDs [21-40] | Bitmap | Check for extended PIDs | probed implicitly by python-obd support-scan |
| 0x33 | Barometric pressure | kPa | From baro sensor in air filter housing | ✅ polled (US-199 — exposes BAROMETRIC_KPA) |
| 0x42 | Control module voltage | V | 13.5-14.5V running | ❌ **confirmed unsupported** — use ELM_VOLTAGE (see note below) |

### Critical Caveat: PID 0x0B (Manifold Pressure)

The 2G 4G63T does **NOT** have a traditional MAP sensor for fuel metering. It uses:
- **MAF sensor** for primary fuel calculation
- **MDP sensor** (Manifold Differential Pressure) for EGR monitoring only
- **Barometric pressure sensor** in the air filter housing

**Session 23 empirical result (2026-04-19): PID 0x0B does not respond on this ECU.** Prior research documented "PID 0x0B may report MDP data, not reliable for boost." Live-car testing is stronger: the ECU does not answer this PID at all. For any boost measurement on this car, aftermarket MAP sensor (GM 3-bar) or ECMLink MAP input is required — both are Phase 2.

### Critical Caveat: PID 0x42 (Control Module Voltage) — Unsupported

**Session 23 empirical result: PID 0x42 does not respond on this ECU.** Battery voltage for the primary display, alert logic, and all voltage-related tests must use the **ELM327 adapter-level query** instead:

- python-obd: `obd.commands.ELM_VOLTAGE`
- ELM327 AT command: `ATRV`
- What it measures: voltage at OBD-II port pin 16 (effectively battery voltage)
- Not an OBD-II Mode 01 PID — adapter-local, not subject to K-line bandwidth constraints
- Resolution ~0.1V; responds instantly

This is the battery voltage source for the Pi collector going forward (Sprint 14 US-199 adds it to the poll set).

### Sprint 14 US-199: Spool Data v2 Story 1 — 6 New PIDs

**Shipped 2026-04-19.** Six new parameter_names join the Pi poll set per Spool's Data v2 priority list (`offices/pm/inbox/2026-04-19-from-spool-data-collection-gaps.md`). Each new parameter has a dedicated decoder in `src/pi/obdii/decoders.py` and is registered in `PARAMETER_DECODERS`.

| parameter_name | PID | Source | Tier / Rate | Decoder Output |
|----------------|-----|--------|-------------|----------------|
| FUEL_SYSTEM_STATUS | 0x03 | Mode 01 | Tier 1 (~1 Hz) | enum code 1..5; unit column holds text label (OL/CL/OL-drive/OL-fault/CL-fault) |
| MIL_ON | 0x01 | Mode 01 | Tier 2 (~0.3 Hz) | bool as 0.0/1.0; unit = 'ON'/'OFF' |
| DTC_COUNT | 0x01 | Mode 01 | Tier 2 (~0.3 Hz) | integer 0-127 as float; unit = 'count' |
| O2_BANK1_SENSOR2_V | 0x15 | Mode 01 | Tier 2 (~0.3 Hz) | voltage float; unit = 'V'. **Probe-gated** — silently skipped if ECU bitmap excludes 0x15. STFT field of response tuple ignored this sprint (future Spool call). |
| RUNTIME_SEC | 0x1F | Mode 01 | Tier 3 (~0.1 Hz) | seconds float; unit = 's'. uint16 rollover at ~18hr (non-issue). |
| BATTERY_V | (ATRV) | ELM327 adapter | Tier 3 (~0.1 Hz) | volts float; unit = 'V'. **Not a Mode 01 PID** — bypasses the supported-PID probe. This is the voltage source on 2G because PID 0x42 is confirmed unsupported. |
| BAROMETRIC_KPA | 0x33 | Mode 01 | Tier 4 (~0.03 Hz) | kPa float; unit = 'kPa'. |

**Supported-PID probe** runs once at connection-open time via `src/pi/obdii/pid_probe.py` and consults python-obd's auto-probed `supported_commands`. The result caches on `ObdConnection.supportedPids` and gates `ObdDataLogger.queryParameter` so unsupported Mode 01 PIDs raise `ParameterNotSupportedError` *before* dispatching a K-line query. Adapter-level commands (pidCode=None) bypass the gate. Probe failures fall back to "always supported" — null-response silent-skip remains the downstream safety net.

**Theoretical poll-rate math (post-US-199):** sum over tiers of `len(tier.parameters) / tier.cycleInterval` = 6/1 + 5/3 + 5/10 + 3/30 = **8.27 PIDs/sec theoretical at 1 Hz cycle cadence**. Session 23 measured 2.5 PIDs/sec actual with 11 PIDs scheduled at ~7.0/s theoretical (0.36x throttle ratio due to K-line latency). Post-US-199 expected actual: 8.27 × 0.36 ≈ **3.0 PIDs/sec** — marginally over the 2.5/s envelope but within K-line physical throttling and well within the story's documented tolerance. If a future drill measures actual throughput exceeding 4 PIDs/sec sustained, file a follow-up story to rebalance tiers (e.g., demote O2_BANK1_SENSOR2_V to tier 3).

**Battery-voltage thresholds** (normal/caution/danger) for BATTERY_V live at `pi.tieredThresholds.batteryVoltage` in `config.json` and match Spool Phase 1 spec (`offices/pm/inbox/2026-04-10-from-spool-system-tuning-specifications.md` §Battery Voltage): normal 13.5-14.5V running, danger <12.0V or >15.0V. See `specs/grounded-knowledge.md` §Battery Voltage via ELM_VOLTAGE for the source-of-truth table.

### Sprint 14 US-200 — Engine state thresholds (Spool Priority 3)

Spool-spec'd defaults for the `EngineStateMachine`:

| Threshold | Default | Source |
|-----------|---------|--------|
| `crankingRpmThreshold` | 250 RPM | Spool priority 3 — RPM 0 → ≥ 250 triggers CRANKING (starter-motor + combustion-attempt regime for 4G63) |
| `runningRpmThreshold` | 500 RPM | Well above cranking, conservatively below warm idle (Session 23: 761-852 RPM) |
| `keyOffDurationSeconds` | 30s | Spool "reasonable start, tunable" — long enough to dodge stop-and-go false positives, short enough to detect park promptly |

`drive_id` is generated on CRANKING entry via the `drive_counter` singleton sequence (`src/pi/obdii/drive_id.py`) — NOT wall-clock ms (NTP-resync-safe). On KEY_OFF the drive_id is closed; next CRANKING mints a fresh one. See `specs/architecture.md` §5 Drive Lifecycle for full state machine + writer plumbing.

---

## 3. Recommended Core PID Set (Phase 1)

For the initial 5-6 PID monitoring set. Optimized for engine safety and maximum insight with minimum polling overhead.

| Priority | PID | Name | Why |
|----------|-----|------|-----|
| **1** | 0x06 | Short-Term Fuel Trim | Best lean/rich proxy without wideband. Large positive = lean danger. |
| **2** | 0x05 | Coolant Temperature | Prevents catastrophic damage. ECU retards timing >206F. Head gasket risk >220F. |
| **3** | 0x0C | Engine RPM | Essential context -- x-axis of every tuning table. |
| **4** | 0x0E | Timing Advance | Knock indicator. Low/negative values = ECU detecting knock and pulling timing. |
| **5** | 0x04 | Calculated Engine Load | How hard the engine is working. High load + high STFT = lean under boost = danger. |

### Optional 6th PID (choose based on priority):

| Option | PID | Name | When to Choose |
|--------|-----|------|---------------|
| A | 0x10 | MAF Air Flow | Suspect MAF issues or tracking airflow changes from mods |
| B | 0x07 | Long-Term Fuel Trim | Tracking persistent fuel correction trends |
| C | 0x0F | Intake Air Temperature | Testing intercooler efficiency or heat soak |

### Why This Set

- **"Is my AFR safe?"** -- STFT is the best proxy without a wideband sensor
- **"Did my tuning change help?"** -- RPM + Load + Timing + STFT together show engine response
- **"Detect out-of-normal conditions"** -- Coolant catches overheating, Timing catches knock, STFT catches lean
- **"Prevent engine damage"** -- The two 4G63T killers: running lean under boost (detonation) and overheating (head gasket). STFT + Coolant directly address both.

---

## 4. Expanded PID Set (Phase 2)

### Phase 2A: Enhanced Monitoring

| PID | Name | Purpose |
|-----|------|---------|
| 0x07 | Long-term fuel trim | Trend analysis; developing issues |
| 0x10 | MAF air flow rate | Airflow monitoring; MAF saturation |
| 0x0F | Intake air temperature | Intercooler efficiency; heat soak |
| 0x14 | O2 Sensor B1S1 | Upstream narrowband; lean detection at WOT |
| 0x11 | Throttle position | WOT detection; throttle tracking |
| 0x0B | Intake manifold pressure | Boost indication (with MDP caveats) |
| 0x03 | Fuel system status | Open/closed loop detection |

### Phase 2B: Diagnostic & Context

| PID | Name | Purpose |
|-----|------|---------|
| 0x01 | Monitor status | Readiness monitors |
| 0x0D | Vehicle speed | Gear detection context |
| 0x1F | Engine run time | Warmup tracking |
| 0x33 | Barometric pressure | Altitude compensation |
| 0x42 | Control module voltage | Electrical health |

---

## 5. Tiered Polling Strategy

The single biggest optimization available. Moves from flat 15-PID polling (~0.35 Hz per PID) to weighted round-robin (~1 Hz for core PIDs).

### Tier 1: Fast Poll (every cycle) -- ~1 Hz per PID

| PID | Name | Rationale |
|-----|------|-----------|
| RPM | Engine RPM | Fastest-changing core parameter |
| THROTTLE_POS | Throttle Position | Driver input correlation |
| INTAKE_PRESSURE | MAP / Boost | Critical for turbo monitoring |
| ENGINE_LOAD | Calculated Load | Key for fuel trim analysis |
| SPEED | Vehicle Speed | Drive cycle tracking |

### Tier 2: Moderate Poll (every 2nd-3rd cycle) -- ~0.3 Hz per PID

| PID | Name | Rationale |
|-----|------|-----------|
| SHORT_FUEL_TRIM_1 | STFT Bank 1 | Trend data; oscillates faster than we can capture |
| O2_B1S1 | O2 Sensor | Narrowband; trend/health analysis only |
| TIMING_ADVANCE | Ignition Timing | Knock/timing drift detection |
| MAF | Mass Air Flow | Correlates with load |

### Tier 3: Slow Poll (every 5th-10th cycle) -- ~0.1-0.2 Hz per PID

| PID | Name | Rationale |
|-----|------|-----------|
| COOLANT_TEMP | Engine Coolant | Changes over minutes; static when warm |
| INTAKE_TEMP | Intake Air Temp | Very slow thermal changes |
| LONG_FUEL_TRIM_1 | LTFT Bank 1 | Changes over minutes |
| BAROMETRIC_PRESSURE | Barometric | Nearly static; once per minute |

### Cycle Pattern (Weighted Round-Robin)

```
Cycle 1: [RPM] [TPS] [MAP] [LOAD] [SPEED]            -- Tier 1 only
Cycle 2: [RPM] [TPS] [MAP] [LOAD] [SPEED] [STFT]     -- Tier 1 + 1 Tier 2
Cycle 3: [RPM] [TPS] [MAP] [LOAD] [SPEED] [O2]       -- Tier 1 + 1 Tier 2
Cycle 4: [RPM] [TPS] [MAP] [LOAD] [SPEED] [TIMING]   -- Tier 1 + 1 Tier 2
Cycle 5: [RPM] [TPS] [MAP] [LOAD] [SPEED] [MAF]      -- Tier 1 + 1 Tier 2
... every 5th full cycle, insert one Tier 3 PID ...
```

Result: Tier 1 at ~1 Hz, Tier 2 at ~0.2-0.33 Hz, Tier 3 at ~0.1-0.2 Hz.

---

## 6. Safe Operating Ranges

### Engine Temperatures

| Parameter | Normal | Caution | Danger |
|-----------|--------|---------|--------|
| Coolant temp | 185-205F (85-96C) | 205-215F | >220F (104C) -- head gasket risk |
| Intake air temp | 20-40C | 40-60C | >65C -- significant heat soak |
| Oil temp (street) | 180-220F | 220-250F | >260F -- oil life reduction |
| EGT | 930-1200F cruise | 1200-1600F | >1750F -- melting things |

### Boost & Fueling

| Parameter | Safe | Caution | Danger |
|-----------|------|---------|--------|
| Stock boost | ~12 psi | 13-14 psi (boost creep) | >15 psi without fuel upgrades |
| AFR at WOT (wideband) | 11.0-11.8:1 | 12.0-12.5:1 | >12.5:1 LEAN or <10.0:1 |
| STFT | -5% to +5% | +/-5-10% | >+/-15% |
| LTFT | -5% to +5% | +/-5-8% | >+/-10% |
| Fuel pressure (base) | 43.5 psi | -- | Low = injector starvation |

### Timing & Knock

| Parameter | Safe | Caution | Danger |
|-----------|------|---------|--------|
| Timing under boost | 10-16 deg BTDC | 5-10 deg | <5 deg or negative (heavy retard) |
| Knock count (ECMLink) | 0 | 1-3 per pull | >5 per pull |
| Knock sum | 0-1 | 2-3 | >4 (~1 deg retard per 1.5 counts) |

### RPM & Electrical

| Parameter | Normal | Limit |
|-----------|--------|-------|
| Idle RPM | 700-800 | -- |
| Redline | 7,000 | 7,500 (rev limiter) |
| Battery voltage (running) | 13.5-14.5V | <12.0V or >15.0V |
| Oil pressure rule of thumb | ~10 psi per 1,000 RPM | Low at idle = concern |

### Key Community Rules

- **Richer AFR is always safer** -- err on the side of rich, it suppresses knock
- **Never tune until coolant >175F** -- ECU behavior differs during warmup
- **Stock fuel system maxes at 14-15 psi boost** -- do not exceed without upgrades
- **The stock boost gauge lies** -- it extrapolates from other sensors, not actual pressure
- **Fewer logged PIDs = faster sample rate** -- start minimal, expand when stable

---

## 7. Known Limitations & Quirks

### OBD-II Compliance Issues

1. **Partial OBD-II implementation**: Mitsubishi gave the GST the OBD-II port but the implementation was never fully connected to OBD-II specs. Expect fewer supported PIDs than modern cars.

2. **"OBDII loggers suck on 2G's"** -- direct community quote. 3-4 samples/second, no knock logging, many parameters not loggable via standard OBD-II.

3. **MAP sensor may report "unsupported"** -- PID 0x0B reads the MDP sensor (EGR monitoring), not a true MAP sensor. May be inaccurate or unavailable for boost measurement.

4. **Narrowband O2 only** -- stock sensor only tells rich/lean relative to stoich (switches around 0.45V). Cannot provide actual AFR numbers. Wideband upgrade is essential for tuning.

5. **No knock data via OBD-II** -- the single most critical safety parameter for a turbo engine is not available through standard OBD-II.

### ECU-Specific Quirks

6. **95 ECU swap = no OBD-II**: If a 1995 ECU has been swapped into the car, OBD-II will not work at all.

7. **ECMLink comms lock**: ECMLink has a "Lock comms in ECMLink mode" checkbox (Misc tab) that is checked by default. When active, no OBD-II scanner can communicate. Must uncheck, save, and disconnect laptop first. Re-enables itself each reconnect.

8. **98-99 ECU is flashable** (the "black box" ECU), unlike 95-96 which uses EPROM chips.

### Hardware Quirks

9. **OBD-II port power issues are common on 2G DSMs**: Corrosion in engine compartment fuse box, bent/dirty pins, deteriorated wiring. Door Lock fuse (driver's kick panel) powers Pin 16.

10. **Missing L-Line**: Some 2G DSMs lack Pin 15, causing initialization failures with certain adapters. The OBDLink LX (STN chipset) handles this better than ELM323-based adapters.

11. **Battery relocation weakens grounds**: If battery was moved to trunk, engine bay grounding suffers. A dedicated 4-gauge ground wire resolves this.

12. **IAT sensor is inside the MAF**: Pins 1 (5V), 5 (ground), 6 (signal). A constant -74F reading means MAF/wiring failure.

---

## 8. Mobile App Recommendations

### Critical Finding: BlueDriver Will NOT Work

BlueDriver is a closed ecosystem -- the app only works with BlueDriver's own hardware. It will not pair with the OBDLink LX. This was likely one reason the CIO couldn't collect data.

### OBDLink LX Compatibility

The OBDLink LX uses **Classic Bluetooth 3.0** -- Android and Windows only. **No iOS support** (Apple requires BLE or WiFi).

### App Comparison

| Feature | OBDLink App | Torque Pro | Car Scanner | OBD Fusion |
|---------|-------------|------------|-------------|------------|
| Works with OBDLink LX | Yes | **Yes** | Yes | Yes |
| Platform | Android | Android | Android/Win | Android/Win |
| PID Discovery | Yes | **Yes** | Yes | Yes |
| Custom PIDs | Limited | **Excellent** | Good | Good |
| CSV Export | Limited | **Yes** | Yes | Yes |
| Datalogging | Basic | **Excellent** | Good | Good |
| Price | Free | $5 | Free/$9 | $6-$10 |
| DSM Community Tested | Yes | **Yes** | Unknown | Unknown |

### Primary Recommendation: Torque Pro ($5, Android)

- Confirmed working on 2G DSMs by DSMTuners community
- Best CSV export (directly useful as sample data for Pi system)
- Boost calculation from MAP sensor
- Custom PID files via `.torque/extendedpids/`
- Mitsubishi LT Plugin available for manufacturer-specific PIDs

### For Development Without the Car: ELM327-emulator (Python)

`pip install ELM327-emulator` -- runs on the Pi, creates a virtual serial port, configurable PID responses. Enables end-to-end testing without the car.

---

## 9. Hardware Troubleshooting

### Before Trying Any App, Verify Hardware

1. **Check 12V on OBD-II Pin 16** with a multimeter (key off -- unswitched power from battery)
2. **Check continuity on Pin 7** (pink wire) from OBD-II port to ECU Pin 62
3. **Check ground pins 4 and 5**
4. **Inspect fuse box** for corrosion (10A fuses #10 and #11 in yellow fuse holder)
5. **Engine must be RUNNING** (not just ignition on) for ISO 9141-2 initialization
6. In OBDLink app: Settings > Preferences > Communications > set protocol to "Automatic"
7. If auto-detect fails, manually force **ISO 9141-2**

### OBD-II Port Wiring Reference (96-99 2G Turbo)

| OBD-II Pin | Wire Color | Connects To | Function |
|-----------|------------|-------------|----------|
| 1 | Yellow | ECU Pin 56 | Diagnostic Mode |
| 4 | Black | Ground #5 | Chassis Ground |
| 5 | Black/White | Ground #5 | Signal Ground |
| 7 | Pink | ECU Pin 62 | K-Line (ISO 9141-2 data) |
| 14 | Yellow/White | ECU Pin 86 | Vehicle Speed Sensor |
| 16 | Red/Black | ECU Pin 80 | +12V Unswitched (Battery) |

---

## 10. Future: ECMLink V3 Upgrade Path

When ECMLink V3 is installed, OBD-II becomes secondary. ECMLink communicates directly with the ECU via MUT protocol at **15,625 baud** (~10x faster effective sample rate).

### Parameters Only Available via ECMLink (Not OBD-II)

| Parameter | Why It Matters |
|-----------|---------------|
| **Knock Sum / Knock Count** | Direct knock detection -- the #1 safety metric |
| **Knock Learn** | How much ECU permanently pulled timing |
| **Wideband AFR** (with wideband input) | Actual air-fuel ratio |
| **Injector Duty Cycle** | Know when injectors max out |
| **Boost** (with aftermarket MAP) | Actual manifold pressure |
| **AirFlowPerRev** | Volumetric efficiency (stock idle: ~0.27) |
| **TPS Delta** | Rate of throttle change |
| **MAF Frequency (Raw)** | Overflow at ~2700 Hz = MAF limit |

### ECMLink Target Values

| Parameter | Target |
|-----------|--------|
| AirFlowPerRev (idle) | 0.27 +/-10% |
| AFR closed loop | 14.7:1 |
| AFR WOT (pump gas) | ~11.5:1 |
| Coolant for tuning | >179F |
| Fuel trims | +/-5% |
| Knock CEL threshold | 3 degrees recommended |
| TPS idle voltage | 0.63V |

### PiLink: Existing Product Validation

**PiLink** (found on DSMTuners) is a commercial Raspberry Pi-based datalogger for ECMLink ECUs. It auto-starts logging on ignition, saves on shutdown, and supports remote tuning via cellular. This validates our system concept and provides design patterns to learn from.

---

## 11. Design Implications for Our System

Based on all research, these are the actionable constraints for PRDs and user stories:

### Architecture Decisions

1. **Implement tiered polling** -- weighted round-robin, not flat polling. This is the single biggest performance improvement available.

2. **Design for sparse, slow data** -- 1 Hz per core PID at best. Do not design dashboards expecting smooth real-time updates. The OSOYOO display should show numerical values, not smooth gauges.

3. **Offline is the normal state** -- the Pi will be disconnected from WiFi most of the time. All data collection, storage, and alerting must work fully offline.

4. **Graceful degradation for missing PIDs** -- some PIDs may report "unsupported." The system must handle this at startup (query PID 0x00) and adapt.

5. **Alert thresholds from community data** -- use the safe operating ranges documented in Section 6, not arbitrary values.

6. **90-day retention on Pi, forever on server** -- auto-purge after confirmed sync to Chi-Srv-01.

7. **Easy connect/disconnect** -- the Pi setup should have a single power connector and quick-release mount.

8. **Boot on AUX power** -- system must handle frequent start/stop cycles without data corruption.

9. **OBD-II is Phase 1; ECMLink is Phase 2** -- design data models and APIs to accommodate both data sources.

10. **Wideband O2 is the recommended first aftermarket upgrade** -- the stock narrowband provides almost no useful AFR data under boost.

### What OBD-II CAN Do (Our Scope)

- Coolant temp monitoring (most reliable, clear thresholds)
- RPM tracking (~1 Hz with core PID set)
- Fuel trim trend analysis (STFT/LTFT)
- Timing advance monitoring (knock indicator proxy)
- Engine load tracking
- Basic health monitoring and alerting
- Long-term trend analysis across drives

### What OBD-II CANNOT Do (Out of Scope Until ECMLink)

- Knock count/knock sum (the #1 safety metric)
- Actual AFR (needs wideband sensor)
- Fast datalogging (MUT protocol is 10x faster)
- Reliable boost pressure (MDP sensor limitation)
- Injector duty cycle, pulse width
- Real-time gauge-quality display refresh

---

## 12. CIO Context

Captured from CIO interview (Session 10):

| Fact | Detail |
|------|--------|
| Usage | Weekend summer project car, city driving, no WOT/dyno/autocross |
| Tuning experience | New to tuning, learning |
| Initial PIDs | 5-6 core set, expand later |
| Report format | Human-readable text first, then ECMLink-compatible CSV/JSON |
| Comparison style | Baseline-mandatory, trend-oriented ("getting better?") |
| Alert philosophy | Out-of-normal range, engine damage prevention |
| Pi location | Glovebox or trunk, display on dash (low profile) |
| Power | Battery > fuse > UPS (Geekworm X1209) > Pi, boots on AUX |
| WiFi | Offline is NORMAL. Sync only when on DeathStarWiFi. Never error on no network. |
| Sync | Auto-sync when home WiFi detected |
| Retention | 90 days on Pi, forever on server |
| Multi-vehicle | Possible future use on other vehicles or shared with friends |
| OBDLink LX experience | Tried OBDLink app and BlueDriver app, couldn't collect data |
| BlueDriver | INCOMPATIBLE with OBDLink LX (closed ecosystem) |

---

## 13. Sources

### Protocol & Throughput
- [OBDLink LX Product Page](https://www.obdlink.com/products/obdlink-lx/)
- [OBD Solutions - STN2120 Chip](https://www.obdsol.com/solutions/chips/stn2120/)
- [Circuit Crush - How OBD-II Works Part 2](https://circuitcrush.com/how-obd-ii-works-part-2/)
- [OBD Clearinghouse - K-line Communication](https://www.obdclearinghouse.com/Files/viewFile?fileID=1380)
- [M0AGX - Reading OBD2 without ELM327, K-Line](https://m0agx.eu/reading-obd2-data-without-elm327-part-2-k-line.html)

### 2G DSM Community
- [DSMtuners - Diagnostic scan on 2G](https://www.dsmtuners.com/threads/diagnostic-scan-on-2g-merged-8-8-obd-ii-obdii-obd2-obd-2-port-location-where.278771/)
- [DSMtuners - OBD2 Digital Dash with ECMLink](https://www.dsmtuners.com/threads/obd2-digital-dash-with-ecmlink.529966/)
- [DSMtuners - Torque app for Android OBD2](https://www.dsmtuners.com/threads/torque-app-for-android-obd2.426799/)
- [DSMtuners - OBDII Port Pinouts](https://www.dsmtuners.com/threads/obdii-port-pinouts.122243/)
- [DSMtuners - 2G DSM Wiring Schematics](https://www.dsmtuners.com/threads/2g-dsm-95-96-97-99-wiring-schematics-ecu-pinouts-diagrams-tcu-diagrams-ect.528552/)
- [DSMtuners - EvoScan Basics](https://www.dsmtuners.com/threads/evoscan-basics.354307/)
- [DSMtuners - PiLink for ECMLink Owners](https://www.dsmtuners.com/threads/new-product-launch-pilink-for-ecmlink-owners.527993/)
- [DSMtuners - List of Values to Log](https://www.dsmtuners.com/threads/list-of-values-to-log.444831/)
- [DSMtuners - MHIScan Free DataLogger](https://www.dsmtuners.com/threads/mhiscan-new-free-datalogger-for-dsms.326872/)

### Safe Operating Ranges
- [DSMtuners - Ideal Operating Temperature](https://www.dsmtuners.com/threads/ideal-operating-temperature-merged-9-7.193348/)
- [DSMtuners - Safe Knock Count 2G](https://www.dsmtuners.com/threads/safe-knock-count-2g-logging-w-evoscan.361402/)
- [DSMtuners - Stock Boost and Boost Limit](https://www.dsmtuners.com/threads/2g-4g63-stock-boost-and-boost-limit.312197/)
- [DSMtuners - Safe Oil Temp](https://www.dsmtuners.com/threads/safe-oil-temp.269313/)
- [DSMtuners - EGT Temperatures](https://www.dsmtuners.com/threads/egt-temperatures.477439/)
- [DSMtuners - Normal Oil Pressure](https://www.dsmtuners.com/threads/what-is-normal-oil-pressure.437587/)
- [DSMtuners - Stock Fuel Pressure](https://www.dsmtuners.com/threads/stock-fuel-pressure-on-a-2g-why-afpr.198174/)

### ECMLink & Tuning
- [ECMTuning Wiki - DSMLink Loggable Params](https://www.ecmtuning.com/wiki/dsmlinkloggableparams)
- [ECMTuning Wiki - GM 3-Bar MAP Install](https://www.ecmtuning.com/wiki/gm3barinstall)
- [ECMTuning Wiki - ECMLink in 98/99 DSM](https://www.ecmtuning.com/wiki/use_ecmlink_in_98_99_dsm)

### Mobile Apps
- [OBDLink Compatible Apps](https://www.obdlink.com/compatible-apps/)
- [BlueDriver Vehicle Compatibility](https://us.bluedriver.com/pages/bluedriver-vehicle-compatibility)
- [Torque Wiki - Bluetooth Adapters](https://wiki.torque-bhp.com/view/Bluetooth_Adapters)
- [Torque Wiki - PIDs](https://wiki.torque-bhp.com/view/PIDs)
- [Car Scanner - Compatibility](https://www.carscanner.info/compatibility/)
- [OBD Fusion - OBDSoftware.net](https://www.obdsoftware.net/software/obdfusion)

### Development Tools
- [ELM327-emulator on GitHub](https://github.com/Ircama/ELM327-emulator)
- [econpy/torque on GitHub](https://github.com/econpy/torque) (Torque Pro data pipeline)
- [python-OBD Command Tables](https://python-obd.readthedocs.io/en/latest/Command%20Tables/)
- [OBD-II PIDs - Wikipedia](https://en.wikipedia.org/wiki/OBD-II_PIDs)
- [CSS Electronics - OBD2 PID Overview](https://www.csselectronics.com/pages/obd2-pid-table-on-board-diagnostics-j1979)
