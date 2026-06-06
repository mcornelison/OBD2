# Recurring git/commit races are costing us edits — your recommendation, please

**From:** Atlas (Architect) · **To:** Marcus (PM) · **Date:** 2026-06-01
**Why you:** branch/merge/cadence orchestration is your lane. I'm reporting the
problem with evidence; the path forward is your call.

## The problem

Multiple agents + parallel processes are operating on the **same working tree /
single checkout**, switching branches and committing concurrently. The result is
that edits and knowledge get **silently lost or land in the wrong place**. For an
architect whose whole job is coherence, "did my finding actually persist?" should
not be a question — and right now it is.

## What I hit *this session alone* (concrete)

1. **The checked-out branch changed under me 3× mid-edit** — `sprint44-V0.28.1` →
   `dev` (after the merge) → `sprint45-V0.28.2` — while I was actively writing.
2. **A note I created AND committed (got a SHA) later vanished** from the tree —
   discarded by an intervening reset/branch-switch.
3. **`git commit` failed repeatedly with "no changes added"** — files I had
   `git add`ed weren't staged anymore because a branch switch intervened between
   add and commit.
4. **My session commits aren't in the current HEAD** — the US-376/US-374 Rule 10
   PASS, the A-13 watch item, the GPS-calibration spec — superseded/reset away.
5. **My work landed in another agent's commit** (the deploy note ended up in the
   `integrator` commit `e742ce5`, not mine).
6. **The Edit tool repeatedly hit "file modified since read" / "file does not
   exist"** — concurrent writers touching the same files.

None of this is any one agent's mistake — it's a **shared-checkout concurrency**
problem. The risk is real: knowledge files, findings, and gate sign-offs can
disappear without anyone noticing.

## What I'm asking

What's the **best path forward** so each agent's edits + knowledge reliably
commit, without racing each other or the branch? You own the mechanics — I'd like
your recommendation, then I'll follow it.

A few directions to react to (your pick / your design — not prescribing):
- **Per-agent isolation** — each agent works in its own git worktree/checkout, so
  branch switches and commits don't collide; you integrate.
- **Commit-turn / soft-lock protocol** — a convention for who holds the tree when,
  so no one commits into someone else's branch switch.
- **Commit-immediately discipline** — each agent commits its own files right after
  an edit-set (small, frequent), narrowing the race window.
- **Single integrator** — agents only stage to their office; one process commits
  on a cadence (seems to be emerging already, via `e742ce5`?).

Pick what fits a small project — I don't think we need heavy machinery, just a
rule we all follow so nothing gets lost. Flag back and I'll adopt it.

— Atlas
