# Gap — EDR sensor-reader: missing deploy deps + ImportError masked as sensor-absent

**By:** Atlas · **Date:** 2026-07-02 · **Found:** on-Pi, first live sensor bring-up (CIO wired TSL2591 + ICM-20948).
**Severity:** Med (a shipped feature that couldn't work on any hardware until fixed). A-16 / US-409 family.

## What happened
CIO wired the two EDR sensors + I enabled `pi.bus.enabled` + `pi.sensors.{light,imu}.enabled`. The reader started but reported BOTH sensors absent — **not** because of hardware, but:
```
WARNING sensor_reader | probe | light sensor absent (No module named 'adafruit_tsl2591') -- publishing silence (state=absent)
WARNING sensor_reader | probe | imu   sensor absent (No module named 'adafruit_icm20x') -- publishing silence (state=absent)
```
`src/pi/sensors/sensor_reader.py` lazy-imports `adafruit_tsl2591` / `adafruit_icm20x`, but **those libs were never in `requirements-pi.txt`** (only `adafruit-blinka` + the rgb-display driver were). So a deployed reader can never read the wired hardware.

## Two distinct defects

**1. DEPLOY DEP GAP (fixed).** The reader's driver deps were missing from `requirements-pi.txt` → a clean deploy ships a reader that can't work. **Fixed:** added `adafruit-circuitpython-tsl2591` + `adafruit-circuitpython-icm20x` to `requirements-pi.txt` (committed). After a live `pip install` of both, the light sensor read end-to-end (`edr_light_sample` rows at 1 Hz, "light sensor present -- reader armed"; IMU then correctly "absent (No I2C device at 0x69)"). Same A-16 class as the display kiosk deps — a shipped feature whose deploy was incomplete, only visible on hardware.

**2. HONEST-INSTRUMENT MASKING (open — US-409 design gap, route to Ralph/Iris).** The reader's graceful-absence catches an **`ImportError` (missing DRIVER = a deploy/config bug)** and reports it identically to a **physically-absent SENSOR (no I2C ACK)** — both become a quiet `state=absent`. That **masks a real deploy defect as "no sensor wired."** My ADR §3 graceful-absence was for *hardware* absence (probe → no ACK), not a missing driver. Fix: the probe should **distinguish** (a) driver/import failure → a LOUD `ERROR` "sensor driver not installed (deploy/config bug)", from (b) I2C-no-response → the quiet `sensor_absent` honest state. A missing dependency must not look the same as absent hardware.

## Routing
- Dep fix committed to `requirements-pi.txt`.
- Defect 2 (ImportError-vs-absent distinction) → PM/Ralph as a US-409 follow-up (honest-instrument).
- Note: sensors currently ENABLED on the Pi as a **test** (config not committed — sensors not in permanent locations; first live `pi.bus.enabled`, whose byte-identical `realtime_data` golden-master confirms on the next real drive).

— Atlas
