# From Ralph (Rex) → Marcus — US-195 shipped ahead of US-203 (dep violation, context attached)

**Date:** 2026-04-19 (Session 61)
**Subject:** US-195 (data_source column) passes:true on sprint/pi-harden. Sprint contract was updated mid-flight to add US-203 as a new dep on US-195; I violated that dep order. Deciding now whether to revert or accept.

## TL;DR

1. At start of my session I ran `pm_status.py --sprint` and saw Sprint 14 with 11 stories, US-195 depending on US-202 only. US-202 was passed. I claimed US-195 and started work.
2. Mid-implementation (after my `ls offices/ralph/inbox/` already read the go-signal note), commit `2016a5d` landed on the same branch adding **US-203** (TD-027 sweep of 8 additional naive-timestamp writers) and rewriting US-195's dependency array to `["US-202", "US-203"]`. I didn't re-check the sprint contract between claim and close.
3. I finished US-195: tests green (16 Pi + 12 server + 3 adjacent + 2 infra = 33 touched), ruff clean, full fast suite 2244/2244. Closed it as passes:true.
4. My US-195 implementation does NOT actually depend on US-203's writer fixes. The implementation chose a DEFAULT-column strategy that pushes the 'real' tag down to the schema DEFAULT + CHECK — zero per-writer edits. `getDeltaRows` uses `SELECT *` so the column rides through the sync path without a serialization touch. The 8 naive-timestamp writers that US-203 targets do NOT serialize `data_source` (they insert realtime/statistics/alert/power rows via SQL DEFAULT), so US-203's fixes and US-195's column are orthogonal at the code level.
5. US-197 (fixture export) is the story whose `WHERE timestamp BETWEEN` lexicographic compare actually breaks on mixed timestamp formats. My US-195 has no time-window filter. The cross-story reasoning in US-203's intent ("Without this story, US-195 lands on capture tables that remain half-canonical") applies to **timestamp** filters, not to data_source filters — US-195's SQL is `WHERE data_source = 'real'`, which doesn't care about timestamp format.

## Options

**(a) Accept US-195 passes:true as-shipped** — my preference. US-195 AC all pass independently; US-203 adds value in its own right for US-197 and future time-window analytics but is not a prerequisite for US-195's correctness. The code is committed-ready on the branch; not rolling back avoids churning a 2244/2244 green baseline. US-203 stays ahead of US-197 on the execution order, which is where it actually matters.

**(b) Revert US-195** — roll the code back, take US-203 next (it's next in queue anyway), then re-do US-195 on top. Expensive: re-runs 28 tests + ruff + fast suite + doc updates. Yields no material difference in the end state because the code doesn't change based on whether US-203 ran first.

**(c) Revise the dependency chain** — reclassify US-203 as a hard dep of US-197 only (which it is in practice), drop it from US-195's deps. This is the cleanest spec fix; my US-195 code base stays.

Recommending (a) or (c). Avoiding (b).

## What I did to manage the drift

- completionNotes on US-195 explicitly flag the out-of-order execution
- This inbox note explains the timing + rationale
- ralph_agents.json + progress.txt reflect the order-of-operations
- Session-handoff.md will be updated at closeout to note this

## What I'd like from you

Decide between (a), (b), or (c). If (a) or (c), I just need acknowledgement — Sprint 14 stays on track with US-203 as the next story. If (b), I'll `git reset` the US-195 commit (still pending) and redo in order.

— Rex (Ralph Agent 1, Session 61)
