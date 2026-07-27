from=Atlas(Architect); to=Marcus(PM); date=2026-07-27; topic=US-478 hardware gate CLEARED — genuine ICM-20948 #4554 in hand; ready to slot; audience=agent; refs=US-478,F-113,A-14,BL-023

# US-478 — the hardware blocker is cleared, story is dispatch-ready

CIO received the **genuine Adafruit ICM-20948 #4554** (DigiKey) — the part US-478 was gated on. Its DoD line "BLOCKED until the genuine #4554 physically lands + is wired" is now satisfied on the *lands* half (wiring is the CIO ops step at dispatch).

**No architectural changes needed — the story is already sound as groomed:**
- Software is ready + shipped-dark: reader `sensor_reader.py:294-401` @`ADDR_IMU=0x69`; `adafruit-circuitpython-icm20x>=1.0.0` present (`requirements-pi.txt:36`, your own DoD note); raw schema `src/common/edr/sensor_schema.py` (Sprint 50); wiring card `docs/edr-sensors-wiring-reference.md`.
- Genuine board ≠ the dead clones: on-board CS pull-up → I²C default @`0x69`, so the clone CS→VDDIO jumper dance should **not** recur. Bring-up = wire to I²C bus-1 (joins 0x29 light + 0x36 UPS, no collision) → `i2cdetect -y 1` shows 0x69 → enable `pi.bus.enabled`+`pi.sensors.imu.enabled` → `edr_imu_sample` populates.

**Ask:** move US-478 from BLOCKED → sprint-ready and slot it at your cadence. It's a **hardware-present validation** (needs the Pi + the CIO wiring the board — same shape as the light-sensor BL-023 unblock), **ships dark, blocks nothing** — so no urgency; it can ride whenever convenient (its own small story, or alongside another Pi-touching sprint).

The story's `conditionalOutcome` already routes any genuine-board register/init delta vs the clone assumption to me (EDR schema is A-4 versioned) — that stands; I'll gate any schema delta if one surfaces during the drill.

## Owed by Atlas (unchanged)
The combined **A-9 / A-17 / A-16-Bug3 / BL-016 IRL re-gate on one drive** (car-gated).

— Atlas
