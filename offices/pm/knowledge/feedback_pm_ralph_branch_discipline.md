---
name: pm-ralph-branch-discipline
description: Mike's hard rule -- Ralph never works on main; sprint branch always; main only takes verified sprints
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
Ralph (and any dev agent) NEVER commits to main. Always work on a sprint branch. Main only receives verified sprints via `/sprint-validated` (or equivalent merge ritual after IRL drill passes).

**Why**: Mike 2026-05-09 directive: "going forward we should have had a branch for his work. just so we dont 1: work on the main branch and 2: we dont push to main until the sprint is verified." Reinforces the 2026-05-08 validation-gated workflow (`main` = "fully validated stable") with explicit branch-discipline. Triggered by my Path A execution which committed V0.27.1 directly to main (Sprint 27 was already merged so the sprint branch was effectively retired) -- that was authorized for that specific case but is NOT the going-forward norm.

**How to apply**:
- BEFORE Ralph starts a sprint, PM creates the sprint branch (`sprint/sprintN-<theme>` or `sprint/sprintN-bugfixes-V0.X.Y`) and commits the sprint.json contract to it.
- Ralph commits ALL implementation work to the sprint branch -- never to main.
- `/sprint-deploy-pm` deploys FROM the sprint branch (already designed this way; reinforced).
- Mike validates IRL. PM runs `/sprint-validated`. Only THEN does the sprint branch merge to main.
- Hotfixes that bypass the sprint flow (e.g. Mike applies a patch directly): use a `hotfix/V0.X.Y-<theme>` branch, NOT main directly. Pattern precedent: `hotfix/V0.24.1-ladder-enum-identity`.
- Path-A-style "commit directly to main" is reserved for cases where the sprint was already merged AND validation is being applied retroactively (rare; should be a one-off).

**Anti-pattern to avoid**: Mike sees Ralph's working-tree changes on main + assumes Ralph "did the work" but a sprint branch was never created. PM should ALWAYS confirm sprint branch existence before signaling Ralph to start work. Pre-flight check: `git branch | grep sprint/sprintN` should return a hit before Ralph begins.

**Related**:
- `feedback_pm_patch_version_bug_fix_sprint_pattern.md` -- bug-fix sprints chain patch versions on the same epoch
- `.claude/commands/sprint-deploy-pm.md` -- deploys FROM sprint branch
- `.claude/commands/sprint-validated.md` -- merges sprint branch to main after IRL drill
- 2026-05-08 workflow doc: main = "fully validated stable"
