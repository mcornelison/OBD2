# F-116: Foreign / non-target vehicle contamination — marker enum + ingest guard

| Field | Value |
|---|---|
| Priority | P2 (data-integrity; not engine-safety) |
| Status | pending |
| Category | data-integrity / ingest |
| Size | M |
| Parent Epic | E-002 — Data Pipeline / Server Analytics |
| Related PRD | Sprint 51 candidate (data-integrity/hygiene) |
| Dependencies | Atlas schema/design decision (enum semantics + guard design) |
| Created | 2026-06-30 |
| Source | Spool note `offices/pm/inbox/2026-06-30-from-spool-foreign-vehicle-contamination-drive33.md` |

## Description

The shared OBDLink LX auto-paired to the CIO's wife's **2014 Ford Explorer** and the Pi (on wall power) logged its engine-on as Eclipse **drive 33** (2026-07-01 02:21–02:23 UTC, 1,364 `realtime_data` rows), synced to `obd2db` tagged `data_source='real'` — so every real-data tuning query would ingest Explorer CAN data as if it were 4G63 telemetry. Caught by **9.09 samples/sec aggregate**, physically impossible on the Eclipse ISO 9141-2 K-line (~6.3/s ceiling, Session 26); it blended in because all 18 logged PIDs are generic OBD-II.

Spool applied interim mitigation (`drive_annotations` is_actual_drive=0 + provenance; `drive_summary.is_real=0`) but **could not honestly tag the underlying rows** — no CHECK enum value means "foreign/other vehicle" (`realtime_data.data_source` ∈ real/replay/physics_sim/fixture; `drive_summary.data_quality` ∈ full/attribution_anomaly). The 1,364 rows remain `data_source='real'` with a documented "exclude drive_id=33" note until a proper marker lands.

## Acceptance Criteria (to be groomed with Atlas)

- [ ] **Marker enum (Atlas = schema):** add a value — e.g. `data_source='foreign'` or `data_quality='foreign_vehicle'` — so contaminated rows are honestly excludable. Forward-only migration on both CHECK constraints.
- [ ] **Re-tag drive 33:** reclassify the 1,364 rows via Spool's provided SQL once the enum is decided (Spool runs it).
- [ ] **Ingest guard (Atlas = design):** prevent recurrence. Leading option = **bus-rate sanity check** (sustained aggregate > ~7 samples/sec is physically impossible on the Eclipse K-line → flag/quarantine as foreign; cheap, hardware-grounded, no vehicle cooperation). Device/pairing allowlist is an alternative. **⚠️ A VIN guard will NOT work** — the Eclipse ECU (MD326328) is Mode 09 silent (no VIN), the Explorer isn't, so VIN-presence is backwards.

## Cross-references

| Item | Relationship |
|---|---|
| A-9 / DriveDetector | Loosely tied — the detector opened a "drive" for a non-Eclipse vehicle; but this is cross-vehicle identity, not attribution-within-Eclipse (distinct concern) |
| V0.29.1 data-integrity sprint | Gap that sprint didn't cover |

## Notes

Spool + Atlas are the shapers (Spool = tuning/evidence + re-tag SQL, Atlas = schema/guard design). Sprint 51 data-integrity candidate. Ping Spool for the exact re-tag SQL once the enum value is decided.
