# Black-box / Event-Data-Recorder concept — engine & OBD-side SME assessment

**Date**: 2026-06-16
**From**: Spool (Tuning SME)
**To**: Atlas (Architect)
**Priority**: Important (design input — CIO-directed forward)
**Re**: CIO brainstormed a Pi-5 automotive "black box" (EDR) design with an external agent. CIO asked me to pass it through an engine/OBD reality check first, then forward to you. This is the outcome. The external plan is sound in *structure* (recorder-first, IMU as high-rate channel, RAM ring → rolling disk segments → protected event vault, tiered OBD polling, trigger-on-event). My notes are only where it collides with **our specific car** — a 1998 DSM — and where engine-protection changes the trigger set.

## Headline
Concept fits and complements tuning. But the plan was written without our specs, so two load-bearing assumptions break, and the most important engine signal is missing from its data path. **CIO has ruled ECMLink datastream integration IN-SCOPE** (see §3) — that's the biggest single architecture decision in here.

## 1. OBD bandwidth — measured ceiling, not the plan's targets
Our bus is **ISO 9141-2 K-Line @ 10,400 bps** (request-reply, pre-CAN). The plan's python-OBD cadence assumes modern CAN. Grounded against our own data:

- **Drive 27 (real capture):** 16 PIDs, **~0.39 Hz per PID** (one sample every ~2.5 s), **~6.3 samples/sec aggregate**, full poll cycle ≈ 2.5 s.
- The plan's **Tier-1 = 5 Hz × 5 PIDs = 25 samples/s** — that's **~4× our entire throughput budget**, before Tier-2/3.

**Implication:** OBD throughput is a *fixed ~6 samples/sec budget you allocate*, not a per-tier rate you set. The tiering *concept* is right; the numbers must be derived from this ceiling. Higher per-PID rate only comes from polling *fewer* PIDs. I can produce a measured throughput budget + a recommended PID-priority allocation when this grooms.

## 2. PID availability — validate against our actual supported set
The plan's "high-priority" PID list is generic. On our MD326328 (ECMLink) ECU, grounded:
- **Confirmed SUPPORTED & live** (Drive 27): SPEED, RPM-equiv via ENGINE_LOAD, THROTTLE_POS, COOLANT_TEMP, INTAKE_TEMP, **MAF**, SHORT/LONG_FUEL_TRIM_1, **TIMING_ADVANCE**, O2_B1S1, O2_B1S2, BATTERY_V, FUEL_SYSTEM_STATUS, MIL_ON, DTC_COUNT (16 total).
- **Confirmed UNSUPPORTED:** **Mode 02 freeze-frame** (verified live, Session 25, on this ECU).
- **Likely unsupported (verify):** `fuel_rate` (0x5E), `ambient_air_temp` (0x46).
- **Action:** validate the recorder's PID schema against our logged supported-PIDs map + `offices/tuner/scripts/probe_obd_capabilities.sh`. Don't create `sample_obd` columns for PIDs that only return NULL.

## 3. The knock gap → ECMLink datastream (CIO ruled IN-SCOPE)
**On a stock-turbo 4G63, detonation is the #1 engine-killer (cracked #4 piston).** Knock sum / knock-retard is **NOT a standard OBD-II PID** — `TIMING_ADVANCE` (0x0E) gives *base* timing, not knock-retard. Knock lives in **ECMLink's own datastream**, off the OBD path we read today. A recorder blind to knock misses the event most likely to end this engine.

CIO wants ECMLink datastream **on the table**. My honest flags for you:
- **High value, high integration uncertainty.** ECMLink V3 logging is historically tied to its Windows software over the ECU's diagnostic interface; whether it exposes a real-time stream the Pi can read *without* that software needs a **feasibility spike** before any commitment.
- **K-line contention:** the OBDLink LX already occupies the diagnostic channel. ECMLink tapping the same interface concurrently is a real conflict to design around (arbitration, or separate physical tap).
- If feasible, it unlocks the *real* engine triggers (knock, true load, MAP/boost). If not, engine triggers are limited to coolant/voltage/DTC + IMU inference — say so explicitly rather than implying knock coverage we don't have.

## 4. Engine-protection triggers (my lane — real thresholds)
The plan's motion triggers (0.7g brake / 0.8g lateral / 1.5g impact) are fine as *driving*-event triggers. Its engine-state triggers are vague. Replace with grounded values:
- **Coolant: absolute, not rate.** Freeze at **≥104 °C / 220 °F** — head-gasket-risk band on the 4G63 (bolt stretch, MLS clamp loss, coolant→#4). Drive 27 peaked 101 °C; we're already near it. A rate trigger misses a slow climb into the band.
- **Lean-under-load:** combined STFT+LTFT lean excursion (>~+10–15%) **while load/MAP is high** — lean on boost is an engine-killer; far higher value to seal than a curb strike.
- **Overboost** + **high IAT (heat-soak pulls timing)** as secondary.
- **Knock event** (pending §3) would be the top engine trigger if ECMLink lands.

I'll own the full engine-trigger threshold spec when this grooms.

## 5. Architectural tension with B-104 (your call)
B-104 deliberately made the **Pi a dumb emitter, server the brain** (server computes analytics from raw `realtime_data`). The EDR model puts **trigger logic + event-sealing back ON the Pi.** Not necessarily contradictory — you can stream raw *and* keep a local ring + event vault — but it's a real fork and shouldn't *silently* reverse B-104. Flagging for an explicit ruling.

## 6. Single source of truth + a dedicated reader per source (CIO architectural directive)
CIO directive to carry into this design: **every data consumer sources from exactly ONE canonical source — never directly from the device.** And: **stand up a dedicated data-reading process** that owns the hardware I/O, normalizes, and publishes; all consumers (recorder/event-vault, trigger service, sync/export, display, and the server pipeline) read from that single published source downstream — never reach around it to the hardware.

Why this is a hardware constraint here, not just tidy design:
- **The K-line physically tolerates ONE reader.** The ELM327 is request-reply over a single 10.4 kbps channel — two processes polling it concurrently corrupt the sequencing and tank the already-thin ~6 samples/sec budget. A single dedicated OBD reader isn't a preference; it's forced by the bus.
- It **resolves the ECMLink/OBDLink contention** in §3 cleanly: one reader owns the diagnostic channel and arbitrates OBD-vs-ECMLink access, instead of two services racing the same port.
- It keeps faith with **B-104**: the server already treats raw `realtime_data` as its one source. Extend the same discipline Pi-side — the dedicated reader is the single *producer*; ring buffer, event vault, triggers, and display are all *consumers* of that one stream.
- Line in the sand: the external plan's `sensor-obd` / `sensor-imu` / `sensor-light` split is fine **only** if each is the sole owner of its bus (OBD on serial; IMU + light on I²C) and publishes into the one canonical buffer — and no consumer (especially display or triggers) ever opens the hardware itself.

## 7. Credit + cross-refs
- **Power integrity** (the plan's stated #1 risk): we're already ahead — ShutdownSequencer (F-7), UPS HAT, MAX17048, EEPROM `POWER_OFF_ON_HALT`. The hard part is largely solved.
- **Light sensor → display auto-dim:** CIO flagged this as a use beyond context-logging. That's **Iris's lane** (UI/display brightness) — routing a pointer to her; not architecting it here.
- **Scope:** this is a **V0.3x+ epic**, not a sprint — complements the tuning mission (event reconstruction + datalog context), doesn't replace it. PM should size it as such.

## 8. Derived-signal catalog + compute placement (IMU × speed × engine)
CIO's framing: the 9-DoF IMU turns our 1-D speed trace into a full 6-DOF picture of what the car — and the engine — was doing. Confirmed RPM **is** in our logged set, so gear is derivable. Catalog ranked by tuning value, each tagged with where it should compute:

| # | Inference | Inputs | Tuning value | Compute |
|---|---|---|---|---|
| 1 | **Gear + shift quality + clutch slip** | speed÷RPM (F5M33 ratios) + long-g | gear is the master context for every trim/knock/load reading; slip protects drivetrain | **Server** derives; Pi may show live gear |
| 2 | **Road grade → grade-corrected load** | accel gravity vector + gyro (pitch) | removes the #1 confounder in fuel-trim/knock analysis (hill vs boost) | **Server** (fusion) |
| 3 | **Boost onset / spool characterization** | long-g rate inflection + RPM | maps where TD04-13G lights + spool consistency drive-to-drive, with **no boost PID** | **Server** |
| 4 | **Lateral-g ↔ fuel-trim correlation** | lateral-g + STFT/LTFT | separates real lean tune fault from corner fuel-slosh (hazard on boost) | **Server** |
| 5 | **Vertical-g ↔ knock discrimination** | vertical-g + knock-retard | knock sensor is an accelerometer — hears potholes as "knock"; throws out road-induced false knock | **Server** (gated on ECMLink §3) |
| 6 | **DFCO window flag** | long-g + throttle + RPM | excludes decel-fuel-cut samples that pollute LTFT interpretation | **Server** |
| 7 | **Poor-man's dyno trend** | long-g × mass (~1300 kg) + drag model | drive-to-drive thrust consistency → catches boost leak / failing pump without a dyno | **Server** |

**"During the drive" vs server — the placement rule (ties to §6 + B-104):**
- Server compute is only available *after* sync (home WiFi), so server-derived signals inform the **next** drive + build the engine's behavioral model over time — they are not a live readout.
- **Live on Pi** (cheap, safety-relevant, off the one canonical stream — never re-reading hardware): current gear, live lateral/longitudinal-g, road grade, and safety alerts (coolant ≥104 °C, knock if ECMLink, voltage brownout).
- **Server** (heavy fusion/correlation/modeling): items 2–7. Fusing 100 Hz IMU against ~6 Hz OBD needs interpolation/time-alignment the Pi shouldn't burn cycles on mid-drive — inherently a server job, and consistent with B-104.

**Build-first recommendation:** items 1–3 (**gear, grade-corrected load, spool characterization**) — they re-contextualize *every datalog we already have* and need nothing but the IMU + our existing PID set. Items 4–7 are higher-sophistication payoffs on that foundation.

## What I can deliver when you want it
1. Measured OBD throughput budget + PID-priority allocation for our K-line.
2. Full engine-protection trigger spec with thresholds + rationale.
3. PID-support validation against our live capabilities.
4. ECMLink datastream — engine-signal wishlist (what knock/load/boost fields are worth the integration cost), so a feasibility spike has a target.

CIO and I are still chatting this through; treat this as the first-pass SME read, not frozen. Ping me with questions.

— Spool
