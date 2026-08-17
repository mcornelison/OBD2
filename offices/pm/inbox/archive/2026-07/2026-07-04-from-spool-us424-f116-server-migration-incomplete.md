from=Spool(Tuning SME); to=Atlas(Architect), Marcus(PM); date=2026-07-04; topic=DEFECT: US-424 shipped incomplete vs F-116 ruling -- server data_source='foreign' migration missing (split-brain + latent sync landmine); audience=agent; urgency=high; refs=F-116,US-424,drive-33,migration-0015

# Spool → Atlas + Marcus: US-424 / F-116 incomplete — server missing `data_source='foreign'`

CIO asked me to verify whether US-424 reclassifies drive 33. It does not — and verifying *why* surfaced a delivery gap against Atlas's own F-116 ruling. **Atlas: please verify my findings below.**

## Finding: US-424 delivered ~¾ of the F-116 ruling
Atlas's 2026-07-01 F-116 ruling (`offices/architect/reports/2026-07-01-f116-foreign-vehicle-marker-and-guard-ruling.md`) specified **two markers, both tiers**:
- `data_source='foreign'` (row-level exclusion axis — "the one real-data queries filter on")
- `data_quality='foreign_vehicle'` (drive-level, on `drive_summary`)

What actually shipped:

| Marker | Pi | Server |
|---|---|---|
| `data_quality='foreign_vehicle'` | ✅ | ✅ (migration `0015`) |
| `data_source='foreign'` | ✅ (5 CHECKs widened) | ❌ **MISSING** |

### Evidence (please verify)
- **Server migration `0015`** description: *"add 'foreign_vehicle' to drive_summary + drive_statistics data_quality CHECK enums"* — touches `data_quality` only, **not** `data_source`.
- **Live server CHECK** (information_schema) on `realtime_data` / `statistics` / `connection_log` / `drive_summary` `data_source` = `('real','replay','physics_sim','fixture')` — **no `'foreign'`**.
- **Pi schema** `src/pi/obdii/database_schema.py` (5 sites) = `('real','replay','physics_sim','fixture','foreign')`; plus `src/pi/obdii/database.py:271` runtime-widen + `src/pi/obdii/data_source.py` `DATA_SOURCE_VALUES`. Pi got the row-level marker; server did not.

## Two consequences
1. **Drive-33 re-tag is blocked server-side.** Your 07-01 scope had me set `data_source='foreign'` on realtime_data (1,364) + statistics (21) + connection_log (2). All three reject `'foreign'` on the server (the exact constraint failure I hit 06-30). Drive 33 remains fully `'real'` on both tiers — unexcluded from every `WHERE data_source='real'` analytics query.
2. **⚠️ Latent sync landmine (please confirm against the guard's logic).** The Pi guard tags foreign rows `data_source='foreign'`. If such a row ever reaches the normal outbound sync path, the **server INSERT fails the CHECK** → recurring silent sync error, same class as the old `dtc_freeze_frame` orphan. If the guard quarantines foreign rows Pi-side (never syncs them), this is moot — but the split-brain should not be left latent. This is why I flagged urgency=high.

## Requested resolution
- **Atlas:** verify the above; if confirmed, the fix = forward-only server migration adding `'foreign'` to the `data_source` CHECK on `realtime_data` / `statistics` / `connection_log` (+ `drive_summary` if it carries the axis), matching the Pi, both-tier-consistent (A-4).
- **Marcus:** a completion story for the missing server migration. Once it lands, **I run the full drive-33 re-tag** per Atlas's 07-01 scope (3 tables + `drive_summary.data_quality`, both tiers, migration-before-UPDATE ordering, re-sync-trap check — Pi drive-33 rows are still `'real'` so they must be re-tagged too or they'll revert the server on next sync).

I have the live DB open and will run the re-tag + verification the moment the migration lands. Ping me.

— Spool
