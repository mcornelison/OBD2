from=Marcus(PM); to=Iris(UI/UX); date=2026-07-27; topic=design brief -- live driving cards (W-11) + unified alert layer + close your open polish items (pre-car full-UI push); audience=mixed; refs=W-11,DELTA-1,DELTA-2,F-121,US-478

# Design brief — the live-driving UI (the long pole before the Pi goes back in the car)

F-121 is COMPLETE + deployed (V0.29.16): render-truthfully carousel, live light feed, idle card, letterbox, and the DTC STOP-tier safety treatment (your §6d via Spool, US-484-b). Thank you — it renders true on the Pi now.

CIO's next goal: **the UI fully worked out before the Pi returns to the Eclipse.** He chose **you-design-first, then I groom**. The genuine Adafruit ICM-20948 #4554 arrived (US-478 will bring it up on the EDR bus → a `states/imu` file, mirroring the light bridge). That unblocks the live-motion UI you've had parked. Please design:

1. **W-11 live-instrument home card** — the *driving* twin of your idle card (same carousel home slot: parked→idle, driving→live). From the IMU `states/imu` feed (accel/gyro/mag): compass/heading, g-force, grade/pitch, gear-ish — your call on what earns the 480×320 glance. Honest-instrument: absent/stale IMU → fall back to the idle card, never fabricate motion.
2. **Unified alert layer (DELTA-1)** — the arbiter you + Atlas parked: one alert surface merging the DTC STOP takeover (live) with any live engine/motion alerts, so two sources can't fight for the screen. Atlas ruled this EDR-gated + wanted to gate the arbiter design — loop him early on the arbiter contract.
3. **Close your open polish items** — the ones you flagged: density/glanceability on the System Status card, the menu **long-press vs ⋮** decision (you leaned long-press-only), DTC detail polish, and anything else you consider unfinished. Make the shipped UI clean end-to-end.

## Grounding + gates
- **Data path**: `states/imu` lands via US-478 (Ralph). Live-card validation needs real IMU data → the board must be wired first (CIO AI-005) + US-478 built. So the live card designs can proceed now, but their build/validate sequences AFTER US-478.
- **Consumer-only**: display reads `states/imu`; the reader owns the sensor (Atlas DELTA-2, same as light).
- **Full-brightness-alarm rule** (Spool §6d ch.4) already lives in the STOP path — the unified alert layer must preserve it.

## Flow
Design + mockups → CIO reviews (he's back at the machine for this) → I groom into the live-cards sprint (which sequences after the US-478 IMU foundation). Loop Atlas early on the DELTA-1 arbiter contract. Ping me when there's something to review; no rush on my side — the IMU wiring + US-478 are the pacing items.

— Marcus
