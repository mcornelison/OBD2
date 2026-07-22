from=Marcus(PM); to=Rex(Dev); date=2026-07-22; topic=BL-023 RESOLVED -- US-483 unblocked, split to 483-a/b, build the REAL light feed; audience=agent; refs=US-483-a,US-483-b,BL-023

# US-483 unblocked — the sensor is LIVE, build it for real

Good refusal on BL-023 (didn't guess a safety-adjacent contract). Resolution from the CIO: **the TSL2591 is wired and I2C-addressable @0x29** (PM verified on the Pi — `i2cdetect` shows `29`, MAX17048 at `36`). It was only *config*-dark, not hardware-absent. So we build the real feed, not a fixed fallback.

**US-483 is split into two sprint-ready stories** (in `sprint.json`):
- **US-483-a** — connect-when-wired: flip `pi.bus.enabled=true` + `pi.sensors.light.enabled=true`, then bridge the existing `raw.light.lux` (already published by `sensor_reader.py`) → a `states/light` file at `/run/eclipse-obd/states/light` (`{lux, ts}`), **mirroring the states/ pattern you just built in US-480-a**. Atlas's seam is a heads-up-confirm, not a blocking gate (he approved the pure-consumer pattern; CIO directs build).
- **US-483-b** — the display brightness consumer with a **grounded, parameterized** curve. All values are CONFIG KEYS, not hardcoded (CIO's hard requirement): `luxMin=3.0`, `luxFull=1000`, `minLevel=0.15`, `alarmFloorLevel=0.40` (never dim a live STOP below legible), `defaultLevel=0.70`, `luxStaleSec=10`, `curve=logarithmic`. Grounded in the Adafruit TSL2591 datasheet + standard illuminance references (civil-twilight ~3.4 lux, overcast day ~1000 lux). Iris owns curve tuning — that's why they're params.

Full DoD/validation in the story contracts. Graceful-absence still holds (a dead IMU must not block the light feed — US-409).

**US-484 stays blocked** (BL-024) — it needs Atlas (`--text-primary` token) + Spool (`--critical-red` safety value); the CIO is getting those rulings. Don't attempt US-484 until they land. The 7 already-complete stories stay complete (I restored their state after regenerating the contract for the split).

— Marcus
