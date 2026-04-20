# From Marcus (PM) → Rex — Path A approved; US-209 loaded; GO

**Date:** 2026-04-20
**Re:** `offices/pm/inbox/2026-04-20-from-ralph-us205-schema-divergence-halt.md`

## Decision: Path A. US-209 is live at the top of Sprint 15.

Your diagnosis is correct and your halt was the right call — the US-195/US-200 migrations landed in SQLAlchemy models but never ran on the live MariaDB. CI's ephemeral-SQLite shape made the gap invisible. You surfaced it cleanly via the --dry-run gate. Exactly what the stop-condition design is for.

## Sprint 15 contract updated

New execution order:
1. **US-209** (S, no deps) — server schema catch-up (ALTER TABLEs + CREATE TABLE drive_counter on live obd2db)
2. **US-205** (S, deps=[US-209]) — truncate, re-scoped to ~352K Pi-side real rows
3. **US-204** (L) — DTC + dtc_log (unblocks after US-205)
4. **US-206** (S) — drive-metadata
5. **US-207** (S) — already PASSED Session 73, nice work
6. **US-208** (M) — activity-gated first-drive validator

US-205's intent now explicitly acknowledges the ~352K 'real' rows — all benchtest/simulator activity that got the US-195 DEFAULT tag. None are in-vehicle drives. "Clean slate before first REAL drive" intent is still satisfied by deleting them all. That side-effect is CIO-approved (via me).

## The US-195 simulator-tag scope gap

You found it. `--simulate` and benchtest rows inherit `data_source='real'` because nothing overrides the DEFAULT. Not a Sprint 15 blocker — but it's a real scope gap in US-195. File a TD when you have a spare moment (TD-030?) describing: "US-195 DEFAULT 'real' tags simulator + benchtest rows as real; add explicit override in --simulate path + test fixtures." Sprint 16+ cleanup. Note in that TD that US-205 clean-slate is the pragmatic mitigation for now.

## TD-029 filing

US-209 acceptance #8 includes filing **TD-029** (server migrations not auto-applied to live DB). Recommended long-term fixes:

- **Option 1 (canonical):** adopt Alembic; server migrations become first-class versioned artifacts; deploy-server.sh runs `alembic upgrade head` as a deploy step.
- **Option 2 (minimal):** keep the per-feature `ensure*Column` / `apply_server_migrations.py` pattern, but wire them into `deploy-server.sh --init` (and maybe default deploy) as an explicit "migration gate."

Option 2 is cheaper + matches current style. Option 1 is cleaner long-term. Include both in TD-029; let CIO pick in Sprint 16+ grooming.

## What's already in working tree (your Session 72/73 work)

- `scripts/truncate_session23.py` + 22 tests — **keep**; US-205 reuses after US-209 lands.
- US-207 cleanup artifacts (TD-015/017/018/028 Closed annotations, Makefile + pm_status/sprint_lint touchups, agent.md + prompt.md edits for TD-028, `offices/ralph/agent.py`, new `knowledge/session-learnings.md` entry) — **keep; committed in sprint-close batch.**
- ralph_agents.json status=unassigned — **good, pick up US-209 next iteration.**

## Ancillary

- CIO ran server + Pi deploy earlier in Session 25 (server @ `8738751`, Pi healthy). Don't re-deploy during US-209; the script should only touch the MariaDB schema, not code.
- For the US-209 script, follow the same CommandRunner Protocol pattern you used in `truncate_session23.py` — that's already a project convention now.
- Backup path for US-209: `/tmp/obd2-migration-backup-<ts>.sql` — this is SAFER than backing up the whole DB, you only need the 4 affected tables. `mysqldump --single-transaction obd2db realtime_data connection_log statistics alert_log > /tmp/...`.

## Go.

Sprint 15 currently: **1/6 passed (US-207), 5/6 pending.** After US-209 + US-205 land, US-204/206/208 are unblocked and the P0 chain clears.

— Marcus
