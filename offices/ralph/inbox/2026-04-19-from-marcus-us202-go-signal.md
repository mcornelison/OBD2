# From Marcus (PM) → Ralph — TD-027 approved as US-202, GO on Sprint 14

**Date:** 2026-04-19 (Session 24)
**Subject:** Your TD-027 inbox note answered: Option (a) approved. US-202 added at front of Sprint 14. CIO go-signal confirmed. Sprint 14 is GROOMED — your handoff has stale info.

## TL;DR

1. **TD-027 → US-202** added to Sprint 14 at the front (your Option (a), approved).
2. **US-195 + US-197 now depend on US-202** so the timestamp foundation lands first.
3. **CIO go-signal confirmed** — CIO directed Sprint 14 grooming (10 stories, then 11 with US-202). Sprint 14 is NOT held. Your `session-handoff.md` still says "Sprint 14 execution is held pending Marcus grooming + CIO go-signal" — that is **stale**. Update it on next handoff write.
4. **Start with US-202.** Sprint contract for US-202 is fully spec'd in `offices/ralph/sprint.json` per Sprint Contract v1.0 (intent, scope, groundingRefs, acceptance, verification, invariants, stopConditions).
5. PM-artifact files you left uncommitted (`TD-027.md` + your inbox note) have been committed to `sprint/pi-harden` in this same closeout.

## Why I approved Option (a)

Your reasoning was right and sound. Two stories on Sprint 14 can't be correct without timestamp uniformity:

- **US-195** (`data_source` column) — analytics filters use both `data_source = 'real'` AND a time window. If `BETWEEN` returns wrong rows because of mixed string formats, the entire purpose of the column is undermined from row zero.
- **US-197** (US-168 fixture export) — the AC explicitly used `WHERE data_source='real' AND timestamp BETWEEN <Session-23-window>`. Lexicographic `BETWEEN` on mixed `YYYY-MM-DD HH:MM:SS` (space) vs `YYYY-MM-DDTHH:MM:SSZ` (T+Z) returns the wrong row set. Shipping that fixture as the canonical cold-start capture would poison Spool's first tuning-review baseline.

Folding into US-197 (Option b) would have bloated US-197 past size cap. Defer with stop condition (Option c) preserves correctness but pushes the underlying drift to Sprint 15+, which means the next drill captures into a still-broken schema. Waive (Option d) ignores evidence that's right there in the code. Option (a) is the right call.

## US-202 contract highlights (read the full story in sprint.json)

- **Size:** S
- **Dependencies:** none — lands FIRST
- **Filed-by-Ralph TD spec is the source of truth** — your TD-027 body has the proposed fix; US-202 acceptance criteria mirror it exactly
- **No backfill of historical rows** (your forensic-data instinct is correct). The 149 Session 23 rows preserve original format strings; US-202 only normalizes NEW inserts going forward
- **Includes Thread 1 investigation** — run `SELECT event_type, timestamp FROM connection_log WHERE [Session-23 window] ORDER BY timestamp` on Pi data/obd.db; document whether the 23s vs minutes discrepancy is gap-between-events (most likely), format-mix-corrupts-delta, or other. If gap-between-events: file Sprint 15+ heartbeat-row note (don't scope-creep heartbeat into US-202).
- **Files to touch** (per TD spec): new `src/common/time/helper.py` (utcIsoNow), `database_schema.py` (DEFAULT change), 4 explicit Python writers route through the helper, 2 new test files, `specs/standards.md` canonical-format subsection, TD-027 annotation.

## Execution order (sprint.json updated)

```
P0: US-202 (timestamp foundation) → US-195 (data_source) → US-193 (TD-023) → US-194 (TD-25/26)
P1: US-199 (PIDs) → US-200 (drive_id) → US-196 (US-167 carry) → US-197 (US-168 carry)
P2: US-198 (TD-024) → US-192 (US-170 retry)
P3: US-201 (B-044 audit + API_KEY)
```

## Your stale handoff items to fix on next closeout

- `session-handoff.md` line 19 — "Sprint 14 execution is held" → was held briefly Session 23 evening, **no longer**. Sprint 14 has been GROOMED + AUTHORIZED since commit `3b0080d` (Session 24). Just hadn't responded to your TD-027 note yet — that's now done with US-202.
- `session-handoff.md` line 27 — "Visible story IDs from targeted grep (contract may still be evolving — do NOT treat as final)" → contract IS final now. Read full sprint.json (or use `python offices/pm/scripts/pm_status.py --sprint` for the table view).
- Story count: was 10, now **11** (US-202 added).
- US-195 + US-197 now have US-202 in their dependency arrays — re-read those stories' `dependencies` field before working them.

## New PM tooling you can use

I added two PM scripts in this branch (commit `5c280e4` + this commit):

- `python offices/pm/scripts/pm_status.py` — shows current sprint stories (id/size/priority/status/deps/title) + backlog + counter. Use at the start of each Ralph session to confirm sprint state without re-reading the full sprint.json.
- `python offices/pm/scripts/backlog_set.py` — PM CLI for backlog mutations (don't touch this; it's mine).

## Working tree state at this commit

- Committed: TD-027 spec, your TD-027 inbox note, US-202 sprint contract, story counter bump, backlog harden-phase update, this go-signal note
- Still uncommitted (yours): `progress.txt`, `session-handoff.md`, `ralph_agents.json`, `knowledge/session-learnings.md` — your session tracking, you commit at sprint close per Rule

## What to do now

1. Re-read `offices/ralph/sprint.json` — full file is fine since sprint is yours to execute now.
2. Start US-202 (TDD as always: tests first).
3. Per CIO Q&A in MEMORY.md, work the sprint via `ralph.sh N` in CIO's shell. Don't invoke ralph.sh from inside this session.

— Marcus (Sprint 14 is GO)
