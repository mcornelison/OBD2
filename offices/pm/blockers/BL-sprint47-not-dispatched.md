# BL — Sprint 47 / V0.29.1 not dispatched (no sprint branch; dispatch gates open)

- **Filed by:** Rex (Ralph, Agent 1), headless iteration
- **Date:** 2026-06-28
- **Severity:** Blocks ALL Sprint 47 stories (environment not ready for a Ralph iteration)
- **Tag emitted:** HUMAN_INTERVENTION_REQUIRED

## Situation

`ralph.sh` started a Ralph iteration, but Sprint 47 / V0.29.1 is **frozen-pending-gates, not dispatched**. I refused-first (Rule 1) rather than build against an undispatched, possibly-still-changing sprint.

## Evidence

1. **No sprint branch.** `git branch` shows no `sprint/sprint47-V0.29.1`. Every prior sprint (sprint20…sprint46) has its own branch; Sprint 47 has none. Working checkout is on `dev`.
2. **HEAD = the freeze hand-off.** `5788c4c freeze(pm): Sprint 47/V0.29.1 frozen + routed to Atlas for Rule-13` is the tip — nothing after it. Atlas Rule-13 sign-off has not landed in history.
3. **Documented gate sequence still open** (Session 49 closeout pointer): Atlas Rule-13 → `/resize-sprint` split decision (9 stories = large; candidate split **47a** A-9 US-386..390 / **47b** US-367/391/392/379) → PM creates `sprint/sprint47-V0.29.1` → dispatch. None of these are done.
4. **`ralph_agents.json` is stale.** Agent 1 (Rex) still shows `status: active` / `taskid: ""` from Sprint 46 closeout (lastCheck 2026-06-19).

## Why this blocks (not just a nit)

- Ralph must commit to **the current sprint branch**; there is none. Committing to `dev` violates the dev/main isolation workflow (sprint work merges to dev via `/sprint-deploy-pm` Phase 3.5, not by Ralph committing straight to dev). Leaving work uncommitted loses it on the PM's eventual branch switch (handbook §13).
- Ralph is forbidden from creating/switching branches — that's PM-owned.
- A pending `/resize-sprint` split could re-shape stories (e.g. US-386 lands in 47a) — building now risks rework.

## Requested PM (Marcus) actions to unblock

1. Confirm **Atlas Rule-13** PASS on the frozen `bigDoDHash` (`687eb90b…`).
2. Make the **`/resize-sprint`** call: ship 9-story Sprint 47 whole, or split 47a/47b. Update `sprint.json` accordingly (re-freeze if scope changes).
3. Create + switch to `sprint/sprint47-V0.29.1` (fork from `dev`), announce the quiet window.
4. Then re-run `ralph.sh` — Agent 1 will pick US-386 (highest-priority, buildable: pure in-process RED reproducer, no IRL).

## Note on carry-forward (not part of this blocker, FYI)

Sprint 46 / V0.29.0 still awaits the Pi `pi.bus.enabled` flag-flip + byte-identical validation → `/sprint-validated`. Memory says to fold that into the same Pi deploy window as the Sprint 47 A-9 IRL re-gate.
