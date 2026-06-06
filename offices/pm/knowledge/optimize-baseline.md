# PM Office Optimize Baseline

**Last optimize**: 2026-06-05 (Session 47 — V0.28 chain-merge session)

## Line counts (post-optimize)

| File | Lines | Target | Status |
|---|---|---|---|
| `.claude/commands/init-pm.md` | 7 | ~30 | OK (well under) |
| `offices/pm/projectManager.md` | 441 | ~400 | OK (10% over — acceptable; under 500 trigger) |
| `offices/pm/knowledge/projectManager-session-history.md` | 2399 | append-only | OK |

## What this run did

- 2nd run of `/optimize-office-pm`. `projectManager.md` had grown **452 → 738** over Sessions 39→47 (7 sessions) — past the 500-line trigger, as the prior baseline predicted.
- Archived **6 older session summaries** (Sessions 43, 41, 40×2, 39, 38) to `projectManager-session-history.md`, appended oldest-first (chronological). Last (S46) + Previous (S44) stay inline per the 2-session sliding window.
- Archived the explicitly-stale **"Stale (Session 35 pickup — kept for reference)"** block to the history file under `## Historical Quick Context blocks` (append-only).
- **Trimmed the `Last Updated` header** from a chained multi-session narrative — **11,672 chars → 733 chars** (one line; the single biggest boot-context byte reduction this run, ~11KB). This is the recurring pattern the Session-39 baseline flagged: closeout prepends a session paragraph instead of replacing it.
- Updated the `Current Phase` pointer to V0.28-merged state (done inline during the chain-merge work earlier this session).

## Patterns to watch (carried forward + reaffirmed)

- **`Last Updated` header bloat** — STILL the #1 recurring offender. Every closeout prepends ~1.5KB of session narrative; it grew to 11.6KB before this trim. **Recommendation stands:** amend `/closeout-pm` to bump the header to a 1-line current-state pointer, not append. (Optimize keeps having to undo it.)
- **`Current Phase` line (line 19) carries a long `Previous Current Phase preserved` chain** back through V0.27.x — a second instance of the same append-don't-replace pattern, inside Quick Context. NOT trimmed this run (delicate mid-line surgery; file already under trigger). Candidate for next run's surgical cut at the V0.28↔V0.27 boundary.
- **`### Previous State` / `### Stale (... pickup)` snapshots within Quick Context** — closeout doesn't archive these; only optimize does. One archived this run (S35). Watch for new ones.

## Notes for next run

- Knowledge Index scan: 2 PM-knowledge refs resolve; 1 forward-ref (`feedback-pm-windows-encoding-ad-hoc-audits.md`) is a "consider creating" TODO, not a broken link — left intact. (Worth actually creating: hit the cp1252 `→` gotcha twice in Session 47 ad-hoc audits.)
- `backlog.json` lastUpdated 2026-06-01 (4 days; within threshold; no flag).
- `story_counter.json` nextId = US-380 (US-379 fast-follow filed Session 47).
- `regression_manifest.json` post-V0.28-merge: F-005/F-007 OK (validated by chain merge V0.28.2); F-013/F-014 still NEVER-validated-IRL (self-update; long-standing synthetic-only). 1 STALE.
- **Out-of-scope flag (NOT optimize's lane):** the cross-agent `MEMORY.md` is over its 24.4KB size limit — needs a separate history-trim pass (it's shared memory, not PM-office, per the CIO memory-boundary directive).
- If `projectManager.md` exceeds 500 lines again, re-run (and consider the `Current Phase` line surgery noted above).
