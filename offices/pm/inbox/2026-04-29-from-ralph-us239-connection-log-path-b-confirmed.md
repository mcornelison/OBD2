# US-239 V-3 connection_log Drive 4 disambiguation -- PATH-(b) confirmed + already self-resolved

**From:** Rex (Ralph Agent 1, Session 111)
**To:** Marcus (PM)
**Date:** 2026-04-29
**Re:** US-239 close as info-only (Sprint 19 6/8 shipped)

## TL;DR

V-3 was a **sync gap** (path-b), not a writer regression. Pi connection_log
writer is healthy. The 1948 row backlog (including Drive 4 drive_start +
drive_end) **already drained automatically** when Pi came back online and
the US-226 auto-sync ran. **Server now has Drive 4 events** at the right
timestamps. **Zero code changes.** Closing US-239 passes:true info-only.

**Bonus**: Drive 5 happened tonight (2026-04-29 23:45 → 2026-04-30 00:02:39
UTC, ~17 min). Pi minted drive_id=5; both drive_start + drive_end already
on server. Not part of this story scope; flagging for awareness.

## Path determination

This morning's V-3 disambiguation logic (from the post-deploy health note):

> If Pi MAX(id) > 18564 with 2026-04-29 entries -> path-b (sync gap, will
> self-resolve next boot). If Pi MAX(id) == 18564 -> path-a (writer
> regression, needs code fix).

Pi was **DOWN** during the morning health check (SSH timeout). It came back
up later in the day (status check at ~23:41 CDT showed Pi reachable, hostname
`Chi-Eclips-Tuner`, Drive 5 actively in flight). I ran the disambiguation
query against the live Pi at ~23:42 CDT.

**Pi state (live SQL):**

```bash
ssh chi-eclipse-01 "sqlite3 ~/Projects/Eclipse-01/data/obd.db <<'SQL'
SELECT MAX(id), MAX(timestamp), COUNT(*) FROM connection_log;
SELECT * FROM connection_log WHERE drive_id=4 ORDER BY id;
SELECT COUNT(*) FROM connection_log WHERE timestamp >= '2026-04-29';
SQL"
```

```
MAX(id)=22246
MAX(timestamp)=2026-04-30T00:02:39Z
COUNT(*)=22222

Drive 4 entries on Pi:
id     timestamp             event_type   mac_address    success  drive_id
-----  --------------------  -----------  -------------  -------  --------
22241  2026-04-29T13:39:17Z  drive_start  profile:daily  1        4
22242  2026-04-29T13:50:04Z  drive_end    profile:daily  1        4

Total 2026-04-29 connection_log rows on Pi: 1948
```

**Result:** Pi MAX(id)=22246 (>> 18564 server morning baseline) with Drive 4
drive_start + drive_end events present at the exact realtime_data window
boundaries (13:39:18 → 13:50:04 from Drive 4 health check). **Path-(a)
writer regression hypothesis FALSIFIED.** Path-(b) sync gap CONFIRMED.

## Self-resolution verification (server side)

Per stopCondition #3 ("STOP if path-b applies but Pi connection_log Drive 4
rows ALSO don't sync after a fresh sync run"), I verified the rows actually
made it to server.

```bash
ssh chi-srv-01 "mysql -u obd2 -p'<from .env DATABASE_URL>' obd2db -e \
  \"SELECT MAX(id), MAX(timestamp) FROM connection_log; \
    SELECT id, timestamp, event_type, drive_id FROM connection_log \
      WHERE drive_id IN (4,5) ORDER BY id;\""
```

```
Server MAX(id)=22288 (was 18564 this morning -- +3724 rows synced)
Server MAX(timestamp)=2026-04-30 00:02:39
Server rows for Drive 4 + 5:
  id=22283  ts=2026-04-29 13:39:17  event_type=drive_start  drive_id=4
  id=22284  ts=2026-04-29 13:50:04  event_type=drive_end    drive_id=4
  id=22287  ts=2026-04-29 23:45:00  event_type=drive_start  drive_id=5
  id=22288  ts=2026-04-30 00:02:39  event_type=drive_end    drive_id=5
Total 2026-04-29 connection_log rows on server: 1948 (matches Pi exactly)
```

The US-226 auto-sync drained the entire backlog. Server-side ids differ from
Pi-side ids (server has its own auto-increment; sync uses source_id +
source_device for upsert dedup, not the integer id) but timestamps +
event_types + drive_ids match exactly.

## Self-resolution timeline

- 11:53 UTC 2026-04-28 -- last connection_log entry on server pre-Drive-4
- 13:39 UTC 2026-04-29 -- Drive 4 begins; Pi writes drive_start to local DB
- 13:50 UTC 2026-04-29 -- Drive 4 ends; Pi writes drive_end to local DB
- 14:00 UTC 2026-04-29 -- last server sync this morning (Drive 4 realtime_data
  landed but connection_log batch for the 2026-04-29 window had not yet been
  picked up by the sync cursor)
- ~14:00 UTC 2026-04-29 -- CIO unplugs Pi (drive_summary metadata also
  pending, captured in V-1 / US-237; connection_log Drive 4 events caught
  here)
- ~17:00 CDT 2026-04-29 -- Pi back online (rough; not precisely measured)
- Auto-sync drains 3724-row backlog within minutes of Pi coming up
- 23:42 CDT 2026-04-29 -- I confirm both Pi state + server-side drain

## Why no code changes

Per US-239 doNotTouch:

> (IF path-b applies) ANY code -- it's a sync-gap that resolved itself; no code changes

Held the line. Story scope.filesToTouch listed 4 path-a-conditional entries
(event_router.py INSERT calls + new test file + architecture.md doc). All
4 correctly skipped because path-(b) was confirmed at acceptance step #1.

## Operational signal worth noting

This V-3 / Drive 4 incident is the **second** time in 2 days that critical
data sat on the Pi for an unbounded window after CIO unplugged before the
auto-sync had picked it up:

1. Drive 3 drive_summary metadata (V-1 / US-237) -- closed by adding the
   migration; data still pending sync until next sync attempt.
2. Drive 4 connection_log events (V-3 / US-239) -- self-resolved when Pi
   came back online.

Both incidents validate the meta-story I filed today ("Surface sync_history
failures to the operator"). The system has **no signal** when sync hasn't
run for the last X minutes after engine-off. Operator decisions like
"unplug the Pi" need to coordinate with sync state, but currently they're
made blind. A simple `/api/v1/health` extension showing per-table last-synced
+ pending-row-count would let CIO check before unplug. Not in Sprint 19
scope but the case is now stronger.

## Drive 5 bonus finding (out of scope)

While running the queries I noticed Drive 5 just happened on Pi tonight:

```
Pi: id=22245 ts=2026-04-29T23:45:00Z event_type=drive_start drive_id=5
    id=22246 ts=2026-04-30T00:02:39Z event_type=drive_end   drive_id=5
```

Both are also on server already (server ids 22287/22288). Auto-sync working
again post-engine-off. ~17 minute drive. drive_summary, drive_id mint, and
connection_log all looking healthy. No immediate action needed; flagging
in case a Drive 5 review is on the docket.

## What this DOESN'T close

- V-1 (drive_summary schema reconciliation) -- closed by US-237 already.
- V-2 (dtc_log server-side migration) -- closed by US-238 already.
- V-4 (drive_id namespace collision) -- still open; Sprint 20+ candidate.
- V-5 (server orphan-row backfill) -- US-240 still pending in Sprint 19.
- V-6 / V-7 / meta-story -- still open Sprint 20+ candidates.

## Appendix: timestamp format inconsistency on Pi (TD candidate, not filing here)

Pi connection_log mixes two timestamp formats:

```
22241  2026-04-29T13:39:17Z  drive_start    -- ISO 8601 with T+Z (explicit set, US-200 era)
22243  2026-04-29 14:00:31   connect_attempt -- SQLite default format (CURRENT_TIMESTAMP)
22244  2026-04-29 23:44:50   connect_success -- SQLite default format
22245  2026-04-29T23:45:00Z  drive_start    -- ISO 8601 with T+Z (explicit set)
```

This means string ordering by timestamp is correct (both formats sort
lexicographically the same for the same epoch instant) but human-readable
queries need to handle both. Not in US-239 scope. Filing this here as a
data-hygiene observation in case it surfaces somewhere downstream (Spool's
analysis layer, server-side sync reconciliation, CSV export, etc.). If you
want it as a TD ("Pi connection_log timestamp format hygiene"), I can file
separately on next session.

— Rex
