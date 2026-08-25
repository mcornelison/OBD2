# EDR connect-when-wired bench drill (CIO acceptance)

**Feature:** F-113 / F-114 (EDR sensor reader + Pi-local raw-sensor persistence)
**Ships:** V0.29.4 (Sprint 50), **dark** behind per-sensor flags.
**ADR:** `$FLEET_SHARE/knowledge/superpowers/specs/2026-06-30-edr-sensor-reader-schema-bus-adr.md`
**Wiring:** `docs/edr-sensors-wiring-reference.md`
**Story:** US-411 (bench harness + golden-master regression + this drill)

The EDR sensor path is built, unit-tested, and shipped **dark** (every flag
defaults `false`). No hardware is needed to build or bench-test it — the mock
harness in `tests/pi/sensors/test_edr_end_to_end.py` exercises the full
reader → bus → subscriber pipeline with synthetic devices. This doc is the
one manual step: **flip the flags on a wired Pi and confirm live data**. It is
the connect-when-wired acceptance the CIO runs once each sensor is physically
attached — independently per sensor.

Hardware (I²C bus-1):

| Sensor | I²C addr | Topic prefix | Flag |
|---|---|---|---|
| TSL2591 light | `0x29` | `raw.light.*` | `pi.sensors.light.enabled` |
| ICM-20948 9-DoF IMU | `0x69` | `raw.imu.*` | `pi.sensors.imu.enabled` |
| MAX17048 UPS fuel gauge | `0x36` | (existing UPS path) | (existing) |

---

## Step 1 — wire the sensor(s)

Attach the sensor to I²C bus-1 per `docs/edr-sensors-wiring-reference.md`
(3V3 / GND / SDA / SCL). You can wire one sensor and go live on it alone — the
flags are independent.

## Step 2 — confirm the bus sees the address (`i2cdetect`)

```bash
ssh chi-eclipse-01 "i2cdetect -y 1"
```

Expect the wired addresses to appear. With both EDR sensors + the UPS present:

```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
20: -- -- -- -- -- -- -- -- -- 29 -- -- -- -- -- --
30: -- -- -- -- -- -- 36 -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- 69 -- -- -- -- -- --
```

`29` = TSL2591 (light), `36` = MAX17048 (UPS), `69` = ICM-20948 (IMU). If an
address is missing, the sensor isn't seen on the bus — fix the wiring before
flipping the flag (a flag-on-but-absent sensor is **safe** — it takes the
graceful-absent path, publishes `state.sensor.*=absent`, and writes nothing —
but it won't give you live data).

## Step 3 — flip the flags in `config.json`

The bus master gate must be on, plus the per-sensor flag for each wired sensor:

```json
{
  "pi": {
    "bus": { "enabled": true },
    "sensors": {
      "imu":   { "enabled": true,  "sampleHz": 50, "persistHz": 25 },
      "light": { "enabled": true,  "sampleHz": 1 },
      "retentionDays": 7
    }
  }
}
```

Enable only the sensor(s) you wired. Then validate:

```bash
python validate_config.py
```

## Step 4 — restart + confirm presence STATE = present

Restart the Pi data service (or `python src/pi/main.py`). The reader probes each
I²C address at startup and publishes a **retained** presence STATE:

- probe **succeeds** → `state.sensor.imu` / `state.sensor.light` = **present**,
  poll loop armed at `sampleHz`.
- probe **fails** (absent / off-Pi) → `state.sensor.* = absent`, **no** samples,
  **no** fabricated `0.0` — silence, logged once at WARN.

The presence STATE is the fastest live confirmation the probe detected each
sensor (grep the startup log for `sensor present -- reader armed`, or watch the
STATE topic on the bus).

## Step 5 — confirm rows accumulate

Persistence is **always-on** (key-on, incl. engine-off — true black-box), at the
decimated baseline (`persistHz`, IMU default 25 Hz; light 1 Hz). Query the Pi DB:

```bash
ssh chi-eclipse-01 "sqlite3 <pi-db-path> \
  'SELECT COUNT(*), MAX(ts_utc) FROM edr_imu_sample;   \
   SELECT COUNT(*), MAX(ts_utc) FROM edr_light_sample;'"
```

Expect the counts to climb over a few seconds and `data_source = 'real'`.
`drive_id` is **NULL** unless a drive is RUNNING (the A-9 / DTC-KOEO latch — a
parked key-on capture is NULL, never a stale drive id). A saturated light read
persists `lux = NULL` (raw counts kept), never `inf`.

## Step 6 — confirm the retention window vs free space (deploy-time)

The always-on IMU baseline is ~325 MB/day (~2.3 GB for the default 7-day
window). Confirm `pi.sensors.retentionDays` against the Pi's actual free space
(`df -h`); a 64 GB+ card absorbs 7 days easily — drop to 3 days (~1 GB) if tight.
The rolling-window purge deletes rows older than `retentionDays` from both tables
automatically (piggybacked on the subscriber's own drain thread — no new daemon).

---

## Pass criteria

1. `i2cdetect -y 1` shows the wired address(es) — `29` and/or `69` (`36` = UPS).
2. `state.sensor.{imu,light}` = `present` for each enabled+wired sensor.
3. `edr_imu_sample` / `edr_light_sample` row counts climb after restart.
4. Flags off → zero EDR rows and `realtime_data` unchanged (golden master,
   proven by construction + `tests/pi/sensors/test_edr_end_to_end.py` and
   `tests/pi/bus/test_persistence_golden_master.py`).

If a flag is on but the sensor is unwired, the pass criteria for that sensor are
the **absent** path: `state.sensor.* = absent`, zero rows, no error — go back to
Step 1.
