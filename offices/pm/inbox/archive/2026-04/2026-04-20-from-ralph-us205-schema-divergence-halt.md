# US-205 halted at --dry-run: server schema divergence — need direction

**Date:** 2026-04-20
**From:** Rex (Ralph agent, Session 72)
**To:** Marcus (PM) + Spool
**Priority:** Blocker — Sprint 15 US-204 depends on US-205
**Re:** Sprint 15 US-205 "Session 23 operational truncate + drive_counter reset"

## TL;DR

I built + tested `scripts/truncate_session23.py` per spec (22 unit tests green). Ran `--dry-run` against live Pi + server. **I did NOT run `--execute`.** The script refused it automatically per stopCondition #4 after finding **9 divergence reasons** — mostly US-195 and US-200 never ran on the live MariaDB. Need your call before I can proceed.

## What I built

- `scripts/truncate_session23.py` (~520 lines, Python stdlib-only, SSH-orchestrated)
  - `--dry-run` scans Pi + server state, runs orphan scan, verifies fixture SHA-256
  - `--execute` requires prior `--dry-run` (sentinel file gate) AND zero divergence reasons
  - Auto-stops Pi `eclipse-obd.service` before DELETEs (DB lock issue I hit during audit)
  - Backs up Pi DB via `sqlite3 .backup` + server via `mysqldump --single-transaction` BEFORE any DELETE
  - Transactional DELETEs (SQLite `BEGIN IMMEDIATE;` on Pi, `START TRANSACTION;` on server)
  - Re-checks fixture SHA-256 post-execute (regression guard)
- `tests/scripts/test_truncate_session23.py` (22 tests: 22 pass)
  - Injects `CommandRunner` Protocol so no SSH/network in tests
  - Covers: DSN parsing, addresses.sh sourcing, divergence detection (6 cases), Pi state scan with canned rows, report rendering, CLI safety gates, sentinel round-trip

## What --dry-run found

```
Pi (chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db):
  realtime_data:  352,508 rows, ALL tagged data_source='real'
                  (149 from Session 23 on 2026-04-19 + 352,359 from 2026-04-20 benchtest)
                  Range: 2026-04-19 07:18:50 .. 2026-04-20 19:00:30
  connection_log: 18 rows 'real'
  statistics:     11 rows 'real'
  alert_log:      0 rows, data_source COLUMN ABSENT (intentional — not in CAPTURE_TABLES)
  drive_counter.last_drive_id = 1   (already incremented from the 2026-04-20 runs)

Server (chi-srv-01 MariaDB obd2db):
  realtime_data:  26,765 rows — NO data_source column, NO drive_id column
  connection_log: 34 rows — NO data_source, NO drive_id
  statistics:     75 rows — NO data_source, NO drive_id
  alert_log:      0 rows — NO data_source, NO drive_id
  drive_counter:  TABLE DOES NOT EXIST

Orphan scan (Session 23 window on server):
  ai_recommendations: 0 rows  ← clean
  calibration_sessions: 0 rows ← clean

Regression fixture:
  data/regression/pi-inputs/eclipse_idle.db
  sha256=0b90b188... (188,416 bytes) ← matches metadata.json baseline
```

## Two things the spec didn't anticipate

### Problem 1 — US-195 + US-200 never ran on live MariaDB

The server-side migrations (data_source column, drive_id column, drive_counter table) were shipped as SQLAlchemy model changes in US-195 (Session 65) and US-200 (Session 66) but never applied to the live MariaDB via `CREATE TABLE`/`ALTER TABLE`. The model code was tested against ephemeral SQLite in CI, so the gap went unnoticed.

Evidence: `SHOW COLUMNS FROM realtime_data` on `obd2db` returns only the pre-US-195 columns (id, source_id, source_device, synced_at, sync_batch_id, timestamp, parameter_name, value, unit, profile_id). No `data_source`. No `drive_id`.

Spec's `WHERE data_source='real'` filter is therefore **impossible to express** against the live server tables. The spec acceptance criterion #5 (`DESCRIBE dtc_log` — sorry, I meant `SELECT COUNT(*) WHERE data_source='real'` on server) fails with `ERROR 1054 (42S22): Unknown column 'data_source'`.

### Problem 2 — Pi `data_source='real'` scope is 2000× the documented count

Spool's truncate-request doc expected 149 realtime_data + 16 connection_log + 11 statistics rows (all from Session 23). Reality:

| Table | Spec expected 'real' | Actual 'real' | Delta |
|-------|----------------------|---------------|-------|
| realtime_data | 149 | 352,508 | +352,359 |
| connection_log | 16 | 18 | +2 |
| statistics | 11 | 11 | 0 |

Root cause: US-195 set `DEFAULT 'real'` on the `data_source` column. Every row written by `eclipse-obd.service` after that — including CIO benchtest / verify_live_idle.sh / --simulate mode — inherits the `'real'` tag because nothing else explicitly tags it. The Pi was running all day on 2026-04-20 (benchtest activity), and those rows look identical to Session 23 rows under the `data_source='real'` filter.

**The intent ("clean slate before first real drive") is still satisfied by DELETEing all 352K 'real' rows** — none of them are from actual in-vehicle drives. The Pi is stationary (not yet wired to car accessory line per shared memory). But that's a big surprise count that the CIO should consciously approve.

## Proposed paths

Pick one. I built the script to handle whichever you choose.

**Path A — Fix server schema first, then run US-205 as specified.**
New story (size S): run `data_source.py::ensureAllCaptureTables` + `drive_id.py::ensureAllDriveIdColumns` + `ensureDriveCounter` as Alembic migrations (or raw-SQL migrations consistent with spec US-195 / US-200 plumbing) on live MariaDB. After that ships, US-205 runs cleanly with both hosts in sync. Cleanest ordering; US-204 (DTC mirror table) would benefit since DTC sync also depends on the server-side data_source + drive_id columns.

**Path B — Pi-only truncate now; defer server truncate to "Path A" story.**
Tweak US-205 scope: Pi truncate + drive_counter reset runs today, server is skipped with a documented reason. Risk: server-side Session 23 rows (and 26,765 other real rows) persist; first real drive shows `drive_id=1` on Pi but NULL on server until the schema migration lands. Analytics mixed-state for a short window. Feels brittle.

**Path C — Narrow Pi filter to Session 23 timestamp window; leave server untouched.**
Change filter to `WHERE timestamp BETWEEN '2026-04-19 07:18:50' AND '2026-04-19 07:20:41'`. Removes exactly Session 23's 149 rows but leaves 352K post-Session-23 benchtest rows behind. drive_counter stays at 1 (first real drive becomes drive_id=2). Does NOT match the spec's stated intent.

**My recommendation: Path A.** It's the smallest correct fix. US-205 as written then runs clean. US-204 (DTC server mirror) and US-206 (drive_summary server mirror) both need the same server-side schema catchup anyway — doing it once up front unblocks all of Sprint 15's server-side work.

## What I already did safely

- **Pi service was stopped** for the state audit (DB had a write lock), then **restarted** (`systemctl is-active` = active). No service outage beyond the audit window.
- **No mutations.** Script refused --execute. The dry-run sentinel was removed after the run — clean state.
- **Fixture hash was not touched.** `data/regression/pi-inputs/eclipse_idle.db` matches its metadata.json baseline.
- `orphan scan` confirmed `ai_recommendations` and `calibration_sessions` have zero rows in the Session 23 window — good data hygiene, no surprise cascades.

## What I'm doing next (low-risk bookkeeping)

- Update `specs/architecture.md` §5 Drive Lifecycle Invariant #4 — note that Session 23 truncate is **pending server schema catchup** (referencing this inbox note). Do NOT remove Invariant #4 yet since NULL-drive_id rows still exist on Pi.
- Mark US-205 `passes: false` with full `completionNotes` pointing at this file.
- Set ralph_agents.json Agent 1 (Rex) to `unassigned` so the next Ralph iteration can pick up a different story (e.g., US-207 4-TD cleanup, which has no US-205 dependency).

## Files this session

**Net new:**
- `scripts/truncate_session23.py` (new, 520 lines) — full orchestrator, safe-by-default
- `tests/scripts/test_truncate_session23.py` (new, 353 lines) — 22 tests, all pass

**Intended touch next (small):**
- `specs/architecture.md` §5 footnote
- `offices/ralph/sprint.json` — US-205 feedback block
- `offices/ralph/ralph_agents.json` — status=unassigned
- `offices/pm/inbox/` — this note
- `offices/tuner/inbox/` — parallel short note to Spool
- `offices/ralph/progress.txt` — session log

Your call on path. I'm standing down on US-205 --execute until you respond.

— Rex (Ralph, Session 72)
