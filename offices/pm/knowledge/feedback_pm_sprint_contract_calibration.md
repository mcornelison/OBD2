---
name: PM Sprint Contract — Calibration Notes (Sprint 14 audit findings)
description: Sprint Contract v1.0 spec sizing caps (S ≤2 filesToTouch / M ≤5 / L ≤10) are systematically tighter than this project's reality; pre-flight audit + feedback scaffold + passes:false defaults must be set explicitly when authoring stories.
type: feedback
originSessionId: 8097548c-53b0-4bc3-b07b-fa89f7118840
---
Session 24 audit (via `offices/pm/scripts/sprint_lint.py`) of Sprint 14's 12 stories found 0 schema errors but 36 warnings — all systemic.

**Why:** When CIO directed a thorough specs review during Sprint 14 wait time, I re-read `docs/superpowers/specs/2026-04-14-sprint-contract-design.md` and found my Sprint 14 stories had been violating the spec in three classes (one I didn't catch until the lint tool surfaced them).

**How to apply when authoring future sprint contracts:**

### Required fields I've been omitting
- `feedback: {filesActuallyTouched: null, grounding: null}` — REQUIRED scaffold per spec; Ralph populates as he works. I'd been omitting entirely and using `passes/completedDate/completionNotes` instead.
- `passes: false` (NOT `null`) — required default until story complete. `null` was a my-invention.
- First acceptance criterion should be the **pre-flight audit**: "Produce pre-flight audit listing files to touch, unknowns, and assumptions before any code change." None of my Sprint 14 stories included this.

### Sizing cap divergence (project-specific calibration)
The spec caps don't match this project's reality. My Sprint 14 stories typically have 7-15 filesToTouch and 8-12 acceptance criteria. Spec caps:

| Size | spec filesToTouch | spec acceptance | this project's actual |
|------|-------------------|-----------------|----------------------|
| S    | ≤2                | ≤3              | 7-12                 |
| M    | ≤5                | ≤5              | 9-16                 |
| L    | ≤10               | ≤8              | (haven't used L yet) |

Ralph completes these "oversized" stories cleanly (US-202 hit 12 filesToTouch and shipped fine). Two interpretations:
- (a) The spec caps are too tight for this project; the lint warnings are noise.
- (b) I've been undersizing; what I call S is really L; should require `pmSignOff` on most stories.

For now, treat spec sizing-cap warnings as **informational** (not blocking). If story velocity drops or Ralph starts filing more blockers, re-read this and consider tightening. **Don't retroactively re-size mid-sprint** — disrupts Ralph's planning.

### Banned phrases to scan for
- `handle edge cases`, `works correctly`, `good UX`, `as appropriate`, `if needed`
- `etc.` / `and so on` — use explicit lists instead
- `make sure that`
- `verify` without a specific command
- `tests pass` without a specific pytest command

The lint tool catches these. Run before every sprint commit.

### Workflow
Run `python offices/pm/scripts/sprint_lint.py` before every commit touching `offices/ralph/sprint.json`. 0 errors required; warnings reviewed but acceptable mid-sprint.
