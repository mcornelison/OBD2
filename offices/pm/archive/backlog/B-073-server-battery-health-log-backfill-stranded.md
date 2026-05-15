# B-073: Server-side battery_health_log backfill -- stranded rows 11-15 from pre-V0.27.4 era

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Low (P3)               |
| Status       | Pending (V0.27.6 candidate) |
| Category     | data recovery / one-off |
| Size         | XS                     |
| Related PRD  | None                   |
| Dependencies | None (US-315 V0.27.4 fix is forward-only; this is a one-time replay) |
| Created      | 2026-05-11             |

## Description

V0.27.4 US-315 added the sync UPDATE propagation path (modified_at cursor). It works forward (verified by drain_event_id=16 closing on both Pi and server post-V0.27.4 deploy). **But it does NOT auto-replay missed historical UPDATEs.**

Server-side `obd2db.battery_health_log` rows 11-15 are permanently stranded with `end_timestamp=NULL` despite Pi-side having full close-event data. They'll stay NULL on server forever unless something forces a re-sync.

## Stranded rows (Spool 2026-05-11 audit)

| drain_event_id | Pi-side end_timestamp | Server-side end_timestamp | synced_at (INSERT) |
|---:|---|---|---|
| 11 | 2026-05-10T00:52:28Z | NULL | 2026-05-10T00:46:16 |
| 12 | 2026-05-10T01:12:43Z | NULL | 2026-05-10T01:12:30 |
| 13 | 2026-05-10T02:34:59Z | NULL | 2026-05-10T02:24:47 |
| 14 | 2026-05-10T03:47:44Z | NULL | 2026-05-10T03:35:42 |
| 15 | 2026-05-10T14:13:49Z | NULL | 2026-05-10T14:00:43 |

(Row 16 closes cleanly on both sides; first US-315 IRL evidence.)

## Resolution

Two options:

### Option 1 (recommended) — One-off SQL UPDATE

Source close-event data from Pi-side rows + run server-side `UPDATE battery_health_log SET end_timestamp = ..., end_soc = ..., end_vcell_v = ..., runtime_seconds = ... WHERE id IN (11, 12, 13, 14, 15)`. Trivial mechanical fix.

### Option 2 — Generic post-US-315 historical-row reconciliation pass

Build a `scripts/reconcile_stranded_sync_rows.py` that compares Pi vs server for B-065-affected tables + reconciles. More flexible (also covers drive_summary once that side validates post-Drive-11+), but more code.

**Recommendation**: Option 1 for V0.27.6 (~10-line one-off SQL). Option 2 deferred until Drive 11+ validates drive_summary sync UPDATE too (then bundled cleanup makes sense).

## Acceptance Criteria

- [ ] Pre-flight: SSH chi-srv-01 + `mysql obd2db -e "SELECT id, end_timestamp FROM battery_health_log WHERE id IN (11,12,13,14,15)"` confirms current NULL state
- [ ] One-off SQL script runs; rows 11-15 server-side now match Pi-side end_timestamp + runtime_seconds + end_vcell_v
- [ ] Script idempotent: re-running on already-populated rows is a no-op (no overwrites)
- [ ] Post-script: `synced_at` left as-is (it's INSERT-time; not bumped on UPDATE per US-315 design)

## Validation Script Requirements

- **Input**: chi-srv-01 obd2db with battery_health_log rows 11-15 stranded (NULL end_timestamp)
- **Expected Output**: rows 11-15 populated; values match Pi-side authoritative state
- **Test Program**: smoke against staging DB OR rollback-safe dry-run + diff before apply

## Source

`offices/pm/inbox/archive/2026-05/2026-05-11-from-spool-calibration-cli-pymysql-missing.md` Story D
