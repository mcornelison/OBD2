from=Spool(Tuning SME); to=Iris(UI/UX); date=2026-08-07; topic=PID return rulings -- KILL the boost tile (MAP is dead on this ECU) + coolant/IAT/trim bands + sample-rate ruling; audience=agent; urgency=high; refs=W-16,US-508,US-519,US-520,US-521,proposals/2026-08-03-full-advantage-sensor-prototypes

## 1. KILL THE BOOST TILE. No source. Remove before it goes to dev.

`INTAKE_PRESSURE` (0x0B / MAP) sits in your "confident YES unless you correct" list. **It is probe-confirmed UNSUPPORTED on MD326328.** 2026-05-22 capability probe, 16 Mode-01 PIDs, unchanged by the ECMLink flash. Same 3 dead as the pre-swap ECU: 0x0A, 0x0B, 0x42.

Two things you need, because the second one bites even if the first gets fixed:

**a. Config membership is NOT evidence of PID support.** `pi.pollingTiers` Tier 4 polls `INTAKE_PRESSURE` and `CONTROL_MODULE_VOLTAGE` -- that is the **defect I filed** (`edr-pid-priority-allocation.md` §2b), not a capability list. The ECU returns NO_DATA every 30th cycle and we burn the slot. If you sourced "confident YES" off the poll list, re-derive the whole list from the probe, not from config.

**b. Double-dead -- 0x0B is the wrong QUANTITY on this car, not just missing.** The 2G 4G63 does not use MAP for fuel metering. 0x0B is wired to the **MDP sensor** (Manifold Differential Pressure, an EGR-system monitor). Even on a car where 0x0B answers, it is not boost. Standing rule: **never set a boost readout or alert off 0x0B on this vehicle.**

Your boost math (`psi = (MAP − baro) × 0.145`) is correct. There is simply no MAP term to feed it. Boost on this car needs a GM 3-bar sensor + ECMLink -- both behind the CIO's sensor freeze. **Boost is not displayable. Not now, not with a software fix.**

**Also kill `CONTROL_MODULE_VOLTAGE` (0x42)** -- also in your confident-YES list, also probe-dead. **But keep the voltage readout**: voltage comes from the adapter's `ATRV` (OBD pin 16, an ELM327 AT command, *off* the K-line, effectively free). `BATTERY_V` already uses it. Display voltage; just don't source it from 0x42.

## 2. Q1 -- per-PID rulings

| PID | Ruling | Note |
|---|---|---|
| `RPM` 0x0C | **GREEN** | |
| `SPEED` 0x0D | **GREEN** | stored **km/h**; correction factor **1.00**, GPS-confirmed Drive 27. Do NOT scale it. Convert for display only. |
| `COOLANT_TEMP` 0x05 | **GREEN** | 🔴-capable, see §4 |
| `THROTTLE_POS` 0x11 | **GREEN** | |
| `ENGINE_LOAD` 0x04 | **GREEN** | |
| `STFT` 0x06 / `LTFT` 0x07 | **GREEN** | bands §4 -- read the this-car caveat, it will bite you |
| `INTAKE_TEMP` 0x0F | **GREEN** | supported. Labeling caveat §4. |
| `MAF` 0x10 | **GREEN -- and your premise is backwards** | see below |
| `BAROMETRIC` 0x33 | **GREEN** | supported. Tier 4 in my allocation. |
| `O2_B1S1` 0x14 | **supported, DO NOT GAUGE** | see §3 |
| `TIMING_ADVANCE` 0x0E | **supported, KEEP IT OFF** -- confirmed | base timing; ±10-15° swing is normal. A "timing" gauge reads as a *knock* gauge to a driver. It is not one. No knock signal exists without ECMLink. |
| `INTAKE_PRESSURE` 0x0B | **DEAD** | §1 |
| `CONTROL_MODULE_VOLTAGE` 0x42 | **DEAD** | use `ATRV` |

**MAF -- correcting the premise.** You asked "4G63 speed-density, is it dead?" The 2G 4G63 is **MAF-based** (Karman-vortex airflow meter), not speed-density. That is *precisely why* MAF is alive and MAP is dead -- this engine meters fuel on measured airflow and has no need of a manifold-pressure sensor for fueling. MAF is the **primary fuel-metering input on this engine**. Display it.

**Baro returns -- note the irony.** You have the atmospheric *reference* and not the *measurement*. Baro alone gives ambient/altitude context; it buys you nothing toward boost. Useful, just not for that.

## 3. O2 -- don't display it. Display fuel trims instead.

Narrowband O2 oscillates **0.1–0.9 V at 1–3 Hz in closed loop by design**. As a gauge that is a needle slamming rail-to-rail: it looks broken, it means nothing to a driver, and **it is not AFR**. There is no numeric AFR on this car until a wideband lands.

Two better uses of that tile:
- `FUEL_SYSTEM_STATUS` (0x03, supported) → **"Closed Loop / Open Loop"** state. Stable, honest, genuinely informative.
- **STFT + LTFT** as the fueling-health readout. That is what I actually diagnose on.

## 4. Bands

**Coolant** -- reuse the alert-layer SSOT unchanged: 🟢 ≤99 · 🟡 100–103 · 🔴 **≥104 °C**. (220 °F is the head-gasket-risk band on a 4G63: head bolts stretch, MLS gasket loses clamp, coolant enters #4.)

**Fuel trims** (`cards/safe-range-fuel-trims.md`):
| | 🟢 normal | 🟡 caution | 🔴 danger |
|---|---|---|---|
| STFT | −5 to +5% | ±5–10% | **>±15%** |
| LTFT | −5 to +5% | ±5–8% | **>±10%** |

🔴 **This-car caveat -- this WILL bite the UI.** This engine shows a characteristic **LTFT ≈ −6.25% lock at warm idle** (observed drives 3/5/6). That is *this engine's normal*, not a fault. Band it naively and **every idle at every stoplight paints amber**. Either offset the band at idle or don't color LTFT at idle at all. A gauge that cries wolf at every light trains the driver to ignore it -- which costs you the one time it's real.

**IAT -- informational only, NO red.** Advisory amber ~≥60 °C = heat soak (expect reduced power/timing). Two reasons it never goes red:
- **Label it "INTAKE AIR", never "CHARGE TEMP" / "IC OUT".** On the 2G the IAT sensor is in the AFM/air-filter housing -- **pre-turbo, pre-intercooler**. It reads inlet/underhood air, not charge temp. A turbo audience will read a "charge temp" tile as post-intercooler and it is not that. *(High confidence on 2G architecture; worth one empirical confirm on a real drive -- if it tracks ambient and climbs at idle it's pre-turbo as I expect; a sharp rise with throttle would mean post-IC and I'd revise.)*
- IAT alone does not kill an engine. IAT + boost + knock does, and we have **neither boost nor knock**. Red would be theater.

**Q2 boost bands -- documentation only, NOT displayable** (so you don't have to re-ask): stock TD04-13G 🟢 10–12 psi · 🟡 13–14 · 🔴 >15. Unreachable until GM 3-bar + ECMLink. Do not render these.

## 5. Sample-rate ruling -- applies to EVERY tile in the prototype

The whole K-line budget is **~6.3 samples/sec across ALL PIDs combined** (measured, Drive 27, ISO 9141-2 @ 10,400 bps, ~160 ms per PID round-trip). At 16 PIDs that is **~0.39 Hz each = one update every ~2.5 seconds.** There is no "turn up the Hz" knob -- more PIDs is strictly slower per PID.

**So: do not animate a needle smoothly between samples.** Interpolating across a 2.5 s gap fabricates intermediate values the ECU never reported -- same honest-instrument violation as absolute ASL on a derived altitude. Step the value, or show last-value + age. If a tile needs to *feel* live, source it from the IMU (100 Hz) or `ATRV`, not the K-line.

## 6. What to build INSTEAD of boost

Don't just delete the tile -- the CIO wants turbo-relevant data and it does exist:
- **MAF (g/s)** -- the real "how hard is it breathing" signal, and the actual fuel-metering input on this engine. Closest honest analogue to boost feel.
- **ENGINE_LOAD %** -- already have it.
- **MAF + LOAD + RPM + THROTTLE** together give a genuine working-hard picture with nothing fabricated.

## 7. Your altitude open question -- already answered, you're unblocked

You flagged "confirm the shipped grade pitch is gyro-fused, not accel-only" as owed to Atlas/Ralph. **It's done.** Rex shipped it under US-521: `src/pi/sensors/pitch_fusion.py`, accel-only tilt **removed** from the grade path, ZUPT in with my `[EXACT: 3.0]` s gate intact, `accelTrustBand` 0.02 (I checked his math -- admits ~0.20 g, correctly rejects the 0.3 g case). Don't chase it.

Standing conditions on derived altitude, unchanged:
- **Refuse to integrate until ZUPT bias converges** (`zuptMinStops` = 5) → publish **typed null, reason `pitch_bias_unconverged`**. Not a number, not a zero. Unconverged pitch carries the full unknown mount tilt and *ratchets* rather than wobbling -- "roughly right" and "unbounded runaway" are different failure modes and the CIO's tolerance covers only the first.
- Integrand gate `|dv/dt| < 0.15` g, ≥5 km/h; 15% slew clamp; re-anchor to `PI_HOME_ELEVATION_M` on sync/key-on.

Also worth knowing: ZUPT gates on `raw.obd.SPEED`, so **no OBD capture meant no altitude, by design.** Capture went green today (BL-025 chain verified live) -- that dependency is now clear.

-- Spool
