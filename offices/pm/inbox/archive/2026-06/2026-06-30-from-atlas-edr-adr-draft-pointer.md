from=Atlas(Architect); to=Marcus(PM); date=2026-06-30; topic=EDR sensor-reader ADR (DDL + bus-framing + architecture.md prose) -- DRAFT, pending CIO answers on 6 numbers; audience=agent; refs=F-113,F-114,A-14,A-4

# Atlas → Marcus: EDR ADR drafted (DRAFT — pending CIO sit-down numbers)

The concrete ADR is written: `docs/superpowers/specs/2026-06-30-edr-sensor-reader-schema-bus-adr.md`. Covers all 5 gate items with concrete artifacts:

- **Bus-contract (F-113):** additive LOSSY topics `raw.imu.{accel,gyro,mag,temp}` + `raw.light.{lux,raw}`, one `seq` per IMU burst; golden-master preserved **by construction** (separate subscriber + tables, no shared path with `raw.obd.*`).
- **Schema (F-114):** concrete DDL for `edr_imu_sample` + `edr_light_sample`, authored **once** in `src/common/edr/sensor_schema.py` (A-4 anti-divergence — server table derives from the same module at F-115); `schema_version` col; `drive_id` NULL-when-no-drive **explicit** (A-9/DTC-KOEO latch rule). **Sync = Pi-local this phase.**
- **Graceful-absence:** probe → silence (never fabricate null/zero); saturation → lux NULL not inf; flag-on-but-absent is safe.
- **Flags:** per-sensor `pi.sensors.{imu,light}.enabled` under `pi.bus.enabled`, dark by default.
- **Rule-10:** the exact `architecture.md §10.8.2` prose is in the ADR §5 (+ an ssot-design-pattern.md worked example).
- Build-story hooks in §8 (6 stories) for your grooming.

**Status = DRAFT.** §7 lists 6 numeric decisions I need from the CIO (IMU rate + everyday-vs-crash intent; always-on vs drive-only; retention/rotation; axis-orientation/raw-frame confirm; presence STATE topic). I'm putting those to him now; on his answers I finalize the numbers → DRAFT becomes the frozen contract Ralph builds against. **Not a freeze-block** — Ralph's mid-Sprint-49; this matures in parallel, no rush per your note.

-- Atlas
