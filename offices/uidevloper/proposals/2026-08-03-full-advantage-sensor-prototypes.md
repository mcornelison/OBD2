# "Full Advantage of Existing Sensors" — 4 Prototypes — Design Spec

| | |
|---|---|
| **Author** | Iris (UI/UX) |
| **Date** | 2026-08-03 · **rev 2026-08-17 (Spool CORRECTION 2 — baro has no source)** |
| **Status** | **CIO priorities set 2026-08-03: P2 (Engine card) + P3 (post-drive review) = PRIORITY; P4 = low-priority/fun, re-styled as an aircraft attitude indicator for the Eclipse; P1 folded into P2.** GPS + baro sensor ON HOLD. **Spool's data gate is now CLEARED (2026-08-07) — P2 is unblocked, with the boost gauge removed.** P3 still needs an Atlas server-tier contract. |
| **Rev 08-07** | Spool's probe rulings (`inbox/2026-08-07-from-spool-pid-return-rulings-kill-boost-tile.md`) folded: **boost tile killed** (MAP 0x0B probe-dead *and* the wrong quantity), **MAF promoted** to the centrepiece, 0x42 → `ATRV`, O2 → `FUEL_SYSTEM_STATUS` + trims, timing stays off, **~2.5 s/PID sample-rate rule** added as a design constraint. |
| **Rev 08-17** | Spool **CORRECTION 2** (`inbox/2026-08-17-from-spool-CORRECTION-baro-has-no-source.md`): **BAROMETRIC has NO SOURCE** — absent from the live capture; do not display. Basis of §0 switched to the **confirmed-live capture set** (drives 37/38). **MAF + `FUEL_SYSTEM_STATUS` both CONFIRMED LIVE with real values** (MAF 3.1–3.4 g/s idle) — the two substitutes for boost and the O2 tile are real. Nothing in the design breaks. |
| **Rev 08-07b** | Spool **CORRECTION** (`inbox/2026-08-07-from-spool-CORRECTION-ltft-idle-band.md`): the **LTFT idle-offset caveat is WITHDRAWN** — the −6.25 % figure was **old-ECU** (MD346675). Fuel trims are banded **straight**, no idle special-case. Everything else in his ruling stands. |
| **Directive** | CIO 2026-08-03: take full advantage of the sensor data we already have; **fact-check every readout against what the OBDLink actually returns; NO dead "no source" displays.** |
| **Companion** | `proposals/2026-08-03-full-advantage-sensor-prototypes.html` + hosted artifact |
| **Palette** | `specs/UI/tokens.css` |

## 0. Fact-check — what data is actually available (the "no dead displays" gate)

**Basis, rev 2026-08-17: the CONFIRMED-LIVE CAPTURE SET — measured in `realtime_data` on drives
37/38 — not a probe count, not a poll list, not an allocation doc.** Only a parameter observed
returning real values may drive a readout.

That basis moved twice, and both moves were the same error made by two different people:

1. **08-07** — my first pass derived "confident YES" from the **`config.json` poll list**. Spool's
   correction: **config membership is not evidence of PID support** (Tier 4 polls two dead PIDs and
   eats NO_DATA every 30th cycle — his filed defect, `edr-pid-priority-allocation.md` §2b).
2. **08-17** — Spool then self-corrected: he had green-lit **BAROMETRIC** off a probe that reported
   *"16 PIDs supported"* **without enumerating which 16**, plus his own doc listing baro as a
   **proposed** Tier-4 allocation. He **read a proposal as a capability** — his words — and the rule
   binds him identically. Baro is **absent from the live capture**.

**The durable rule for this surface: a readout requires a parameter seen returning a real value in
`realtime_data`.** Everything weaker — a poll list, a supported-count, a tier allocation, a card
tagged `both` — is a plan, not evidence. See
[[pattern-the-artifact-is-not-the-fact]].

| Signal | Ruling | Notes |
|---|---|---|
| RPM 0x0C · THROTTLE_POS 0x11 · ENGINE_LOAD 0x04 | ✅ **GREEN** | driving feel |
| SPEED 0x0D | ✅ **GREEN** | stored **km/h**, correction factor **1.00** (GPS-confirmed Drive 27) — do NOT scale; convert for display only |
| COOLANT_TEMP 0x05 | ✅ **GREEN** | 🔴-capable (see bands) |
| INTAKE_TEMP 0x0F | ✅ **GREEN** | **label "INTAKE AIR", never "charge temp"** — see below |
| **MAF 0x10** | ✅ **GREEN — my premise was backwards** | the 2G 4G63 is **MAF-based** (Karman-vortex), not speed-density. *That is why MAF lives and MAP is dead:* this engine meters fuel on measured airflow and needs no manifold-pressure sensor for fuelling. **Primary fuel-metering input → the centrepiece.** |
| STFT 0x06 · LTFT 0x07 | ✅ **GREEN** | bands below — band them **straight**; the idle-offset caveat was **withdrawn** by Spool 08-07 |
| ~~BAROMETRIC 0x33~~ | ❌ **NO SOURCE — do not display** | **Corrected 2026-08-17 (Spool CORRECTION 2).** He green-lit it on 08-07; it is **absent from the live capture** (drives 37/38 land 16 params, baro is not one; `drive_summary.baro` blank on drives 34–38). Unsupported-vs-not-polled is unsettled, but there is **no source either way**. Nothing of mine breaks — boost was already dead and baro was only ever an atmospheric *reference*. |
| FUEL_SYSTEM_STATUS 0x03 | ✅ **GREEN** | → "Closed loop / Open loop" — takes the tile O2 would have had |
| g-force · heading · grade · **gyro** | IMU | ✅ **GREEN** | 100 Hz — the only source that can feel live |
| **INTAKE_PRESSURE 0x0B (MAP)** | ❌ **DEAD — double-dead** | probe-unsupported **and** the wrong quantity: on the 2G it's wired to the **MDP sensor** (EGR-system monitor), not manifold boost. Standing rule: **never source a boost readout or alert off 0x0B on this vehicle.** |
| **CONTROL_MODULE_VOLTAGE 0x42** | ❌ **DEAD** | but **keep the voltage readout** — source it from the adapter's `ATRV` (pin 16, off the K-line, effectively free; `BATTERY_V` already does this) |
| O2_B1S1 0x14 | ⛔ **supported, DO NOT GAUGE** | narrowband oscillates 0.1–0.9 V at 1–3 Hz *by design* — as a gauge it's a needle slamming the rails, it means nothing to a driver, **and it is not AFR**. No numeric AFR exists until a wideband lands. |
| TIMING_ADVANCE 0x0E | ⛔ **supported, KEEP IT OFF** | base timing swings ±10–15° normally. A "timing" gauge **reads as a knock gauge** to a driver and is not one. No knock signal exists without ECMLink. |

### Boost is not displayable — by any software fix

My boost math (`psi = (MAP − baro) × 0.145`) was correct; **there is no MAP term to feed it — and
as of 08-17 no baro term either.** Both sides of the subtraction are missing. Boost on this car requires a **GM 3-bar sensor + ECMLink** — both behind the CIO's sensor
freeze. Spool's bands are recorded here as documentation only, **not to render**: stock TD04-13G
🟢 10–12 psi · 🟡 13–14 · 🔴 >15.

### Bands that DO apply

- **Coolant** (alert-layer SSOT, unchanged): 🟢 ≤99 · 🟡 100–103 · 🔴 **≥104 °C** (head-bolt stretch /
  MLS clamp loss on a 4G63).
- **Fuel trims:** STFT 🟢 −5…+5 % · 🟡 ±5–10 % · 🔴 >±15 %. LTFT 🟢 −5…+5 % · 🟡 ±5–8 % · 🔴 >±10 %.
  **Band both STRAIGHT — no idle offset, no idle suppression, no special-case branch.**
  ⚠️ **Superseded (Spool CORRECTION 2026-08-07):** his earlier note in the same day warned of a
  characteristic **LTFT ≈ −6.25 % lock at warm idle** requiring an idle offset. **That figure is
  from the OLD ECU** (MD346675, drives 3/5/6); the car has run **MD326328** since 2026-05-22, and
  he re-baselined against it (drives 25–38, n≈2,700): per-drive averages **−2.6 % to +1.5 %**, full
  range **−3.9 % to +3.1 %**, warm parked idle **−2.6 % / −2.4 %**. All inside the ±5 % 🟢 band,
  **including the idle case he warned about** — a naive band does *not* false-alarm on this car.
  The special-case is therefore **not built**. See [[pattern-the-artifact-is-not-the-fact]].
- **Fixture warning (Spool, unresolved):** do **not** use drives **35/36** as a "healthy idle"
  reference in any mock or fixture — they report LTFT **exactly 0.00 across all 232 samples, zero
  variance**, which is either a genuine adaptive-memory reset or a decode artifact of the same class
  as the Session-27 freeze-frame floor-decode bug. He is not calling it yet.
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
- **No alarm fatigue:** IAT never red; no timing or O2 gauge. (LTFT idle-suppression was withdrawn — it solved a problem the current ECU does not have.)

## 3. Routing
- **Spool — ANSWERED 2026-08-07** (`inbox/2026-08-07-from-spool-pid-return-rulings-kill-boost-tile.md`):
  per-PID rulings delivered, boost killed, MAF premise corrected, bands + sample-rate rule given.
  **P2's data gate is cleared.** Nothing further owed to him on this line.
- **CIO — ANSWERED 2026-08-03:** P2 + P3 priority; P4 fun/low; P1 folded into P2.
- **Marcus:** hand-off for backlog — see `pm/inbox/2026-08-07-from-iris-w16-sensor-prototypes-for-backlog.md`.
- **Atlas:** P3 needs a server-tier analytics contract; P4 needs `roll` + `yawRate` exposed in `states/imu`.
