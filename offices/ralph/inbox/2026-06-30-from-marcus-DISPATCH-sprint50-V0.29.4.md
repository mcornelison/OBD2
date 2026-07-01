from=Marcus(PM); to=Rex(Dev); date=2026-06-30; topic=DISPATCH Sprint 50/V0.29.4 -- EDR sensor-reader (hardware-deferred, to FINAL ADR) + quick sync drain (bench-only, 8 stories); audience=agent; urgency=high; refs=US-408,US-409,US-410,US-411,US-412,US-413,US-414,US-415

# Marcus -> Rex: Sprint 50 / V0.29.4 DISPATCHED

Branch **`sprint/sprint50-V0.29.4`** forked from `dev`, pushed, upstream set; checkout is on it. **8 stories.** Builds on the shipped F-110 `SampleBus` (V0.29.0).

## THE contract to build against
**`docs/superpowers/specs/2026-06-30-edr-sensor-reader-schema-bus-adr.md` (FINAL).** The EDR stories (US-408..411) implement it **section-by-section — do NOT re-derive**. Concrete DDL (§2.2), bus topics (§1.1), rates (50/25/1 Hz), always-on capture (§2.4), 7-day rolling retention (§2.6), presence STATE topics (§3), per-sensor flags (§4), Rule-10 prose (§5) are all in it.

## Build order
**EDR first (sequential — each builds on the last):**
1. **US-408 schema contract** -- **start here.** `src/common/edr/sensor_schema.py` single-source DDL for `edr_imu_sample` + `edr_light_sample` (ADR §2.2) + `schema_version` + Pi table creation. The foundation everything writes to.
2. **US-409 IMU + light readers** (deps 408) -- **the heaviest story (L, PM-signed-off).** Build **IMU first, then light on the same seams.** Additive `raw.imu.*`/`raw.light.*` LOSSY topics (one shared `seq` per IMU burst), graceful-absence (**probe -> silence, NEVER fabricate a 0.0/null**), presence STATE `state.sensor.{imu,light}`, per-sensor flags. **If you find yourself compressing, flag it and I'll split it 409-a/-b.**
3. **US-410 persistence + retention** (deps 408,409) -- sibling subscriber (separate from the OBD `PersistenceSubscriber`) -> the EDR tables at `persistHz` (25 Hz decimated), **`drive_id` explicit NULL when no RUNNING drive** (the A-9/DTC-KOEO latch -- never inherit a stale `_currentDriveId`), always-on, rolling-window purge on an existing maintenance tick (no new daemon).
4. **US-411 bench harness + golden-master** (deps 408-410) -- mock-sensor harness + absent-path + **the F-110 `realtime_data` byte-identical golden-master regression** (it holds by construction -- separate subscriber/tables -- US-411 proves it) + saturation test + the documented connect-when-wired drill.

**Sync drain (independent, any order):**
5. **US-412** sync `power_log` + `startup_log` -> server (2 new server tables + migration + coverage).
6. **US-413** `drive_counter` server sync gap fix (root-cause first: `rg drive_counter src/pi/`).
7. **US-414** `sync_history` timezone fix (both columns UTC ISO-8601; kills the exact-5h mismatch).

**Last:**
8. **US-415 doc-sync** -- `architecture.md` §10.8.2 (ADR §5 prose) + `ssot-design-pattern.md` worked example + `regression_manifest` (F-113/114/101/064).

## Hardware note (does NOT block you)
CIO wires the ICM-20948 + TSL2591 **tomorrow evening**. **Graceful-absence means you build + bench-test the whole EDR path with NOTHING wired** (mock-sensor + absent-path). The connect-when-wired drill (US-411) is the CIO's acceptance step at wiring, not a sprint blocker. A flag-on-but-absent sensor MUST take the absent path, never crash.

## Validation = BENCH ONLY (drive drills waived)
Mock-sensor rigs, `i2cdetect` (at wiring), DB-column checks, the golden-master regression, fixture tests. NO drive drills.

## Notes
- Commit to THIS branch (shared-checkout: commit-immediately; if `.git/index.lock` blocks you, it's likely the recurring stale-lock (TD-057) -- wait/retry, never force, escalate if >a few min).
- The golden-master (`realtime_data` byte-identical) is the hard constraint -- sensors share NO code path with `raw.obd.*`.

CIO launches `ralph.sh` from his shell.

-- Marcus
