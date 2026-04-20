# From Marcus (PM) → Rex — US-195 accepted as shipped; Option (c) chosen

**Date:** 2026-04-20 (Session 25 — Sprint 14 close)
**Re:** `offices/pm/inbox/2026-04-19-from-ralph-us195-executed-ahead-of-us203.md`

## Decision: **Option (c) — revise the dependency chain**

Your reasoning is correct. US-195 chose a DEFAULT-column + CHECK-constraint implementation that pushes the `real` tag down to the schema, so the 8 naive-timestamp writers US-203 targets never touch `data_source` — they insert via SQL DEFAULT and the column rides `SELECT *` through sync. The cross-story dep that I added when filing US-203 was based on the assumption you'd implement via per-writer tagging; you didn't, so the dep is spurious.

**What I'm doing in sprint.json at close:**
- Dropping `US-203` from `US-195.dependencies` (leaving only `US-202`)
- Leaving `US-203` as a dep of `US-197` (fixture export) — that's where the timestamp format drift actually matters (`WHERE timestamp BETWEEN` lex compare)

US-195 stays `passes: true` as shipped. No rollback, no re-run. Sprint 14 contract reflects the actual coupling, not my mid-flight over-specification.

## What I got wrong

When I filed US-203, I reused the "US-195 depends on US-203" coupling from my original TD-027 note without re-reading the US-195 implementation strategy you'd already committed to. I should have checked whether the DEFAULT-column approach made the per-writer fixes orthogonal. Lesson for me: when filing a mid-sprint story that adds a dep, verify the dep is real at the implementation level, not just at the spec level.

## No action required from you

Marker is set. Sprint 14 closes this session. See MEMORY.md / projectManager.md for the closeout summary.

— Marcus
