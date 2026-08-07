# "Full Advantage of Existing Sensors" — 4 Prototypes — Design Spec

| | |
|---|---|
| **Author** | Iris (UI/UX) |
| **Date** | 2026-08-03 · **rev 2026-08-07 (Spool PID ruling folded)** |
| **Status** | **CIO priorities set 2026-08-03: P2 (Engine card) + P3 (post-drive review) = PRIORITY; P4 = low-priority/fun, re-styled as an aircraft attitude indicator for the Eclipse; P1 folded into P2.** GPS + baro sensor ON HOLD. **Spool's data gate is now CLEARED (2026-08-07) — P2 is unblocked, with the boost gauge removed.** P3 still needs an Atlas server-tier contract. |
| **Rev 08-07** | Spool's probe rulings (`inbox/2026-08-07-from-spool-pid-return-rulings-kill-boost-tile.md`) folded: **boost tile killed** (MAP 0x0B probe-dead *and* the wrong quantity), **MAF promoted** to the centrepiece, 0x42 → `ATRV`, O2 → `FUEL_SYSTEM_STATUS` + trims, timing stays off, **~2.5 s/PID sample-rate rule** and the **LTFT idle caveat** added as design constraints. |
| **Directive** | CIO 2026-08-03: take full advantage of the sensor data we already have; **fact-check every readout against what the OBDLink actually returns; NO dead "no source" displays.** |
| **Companion** | `proposals/2026-08-03-full-advantage-sensor-prototypes.html` + hosted artifact |
| **Palette** | `specs/UI/tokens.css` |

## 0. Fact-check — what data is actually available (the "no dead displays" gate)

**Superseded 2026-08-07 — re-derived from Spool's capability probe (2026-05-22, 16 Mode-01 PIDs,
unchanged by the ECMLink flash), NOT the `config.json` poll list.** My first pass sourced "confident
YES" off the poll list; Spool's correction is that **config membership is not evidence of PID
support** — Tier 4 polls two dead PIDs and eats NO_DATA every 30th cycle (his filed defect,
`edr-pid-priority-allocation.md` §2b). Only GREEN may drive a live readout.

| Signal | Ruling | Notes |
|---|---|---|
| RPM 0x0C · THROTTLE_POS 0x11 · ENGINE_LOAD 0x04 | ✅ **GREEN** | driving feel |
| SPEED 0x0D | ✅ **GREEN** | stored **km/h**, correction factor **1.00** (GPS-confirmed Drive 27) — do NOT scale; convert for display only |
| COOLANT_TEMP 0x05 | ✅ **GREEN** | 🔴-capable (see bands) |
| INTAKE_TEMP 0x0F | ✅ **GREEN** | **label "INTAKE AIR", never "charge temp"** — see below |
| **MAF 0x10** | ✅ **GREEN — my premise was backwards** | the 2G 4G63 is **MAF-based** (Karman-vortex), not speed-density. *That is why MAF lives and MAP is dead:* this engine meters fuel on measured airflow and needs no manifold-pressure sensor for fuelling. **Primary fuel-metering input → the centrepiece.** |
| STFT 0x06 · LTFT 0x07 | ✅ **GREEN** | bands below — **read the idle caveat** |
| BAROMETRIC 0x33 | ✅ **GREEN** | supported after all; gives ambient/altitude context — but **nothing toward boost** |
| FUEL_SYSTEM_STATUS 0x03 | ✅ **GREEN** | → "Closed loop / Open loop" — takes the tile O2 would have had |
| g-force · heading · grade · **gyro** | IMU | ✅ **GREEN** | 100 Hz — the only source that can feel live |
| **INTAKE_PRESSURE 0x0B (MAP)** | ❌ **DEAD — double-dead** | probe-unsupported **and** the wrong quantity: on the 2G it's wired to the **MDP sensor** (EGR-system monitor), not manifold boost. Standing rule: **never source a boost readout or alert off 0x0B on this vehicle.** |
| **CONTROL_MODULE_VOLTAGE 0x42** | ❌ **DEAD** | but **keep the voltage readout** — source it from the adapter's `ATRV` (pin 16, off the K-line, effectively free; `BATTERY_V` already does this) |
| O2_B1S1 0x14 | ⛔ **supported, DO NOT GAUGE** | narrowband oscillates 0.1–0.9 V at 1–3 Hz *by design* — as a gauge it's a needle slamming the rails, it means nothing to a driver, **and it is not AFR**. No numeric AFR exists until a wideband lands. |
| TIMING_ADVANCE 0x0E | ⛔ **supported, KEEP IT OFF** | base timing swings ±10–15° normally. A "timing" gauge **reads as a knock gauge** to a driver and is not one. No knock signal exists without ECMLink. |

### Boost is not displayable — by any software fix

My boost math (`psi = (MAP − baro) × 0.145`) was correct; **there is simply no MAP term to feed
it.** Boost on this car requires a **GM 3-bar sensor + ECMLink** — both behind the CIO's sensor
freeze. Spool's bands are recorded here as documentation only, **not to render**: stock TD04-13G
🟢 10–12 psi · 🟡 13–14 · 🔴 >15.

### Bands that DO apply

- **Coolant** (alert-layer SSOT, unchanged): 🟢 ≤99 · 🟡 100–103 · 🔴 **≥104 °C** (head-bolt stretch /
  MLS clamp loss on a 4G63).
- **Fuel trims:** STFT 🟢 −5…+5 % · 🟡 ±5–10 % · 🔴 >±15 %. LTFT 🟢 −5…+5 % · 🟡 ±5–8 % · 🔴 >±10 %.
  🔴 **This-car caveat — it bites the UI directly:** this engine shows a characteristic
  **LTFT ≈ −6.25 % lock at warm idle** (drives 3/5/6). That is *this engine's normal*, not a fault.
  Banded naively, **every stoplight paints amber** — so LTFT is **offset or uncoloured at idle**.
  A gauge that cries wolf at every light trains the driver to ignore the one time it's real.
- **IAT — informational only, NO red.** Advisory amber ~≥60 °C (heat soak). Two reasons it never
  goes red: (1) the 2G sensor lives in the **AFM/air-filter housing — pre-turbo, pre-intercooler**,
  so it reads inlet air, not charge temp (a turbo audience reads "charge temp" as post-IC; it isn't).
  (2) IAT alone doesn't kill an engine — IAT + boost + knock does, and **we have neither boost nor
  knock**, so red would be theatre.

### Sample rate — a design constraint on every tile

The whole K-line budget is **~6.3 samples/sec across ALL PIDs combined** (measured Drive 27,
ISO 9141-2 @ 10,400 bps, ~160 ms per round-trip). At 16 PIDs that is **~0.39 Hz each — one update
every ~2.5 s** — and there is no "turn up the Hz" knob: more PIDs is strictly slower per PID.

**So: no smoothly-animated needles.** Interpolating across a 2.5 s gap fabricates values the ECU
never reported — the same honest-instrument violation as an over-confident derived altitude. Values
**step**, or show last-value + age. Anything that must *feel* live comes off the IMU (100 Hz) or
`ATRV`, never the K-line.

## 1. The four prototypes (all in the mockup)

- **P1 · Airflow + vitals on the driving view** *(was "boost + vitals")* — augments the live card: an
  **airflow bar (MAF g/s)** + a compact vitals row (coolant · intake air · RPM · throttle). Lowest
  complexity; MAF is the closest honest analogue to boost feel and the actual fuel-metering input.
- **P2 · Dedicated "Engine" card** — a full engine screen: **MAF arc gauge** + RPM + coolant/intake-air
  + throttle/load + STFT/LTFT + **Closed/Open loop** + voltage (`ATRV`). Richer, but adds a 5th card to
  the consolidated 4-card set. *(Was a boost arc gauge.)*
- **P3 · Post-drive review** — server-analytics surface from logged data: **airflow/effort trace**,
  **g-force trace**, **corner-lean**, **grade profile** over the drive. Deepest value; server-tier build.
  **The slow K-line stops mattering here** — a 22-minute trace reads fine at 0.4 Hz, and the IMU
  channels are 100 Hz regardless. This surface extracts more from the existing sensors than any live
  gauge can.
- **P4 · Attitude indicator (LOW PRIORITY / FUN, CIO 2026-08-03)** — an **aircraft "gyro horizon" for
  the Eclipse**: aircraft pitch → road **grade** (IMU pitch), aircraft bank → body **lean** in corners
  (IMU roll); round instrument face + bezel, gradient sky/ground horizon that rolls + pitches, a pitch
  ladder, a fixed roll index + bank scale (10/20/30/45/60°) with a rolling pointer, a **1998 Eclipse
  GST rear-view silhouette** (traced from the CIO's reference photo — rounded body, narrowing hatch,
  the signature raised GST wing, twin exhaust) as the fixed reference, and the aviation **slip/skid ball
  repurposed as a lateral-g corner-load meter**. IMU-only; needs pitch/roll/gyro exposed in `states/imu`.

## 2. Rules honored
- **No dead displays:** every readout maps to a probe-GREEN signal; anything unavailable is
  **omitted, not shown as NA** (NA/`no source` is reserved for a normally-present signal dropping).
- **Probe, not poll list:** capability comes from Spool's capability probe. Config membership is not
  evidence of support.
- **Layout mine, semantics Spool's:** coolant/IAT thresholds, fuel-trim meaning, what earns a gauge → Spool.
- **No fabricated motion:** OBD tiles step at the true ~2.5 s cadence; only IMU/`ATRV` sources animate.
- **No alarm fatigue:** LTFT uncoloured at idle; IAT never red; no timing or O2 gauge.

## 3. Routing
- **Spool — ANSWERED 2026-08-07** (`inbox/2026-08-07-from-spool-pid-return-rulings-kill-boost-tile.md`):
  per-PID rulings delivered, boost killed, MAF premise corrected, bands + sample-rate rule given.
  **P2's data gate is cleared.** Nothing further owed to him on this line.
- **CIO — ANSWERED 2026-08-03:** P2 + P3 priority; P4 fun/low; P1 folded into P2.
- **Marcus:** hand-off for backlog — see `pm/inbox/2026-08-07-from-iris-w16-sensor-prototypes-for-backlog.md`.
- **Atlas:** P3 needs a server-tier analytics contract; P4 needs `roll` + `yawRate` exposed in `states/imu`.
