# `static_data` Disposition — KEEP, honest-empty

**Story:** US-456 (Sprint 55 / V0.29.9) · **Design item:** F-082 D-5 (CIO-decided) ·
**Decision date:** 2026-07-04 · **Decided by:** Ralph (Rex) executing the CIO-grounded D-5 disposition.

## Decision

The Pi-side `static_data` table is **KEPT**. It is **not** dropped, and no `TD-061`
is filed. The table stays **honest-empty** on the current vehicle, with the reason
recorded here and at the schema SSOT.

## Why the table cannot hold a VIN

`static_data` was designed to hold one-time OBD-II parameters keyed on the VIN
(`static_data.vin` is `NOT NULL`, a foreign key to `vehicle_info(vin)`). The VIN is
read over **OBD Mode 09**. The vehicle's current ECU (**MD326328**, 1997 board +
ECMLink V3) is **Mode-09-silent** — it does not answer VIN queries, so the VIN is
un-gettable over OBD. (Tuner knowledge: "Mode 09 silent — can't fingerprint via OBD.")

With no VIN there is no valid foreign key, so no honest `static_data` row can exist.

## Why KEEP over DROP

1. **The empty table is already honest, by design.** `StaticDataCollector`
   (`src/pi/obdii/vehicle/static_collector.py`) queries the VIN **first**; on a null
   (silent) response it raises `VinNotAvailableError` and writes **zero** rows — it
   never fabricates a placeholder VIN or a synthetic `vehicle_info` record. An empty
   table here is an *honest instrument*, consistent with the project's
   honest-availability / typed-NA discipline. Dropping is not required to be honest.

2. **Hardware-conditional, not dead.** The moment a Mode-09-capable ECU is connected
   (e.g. the prior stock ECU, or a future configuration that answers Mode 09), the
   existing collector populates the table with no code change. Dropping would
   permanently discard a working capability for a transient hardware fact.

3. **Blast radius / proportionality.** Dropping the table would cascade through an
   entire Pi subsystem — `StaticDataCollector`, the `vehicle/` package, ~15 public
   exports, the `pi.staticData.*` config keys, the `FK_static_data_vehicle`
   constraint, and the schema registration — far out of proportion to this size-S
   disposition story, with no data-integrity benefit (the table is already empty).

## Guardrail

`tests/pi/obdii/test_static_data_honest_empty.py` pins the load-bearing behaviour:
with a Mode-09-silent connection, `collectStaticData()` writes **0** rows to both
`static_data` and `vehicle_info`, and `shouldCollectStaticData()` declines. If a
future change makes the collector fabricate a placeholder VIN, that guard fails —
so "honest-empty" stays a *verified* property, not just this note.

## Re-evaluate if…

- A Mode-09-capable ECU is installed and the VIN becomes gettable (then the table
  populates naturally — no disposition change needed), **or**
- the `static_data` capability is intentionally retired project-wide (then revisit
  drop + file `TD-061` at that time).
