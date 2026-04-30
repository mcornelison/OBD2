# chi-srv-01 power cycle results + drive_summary schema-drift findings

**Date**: 2026-04-29
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (P0 schema-drift finding embedded; the rest is informational)

## TL;DR

CIO power-cycled chi-srv-01 tonight. I instrumented pre/post snapshots and a continuous health monitor for the duration. Three outcomes:

1. **US-231 AC #7 (host-reboot survival) PASSED** — all three services (`obd-server`, `mariadb`, `ollama`) auto-started cleanly with `n_restarts=0` on each, MariaDB ran clean InnoDB log replay, no data loss. Ralph's deferred "if CIO willing" acceptance criterion now has live evidence. **Recommend US-231 flips to `passes:true`** in sprint.json (Sprint 18 retroactive close: 8/8 → 8/8 with the lone outstanding AC validated).
2. **drive_summary sync has been failing in production for an unknown duration. Root cause is a missing schema migration on chi-srv-01.** This is a NEW finding from the snapshot work. **Recommend P0 add-on for Sprint 19**, or hotfix story if you'd rather not interrupt Rex mid-sprint. Diagnosis + suggested fix below.
3. **One pre-cycle observation**: an 11-second health-probe outage 3 minutes before the actual power cycle. Possibly correlated with the drive_summary 500 storm; possibly unrelated. Filed for awareness, no action recommended unless it recurs.

Detailed material below.

---

## 1. Power cycle results — US-231 AC #7 PASS

### Downtime timeline (from continuous health monitor)

| Marker | Time (CDT) | Notes |
|---|---|---|
| Pre-snapshot taken | 20:10:02 | 43d 22h prior uptime |
| **DOWN** detected | **20:16:46** | CIO killed power |
| **UP** detected | **20:20:27** | first 200 from `/api/v1/health` |
| **Total offline** | **3 min 41 sec** | |
| MariaDB ready | 20:19:46 | from mariadb error log |
| obd-server `active` | 20:19:47 | systemd activation timestamp |
| Ollama `active` | 20:19:38 | independent unit, came up first |
| Post-snapshot taken | 20:27:05 | 8 min uptime |

### Acceptance grading (full)

| Gate | Result | Evidence |
|---|---|---|
| All 3 services auto-start, no operator action | ✅ | `obd-server`, `mariadb`, `ollama` all `is-active=active`, **`n_restarts=0`** on each — clean cold start, no flapping |
| obd-server waits for mariadb (`After=mariadb.service` ordering) | ✅ | both became `active` at the same wall second (20:19:47) — no race-condition restart loop |
| `/api/v1/health` returns 200 | ✅ | within seconds of network return; `components.api/mysql/ollama` all `up` |
| Ollama responds, models intact | ✅ | `qwen2.5:14b` + `deepseek-r1:14b`, **byte-identical sizes/timestamps pre-vs-post** — model files survived |
| MariaDB clean recovery | ✅ | `End of log at LSN=24786288` clean replay; buffer pool warm-load from `/mnt/raid5/databases/mysql/ib_buffer_pool` succeeded; **zero `[Warning]` or `[ERROR]` lines** in error log post-boot |
| Row counts identical or grow only via Pi sync | ✅ | see table below |
| max_id strictly monotonic | ✅ | `realtime_data.max_id` 78616→79065 (+449), exact match to row count delta — no rollback |
| Pi auto-resumes sync without manual kick (US-226) | ✅ | Pi `last_synced_at` advanced 01:09:50Z → 01:26:51Z; 65 new `sync_history` batches recorded post-boot |

### Row count delta (data-integrity gate)

```
table                pre              post              delta
realtime_data        20859 / 78616    21308 / 79065     +449 / +449  Pi backfilled cleanly
sync_history         681 / 681        746 / 746         +65          Pi pumped 65 batches in 17 min
all other tables     unchanged                          —            no orphan inserts, no losses
```

### Why the After=mariadb.service ordering matters

This is the part of US-231 that wasn't validated until tonight. Without `After=mariadb.service`, systemd would have started `obd-server` in parallel with `mariadb` on boot, and obd-server's first DB connection attempts would have hit a "Connection refused" loop. uvicorn would still come up `active` via `Restart=always`, but you'd see a flurry of restart events and stale error logs.

Instead: zero restarts on obd-server post-boot, both `active` at the same wall second. The unit file is correct. Sprint 18 US-231's hardest-to-test acceptance criterion (the one that was deferred at sprint close) is now empirically valid.

### Artifacts

- Reusable snapshot script: `offices/tuner/scripts/server_snapshot.sh`
- Full monitor trace: `offices/tuner/drills/2026-04-29-chi-srv-01-powercycle-monitor.log` (190 samples @ 3s cadence)
- Pre/post snapshot dumps: `/tmp/srv_pre.txt` and `/tmp/srv_post.txt` (ephemeral on this dev box; rotated out of `/tmp` on next windows-dev reboot)

---

## 2. drive_summary schema-drift bug — P0 finding (independent of power cycle)

### What I observed

The pre-snapshot showed live ERROR-level entries in the `obd-server` log on every Pi sync attempt:

```
Apr 29 20:08:50 chi-srv-01 uvicorn[1737523]:
  ERROR | src.server.api.sync | Sync upsert failed for batch
  chi-eclipse-01-2026-04-30T01:08:43Z:
  (pymysql.err.OperationalError) (1054, "Unknown column 'drive_summary.source_id' in 'SELECT'")

[SQL: SELECT drive_summary.source_id FROM drive_summary
      WHERE drive_summary.source_device = %s AND drive_summary.source_id IN (%s, %s, %s, %s)]
[parameters: ('chi-eclipse-01', 2, 3, 4, 5)]

INFO: 10.27.27.28:60830 - "POST /api/v1/sync HTTP/1.1" 500 Internal Server Error
```

Confirming with Pi-side state:

```
sqlite3 obd.db "SELECT table_name, last_synced_id, last_synced_at, status FROM sync_log;"

connection_log    22246      2026-04-30T00:02:39Z   ok
drive_summary     0          2026-04-30T01:26:51Z   failed   <-- the smoking gun
realtime_data     3454991    2026-04-30T01:26:51Z   ok
statistics        70         2026-04-30T00:02:48Z   ok
```

`drive_summary.last_synced_id=0` and `status=failed`. **Pi has never successfully synced a single drive_summary row to server.**

### Root cause

The server's `drive_summary` table is on a **pre-Sprint-15 schema**. Migrations only ran through `v0003_us223_drop_battery_log` (Apr 23). No migration ever modernized `drive_summary` to the schema US-206 / US-214 / US-228 expect.

**Server `drive_summary` table (current state on chi-srv-01):**
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

**Pi `drive_summary` table (current — what the server CODE expects):**
```
drive_id                 INTEGER  PK              <-- not present on server
drive_start_timestamp    DATETIME NOT NULL        <-- not present on server
ambient_temp_at_start_c  REAL                     <-- not present on server
starting_battery_v       REAL                     <-- not present on server
barometric_kpa_at_start  REAL                     <-- not present on server
data_source              TEXT NOT NULL DEFAULT 'real'  <-- not present on server
```

The server `drive_summary` still contains 9 stale rows from 2026-04-16 sim/dev data (`device_id='sim-eclipse-gst'`, `device_id='eclipse-gst-day1'`) — pre-real-data, pre-Sprint-15 truncate. Sprint 18's US-227 truncate did not touch this table because the Pi was never successfully syncing drive_summary anyway, so it wasn't on the truncate's drift watchlist.

**`schema_migrations` on server confirms the gap:**
```
version  description                                                                  applied_at
0001     US-195 data_source + US-200 drive_id / drive_counter catch-up               2026-04-22 22:12:39
0002     US-217 battery_health_log                                                    2026-04-22 22:12:43
0003     US-223 / TD-031 close -- drop battery_log                                    2026-04-23 10:32:36
```

There are **no v0004+ migrations**. Sprint 15's US-206 (`drive_summary` cold-start metadata columns), Sprint 16's US-214 (drive_summary reconciliation logic), and Sprint 18's US-228 (cold-start backfill UPDATE) were all written assuming the modernized schema — but the migration that creates that schema on chi-srv-01 was never written.

This is a **gap in Sprint 16 US-213 (server schema migration gate)** scope: the gate exists and runs at deploy time, but nobody authored the v0004 migration for `drive_summary`. So the gate has been a no-op for this table — it's never had work to do.

### Recommended fix (one new Sprint 19 story; Rex sizing)

**`v0004_drive_summary_modernize.py`** — single migration with this sequence:

1. `DROP TABLE drive_summary` — the 9 rows in there are pre-real stale sim/dev data with no value (oldest is 2026-04-16, pre-Sprint-15 truncate; all `device_id='sim-eclipse-gst'`/`eclipse-gst-day1`).
2. `CREATE TABLE drive_summary` matching the modernized schema the code expects, with the source-attribution columns (`source_id`, `source_device`) the sync code's SELECT references — these aren't on Pi either. They're synthesized by the server-side `sync.py` upsert logic to attribute each row to its origin device. (Rex will know the exact column set; I'm flagging this so the migration includes them.)
3. `INSERT INTO schema_migrations (version, description, applied_at) VALUES ('0004', 'US-228+ drive_summary modernize — server-tier catch-up to Pi schema', NOW())`.

**Acceptance test**: `bash tests/deploy/test_obd_server_service.sh` after deploy + observe Pi sync_log: `drive_summary.status` flips from `failed` → `ok` AND `last_synced_id` advances past 0. The 4 currently-orphaned Pi rows (drive_id 2, 3, 4, 5) sync up.

**Scope decision (your call)**:
- **Option A (recommended)**: **Sprint 19 add-on as a new story**. The bug is currently dropping data on the floor — every Pi sync attempt loses `drive_summary` rows. Even though all 4 currently-orphaned rows have all-NULL metadata (US-228 broken-backfill from my Sprint 19 consolidated note — see open item below), syncing them up would still let post-hoc analytics work, and would clear the 500 storm out of the obd-server log.
- **Option B**: **Sprint 20 carryforward**. The bug has been silent for weeks — you can argue another sprint of silence isn't materially worse, and Rex is mid-sprint on the Sprint 19 P0 ladder (US-216 SOC→VCELL, UpsMonitor BATTERY-detection, US-228-fix-Option-a). Adding work mid-sprint risks contract drift.

I lean Option A but understand the contract argument. Your call.

### Cross-link to my Sprint 19 consolidated note

This finding **confirms** an item I flagged in `2026-04-29-from-spool-sprint19-consolidated.md`:

> **Drive_summary sync still failing** (status=failed in sync_log) — separate from US-228 metadata bug. Worth flagging to Ralph.

That note flagged the symptom; tonight's snapshot drilled into the root cause. The two issues are now clearly separable:

1. **Schema drift** (this note) — server table is on legacy schema, no v0004 migration → every sync fails.
2. **US-228 metadata broken-backfill** (my Sprint 19 consolidated note, P0) — even when sync works, the metadata fields stay NULL because Sprint 18's UPDATE-backfill approach can't fire. Pi-side bug.

These need to be fixed in order. (1) first — otherwise (2)'s fix has no place to land. Rex can do them as one chained story or two; the migration is fast and the US-228 Option (a) work is already in his Sprint 19 contract.

---

## 3. The 11-second pre-cycle blip — observational

The continuous health monitor caught a brief outage **3 minutes before the actual power cycle**:

```
2026-04-29T20:13:50  UP
2026-04-29T20:13:56  DOWN     <-- first failed probe
2026-04-29T20:14:03  DOWN     <-- second failed probe
2026-04-29T20:14:07  UP       <-- recovered (~11 sec)
2026-04-29T20:14:11  UP
```

Two consecutive failed health probes (curl timeout=3s, cadence=3s), then recovery. Possibilities:

1. **obd-server briefly stalled under sync error load.** During this window, the Pi sync was firing 500s every batch on `drive_summary` (the schema-drift bug, see §2). Possible the error path through SQLAlchemy + pymysql + uvicorn briefly held a worker thread long enough for the health probe to time out.
2. **Network hiccup** — windows-dev → chi-srv-01 path, DNS, switch.
3. **Coincidental two-probe failure** — health endpoint genuinely fine, just two unlucky probes.

I'm not sure which. The obd-server log doesn't show anything notable in that window — no exceptions, no restart events. **No action recommended** unless it recurs after the schema-drift fix lands. If it does recur post-fix, that argues for hypothesis 2 or 3 (transient infra) and we can ignore. If it doesn't recur post-fix, retroactively that argues for hypothesis 1 (was a symptom of the 500 storm).

---

## Action items for you (PM lane)

1. **Decide on Option A vs Option B for the drive_summary schema-drift fix.** I'll defer to your sprint contract judgment.
2. **Flip US-231 to `passes:true` in sprint.json** with completedDate=2026-04-29 + a note referencing this drill log as AC #7 evidence. Sprint 18 retroactively closes 8/8 with all ACs validated, no exceptions. (This is a doc/state update only, no code. Your call whether to drop a one-line entry in `offices/pm/projectManager.md` to record the AC #7 closure.)
3. **(Optional) File a TD against Sprint 16 US-213 retroactively.** US-213 was the "server schema migration gate" story; it's been silently a no-op for `drive_summary` because the v0004 migration was never authored. The gate works as designed; the *content* (the migration list) was incomplete. Worth a TD for the post-mortem record. Low priority; not blocking anything.

## Action items for me (Spool lane, follow-on this session)

- Update auto-memory: server runs `qwen2.5:14b` + `deepseek-r1:14b`, **not** `llama3.1:8b` as my MEMORY.md says. Drift item I'll fix at closeout.
- Update auto-memory: chi-srv-01 was at 43-day uptime pre-cycle; that record breaks tonight. Reset.
- The 4 Pi-side `drive_summary` rows have all-NULL metadata (4/4) confirms my Sprint 19 consolidated note's observation about US-228. No new work — just adding "4 of 4 drives" to the failure-count for the record.

---

— Spool

## Sources / inputs

- `offices/tuner/scripts/server_snapshot.sh` (this session, reusable for future server reboots/redeploys)
- `offices/tuner/drills/2026-04-29-chi-srv-01-powercycle-monitor.log` (190 health probes @ 3s cadence)
- chi-srv-01 `obd-server.service` journal (live tail during pre-snapshot)
- chi-srv-01 `mariadb.service` error log (live tail during post-snapshot)
- chi-srv-01 `obd2db.schema_migrations` (3 rows, ending v0003)
- chi-srv-01 `obd2db.drive_summary` (9 stale dev rows, legacy schema)
- chi-eclipse-01 `obd.db drive_summary` (4 rows, current schema, all-NULL metadata)
- chi-eclipse-01 `obd.db sync_log` (drive_summary `status='failed'`)
- `Z:/O/OBD2v2/src/server/migrations/versions/` (only 3 files: v0001, v0002, v0003)
- 2026-04-28-from-ralph-us231-server-unit-shipped-deploy-pending.md (the AC #7 deferral note)
- 2026-04-29-from-spool-sprint19-consolidated.md (cross-link, drive_summary sync flag in §"Open Items")
