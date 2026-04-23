# From Marcus (PM) → Rex — Sprint 18 loaded. GO when CIO gives shell-side go.

**Date:** 2026-04-23
**Branch:** `sprint/ops-hardening` (from main@a6bfa2f)
**Baseline:** fastSuite ~3135, ruffErrors=0

## Theme: Ops-Hardening + Sync Restoration

Drive 3 (2026-04-23, 9.5 min, engine graded **EXCELLENT** per Spool) proved the Pi capture surface works. But Spool's post-deploy audit found gaps between "captured" and "usable end-to-end." Sprint 18 closes them.

## 8 stories (2M + 6S ≈ 13 points)

**P0 — sequential (anchor + cleanup)**:
1. **US-226** (M) Restore Pi→server sync — last success 2026-04-19; Drive 3's 3272 rows stuck on Pi
2. **US-227** (S, deps US-226) Pi+server truncate — 2.9M stale drive_id=1 rows

**P1 — independent, parallel-safe**:
3. **US-228** (S) Fix US-206 drive_summary NULL on cold-start (timing bug)
4. **US-229** (S) Fix drive_end not firing — ELM_VOLTAGE heartbeat filter
5. **US-230** (S) Journald persistence deploy hardening — `/var/log/journal/` still empty post-US-210
6. **US-231** (M) Server tier systemd unit — mirror of US-210 for chi-srv-01

**P2 — opportunistic**:
7. **US-232** (S) TD-035 close — SIGTERM responsiveness (retry loop → `threading.Event.wait`)
8. **US-233** (S) Pre-mint orphan-row backfill — 225 Drive 3 BT-connect-window rows

## Execution order constraint

**US-227 runs AFTER US-226 ships AND Drive 3 rows confirmed on server.** Truncate before sync = lost data. `sync_log.synced_at` cursor should cover Drive 3's timestamp range before you start US-227.

## US-226 triage shortlist (from Spool)

The sync bug is one of three likely causes — document which in your completionNotes:
1. **Config key renamed/dropped** in US-213 migration-gate refactor — top-level `pi.sync` is MISSING from deployed config. Most likely.
2. **drive_end trigger starved** — US-229 fixes drive_end, but US-226 must ALSO add interval-based sync as defensive measure (if drive_end is ever broken again, sync still runs).
3. **Orchestrator wiring dropped** SyncClient in a Sprint 15/16 refactor — less likely but possible.

Fix the actual root cause; rule out the other two with evidence.

## US-229 — ECU-sourced filter rule

Drive_end detection key: "rows still arriving from ECU-sourced PIDs only." ELM_VOLTAGE is adapter-level (ATRV command via ELM327, not ECU-dependent) — it keeps ticking after engine-off. Add `is_ecu_dependent` metadata to `PARAMETER_DECODERS` entries (all Mode 01 PIDs + DTC Mode 03/07 = True; ELM_VOLTAGE = False). Do NOT stop ELM_VOLTAGE polling — it's a legitimate battery monitor.

## US-231 — mirror US-210 exactly

Server unit needs: `Restart=always`, `RestartSec=5`, `After=network.target mariadb.service`, `User=mcornelison` (not root), `EnvironmentFile=/mnt/projects/O/OBD2v2/.env`, `Type=simple`, `WorkingDirectory=/mnt/projects/O/OBD2v2`, `ExecStart=.../uvicorn src.server.main:app --host 0.0.0.0 --port 8000`. Reuse the Sprint 16 Pi-side `cmp -s` install-if-changed pattern. One-time cutover from manual uvicorn must be clean — no port conflict.

## Spool parallel deliverables (NOT Ralph stories)

Tracked in sprintNotes:
- **First real-drive review ritual** against Drive 3 (unblocked by US-226 sync ship)
- **Update `knowledge.md` "Real Vehicle Data"** — Drive 3 supersedes Session 23 as authoritative warm-idle baseline
- **DSM DTC cheat sheet** (post-drill docs)
- **TD-033 telemetry_logger ↔ UpsMonitor audit** (20-min deliverable)

## Non-story verify (not Ralph's scope but flag if you hit it)

1853 physics_sim rows in Pi `drive_id=2` from 2026-04-23 03:12-03:14 UTC — either intentional benchtest (good — US-212 tagging works!) or unintentional leakage. If you stumble on the source while working other stories, inbox Spool/Marcus. No story unless finding demands one.

## Story counter

nextId = **US-234** (US-226 through US-233 consumed Sprint 18).

## Go when CIO says go

`./offices/ralph/ralph.sh N` from CIO's shell.

— Marcus
