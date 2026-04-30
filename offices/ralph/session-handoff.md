# Ralph Session Handoff

**Last updated:** 2026-04-29, Session 105 closeout (Rex)
**Branch:** `main` (Sprint 18 already merged + closed by Marcus@477b62c)
**Last commit:** `477b62c` chore(pm): Sprint 18 closeout — 8/8 SHIPPED, B-037 ops-hardening phase complete

## Quick Context

### What's Done

**Sprint 18 (Ops-Hardening + Sync Restoration) SHIPPED 8/8 and merged to main.**

This session (Session 105) shipped the last two stories AND ran live verification + post-deploy variance hunting:

- **US-227** (Pi+server operational truncate, S, P0) → `passes:true` 2026-04-27. Live execute on Pi (2,939,090 → 0) + server (812 → 0); Drive 3 (6,089) preserved both sides; drive_counter advanced to 3 idempotent; fixture hash unchanged. Backups landed 509 MB Pi + 1.9 MB server. New `scripts/truncate_drive_id_1_pollution.py` reuses US-205 plumbing via importlib seam. 32 new tests; specs/architecture.md §5 invariant #4 + Modification History; Spool inbox annotated.
- **US-231** (Server tier systemd unit, M) → `passes:true` 2026-04-29. New `deploy/obd-server.service` mirroring eclipse-obd shape (Restart=always, mariadb.service After=, EnvironmentFile, no inlined secrets). New `step_install_server_unit` in deploy-server.sh + cutover-aware step 5 + `sudo systemctl restart` step 6. 14 static unit-content tests + bash live test with skip-on-77 + pytest wrapper. specs/architecture.md §11 rewritten for both tiers. docs/testing.md NEW Server systemd unit verification section. TD-037 filed for stale `obd2-server.service` + `install-server.sh`.
- **First operator deploy of US-231 failed silently** (`sudo: a terminal is required` + remote heredoc had no `set -e`, so misleading 'Unit installed' echo printed despite all sudo commands failing). Patched same session: (a) `ssh -t` for sudo-bearing commands, (b) `set -e` inside heredoc, (c) smarter step-5 cutover gated on `systemctl is-active --quiet` + broader `[u]vicorn` pattern that catches the detached uvicorn child (the prior `nohup .*[u]vicorn` only matched the bash wrapper).
- **Operator re-ran deploy + AC #6 process-kill drill** — both verified live. Cutover from PID 1073743 → systemd-managed PID 1734382 active 07:59:12 CDT; AC #6 kill drill PID 1734382 → 1737523 in ~10s with bash test 5/5 PASS post-recovery. AC #7 reboot deferred per story 'if CIO willing'.
- **Sprint 18 closed 8/8** by Marcus@477b62c.

**Post-Sprint-18 work this session (post-merge, on main):**

- **CIO ran a Drive 4 test** (warm-idle garage test, 2026-04-29 13:39:18 → 13:50:04 UTC, 4,487 rows on `drive_id=4`). Pi unplugged after.
- **Health check + variance hunt** ran from windows-dev session. Pi unreachable as expected; server healthy (uptime 3h+, lastSync=14:00:12 UTC, /api/v1/health=200).
- **7 variances filed** in `offices/pm/inbox/2026-04-29-from-ralph-post-deploy-system-health-drive4.md` (593 lines, 26 KB) with raw query evidence + recommended Sprint 19 story shapes + suggested meta-story.

### What's In Progress

Nothing in progress for Ralph. Next session works from Sprint 19 spec (Marcus is grooming).

### What's Blocked

Nothing blocked. Sprint 19 grooming is on Marcus + Spool; Ralph is unassigned awaiting next sprint contract.

**Awareness items (not Ralph blockers, but next session should know):**

- **Spool's `2026-04-29-from-spool-sprint19-consolidated.md`** is the canonical Sprint 19 input. Three test events today (Drain test 4, Drive 4, Drive 5). Spool's must-fix list (Sprint 19 P0):
  - **P0 #1** US-216 SOC ladder STILL not firing (4th drain test in 9 days)
  - **P0 #2** US-228 cold-start metadata 4th NULL across drives 3, 4, 5 (and Drive 5 in-flight)
  - **P0 #3** MAX17048 SOC% calibration egregiously broken
- **My variance report covered Drive 4 only;** Spool's note adds Drive 5 (cold-start → warm-idle, 17:39 min, 489 ECU samples per PID) and confirms US-229 fired correctly on BOTH Drive 4 and Drive 5 — which adds nuance to my V-3 "Drive 4 connection_log missing." Most likely path-(b) sync-gap, not a writer regression.
- **B-047 Pi self-update from server release registry** filed by CIO directive (4 sub-stories US-A through US-D). Backlog item already in `offices/pm/backlog/B-047-pi-self-update-from-server-release-registry.md`.

### Test Baseline

- **Fast suite: 3350 passed / 18 skipped / 19 deselected / 0 regressions / 0 failures in 758.86s (12:38)** — measured 2026-04-28 evening after the regression-fix re-run for US-231.
- Was 3304 / 17 pre-Session-105. +14 static unit-content tests + +1 skipped live `test_obd_server_service_install` (deploy-pending → now passing post-deploy; will pass not-skip on next fast-suite run since the unit is now installed on chi-srv-01).

### Sprint State

- **Sprint 18 SHIPPED 8/8** — closed by Marcus@477b62c 2026-04-29.
- All stories `passes:true`. completedDates 2026-04-23 (six stories), 2026-04-27 (US-227), 2026-04-29 (US-231).
- `offices/ralph/sprint.json` still reflects Sprint 18; will be replaced by Sprint 19 contract when Marcus loads it.
- **Story counter:** nextId = US-234 (US-226–US-233 consumed Sprint 18).

### Agent State

- **Rex** (Agent 1, windows-dev): unassigned, lastCheck 2026-04-29
- Agent2 / Agent3 / Torque: unassigned (no recent activity)

## What's Next (priority order)

1. **Wait for Marcus's Sprint 19 contract.** When sprint.json refreshes, read Spool's `2026-04-29-from-spool-sprint19-consolidated.md` first (canonical input) + my `2026-04-29-from-ralph-post-deploy-system-health-drive4.md` (V-1 through V-7 + suggested meta-story).
2. **High-probability Sprint 19 stories** the next Ralph should expect:
   - US-216 SOC ladder fix (P0; 4 failed drain tests is enough evidence)
   - drive_summary 3-way schema reconciliation (V-1; one migration unblocks all Pi→server drive metadata; 148 silent failures and counting)
   - dtc_log server-side migration (V-2; next DTC = data loss)
   - US-228 cold-start NULL fix (Spool's P0 #2; Drive 4 was warm-restart so backfill correctly skipped, but Drive 3 + Drive 5 cold-starts still NULL means the backfill-window logic isn't doing what it should)
3. **When Pi powers up next**, disambiguate V-3 (Drive 4 connection_log missing) with the one-line probe documented in the variance report:
   ```bash
   ssh chi-eclipse-01 "sqlite3 ~/Projects/Eclipse-01/data/obd.db \
     'SELECT MAX(id), MAX(timestamp) FROM connection_log; \
      SELECT * FROM connection_log WHERE drive_id=4'"
   ```
   Pi MAX(id) > 18564 → sync gap (path-b, self-resolves on next sync). MAX(id) == 18564 → writer regression (path-a, code fix story).

## Key Learnings from This Session

(Detailed in `offices/ralph/knowledge/session-learnings.md`; surfaced here are the load-bearing ones.)

- **`ssh -t` and `set -e` are paired invariants for any sudo-bearing remote heredoc.** Either alone is a footgun. Without -t, sudo can't prompt → silent failure. Without set -e, the failure prints a misleading success-echo. Both belong in any future deploy-template touching `ssh $HOST "...sudo..."`.
- **`pkill -f` patterns must match the actual cmdline of the process you want dead, not its launcher.** `nohup cmd &` creates a bash wrapper holding `nohup ...` + a detached child holding only `cmd`. Killing the wrapper does NOT kill the child. The narrower `nohup .*[u]vicorn` pattern caused a sneaky long-lived orphan. Broader patterns are correct AND should be gated on `systemctl is-active --quiet` to avoid racing with the unit's own restart on subsequent deploys.
- **Schema reconciliation is fundamentally a 3-way problem when an ORM is involved.** drive_summary has Pi schema, server actual table, AND server ORM model — all three diverged independently. US-214's reconciliation only addressed two of the three. Future schema work needs all three reading from a canonical definition (Alembic + shared models, ideally).
- **A 100% sync failure for one table doesn't break the others.** drive_summary fails every attempt; realtime_data + connection_log keep flowing. Good for resilience; bad for visibility — sync_history shows mixed pass/fail and the operator sees `lastSync=recent` without knowing one table is silently dead. **148 failures vs 93 successes (60%) is a loud signal that wasn't surfaced anywhere.** Worth a dedicated story (suggested as a meta-story in the Sprint 19 inbox note).
- **The Bash tool can't allocate a TTY.** When testing patches that use `ssh -t`, the local Bash tool execution fails with 'Pseudo-terminal will not be allocated.' Don't try to validate `ssh -t` flow from the agent side; document the operator-side workflow and use the user-prompt `! <cmd>` prefix to have the operator run interactive commands during testing.
- **The cheapest server-side health-and-variance probe is one Python helper invocation:**
  ```python
  from importlib.util import spec_from_file_location, module_from_spec
  from pathlib import Path
  spec = spec_from_file_location('h', 'scripts/truncate_drive_id_1_pollution.py')
  m = module_from_spec(spec); spec.loader.exec_module(m)
  addrs = m.loadAddresses(Path('deploy/addresses.sh'))
  creds = m.loadServerCreds(addrs)
  print(m._runServerSql(addrs, creds, 'SELECT ...', m._defaultRunner).stdout)
  ```
  Reuses the DSN parsing + SSH plumbing from US-205/US-227. Add this to any future health-check or deploy-validation work.
- **The post-deploy variance hunt is high-leverage.** This session's hunt found V-1 (148 silent failures over multi-day window), V-2 (entire missing table), V-3 (entire missing event stream). All would have continued bleeding indefinitely without the hunt. Next session's pattern: any time CIO runs a real drive, do a server-side health pass and surface variances proactively.
