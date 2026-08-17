# US-218 complete — I-017 closed. Divergence flagged for Marcus.

**From:** Rex (Ralph), Agent 1, Session 87
**Date:** 2026-04-21
**Re:** US-218 (Sprint 16 Wiring — I-017 close, specs/standards.md ↔ agent.md dedup)

## Summary

US-218 closed I-017 by canonicalizing the overlap between `specs/standards.md` (PM-owned) and `offices/ralph/agent.md` (Ralph-owned). Approach was Option B from the original I-017 filing — per-topic canonical source-of-truth + reduce agent.md to a pointer table. specs/standards.md NOT touched (per US-218 scope fence + invariants).

## Audit results

**TOC comparison:**
- `specs/standards.md`: 13 top-level sections (§1 File Headers → §13 Database Coding Patterns) + Overview + Mod History. Unchanged.
- `offices/ralph/agent.md`: lost 4 H3 subheads under "Coding Standards (core)" (Naming Conventions / File Headers / Code Quality Rules / Documentation); renamed "Error Handling" → "Error Handling — operational constants". No H1/H2 changes. All Ralph-operational sections (Workflow, Communication, Safety, Git Branching, PM Communication Protocol, Housekeeping, CIO Dev Rules, Golden Code Patterns) retained.

**Line count:** agent.md 352 → 333 (−19 lines). Small delta because Session 71 already did the big refactor; this was the residual cross-doc cleanup.

**Overlap sites closed** (full table in the I-017 closure annotation at `offices/pm/issues/I-017-standards-md-agent-md-duplication.md`):

| Topic | Canonical | agent.md after |
|-------|-----------|----------------|
| File headers, naming, SQL conventions, commenting, imports/type hints/docstrings, config structure, testing, logging, git, code review, project patterns, file size, DB patterns | `specs/standards.md` §1–§13 | Single pointer-index table |
| 5-tier error classification | `specs/methodology.md` + `specs/architecture.md` §7 | Collapsed from 5-bullet list to 1-sentence pointer |
| Retry schedule `[1,2,4,8,16]` + exit codes (0/1/2/3) | Ralph-operational | Kept in agent.md (operational constants) |
| Pytest markers (`pi_only`) + patterns-testing.md pointer | Ralph-operational | Kept in agent.md (not duplicated in standards.md) |

## ⚠ Divergence flagged — Marcus adjudicates

While deduping I found one **authoritatively-different** pair (not just duplication — two docs disagree on the same topic). This falls outside US-218's scope fence (dedup agent.md; don't touch standards.md), so I'm flagging it rather than fixing.

**Topic:** Logger message formatting — f-strings vs `%` formatting.

**`specs/standards.md` §8 Log Message Format (line 560):**
```python
# Good: Contextual information
logger.info(f"Processing batch | batchId={batchId} | recordCount={len(records)}")
logger.error(f"Failed to fetch | endpoint={endpoint} | status={response.status_code}")
```

**`offices/ralph/agent.md` Golden Code Patterns (line 308, derived from `specs/golden_code_sample.py`):**
```python
logger.info("Loaded %d record(s)", count)   # % formatting (not f-strings) for lazy evaluation
```

**Why this matters:** standards.md §8 shows the "good" example using f-strings. Golden Code Patterns (from `specs/golden_code_sample.py`) explicitly says `%` formatting for lazy evaluation. Ralph's golden-code discipline produces `%`; standards.md examples use f-string. A reviewer checking either doc gets a different answer.

**Suggested resolution options** (Marcus picks):

1. **specs/standards.md § is canonical** → Rewrite the §8 examples to use `%` formatting, note "lazy eval" rationale, retire the f-string examples. Golden Code Patterns stays aligned.
2. **Performance irrelevant at current scale** → Update Golden Code Patterns to accept f-strings (aligning Ralph with §8). Requires CIO sign-off since `specs/golden_code_sample.py` is CIO-sourced.
3. **Both are valid in different contexts** → Add a §8 subsection: "use `%` formatting for hot paths; f-strings OK elsewhere." Document which paths are hot.

I don't have a recommendation — option 1 is most aligned with specs/standards.md supremacy (which was the I-017 north star), but option 2 is the lowest-friction (f-strings are Python-idiomatic and the performance difference is nanoseconds at our volumes). Option 3 is the most nuanced but adds cognitive load.

This isn't urgent — no active bug. File it as a sprint-16+ TD or groom directly; your call.

## Verification evidence (US-218)

- `wc -l offices/ralph/agent.md`: 352 → 333 lines (−19).
- `grep -E '^#+ ' specs/standards.md`: unchanged (0 edits to standards.md).
- `grep -E '^#+ ' offices/ralph/agent.md`: 4 H3 headings removed under Coding Standards + 1 H2 renamed; 0 other structural changes.
- `pytest tests/ -m "not slow" -q`: [results in progress.txt].
- `python offices/pm/scripts/sprint_lint.py`: 0 errors.

## Files touched

- Modified: `offices/ralph/agent.md` (dedup + pointer table + mod-history entry)
- Modified: `offices/pm/issues/I-017-standards-md-agent-md-duplication.md` (Closed annotation)
- Created: `offices/pm/inbox/2026-04-21-from-ralph-us218-dedup-complete.md` (this note)
- Modified: `offices/ralph/sprint.json` (US-218 passes:true + completionNotes)
- Modified: `offices/ralph/ralph_agents.json` (status=unassigned, taskid='', new closeout note)
- Modified: `offices/ralph/progress.txt` (US-218 entry appended)

## Knowledge files — clean

Audited `offices/ralph/knowledge/patterns-*.md` for standards.md duplication. Only hit was `sweep-history.md` line 13 ("S6 (6af8e9a): camelCase enforcement, README finalization, archive reorg specs") which is a historical reference, not a rule duplication. No cleanup needed.

— Rex
