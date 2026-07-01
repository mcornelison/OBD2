# TD-057: Shared-checkout stale `.git/index.lock` recurrence — needs a safe auto-clear

| Field | Value |
|---|---|
| Status | open |
| Priority | P2 (recurring; costs sprint hours + forces HUMAN_INTERVENTION) |
| Category | infrastructure / shared-checkout concurrency |
| Size | S–M |
| Created | 2026-06-30 |
| Source | Sprint 49 turnover (Marcus/PM); progress.txt lines 377/428; BL-stale-index-lock-blocks-commit + prior BL-stale-index-lock-blocks-us367 |

## Problem

On the shared chi-nas-01 SMB checkout, a **crashed/orphaned `git` process leaves a 0-byte `.git/index.lock`** that blocks ALL write git ops (`add`/`commit`/`stash`) for every agent, while read ops keep working. It has now recurred across **multiple sprints**:
- **US-367** (Sprint 47 era) — `BL-stale-index-lock-blocks-us367-commit`
- **Sprint 49** — `BL-stale-index-lock-blocks-commit`: blocked Ralph's US-403 + US-404 **and** Atlas's notes **and** the PM PRD for **~2 hours**, forcing `HUMAN_INTERVENTION_REQUIRED` + a manual PM clear.

Handbook §13 Rule-4 ("never force a lock while a git process is running") + the harness gating `rm .git/index.lock` as sensitive means agents correctly **cannot self-clear** — every occurrence escalates to CIO/PM. That's the right safety default but a poor steady state for a recurring event.

## The safe-clear heuristic (validated this sprint)

The PM cleared it safely by verifying: **lock is 0 bytes** (a live commit writes the new index *into* index.lock before rename, so 0-byte = nothing pending) **AND no live `git` process** owns it (only seconds-old diagnostics + Logi**t**ech substring false-matches). Those two conditions together = definitively orphaned → removal loses nothing.

## Proposed fix (pay-down options)

1. **Script `offices/pm/scripts/clear_stale_index_lock.sh`** — encodes the heuristic: remove `.git/index.lock` ONLY if (a) 0 bytes, (b) mtime age > N minutes, (c) no live `git.exe` holding it. Refuse otherwise. Gives agents/PM a *safe* one-command clear instead of a manual forensic + `rm`.
2. **Ralph in-loop hook** — on a lock-blocked commit, ralph.sh runs the guarded clearer (not a bare `rm`) and retries once before escalating.
3. **Investigate the root cause** — why do git processes crash mid-commit on this share (SMB latency? a killed `claude -p` iteration mid-`git add`?). If it's iteration teardown killing git mid-write, add a commit-completion barrier.

## Acceptance Criteria

- [ ] A guarded clearer exists and is documented in handbook §13 (supersedes the "escalate every time" step for the verified-orphaned case).
- [ ] The clearer refuses to act on a non-empty lock or when a live git process is present (fails safe).
- [ ] Ralph's blocker path uses it before emitting HUMAN_INTERVENTION_REQUIRED.

## Cross-references

| Item | Relationship |
|---|---|
| BL-stale-index-lock-blocks-commit | The Sprint-49 occurrence this TD generalizes |
| BL-stale-index-lock-blocks-us367-commit | Prior occurrence — establishes recurrence |
| Handbook §13 Rule-4 | The discipline this TD refines (safe-clear for verified-orphaned) |
