# TD-038: drive_summary server schema drift — missing v0004 migration, sync failing in production

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | High (P0)                 |
| Status       | Open                      |
| Category     | architecture / database / sync |
| Affected     | `chi-srv-01:obd2db.drive_summary`, `src/server/migrations/versions/`, `src/server/api/sync.py`, Pi `sync_log` for table=drive_summary |
| Introduced   | Sprint 15 (US-206 added cold-start metadata columns to Pi schema; server v0004 migration was never authored). Has been silently failing every Pi sync since Sprint 15. |
| Created      | 2026-04-29                |

## Description

The chi-srv-01 server's `drive_summary` table is on a **pre-Sprint-15 schema**. Migrations only ran through `v0003_us223_drop_battery_log` (2026-04-23). No migration ever modernized `drive_summary` to the schema US-206 / US-214 / US-228 expect.

**Server `drive_summary` (current — legacy):**
```
id               int(11)        AI PK
device_id        varchar(64)    NOT NULL
start_time       datetime       NOT NULL
end_time         datetime
duration_seconds int(11)
profile_id       varchar(64)
row_count        int(11)
created_at       datetime       DEFAULT current_timestamp()
```

**Pi `drive_summary` (current — what server CODE expects):**
```
drive_id                 INTEGER  PK
drive_start_timestamp    DATETIME NOT NULL
ambient_temp_at_start_c  REAL
starting_battery_v       REAL
barometric_kpa_at_start  REAL
data_source              TEXT NOT NULL DEFAULT 'real'
... + source_id, source_device (synthesized server-side by sync.py)
```

**Symptom (2026-04-29 evening, observed during chi-srv-01 power-cycle drill):**

```
ERROR | src.server.api.sync | Sync upsert failed for batch chi-eclipse-01-...:
  (pymysql.err.OperationalError) (1054, "Unknown column 'drive_summary.source_id' in 'SELECT'")
INFO: 10.27.27.28:60830 - "POST /api/v1/sync HTTP/1.1" 500 Internal Server Error
```

**Pi-side state:**
```
sqlite3 obd.db "SELECT table_name, last_synced_id, status FROM sync_log WHERE table_name='drive_summary';"
drive_summary  0  failed
```

`last_synced_id=0`, `status=failed`. **Pi has never successfully synced a single drive_summary row to server.**

**Server `schema_migrations` confirms the gap:**
```
0001  US-195 data_source + US-200 drive_id catch-up      2026-04-22
0002  US-217 battery_health_log                          2026-04-22
0003  US-223 / TD-031 close — drop battery_log           2026-04-23
[no v0004]
```

The server `drive_summary` still contains 9 stale rows from 2026-04-16 sim/dev data (`device_id='sim-eclipse-gst'`, `device_id='eclipse-gst-day1'`) — pre-real-data, pre-Sprint-15 truncate. Sprint 18's US-227 truncate did not touch this table because Pi was never successfully syncing drive_summary, so it wasn't on the truncate's drift watchlist.

## Why It Was Accepted

It wasn't accepted — it's a **gap in Sprint 16 US-213 (server schema migration gate)** scope. The gate exists and runs at deploy time, but nobody authored the v0004 migration for `drive_summary` when US-206 added the columns Pi-side. So the gate has been a no-op for this table — it's never had work to do.

This is the most expensive kind of TD: code wrote checks that always pass because the tested condition is unreachable.

## Risk If Not Addressed

**Already actively dropping data on the floor.** Every Pi sync attempt to `drive_summary` returns 500. 4 Pi-side `drive_summary` rows currently orphaned (drive_id 2, 3, 4, 5). All 4 have NULL metadata (compounded by US-228 broken-backfill, addressed by Sprint 19 US-236) — but the rows themselves never reach server.

**Compounds with Sprint 19 US-236**: Sprint 19's US-228-fix-Option-a will start writing valid drive_summary rows on Pi. Until TD-038 is fixed, those will pile up unsynced. The sync_log status=failed prevents subsequent table-syncs from proceeding past this point.

**Impacts analytics**: any post-hoc analysis that joins realtime_data ↔ drive_summary on server is missing every drive since Pi started recording real data.

**Likelihood: certain (already happening). Impact: medium-to-high (silent data loss on a structurally-significant table).**

## Remediation Plan

**One new migration: `src/server/migrations/versions/v0004_drive_summary_modernize.py`** with this sequence:

1. `DROP TABLE drive_summary` — the 9 stale rows are pre-real sim/dev data with no value (oldest 2026-04-16; all `device_id='sim-eclipse-gst'`/`eclipse-gst-day1`).
2. `CREATE TABLE drive_summary` matching the modernized Pi schema **plus** the source-attribution columns the server's `sync.py` upsert references (`source_id`, `source_device`). These are server-only columns synthesized during upsert.
3. `INSERT INTO schema_migrations (version, description, applied_at) VALUES ('0004', 'US-228+ drive_summary modernize — server-tier catch-up to Pi schema', NOW())`.

**Acceptance**: post-migration, `bash tests/deploy/test_obd_server_service.sh` passes; Pi `sync_log.drive_summary` flips from `status=failed, last_synced_id=0` → `status=ok, last_synced_id≥4`. The 4 currently-orphaned Pi rows (drive_id 2-5) sync up. 500 storm in obd-server log stops.

**Sprint placement** — PM decision pending:
- **Option A (Spool's lean)**: Sprint 19 add-on as a new story. Bug is currently dropping data.
- **Option B**: Sprint 20 carryforward. Bug has been silent for weeks; another sprint of silence isn't materially worse, and Rex is mid-sprint.

## Related

- **Sprint 16 US-213** (server schema migration gate) — gate works as designed; content (the migration list) was incomplete. See TD-039 for the retro reflection.
- **Sprint 15 US-206** (cold-start metadata columns) — added columns to Pi schema; server-side migration never followed
- **Sprint 19 US-236** (US-228 defer-INSERT fix) — ships valid drive_summary rows; TD-038 unblocks them syncing
- **Sprint 18 US-227** (operational truncate) — did not touch drive_summary because of this drift
- **Source notes**:
  - `offices/pm/inbox/2026-04-29-from-spool-chi-srv-01-power-cycle-and-drive-summary-schema-drift.md` Section 2 (root cause + suggested fix)
  - `offices/pm/inbox/2026-04-29-from-spool-sprint19-consolidated.md` (initial flag in Open Items)
