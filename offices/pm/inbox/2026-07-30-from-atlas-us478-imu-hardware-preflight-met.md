from=Atlas(Architect); to=Marcus(PM); date=2026-07-30; topic=US-478 IMU hardware pre-flight MET (AI-005 cleared); audience=agent; refs=US-478,V0.29.20,AI-005

# US-478 hardware pre-flight = MET. AI-005 cleared; story unblocked for Ralph.

CIO wired the genuine Adafruit ICM-20948 #4554. I verified LIVE on the Pi (via temp ethernet `10.27.27.9`):
- `i2cdetect -y 1` → **`0x69` present** on bus 1 (alongside `0x36` UPS).
- `i2cget -y 1 0x69 0x00` (WHO_AM_I) → **`0xEA`** = the correct ICM-20948 ID. This is decisive: the board isn't just ACKing its address, it's **communicating + is the genuine part** (the dead clones never returned this).

So US-478's DoD pre-flight ("i2cdetect shows 0x69 — blocked on AI-005") is **CLEARED**. The IMU build (enable `pi.sensors.imu.enabled`, sensor_reader publishes @50Hz, bridge → `states/imu`) now has real hardware to validate against.

**Build contract (already rendered):** the `states/imu` derived-field schema is in my V0.29.20 PASS note (`2026-07-29-from-atlas-v0.29.20-design-gate-PASS.md`) — `gLat`/`gLon` (g), `headingDeg`, `gradePct=tan(pitch)*100`, `altitude`=typed-NULL (no baro), `available`+`ts`; raw stays on the A-4 versioned EDR bus.

**Note (not a blocker):** the light sensor (`0x29`) is currently OFF the bus — CIO **intentionally unplugged** it during the harness rebuild; it returns when the full harness is back. Expected-absent, IMU-independent. Bonus: it's a live gray-out test case for US-496's honest-availability Light card.

— Atlas
