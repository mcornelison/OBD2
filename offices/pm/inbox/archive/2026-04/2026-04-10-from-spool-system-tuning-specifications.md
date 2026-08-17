# System Tuning Specifications — From Spool to Marcus

**Date**: 2026-04-10
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important
**Subject**: Complete tuning specifications for the Eclipse OBD-II monitoring system — PIDs, thresholds, display requirements, analysis logic, and roadmap

---

## Context

The CIO has shared the full vision for the project. I've reviewed what's been built (144 modules, 12 database tables, simulator, display, hardware integration — impressive work). Now I need to give you the tuning brain that drives the system's intelligence.

**This document contains:**
1. Data collection specifications (what to collect, how often, why)
2. Alert thresholds with exact numbers and rationale
3. Display specifications (what the driver sees)
4. Server analysis specifications (what Chi-Srv-01 looks for)
5. Numerical examples with inputs AND outputs (for developer accuracy)
6. Tuning roadmap (phased by vehicle modification state)

**What this document does NOT contain:** Software architecture, database schemas, API designs, or code. That's your team's domain. I'm giving you the domain knowledge. You turn it into stories.

---

## 1. Data Collection Specifications

### 1.1 Phase 1: OBD-II Only (Current State — Stock ECU)

The car currently has a stock ECU with modified EPROM. OBD-II over ISO 9141-2 via OBDLink LX Bluetooth. Maximum ~5 PIDs/second.

#### Core PID Set (5 PIDs, ~1 Hz each)

| PID | Name | Unit | Raw Range | Why It's Core |
|-----|------|------|-----------|---------------|
| 0x05 | Coolant Temperature | F | -40 to 419F | Engine protection. #1 priority. Head gasket fails above 220F. |
| 0x0C | Engine RPM | RPM | 0-16,383 | Context for every other reading. Defines engine state. |
| 0x04 | Calculated Engine Load | % | 0-100% | Workload context. High load + high temp = danger. |
| 0x0E | Timing Advance | degrees BTDC | -64 to 63.5 | Only knock indicator available without ECMLink. Dropping timing = possible detonation. |
| 0x06 | Short-Term Fuel Trim B1 | % | -100 to 99.2% | Best real-time lean/rich indicator. Large positive = engine is adding fuel = something is lean. |

#### Extended PID Set (cycle these in at lower frequency)

| PID | Name | Unit | Polling Rate | Why |
|-----|------|------|-------------|-----|
| 0x07 | Long-Term Fuel Trim B1 | % | Every 10 cycles (~10 sec) | Trend indicator. LTFT drifting positive over weeks = developing problem. |
| 0x0F | Intake Air Temperature | F | Every 10 cycles | Charge density context. High IAT = less power, more knock risk. |
| 0x11 | Throttle Position | % | Every 3 cycles (~3 sec) | Load context. Distinguishes idle vs cruise vs WOT. |
| 0x0D | Vehicle Speed | mph | Every 3 cycles | Context. Stationary vs moving. Gear estimation. |
| 0x42 | Control Module Voltage | V | Every 30 cycles (~30 sec) | Battery/charging health. Drop below 13.5V = alternator issue. |
| 0x14 | O2 Sensor B1S1 | V | Every 5 cycles | Narrowband O2. Should oscillate 0.1-0.9V. Stuck = dead sensor. |
| 0x0B | Manifold Pressure (MDP) | kPa | Every 5 cycles | **CAUTION: This is MDP, not true MAP on this car.** Use for relative reference only, NOT boost measurement. |

#### Polling Strategy

The system already has a tiered polling concept (I saw it in the OBD research doc — good work). Here's the tuning-driven priority:

**Tier 1 — Every cycle (1 Hz):** Coolant, RPM, Load, Timing, STFT
- These are the "is the engine alive and happy" parameters
- If any of these go bad, you need to know NOW, not in 10 seconds

**Tier 2 — Every 3 cycles (~0.3 Hz):** TPS, Speed
- Context parameters. Important but not safety-critical at this refresh rate.

**Tier 3 — Every 10 cycles (~0.1 Hz):** LTFT, IAT, O2 voltage
- Slow-moving parameters. LTFT updates slowly in the ECU anyway. IAT changes over minutes, not seconds.

**Tier 4 — Every 30 cycles (~0.03 Hz):** Battery voltage, MDP
- Near-static parameters. Battery voltage doesn't change second-to-second.

### 1.2 Phase 2: ECMLink V3 + OBD-II (After ECMLink Install)

ECMLink provides a serial data stream at 10-50 Hz with 50+ parameters. This is a completely different data volume. The PM and architect need to plan for this NOW even if it ships later.

#### ECMLink Priority Parameters

| Parameter | Unit | Sample Rate | Why It Matters |
|-----------|------|------------|----------------|
| **Wideband AFR** | ratio (e.g., 11.5:1) | 20 Hz | THE safety metric. Real air-fuel ratio. Non-negotiable. |
| **Knock Count** | count | 20 Hz | Detonation events. ANY knock under boost = immediate concern. |
| **Knock Sum** | cumulative | 20 Hz | Total knock energy. Persistent high knock sum = tune problem. |
| **Boost (MAP)** | psi | 20 Hz | Actual manifold pressure. Verify boost target vs actual. |
| **Injector Duty Cycle** | % | 10 Hz | Fuel system headroom. >85% = running out of injector. |
| **Timing Advance** | degrees BTDC | 20 Hz | ECU-commanded timing. Compare with knock events. |
| **RPM** | RPM | 20 Hz | Context for everything. |
| **TPS** | % | 20 Hz | Throttle position. Defines load state. |
| **Coolant Temp** | F | 5 Hz | Same as OBD-II but higher resolution. |
| **IAT** | F | 5 Hz | Intake air temp. Heat soak detection. |
| **Ethanol Content** | % | 1 Hz | From flex fuel sensor. What's actually in the tank. |
| **Target AFR** | ratio | 10 Hz | What the ECU is TRYING to hit. Compare with actual AFR. |
| **STFT** | % | 10 Hz | Short-term fuel correction. |
| **LTFT** | % | 1 Hz | Long-term fuel correction. Trend indicator. |
| **Barometric Pressure** | kPa | 0.5 Hz | Altitude/weather correction for analysis. |

#### Data Volume Estimate (For Architect)
- Phase 1 (OBD-II): ~5 readings/sec x 3600 sec/hr = ~18,000 rows per hour of driving
- Phase 2 (ECMLink): ~15 params x 10 Hz avg = ~150 readings/sec = ~540,000 rows per hour
- Typical summer weekend drive: 1-3 hours
- Seasonal estimate: ~20 drives x 2 hrs avg = ~40 hours = ~21.6 million rows/season on ECMLink
- Storage and retention strategy needs to account for this scale

---

## 2. Alert Thresholds

### 2.1 Phase 1 Thresholds (OBD-II, Stock ECU)

Every alert has three levels: **Normal** (green), **Caution** (yellow), **Danger** (red).

#### Coolant Temperature (PID 0x05)
| Level | Range | Driver Display | Action |
|-------|-------|---------------|--------|
| Normal | 180-210F | Green | None |
| Caution | 210-220F | Yellow, audible beep | Alert driver. Monitor closely. Reduce load. |
| Danger | >220F | Red, continuous alert | **PULL OVER. Engine off. Head gasket risk.** |
| Cold | <160F | Blue (info only) | Engine not at operating temp. Normal during warmup. |

**Rationale:** The 4G63 MLS head gasket loses clamp force when head bolts stretch from heat. Above 220F, the gasket weeps coolant into #4 cylinder. This is the most common 4G63 failure mode and it's entirely preventable with temperature monitoring.

#### Short-Term Fuel Trim (PID 0x06)
| Level | Range | Meaning | Action |
|-------|-------|---------|--------|
| Normal | -5% to +5% | ECU is making small corrections. Healthy. | None |
| Caution | -10% to -5% OR +5% to +10% | ECU is working harder to correct. Something may be developing. | Log for trend analysis. |
| Danger | < -15% OR > +15% | ECU is at correction limit. Active fueling problem. | Alert driver. **If positive (lean): could be vacuum leak, weak fuel pump, or clogged injector.** |

**Rationale:** STFT shows what the ECU is doing RIGHT NOW to correct fueling. Large positive STFT means the engine is running lean and the ECU is adding fuel to compensate. On a turbocharged engine, lean = detonation = dead engine.

#### Timing Advance (PID 0x0E)
| Level | Condition | Meaning | Action |
|-------|-----------|---------|--------|
| Normal | Matches baseline for RPM/load point | ECU is happy with combustion | None |
| Caution | Drops >5 degrees below baseline suddenly | Possible knock event, ECU pulling timing | Log it. If repeated at same RPM/load, flag for review. |
| Danger | Goes to 0 or negative under load | Active detonation. ECU is pulling all timing. | **Reduce throttle immediately. Do not continue at this load.** |

**Rationale:** Without ECMLink, timing advance is our only window into knock activity. The stock ECU will retard timing when the knock sensor detects detonation. A sudden drop in timing at a specific RPM/load point means the engine is knocking there.

#### Engine RPM (PID 0x0C)
| Level | Range | Action |
|-------|-------|--------|
| Low idle | <600 RPM | Idle too low. Possible vacuum leak or IAC issue. |
| Normal | 600-6500 RPM | None |
| Caution | 6501-7000 RPM | High RPM warning. Approaching factory redline. |
| Danger | >7000 RPM | **Over-rev. Factory redline exceeded. Valve float risk on stock springs.** |

*Note: Factory redline on 97-99 2G Eclipse GST is 7000 RPM (softer cam than 95-96). Corrected 2026-04-12.*

#### Battery Voltage (PID 0x42 or hardware UPS)
| Level | Range | Action |
|-------|-------|--------|
| Normal | 13.5-14.5V (engine running) | Charging system healthy |
| Caution | 12.5-13.5V OR 14.5-14.8V | Low = weak alternator. High = regulator starting to fail. |
| Danger | <12.0V OR >15.0V | **Low = charging failure, engine may stall. High = regulator failed, will cook battery and electronics.** |

#### Intake Air Temperature (PID 0x0F)
| Level | Range | Action |
|-------|-------|--------|
| Normal | Ambient to 130F | Normal for turbocharged intake |
| Caution | 131-160F | Heat soak building. Power loss. Increased knock risk. Stock side-mount intercooler heat soaks quickly under sustained boost. |
| Danger | >160F | **Significant knock risk at boost. Reduce load. Consider FMIC upgrade.** |
| Sensor Failure | Fixed at -40F (-40C) | IAT sensor is inside MAF housing on 2G. Constant -40 = sensor disconnected or failed. **This is a known 2G quirk.** |

*Note: Caution range extended to close previous 150-160F gap. Corrected 2026-04-12.*

### 2.2 Phase 2 Thresholds (ECMLink + Wideband)

**Alert Level Definitions (applies to both gas and E85 tables below)**:
- **Target**: The ideal sweet spot the tune aims for (narrower than Normal)
- **Normal**: Any value NOT in Caution or Danger range — no alert triggered
- **Caution**: Specific numerical bounds triggering yellow alert
- **Danger**: Specific numerical bounds triggering red alert

#### Wideband AFR — Pump Gas (93 Octane)
| Condition | Target AFR | Normal Range | Caution | Danger |
|-----------|-----------|--------------|---------|--------|
| Idle | 14.7:1 (stoich) | 14.0 to 15.5 | <14.0 or >15.5 | <13.0 or >16.0 |
| Cruise (part throttle) | 14.5-15.0:1 | 13.5 to 15.5 | <13.5 or >15.5 | <13.0 or >16.5 |
| WOT (full boost) | 11.0-11.5:1 | <11.5 (rich is safe) | 11.5-12.0:1 (slightly lean) | **>12.5:1 (LEAN UNDER BOOST — STOP)** |

#### Wideband AFR — E85
| Condition | Target AFR | Normal Range | Caution | Danger |
|-----------|-----------|--------------|---------|--------|
| Idle | 9.8:1 (E85 stoich) | 9.0 to 10.5 | <9.0 or >10.5 | <8.5 or >11.0 |
| Cruise | 9.8-10.2:1 | 9.0 to 10.5 | <9.0 or >10.5 | <8.5 or >11.5 |
| WOT (full boost) | 7.5-8.0:1 (Lambda 0.68-0.72) | <8.0 (rich is safe) | 8.0-8.5:1 | **>8.8:1 (LEAN UNDER BOOST — STOP)** |

*Note: Explicit Normal ranges added 2026-04-12 to remove ambiguity. Rich-of-target at WOT is intentionally safe — only lean AFR under boost is dangerous.*

**CRITICAL NOTE FOR DEVELOPER:** AFR thresholds MUST change based on ethanol content. The flex fuel sensor reports ethanol percentage. At 0% ethanol (pure gas), use gas thresholds. At 85% ethanol (E85), use E85 thresholds. In between, interpolate linearly. Example:
- 50% ethanol → WOT danger threshold = midpoint between 12.5:1 (gas) and 8.8:1 (E85) = ~10.65:1

#### Knock Count (ECMLink)
| Level | Value | Action |
|-------|-------|--------|
| Normal | 0 | No knock detected. Happy engine. |
| Caution | 1-3 per drive | Some knock. Log RPM, load, timing, AFR at each event. Review pattern. Could be false knock (heat shield rattle, belt chirp). |
| Danger | >3 per drive OR >1 per WOT pull | **Active detonation. Do not increase boost. Review tune at affected RPM/load cells.** |

#### Knock Sum (ECMLink)
| Level | Value | Action |
|-------|-------|--------|
| Normal | 0 | Perfect |
| Caution | 1-5 | Minor knock energy accumulated. Review. |
| Danger | >10 | **Significant knock energy. The tune needs attention at the affected operating points.** |

#### Injector Duty Cycle (ECMLink)
| Level | Range | Action |
|-------|-------|--------|
| Normal | 0-75% | Plenty of headroom |
| Caution | 75-85% | Getting warm. Injectors are working hard. |
| Danger | >85% | **Fuel system is at its limit. Lean condition imminent at higher RPM/load. Upgrade injectors before increasing boost.** |
| Static flow limit | >95% | **Injectors are maxed out. Engine WILL go lean above this point.** |

#### Boost Pressure (ECMLink + MAP sensor)
| Level | Stock Turbo | Action |
|-------|------------|--------|
| Normal | 10-14 psi | Target boost range |
| Caution | 14-15 psi | Approaching turbo efficiency limit |
| Danger | >15 psi | **Stock turbo is out of its efficiency range. Compressor surge risk. EGTs climbing.** |
| Boost spike | >3 psi over target momentarily | **Wastegate control issue. Investigate duty cycle or wastegate actuator.** |
| Boost creep | Boost exceeds target and won't come down | **Exhaust flow is overpowering the wastegate. Needs larger wastegate or exhaust restriction.** |

#### Ethanol Content (Flex Fuel Sensor)
| Level | Range | Action |
|-------|-------|--------|
| Expected E85 | 70-85% ethanol | Normal. "E85" at the pump varies widely. |
| Low ethanol | 50-70% | Pump may be selling diluted E85. Tune still safe (ECMLink interpolates). Log and inform driver. |
| Unexpected gas | <30% | Someone put gas in the tank. ECMLink will switch to gas map. Inform driver. |
| Unexpected high | >85% | Racing E85 or very fresh batch. Tune is fine. Note it. |

---

## 3. Display Specifications (3.5" Touchscreen)

### 3.1 What The Driver Needs To See

The display is 480x320 pixels, touch-capable. The driver is DRIVING. Information must be glanceable in under 1 second. No text paragraphs. No menus while moving.

#### Primary Driving Screen (Default)

**Layout concept** (the UI designer decides the actual layout, but these are the elements):

| Element | Size Priority | Update Rate | Format |
|---------|--------------|-------------|--------|
| **System Status Indicator** | Large, always visible | Real-time | Green circle / Yellow triangle / Red X |
| **Coolant Temperature** | Large | 1 Hz | "185F" — changes color at thresholds |
| **RPM** | Medium | 1 Hz | "2500" or bar graph |
| **Boost** (Phase 2 only) | Medium | Real-time | "12.3 psi" — only when MAP sensor installed |
| **AFR** (Phase 2 only) | Medium | Real-time | "11.5" — only when wideband installed |

**The status indicator is the most important element.** It's the "at a glance" answer to "is everything OK?"
- **Green**: All parameters within normal range. Drive happy.
- **Yellow**: One or more parameters in caution range. Tap for details.
- **Red**: One or more parameters in danger range. Audible alert. Tap for details.

#### Detail Pages (Tap to Access)

**Page 1: Thermal**
- Coolant temp (with trend arrow: stable, rising, falling)
- Intake air temp
- Time at temperature (how long has coolant been above 200F this drive?)

**Page 2: Fuel** (Phase 2)
- AFR actual vs target
- STFT / LTFT
- Injector duty cycle
- Ethanol content %

**Page 3: Knock** (Phase 2)
- Knock count this drive
- Knock sum this drive
- Last knock event: RPM, load, timing at moment of knock

**Page 4: Boost** (Phase 2)
- Current boost
- Target boost
- Peak boost this drive

**Page 5: System**
- Pi battery level
- WiFi status (connected/disconnected)
- Last sync time
- OBD connection status
- Drive duration

#### Touch Interactions
| Gesture | Action |
|---------|--------|
| Tap status indicator | Show details of current alert |
| Swipe left/right | Cycle between detail pages |
| Tap and hold (3 sec) on alert | Acknowledge / dismiss non-critical alert |
| **No interactions while vehicle speed > 0 that change system behavior** | Safety. Read-only while driving. |

### 3.2 Parked Mode (Engine Off, Pi On Battery)

When the engine is off and the Pi is running on battery:
- Show sync status: "Syncing to server... 45%" or "Sync complete"
- Show last drive summary: duration, distance, any alerts
- Show server advisory messages (if any downloaded from last sync)
- Show battery remaining: "Pi battery: 78% (~1.5 hrs)"

---

## 4. Server Analysis Specifications (Chi-Srv-01)

### 4.1 What The Server Does

When the Pi syncs a datalog to the server, the server should perform these analyses. Each analysis has a specific input, a specific output, and a specific "so what" that gets sent back to the Pi as an advisory.

### 4.2 Analysis Definitions

#### Analysis 1: Knock Correlation

**Purpose:** Identify WHERE the engine is knocking (at what RPM and load) so the tune can be adjusted.

**Input:**
- All knock events from the drive (timestamp, knock_count, knock_sum)
- Corresponding RPM, load, timing_advance, AFR, boost at each knock event timestamp

**Process:**
- Group knock events by RPM band (500 RPM bins: 2000-2500, 2500-3000, etc.) and load band (10% bins)
- For each bin with knock: record the average timing, average AFR, average boost at knock
- Compare with knock-free bins at similar RPM/load

**Output Example:**
```
KNOCK CORRELATION REPORT — Drive 2026-07-15 14:30
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total knock events: 4
Total knock sum: 7

Affected cells:
  RPM 4000-4500, Load 70-80%: 3 events, avg timing 14 deg, avg AFR 11.8:1, boost 13.5 psi
  RPM 5000-5500, Load 80-90%: 1 event, avg timing 12 deg, avg AFR 11.4:1, boost 14.2 psi

Advisory: Knock concentrated at 4000-4500 RPM under boost.
  AFR at 11.8:1 is slightly lean for pump gas WOT target (11.0-11.5).
  Recommendation: Add fuel in the 4000-4500 RPM / 70-80% load cell.
  Consider removing 1-2 degrees timing in this cell.
```

#### Analysis 2: AFR Drift Trending

**Purpose:** Detect gradual changes in air-fuel ratio that indicate a developing mechanical problem.

**Input:**
- LTFT values from the last N drives (minimum 5 drives for meaningful trend)
- Grouped by operating condition: idle, cruise, boost

**Process:**
- Calculate LTFT average per operating condition per drive
- Plot trend over drives
- Flag if trend is moving consistently in one direction (>0.5% per drive average)

**Output Example:**
```
AFR DRIFT REPORT — Last 10 Drives
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Idle LTFT trend: +0.3%/drive (5 drives ago: +1.2%, now: +2.7%)
Cruise LTFT trend: +0.1%/drive (stable, normal variation)
Boost LTFT trend: +0.8%/drive (5 drives ago: +0.5%, now: +4.5%)

Advisory: LTFT under boost is trending positive at +0.8% per drive.
  The engine is progressively needing more fuel at high load.
  Possible causes (in order of likelihood):
    1. Fuel pump weakening (check fuel pressure with gauge — should be 43.5 psi base)
    2. Injector starting to clog (one or more)
    3. Small boost/vacuum leak developing
  Action: Monitor next 3 drives. If LTFT exceeds +8%, investigate before next WOT pull.
```

#### Analysis 3: Injector Duty Cycle Tracking

**Purpose:** Track how close the fuel injectors are to their flow limit so the driver knows when to upgrade.

**Input:**
- Peak injector duty cycle per drive
- RPM and boost at peak IDC
- Ethanol content at time of peak

**Process:**
- Track peak IDC trend over drives
- Calculate headroom (100% - peak IDC)
- Project at what boost level IDC will exceed 85% (based on relationship between boost and IDC)

**Output Example:**
```
INJECTOR DUTY CYCLE REPORT — Last 10 Drives
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Current injectors: 550cc (ID550)
Current fuel: E85 (avg 74% ethanol)

Peak IDC this period: 82% at 5200 RPM, 14.5 psi boost
Average peak IDC: 78%
Trend: +1.2% per drive over last 5 drives

Headroom remaining: 18% (at current peak)
Projected IDC at 15 psi: ~87% ← CAUTION

Advisory: Injectors are running at 82% peak duty cycle on E85 at 14.5 psi.
  At current trend, you will exceed 85% within 3-4 drives if boost increases.
  If you plan to run 15 psi, upgrade to 660cc injectors first.
  At current boost (14.5 psi), you have adequate margin. No immediate action needed.
```

#### Analysis 4: Thermal Pattern Analysis

**Purpose:** Detect cooling system degradation before it causes a head gasket failure.

**Input:**
- Coolant temp time-series from each drive
- Ambient temperature (from IAT at drive start, before engine heat-soaks the intake)
- Driving pattern (idle time, cruise time, boost time from TPS/RPM data)

**Process:**
- Calculate peak coolant temp per drive
- Calculate average coolant temp during cruise
- Normalize for ambient temperature (a 95F day will run hotter than a 70F day)
- Track normalized trend over drives

**Output Example:**
```
THERMAL REPORT — Last 10 Drives
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ambient-adjusted peak coolant trend:
  Drive 1 (June 1, 72F ambient): Peak 198F → Normalized: +126F above ambient
  Drive 5 (June 15, 78F ambient): Peak 203F → Normalized: +125F above ambient
  Drive 10 (July 1, 85F ambient): Peak 214F → Normalized: +129F above ambient

Trend: +0.3F/drive normalized (within normal variation)

Advisory: Cooling system is performing consistently.
  No degradation detected. Peak temps are tracking ambient as expected.
```

**Abnormal Example:**
```
Trend: +1.5F/drive normalized (CONCERNING)

Advisory: Coolant temps are rising faster than ambient can explain.
  Normalized peak is +4.5F higher than baseline from 3 weeks ago.
  Possible causes:
    1. Coolant level low (check overflow tank)
    2. Thermostat starting to stick
    3. Radiator fan relay intermittent
    4. Radiator fins clogged (bugs, debris)
  Action: Check coolant level before next drive. If level is fine, monitor for 2 more drives.
  If trend continues, investigate thermostat and fan operation.
```

#### Analysis 5: E85 Content Tracking

**Purpose:** Track ethanol content consistency from local fuel stations so the driver knows what they're actually getting.

**Input:**
- Ethanol content readings from flex fuel sensor over each drive
- Stable readings only (ignore first 5 minutes after fillup as fuel mixes in tank)

**Process:**
- Record average ethanol % per fillup
- Track by station if driver provides station info (future feature)
- Alert on significant deviations

**Output Example:**
```
E85 CONTENT TRACKING — Last 5 Fill-ups
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fill 1 (June 5): 78% ethanol
Fill 2 (June 12): 74% ethanol
Fill 3 (June 20): 72% ethanol
Fill 4 (June 28): 81% ethanol
Fill 5 (July 5): 65% ethanol ← LOW

Average: 74% ethanol
Range: 65-81%

Advisory: Your local E85 is averaging 74% ethanol, which is normal
  (E85 at the pump typically ranges 51-83% depending on season and region).
  Fill 5 was notably low at 65%. ECMLink is compensating correctly via flex fuel
  interpolation. No action needed, but be aware that lower ethanol content means
  slightly less knock resistance and slightly less power (closer to gas tuning).
```

#### Analysis 6: Baseline Comparison

**Purpose:** Compare today's drive to the established baseline to catch anything that's changed.

**Input:**
- Current drive data (all parameters)
- Baseline established from first 5 "healthy" drives after initial tune

**Process:**
- For each parameter at each operating condition (idle, cruise, boost), compare current average with baseline average
- Flag deviations >2 standard deviations from baseline
- Correlate flagged parameters (e.g., high LTFT + high IAT = heat soak, not a real problem)

**Output Example:**
```
BASELINE COMPARISON — Drive 2026-07-15 vs Baseline
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Parameters within normal range: 12/14 ✓

Deviations:
  IAT at cruise: 142F (baseline: 118F) → +24F above baseline
    Context: Ambient temp today was 94F vs baseline avg of 72F.
    Adjusted deviation: +2F — within normal range. No concern.

  LTFT at idle: +4.8% (baseline: +1.2%) → +3.6% above baseline
    Context: No corresponding change in ambient or other parameters.
    This is a real deviation. LTFT is consistently higher at idle.
    Possible cause: Small vacuum leak developing.
    Action: Monitor for 2 more drives. If LTFT continues >+5% at idle, inspect vacuum lines.

Overall: No immediate concerns. One parameter to watch (idle LTFT).
```

---

## 5. Numerical Examples (Developer Reference)

These examples show exact input data and expected output so the developer can validate their implementation. All values are realistic for our vehicle.

### Example 1: Coolant Temperature Alert Escalation

**Scenario:** Normal drive, coolant temp rises through threshold zones.

**Input data (time series):**
```
timestamp,           coolant_temp_f, alert_level
2026-07-15 14:00:00, 165,           cold       (blue, info)
2026-07-15 14:05:00, 182,           normal     (green)
2026-07-15 14:10:00, 192,           normal     (green)
2026-07-15 14:30:00, 195,           normal     (green)
2026-07-15 14:45:00, 208,           normal     (green)
2026-07-15 14:50:00, 212,           caution    (yellow — alert triggered)
2026-07-15 14:52:00, 218,           caution    (yellow — still in caution)
2026-07-15 14:53:00, 221,           danger     (red — DANGER alert triggered)
```

**Expected system behavior:**
- At 14:00 — Display shows blue coolant indicator (cold engine, normal during warmup)
- At 14:05 — Display transitions to green (engine warming up, crossed 180F)
- At 14:50 — Display turns yellow, audible beep, alert logged: "Coolant temp 212F — monitor closely"
- At 14:53 — Display turns red, continuous audible alert, alert logged: "DANGER: Coolant temp 221F — pull over immediately, head gasket risk"

**Alert log entries:**
```
id, timestamp,            parameter,    value, severity, message
1,  2026-07-15 14:50:00, COOLANT_TEMP, 212,   CAUTION,  "Coolant temperature elevated (212F). Monitor closely."
2,  2026-07-15 14:53:00, COOLANT_TEMP, 221,   DANGER,   "DANGER: Coolant temperature critical (221F). Risk of head gasket failure. Reduce load immediately."
```

### Example 2: Fuel Trim Anomaly Detection

**Scenario:** LTFT gradually drifting positive over multiple drives, indicating developing lean condition.

**Input data (drive summaries):**
```
drive_date,  ltft_idle_avg, ltft_cruise_avg, ltft_boost_avg
2026-06-01,  +1.2%,         +0.8%,           +0.5%
2026-06-08,  +1.5%,         +1.0%,           +1.2%
2026-06-15,  +2.0%,         +1.1%,           +2.5%
2026-06-22,  +2.8%,         +1.3%,           +3.8%
2026-06-29,  +3.5%,         +1.5%,           +5.2%
2026-07-06,  +4.2%,         +1.4%,           +6.8%
```

**Expected analysis output:**
```
FUEL TRIM DRIFT DETECTED

Idle LTFT: +1.2% → +4.2% over 6 drives (trend: +0.6%/drive)
  Status: MONITOR — approaching investigation threshold (+5%)

Cruise LTFT: +0.8% → +1.4% over 6 drives (trend: +0.1%/drive)
  Status: NORMAL — within expected variation

Boost LTFT: +0.5% → +6.8% over 6 drives (trend: +1.3%/drive)
  Status: WARNING — significant lean trend under boost

Advisory: LTFT under boost is climbing at +1.3% per drive.
  The engine is progressively needing more fuel at high load.
  At current rate, LTFT will exceed +8% (danger threshold) in ~1-2 drives.
  
  Priority investigation (in order):
    1. Check fuel pressure with gauge (should be 43.5 psi base, 50+ psi at boost)
    2. Listen for boost leaks (pressurize intake, spray soapy water)
    3. Check injector balance (per-cylinder STFT in ECMLink if available)
```

### Example 3: Knock Event Analysis

**Scenario:** Two knock events during a spirited drive. Determine if they're real knock or false positives.

**Input data (knock events with context):**
```
Event 1:
  timestamp: 2026-07-15 15:23:45
  knock_count: 1
  knock_sum: 2
  rpm: 4200
  load: 75%
  timing_advance: 14 deg → dropped to 11 deg (ECU pulled 3 degrees)
  afr: 11.8:1
  boost: 13.5 psi
  tps: 85%
  iat: 128F
  coolant: 195F

Event 2:
  timestamp: 2026-07-15 15:24:02
  knock_count: 1
  knock_sum: 1
  rpm: 2100
  load: 25%
  timing_advance: 18 deg → 16 deg (ECU pulled 2 degrees)
  afr: 14.7:1
  boost: -15 inHg (vacuum, no boost)
  tps: 12%
  iat: 125F
  coolant: 195F
```

**Expected analysis:**
```
KNOCK EVENT ANALYSIS — Drive 2026-07-15

Event 1 (15:23:45) — LIKELY REAL KNOCK
  RPM: 4200, Load: 75%, Boost: 13.5 psi, TPS: 85%
  Engine was under significant boost load.
  AFR: 11.8:1 — slightly lean for WOT (target: 11.0-11.5:1)
  Timing pulled: 3 degrees (significant ECU response)
  Assessment: High load + slightly lean AFR = plausible detonation.
  Action: Add fuel at 4000-4500 RPM / 70-80% load in ECMLink fuel table.
           Consider removing 1 degree timing at this cell.

Event 2 (15:24:02) — LIKELY FALSE KNOCK
  RPM: 2100, Load: 25%, Boost: vacuum (-15 inHg), TPS: 12%
  Engine was at light cruise/decel. No boost. Low load.
  Real detonation at 2100 RPM / 25% load / vacuum is extremely unlikely.
  Timing pulled: 2 degrees (mild ECU response)
  Assessment: Probable false trigger — heat shield rattle, exhaust tick, or road vibration.
  Action: No tune change. If this pattern repeats at same RPM/load, check for
           loose heat shields or exhaust hangers.

Summary: 1 real knock event, 1 probable false positive.
  Real knock was associated with slightly lean AFR under boost.
  Fuel correction at the affected cell is recommended.
```

### Example 4: Ethanol Content + AFR Threshold Interpolation

**Scenario:** Driver has a partial tank of E85 mixed with pump gas. System must adjust AFR thresholds based on actual ethanol content.

**Input:**
```
ethanol_content: 62% (from flex fuel sensor)
operating_condition: WOT (wide open throttle, under boost)
measured_afr: 10.2:1
```

**Calculation:**
```
Gasoline WOT target AFR: 11.0-11.5:1 (midpoint: 11.25:1)
E85 WOT target AFR: 7.5-8.0:1 (midpoint: 7.75:1)
Gasoline WOT danger (lean): 12.5:1
E85 WOT danger (lean): 8.8:1

Ethanol fraction: 62% = 0.62
Gas fraction: 38% = 0.38

Interpolated WOT target midpoint:
  (0.38 x 11.25) + (0.62 x 7.75) = 4.275 + 4.805 = 9.08:1

Interpolated WOT danger threshold:
  (0.38 x 12.5) + (0.62 x 8.8) = 4.75 + 5.456 = 10.21:1

Interpolated WOT target range:
  Low: (0.38 x 11.0) + (0.62 x 7.5) = 4.18 + 4.65 = 8.83:1
  High: (0.38 x 11.5) + (0.62 x 8.0) = 4.37 + 4.96 = 9.33:1
```

**Expected result:**
```
Ethanol: 62%
WOT Target AFR: 8.83 - 9.33:1
WOT Danger (lean): 10.21:1
Measured AFR: 10.2:1

Status: CAUTION — AFR is at the lean boundary for this ethanol blend.
  Measured 10.2:1 is within 0.01 of the danger threshold (10.21:1).
  This is too close. The tune may need slightly more fuel at WOT for
  mid-blend ethanol content.
```

### Example 5: Drive Summary Generation

**Scenario:** Complete drive with all data collected. Generate summary for driver display and server storage.

**Input (drive session):**
```
drive_start: 2026-07-15 14:00:00
drive_end: 2026-07-15 15:15:00
duration: 75 minutes
distance: 42 miles (from vehicle speed integration)

Parameter summaries:
  coolant_temp: min=165F, max=198F, avg=192F
  rpm: min=700, max=6200, avg=2400
  iat: min=95F, max=138F, avg=118F
  boost: min=-18 inHg, max=14.2 psi, avg=2.1 psi
  afr: min=10.8:1, max=15.2:1 (WOT min was 11.2:1)
  knock_count: 0
  idc_peak: 78%
  ethanol: 74% (stable)
  stft_avg: +2.1%
  ltft: +1.5%
  battery: 14.2V avg
```

**Expected drive summary output (for display and storage):**
```
DRIVE SUMMARY — 2026-07-15
━━━━━━━━━━━━━━━━━━━━━━━━━
Duration: 1h 15m | Distance: 42 mi
Status: ✓ ALL NORMAL

Engine:
  Coolant: 192F avg, 198F peak ✓
  IAT: 118F avg, 138F peak ✓
  RPM: 6200 peak
  Boost: 14.2 psi peak

Fueling:
  AFR (WOT): 11.2:1 min ✓ (target: 11.0-11.5)
  Ethanol: 74%
  IDC: 78% peak ✓
  STFT: +2.1% avg ✓
  LTFT: +1.5% ✓

Safety:
  Knock events: 0 ✓
  Battery: 14.2V ✓
  Alerts: None

No issues detected. Happy engine. 🟢
```

---

## 6. Tuning Roadmap

### Phase 0: Pre-Hardware (NOW — April 2026)
**Vehicle state:** Car in garage, battery charger, Pi on desk
**System state:** 144 modules built, simulator working, no live data yet

**What the team should be building:**
- Finish current sprint work (DB verify, orchestration tests, Ollama cleanup)
- Ensure the simulator can generate all Phase 1 PID data realistically
- Build/verify the alert threshold engine against the thresholds in this document
- Build/verify drive summary generation (Example 5 above)
- Test display rendering for the 3.5" screen layout

**What Spool provides:** This document. All thresholds, all examples, all analysis specs.

### Phase 1: First Live Connection (May-June 2026)
**Vehicle state:** Car out of storage, driving on pump gas, stock ECU
**Pi state:** Installed in car, connected via OBDLink LX Bluetooth
**Data source:** OBD-II only, ~5 PIDs/sec

**Milestone: First real datalog uploaded to server.**

**What the system should do:**
- Collect core 5 PIDs at 1 Hz with tiered extended PIDs
- Display coolant, RPM, and status indicator on 3.5" screen
- Alert on coolant temp, STFT, timing anomalies (Phase 1 thresholds)
- Store datalogs locally on Pi
- Sync to Chi-Srv-01 when parked in garage on WiFi
- Generate drive summaries
- Server runs baseline comparison and thermal analysis

**What Spool validates:** First live data from the actual car. Verify which PIDs are actually supported (PID 0x00 query). Confirm sensor readings match reality (does coolant temp read right? does RPM match tach?). Establish baseline.

### Phase 2: ECMLink + Wideband (June-July 2026)
**Vehicle state:** ECMLink flashed, wideband installed, still on pump gas
**New hardware:** Fuel pump swapped, flex fuel sensor wired, exhaust upgraded
**Data source:** OBD-II + ECMLink serial (if Pi can receive it)

**Milestone: First WOT datalog with real AFR and knock data.**

**What the system should do:**
- Everything from Phase 1, plus:
- Ingest ECMLink datastream (knock, AFR, boost, IDC, ethanol, timing, target AFR)
- Display AFR and boost on driver screen
- Alert on ALL Phase 2 thresholds (wideband AFR, knock, IDC, boost)
- Server runs knock correlation analysis (Analysis 1)
- Server runs AFR drift trending (Analysis 2)
- Server establishes the "real" baseline now that we have full data

### Phase 3: E85 + Full Tune (July-August 2026)
**Vehicle state:** Injectors swapped, E85 in tank, flex fuel active, tuned
**Data source:** Full ECMLink + flex fuel sensor

**Milestone: First E85 datalog with ethanol-adjusted thresholds.**

**What the system should do:**
- Everything from Phase 2, plus:
- Ethanol-aware AFR thresholds (interpolation per Example 4)
- E85 content tracking analysis (Analysis 5)
- Injector duty cycle tracking (Analysis 3)
- Full baseline comparison with E85-specific baseline
- Server runs all 6 analysis types

### Phase 4: Mature System (September 2026+)
**Vehicle state:** Fully tuned, E85, all monitoring active
**System state:** Library of datalogs, established baselines, trend data

**What the system should do:**
- Everything from Phase 3, plus:
- Multi-drive trend analysis (Analysis 2, 3, 4 with real historical data)
- Seasonal comparison (July vs September — ambient temp effects)
- Anomaly detection against established baseline
- Advisory messages pushed to Pi for driver review at next startup

### Phase 5: Edge Intelligence (Future)
**What it could become:**
- Small ML model on Pi for real-time pattern recognition
- Predictive alerts ("based on the last 50 drives, your fuel pump is weakening")
- Automatic tune suggestion generation (validated by Spool before applying)
- Integration with ECMLink for closed-loop tune adjustments (requires extensive safety validation)

**This phase requires:** A full summer of clean data, validated analysis pipelines, and proven thresholds. Not before late 2026 at the earliest.

---

## 7. Standing Offer

Marcus, I'm available for consultation on any of this. When the developer has questions about threshold values, when the architect needs to understand data relationships, when the tester needs to validate alert behavior — send a note to my inbox. I'll respond with specific, grounded answers.

**What I need from the team:**
- Let me review any proposed threshold values before they're committed to code
- Send me the first real datalog from the car when it happens — I want to validate the readings
- Flag any PID that returns unexpected values — I can tell you what it should look like
- When ECMLink is installed, send me the first WOT pull datalog — I'll verify the tune is safe

This is going to be a good system. The foundation is solid. Now let's put the tuning brain in it.

— Spool

---

*"The software team builds the pipeline. I define what flows through it and what it means."*
