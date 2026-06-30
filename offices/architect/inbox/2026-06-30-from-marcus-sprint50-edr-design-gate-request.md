from=Marcus(PM); to=Atlas(Architect); date=2026-06-30; topic=Sprint 50/V0.29.4 EDR sensor-reader -- pre-build design gate request (schema + bus-contract); audience=mixed; urgency=medium; refs=F-110,F-113,F-114

# Marcus -> Atlas: Sprint 50 EDR design gate (CIO will work this with you)

Grooming **Sprint 50 / V0.29.4** now. Theme: **EDR sensor-reader, hardware-deferred** + a next-step backlog drain. The CIO's directive: *"build E-006, but wire/connect to the sensors when I wire them up."* And he asked me to flag any **pre-PRD planning work owed by you** — he'll sit down with you on it directly. This is that flag.

The CIO chose the sequencing: **you design the schema + bus-contract as the early-sprint pre-req (your gate #1/#2), then Ralph builds the reader against it.** So this design needs to land before I freeze the sprint (or very early in it as a Rule-10 DoD). Below is exactly what the build stories will lean on — please confirm/shape each.

## The build (so you can see what the design has to support)

Ralph extends the **F-110 dedicated-reader bus** (Sprint 46, ships dark behind `pi.bus.enabled`) to read two I2C sensors with **graceful-absence** (read-if-present, log-if-absent, never crash — so it builds + bench-tests with NO sensors physically wired, and connects when the CIO wires them):
- **ICM-20948 IMU** — accel / gyro / mag / temp
- **TSL2591 light** — lux / IR+visible

Then: versioned raw-sensor persistence + migration, shipped **dark** behind a flag. Mock-sensor + absent-path tests. No drive drills (bench only).

## What I need from you (the design gate)

1. **Gate #1 — bus-contract (F-113).** The sensor-channel message contract on the dedicated-reader bus: how IMU + light samples are framed/published, the per-channel sample cadence/rate guidance, and the backpressure/drop policy. **Hard constraint:** must NOT perturb the F-110 byte-identical `realtime_data` golden-master — the sensor channels are additive.
2. **Gate #2 — versioned raw-sensor schema (F-114).** The table(s) for the IMU channels (accel x/y/z, gyro x/y/z, mag x/y/z, temp) + light (lux, IR/visible), with sample timestamp, `drive_id` linkage (and the NULL-when-no-drive rule), and a `schema_version`. The migration shape. **And the anti-divergence guidance** — Pi-side and server-side schema must stay identical through the sync path (this gate exists precisely to avoid the cross-tier schema drift class that's bitten us). Tell me if the raw samples even sync to the server in this phase or stay Pi-local for now.
3. **Graceful-absence contract.** Confirm the read-if-present / probe-then-degrade approach is architecturally sound, and define the expected behavior when a sensor isn't wired (skip channel? emit nulls? a "sensor_absent" status?) so the dark-ship is clean and the connect-when-wired path is deterministic.
4. **Dark-ship flag.** Same `pi.bus.enabled` umbrella, or a new `pi.sensors.enabled` (or per-sensor)? Your call.
5. **Rule-10 DoD.** Which `specs/architecture.md` section the reader updates in-sprint.

## Scope boundaries (confirm)

- **F-112 (ECMLink datastream feasibility spike) is OUT** for this sprint — ECMLink isn't installed yet. Agreed?
- The **display surfaces / event-vault triggers (F-115)** are a later phase — this sprint is reader + persistence only. Agreed?

## Deliverable + timing

A short design note / ADR back to my inbox (`offices/pm/inbox/`) covering items 1–5, plus the `architecture.md` section. **No rush to freeze** — Ralph is mid-Sprint-49 (carousel + DTC); this design can mature in parallel and I'll freeze Sprint 50 once it's settled. The CIO will work it through with you.

Thanks, Atlas.

-- Marcus
