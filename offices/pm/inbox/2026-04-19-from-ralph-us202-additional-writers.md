# From Ralph → Marcus (PM) — US-202 stopCondition #4 triggered: 8 additional capture-table writers outside TD-027 spec

**Date:** 2026-04-19 (Session 60)
**Context:** US-202 (TD-027 fix) — stopCondition #4: "STOP if grep finds >5 additional INSERT-with-timestamp call sites not in TD-027 spec — audit them and file findings to PM before silent-sweeping."

## TL;DR

I fixed the 4 explicit writers named in the TD-027 spec (sync_log, switcher, data_retention, drive/detector) and the 6 schema DEFAULTs. While auditing via `rg "INSERT INTO (connection_log|alert_log|battery_log|power_log|realtime_data|statistics)"`, I found **8 additional explicit-timestamp writers** that are NOT in the TD-027 spec. I did NOT silent-sweep them (per stopCondition #4). They're listed below with naivety status so you can decide whether to expand Sprint 14 scope or file as Sprint 15+ follow-up.

## What I fixed in US-202 (the 4 spec'd writers)

| File:line | Old | New |
|-----------|-----|-----|
| `src/pi/data/sync_log.py:136` | inline `datetime.now(UTC).strftime(...)` | routes through `utcIsoNow()` |
| `src/pi/profile/switcher.py:607` | `event.timestamp` (naive) | `utcIsoNow()` |
| `src/pi/obdii/data_retention.py:457` | `datetime.now()` (naive) | `utcIsoNow()` |
| `src/pi/obdii/drive/detector.py:616` | `timestamp` param (naive caller) | `utcIsoNow()` |

Plus `src/pi/obdii/obd_connection.py:445` — verified uses DEFAULT path, no Python change needed post-schema-update.

## The 8 additional writers I found but did NOT touch

All are capture-table writers (same 6 tables in TD-027 scope), all use the same anti-pattern of passing a Python datetime that is naive or could be naive. Session 23's Pi data shows 2 of them (below) already caused format drift in `connection_log`.

### Confirmed naive (certain format-drift contributors)

| # | File:line | Table | Source | Naivety |
|---|-----------|-------|--------|---------|
| 1 | `src/pi/power/power_db.py:131` | `power_log` | `datetime.now()` (direct) | **Naive local time** — exactly the Thread 2 bug |
| 2 | `src/pi/obdii/data\logger.py:197` | `realtime_data` | `reading.timestamp` from upstream `datetime.now()` at `realtime.py:399` | **Naive local time** |
| 3 | `src/pi/obdii/data/helpers.py:95` | `realtime_data` | `reading.timestamp` (same upstream pattern) | **Naive local time** |
| 4 | `src/pi/analysis/engine.py:672` | `statistics.analysis_date` | `analysisDate` from `engine.py:264` `datetime.now()` | **Naive local time** |
| 5 | `src/pi/alert/manager.py:489` | `alert_log` | `event.timestamp` via `AlertEvent.__post_init__` at `alert/types.py:167` `datetime.now()` | **Naive local time** |

Writers 2 and 3 are the reason Session 23's **realtime_data** rows show timestamps like `2026-04-19 07:18:50.697867` (Chicago local) instead of `2026-04-19T12:18:50Z` (UTC canonical). The 149 captured rows are NOT in canonical format. US-202 invariant #1 (no backfill) protects them as forensic data, but **US-197's regression fixture export will inherit that format drift** unless the Pi collection path is fixed before the next drill.

### Ambiguous (caller determines naivety)

| # | File:line | Table | Source | Naivety |
|---|-----------|-------|--------|---------|
| 6 | `src/pi/power/battery.py:546` | `battery_log` | `reading.timestamp` (BatteryReading) | Likely naive — battery monitor ingest uses naive `datetime.now()` |
| 7 | `src/pi/power/power_db.py:55` | `power_log` | `reading.timestamp` | Same likely-naive pattern |
| 8 | `src/pi/power/power_db.py:94` | `power_log` | `timestamp` param | Caller-dependent |

### Clean (uses DEFAULT path — no Python timestamp — canonical post-US-202 schema)

- `src/pi/obdii/obd_connection.py:445` ✓ (already verified in US-202)
- `src/pi/obdii/shutdown/command_core.py:361` ✓
- `src/pi/obdii/shutdown/manager.py:285` ✓

These three will start producing canonical timestamps automatically as soon as the US-202 schema change deploys. No code change needed.

## Why this matters for Sprint 14 beyond US-202

**US-195** (`data_source` column on capture tables) — the acceptance says filters compose correctly with time windows. Filters will work on canonical-format rows written by the 4 fixed writers. Filters will NOT work correctly on rows written by writers 1–5 above: `realtime_data` (#2, #3) and `statistics` (#4) are the highest-volume writers in the system. If US-195 ships without expanding the sweep, the capture tables remain half-canonical / half-naive-local.

**US-197** (regression fixture export) — the fixture is exported FROM the Pi's `obd.db`. Session 23's existing rows are already mixed format (per Invariant #1 — we're not backfilling). If a second drill happens before writers 2 and 3 are fixed, the fresh rows will STILL be naive-local. The fixture then captures the bug.

**US-195 + US-197 are effectively at risk of landing on a surface that still exhibits the underlying problem.** That was the exact concern that motivated filing TD-027 as blocking these two stories.

## Options for you (same structure as my original TD-027 note)

### Option (a) — **Expand US-202 scope now** [recommended]

Fix all 5 confirmed-naive writers (rows 1–5) plus audit + fix writers 6–8 in the same story. Add ~5 test cases to `test_timestamp_format.py` covering realtime_data + alert_log + statistics + battery_log + power_log explicit-path shape parity with DEFAULT. Story stays size S → M bump likely. No new story needed.

**Pro**: unblocks US-195 + US-197 with confidence. Matches the spirit of TD-027 (one-shot sweep to eliminate the class of bug, not half-measure). Cheapest to do while I have all the context loaded.

**Con**: pushes US-202 to M, exits stopCondition #4 territory on purpose.

### Option (b) — **File a new story US-203 immediately**

New story at front of Sprint 14 covering the 8 additional writers. US-195 + US-197 depend on US-203 + US-202.

**Pro**: respects stopCondition #4 as written (no silent-sweep). Clean sprint-contract separation.

**Con**: more sprint-bookkeeping overhead. I hand off context to whoever picks up US-203 (may be me next iteration anyway).

### Option (c) — **Defer to Sprint 15+ with a US-195/US-197 stop condition**

Add explicit stopConditions to US-195 + US-197: "STOP if capture tables contain rows with format mismatch in the time window — means unaddressed upstream naive writer."

**Pro**: minimal Sprint 14 churn.

**Con**: US-195 + US-197 will likely trip the stop condition on first touch and end up doing the work anyway — scope creep downstream of where it belongs.

### Option (d) — **Waive**

Accept that US-195 + US-197 land on partially-canonical capture tables and file a Sprint 15+ TD to clean up.

**Pro**: fastest to move US-195 + US-197 forward.

**Con**: partially defeats the purpose of US-202. Some capture rows never reach canonical format.

## My recommendation

**Option (a)**. The 5 confirmed writers are all structurally identical to the 4 I already fixed — same pattern, same helper call, same test shape. I have all the context loaded right now; expanding scope mid-story is cheaper than handing off. The remaining 3 ambiguous writers need 20 minutes of upstream tracing to confirm naivety; that's cheap from inside the current session.

If you prefer clean sprint-contract discipline, Option (b) is fine too — I'd just pick up US-203 as the very next iteration.

## What I'm doing right now

- US-202 proper (the 4 spec'd writers + schema + helper + tests + specs) is **complete and green**.
- This note is filed.
- Closing US-202 in sprint.json with `passes: true` and completionNotes referencing this note.
- Exiting Ralph agent state to `unassigned` per Rule 8.

If you approve Option (a) or (b), let me know in Ralph's inbox and I'll pick it up next iteration.

— Rex (US-202 closed, awaiting your call on US-203 scope)
