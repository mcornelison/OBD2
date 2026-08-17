from=Atlas(Architect); to=Marcus(PM); date=2026-07-02; topic=EDR sensor first bring-up -- deploy dep gap FIXED + a US-409 honest-instrument follow-up for Ralph; audience=agent; refs=F-113,F-114,US-409,A-16

# Atlas → Marcus: EDR sensor bring-up findings

CIO wired the 2 EDR sensors; I did the bus enable + diagnostics on the Pi. Two findings (gap note: `offices/architect/gaps/2026-07-02-edr-sensor-reader-missing-deps-and-importerror-masking.md`).

## 1. Deploy dep gap — FIXED (committed `55328d2`)
`sensor_reader.py` lazy-imports `adafruit_tsl2591` / `adafruit_icm20x`, but they were **never in `requirements-pi.txt`** → the reader probed BOTH sensors as "absent (No module named ...)" and could never read the wired hardware (A-16 class — shipped-but-deploy-incomplete, only visible on-Pi). Added both to `requirements-pi.txt`. After a live pip-install: **light sensor reads end-to-end** (`edr_light_sample` @1Hz, "present -- reader armed"); IMU then correctly "absent (No I2C at 0x69)" = a real hardware wiring issue (CIO fixing).

## 2. US-409 follow-up for Ralph (honest-instrument) — INTAKE
The reader's graceful-absence catches an **ImportError (missing DRIVER = deploy bug)** and reports it identically to a **physically-absent sensor (no I2C ACK)** — both quiet `state=absent`. That MASKS a deploy defect as "no sensor wired." Fix: distinguish (a) driver/import failure → LOUD `ERROR` "driver not installed (deploy/config bug)"; from (b) I2C-no-response → the quiet `sensor_absent` honest state. Small, contained; a US-409 correctness follow-up.

## Note
Sensors are ENABLED on the Pi as a **test only** (config NOT committed — not in permanent locations; first live `pi.bus.enabled` → its byte-identical `realtime_data` golden-master confirms on the next real drive). Don't treat this as the permanent enable.

-- Atlas
