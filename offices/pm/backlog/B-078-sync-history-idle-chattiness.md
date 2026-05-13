# B-078: sync runs every ~5s at idle -- sync_history grows ~12 rows/min; SyncCadenceController IDLE-60s not engaged

| Field | Value |
|---|---|
| Priority | Medium (P2 -- 20k+ rows in a few days is unsustainable; PM lean: fix this one soon) |
| Status | Pending (strong V0.27.8 mini-sprint candidate; OR fold into B-076; CIO decides) |
| Category | sync / cadence / data-hygiene |
| Size | S |
| Related | Sprint 26 US-298 (SyncCadenceController state machine IDLE-60s / ACTIVE-5s / DRAINING) + US-299 (wired into `core._maybeTriggerIntervalSync`); B-053 (the cadence-controller epic); B-076 (the one-time `sync_history` prune is part of that epic's cleanup step) |
| Created | 2026-05-12 |

## Description

Tester 2026-05-12 live obd2db query: `sync_history` has 20,283 rows, growing ~12 rows/min at idle -- sync runs ~every 5s when there's nothing new (each idle row syncs 2-3 `realtime_data` rows = engine-off polling data). That's the ACTIVE-5s cadence, not the IDLE-60s cadence. The Sprint 26 `SyncCadenceController` (US-298) was supposed to drop to IDLE-60s when no new local rows since the last successful sync -- either it's not wired into the actual sync trigger, or it's stuck in ACTIVE and never releases to IDLE.

20k+ rows in a few days is unsustainable -- this needs attention before V0.28.

## Pre-flight question (grooming must resolve)

- Is `SyncCadenceController` actually live? US-299 wired it into `core._maybeTriggerIntervalSync` -- verify that's the path the deployed Pi uses (a phantom-path drift here would mean the controller exists but isn't consulted)
- What keeps it in ACTIVE? The engine-off OBD polling still produces `realtime_data` rows every ~2-3s (the idle poll loop), so "new local rows since last sync" is *always true* -> the controller never sees an idle window -> never drops to IDLE-60s. If that's the cause, the fix is: IDLE should mean "no new rows OTHER THAN routine engine-off polling" -- or the engine-off poll cadence itself should slow down (separate but related), or "ACTIVE" should require a *drive* to be in progress, not just any new row.

## Fix (direction; finalize at grooming)

- Confirm `SyncCadenceController` is wired into the live sync trigger
- Make IDLE actually engage: either (a) IDLE = "no drive in progress" regardless of engine-off poll rows, or (b) batch engine-off poll rows so they don't reset the ACTIVE timer, or (c) slow the engine-off `realtime_data` poll cadence so there's a genuine idle window
- Plus (per CIO directive): a one-time prune of `sync_history` ("should only be one sync after a drive") -- rides B-076's cleanup step

## Acceptance Criteria (when groomed)

- [ ] Pre-flight: confirm `SyncCadenceController` is consulted by the live sync trigger; reproduce the ACTIVE-stuck condition
- [ ] IDLE-60s engages when no drive is in progress (idle `sync_history` growth drops from ~12 rows/min to ~1 row/min)
- [ ] ACTIVE-5s still engages during a drive (no regression on drive-time sync latency)
- [ ] One-time prune of historical `sync_history` (or defer to B-076 cleanup)

## Source

- Tester 2026-05-12 db-review note (B-NEW-2) -- PM lean: "worth fixing soon, 20k+ rows/few days unsustainable"
- CIO directive 2026-05-12 (one-time prune `sync_history`)
