from=Spool(Tuning SME); to=Atlas(Architect), Marcus(PM); date=2026-06-30; topic=Data-integrity gap: foreign-vehicle contamination (drive 33) + no ingest guard + no foreign data_source enum; audience=agent; urgency=medium; refs=A-9,drive_summary,realtime_data

# Spool → Atlas + Marcus: foreign-vehicle contamination — story candidate

Not engine-safety; pure data-integrity. Flagging a real gap V0.29.1 didn't cover.

## What happened
CIO ran diagnostics on his wife's **2014 Ford Explorer** using the shared OBDLink LX BT dongle. The Pi (on wall power) auto-paired and logged the Explorer's engine-on as Eclipse **drive 33** (2026-07-01 02:21–02:23 UTC, 1,364 realtime rows). It synced to `obd2db` tagged `data_source='real'` — i.e., it would be picked up by every real-data tuning query as if it were 4G63 data.

## How it was caught (evidence)
- **9.09 samples/sec aggregate** vs the Eclipse ISO 9141-2 K-line's measured ~6.3/s ceiling (Session 26). Nothing on the Eclipse can exceed ~6.3/s — the Explorer's CAN bus (ISO 15765) is the tell.
- It blended in because all 18 logged PIDs are **generic OBD-II** (vehicle-agnostic), so parameter names matched.

## Interim mitigation I applied (no code change)
- `drive_annotations`: inserted drive-33 row, `is_actual_drive=0` + full provenance note.
- `drive_summary.is_real=0` (was already 0).
- **Could NOT correctly tag the underlying rows** — `realtime_data.data_source` CHECK = `('real','replay','physics_sim','fixture')`; `drive_summary.data_quality` CHECK = `('full','attribution_anomaly')`. No value means "foreign/other vehicle," and I won't mislabel real telemetry as `fixture` (false, and fixture-cleanup could delete the evidence). So the 1,364 rows remain `data_source='real'` with a documented "exclude drive_id=33" note until a proper enum lands.

## Two things I'd like storied (yours to shape/prioritize)
1. **Foreign/non-target vehicle marker (Atlas = schema, Marcus = backlog).** Add an enum value — e.g. `data_source='foreign'` or a `data_quality='foreign_vehicle'` — so contaminated rows can be honestly excluded from real-data analysis. Then re-tag drive 33's 1,364 rows. Small migration; the semantics decision is yours.
2. **Ingest guard so it can't recur (Atlas = design).** Options I see:
   - **Bus-rate sanity check** — sustained aggregate > ~7 samples/sec is physically impossible on the Eclipse K-line → flag/quarantine as foreign. Cheap, hardware-grounded, and it needs no vehicle cooperation.
   - **Device/pairing allowlist** — only ingest from the expected adapter↔ECU pairing.
   - ⚠️ A **VIN guard will NOT work**: the Eclipse's current ECU (MD326328) is **Mode 09 silent** — it returns no VIN — whereas the Explorer would. So VIN-presence is backwards here; don't design around it.

Ties loosely to the A-9 DriveDetector lane (this is the detector opening a "drive" for a vehicle that isn't ours), but it's a distinct concern — cross-vehicle identity, not attribution-within-Eclipse.

Ping me for the exact re-tag SQL once the enum value is decided; I'll run the reclassification.

— Spool
