# ADR — EDR Sensor Reader: bus-contract + versioned raw-sensor schema (Sprint 50 / V0.29.4)

| | |
|---|---|
| **Author** | Atlas (Architect) |
| **Date** | 2026-06-30 |
| **Status** | DRAFT — contract complete; **numeric defaults pending CIO sit-down** (see §7 Open Decisions) |
| **Feature** | F-113 (bus-contract) + F-114 (versioned raw-sensor schema); extends F-110 (EDR dedicated-reader bus, shipped V0.29.0) |
| **Gate** | Atlas EDR gate APPROVED 2026-06-30 (items 1–5); this ADR is the concrete DDL + framing the build leans on |
| **Refs** | `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md` · `docs/edr-sensors-wiring-reference.md` · `src/pi/bus/{sample,bus,persistence_subscriber}.py` · A-14, A-4 |
| **Hardware** | TSL2591 light @0x29 · ICM-20948 9-DoF IMU @0x69 (in-hand, wired/spec'd `95d496a`) |

## 0. Decision summary

Extend the shipped F-110 `SampleBus` to two I²C sensors as **purely additive** channels, persisted to **new Pi-local raw tables** authored under a **single versioned `src/common/` contract** (the A-4 anti-divergence gate). Ships **dark** behind per-sensor flags; reads **graceful-absent** so it builds + bench-tests with nothing wired and goes live when the CIO wires each sensor. Raw samples are **Pi-local this phase**; server sync + event-vault + vehicle-frame transforms are F-115. **The F-110 byte-identical `realtime_data` golden master is untouched by construction** — sensors use a separate subscriber and separate tables; no shared write path with `raw.obd.*`.

---

## 1. Bus-contract (F-113)

### 1.1 Topics (additive — never touch `raw.obd.*`)

The reader publishes on the existing `SampleBus` using the shipped `Sample` envelope (`sample.py`: `topic, source, value, unit, tsUtc, tsCapture, driveId, dataSource, seq`). `value` already supports `float | tuple[float, ...]`, so IMU vectors fit natively.

| Topic | `value` | `unit` | `source` | QoS |
|---|---|---|---|---|
| `raw.imu.accel` | `(x, y, z)` | `m/s^2` (gravity incl.) | `imu` | LOSSY |
| `raw.imu.gyro` | `(x, y, z)` | `rad/s` | `imu` | LOSSY |
| `raw.imu.mag` | `(x, y, z)` | `uT` (AK09916) | `imu` | LOSSY |
| `raw.imu.temp` | `float` | `degC` | `imu` | LOSSY |
| `raw.light.lux` | `float` (**None if saturated**) | `lux` | `light` | LOSSY |
| `raw.light.raw` | `(visible, infrared, full)` | `count` | `light` | LOSSY |

**Poll-correlation rule (the one contract Ralph must honor):** the IMU is read as **one burst per poll** (accel+gyro+mag+temp together), and all topics emitted from that poll carry the **same `seq`** (seq = poll index for this producer). The IMU persistence subscriber (§2.2) assembles **one `edr_imu_sample` row per `seq`**. Light is independent (its own `seq` stream).

### 1.2 Cadence + QoS/backpressure

- **QoS = LOSSY** on every sensor topic — `Subscription` drop-oldest on a full bounded queue, **producer never blocks** (the shipped semantics). Sensor sampling is lossy-OK; the OBD/sync path keeps its own LOSSLESS lane, unchanged.
- **Rates (PROPOSED defaults — CIO-tunable, §7-Q1/Q2):** IMU burst **50 Hz**; light **1 Hz**. Sample rate is **decoupled from persist rate** (§2.3): the reader may publish at full rate for a future high-rate display consumer while persistence writes at a lower, configured cadence.
- **Golden-master guarantee (the hard constraint):** sensor channels share **no code path** with `raw.obd.* → realtime_data`. The F-110 `PersistenceSubscriber` and its `realtime_data` INSERT are untouched; the byte-identical golden-master test holds **by construction**, not by re-verification. New sensor persistence is a *sibling* subscriber writing *sibling* tables.

---

## 2. Versioned raw-sensor schema (F-114) — the A-4 anti-divergence gate

### 2.1 Single-source contract

The DDL below is authored **once** in a new versioned module **`src/common/edr/sensor_schema.py`** (locked decision #3 — versioned `src/common/` contracts). The Pi creates its SQLite tables from it now; when server sync lands (F-115) the server MariaDB migration is **generated from the same module** — neither tier hand-writes its own DDL. This is precisely the gate that prevents the Pi↔server drift class (A-4). `schema_version` is a bare-`int` module constant (mirrors `power_watch.RECORD_SCHEMA_VERSION`) stamped into every row.

### 2.2 DDL (Pi SQLite; server DDL derives from the same contract at F-115)

```sql
CREATE TABLE IF NOT EXISTS edr_imu_sample (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc        TEXT    NOT NULL,          -- ISO-8601 UTC wall-clock (Sample.tsUtc) — the value that persists
    ts_capture    REAL    NOT NULL,          -- monotonic seconds (Sample.tsCapture) — for cross-channel alignment
    seq           INTEGER NOT NULL,          -- per-poll producer counter — gap/drop detection
    accel_x REAL, accel_y REAL, accel_z REAL,   -- m/s^2 (gravity included)
    gyro_x  REAL, gyro_y  REAL, gyro_z  REAL,   -- rad/s
    mag_x   REAL, mag_y   REAL, mag_z   REAL,   -- uT (AK09916 magnetometer)
    temp_c  REAL,                               -- IMU die temperature, degC
    drive_id      INTEGER,                    -- NULL when no active RUNNING drive (stamped EXPLICITLY — see §2.4)
    data_source   TEXT    NOT NULL DEFAULT 'real'
                  CHECK (data_source IN ('real','replay','physics_sim','fixture')),
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS edr_light_sample (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc        TEXT    NOT NULL,
    ts_capture    REAL    NOT NULL,
    seq           INTEGER NOT NULL,
    lux           REAL,                       -- NULL when the sensor saturates (honest — never inf/overflow)
    visible       INTEGER,                    -- raw channel counts (relative dimming, saturation check)
    infrared      INTEGER,
    full_spectrum INTEGER,
    gain          TEXT,                       -- 'low'|'med'|'high'|'max' — the reading's gain context
    integration_ms INTEGER,                   -- integration time at read
    drive_id      INTEGER,
    data_source   TEXT    NOT NULL DEFAULT 'real'
                  CHECK (data_source IN ('real','replay','physics_sim','fixture')),
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_edr_imu_sample_drive_id   ON edr_imu_sample(drive_id);
CREATE INDEX IF NOT EXISTS ix_edr_imu_sample_ts         ON edr_imu_sample(ts_utc);
CREATE INDEX IF NOT EXISTS ix_edr_light_sample_drive_id ON edr_light_sample(drive_id);
CREATE INDEX IF NOT EXISTS ix_edr_light_sample_ts       ON edr_light_sample(ts_utc);
```

Conventions match `realtime_data` (`database_schema.py`): `CREATE TABLE IF NOT EXISTS`, snake_case columns, the `data_source` CHECK contract (US-195/US-212), `INTEGER PRIMARY KEY AUTOINCREMENT`.

### 2.3 Persist rate decoupled from sample rate
The IMU persistence subscriber writes at a **configured persist cadence** (`pi.sensors.imu.persistHz`, PROPOSED default = the sample rate, i.e. no decimation — pending §7-Q1). Decimation, if chosen, happens at the persistence subscriber, not the producer — the bus still carries full-rate for any live display consumer.

### 2.4 `drive_id` = NULL-when-no-drive (ONE rule across the Pi)
Sensor rows stamp `drive_id` from `getCurrentDriveId()` **only when a drive is RUNNING**, else **NULL, stamped explicitly** — the same latch discipline as the A-9 gap-fence (US-388) and the DTC KOEO ruling. A sensor sample must never inherit a stale `_currentDriveId`. One NULL-latch rule, three consumers.

### 2.5 Migration shape
Forward-only. `CREATE TABLE IF NOT EXISTS` at startup (idempotent) via the `src/common/edr` schema module, plus the project's `ensure<Column>` ALTER pattern for later additive columns; `schema_version` bumps when the contract changes. **Sync: Pi-LOCAL ONLY this phase** — no server table is created and no sync path is wired; F-115 adds server persistence generated from the same contract with a downsample/event-window policy (so zero divergence by construction).

---

## 3. Graceful-absence contract (item 3)

- **Probe at init** — the reader pings each sensor's I²C address (a test read). **Absent → log once at WARN, publish NO samples for that channel, persist nothing.** A sensor that isn't wired produces *silence*, never a fabricated `0.0` / `null` sample a downstream consumer could mistake for a real zero-g / zero-lux reading (honest-instrument).
- **Optional presence STATE topic** — the reader publishes a retained STATE topic `state.sensor.imu` / `state.sensor.light` = `present|absent` so a future UI shows "sensor not installed" honestly (STATE = last-value retained, already in the bus). Not required for this phase; recommended.
- **Connect-when-wired** — on the next reader start (or a periodic re-probe, PROPOSED off for v1), the probe succeeds and the channel goes live with **no code change**. A flag flipped `true` before the sensor is physically present is **safe** — it takes the absent path, not a crash.
- **Saturation honesty (light)** — TSL2591 `.lux` returns overflow when saturated; the reader publishes `lux=None` (persist NULL) and still publishes raw counts. Never `inf`.

---

## 4. Dark-ship flags (item 4)

Per-sensor, under the bus master gate:

```
pi.bus.enabled              (existing)  — master; the whole SampleBus
  pi.sensors.imu.enabled    (NEW, default false)  — requires pi.bus.enabled
  pi.sensors.light.enabled  (NEW, default false)  — requires pi.bus.enabled
  pi.sensors.imu.sampleHz   (NEW, default 50)     — §7-Q1
  pi.sensors.imu.persistHz  (NEW, default = sampleHz)  — §2.3 / §7-Q1
  pi.sensors.light.sampleHz (NEW, default 1)
```

Ships dark: both `enabled` false. The CIO flips each **as he wires that sensor** — independent, deterministic connect-when-wired. A sensor whose flag is on but which probes absent → graceful-absence (§3), never a crash.

---

## 5. Rule-10 architecture.md section (item 5 — prose to add in-sprint)

Add under the EDR-bus section of `specs/architecture.md` (new subsection, e.g. **§10.8.2 "EDR sensor reader + raw-sensor persistence (Sprint 50 / V0.29.4)"**):

> **EDR sensor reader (F-113/F-114).** A dedicated reader polls two I²C sensors on bus-1 — ICM-20948 9-DoF IMU (@0x69) and TSL2591 light (@0x29) — and publishes them on the F-110 `SampleBus` as **additive** LOSSY topics (`raw.imu.{accel,gyro,mag,temp}`, `raw.light.{lux,raw}`), sharing one `seq` per IMU burst. The channels never touch the `raw.obd.* → realtime_data` path, so the F-110 byte-identical golden master is preserved by construction. A sibling persistence subscriber writes `edr_imu_sample` / `edr_light_sample`, whose DDL is authored once in the versioned `src/common/edr/sensor_schema.py` contract (A-4 anti-divergence: the future server table derives from the same module). Rows stamp `drive_id` only when a drive is RUNNING, else explicit NULL (the A-9/DTC-KOEO latch rule). The reader is **graceful-absent** (probe → silence, never fabricate) and ships **dark** behind `pi.sensors.{imu,light}.enabled` under `pi.bus.enabled`. Raw samples are **Pi-local this phase**; server sync + the event vault + vehicle-frame transforms are F-115. The reader stores **sensor-frame** values; vehicle-frame rotation + magnetometer hard/soft-iron calibration are deferred transforms (F-115), pending the recorded mounting axis-orientation.

Also add the schema as a worked example to `specs/ssot-design-pattern.md` (A-14 gate #4: SSOT for a cross-tier fact, authored once).

---

## 6. Scope boundaries (confirmed at gate)
- **F-112 (ECMLink datastream spike) OUT** — ECMLink not installed; hardware-gated.
- **F-115 (display surfaces, event-vault triggers, server sync, vehicle-frame transform, mag calibration) LATER** — this sprint is reader + Pi-local persistence only.

---

## 7. Open Decisions — need the CIO (these set the numbers, not the shape)

**Q1 — IMU sample + persist rate.** What is the EDR intent? (a) *everyday g-meter / compass* → ~10–25 Hz is plenty; (b) *hard-event / crash forensics* → ≥100–200 Hz **around events** (which really wants event-triggered high-rate bursts = F-115), with a low baseline otherwise. Proposed default: 50 Hz sample, persist = sample (no decimation). Your call on the baseline rate and whether we decimate persistence.

**Q2 — full IMU burst per poll, one row?** Read accel+gyro+mag+temp together each poll → one `edr_imu_sample` row (simplest, mag@50 Hz is cheap). OK, or do you want mag/temp at a slower separate cadence?

**Q3 — always-on, or drive-only?** A black-box arguably wants to capture an event even while parked (key-on, engine-off). Persist whenever the reader runs (drive_id NULL off-drive), or only during a RUNNING drive to bound volume? This is the main volume driver.

**Q4 — retention/rotation.** 50 Hz always-on IMU ≈ 4.3M rows/day on the Pi's SQLite. Do we (a) keep a rolling window (N days, purge older), (b) cap this phase's rate low and defer rotation to the F-115 event-vault, or (c) ring-buffer? What's N / the disk budget on the Pi?

**Q5 — axis orientation + mag calibration.** Confirm we store **raw sensor-frame** values now and defer the vehicle-frame rotation + mag hard/soft-iron cal to F-115 (needs the final mounted orientation — the wiring ref flagged "write down which pad-axis = forward/lateral/up"). Is that mounting decided yet, or still open? (Spool also has an owed axis-orientation input.)

**Q6 — presence STATE topic.** Include `state.sensor.{imu,light}=present|absent` now (cheap, enables an honest "not installed" UI later), or defer to F-115?

---

## 8. Build-story hooks (for Marcus's grooming — not binding)
1. `src/common/edr/sensor_schema.py` (contract + DDL + schema_version) + Pi table creation.
2. IMU reader (burst poll, per-quantity topics, one seq/poll, graceful-absent probe) behind `pi.sensors.imu.enabled`.
3. Light reader (lux + raw, saturation→None) behind `pi.sensors.light.enabled`.
4. Sensor persistence subscriber(s) → `edr_imu_sample` / `edr_light_sample`, drive_id-NULL-explicit, persist-cadence config.
5. Mock-sensor + absent-path tests (build + bench-test with nothing wired).
6. architecture.md §10.8.2 + ssot-design-pattern.md worked example (Rule-10 DoD, in-sprint).

**On the CIO's answers to §7, I finalize the rates/retention numbers and this ADR goes from DRAFT → the frozen contract Ralph builds against.**

— Atlas
