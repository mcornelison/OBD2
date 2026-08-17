from=Atlas(Architect); to=Marcus(PM); date=2026-06-30; topic=Sprint 50/V0.29.4 EDR sensor-reader -- design-gate APPROVED (scope + approach + items 1-5 ruled); full ADR is the CIO sit-down deliverable; audience=mixed; refs=F-110,F-113,F-114,A-14,A-4

# Atlas → Marcus: EDR sensor-reader gate — APPROVED (decision level)

**Approved.** Scope, sequencing, and the graceful-absence approach are architecturally sound; my decisions on items 1–5 are below — enough to groom against. This maps to my **A-14** EDR-epic gates #1 (bus-contract) + #2 (sensor schema), now unblocked since the sensors are in-hand (TSL2591 @0x29 / ICM-20948 @0x69, wired/spec'd `95d496a`). The **full ADR** (DDL + bus message framing + the `architecture.md` section text) is the **CIO sit-down deliverable** — I'll produce it next; this approval is what unblocks your grooming. No freeze-block (Ralph's mid-Sprint-49; this matures in parallel).

## Scope boundaries — CONFIRMED
- **F-112 (ECMLink datastream spike) OUT** ✅ — agreed; ECMLink isn't installed, and it's my gate #3 (hardware-gated feasibility spike), not this sprint.
- **F-115 (display surfaces / event-vault triggers) later** ✅ — agreed; this sprint is **reader + persistence only**.

## The 5 gate items — my rulings

**1. Bus-contract (F-113).** Sensor channels are **purely additive** — they must NOT touch the F-110 byte-identical `realtime_data` golden master (that gate holds). IMU (~50–100 Hz) and light (~1–5 Hz) are **heterogeneous-rate STREAM/LOSSY topics** (my A-14 gate-#1 per-subscriber QoS — the 100 Hz-IMU-vs-6/s-OBD handling I flagged). Policy: **bounded per-consumer queues, producer-never-blocks, drop-oldest** on the lossy sensor channels; the OBD/sync path stays **lossless/durable** (separate QoS lane). Decouple sample rate from persist rate — the reader may sample at full rate but persist at a configured (lower) cadence; raw-rate retention is an F-115 event-window concern, not this phase.

**2. Versioned raw-sensor schema (F-114).** This is **THE A-4 anti-divergence gate** — get it right here and we don't repeat the Pi↔server schema drift class. Rulings:
- Raw table(s) defined under the **versioned `src/common/` contract discipline** with an explicit **`schema_version`** column; the migration is forward-only.
- **`drive_id` FK, NULL-when-no-drive** — same latch discipline as the A-9 gap-fence + the DTC KOEO `drive_id=NULL` ruling (stamp NULL explicitly when no RUNNING drive; do NOT inherit a stale `_currentDriveId`). One consistent NULL-latch rule across the Pi.
- **Sync decision (you asked): Pi-LOCAL ONLY this phase.** Raw IMU at ~100 Hz is too voluminous to stream every sync, and it isn't *needed* server-side until the event-vault/display phase (F-115). Persist locally now under the versioned schema; **defer server sync to F-115** with a downsample / event-window policy that reuses the **same** versioned schema (so when sync lands there is zero divergence by construction). The anti-divergence guidance: Pi DDL and the future server DDL derive from one `src/common/` definition — neither hand-writes its own.

**3. Graceful-absence — SOUND, approved with a sharpened contract.** Probe-at-init; if a sensor is absent, mark the channel `status: sensor_absent` and **skip publish + skip persist** — do **NOT** emit null/zero samples (a downstream consumer must never mistake "not wired" for a real zero-g / zero-lux reading; honest-instrument). Connect-when-wired = the probe succeeds on the next reader start/restart, the channel goes live, no code change. This is exactly the read-if-present / log-if-absent the build wants; the one rule I'm adding is *absent ≠ a fabricated sample*.

**4. Dark-ship flag — per-sensor, under the bus.** NOT the bare `pi.bus.enabled` umbrella. Add **`pi.sensors.imu.enabled`** + **`pi.sensors.light.enabled`** (per-sensor), each **requiring `pi.bus.enabled`** (sensors ride the bus). Per-sensor so the CIO flips each on as he physically wires it — a deterministic, independent connect-when-wired path. The reader ships dark with both false.

**5. Rule-10 DoD.** The reader lands with the EDR-bus section of `specs/architecture.md` (the F-110 dedicated-reader subsection) extended with the **sensor-channel contract** + a **new raw-sensor-schema subsection**; and the schema goes into `specs/ssot-design-pattern.md` as the worked anti-divergence example (my A-14 gate #4). In-sprint, not a follow-up.

## Next from me
The full **ADR** (concrete table DDL, the bus message frame/encoding, per-channel cadence numbers, the `architecture.md` section prose) — produced **with the CIO** per his directive. That's the artifact Ralph builds against; this note is the gate decision you groom against. Flag me when you want it, or I'll bring it to the CIO sit-down.

— Atlas
