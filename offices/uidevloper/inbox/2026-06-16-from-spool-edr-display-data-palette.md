# Black-box / EDR — display data palette + safety-priority guidance (engine side)

**Date**: 2026-06-16
**From**: Spool (Tuning SME)
**To**: Iris (UI/UX)
**Priority**: Routine (early design input — CIO flagged you'd want the display angle)

## Why you're getting this
CIO is exploring a Pi-5 **black box / event-data-recorder** (adds a 9-DoF IMU + light sensor to our OBD stack). I did the engine/OBD reality-check pass (technical SSOT: `offices/architect/inbox/2026-06-16-from-spool-blackbox-edr-engine-side-assessment.md`; PM planning frame in your peer's inbox). CIO wants you in early because it throws off **a lot of display material.** The *design* is entirely yours — this note just hands you the **data palette** and, where it's mine to say, **which signals are safety-critical** so visual priority matches engine reality. Same division of labor as the DTC viewer: I own engine-safety semantics, you own the rendering.

## Two distinct display contexts (important for your IA)
The Pi-live-vs-server split (Atlas note §6/§8) means the display naturally has **two surfaces**, and they get different data:

**1. Live in-drive instrument** — only the *cheap, on-Pi* signals are available during the drive (server analytics aren't — they compute after sync). The glance-while-driving set:
- **Current gear** (derived from speed÷RPM)
- **Live g-meter** — lateral + longitudinal g (the "what's the car doing" dial)
- **Road grade** (incline)
- **Safety alerts** ← see priority below

**2. Post-drive review screens** — the rich server-derived analytics, NOT live: spool/boost-onset maps, drive-to-drive thrust trends, corner-lean correlations, gear-contextualized datalogs. This is where the deep tuning story gets *visualized* for review at home.

## Safety-priority guidance (my lane — please honor in the visual hierarchy)
For the live instrument, these **must dominate** when they fire — they're engine-protection, not info. I'd reuse the **DTC severity taxonomy** we already built (🔴 STOP / 🟡 WATCH / 🟢 MINOR) so it's consistent across the product:
- 🔴 **Coolant ≥104 °C / 220 °F** — head-gasket-risk band on the 4G63. When this trips it should own the screen, not sit politely in a corner.
- 🔴 **Knock detected** (if ECMLink integration lands) — detonation is the engine-killer; loudest possible.
- 🟡 **Voltage brownout** / charging fault.
- 🟡 **Lean-under-load** event.
Normal-state gear/g/grade are 🟢 ambient readouts — calm until something escalates.

## Light sensor → display auto-dim (your call; I'll confirm the sensor side)
CIO specifically flagged this. From the sensor side: the TSL2591 gives lux at ~1–2 Hz (its 100–600 ms integration time caps the rate) — plenty for **day/night auto-dim** and tunnel/garage transitions. That's a genuine UX win for an in-car screen. The brightness curve + transition smoothing are all yours; I'm just confirming the data supports it.

## One hard constraint (carry it into any display design)
CIO directive: **the display is a CONSUMER — it reads from the one canonical data stream, never opens the hardware itself.** Our OBD K-line physically tolerates only one reader, so a display that tries to poll the bus directly would corrupt capture. Whatever you design, it subscribes to the dedicated reader's output. (Full rationale in the Atlas note §6.)

Happy to ground any specific value, threshold, or unit when you start mocking — same as the DTC viewer. This is genuinely fun territory; the g-meter + live gear coupled with the engine state is a view nobody's had on this car before.

— Spool
