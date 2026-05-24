# Sprint 40 / V0.27.16 Dispatch

**From**: Marcus (PM)
**To**: Ralph
**Date**: 2026-05-20 (evening)
**Branch**: `sprint/sprint40-bugfixes-V0.27.16` (already spun from sprint39 tip `62dae11`, pushed to origin)

---

## TL;DR

V0.27 chain re-blocked. Atlas + CIO live in-car drill this evening surfaced two findings reversing this morning's chain-unblock-candidate verdict.

- **F-7 (CRITICAL, chain-blocking)**: ShutdownSequencer state-machine bug in `src/pi/power/power_watch/__main__.py:301-322`. Boot-grace-ignored loss events latch the polling loop blind. ~10 line Python fix per Atlas's prescription.
- **F-8 (HIGH, parallel; not chain-blocking)**: `boot-progress-finalize.service` ExecStop never fires during shutdown. Missing `Conflicts=shutdown.target`. One-line systemd fix. Root cause of "Finding A / CLEAN_COMPLETE instrument honesty" (open since V0.27.13; now in-scope).

Sprint contract at `offices/ralph/sprint.json` is the authoritative scope. 4 stories US-344..US-347 (T1..T4 per Atlas's task spine). All size S; all priority high.

## Read first (in this order)

1. `offices/ralph/sprint.json` — Sprint 40 contract (4 stories US-344..US-347)
2. `offices/pm/inbox/2026-05-20-from-atlas-chain-merge-BLOCKED-F7-and-F8-findings.md` — Atlas's full inbox note to PM (TL;DR + task spine proposal that PM ratified into the sprint.json above)
3. `offices/architect/findings/2026-05-20-shutdown-sequencer-boot-grace-latch-bug.md` — Atlas F-7 RCA + evidence bundle
4. `offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md` — Atlas F-8 RCA + evidence bundle
5. `offices/pm/blockers/BL-019.md` + `offices/pm/issues/I-039-boot-progress-finalize-execstop-never-fires.md` — PM pointer files (cross-links only; substance lives in Atlas's findings)

## Story sequencing per sprint.json deps

- **US-344 (T1)** + **US-345 (T2)** parallel — independent code paths, can run in either order or concurrently
- **US-346 (T3)** depends on T1 + T2 — `specs/architecture.md` §10.6 amendment documents both fixes (PM Rule 10 design-gate DoD applies; Atlas BLOCKs if not in-sprint)
- **US-347 (T4)** depends on T1 + T2 + T3 — in-car re-validation drill (Test 2 reproduction + Test 1 control + F-8 instrument verification on first reboot)

## Atlas gate cadence (mirrors Sprint 39 §9 pattern)

Atlas pre-registers per-task gate criteria when you dispatch each task. The acceptance criteria in `sprint.json` are the PM contract baseline; Atlas may amend at dispatch. Expect a per-task GATE-PASS or GATE-CHANGES-REQUESTED note in your inbox like Sprint 39's `2026-05-18-from-atlas-task1-GATE-PASS.md` etc.

## Constraints PM is tracking

- **PM Rule 10 design-gate DoD** applies to T3 (US-346). Atlas BLOCKs the sprint if `specs/architecture.md` §10.6 isn't updated in-sprint. PM administers; Atlas owns the gate.
- **Stacked-chain rule**: V0.27.16 stacks on V0.27.15 per Mike 2026-05-08/10. Do not merge to main; do not bump regression_manifest features (Tester's lane post-`/sprint-validated`).
- **No re-archiving of Sprint 39 artifacts**: Sprint 39 / V0.27.15 evidence bundles stay in place. T4 evidence bundles are new under `sprint40-test-1/` + `sprint40-test-2/` directories (or whatever Atlas prescribes at T4 dispatch).

## Two lint failures still standing RED from V0.27.15 ship

CIO chose deploy-anyway override; both still owed:
- **B-044**: hardcoded `chi-srv-01` in `src/pi/power/power_watch/tasks/sync_with_server.py:82` (defensive log message string). Fix options: (a) config interpolation; (b) `# b044-exempt: log message text only, not a network target` comment.
- **`prompt.md` / `ralph.sh` promise-tag drift**: `prompt.md` documents promise tags `['COMPLETE', 'PARTIAL_BLOCKED']`; `ralph.sh` doesn't handle `PARTIAL_BLOCKED`. Reconcile one or the other.

If you have bandwidth in Sprint 40, fold these in as supplemental commits. If not, surface a TD-054 placeholder and we'll defer to next sprint.

## What PM does next

- Monitors progress (you commit; PM does NOT run code; PM merges only at `/sprint-deploy-pm` / `/chain-validated`)
- Runs `/sprint-deploy-pm` after T1 + T2 + Atlas gate-pass land (deploys V0.27.16 to Pi + server, stacked on V0.27.15)
- Waits for T4 in-car drill (CIO observes; Atlas gates) before `/sprint-validated` (Tester) + `/chain-validated` (PM)

Sprint contract is the contract of record. Questions about scope → ping me. Questions about per-task technical gates → Atlas.

— Marcus
