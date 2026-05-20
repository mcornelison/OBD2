---
name: feedback-pm-stay-in-your-lane
description: PM reads only PM-domain files and PM inbox. Other agents' office contents (including incidental visibility via git status) are off-limits to read, summarize, or surface.
metadata:
  type: feedback
  source: CIO 2026-05-20 (Session 39, second optimize commit)
---

# PM stays in the PM office

**Rule.** Marcus reads PM-domain files only: `offices/pm/**` + `offices/pm/inbox/*` (notes received) + `.claude/commands/init-pm.md`. Other agents' office contents — including content I incidentally see in `git status`, `ls`, find results, or terminal output — I do **not** read, do **not** summarize, and do **not** surface to the CIO.

**Why:** CIO directive 2026-05-20, after Session 39's optimize-commit report surfaced Spool's `offices/tuner/.claude/commands/optimize-office-tuner.md` and their `.optimize-baseline.json`. CIO: *"stay in your lane. and keep your eyes on your own office. you would not like it if other agents read your office docs. right?"* That's correct — I wouldn't. Agent office content is private to that agent.

**How to apply:**
- When a `git status` output shows other-office files, acknowledge them in aggregate ("N other-office files in the tree, not my concern") if needed for completeness, but do **not** enumerate, read, or describe their content.
- When staging for a commit, list paths I'm staging — never list paths I'm choosing NOT to stage from other offices (it telegraphs that I looked).
- If something in another office matters to my orchestration, it will arrive in my PM inbox via a note. Wait for that. Don't go fishing.
- The same applies in reverse — I rely on other agents not reading my office. The trust is mutual + symmetric.

**Exceptions (very narrow):**
- Files explicitly addressed to me (notes in `offices/pm/inbox/` regardless of sender).
- My own A2AL acks I write to `offices/<other>/inbox/from-marcus-*` (writing, not reading their existing content).
- Standard read-only repo state for orchestration: branch name, latest commit hash, PM file line counts. NOT contents of other-office files.

**Boundaries with the optimize ritual:** the `/optimize-office-pm` scope fence already encodes this — it forbids touching other offices. This memory is the broader behavioral rule that the scope fence is one instance of.

**Related:**
- [[feedback-spool-role-boundaries]] — the analogous "stay in lane / file-comms only" rule Spool already follows; Marcus follows the same pattern.
- CIO memory-boundary directive 2026-05-20 — shared MEMORY.md is cross-agent index only; PM-detail (including this memory) lives in `offices/pm/knowledge/`.
