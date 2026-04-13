# Reorg Handoff — Start Here (Fresh Session Entry Point)

**Date created**: 2026-04-13
**Created by**: Ralph (end of brainstorm/planning session)
**Last updated**: 2026-04-13 (Sweep 1 complete)
**Status**: **Sweep 1 of 6 COMPLETE and merged to main (commit `21029e8`).** Start Sweep 2 next. Baseline preserved: 1517 full-suite passing, 1499 fast-suite. Sprint 1 branch `sprint/reorg-sweep1-facades` retained until Sweep 2 merges.

---

## What is this?

The OBD2v2 project is about to undergo a 6-sweep structural reorganization covering tier split, legacy cleanup, file size reduction, orchestrator refactor, config restructure, and camelCase enforcement. This work is **CIO-direct** (not run through PM story grooming) per Marcus's architectural-decisions brief.

A full design doc and 6 bite-sized implementation plans are already written, reviewed, and committed to `main`. **You do not need to re-plan.** You execute.

## If you are a fresh Ralph session picking this up

### Step 1: Load Ralph context
Run `/init-agent`. This loads the agent instructions from `offices/ralph/agent.md` and the Ralph CLAUDE.md at `offices/ralph/CLAUDE.md`.

### Step 2: Read the architecture (locked decisions)
Read `offices/ralph/CLAUDE.md` sections on 3-tier architecture and the 7 locked architectural decisions. These are load-bearing. Every sweep is designed around them.

### Step 3: Read the design doc
`docs/superpowers/specs/2026-04-12-reorg-design.md` — the source of truth for the whole reorg. 12 sections, ~800 lines. Read all of it. Particularly sections 5 (target layout), 7 (sweep plan), 8 (execution strategy), and 9 (risks).

### Step 4: Read the plan for the sweep you are about to execute
Plans live in `docs/superpowers/plans/`. Execute them in order:

| Sweep | Plan file | Status |
|---|---|---|
| 1 | `2026-04-12-reorg-sweep1-facades.md` | ✅ **COMPLETE** — merged to main as `21029e8` on 2026-04-13. 18 facades deleted, shutdown subpackage populated, __init__.py rewritten. |
| 2 | `2026-04-12-reorg-sweep2-thresholds.md` | **Start here** — legacy threshold merge. Low risk, no cooling period needed from 1→2. |
| 3 | `2026-04-12-reorg-sweep3-tier-split.md` | After sweep 2 merges — **highest risk** — physical tier split |
| 4 | `2026-04-12-reorg-sweep4-config.md` | After sweep 3 cooling period — config restructure |
| 5 | `2026-04-12-reorg-sweep5-file-sizes.md` | After sweep 4 — orchestrator split (TD-003) + 10 other files |
| 6 | `2026-04-12-reorg-sweep6-casing.md` | After sweep 5 cooling period — camelCase + READMEs |

### Step 5: Use subagent-driven-development skill
The execution mode is **subagent-driven** (confirmed by CIO 2026-04-12). Invoke `superpowers:subagent-driven-development` and follow its process:
1. Extract all tasks from the current sweep's plan into TodoWrite
2. Dispatch an implementer subagent per task with full task text + context
3. Two-stage review after each task (spec compliance, then code quality)
4. Mark complete, move to next task

**Do not** re-read the design doc in subagents — the controller (main session) has the context, subagents get exactly the task text they need. This is the whole point of subagent-driven.

### Step 6: After each sweep, surface to CIO for merge approval
Never merge a sweep branch to `main` without explicit CIO approval. Each plan has a specific "surface to CIO" step at the end — follow it.

---

## Current repository state (as of 2026-04-13, post-Sweep-1)

- **Branch**: `main`, 8 commits ahead of origin (not pushed — CIO holding)
- **Sprint branch `sprint/reorg-sweep1-facades`**: RETAINED. Do not delete until Sweep 2 merges (plan rule).
- **Recent commits on main**:
  - `21029e8 Merge sprint/reorg-sweep1-facades: Sweep 1 complete — facade cleanup`
  - `f97afa3 docs: Ralph → PM sweep 1 complete architecture report`
- **Baseline** (preserve at every commit): **1517 full-suite passing, 1499 fast-suite passing, 19 slow deselected**
- **`reorg-baseline` tag** exists for nuclear rollback to pre-sweep state
- **Lessons learned from Sweep 1** (applies to Sweep 2+):
  - Top-level packages (display/alert/analysis/profile/power/calibration/ai/backup/hardware/common) import WITHOUT `src.` prefix. `src/` itself is on sys.path via conftest.
  - When nominated canonical is a submodule but symbols span the package, the correct canonical is the package `__init__.py`. Verify via `python -c "import <pkg> as m; print(hasattr(m, symbol))"` before trusting the plan.
  - Lazy imports + `@patch('old.X')` targets in tests must move together. Grep tests for patch strings alongside code.
  - Parallel PM sessions can flip Ralph's working tree via their own `git checkout main`. Recover via stash/checkout/pop; don't panic or reset.
  - Ruff I001 auto-fix via `ruff check --fix --select I001 <file>` on the specific rewritten files — don't fix the whole tree (leaves pre-existing warnings alone).

## Worktree decision (deferred)

The subagent-driven-development skill lists `superpowers:using-git-worktrees` as required. The previous Ralph session considered creating a worktree at `Z:/o/OBD2v2-reorg/` but **deferred the decision** for these reasons:

1. The reorg is strictly sequential (one sweep at a time, no parallel work)
2. The plans explicitly use `Z:/o/OBD2v2` paths in every bash command
3. Each sweep has its own sprint branch, which is the isolation mechanism
4. A worktree would require rewriting all plan `cd` commands or operating from a different CWD

**If you want to create a worktree anyway** (e.g., to keep the main checkout free for other work), do it before starting sweep 1 task 1. Create it with:
```bash
cd Z:/o/OBD2v2
git worktree add ../OBD2v2-reorg -b sprint/reorg-sweep1-facades main
cd ../OBD2v2-reorg
# All plan commands now execute from here. Rewrite cd commands in your head.
```

**If you do not want a worktree**, just create the sprint branch directly as Task 1 of sweep 1 describes:
```bash
cd Z:/o/OBD2v2
git checkout -b sprint/reorg-sweep1-facades main
```

The plans work either way; choose based on whether you need the original checkout free for other work.

## Invariants across all 6 sweeps

These rules apply to every sweep. If any of them is violated, stop and surface to CIO:

1. **Spool-authoritative values in `tieredThresholds` must not change, byte-for-byte.** Sweeps 2, 4, 5, and 6 each have a preservation check. The baseline snapshot is created at the start of sweep 2 (or re-created per-sweep) and compared at the end.

2. **No tier-boundary violations.** Pi code cannot import from `src.server.*`; server code cannot import from `src.pi.*`. `src.common.*` is the only cross-tier bridge. Exception: the documented `ollama_manager` temporary in sweep 3 task 8 (filed as tech debt).

3. **Each sweep merges to `main` before the next begins.** No long-lived integration branches. No stacking sweeps. Sprint branches are deleted only after 7+ days post-merge.

4. **24-hour cooling period after sweeps 3 and 5.** These are the high-risk sweeps. After merging them to `main`, wait 24 hours before starting the next sweep. Use the time to run the simulator, watch for surface issues, and let the stability prove itself.

5. **Green at every commit.** No exceptions. The fast test suite (`pytest -m "not slow"`) runs after every meaningful change. The full suite runs before each PR merge.

6. **No new feature work, no bug fixes unrelated to structural correctness, no behavior changes.** If a sweep task discovers a bug, file it to `offices/pm/tech_debt/` and keep moving. Do not fix inline.

7. **CIO approval gate before every merge to main.** Plans include explicit "surface to CIO" steps. Respect them.

## What Spool needs to know

Nothing, unless a tuning value is threatened. If any sweep step would change a value inside `tieredThresholds`, stop the sweep and file to `offices/tuner/inbox/` immediately. Spool does not need to review the reorg otherwise.

## What Marcus needs to know

Already notified. See `offices/pm/inbox/2026-04-12-from-ralph-reorg-plan.md`. After sweep 6 merges, Ralph notifies Marcus again via inbox to close the backlog items (TD-002, TD-003, B-019, B-040, and B-006 as declined).

## Resolving this work in the backlog

The reorg resolves:
- **TD-002** — Re-export facade modules → sweep 1
- **TD-003** — Orchestrator refactoring plan → sweep 5
- **B-019** — Split oversized files → sweep 5

And closes:
- **B-006** — camelCase migration → sweep 6 (decided: keep camelCase, close as declined)
- **B-040** — Structural Reorganization → the reorg itself (Marcus creates this as a backlog summary item)

## Quick reference — key file paths

- **Design doc**: `docs/superpowers/specs/2026-04-12-reorg-design.md`
- **Plans folder**: `docs/superpowers/plans/`
- **Marcus inbox note**: `offices/pm/inbox/2026-04-12-from-ralph-reorg-plan.md`
- **Ralph CLAUDE.md**: `offices/ralph/CLAUDE.md` (architecture + 7 locked decisions)
- **Project CLAUDE.md**: `CLAUDE.md` at repo root
- **TD-003 (orchestrator plan)**: `offices/pm/tech_debt/TD-003-orchestrator-refactoring-plan.md`

## If something goes wrong

- **A sweep fails in the middle**: fix forward on the same sprint branch. Don't merge. Don't escalate unless you hit a true blocker.
- **A sweep discovers an AMBIGUOUS classification**: file `offices/pm/tech_debt/TD-reorg-sweepN-<desc>.md`, surface to CIO, stop that sweep until resolved.
- **A Spool value drifts**: **immediately stop**, revert the last commit that caused drift, file to `offices/tuner/inbox/`. Do not merge.
- **Tests go red and you can't find the cause**: revert to the last known-green commit on the sweep branch, try again. The plan commits are deliberately small to bound this blast radius.
- **Nuclear rollback needed**: the tag `reorg-baseline` is created in sweep 1 task 1. `git reset --hard reorg-baseline` returns to pre-reorg state. Only use with explicit CIO approval.

## End of handoff

Go execute sweep 1. Good luck.
