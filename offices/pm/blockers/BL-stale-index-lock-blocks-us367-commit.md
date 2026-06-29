# BL — Stale `.git/index.lock` (~3h) blocks the US-367 commit (whole shared checkout)

**Filed:** 2026-06-29 by Rex (Dev)
**Severity:** HIGH (blocks ALL git writes on the shared checkout, every agent — not just US-367)
**Needs:** CIO judgment + action (clear a stale lock; I will not delete a lock I didn't create headless)

## Summary

US-367 (ECU-lineage 2-row backfill) is **code-complete, green, and ready** — but the
commit cannot land. `Z:\o\OBD2v2\.git\index.lock` exists as a **0-byte file last
modified 2026-06-29 06:09:41** (~3 hours stale at filing). A legitimate git
operation never holds `index.lock` for hours; this is an **orphaned lock** left by
a git process that died/was killed without cleanup. It blocks every `git add` /
`git commit` on the shared checkout for ALL agents.

Per handbook §13 ("never delete it while a `git` process is running") + my own
rule ("you didn't create it → surface it, don't delete"), I did NOT delete it.
I cannot confirm process-absence in this headless run (process-listing commands
are approval-gated), so clearing it is a CIO call.

## What IS done (all on disk, just uncommitted)

- `src/server/cli/backfill_ecu_lineage.py` (new) — one-shot ECU-lineage bootstrap CLI.
- `tests/server/cli/test_backfill_ecu_lineage.py` (new) — 9 tests, all green.
- `offices/ralph/sprint.json` — US-367 `passes:true` + completionNotes + feedback.
- `offices/ralph/ralph_agents.json` — Rex unassigned, fresh close note.
- `offices/ralph/progress.txt` — US-367 session entry appended.
- `offices/pm/inbox/2026-06-29-from-rex-us367-backfill-shipped.md` — PM/Atlas note.

Gates already passed: `tests/server/cli` = 32 passed (zero regression); ruff clean
on both new files; end-to-end smoke run confirmed V-1..V-7 + the 2-prior/2-new
partition. Sprint 47 / V0.29.1 is **9/9 `passes:true`** in sprint.json on disk.

## CIO remediation (recommended order)

1. **Confirm no git process holds the lock** (the team's helper):
   ```
   powershell -ExecutionPolicy Bypass -File check_git_procs.ps1
   ```
   Expect `GIT_PROC_COUNT=0` and a multi-hour `LOCK_EXISTS age_s=...`.
2. **If and only if `GIT_PROC_COUNT=0`, delete the stale lock:**
   ```
   rm "Z:/o/OBD2v2/.git/index.lock"
   ```
3. **Land the prepared commit** (idempotent — re-stages + commits the 6 files above):
   ```
   bash us367_commit.sh
   ```
   (A background instance of this script may already be retrying; check
   `git log -1 --oneline` first — if it already shows the US-367 feat commit, the
   lock cleared on its own and no action 3 is needed.)
4. Then Sprint 47 is fully landed; proceed to `/sprint-deploy-pm` (the live-DB
   backfill run + V-1..V-7 SELECTs + dtc_freeze_frame re-drain are the deploy-time
   steps documented in the PM note).

## Note

This stale lock is a TEAM-WIDE infra issue, independent of US-367 — any agent
trying to commit right now is blocked by the same lock.
