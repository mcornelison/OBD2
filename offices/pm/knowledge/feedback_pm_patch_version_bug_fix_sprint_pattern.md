---
name: pm-patch-version-bug-fix-sprint-pattern
description: Mike's versioning rule -- bug-fix sprints continue patch-versioning until all bugs fixed; minor version bumps only on feature sprints
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
Bug-fix sprints follow patch-version progression on the same minor-version epoch. Minor version bumps only when the next FEATURE sprint ships.

**Why**: Mike 2026-05-08 directive (Q5 in V0.27.2 grooming Q&A): "next sprint if it is a bug fix then it shuld be 0.27.3 continue this pattern until all bugs are fixed." Tied to the 2026-05-08 validation-gated workflow (`main` = "fully validated stable"). Feature sprints set the minor version; bug-fix sprints accumulate patches until the bug list is clean.

**How to apply**:
- Feature sprint with new stories ships V0.X.0 -> minor-version bump (e.g. Sprint 27 = V0.27.0)
- Hotfix on the same epoch (Mike or Ralph) = next patch (V0.X.1)
- Bug-fix sprint after the feature sprint = next patch (V0.X.2)
- Subsequent bug-fix sprint = next patch (V0.X.3, V0.X.4, ...) until no bugs remain
- Next feature sprint then bumps minor -> V0.(X+1).0
- Bug-fix sprints stay distinct sprints with own `sprint.json` + `bigDefinitionOfDone` + branch + `/sprint-deploy-pm` + `/sprint-validated`. Only the version pattern is shared across the chain.
- Bug attribution doesn't matter (Mike Q2: "irreguardless of what sprint is was to be done, this is the bug fix sprint"). The bug-fix sprint owns whatever bugs are on the queue at the time, regardless of which prior sprint introduced them.
- Bug-fix sprint stories STILL get sequential US- IDs from `story_counter.json` -- only the sprint-level VERSION inherits the patch pattern.

**Related**:
- `feedback_pm_semver_convention.md` -- prior SemVer convention; this refines the patch-version usage rule
- `regression_manifest.json` -- features that must keep working; bug-fix sprints can target specific features whose `lastValidated` is broken
- `.claude/commands/sprint-deploy-pm.md` + `sprint-validated.md` -- validation-gated workflow these patch versions live in
