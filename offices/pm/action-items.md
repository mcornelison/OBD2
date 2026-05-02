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

(none yet)
