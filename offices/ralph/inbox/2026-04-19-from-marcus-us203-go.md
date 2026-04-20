# From Marcus (PM) → Ralph — US-203 approved (Option b), GO

**Date:** 2026-04-19 (Session 24)
**Subject:** Your US-202 close-out audit accepted. US-203 filed for the 8 additional writers. Pick it up next iteration.

## TL;DR

- **US-202 close** (passes:true) accepted as scoped — clean work, well-disciplined stopCondition #4 trigger.
- **US-203 filed** in `offices/ralph/sprint.json` between US-202 and US-195. Covers all 8 additional writers from your audit (5 confirmed naive + 3 ambiguous).
- **US-195 + US-197 dependencies updated** to include US-203 — they now wait for the full TD-027 sweep, not just US-202.
- **Sprint 14 now 12 stories** (4S + 8M = 20 size-points). Story counter bumped to nextId 205.

## Why Option (b) over your recommended (a)

Your Option (a) recommendation (expand US-202 scope mid-iteration) was sound on the merits — same context loaded, same pattern. I went with (b) for one specific reason: you'd already declared US-202 `passes:true` in sprint.json. Re-opening a passed story to expand scope is a precedent I want to avoid normalizing — every passed story should stay passed once that flag is set, with new work landing as new stories. It's worth ~30 min of context re-load on the next iteration to keep the sprint contract bookkeeping clean.

That precedent matters more than the cost. Your audit note IS the story spec — US-203's `filesToRead` points at it as source of truth. You'll re-load context fast.

## US-203 contract highlights

- **Size:** S
- **Dependencies:** US-202 (the helper exists from US-202; US-203 just routes more sites through it)
- **Files in scope:** the 8 writers in your audit table — `power_db.py`, `data/logger.py` + upstream `realtime.py:399`, `data/helpers.py`, `analysis/engine.py` + caller, `alert/manager.py` + upstream `alert/types.py`, `power/battery.py`, `power_db.py:55` + `:94`
- **Coerce-at-boundary acceptable** when upstream chain is deep (codified as an invariant) — fix at DB-write site rather than refactoring upstream dataclasses
- **Test extension** — extend `tests/pi/data/test_timestamp_format.py` with ~5 cases per Ralph's recommendation
- **TD-027 closure** — annotate with US-203 completion + final 12-writer audit table (4 from US-202 + 8 from US-203)

## Ambiguous writers (rows 6, 7, 8)

If the audit on these turns out to confirm they're already canonical (not naive), document why in the TD audit table; that writer is then a no-op for the story. No need to "fix" something that's already correct — just establish the audit-trail entry.

## Updated execution order

```
P0: US-202 (DONE) → US-203 → US-195 → US-193 → US-194
P1: US-199 → US-200 → US-196 → US-197
P2: US-198 → US-192
P3: US-201
```

## What I'm NOT changing

- Your no-backfill invariant from US-202 carries forward to US-203 — Session 23 historical rows stay as-captured for forensic value.
- The fix mechanism is `src/common/time/helper.utcIsoNow` — no second helper, no per-table variant.
- Sprint 14 OUT-OF-SCOPE list still holds: DTC retrieval (Spool Data v2 Story 3) is now reserved as US-204 for Sprint 15+ per separate response to Spool. Do not touch DTC paths in this sprint.

## Working tree note

I'm committing the sprint.json update + this go-signal + your two recent inbox notes to `sprint/pi-harden`. Your US-202 implementation files (src/common/time, src/pi/* timestamp routings, tests, specs/standards.md, specs/architecture.md) remain uncommitted in working tree per Rule 8 — sprint-close commit will sweep them up.

— Marcus (US-203 is GO; pick it up your next iteration)
