---
id: F-077
parent: E-OPS
status: pending
renamedFrom: B-077
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-077: OBD reconnect loop too chatty at idle -- connection_log grows ~6 rows/min 24/7

| Field | Value |
|---|---|
| Priority | Medium (P2) |
| Status | Pending (V0.27.8 mini-sprint candidate OR fold into B-076 epic; CIO decides) |
| Category | obdii / connection-log / data-hygiene |
| Size | S |
| Related | V0.27.6 US-325 (BT reconnect exponential backoff on `runReconnectHeartbeat` -- VERIFY whether this already covers the loop writing connection_log rows, or it's a different loop / pre-deploy data); B-076 (the one-time `connection_log` truncate is part of that epic's cleanup step) |
| Created | 2026-05-12 |

## Description

Tester 2026-05-12 live obd2db query: `connection_log` has 6,996 rows, growing ~6 rows/min at idle -- the OBD reconnect loop fires ~every 10s 24/7 even engine-off / no ECU present, and each attempt writes a `connection_log` row. ~6 rows/min = one row every 10s = the BASE heartbeat interval, NOT a backed-off interval.

## Pre-flight question (grooming must resolve)

V0.27.6 US-325 already shipped exponential backoff on `runReconnectHeartbeat` (10 -> 20 -> 40 -> 80 -> 160 -> 320s cap, reset on success). So one of:
- (a) The tester's observation is **pre-V0.27.6-deploy data** (V0.27.6 deployed 2026-05-12; tester queried 2026-05-12 ~01:40Z -- timing overlap unclear) -> may already be fixed; just needs a re-query + the one-time truncate
- (b) `connection_log` rows are written by a **different code path** than `runReconnectHeartbeat` (e.g., a lower-level connect-attempt logger inside `ObdConnection` / the data-logger reconnect) that US-325's backoff doesn't touch
- (c) US-325's backoff applies to the *cadence* but `connection_log` rows are written *per-attempt-event* regardless -- though at the 320s cap that's ~0.19 rows/min, not 6/min, so this alone doesn't explain it

Grooming: `rg connection_log src/pi/` to find every writer; cross-check against US-325's `runReconnectHeartbeat` callsite; determine if (a) (no fix needed -- just truncate) or (b)/(c) (extend backoff to the chatty writer).

## Fix (if (b) or (c))

Exponential backoff on the reconnect-attempt cadence once N consecutive attempts fail / no ECU seen in M minutes (cap ~60-120s), mirroring US-325's pattern. Don't write a `connection_log` row on every 10s tick when nothing has changed -- write on state transitions + at the backed-off cadence.

Plus (regardless of (a)/(b)/(c), per CIO directive): a one-time truncate of historical `connection_log` rows -- this rides B-076's cleanup step.

## Note on the CIO's "away from home wifi" framing

The tester flags: the CIO's "connection drops away from home wifi" observation actually points at THIS OBD-BT reconnect loop, not the WiFi sync path -- `connection_log` rows are OBD/BT connection attempts, not network events. (The WiFi-instability OS fix `wifi.powersave=2` was the right call for the actual WiFi drops; this is a separate, OBD-side noise issue.)

## Acceptance Criteria (when groomed)

- [ ] Pre-flight: `rg connection_log src/pi/` -- enumerate writers; determine if US-325 already covers it (re-query the deployed Pi)
- [ ] If not covered: backoff on the chatty writer's cadence; `connection_log` rows on state-transition + backed-off cadence only
- [ ] One-time truncate of historical `connection_log` (or defer to B-076 cleanup)
- [ ] Post-fix: idle `connection_log` growth rate << 6 rows/min (target: ~0 rows/min when engine-off + no ECU, after the backoff caps out)

## Source

- Tester 2026-05-12 db-review note (B-NEW-1)
- CIO directive 2026-05-12 (one-time truncate `connection_log`)
