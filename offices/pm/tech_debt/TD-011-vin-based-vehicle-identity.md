# TD-011: VIN-Based Vehicle Identity (Decouple from Pi Device ID)

**Priority**: Low (deferrable until multi-vehicle or Pi-swap scenarios arise)
**Status**: Open
**Category**: Data Model / Identity
**Related**: B-036 (Server), B-037 (Pi), VehicleInfo model (`src/server/db/models.py:168`)
**Filed**: 2026-04-16 (CIO directive, PM Session 19)

## Description

Today the system conflates **Pi identity** and **vehicle identity** under a single `device_id` string (e.g. `chi-eclipse-01`). This works because there is currently one Pi installed in one Eclipse. It will break down in two foreseeable scenarios:

1. **Pi moved between cars.** The CIO's Pi could be transplanted to another vehicle (e.g. a friend's car) and collect data under the same `device_id`, producing a dataset that appears to be one vehicle but is actually two.
2. **Multiple Pis on multiple cars** (CIO has noted sharing with friends as a possible direction). Two Pis collecting on the same VIN (unlikely in practice but possible for shop / diagnostic scenarios) would appear as two unrelated datasets.

The schema already has a `VehicleInfo` table keyed on VIN at `src/server/db/models.py:168`, but nothing currently populates it, and no analytics/report joins data to it. The OBD-II protocol supports VIN retrieval via Mode 0x09 PID 0x02 — when the OBDLink LX connects to a vehicle, the VIN is available.

## Desired Future State

- **Pi identity** remains `device_id` (the edge collector's logical name).
- **Vehicle identity** becomes the VIN, populated in `VehicleInfo` on first connection, and joined via `(source_device, source_id)` from drives.
- Analytics (trends, comparisons, baselines) key on **VIN**, not `device_id`, so a vehicle's history follows the car regardless of which Pi collected it.
- `drive_summary` gets an FK or denormalized `vin` column to make the join cheap.
- Reports show "Vehicle: 1998 Mitsubishi Eclipse GST — VIN 4A3AK54F8WE122916" rather than "Device: chi-eclipse-01".

## Migration Considerations

- Existing rows have `device_id` but no VIN. Backfill strategy: infer VIN from `device_id` where the mapping is known (e.g. `chi-eclipse-01` → CIO's Eclipse VIN).
- Pi must reliably decode VIN on connect and cache it locally so offline drives still tag correctly.
- If a vehicle has no VIN response (very old or ECU quirk), fall back to `device_id` with a warning.

## Trigger to Prioritize

- First real-world Pi connection to the Eclipse (pulls VIN via Bluetooth → validates plumbing).
- Any second vehicle added to the system.
- Spool / CIO needing per-vehicle (not per-Pi) tuning history.

**CIO context (Session 19):** For the foreseeable near term, 100% of collected
data will come from the CIO's single Eclipse. Expansion to a second car is
possible if the system is successful, and **that expansion is the trigger**
that turns this tech debt into a real blocker. Until then, the Pi-centric
`device_id` model is correct and simpler — don't pre-optimize.

## Scope When Pulled In

Likely one feature, ~3–5 stories:
- Pi: decode + cache VIN on BT connect; include in sync payload.
- Server: populate `VehicleInfo` on first sighting; add `vin` to `drive_summary`.
- Analytics/reports: switch grouping from `device_id` to `vin`.
- Data migration story for existing rows.
- Tests for multi-VIN and device-swap edge cases.
