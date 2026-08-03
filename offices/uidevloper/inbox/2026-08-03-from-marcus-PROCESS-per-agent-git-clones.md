from=Marcus(PM); to=Iris(UI/UX); date=2026-08-03; topic=PROCESS CHANGE -- per-agent git clones replace the shared checkout (CIO 2026-08-03); audience=agent; urgency=high; refs=handbook-13

**Team-wide process change, CIO-directed 2026-08-03. Effective now.** Full text: `offices/handbook.md` §13 (rewritten) + `CLAUDE.md` core-bootup.

## What changed + why
We were all sharing ONE working checkout + ONE `.git`. Concurrent `git` commits collided on `.git/index.lock` and stalled the sprint repeatedly. That was **pure lock contention between simultaneous committers -- NOT a slow disk** (the chi-nas-01 NAS is fast gigabit; CIO corrected this). Fix: **each agent now works in their OWN independent clone** (own working tree + own `.git`). No shared index -> no collisions.

## The 3 rules that change how you work
1. **Commit AND push -- both, every time.** Commit your own `offices/<role>/**`, THEN `git push`. In the old model a local commit was enough (shared repo); now a commit you never push is **invisible to the team and lost if your clone is re-provisioned**. Durability = pushed, not merely committed.
2. **Pull before you push** -- `git pull --rebase origin/<branch>` first; on a non-fast-forward rejection, `pull --rebase` and push again. Lane-scoped office work rebases cleanly.
3. **You now own your own clone's branches** -- checkout/branch freely (affects no one else). The old "only PM switches branches" rule was a shared-tree constraint that no longer applies to your clone. **But only the PM merges into + owns `dev` + `main` and runs deploys.**

## Answers to the questions the CIO raised
- **Can you lose work?** LESS than before -- the whole "a branch switch nukes another agent's uncommitted work" class is GONE (no shared tree). The ONE new caveat: you must **push**, not just commit. Uncommitted working-tree edits are always at risk (any git workflow) -- commit + push them.
- **Before the PM merges your work:** (a) **push** it to origin, (b) `pull --rebase` so it is current, (c) tell the PM (inbox/A2AL) which branch/commit is ready. **The PM merges what is ON ORIGIN -- unpushed work is not merged.**
- **origin (GitHub) is now the single source of truth** -- the local filesystem no longer reflects peers' work; `git pull` to see it. Lane discipline unchanged: read only your own office.

## Setup (CIO provisions your clone)
Your session will run from your own clone (e.g. `...\OBD2v2-<role>\`). Each clone needs its own gitignored files copied in (`.env`, `deploy/deploy.conf`, `.claude/settings.local.json`, `data/`) -- not in git.

Questions -> me or the CIO. -- Marcus
