# V0.27.11 Ready For Deploy — Sprint Handoff
**Date:** 2026-05-15
**From:** Ralph (Dev) — Session 201
**To:** Marcus (PM)
**Priority:** P0 (chain-blocker; Drain 23 IRL gate downstream)

## TL;DR

Sprint 37 / V0.27.11 is **complete in-session** per CIO directive. All 3 stories `passes: true`, full Pi suite green, ruff clean, sprint_lint 0 errors (6 informational warnings). Changes left **unstaged** for your `/sprint-deploy-pm` ritual. Branch: `sprint/sprint37-bugfixes-V0.27.11` (from V0.27.10 tip `c6e218a`).

## What shipped

| Story | Title | Result |
|---|---|---|
| US-341 | I-036 polkit + Strategy G `_executeShutdown` hardening | passes:true |
| US-342 | I-037 LADDER_GRACEFUL_GREP_PATTERN repointed at post-success marker | passes:true |
| US-343 | Historical drain re-audit script + findings template | passes:true |

## Important RCA finding (Spool needs this routed)

**Spool's hypothesis on Bug #2 was empirically wrong.** Spool's 2026-05-15 Drain 22 note proposed: "US-330 retry-fallback returns a default value of 1 after exception-handling." That is incorrect. `git show 76aa773 -- src/pi/diagnostics/boot_reason.py` shows US-330's diff is a pure retry wrapper that returns `[]` on all-attempts-fail, which propagates through to `priorBootClean=None` → DB writes NULL (not 1).

**Actual root cause:** US-308's (2026-05-09) ladder probe pattern `'PowerDownOrchestrator: TRIGGER at'` matches the orchestrator's INTENT marker emitted in `_enterTrigger` at `orchestrator.py:887` *before* the failing `subprocess.run`. Drain 22's prior-boot journal contains the intent marker even though poweroff failed — that's the lie source. **US-330's retry code is innocent and stays untouched.**

This matters for the Spool ack note: please confirm Spool sees this before they sign off on the IRL gate, so the wrong root-cause story doesn't get baked into the regression manifest commentary.

## Files changed (unstaged)

**Code:**
- `src/pi/hardware/shutdown_handler.py` — new `SHUTDOWN_SUCCESS_MARKER` constant + `_executeShutdown` rewrite (emit-on-success, ERROR+raise on failure)
- `src/pi/diagnostics/boot_reason.py` — `LADDER_GRACEFUL_GREP_PATTERN` repointed to the post-success marker

**Tests (new):**
- `tests/pi/hardware/test_shutdown_handler_poweroff_auth.py` (3 tests)
- `tests/pi/diagnostics/test_boot_reason_canary.py` (4 tests)

**Tests (calibration):**
- `tests/pi/hardware/test_shutdown_handler_legacy_suppress.py` — mocks set `returncode=0` for the new raise contract
- `tests/pi/power/test_ladder_vs_legacy_race.py` — same calibration

**Deploy:**
- `deploy/polkit-rules/50-eclipse-obd-poweroff.rules` (NEW)
- `deploy/deploy-pi.sh` — `step_install_polkit_poweroff` function + main-body call

**PM artifacts:**
- `offices/pm/scripts/audit_historical_drain_canary.py` (NEW — US-343)
- `offices/pm/findings/2026-05-15-drain-10-22-canary-re-audit.md` (NEW — template)

**Plan + sprint:**
- `docs/superpowers/plans/2026-05-15-v0-27-11-bugfix.md` (NEW)
- `offices/ralph/sprint.json` — final cooked contract; passes:true x3 + feedback blocks populated

**Knowledge updates (closeout-side):**
- `offices/ralph/progress.txt` — Session 201 entry
- `offices/ralph/ralph_agents.json` — Agent 1 status reset
- `offices/ralph/knowledge/session-learnings.md` — new V0.27.11 lessons
- `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md` — current state pointer

## Verification snapshot

- `pytest tests/pi/hardware/test_shutdown_handler_poweroff_auth.py -v` — 3/3 PASS
- `pytest tests/pi/diagnostics/test_boot_reason_canary.py -v` — 4/4 PASS
- `pytest tests/pi/ -m "not slow" -q` — 1715 tests, exit 0
- `ruff check` on all 7 touched src + test files + audit script — All checks passed
- `bash -n deploy/deploy-pi.sh` — OK
- `bash deploy/deploy-pi.sh --dry-run` — new polkit step prints expected DRY-RUN lines
- `python offices/pm/scripts/audit_historical_drain_canary.py --dry-run` — emits expected SSH-without-execute
- `python offices/pm/scripts/sprint_lint.py` — 0 errors / 6 informational warnings (long titles, acceptance counts > sizing caps — see [[feedback-pm-sprint-contract-calibration]])

## Downstream gates (your call)

1. **`/sprint-deploy-pm`** ritual — sprint complete, RELEASE_VERSION bump, push branch, deploy Pi + server FROM SPRINT BRANCH (per chain-end-merge rule).
2. **Spool bench-mock pre-verification** of polkit + canary fixes (Spool 2026-05-15 note offered this).
3. **Drain 23 IRL** (battery ≥8h rest on charger + V0.27.11 deployed + Spool pre-verified) — the final V0.27 chain merge unblocker.
4. **Drive 12 retest** still required from V0.27.10 chain bigDoD (not blocked by V0.27.11, just owed).

## Side artifact (not part of sprint scope)

Mid-session CIO whiteboard discussion of the Pi-tier runtime workflow produced a design-prompt artifact: `docs/design-prompts/2026-05-15-pi-runtime-workflow-schematic.md`. CIO will run it through a fresh Claude design session and evaluate the produced schematic vs his whiteboard + the existing implementation. **No code action required from you on this** — purely informational, may influence V0.28+ architecture stories down the line.

## Footnote

This was a CIO+Ralph co-piloted session per the 2026-05-15 morning directive. You were in tracking mode for V0.27.11 by design. The contract you placeholder-shell'd this morning got cooked end-to-end by Ralph + CIO directly. Sprint scope, story selection, fix strategy choices (Option A polkit, Strategy G hardening), US-343 inclusion — all CIO calls, captured in the cooked contract.

— Ralph (Session 201)
