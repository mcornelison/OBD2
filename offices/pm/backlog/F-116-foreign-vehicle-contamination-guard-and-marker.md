# F-116: Foreign / non-target vehicle contamination — marker enum + ingest guard

| Field | Value |
|---|---|
| Priority | P2 (data-integrity; not engine-safety) |
| Status | pending |
| Category | data-integrity / ingest |
| Size | M |
| Parent Epic | E-002 — Data Pipeline / Server Analytics |
| Related PRD | Sprint 51 candidate (data-integrity/hygiene) |
| Dependencies | Atlas schema/design decision — **RULED 2026-07-01** (`offices/architect/reports/2026-07-01-f116-foreign-vehicle-marker-and-guard-ruling.md`) |
| Created | 2026-06-30 |
| Source | Spool note `offices/pm/inbox/2026-06-30-from-spool-foreign-vehicle-contamination-drive33.md` |

## Description

The shared OBDLink LX auto-paired to the CIO's wife's **2014 Ford Explorer** and the Pi (on wall power) logged its engine-on as Eclipse **drive 33** (2026-07-01 02:21–02:23 UTC, 1,364 `realtime_data` rows), synced to `obd2db` tagged `data_source='real'` — so every real-data tuning query would ingest Explorer CAN data as if it were 4G63 telemetry. Caught by **9.09 samples/sec aggregate**, physically impossible on the Eclipse ISO 9141-2 K-line (~6.3/s ceiling, Session 26); it blended in because all 18 logged PIDs are generic OBD-II.

Spool applied interim mitigation (`drive_annotations` is_actual_drive=0 + provenance; `drive_summary.is_real=0`) but **could not honestly tag the underlying rows** — no CHECK enum value means "foreign/other vehicle" (`realtime_data.data_source` ∈ real/replay/physics_sim/fixture; `drive_summary.data_quality` ∈ full/attribution_anomaly). The 1,364 rows remain `data_source='real'` with a documented "exclude drive_id=33" note until a proper marker lands.

## Acceptance Criteria (Atlas-RULED 2026-07-01)

Ruling: `offices/architect/reports/2026-07-01-f116-foreign-vehicle-marker-and-guard-ruling.md`. Story = **US-424** (Sprint 51 / V0.29.5).

- [ ] **Marker — two axes.** `data_source='foreign'` added to the SSOT `src/pi/obdii/data_source.py` `DATA_SOURCE_VALUES` (propagates to all 5 Pi table CHECKs) **+ mirrored on the server** `data_source` CHECK — the **primary row-level exclusion axis** (every real-data query filters `WHERE data_source='real'` → foreign auto-excluded, zero consumer changes; **NOT `'fixture'`** — fixture-cleanup could delete the evidence). **AND** `data_quality='foreign_vehicle'` added to the `src/server/analytics/drive_statistics_compute.py` `DRIVE_STATISTICS_DATA_QUALITY_VALUES` SSOT + the model enum (the `:101` divergence assertion must stay green) for drive-level honesty.
- [ ] **A-4:** both are forward-only CHECK migrations applied **identically on both tiers** — define once per SSOT, mirror the other; do NOT hand-maintain two lists.
- [ ] **Re-tag drive 33:** Spool runs the reclassification SQL once the enums land — `realtime_data.data_source='foreign'` + `drive_summary.data_quality='foreign_vehicle' WHERE drive_id=33`. **Re-tag, never delete** (evidence preserved).
- [ ] **Ingest guard = sustained bus-rate check (primary).** Aggregate sample rate over a **rolling window** > ~7/s (Eclipse K-line ceiling ~6.3/s) → flag foreign. **SUSTAINED, not instantaneous** (no false-flag on a legit Eclipse burst). On trip → **flag/quarantine (mark `foreign`), NEVER silently delete.**
  - **NOT a device/dongle-MAC allowlist** — the same OBDLink served both vehicles, so it would not have caught drive 33. **NOT a VIN guard** — Eclipse ECU MD326328 is Mode-09 silent (no VIN), the Explorer returns one → VIN-presence is backwards.
  - **Protocol-ID** (ISO 9141-2 K-line vs ISO 15765 CAN via ELM327 `ATDPN`) is a stronger/faster future signal (definitive at connect → could prevent minting a foreign drive) but **no accessor exists today** → future hardening, **out of scope this sprint**.
- [ ] **Placement — layered (A-9 defense-in-depth).** Pi-side **primary**: on trip, retro-tag the open drive's rows `foreign` + do not sync as real (mark-on-detection; A-9-adjacent — same connection-edge, distinct concern, do not couple). Server-side **backstop** tripwire (like `detect_overlapping_drives`): flag any synced drive whose aggregate rate exceeds the ceiling → `data_quality='foreign_vehicle'`. *(Server tripwire is belt-and-suspenders — resize-droppable if tight; marker + Pi guard are the must-haves.)*
- [ ] **Rule-10:** `specs/architecture.md` data-contract section names the `foreign`/`foreign_vehicle` values + the bus-rate guard, in-sprint.

## Cross-references

| Item | Relationship |
|---|---|
| A-9 / DriveDetector | Loosely tied — the detector opened a "drive" for a non-Eclipse vehicle; but this is cross-vehicle identity, not attribution-within-Eclipse (distinct concern) |
| V0.29.1 data-integrity sprint | Gap that sprint didn't cover |

## Notes

Spool + Atlas are the shapers (Spool = tuning/evidence + re-tag SQL, Atlas = schema/guard design). Sprint 51 data-integrity candidate. Ping Spool for the exact re-tag SQL once the enum value is decided.
