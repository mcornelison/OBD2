# PM Action Items

Operational follow-ups gated on sprint code shipping. **Not** sprint stories, **not** TDs, **not** issues — these are tasks owned by Marcus (PM) or by humans (CIO, Spool) that fall outside the dev-only sprint scope per `feedback_sprint_scope_dev_only.md`.

Format per item:
- **AI-NNN** Title — Owner — Status — Filed date — Source

---

## Open

### AI-001 Phantom-path drift in `sprint.json scope.filesToTouch` — fix Marcus-side template generator
- **Owner**: Marcus (PM)
- **Status**: open
- **Filed**: 2026-05-01
- **Source**: Spool sprint22-drain-forensics-spec Story 7 + 8-session pattern noted in MEMORY.md "Small open items"

**Pattern**: Across Sprints 14-21 (8 sessions), Ralph has surfaced ~1 phantom path per sprint in `sprint.json` story scope.filesToTouch — paths that don't exist in the current repo state at sprint-load time. Recent example: Sprint 21 US-252 listed `src/pi/data/database_schema.py` but actual path is `src/pi/obdii/database_schema.py` (Pi schema lives at `obdii/`, not `data/`). Ralph wastes audit-time tracking down the real path on every occurrence.

**Why this is a PM action item, not a sprint story**: This is template-generator work on the PM side (Marcus's grooming workflow), not Ralph dev/code work. Per Sprint 19+ dev-only sprint scope rule, it cannot live in `sprint.json`.

**Proposed remediation**:
1. Add a pre-flight check to `offices/pm/scripts/sprint_lint.py` that walks every story's `scope.filesToTouch`, strips any parenthetical commentary, and verifies the path exists in the current repo state. NEW files (annotated `(NEW ...)`) are exempt — only UPDATE-paths get the existence check.
2. Run lint at story-add time AND before commit. Document the workflow in `offices/pm/projectManager.md` PM Rules.
3. Optional follow-up: when grooming a new story, batch-grep the proposed paths via `Glob` before writing the contract.

**Acceptance** (Marcus self-checks):
- `sprint_lint.py` flags non-existent UPDATE paths as `error` (not warning) on the next sprint contract.
- Run on Sprint 22 contract and confirm zero phantom paths (current state).
- Schedule the lint addition for next PM session (not Sprint 22 — out of dev scope).

---

## Closed

### AI-002 Ralph commit-but-not-stage detector — sprint_lint commit-vs-claim verifier
- **Owner**: Ralph (via Sprint 24 US-282)
- **Status**: Resolved (2026-05-03, Sprint 24 US-282, Rex Session 155)
- **Filed**: 2026-05-03
- **Source**: Sprint 22 US-262 rescue commit `096dade` + Sprint 23 US-275/276/277 rescue commit `6d8af99`

**Pattern**: Twice in two sprints, Ralph's per-story `feat:` commits LOG the work in commit messages + populate `sprint.json feedback.filesActuallyTouched` lists, but the actual src/test/deploy file changes only land in working tree (never staged). Sprint-close merge brings empty story commits to main; PM catches it via post-merge `git status`; rescue commit recovers the work. PM-side detection cost is high — only caught at sprint close by accident.

**Remediation** (shipped Sprint 24 US-282): extended `offices/pm/scripts/sprint_lint.py` with `lintFeedbackVsTreeDiff(story, repoRoot, sprintBaseRef)` function + `_collectChangedFilesSinceRef` + `_resolveSprintBaseRef` helpers + `--check-feedback` CLI flag (OPT-IN). For each story with populated `feedback.filesActuallyTouched`, walks `git log <merge-base HEAD main>..HEAD` and asserts every claimed path (parenthetical-stripped via existing `parseFilesToTouchEntry` helper) appears in at least one commit's tree-diff. Emits `feedback claim missing from commits: '<path>'` per missing path. Default off so pre-ship lint runs (empty feedback by design) do not spurious-fail.

**First-catch in same sprint**: Running `--check-feedback` against current Sprint 24 sprint.json caught **US-280's** claim of `tests/pi/power/test_orchestrator_state_file.py` — file exists on disk (working-tree modification) but is not in any commit between sprint base (`cd8088c`) and HEAD. **Third occurrence of the bug-class in three consecutive sprints** (Sprint 22 US-262 → rescue `096dade`; Sprint 23 US-275/276/277 → rescue `6d8af99`; Sprint 24 US-280 → caught by US-282 in same sprint). PM/CIO action: retroactive ship-commit pattern (similar shape to `096dade` and `6d8af99`) before sprint-close merge to bring US-280's working-tree changes onto the sprint branch. The catch IS the durable-fix's proof-of-concept — first sprint with the check prevented the bug from reaching main silently.

---
