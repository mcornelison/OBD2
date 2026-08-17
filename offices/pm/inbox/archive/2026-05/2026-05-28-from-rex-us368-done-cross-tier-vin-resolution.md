# US-368 DONE — F-109 dtc_freeze_frame + cross-tier note for US-369

**From:** Rex (Ralph Agent, Agent 1) · **Date:** 2026-05-28 · **Sprint:** 43 / V0.28.0
**Re:** US-368 complete; two design decisions that affect US-369 + the Atlas Rule 10 gate.

## Status

US-368 `passes: true`. Full server suite GREEN (exit 0, +25 tests), full Pi suite GREEN
(exit 0, +15 tests), ruff clean on touched files. Changes UNSTAGED per PM protocol.

## Decision 1 — server `dtc_freeze_frame` carries sync columns (affects US-369)

The server `DtcFreezeFrame` model was created with the **standard synced-capture
columns** (`source_id`, `source_device`, `synced_at`, `sync_batch_id`,
`UNIQUE(source_device, source_id)`) in addition to AC#1's five enumerated columns.
Rationale: US-369 syncs this table Pi→server, and every other synced capture table
uses the `(source_device, source_id)` upsert key. Creating it without them would force
US-369 to add a 2nd migration. AC#1 / V-1 check the 5 named columns are **present**, not
exclusive — so this is compatible. **US-369 can register `dtc_freeze_frame` in the sync
table registry as-is.**

## Decision 2 — cross-tier VIN→id resolution (US-369 MUST implement)

The two tiers key `vehicle_info` differently:
- **Pi**: PK is `vin TEXT`, single row. Pi `dtc_freeze_frame.vehicle_info_vin` stores the
  active vehicle's VIN.
- **Server**: PK is integer `id` with ECU lineage (install/removal). Server
  `dtc_freeze_frame.vehicle_info_id` is an integer FK.

The temporal invariant (`ecu_install ≤ captured_at ≤ ecu_removal`) can only live
server-side (the Pi schema has no ECU-lineage columns — server-only per US-365). It is
enforced by **`insertDtcFreezeFrame(session, …)` in `src/server/api/dtc_freeze_frame.py`**.

**US-369 sync should:** for each incoming Pi freeze-frame row, resolve the server
`vehicle_info_id` by looking up the `vehicle_info` row for that `vin` whose
`[ecu_install, ecu_removal]` window contains `captured_at`, then call
`insertDtcFreezeFrame(...)` (which validates the window + rejects a bogus id before any
partial insert). US-369's "FAILS LOUDLY if FK doesn't exist server-side" conditionalOutcome
maps directly onto the `ValueError` that writer-path already raises.

## Still open (NOT self-satisfiable by Ralph)

- **AC#7 Atlas Rule 10 sign-off** + the `dtc_freeze_frame` entry in
  `specs/architecture.md` §5.X are owned by **US-373 + Atlas** — PENDING. Same in-sprint
  precedent as US-361 / US-363 / US-365 (marked `passes:true` with the cross-gate routed).

`bigDoDHash` untouched (no change to `validation.bigDefinitionOfDone`).
