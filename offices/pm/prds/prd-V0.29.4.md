---
sprint: 50
version: V0.29.4
status: draft
createdAt: 2026-06-30
createdBy: Marcus (PM)
reviewTier: load-bearing
forksFrom: dev
epic: E-006, E-002, E-OPS
feature: F-113, F-114, F-101, F-064, F-079
theme: EDR sensor-reader (hardware-deferred) built to the FINAL ADR + quick sync/data-pipeline drain
validationMode: BENCH ONLY (CIO waived drive requirements; mock-sensor rigs + i2cdetect + DB-column checks + golden-master regression -- NO drive drills)
selectedStories: [US-408, US-409, US-410, US-411, US-412, US-413, US-414, US-415]
---

# PRD: Sprint 50 / V0.29.4 — EDR sensor-reader (hardware-deferred) + quick sync drain

| Field | Value |
|---|---|
| Sprint | 50 |
| Version | V0.29.4 (patch on the V0.29 chain) |
| Branch | `sprint/sprint50-V0.29.4` (forks from `dev`) |
| Theme | EDR sensor-reader built to the FINAL ADR + a quick sync/data-pipeline drain |
| Validation | **BENCH ONLY** — drive drills waived (V0.29 chain). Mock-sensor rigs, `i2cdetect`, DB-column checks, golden-master regression. |
| Story range | US-408 … US-415 (8 stories) |
| Design | **EDR ADR is FINAL** — `docs/superpowers/specs/2026-06-30-edr-sensor-reader-schema-bus-adr.md` (Atlas, CIO resolved all 6 numbers 2026-06-30). Concrete DDL, bus topics, rates, retention, flags all locked. This PRD's EDR stories build directly to it. |

## 1. Introduction / Overview

**(A) EDR sensor-reader — built hardware-deferred, to the FINAL ADR.** Extend the shipped F-110 `SampleBus` to two I²C sensors — **ICM-20948 9-DoF IMU** (`0x69`) and **TSL2591 light** (`0x29`) on bus-1 — as **purely additive** LOSSY channels, persisted to **new Pi-local raw tables** authored under a **single versioned `src/common/edr/sensor_schema.py` contract** (the A-4 anti-divergence gate). Ships **dark** behind per-sensor flags and reads **graceful-absent** — it builds and bench-tests with nothing wired and goes live when the CIO wires each sensor (tomorrow evening). The F-110 byte-identical `realtime_data` golden master is **untouched by construction** (separate subscriber, separate tables, no shared write path). Raw samples are **Pi-local this phase**; server sync + event-vault + vehicle-frame transforms are F-115.

**(B) Quick sync/data-pipeline drain (3 items).** The highest-value, quickest next-step fixes: mirror `power_log`/`startup_log` to the server, close the `drive_counter` sync gap, and fix the `sync_history` timezone mismatch.

*(The rest of the drain — idle-log-noise batch, clock-guard, LTFT card, mode badge — plus Spool's new foreign-vehicle contamination item (F-116) roll to a Sprint 51 data-integrity/hygiene sprint.)*

## 2. Goals

- Land the EDR reader + Pi-local persistence exactly to the FINAL ADR, so wiring the sensors is the only remaining step to live data.
- Preserve the F-110 `realtime_data` golden master by construction (additive, flag-gated, separate path).
- Bound Pi-local volume with a rolling-window retention purge (no new daemon).
- Close three server-sync/data-correctness gaps.
- Zero drive drills — all bench-verifiable.

## 3. User Stories

> **EDR stories build to the FINAL ADR** (`2026-06-30-edr-sensor-reader-schema-bus-adr.md`). Section refs below point to the exact contract; do not re-derive — implement to the ADR.

---

### US-408: EDR versioned schema contract + Pi tables (ADR §2)
**Description:** As the system, I want the raw-sensor tables defined once in a versioned `src/common/` contract, so Pi and (future) server never diverge.

**Acceptance Criteria:**
- [ ] New module `src/common/edr/sensor_schema.py` holds the **single-source DDL** for `edr_imu_sample` + `edr_light_sample` exactly per ADR §2.2, plus a bare-int `schema_version` constant (mirrors `power_watch.RECORD_SCHEMA_VERSION`).
- [ ] Pi creates both SQLite tables from that module at startup (`CREATE TABLE IF NOT EXISTS`, idempotent) — verified: schema introspection shows the ADR §2.2 columns + indexes + the `data_source` CHECK contract.
- [ ] `schema_version` is stamped into every row (default 1).
- [ ] Forward-only migration shape (ADR §2.5); no server table this phase (Pi-local only).
- [ ] `ruff check` passes on modified files.

**Downstream impact:** New Pi-local module + 2 tables; nothing existing altered. The future F-115 server DDL derives from this same module.

---

### US-409: EDR IMU + light readers — additive bus topics + graceful-absence (ADR §1, §3)
**Description:** As the system, I want a reader that polls both sensors and publishes them on the F-110 bus, reading-if-present and staying silent-if-absent.

**Acceptance Criteria:**
- [ ] **IMU:** one burst poll reads accel+gyro+mag+temp together, publishing `raw.imu.{accel,gyro,mag,temp}` LOSSY topics that **all carry the same `seq`** (seq = poll index) per ADR §1.1; rate `pi.sensors.imu.sampleHz` (default 50).
- [ ] **Light:** publishes `raw.light.lux` (+ `raw.light.raw` visible/infrared/full) at `pi.sensors.light.sampleHz` (default 1); **saturation → `lux=None`** (persist NULL, never `inf`) per ADR §3.
- [ ] **Graceful-absence (ADR §3):** probe each I²C address at init; **absent → log once at WARN, publish NO samples, fabricate nothing** (silence, never a `0.0`/`null` a consumer could read as real). A flag-on-but-absent sensor takes the absent path, never crashes.
- [ ] **Presence STATE topics:** publishes retained `state.sensor.imu` / `state.sensor.light` = `present|absent` (ADR §3) — the live wiring-debug confirmation.
- [ ] Additive only — no change to `raw.obd.*`; LOSSY QoS (drop-oldest, producer-never-blocks).
- [ ] Per-sensor flags `pi.sensors.{imu,light}.enabled`, each requiring `pi.bus.enabled`, **default false** (ADR §4).
- [ ] Unit tests cover present (mock-sensor) + absent paths for both sensors.
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Adds `raw.imu.*`/`raw.light.*`/`state.sensor.*` topics; no existing subscriber consumes them yet.

---

### US-410: EDR persistence subscriber + rolling-window retention (ADR §2.3, §2.4, §2.6)
**Description:** As the system, I want a sibling subscriber to persist sensor samples Pi-local at a decimated baseline, always-on, with a bounded retention window.

**Acceptance Criteria:**
- [ ] New sibling subscriber (modeled on `PersistenceSubscriber`, **separate from the OBD one**) drains `raw.imu.*`/`raw.light.*` and writes `edr_imu_sample`/`edr_light_sample`; **one IMU row per `seq`** (assembles the burst).
- [ ] **Persist cadence decoupled** from sample rate: IMU writes at `pi.sensors.imu.persistHz` (default 25, decimated from the 50 Hz bus) per ADR §2.3; light at 1 Hz.
- [ ] **Always-on capture (ADR §2.4):** persists whenever the reader runs (key-on incl. engine-off). `drive_id` stamped from `getCurrentDriveId()` **only when a drive is RUNNING**, else **explicit NULL** (the A-9/DTC-KOEO latch — never inherit a stale `_currentDriveId`).
- [ ] **Retention (ADR §2.6):** a periodic purge piggybacked on an existing maintenance tick (no new daemon) deletes rows older than `pi.sensors.retentionDays` (default 7) from both tables (`DELETE ... WHERE ts_utc < :cutoff`).
- [ ] Ships **dark** behind the per-sensor flags; both OFF ⇒ no writes; the OBD inline path byte-for-byte unchanged.
- [ ] Observability via existing `SubStats` (depth/dropped).
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Writes 2 new Pi-local tables; **no server/sync change** (F-115). `retentionDays` disk sizing confirmed vs Pi free space at deploy (~2.3 GB @ 7 days).

---

### US-411: EDR bench harness + golden-master regression + connect-when-wired drill
**Description:** As the developer, I need the EDR verifiable with no hardware and proof the OBD golden master is untouched.

**Acceptance Criteria:**
- [ ] Mock-sensor harness feeds synthetic IMU + light readings reader→bus→subscriber; rows land in both tables with correct shape + one-row-per-IMU-seq.
- [ ] **Absent-path test:** flags ON, no sensors → `state.sensor.*=absent`, zero rows, **no fabricated samples** (assert not a single row), no error.
- [ ] **Golden-master regression:** flags OFF (and ON, OBD-only) → `realtime_data` rows **byte-identical** to the pre-bus inline path (reuses the F-110 golden-master discipline).
- [ ] **Saturation test:** a saturating TSL2591 read persists `lux=NULL` + raw counts, never `inf`.
- [ ] Documented **connect-when-wired bench drill**: flip `pi.sensors.{imu,light}.enabled` on a wired Pi, confirm `i2cdetect -y 1` shows `29 36 69` + `state.sensor.*=present` + rows accumulate — the CIO's acceptance drill (run at wiring; not a sprint blocker).
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Test-only.

---

### US-412: Sync `power_log` + `startup_log` from Pi to server (F-101)
**Description:** As the CIO, I want the Pi's `power_log` + `startup_log` mirrored to the server, so power/boot history is queryable server-side.

**Acceptance Criteria:**
- [ ] Server tables `obd2db.power_log` + `obd2db.startup_log` exist (new migration); **deployed AND verified** via `INFORMATION_SCHEMA`.
- [ ] Pi sync coverage pushes both idempotently, catch-up on reconnect (follows the `battery_health_log` pattern).
- [ ] Post-sync, server rows match Pi rows (counts + spot-checked values).
- [ ] `power_log` volume strategy decided + documented at story time (raw-every-poll vs sampled).
- [ ] `ruff check` passes on modified files.

**Downstream impact:** 2 new server tables; B-076 sync-batch/FK conventions apply.

---

### US-413: `drive_counter` server-side sync gap fix (F-064)
**Description:** As the CIO, I want the server's `drive_counter` to track the Pi's (Pi at 10, server stale at 3).

**Acceptance Criteria:**
- [ ] Root cause stated (mirror writer not running vs not in sync set — `rg drive_counter src/pi/`).
- [ ] After fix + a sync cycle, `obd2db.drive_counter.last_drive_id` equals the Pi's value; idempotent.
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Sync coverage set (coordinate with US-412 if shared writer).

---

### US-414: `sync_history` timezone mismatch fix (F-079)
**Description:** As the CIO, I want `sync_history.started_at` + `completed_at` in one timezone, so the data is trustworthy.

**Acceptance Criteria:**
- [ ] The `sync_history` writer writes both columns in **UTC (canonical ISO-8601 per `specs/standards.md`)** — the current exact-5h CDT/UTC mismatch within a row is gone for new rows.
- [ ] Test asserts a written row's two timestamps are same-tz/consistent.
- [ ] `ruff check` passes on modified files.

**Downstream impact:** TD-027-class fix; timestamp-writer only.

---

### US-415: Sprint Documentation Sync (Rule-10 DoD)
**Description:** As the PM, I need docs to reflect the sprint.

**Acceptance Criteria:**
- [ ] `specs/architecture.md` gains **§10.8.2 "EDR sensor reader + raw-sensor persistence"** using the ADR §5 prose (in-sprint Rule-10).
- [ ] `specs/ssot-design-pattern.md` gains the EDR raw-sensor schema as the worked anti-divergence example (A-14 gate #4).
- [ ] `regression_manifest.json` reflects new/changed features (F-113/F-114 EDR; F-101/F-064 sync).
- [ ] Any new config keys (`pi.sensors.*`) documented in `CLAUDE.md`; no stale references.

**Downstream impact:** Docs only.

## 4. Functional Requirements

- FR-1: Raw-sensor DDL authored once in `src/common/edr/sensor_schema.py`; Pi tables created from it (ADR §2).
- FR-2: IMU burst-poll → `raw.imu.*` (shared seq) + light → `raw.light.*` on the F-110 bus, LOSSY, additive (ADR §1).
- FR-3: Graceful-absence — probe, silence-if-absent, never fabricate; presence STATE topics (ADR §3).
- FR-4: Sibling persistence at decimated baseline (`persistHz` 25), always-on, `drive_id` NULL-when-no-drive explicit, rolling-window retention (ADR §2).
- FR-5: Dark behind `pi.sensors.{imu,light}.enabled` under `pi.bus.enabled`; OFF ⇒ `realtime_data` byte-identical (ADR §4).
- FR-6: Server gains `power_log`+`startup_log`; `drive_counter` mirror fixed; `sync_history` single-timezone UTC.

## 5. Non-Goals (Out of Scope)

- **F-112 (ECMLink spike)** — out (not installed).
- **F-115** — server sync of raw samples, event vault, on-Pi triggers, display surfaces, vehicle-frame rotation + mag calibration, event-triggered high-rate (100–200 Hz) capture. Later phase.
- **Physically wiring the sensors** — CIO does it at his schedule; connect-when-wired drill (US-411) runs then.
- **Deferred to Sprint 51 (data-integrity/hygiene):** the idle-log-noise batch (F-077/078/058/079-adjacent), F-080 clock-guard, F-096 LTFT card, F-098 mode badge, F-061 (blocked on F-060), and **F-116 (Spool foreign-vehicle contamination marker + ingest guard)**.
- **No drive drills.**

## 6. Technical Considerations

- **The FINAL ADR is the contract.** EDR stories implement it section-by-section; the only deploy-time confirmation is `retentionDays` vs the Pi's free space.
- **Golden master by construction** — sensors share no code path with `raw.obd.* → realtime_data`; US-411 enforces with the existing regression.
- **`drive_id` NULL-latch** is one rule across three consumers (A-9 gap-fence, DTC KOEO, EDR) — stamp explicit NULL, never inherit `_currentDriveId`.
- **Hardware milestone:** CIO wires both sensors tomorrow evening (`i2cdetect 29/36/69` + CircuitPython smoke test); graceful-absence means the sprint builds/bench-tests regardless.
- Sprint 49 (carousel + DTC) is on `dev`, so nothing here conflicts.

## 7. Success Metrics

- EDR reader + persistence build + bench-pass with **no sensors wired**; `state.sensor.*=absent`, zero fabricated rows.
- `realtime_data` golden-master regression: **0 byte differences** flag-OFF and OBD-only.
- With sensors wired (CIO drill): `i2cdetect` shows `29 36 69`, `state.sensor.*=present`, rows accumulate at the baseline cadence, retention purge holds the window.
- Server `power_log`/`startup_log` populated post-sync; `drive_counter` matches Pi; `sync_history` single-timezone.

## 8. Open Questions

1. **(US-412)** `power_log` volume strategy — raw-every-poll vs sampled? Decide at story time.
2. **(Deploy)** `retentionDays` vs the Pi's actual free space — confirm at deploy (default 7 ≈ 2.3 GB; drop to 3 if tight).
3. **(Resize)** US-409 batches two readers (IMU + light) — accept as one story (Rule-5 similar-pattern) or split? Decide at `/resize-sprint`.

## Action Items (NOT sprint stories — ops/hardware)

- **AI-1:** CIO wires ICM-20948 + TSL2591 (tomorrow eve), records the mounting **axis-orientation map** (feeds F-115 vehicle-frame transform + Spool's owed axis input), runs `i2cdetect` + CircuitPython smoke test, then the US-411 connect-when-wired drill.
