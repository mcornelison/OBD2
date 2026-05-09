# Post-DB-cleanup housekeeping findings — 4 items for Sprint 28 grooming
**Date**: 2026-05-09
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (one P1 reclassification, three grooming items)

## Context

Mike asked me to clean up the server analytics DB now that drives 6 + 7 give us a usable empirical baseline. Cleanup is done — `obd2db` on chi-srv-01 went from ~131k rows of mostly bench-poll noise down to a clean dataset of 5 keep-drives (3, 4, 5, 6, 7) plus the 9 real `battery_health_log` events. While profiling the DB I found 4 things that don't belong on Spool's desk — they belong on yours, in Sprint 28 grooming or behind it.

What I dropped: ~58,885 NULL-`drive_id` realtime_data rows (engine-off bench polls), ~28,000 reconnect-loop spam rows in `connection_log`, all 84 `statistics` rows (computed against polluted data), 4 stale `trend_snapshots` rows from 2026-04-16, the orphan `drive_summary` row for sim-era drive_id=2, and 0 sync_history rows under 30-day retention. `mysqldump` backup taken first; transactional with sanity-check SELECT before COMMIT.

---

## Item 1 — `baselines` table does NOT exist on the live server

**Finding**: `src/server/db/models.py` defines a `Baseline` SQLAlchemy model (line 703–728) for CIO-approved per-parameter baseline values, written by `src.server.analytics.calibration` under `--calibrate --apply`. **The table itself is not in the live `obd2db` schema.** I ran `SHOW TABLES;` and confirmed.

**Why this matters now**: With drives 5 + 6 + 7 in hand, this is the moment we'd normally calibrate per-PID baselines and start grading future captures against them. Without the table (and the migration that creates it, and the CLI flow), the calibration workflow Spool would otherwise recommend isn't runnable.

**Action for grooming**: Triage with Rex. Three possibilities:
1. Migration drift — a migration creating the table was written but never deployed to chi-srv-01.
2. Feature spec'd, never shipped — the model exists in code as a stub; the migration + CLI never landed.
3. Baselines workflow superseded — analytics moved to a different table (`drive_statistics`?) and the model is dead code.

**Spool recommendation**: If it's #1 or #2, this becomes a Sprint 28 or Sprint 29 candidate — "ship the baselines workflow + migration + CLI + analytics consumer." We have the data to make it valuable now. If it's #3, kill the dead model in `models.py`.

---

## Item 2 — `drive_summary` writer regression is P1, not P2

**Status update**: I filed this as P2 yesterday in `2026-05-08-from-spool-drive-6-7-grades-engine-healthy-under-wot.md`. **Reclassifying to P1 after seeing the actual DB state.**

**What I thought yesterday**: drives 6 + 7 have `drive_end` events but no `drive_summary` rows.

**What's actually true**: drives 6 + 7 have NO summary rows AND drives 3, 4, 5 have rows where **every analytics column is NULL** — `start_time`, `end_time`, `duration_seconds`, `row_count`, `is_real`, `data_source` are all NULL on all three rows. The Pi-sync side wrote the `source_id` / `source_device` / `drive_id` keys; the analytics path that's supposed to populate the rest never ran for any drive.

**Downstream impact** (this is the P1 part):
- `analysis_history` = 0 rows. The AI analysis path can't see drives at all.
- `drive_statistics` = 0 rows. Per-drive per-parameter stats don't exist.
- The dashboard's "drives list" view (whatever the equivalent server-side surface is) shows drives without metadata.
- Any future "Spool, grade drive 8" workflow that joins `realtime_data` with `drive_summary` will get nulls.

**Diagnosis pointer**: per `models.py` line 555–565, the analytics-side writer is `src.server.services.analysis._ensureDriveSummary`, supposed to fire at drive-end via the auto-analysis trigger. Either the trigger isn't wired, the function bails early, or the auto-analysis path itself is dead. Rex would be faster than me at finding the actual break point.

**Spool recommendation**: P1, ahead of the V0.27.2 bug-fix work that's already on the docket. Without `drive_summary` populated, all our analytics tables are downstream-blocked.

---

## Item 3 — Connection log noise pattern is a code smell

**Finding**: The Pi was hammering the OBD adapter with reconnect attempts at ~2,640 per day during Apr 24–28 (5 consecutive days, no driving, just bench-running). That's roughly one connect attempt every ~33 seconds, 24/7.

| Day | connect_attempt | connect_failure |
|---|---:|---:|
| 2026-04-24 | 2,640 | 440 |
| 2026-04-25 | 2,641 | 440 |
| 2026-04-26 | 2,640 | 440 |
| 2026-04-27 | 2,640 | 440 |
| 2026-04-28 | 2,641 | 440 |

The Sprint 27 V0.27.1 hotfix added a 10s heartbeat + 30s connect timeout. That implies a worst-case ~2,400 connect_attempt + ~3,600 heartbeat rows per day on a bench-running Pi. **Whether this is healthy reconnect telemetry or runaway log spam depends on whether the new code suppresses logs once disconnected for >N minutes**, and that's a question I can't answer from the data alone.

**Action**: not for Sprint 28, but worth a Marcus/Rex check after V0.27.2 deploys. Re-profile `connection_log` daily growth rate. If we still see ~3k+ rows/day on a quiet day, log suppression / event-coalescing should be on the Sprint 29 candidate list. Connection_log shouldn't outpace `realtime_data` by ~30:1 the way it currently does.

This is also a useful project-wide observation: **`connection_log` daily row count is a free signal for "is the Pi running on bench right now?"** — could be useful for future diagnostics or a regression test.

---

## Item 4 — `battery_health_log`: 5 of 9 drains have NULL `end_timestamp`

**Finding**: Of the 9 drain events in `battery_health_log`, only 4 have a populated `end_timestamp` (and matching `end_soc` + `runtime_seconds`). The other 5 are NULL on close-fields — these are drains where the Pi died before the close-event row write completed.

| drain_event_id | start_timestamp | end_timestamp | runtime_s | Status |
|---:|---|---|---:|---|
| 1 | 2026-05-04 13:21:08 | NULL | NULL | unclosed |
| 2 | 2026-05-04 13:29:09 | 2026-05-04 13:29:14 | 5 | closed |
| 3 | 2026-05-04 13:29:34 | NULL | NULL | unclosed |
| 4 | 2026-05-04 18:58:48 | NULL | NULL | unclosed |
| 5 | 2026-05-04 19:32:47 | NULL | NULL | unclosed |
| 6 | 2026-05-05 23:59:16 | 2026-05-05 23:59:31 | 15 | closed |
| 7 | 2026-05-06 00:00:21 | NULL | NULL | unclosed |
| 8 | 2026-05-09 01:24:04 | 2026-05-09 01:36:45 | 761 | closed (12.7-min Drain 8) |
| 9 | 2026-05-09 01:47:10 | NULL | NULL | unclosed (Drain 9 from yesterday) |

**Already on Sprint 28 docket as P3** per Mike's 2026-05-09 morning note (drain_event_id=9 specifically). This finding extends it: it's a recurring class of bug (5 occurrences, not 1), happening whenever the V0.24.1 ladder fires `systemctl poweroff` faster than the close-event row commits.

**Spool recommendation for Sprint 28 grooming**: keep at P3 (data hygiene, not safety-critical), but spec it as the broader fix: "battery_health_log close-event writes survive `systemctl poweroff` race." Two implementation options worth Rex's input:

1. **Pre-poweroff close-event flush** — orchestrator's `_enterTrigger` writes the close-event BEFORE calling `systemctl poweroff`, with `os.fsync()` + `PRAGMA synchronous=FULL` (same pattern as US-267 from Sprint 22).
2. **Boot-time backfill** — at next boot, `startup_log` writer detects unclosed `battery_health_log` rows older than the most recent `prior_boot_clean=False` boundary and stamps a synthetic `end_timestamp` from boot-reason data. Less precise but resilient to any future race.

I'd vote (1) — same pattern we already validated. (2) only if (1) is harder than expected.

---

## What I want from you

1. **Item 2 reclassification**: bump the `drive_summary` writer regression from P2 to P1 in your Sprint 28 candidate list. Without it, all downstream analytics + AI are blind.
2. **Item 1 grooming question**: ask Rex which of the three possibilities applies to the missing `baselines` table, and let me know — that determines whether we add a "ship baselines" story or kill dead model code.
3. **Item 3**: just put a Sprint 29 candidate placeholder on the radar — "post-V0.27.2 connection_log noise re-profile."
4. **Item 4**: extend the existing P3 from "drain_event_id=9 didn't close" to the broader "5 of 9 drain rows have NULL close-fields, fix the close-write race." Same Sprint 28 P3 slot, just with corrected scope.

Engine-side: drives 5 + 6 + 7 give us our first complete pre-mod baseline shelf and the engine itself is graded healthy across the full envelope. The work I want from Sprint 28 isn't on the engine — it's on the analytics infrastructure that feeds Spool the grading it needs to do its job.

— Spool
