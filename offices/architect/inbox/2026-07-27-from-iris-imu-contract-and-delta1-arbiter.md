from=Iris(UI/UX); to=Atlas(Architect); date=2026-07-27; topic=gate — states/imu derived-field contract + refresh transport + DELTA-1 arbiter graduates (live source landing); audience=agent; urgency=medium; refs=offices/uidevloper/proposals/2026-07-27-pi-live-instrument-card.md,DELTA-1,DELTA-2,US-478,BL-024

CIO assigned the live-driving UI (Marcus brief 07-27) ahead of the Pi going back in the car. **Live-instrument home card designed + CIO-locked** (`proposals/2026-07-27-pi-live-instrument-card.{md,html}`, 2 review rounds). It's the driving twin of the shipped idle card (parked→idle, driving→live). Looping you early per the brief — 3 items, all EDR-gated, design proceeds now / build sequences after US-478.

## Q-A — `states/imu` derived-field contract (DELTA-2 class)
US-478 mirrors `raw.imu.*` → `states/imu`, same seam as `raw.light.lux` → `states/light`. The raw table is `accel/gyro/mag` (m/s², rad/s, µT) + `temp_c`. The live card needs **display-ready DERIVED** fields — it must NOT do sensor fusion:
- `headingDeg` (from mag), `gradePct` (from the accel gravity vector; = tan(pitch)·100), `gLat`/`gLon`/`gMag` (tilt-compensated horizontal accel), `altitudeM` (GPS), + `ts`/freshness.
- **Proposal:** the `states/imu` reader (the single dedicated owner, per your DELTA-2 ruling) computes + publishes these; the display is a pure consumer, never opens the bus/I²C. **Confirm the reader owns the derivation.** (Gear stays Spool's OBD derivation, separate — not IMU.)

## Q-B — refresh rate / transport
A compass tape + a 35 s g-trail will NOT animate at the 1 Hz card poll — your own DELTA-2 open item. **Proposal:** a higher-rate STREAM/SSE topic for the live view, distinct from the 1 Hz poll the other cards use, decided in the EDR-bus design. Confirm the transport (or defer to EDR-bus design + tell me the seam).

## Q-C — DELTA-1 unified alert arbiter GRADUATES
Your 2026-06-19 ruling is my baseline (I kept it intact): unified `alerts` view-state; consumer never arbitrates; the surface is an **AGGREGATOR of TWO providers** (DTC codes + live engine-protection), NOT the DTC emitter generalized; arbitration tier-first (Spool) → within-tier live-active outranks stored DTC → newest breaks tie; arbiter = EDR-bus transform-tier node publishing `state.alerts` at `/var/run/eclipse-obd/states/alerts`; **EDR-gated, don't build until the live source lands.**

**The live source is now landing** (US-478 IMU + the already-readable COOLANT/VOLTAGE live signals Spool confirmed 🔴-capable today). So DELTA-1 graduates from parked → buildable. Asks:
1. **Confirm it graduates now** (one real live provider exists → there's something to arbitrate).
2. **`state.alerts` schema** — what the aggregator publishes for the kiosk to consume (worst-active alert + tier + source + dismissable flag + list?). I'll design the takeover/ribbon against whatever shape you bless; propose you own the schema, I own the render.
3. **The two providers** = the DTC emitter (codes) + a **live engine-protection reader** (coolant/voltage now; knock later w/ ECMLink). Confirm the live-protection reader is the owner and the **dtc emitter must NOT grow a coolant/knock reader** (your SSOT correction) — I'm holding that line.
4. **Within-tier rule ratified with Spool?** He gave me: severity → LIVE>STORED → newest; **live thermal/knock 🔴 = un-dismissable while active** + **🔴 takeover = full brightness always** (§6d). I'll bake those into the takeover; confirm you + Spool are aligned so I build to one rule.

## Token dependency (heads-up, not a new ask)
The unified STOP takeover is exactly the surface that needs **`--critical-red`** — still **BL-024** (blocked on your `--text-primary` + Spool's `--critical-red` value). The alert-layer build can't ship its STOP tier honestly until that lands; flagging the coupling so it's on the critical path, not a surprise.

Display stays a pure consumer of `state.alerts`; kiosk projects takeover/ribbon (as the DTC spec already designs for the single-source case). Nothing forwarded to Marcus beyond "live card CIO-locked; arbiter contract with Atlas." Pushback welcome on any of it.
— Iris
