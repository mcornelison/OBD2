---
name: feedback-pm-commit-before-branch
description: Commit any uncommitted work (incl. other agents' shared-tree changes) BEFORE any git branch/checkout/fork — a clean tree makes branching a plain checkout and avoids the worktree workaround. Team commits their own work; PM pushes.
metadata:
  type: feedback
---

# Commit-before-branch; team commits, PM pushes

**Source**: CIO directive 2026-06-01 (during the V0.28.1 fork+freeze).

> "the team has committed their work (but did not push, that is your job). I would always commit any uncommitted work before you branch. when ready make a branch so that ralph can start working."

## The rule

1. **Commit any uncommitted work BEFORE a branch/checkout/fork.** A clean working tree turns branch operations into a plain `git checkout` / `git branch`. Uncommitted modified tracked files (especially *other agents'* office files in the shared single working tree) **block `git checkout`** with `error: Your local changes ... would be overwritten by checkout`.
2. **Team commits their own work; PM pushes.** Other agents (Spool, Atlas, Iris, Rex) commit their work locally on the shared branch. Pushing to origin is the PM's job. Before branching, the PM also commits whatever pending work remains in the shared tree (CIO 2026-06-01 explicitly authorized PM to commit pending team working-tree files for branch-hygiene — this is the one sanctioned exception to lane-discipline's "don't touch other offices' files", and only for the commit-before-branch purpose).

## Why this matters (the cost it avoids)

Earlier in the 2026-06-01 session, the main tree carried uncommitted foreign files (`offices/tuner/sessions.md`, `offices/uidevloper/enclosures/display-case.scad`). Every attempt to `git checkout dev` / fork a sprint branch failed, forcing the **git-worktree workaround** (create a detached worktree on the target branch, operate there, remove it) — repeated 2-3 times across the session for the dev merge + sprint44 fork. Once the team committed and PM committed the residue (clean tree), the sprint44 checkout was a one-line `git checkout` — no worktree.

## How to apply

Before ANY `git checkout <branch>` / `git checkout -b` / `git worktree add` / sprint fork:

1. `git status --porcelain` — if anything is modified/untracked, resolve it FIRST.
2. Push the team's already-committed-but-unpushed work (`git push origin <branch>`) — PM's job.
3. Commit remaining pending working-tree work (`git add -A` + a clear `chore: commit pending work before branching` message; preserve files as-is; note in the message it's team/working-tree hygiene).
4. THEN branch/checkout. With a clean tree it's a plain checkout — the worktree dance (see [[feedback-parallel-session-branch-gotcha]]) is only needed when you genuinely cannot commit (e.g., a peer is mid-edit in a truly parallel session).

## Related

- [[feedback-parallel-session-branch-gotcha]] — the worktree fallback when a checkout would flip a peer's tree; commit-before-branch is the cheaper first resort.
- [[feedback-ralph-no-git-commands]] — Ralph leaves code unstaged "per PM protocol"; PM integrates/commits at sprint close + branch points.
