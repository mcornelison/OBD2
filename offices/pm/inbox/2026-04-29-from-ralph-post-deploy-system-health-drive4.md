# Post-Sprint-18 system health + Drive 4 variances

**From:** Rex (Ralph Agent 1)
**To:** Marcus (PM)
**Date:** 2026-04-29
**Re:** CIO test drive this morning; system health check + Sprint 19 candidate variances

## TL;DR for Sprint 19 grooming

CIO ran a short engine-on test this morning (2026-04-29 13:39:18 UTC,
warm-idle garage test, 10m 46s, 4487 rows, healthy engine). System health
green; auto-sync delivered the bulk realtime_data; **but Drive 4 surfaced 7
variances** ranging from one critical schema bug (148 silent sync failures
to date) to housekeeping items. **3 stories minimum recommended for Sprint
19; 4 more candidates for Sprint 20+.**

| # | Sev | One-line | Sprint 19 size |
|---|-----|----------|---|
| V-1 | **CRITICAL** | drive_summary 3-way schema mismatch -- ORM/table/Pi all different; sync 100% failing | S-M (one migration) |
| V-2 | MAJOR | dtc_log table missing on server entirely (US-204 was Pi-only) | S |
| V-3 | MAJOR | Drive 4 connection_log events all missing on server; need Pi up to disambiguate sync-gap vs writer regression | S (path-b) / M (path-a) |
| V-4 | MEDIUM | drive_id namespace collision: legacy drive_summary auto-incr ids 1-10 collide with Pi-minted drive_ids | M |
| V-5 | MEDIUM | Server-side pre-mint NULL drive_id rows = 541; US-233 was Pi-only | S |
| V-6 | LOW | Server drive_counter still at 3; Pi at 4 (Pi mints, server passive) | S |
| V-7 | LOW | drive_statistics last computed 2026-04-16; analytics never re-ran for real drives | M |

Plus a meta-variance worth a story by itself: **148 sync failures vs 93
successes is 60% failure rate, with no operator-facing alerting** -- the
project has rich `sync_history.error_message` state but no surface saying
"hey, this is failing." See "Suggested meta-story" at end.

Drive 4 engine fundamentals: tune dialed (LTFT -5.87% avg matches Drive 3's
-6.25% baseline), closed-loop fueling reached, DTCs=0, MIL=off, alternator
charging. **Engine HEALTHY; all variances are infrastructure / data-layer.**

## Operator context

CIO ran a short engine-on test this morning, captured data, then **shut the
car off and unplugged the Pi** before this check. Asked Ralph to verify the
data made it to the server, system health, and report any variances for
sprint backlog.

## Health check summary

| Tier   | Status |
|--------|--------|
| Pi (chi-eclipse-01) | **DOWN** as expected — SSH connect timeout (ssh_rc=255) |
| Server (chi-srv-01) | **HEALTHY** — `obd-server.service` active, enabled, Restart=always; uptime 3h+ since AC#6 kill drill (08:11:37 CDT); /api/v1/health = `{"status":"healthy", components.{api,mysql,ollama}=up}`; lastSync=2026-04-29T14:00:12 UTC |
| Pi→Server sync (US-226) | **WORKING** — Drive 4 realtime_data landed (4487 rows). Auto-sync triggered ~10 min after engine-off. |

## Drive 4 — what landed on the server

| Metric | Value |
|--------|-------|
| drive_id | 4 |
| Time window (UTC) | 2026-04-29 13:39:18 → 13:50:04 (10m 46s) |
| realtime_data rows | 4,487 (rate 6.95/sec) |
| Distinct PIDs | 16 |
| connection_log entries for drive_id=4 | **0** ⚠ (variance) |
| drive_summary entry for drive_id=4 | **NONE** ⚠ (variance) |
| dtc_log entries | **N/A — table doesn't exist on server** ⚠ (variance) |

### Engine health (from realtime_data)

| Signal | Drive 4 reading | vs Drive 3 baseline |
|--------|-----------------|---------------------|
| COOLANT_TEMP | 89-90°C constant | warm restart (NOT cold start; Drive 3 was 20→80°C cold-start) |
| RPM | start ~750 idle, end peaks 1207/1136/851 → wind down | low-rev test, no road drive |
| SPEED | max 3 mph | stationary (garage / driveway test) |
| THROTTLE_POS | 0-9.8% | very light, mostly idle |
| FUEL_SYSTEM_STATUS | 2 (closed loop) | ✅ closed-loop reached |
| O2_B1S1 | 0.02-0.96V swing | ✅ healthy oscillation |
| LTFT | -7.03% to 0%, avg -5.87% | close to Drive 3's -6.25% quantized; **tune still dialed** ✅ |
| STFT | -3.9% to +5.5%, avg -0.24% | ✅ closed-loop active |
| BATTERY_V | 13.1-14.3V, avg 13.99V | alternator charging normally |
| TIMING_ADVANCE | 3-33° | normal idle/transient |
| DTC_COUNT | 0 | ✅ |
| MIL_ON | 0 | ✅ |

**Engine verdict: HEALTHY.** Idle behavior + closed-loop fueling +
no-fault-codes consistent with the "tune dialed" Drive 3 baseline. Drive
shape is a warm garage idle test with brief throttle blips, not a road
drive — limited tuning value, but functional confirmation that the
collector is alive post-Sprint-18.

## Variances — Sprint 19 candidates

### V-1 (CRITICAL): drive_summary 3-way schema mismatch — sync 100% failing

`sync_history` shows **148 failed** sync attempts (vs 93 completed) since the
sync started running. Every failure is the same:

```
(pymysql.err.OperationalError) (1054, "Unknown column 'drive_summary.source_id' in 'SELECT'")
[SQL: SELECT drive_summary.source_id FROM drive_summary
      WHERE drive_summary.source_device = %s AND drive_summary.source_id IN (%s, %s, %s)]
[parameters: ('chi-eclipse-01', 2, 3, 4)]
```

Three different schemas, none reconciled:

| Layer | Shape |
|-------|-------|
| Pi `drive_summary` (US-206 / US-228) | `drive_id, drive_start_timestamp, ambient_temp_at_start_c, starting_battery_v, barometric_kpa_at_start, data_source` |
| Server **ORM model** (queried in sync logic) | expects `source_id`, `source_device` columns |
| Server **actual table** | `id, device_id, start_time, end_time, duration_seconds, profile_id, row_count, created_at` (Sprint 7-8 analytics shape, never reconciled) |

Result: Pi tries to sync drive_summary rows for drive_ids 2, 3, 4. Server's
sync code queries `drive_summary.source_id` (which doesn't exist in the
actual table). Every attempt fails. **Drive_summary metadata for ALL drives
including Drive 3 + Drive 4 is on Pi only; Spool's per-drive ambient/baro/
battery analysis is degraded indefinitely until this lands.**

US-214 reconciliation shipped a partial fix; the migration to add
`source_id`/`source_device` columns to the server table never ran.
`schema_migrations` table has 3 entries (0001 / 0002 / 0003); none reconcile
drive_summary.

**Sprint 19 story shape (S-M):** Add a 0004 migration that either (a) adds
`source_id` + `source_device` columns to the server `drive_summary` table to
match the ORM model OR (b) renames the existing columns to match the ORM
model OR (c) rebuilds drive_summary entirely on a Pi-shape-aligned schema.
Path-(a) is least disruptive. Then re-run sync — drive_summary rows for
drive_ids 2, 3, 4 will land retroactively because Pi has them all.

### V-2 (MAJOR): `dtc_log` table missing on server

US-204 (Sprint 15) added `dtc_log` to the Pi for DTC retrieval (Mode 03/07).
Server has no `dtc_log` table. `SHOW TABLES` confirms: ai_recommendations,
alert_log, analysis_history, anomaly_log, battery_health_log,
calibration_sessions, connection_log, devices, drive_counter,
drive_statistics, drive_summary, profiles, realtime_data, schema_migrations,
statistics, sync_history, trend_snapshots, vehicle_info — no dtc_log.

`schema_migrations` has no entry for it. Drive 4's DTC_COUNT was 0 so no
data was lost this drive, but the next drive that hits a DTC will have its
dtc_log row land on Pi only.

**Sprint 19 story shape (S):** Add a 0005 migration creating dtc_log on
server with the same shape as Pi (per `src/pi/obdii/dtc_client.py` /
US-204). Then sync_log scope (server-side) will need to include dtc_log
in DELTA_SYNC_TABLES.

### V-3 (MAJOR): Drive 4 connection_log events missing on server

Server `connection_log`:
- MAX(id) = **18564**
- MAX(timestamp) = **2026-04-28 11:53:29 UTC**
- 0 entries on 2026-04-29
- 0 entries with drive_id=4 (Drive 3 has 1 — its drive_start)

Drive 4 should have generated at minimum: `connect_attempt` + `drive_start`
+ `drive_end` (per US-229's ECU-silence path). None are on the server.

Two possible root causes — **need Pi back online to disambiguate**:

(a) **Pi connection_log writer regressed** post-Sprint-15 — drive_start /
    drive_end events stopped being written to connection_log even though
    drive_id is being minted (realtime_data rows ARE tagged drive_id=4).
    Check `event_router.py._handleDriveStart` / `_handleDriveEnd` for
    connection_log INSERT calls.

(b) **Pi wrote them but they didn't sync before unplug** — the connection_log
    cursor on Pi is stuck at id 18564; sync sequence got interrupted (Pi
    unplugged ~14:00 UTC, only ~10 minutes after engine-off). A Pi power-up
    + auto-sync should drain remaining rows.

Distinguishing query (when Pi is up): `ssh chi-eclipse-01 'sqlite3
~/Projects/Eclipse-01/data/obd.db "SELECT MAX(id), MAX(timestamp) FROM
connection_log; SELECT * FROM connection_log WHERE drive_id=4"'`. If Pi's
MAX(id) > 18564 with 2026-04-29 entries, it's path-(b) (sync gap, will
self-resolve next boot). If Pi's MAX(id) == 18564, it's path-(a) (writer
regression — needs code fix).

**Sprint 19 story shape (S if path-b, M if path-a):** Wait for Pi power-up
to disambiguate. If path-b, file an info-only TD; if path-a, file a fix
story for the connection_log writer wiring.

### V-4 (MEDIUM): drive_id namespace collision in `drive_statistics` + legacy `drive_summary`

Server has 9 legacy `drive_summary` rows from 2026-04-16 (sim/historical
data: `sim-eclipse-gst`, `sim-eclipse-gst-multi`, `eclipse-gst-day1`) with
auto-increment ids 1-10. The `drive_statistics` table uses those legacy
ids as foreign keys (computed_at = 2026-04-16 13:16:08 across all rows).

Real-data Pi syncs use Pi-minted drive_ids 1, 3, 4 — which **collide** with
the legacy auto-increment ids. So `drive_statistics WHERE drive_id=3`
returns rows for sim-eclipse-gst-multi 2026-04-16 morning, NOT real Drive 3
(2026-04-23). Same for drive_id=4: legacy eclipse-gst-day1 2026-04-16
09:21:32, NOT real Drive 4 (2026-04-29).

**No data loss** — the real drive data is in realtime_data tagged
correctly. But `drive_statistics` is stale (last computed 2026-04-16) AND
its foreign-key namespace is unsafe for new data.

**Sprint 19 story shape (M):** Decide drive_id namespace: (1) truncate the
legacy drive_summary + drive_statistics tables (no real data lost; sim
analytics gets re-keyed); OR (2) namespace the columns (add `source_device`
to drive_statistics so the FK is composite). Linked to V-1.

### V-5 (MEDIUM): Server-side pre-mint orphans accumulated to 541

Server has **541** NULL drive_id real rows in `realtime_data`. Distribution:
- 269 before 2026-04-29 13:39:18 (pre-Drive-4 boundary)
- 348 in 2026-04-29 13:00-14:00 hour
- ~79 between 13:50:04 (Drive 4 engine-off) and 14:00 — **adapter-level
  polls (BATTERY_V via ELM_VOLTAGE) continued post-engine-off**, tagged
  with drive_id=NULL because engine_state went to KEY_OFF after US-229's
  silence-trigger. Expected behavior per US-229 design.

US-233 backfill ran on Pi only. Server-side equivalent was flagged in the
Session 105 morning Spool inbox note as a Sprint 19 candidate. Drive 4's
data adds 348 more orphans to the existing pile.

**Sprint 19 story shape (S):** Server-side US-233-equivalent script. Same
algorithm (orphan → nearest subsequent drive_id within window) but using
the server's MariaDB cursor pattern. Also handle the post-engine-off
adapter-level polls (those should arguably stay NULL since they're not
"part of" any drive — design decision needed).

### V-6 (LOW): Server `drive_counter` at 3, Pi at 4

Server's `drive_counter` table: `(1, 3)`. US-227 set it to 3 (Drive 3
high-water). Pi has now minted Drive 4, but the server's counter copy
didn't follow. Probably irrelevant (server doesn't mint drive_ids; it
just receives them) but flagged for clarity. Could update on every
realtime_data sync if `MAX(drive_id)` in the synced rows exceeds the
counter.

**Sprint 19 story shape (S, low-prio):** Either (a) drop the server's
drive_counter table entirely (server never mints) OR (b) auto-advance it
during sync so it's always >= MAX(drive_id) seen.

### V-7 (LOW): drive_statistics never re-computed since 2026-04-16

`SELECT DISTINCT computed_at FROM drive_statistics` returns only
`2026-04-16 13:16:08`. The analytics layer hasn't been re-run for any of
the real drives. Out of scope for this morning's check, but worth a
Sprint 19 housekeeping note: the post-drive analytics pipeline isn't being
triggered automatically (or the trigger is missing). Spool's review
ritual (US-219) doesn't appear to have fired against Drive 3 or Drive 4
either.

## What WORKED end-to-end

- **US-226 auto-sync triggers**: lastSync=14:00:12 UTC, ~10 min after
  engine-off (13:50:04). Pi pushed Drive 4 realtime_data without operator
  intervention.
- **US-229 ECU-silence drive_end**: implicitly working — engine_state went
  to KEY_OFF post-engine-off (evidenced by NULL drive_id rows resuming
  ~13:50:04 onward in realtime_data). drive_end's connection_log entry
  is missing per V-3 but the state-machine itself appears to have
  transitioned.
- **US-231 server systemd unit**: 3h uptime since AC#6 kill drill, no
  flap-protection trips, /api/v1/health responding on schedule.
- **US-227 Drive 3 preservation**: `realtime_data WHERE drive_id=3` still
  shows 6,089 rows (verbatim Drive 3, untouched by the truncate).
- **Engine health**: tune dialed, no DTCs, closed-loop fueling, alternator
  charging. Functional confirmation that the system is alive post-Sprint-18.

## Recommended priority for Sprint 19

1. **V-1 drive_summary schema reconciliation** (CRITICAL; blocks Spool's
   per-drive metadata analysis indefinitely; 148 failed syncs and counting)
2. **V-2 dtc_log server-side migration** (MAJOR; data-loss risk on the
   first drive that hits a DTC)
3. **V-3 connection_log Drive 4 disambiguation** (MAJOR; need Pi back to
   know if it's a sync gap or a writer regression)
4. **V-4/V-5 namespace + orphan cleanup** (MEDIUM; bundle as a "server-side
   data hygiene" sprint candidate)
5. **V-6/V-7** (LOW; opportunistic)

## Suggested meta-story (worth its own card, separate from V-1..V-7)

**"Surface sync_history failures to the operator"** -- size S/M, priority
medium. The project already collects rich diagnostic state in
`sync_history.error_message` (148 detailed rows showing the drive_summary
column-not-found error since some early date). But there's no surface that
says "hey, this is failing." Concretely:

- `/api/v1/health` reports `lastSync: 2026-04-29T14:00:12` -- which is
  technically true (a sync did run at that time and partially succeeded)
  but obscures the fact that 60% of all sync attempts since are failing.
- No alert_log entry, no email, no daily summary. The variance V-1 has
  been silently bleeding for at least 2 days (148 failures observed
  today; 93 successes total) and would have continued indefinitely.

Story shape: extend `/api/v1/health` to return per-table sync status (last
success per table, failure count in last hour/day, last failure reason).
OR add a daily server-side summary that emits to a Spool inbox note when
the failure rate exceeds X. OR wire alert_log to take an entry on every
Nth consecutive sync_history failure.

Rough acceptance: a hypothetical V-1-equivalent regression in the future
gets caught within 24h via a loud signal (not a Ralph going hunting through
sync_history during an unrelated health check).

## Attachments / data sources

- Server SQL queries via `scripts/truncate_drive_id_1_pollution.py`'s helper
  (`mod._runServerSql(addrs, creds, sql, mod._defaultRunner)`) — same
  DSN-parsing pattern shipped this session for US-227.
- Health endpoint: `curl http://10.27.27.10:8000/api/v1/health`
- All raw query output captured this session; reproducible from the same
  helpers.

## Appendix A — Raw query evidence

For Marcus's grooming verification. Each variance below is anchored to a
reproducible query run during this morning's check. Run via
`scripts/truncate_drive_id_1_pollution.py` helpers from the project root.

### Health endpoint

```
$ curl -s http://10.27.27.10:8000/api/v1/health
{"status":"healthy","version":"1.0.0","components":{"api":"up","mysql":"up","ollama":"up"},
 "lastSync":"2026-04-29T14:00:12","lastAnalysis":null,"driveCount":9,"uptime":"0d 3h 14m"}
```

### Server systemd state

```
=== service ===
active
enabled
=== main pid ===
1737523                              # set at AC#6 kill drill 08:11:37 CDT; uptime 3h+
=== started ===
Wed 2026-04-29 08:11:37 CDT
=== restart pol ===
always
```

### Pi reachability

```
$ ssh -o ConnectTimeout=10 -o BatchMode=yes mcornelison@10.27.27.28 'echo PI_REACHABLE'
ssh: connect to host 10.27.27.28 port 22: Connection timed out  (rc=255)
```

### realtime_data drive distribution (server)

```sql
SELECT drive_id, data_source, COUNT(*) n, MIN(timestamp), MAX(timestamp)
FROM realtime_data GROUP BY drive_id, data_source ORDER BY drive_id, data_source;

drive_id | data_source | n    | first_ts            | last_ts
---------+-------------+------+---------------------+---------------------
NULL     | real        | 541  | 2026-04-21 02:27:10 | 2026-04-29 14:00:10
3        | real        | 6089 | 2026-04-23 16:36:50 | 2026-04-23 18:35:44
4        | real        | 4487 | 2026-04-29 13:39:18 | 2026-04-29 13:50:04
```

Drive 4 ID range: **64116 .. 68602** in realtime_data (4487 rows). Total
realtime_data MAX(id) = 68874 -- 272 NULL-tagged rows after Drive 4 ended
(post-engine-off adapter-level polls, US-229 design).

### Drive 4 PID coverage (16 distinct PIDs over 4487 rows)

```
parameter_name        n    min      max      avg
--------------------- ---- -------- -------- --------
BATTERY_V             304  13.10    14.30    13.99
COOLANT_TEMP          279  89.00    90.00    89.52    # warm restart, NOT cold
DTC_COUNT             279   0        0        0       # no faults
ENGINE_LOAD           279   7.45    25.10    18.44
FUEL_SYSTEM_STATUS    279   2        2        2       # closed loop
INTAKE_TEMP           279  17.00    21.00    17.88
LONG_FUEL_TRIM_1      279  -7.03     0.00    -5.87    # near Drive 3's -6.25 baseline
MAF                   279   2.99    14.31     3.16    # idle MAF
MIL_ON                279   0        0        0
O2_B1S1               279   0.02     0.96     0.55    # closed-loop oscillation
O2_BANK1_SENSOR2_V    278   0.02     0.78     0.41
RPM                   278  718.75 2589.75   783.02    # idle + brief revs
SHORT_FUEL_TRIM_1     279  -3.91     5.47    -0.24
SPEED                 279   0        3        0.05    # stationary
THROTTLE_POS          279   0        9.80     0.04
TIMING_ADVANCE        279   3.00    33.00     5.58
```

### Drive 4 RPM trajectory (start / end)

```
start: 13:39:20 RPM=746, 13:39:22=742, 13:39:24=753.75, 13:39:26=746, 13:39:28=757.75
end  : 13:49:02=851.5, 13:49:00=1207, 13:48:58=1136.5, 13:48:56=746, 13:48:54=804.5
```

### V-1 evidence: drive_summary schema 3-way mismatch

```sql
DESCRIBE drive_summary;        -- server actual table
id                int(11)         NO  PRI  NULL  auto_increment
device_id         varchar(64)     NO       NULL
start_time        datetime        NO       NULL
end_time          datetime        YES      NULL
duration_seconds  int(11)         YES      NULL
profile_id        varchar(64)     YES      NULL
row_count         int(11)         YES      NULL
created_at        datetime        YES      current_timestamp()
```

Server ORM model expects `source_id`, `source_device` (per the failing
query in sync_history below) -- those columns don't exist in the actual
table.

Pi `drive_summary` (per US-206 / US-228, in `src/pi/obdii/drive_summary.py`):
`drive_id, drive_start_timestamp, ambient_temp_at_start_c,
starting_battery_v, barometric_kpa_at_start, data_source`.

```sql
SELECT status, COUNT(*) FROM sync_history GROUP BY status;
completed  93
failed    148
```

Most recent failed reason (sample, all 148 follow this exact pattern):

```
(pymysql.err.OperationalError) (1054, "Unknown column 'drive_summary.source_id' in 'SELECT'")
[SQL: SELECT drive_summary.source_id FROM drive_summary
      WHERE drive_summary.source_device = %s AND drive_summary.source_id IN (%s, %s, %s)]
[parameters: ('chi-eclipse-01', 2, 3, 4)]
```

`schema_migrations` content (no entry covers drive_summary reconciliation):

```
0001  US-195 data_source + US-200 drive_id / drive_counter catch-up   2026-04-22 22:12:39
0002  US-217 battery_health_log -- per-drain-event UPS health table   2026-04-22 22:12:43
0003  US-223 / TD-031 close -- drop battery_log                       2026-04-23 10:32:36
```

### V-2 evidence: dtc_log missing on server

```sql
SELECT COUNT(*) FROM dtc_log;
ERROR 1146 (42S02): Table 'obd2db.dtc_log' doesn't exist
```

`SHOW TABLES` confirms (no dtc_log in the list):

```
ai_recommendations    drive_counter          schema_migrations
alert_log             drive_statistics       statistics
analysis_history      drive_summary          sync_history
anomaly_log           profiles               trend_snapshots
battery_health_log    realtime_data          vehicle_info
calibration_sessions  devices
connection_log
```

### V-3 evidence: Drive 4 connection_log events missing on server

```sql
SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM connection_log;
2026-04-23 03:12:39   2026-04-28 11:53:29   18498

SELECT id, timestamp, event_type, drive_id FROM connection_log WHERE drive_id=4 ORDER BY id;
(0 rows)

SELECT id, timestamp, event_type, drive_id FROM connection_log WHERE drive_id=3 ORDER BY id;
2004  2026-04-23 16:36:49  drive_start  3   # 1 row -- Drive 3 drive_start; no drive_end (US-229 era)

SELECT COUNT(*) FROM connection_log WHERE timestamp >= '2026-04-29';
0
```

Disambiguation query for next Pi power-up:

```bash
ssh chi-eclipse-01 "sqlite3 ~/Projects/Eclipse-01/data/obd.db \
  'SELECT MAX(id), MAX(timestamp) FROM connection_log; \
   SELECT * FROM connection_log WHERE drive_id=4'"
```

If Pi MAX(id) > 18564 with 2026-04-29 entries -> path-b (sync gap; will
self-resolve next boot). If Pi MAX(id) == 18564 -> path-a (writer
regression; needs code fix).

### V-4 evidence: drive_id namespace collision

Server's legacy `drive_summary` rows (auto-increment ids 1-10):

```sql
SELECT * FROM drive_summary;
id  device_id              start_time            end_time              dur  profile_id  rows  created_at
--  --------------------- --------------------- --------------------- ---  ---------   ----  -----------
 1  sim-eclipse-gst        2026-04-16 08:00:00  2026-04-16 08:06:53  413  daily       6195  2026-04-16 13:10:10
 2  sim-eclipse-gst-multi  2026-04-16 08:00:00  2026-04-16 08:02:21  141  daily       2115  2026-04-16 13:12:56
 3  sim-eclipse-gst-multi  2026-04-16 08:07:21  2026-04-16 08:09:57  156  daily       2340  2026-04-16 13:12:56  # COLLIDES with real Drive 3
 4  sim-eclipse-gst-multi  2026-04-16 08:14:57  2026-04-16 08:16:32   95  daily       1425  2026-04-16 13:12:56  # COLLIDES with real Drive 4
 5  sim-eclipse-gst-multi  2026-04-16 08:21:32  2026-04-16 08:28:25  413  daily       6195  2026-04-16 13:12:56
 7  eclipse-gst-day1       2026-04-16 08:00:00  2026-04-16 08:01:35   95  daily       1425  2026-04-16 19:35:17
 8  eclipse-gst-day1       2026-04-16 08:21:35  2026-04-16 08:23:56  141  daily       2115  2026-04-16 19:35:17
 9  eclipse-gst-day1       2026-04-16 09:03:56  2026-04-16 09:06:32  156  daily       2340  2026-04-16 19:35:17
10  eclipse-gst-day1       2026-04-16 09:21:32  2026-04-16 09:23:53  141  daily       2115  2026-04-16 19:35:17
```

`drive_statistics` rows for "drive_id=3" (computed_at 2026-04-16 13:16:08
for ALL of them) reference the legacy id-3 sim row above, NOT real Drive 3
(2026-04-23 16:36 9.5-min real road drive).

```sql
SELECT * FROM drive_statistics WHERE drive_id=4 ORDER BY parameter_name LIMIT 3;
id   drive_id  param              min      max     avg     ...   computed_at
166  4         CONTROL_MODULE_V   13.85    14.52   14.18   ...   2026-04-16 13:16:08  # NOT real Drive 4
167  4         COOLANT_TEMP       20.36    52.75   36.68   ...   2026-04-16 13:16:08
168  4         ENGINE_LOAD        14.98    19.91   15.82   ...   2026-04-16 13:16:08
```

Note `computed_at = 2026-04-16` -- predates Drive 4 (2026-04-29) by 13
days. These are stats for the legacy sim drive that happens to share the
integer 4 with the real Drive 4.

### V-5 evidence: pre-mint NULL drive_id rows

```sql
SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL AND data_source='real';
541

SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM realtime_data
WHERE drive_id IS NULL AND data_source='real' AND timestamp < '2026-04-29 13:39:18';
269   2026-04-21 02:27:10   2026-04-29 13:39:17

SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL AND data_source='real'
AND timestamp >= '2026-04-29 13:00' AND timestamp <= '2026-04-29 14:00';
348
```

Distribution: 269 pre-Drive-4-boundary (cumulative from 2026-04-21 onwards;
the 188-row server-side leftover from Session 105 morning + accumulating
since), ~79 post-Drive-4-engine-off (US-229 design: adapter-level polls
continue tagged NULL after engine_state -> KEY_OFF), the rest mid-window
boundaries.

### V-6 evidence: drive_counter

```sql
SELECT * FROM drive_counter;
1   3        # last_drive_id=3 on server; Pi has minted 4 (server passive on the counter)
```

### V-7 evidence: drive_statistics never re-computed since 2026-04-16

```sql
SELECT DISTINCT computed_at FROM drive_statistics ORDER BY computed_at DESC LIMIT 5;
2026-04-16 13:16:08
```

(Single distinct value -- no re-compute since project init.)

### connection_log day distribution (showing the BT-flap retry backlog Pi was draining)

```sql
SELECT DATE(timestamp), COUNT(*) FROM connection_log GROUP BY 1 ORDER BY 1 DESC LIMIT 10;
2026-04-28   1745
2026-04-27   3521   # ~145 entries/hour = BT retry-loop spam
2026-04-26   3520
2026-04-25   3521
2026-04-24   3520
2026-04-23   2671
```

Combined with V-3, this means: the connection_log sync DID complete the
backlog (3520 rows/day for 5 days = ~17600 rows), but Drive 4 events
(2026-04-29) are absent. Either not written to Pi, or written but unsynced
before unplug. Disambiguation needs Pi back online.

### sync_history first/last completed

```sql
first  id=1    2026-04-16 13:10:09 -> 18:10:10  rows=2132   tables=realtime_data,statistics,connection_log
last   id=241  2026-04-29 09:00:12 -> 14:00:12  rows=27     tables={"realtime_data": {"errors":0,"inserted":27}}
```

Cumulative rows synced (completed only): **87,651**.

Pattern of last 5 completed runs:

```
241  2026-04-29 14:00:12   27    realtime_data
236  2026-04-29 14:00:04   500   connection_log
235  2026-04-29 13:59:13   28    realtime_data
230  2026-04-29 13:59:05   500   connection_log
229  2026-04-29 13:58:12   28    realtime_data
```

Realtime_data syncs in 27-28 row batches (~1 second of polling per batch);
connection_log in 500-row batches. drive_summary attempts interleaved; all
148 failed.

— Rex
