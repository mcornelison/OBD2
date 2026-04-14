# Reorg Handoff — Start Here (Fresh Session Entry Point)

**Date created**: 2026-04-13
**Created by**: Ralph (end of brainstorm/planning session)
**Last updated**: 2026-04-14 (Sweep 4 merged and pushed to origin, Sweep 6 queued)
**Status**: **Sweeps 1, 2a, 2b, 3, and 4 COMPLETE and merged to main.** Sweep 4 (config restructure) landed as commit `f1237b8` on 2026-04-14 and was pushed to `origin/main` in the same session (main had been held behind origin since before the reorg started — 104 commits went up together). Tests preserved at **1469 fast / 1487 full** (exact baseline minus 32 legacy template tests deleted in Sweep 4 Task 8, byte-for-byte Spool `tieredThresholds` preservation verified). **Next: Sweep 6 (camelCase + READMEs, B-006 close)** per CIO decision to re-order — Sweep 5 (orchestrator split + oversized files) is deferred to a later session. Cooling period after Sweep 4 waived per CIO policy (nothing deployed, no runtime surface to soak).

---

## What is this?

The OBD2v2 project is undergoing a 6-sweep structural reorganization covering facade cleanup, legacy threshold merge, tier split, config restructure, orchestrator refactor + file size reduction, and camelCase enforcement. This work is **CIO-direct** (not run through PM story grooming) per Marcus's architectural-decisions brief.

A full design doc and 6 bite-sized implementation plans are already written, reviewed, and committed to `main`. **You do not need to re-plan.** You execute.

## If you are a fresh Ralph session picking this up

### Step 1: Load Ralph context
Run `/init-agent`. This loads the agent instructions from `offices/ralph/agent.md` and the Ralph CLAUDE.md at `offices/ralph/CLAUDE.md`.

### Step 2: Read the architecture (locked decisions)
Read `offices/ralph/CLAUDE.md` sections on 3-tier architecture and the 7 locked architectural decisions. These are load-bearing. Every sweep is designed around them.

### Step 3: Read the design doc session log for current state
`docs/superpowers/specs/2026-04-12-reorg-design.md` — section 12 (Session Log) shows the chronological state of every sweep. The Sweep 3 row is the current high-water mark. Read section 5 (target layout) and section 7 (sweep plan) if you need the big picture.

### Step 4: Read the plan for the sweep you are about to execute

Plans live in `docs/superpowers/plans/`. Execute them in order:

| Sweep | Plan file | Status |
|---|---|---|
| 1 | `2026-04-12-reorg-sweep1-facades.md` | ✅ **COMPLETE** — merged to main as `21029e8` on 2026-04-13. |
| 2 | `2026-04-12-reorg-sweep2-thresholds.md` | ⚠ **SUPERSEDED** by split into 2a + 2b. Kept for reference. |
| 2a | `2026-04-13-reorg-sweep2a-rewire.md` | ✅ **COMPLETE** — merged to main as `418b55b` on 2026-04-13. |
| 2b | `2026-04-14-reorg-sweep2b-delete.md` | ✅ **COMPLETE** — merged to main as `d65d52f` on 2026-04-13. |
| 3 | `2026-04-12-reorg-sweep3-tier-split.md` | ✅ **COMPLETE** — merged to main as `b2be378` on 2026-04-13. Physical tier split (src/common/, src/pi/, src/server/). |
| 4 | `2026-04-12-reorg-sweep4-config.md` | ✅ **COMPLETE** — merged to main as `f1237b8` on 2026-04-14; pushed to origin/main same session (104 commits went up together). Config.json at repo root with tier-aware `pi:`/`server:` shape. 32 legacy template tests deleted, 5 prod-code bugs fixed as followups. Test baseline: 1469 fast / 1487 full (exact baseline − 32 deleted). |
| 5 | `2026-04-12-reorg-sweep5-file-sizes.md` | **DEFERRED** per CIO decision 2026-04-14 — orchestrator split (TD-003) + 10 other oversized files; returns to the queue later. Sprint for 5 has NOT been created. |
| **6** | `2026-04-12-reorg-sweep6-casing.md` | **Start here** — camelCase enforcement + README finalization + close B-006 as declined. Cooling period after Sweep 4 waived per CIO. Plan file already exists — do NOT write a new one. |

### Sweep 6 boot sequence (copy-paste into your first message)

```
1. /init-agent — loads Ralph + CLAUDE.md + auto-memory
2. Read docs/superpowers/plans/REORG-HANDOFF.md — you are here
3. Read docs/superpowers/plans/2026-04-12-reorg-sweep6-casing.md — the Sweep 6 plan (already written; do NOT write a new one)
4. Execute via superpowers:subagent-driven-development
```

### Step 5: Use subagent-driven-development skill

The execution mode is **subagent-driven** (confirmed by CIO 2026-04-12). Invoke `superpowers:subagent-driven-development` and follow its process:
1. Extract all tasks from the current sweep's plan into TaskCreate
2. Dispatch an implementer subagent per task with full task text + context
3. Two-stage review after each task (spec compliance, then code quality) — but see "process optimizations" below
4. Mark complete, move to next task

**Do not** re-read the design doc in subagents — the controller (main session) has the context, subagents get exactly the task text they need. This is the whole point of subagent-driven.

### Step 6: After the sweep, surface to CIO for merge approval

Never merge a sweep branch to `main` without explicit CIO approval. Each plan has a specific "surface to CIO" step at the end — follow it.

---

## Process optimizations learned in Sweeps 2b + 3 (apply these in Sweep 4+)

### 1. Preflight branch check in EVERY subagent prompt

Sweep 2b had Tasks 3 and 4 commit to `main` instead of the sprint branch because a parallel PM session flipped the working tree. Recovery required cherry-picks. Since then, every subagent prompt includes this preflight block as the first instruction:

```
## CRITICAL PREFLIGHT — verify branch before ANY git ops

Run FIRST:
    git -C Z:/o/OBD2v2 branch --show-current

Must say `sprint/reorg-sweep<N>-<name>`. If not, checkout and verify again.
Re-verify before EACH commit.
```

**This worked in Sweep 3** — zero branch-state recovery needed. Keep the pattern.

### 2. Trivial file-creation tasks can be done directly

Sweep 3 Tasks 10-13 (contracts skeleton, Pi skeletons, server skeletons, READMEs) are pure file-creation with literal content from the plan. Don't dispatch a subagent — do it directly with parallel `Write` tool calls. Saves ~5 minutes per task of subagent overhead.

### 3. Lightweight review for pure-delete or pure-scaffolding commits

Not every task needs the full two-stage review dance. Tasks 6, 7, 8 of Sweep 3 (`git rm src/alert/thresholds.py`, `src/obd/__init__.py` re-export cleanup, orphan shim delete) were reviewed directly by the controller via `git show --stat` + grep. Two-stage review is for tasks where content correctness is non-trivial — file deletes and import prunes are verifiable in one bash call.

### 4. No compound bash

Never chain `cd && cmd` or `a && b` — the permission system auto-approves single commands but prompts on chains. Use `git -C Z:/o/OBD2v2 <cmd>` and absolute paths. Parallel `Bash` tool calls are free.

### 5. Ruff I001 after mass rewrites

Any sweep that rewrites many imports will introduce I001 (import-sort) drift. Auto-fix at the end with `ruff check --fix --select I001 <specific files>` — do not fix the whole tree.

### 6. For entry points or subprocess-spawning tests, run the slow suite periodically

Fast-suite-per-task catches most regressions, but `tests/test_e2e_simulator.py` (slow-marked) spawns a subprocess that invokes the real Pi `main.py` path. A stale path in the test fixture won't show up until slow suite runs. **Recommendation**: run the slow suite at task boundaries that touch entry points, not just at Task 14.

### 7. `/tmp/` on Windows is unreliable for Write tool

Bash sees `/tmp/` as the Cygwin/MSYS tmp, which works. The `Write` tool claims success at `/tmp/X` but the file doesn't actually land where git can find it. **Use project-local temp files** like `Z:/o/OBD2v2/.sweep<N>-merge-msg.txt` for merge commit messages, then `rm` after the merge.

### 8. When a subagent dies mid-report, check HEAD vs. index BEFORE assuming worktree state

Sweep 4 Task 6 subagent made 12 good commits, then died while running the fast suite. On return, `git status` showed 43 files "modified" — which *looked* like the commits had been lost. They hadn't: HEAD was correct (all 12 subagent commits intact), but the index and worktree had been reverted to a pre-sweep flat-shape state (likely from a parallel-session `git checkout` that flipped things mid-run). Recovery was simple: `git reset --hard HEAD`. **Always check `git log --oneline` BEFORE inspecting `git diff` when a subagent returns an ambiguous state** — the commits may be fine and only the index/worktree stale. Never rerun work based on `git status` alone.

### 9. Don't use `git stash` for transient checks — it can pop OLD stashes

During Sweep 4 Task 10 I used `git stash` / `ruff check` / `git stash pop` to test ruff against different tree states. The `git stash` was a no-op ("no local changes to save"), but the `pop` happily popped an OLD stash entry left over from a previous session, creating a merge conflict on `loader.py` between ASCII `->` and unicode `→`. Use `git show <sha>:<path>` or temporary files instead. If you must stash, run `git stash list` first and verify the pop target.

### 10. Slow-marked tests are invisible to fast-suite-only runs, but still need fixture updates

Sweep 4 Task 8 subagent updated 23 test files using fast-suite-only verification. Task 10 then caught 2 more files that break the build: `tests/test_simulate_db_validation.py` and `tests/test_e2e_simulator.py`. Both are `@pytest.mark.slow` and so they don't appear in `pytest -m "not slow"` output — the subagent had no signal they existed. **When doing a mass fixture sweep, grep for the fixture pattern across the whole `tests/` tree independently**, don't trust fast-suite output as your file list. Or: run the full suite at least once at a task boundary.

### 11. Subagent section-match pattern can miss non-canonical config keys

The Task 6 subagent was given the 19 canonical pi-section names (`bluetooth`, `display`, etc.) as a grep mask. That mask missed `config.get('shutdown', ...)` and `config.get('monitoring', ...)` in `orchestrator.py` / `shutdown/command.py` because those keys weren't in the canonical-sections list — they were ad-hoc config reads that happen to accept `config.get(X, {})` patterns even though the real config file never had those sections. The test fixtures had been rewritten (under `pi:`), but the prod code was still reading at top level → 5 bugs, 7 tests skipped. **For mass config-reader rewrites, grep for `config.get(['"]\\w+['"]` on the whole src tree, not just a pre-determined section list.**

---

## Invariants across all 6 sweeps

These rules apply to every sweep. If any of them is violated, stop and surface to CIO:

1. **Spool-authoritative values in `tieredThresholds` must not change, byte-for-byte.** Sweeps 2, 4, 5, and 6 each have a preservation check. The baseline snapshot is created at the start of sweep 2 (or re-created per-sweep) and compared at the end. Sweeps 2a, 2b, and 3 all verified empty diffs.

2. **No tier-boundary violations.** Pi code cannot import from `src.server.*`; server code cannot import from `src.pi.*`. `src.common.*` is the only cross-tier bridge. **Sweep 3 verified ZERO violations** — the expected temporary ollama_manager exception didn't materialize because the orphan shim was deleted cleanly.

3. **Each sweep merges to `main` before the next begins.** No long-lived integration branches. No stacking sweeps. Sprint branches are deleted only after 7+ days post-merge.

4. **24-hour cooling period after sweeps 3 and 5** (from the original design doc). **WAIVED by CIO 2026-04-13** for Sweeps 3→4 because nothing is deployed and no runtime surface exists for issues to "soak" out. Same waiver presumably applies to 5→6 unless CIO says otherwise.

5. **Green at every commit.** No exceptions. The fast test suite (`pytest -m "not slow"`) runs after every meaningful change. The full suite runs before each PR merge.

6. **No new feature work, no bug fixes unrelated to structural correctness, no behavior changes.** If a sweep task discovers a bug, file it to `offices/pm/tech_debt/` and keep moving. Do not fix inline. (Exception: Sweep 3 Task 8 added try/except symmetry in `orchestrator._handleProfileChange` as part of Test 3 rewrite — it was completing an existing partial pattern, not new behavior. Reviewers accepted as legitimate.)

7. **CIO approval gate before every merge to main.** Plans include explicit "surface to CIO" steps. Respect them.

## Current repository state (as of 2026-04-14, post-Sweep-4)

- **Branch**: `main` at commit `f1237b8` (Sweep 4 merge), **pushed to `origin/main`** 2026-04-14 — first push of the reorg work (104 commits went up together). The "main is N commits ahead of origin" status from prior sweeps is now resolved.
- **Sprint branches retained** (local only, not pushed):
  - `sprint/reorg-sweep1-facades` (delete ~2026-04-20 per 7-day rule)
  - `sprint/reorg-sweep2a-rewire` (delete ~2026-04-20)
  - `sprint/reorg-sweep2b-delete` (delete ~2026-04-20)
  - `sprint/reorg-sweep3-tier-split` (delete ~2026-04-20)
  - `sprint/reorg-sweep4-config` (delete ~2026-04-21)
- **Baseline** (preserve at every commit): **1469 fast-suite passing, 1487 full-suite passing, 0 fast-skipped, 1 full-skipped, 19 deselected** (Sweep 4 dropped 32 legacy template tests from the sweep-3 baseline of 1501/1519 — the new numbers are the authoritative reference going forward).
- **`reorg-baseline` tag** exists for nuclear rollback to pre-sweep state (still useful since origin now has the sweep work, `reorg-baseline` is the only way back to pre-reorg without a revert chain).
- **Config file location**: `config.json` at repo root (was `src/pi/obd_config.json` pre-Sweep-4). Tier-aware shape: top-level shared (`protocolVersion`/`schemaVersion`/`deviceId`/`logging`) + `pi:` (19 sections) + `server:` (`ai`, `database`, `api`).
- **Simulator invocation**: `python src/pi/main.py --simulate --dry-run` (loads `<projectRoot>/config.json` by default).
- **Consumer pattern for config reads**: `config.get('pi', {}).get('<section>', ...)` for pi-tier sections; `config.get('server', {}).get('ai', ...)` for AI; `config.get('logging', ...)` / `config['protocolVersion']` for top-level shared keys.
- **src/ layout** (post-Sweep-4, unchanged from Sweep-3):
  ```
  src/
  ├── README.md
  ├── common/   (config/, errors/, logging/, analysis/, contracts/, constants.py)
  ├── pi/       (main.py, obd/, hardware/, display/, power/, alert/, profile/, calibration/, backup/, analysis/, clients/, inbox/)
  └── server/   (main.py, ai/, api/, ingest/, analysis/, recommendations/, db/)
  ```
  Note: `src/pi/obd_config.json` is gone (moved to repo root `config.json` in Sweep 4).

## What Spool needs to know

Nothing, unless a tuning value is threatened. If any sweep step would change a value inside `tieredThresholds`, stop the sweep and file to `offices/tuner/inbox/` immediately. Spool does not need to review the reorg otherwise.

## What Marcus needs to know

Already notified. See `offices/pm/inbox/2026-04-12-from-ralph-reorg-plan.md`. After sweep 6 merges, Ralph notifies Marcus again via inbox to close the backlog items (TD-002, TD-003, B-019, B-040, and B-006 as declined).

## Resolving this work in the backlog

The reorg resolves:
- **TD-002** — Re-export facade modules → Sweep 1 ✅
- **TD-003** — Orchestrator refactoring plan → Sweep 5 (deferred)
- **B-019** — Split oversized files → Sweep 5 (deferred)

And closes:
- **B-006** — camelCase migration → Sweep 6 (decided: keep camelCase, close as declined)
- **B-040** — Structural Reorganization → the reorg itself (Marcus creates this as a backlog summary item)

New backlog items filed during the reorg:
- **B-035** — Per-profile tiered threshold overrides (filed during Sweep 2b when Tests 1 & 2 were deleted as square-peg)
- **TD-sweep4-legacy-validator-defaults** — Legacy `hardware.*`/`backup.*`/`retry.*` entries in `src/common/config/validator.py` DEFAULTS/REQUIRED_KEYS that no production code reads. Low priority; fold into a later cleanup sweep.

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
- **Branch-state confusion** (subagent committing to wrong branch): the preflight pattern should prevent this. If it still happens, cherry-pick the orphan commits onto the correct branch and reset the wrong branch back — same procedure Sweep 2b used.
- **Nuclear rollback needed**: the tag `reorg-baseline` is created in sweep 1 task 1. `git reset --hard reorg-baseline` returns to pre-reorg state. Only use with explicit CIO approval.

## End of handoff

Go execute Sweep 6 (camelCase + READMEs + close B-006). Read the plan file first. Good luck.
