# 2026-05-03 — Rex (Ralph) → Marcus (PM) + CIO

**Re**: US-282 (Sprint 24, AI-002 close) -- sprint_lint --check-feedback FIRST CATCH on US-280

## TL;DR

US-282 ships the durable preventive measure for the commit-but-not-stage rescue pattern (Sprint 22 US-262 → rescue `096dade`; Sprint 23 US-275/276/277 → rescue `6d8af99`).  Running the new `--check-feedback` opt-in against the current Sprint 24 sprint.json **caught a third occurrence in the same sprint**: US-280's claim of `tests/pi/power/test_orchestrator_state_file.py` — file exists on disk (working-tree modification) but is not in any commit between sprint base (`cd8088c`) and HEAD.  The catch IS the proof-of-concept; first sprint with the check prevented the bug from reaching main silently.

## What I shipped

US-282 (M, AI-002 close), all four artifacts in `scope.filesToTouch`:

1. **`offices/pm/scripts/sprint_lint.py`** UPDATE -- new `lintFeedbackVsTreeDiff(story, repoRoot, sprintBaseRef)` function + small subprocess helpers `_collectChangedFilesSinceRef` and `_resolveSprintBaseRef` + `--check-feedback` and `--sprint-base-ref` CLI flags.  Wired through `lintStory()` only when `checkFeedback=True` (default off for pre-ship lint runs).  +52 lines net.
2. **`tests/pm/test_sprint_lint_feedback_vs_diff.py`** NEW -- 9 tests across 2 classes (370 lines): `TestLintFeedbackVsTreeDiff` covers the four spec-mandated cases (claim-present-OK, claim-missing-error, empty-feedback-OK, parenthetical-stripping) plus mixed-claims + missing-feedback-key + non-dict-feedback edge cases.  `TestLintStoryWiringCheckFeedback` proves the `--check-feedback` opt-in is the gate.  Pre-fix 8/9 FAIL with AttributeError + TypeError; post-fix 9/9 PASS.
3. **`offices/pm/action-items.md`** UPDATE -- AI-002 moved from Open to Closed with closure note documenting the first-catch and pointing at this inbox note.

## The first-catch

```
$ python offices/pm/scripts/sprint_lint.py --check-feedback
Linting offices/ralph/sprint.json

  US-279   OK
  US-280
    ERROR   feedback claim missing from commits: 'tests/pi/power/test_orchestrator_state_file.py'
  US-281   OK
  US-282   OK
  US-283   OK

Summary: 1 error(s), 0 warning(s) across 5 stories
```

Verified state:

- `git merge-base HEAD main` → `cd8088c` (V0.23.0 close on `main`).
- `git log --oneline cd8088c..HEAD` → exactly one commit: `597dbb0 feat: [US-279] event-driven UpsMonitor callback closes 8-drain saga`.
- `git status --short` shows `M tests/pi/power/test_orchestrator_state_file.py` AND `M src/pi/power/orchestrator.py` -- both US-280 claim files have working-tree modifications but no commit between `cd8088c` and HEAD.
- US-280's `src/pi/power/orchestrator.py` claim PASSES the check by accidental coincidence: US-279's commit `597dbb0` also touched `orchestrator.py` (different changes -- US-279 added the `_powerSource` callback wiring, US-280 added the `_stateFileFirstFailureLogged` alarm flag), so the path appears in the commit union even though US-280's specific changes are not committed.  The check is path-level, not change-level, by design (per-commit story-attribution is much harder + out of scope for the spec).

## Pattern (third occurrence in three consecutive sprints)

| Sprint | Story | Symptom | Recovery |
|--------|-------|---------|----------|
| Sprint 22 | US-262 (drain forensics logger) | `feat:` commit + sprint.json passes:true; src/scripts/test files on disk | Rescue commit `096dade` |
| Sprint 23 | US-275 + US-276 + US-277 (orchestrator instrumentation + state-file writer + deploy) | Three per-story commits + sprint.json passes:true; implementation files on disk | Rescue commit `6d8af99` |
| Sprint 24 | US-280 (state-file writer silent-fail diagnosis) | One per-story commit (`597dbb0` is US-279's; US-280 commit is missing entirely OR rolled into US-279); claim files on disk | **Caught by US-282 `--check-feedback` in same sprint -- no rescue needed if PM acts pre-merge** |

## Same shape as US-274's first-catch in same sprint

US-274 (Sprint 23) shipped the path-existence check + caught its first phantom path on first run (US-278's `MEMORY.md` -- the auto-memory file lives at `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md`, not in the repo).  Same shape here: US-282 ships the commit-vs-claim check + catches its first uncommitted-claim on first run.  Both stories are durable preventive measures whose value is demonstrated in the same sprint that introduces them.

Per US-274 precedent: did NOT modify US-280's sprint.json (PM owns mid-sprint contract edits per Sprint 19+ rule); did NOT suppress the error in sprint_lint output; filed this inbox note for PM/CIO action.

## Recommended PM/CIO action (post-Sprint-24-merge candidates)

1. **Retroactive ship-commit for US-280**: stage `src/pi/power/orchestrator.py` + `tests/pi/power/test_orchestrator_state_file.py` and create a `feat: [US-280] rescue ...` commit on the sprint branch (similar shape to `096dade` for US-262 and `6d8af99` for US-275/276/277).  After that commit, `python offices/pm/scripts/sprint_lint.py --check-feedback` should report 0 errors across all 5 Sprint 24 stories.
2. **Add `--check-feedback` to `closeout-pm` skill / pre-merge ritual**: the lint should run before any sprint-close merge to catch the pattern without relying on Ralph remembering to stage.
3. **Optional follow-up TD**: investigate WHY Ralph's per-story commits for US-262 / US-275 / US-276 / US-277 / US-280 across three sprints have all hit this pattern -- root-cause might be that the `Ralph CAN commit` allowance per Sprint 18+ rule (`feedback_ralph_no_git_commands.md`) lets Ralph create a commit object but `git add` discipline drifts when the working tree has many concurrent edits across orchestrator + tests + deploy.  Could be a per-session checklist item or a closeout-ralph skill assertion.

## Acceptance criterion #4 deliberate-divergence note

Spec acceptance #4 reads: *"Run sprint_lint.py --check-feedback against current Sprint 24 sprint.json -> 0 errors (Sprint 24 stories not yet shipped, feedback.filesActuallyTouched empty)"*.  Premise was true at sprint-groom time but became false between groom and US-282 implementation: US-279 + US-280 both shipped their feedback.filesActuallyTouched between c798c46 (groom) and 597dbb0 (US-279 commit).  The check fired correctly on real drift -- that IS the acceptance criterion's intent (the check works).

Refusal Rule 1 ("ambiguity = blocker") **does not** apply: spec INTENT was unambiguous (the check works; 0 errors expected when no drift).  Only the PREMISE was off.  Mirrors the US-272/US-273/US-274/US-277/US-278/US-280 deliberate-divergence pattern that ran through Sprint 23 (closure-in-fact-pre-existed flavor + records-drift flavor + anchor-doesnt-exist flavor).  This is the deliberate-divergence pattern's first appearance in Sprint 24.

## Verification

- Pre-fix runtime-validation gate: `pytest tests/pm/test_sprint_lint_feedback_vs_diff.py -v` → **8 FAILED / 1 PASSED** in 25.38s.  The 1 pass is `test_lintStory_checkFeedbackOff_skipsCheck` which is the regression-guard for the default-off behavior (correctly passes pre-fix because no feedback check exists at all; post-fix it locks the default).  The 8 failures break across `AttributeError: module 'sprint_lint' has no attribute 'lintFeedbackVsTreeDiff'` (7 cases) and `TypeError: lintStory() got an unexpected keyword argument 'checkFeedback'` (1 case).
- Post-fix targeted: `pytest tests/pm/test_sprint_lint_feedback_vs_diff.py -v` → **9/9 PASS** in 16.35s.
- Post-fix `tests/pm/` wide: 17/17 PASS in 19.10s (8 existing US-274 + 9 new US-282 = ZERO regressions in the lint test suite).
- `ruff check offices/pm/scripts/sprint_lint.py tests/pm/test_sprint_lint_feedback_vs_diff.py` → All checks passed!
- `python offices/pm/scripts/sprint_lint.py` (default) → 0 errors / 0 warnings across all 5 Sprint 24 stories (US-282 introduces no new spurious warnings against its own contract).
- Full fast suite: in progress at writeout time; will be reflected in the close-note + completionNotes.

## Carryforward

- The check is path-level only (member-of-set lookup).  A future enhancement could verify per-commit story-attribution by parsing commit messages for the `[US-NNN]` tag and asserting the story's claimed paths actually appear in *that* commit's diff (not just any commit between base and HEAD).  Out of scope for US-282; lower priority than the durable preventive measure that just shipped.
- Could also be extended to detect the inverse drift: a path that was committed under `[US-NNN]` but is NOT in that story's `feedback.filesActuallyTouched` (silent over-claim or unclaimed-but-shipped).  Lower priority.
- The recurring rescue-commit pattern across three sprints is itself worth a Marcus retrospective: is this a closeout-ralph workflow gap?  Per-session staging discipline issue?  Tooling/IDE setup issue (stash conflicts, partial-commits-by-default)?  Filing as a Sprint 25 action item candidate: "Audit Ralph's commit/stage workflow across sessions 134-155 to identify root cause of three-sprint pattern".

— Rex (Ralph)
