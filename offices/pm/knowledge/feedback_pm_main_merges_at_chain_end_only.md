---
name: PM merges to main only at end of V0.X chain (not per-sprint), once main becomes "fully functional working system"
description: Reinforcement of validation-gated workflow. The bug-fix sprint chain (V0.X.1, V0.X.2, V0.X.3, ...) accumulates on sprint branches without merging to main. Only when ALL bugs in the chain are fixed AND the resulting state is "fully functional working" does the chain merge to main. Per-sprint merges (the prior /sprint-validated default) are NOT the norm.
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
Main branch carries "fully functional working system" -- a stronger bar than "validated per individual sprint." The bug-fix sprint chain accumulates on branches.

**Why**: Mike 2026-05-10 directive: "we never merged Maine. unless everything is working right now, we have bug fixes until all the bug fixes are complete then and only then do we merge to Maine. main needs to be a fully functional working system."

This refines the 2026-05-08 validation-gated workflow. Previously: each sprint validates IRL -> /sprint-validated merges to main. Now: bug-fix sprints (V0.X.1, V0.X.2, ...) accumulate on a chain of sprint branches; main only receives the merge once the whole chain is clean + the resulting state IS the fully functional working system.

**How to apply**:

- Per-sprint /sprint-validated NOT auto-merge to main. It bumps `regression_manifest.json.lastValidated` + marks `sprint.json.validation.validatedAt/By` + records the validation, but DOES NOT `git merge` to main.
- The merge to main is a separate, deliberate act ("/chain-validated" or equivalent) that happens when:
  1. All known bugs in the V0.X chain are fixed (no open BL-XXX, no I-XXX scheduled for the chain still pending)
  2. Main + chain-tip difference is purely additive (V0.X.1 fixes -> V0.X.2 fixes -> ... -> V0.X.N fixes; no destructive rollback)
  3. The resulting state has been IRL-validated AS A WHOLE (not just per-sprint slices)
- V0.X.(N+1) sprint branches FROM V0.X.N sprint branch (cumulative chain), NOT from main. Each sprint inherits the prior sprint's fixes.
- When the chain finally merges to main, main bumps to V0.X.N (the chain-tip version) directly. Main never sees intermediate V0.X.1 / V0.X.2 / V0.X.(N-1) commits as separate merges.

**Anti-patterns this rule prevents**:
- Main carries V0.X.2 fixes but lacks V0.X.3 fixes that surfaced later -> main is "validated per its slice" but not "fully functional working"
- Per-sprint merges accumulate ratchets that have to be undone if a later sprint reveals a regression in a prior fix
- Confusion about "what is on main" mid-chain (is V0.X.2 on main? V0.X.3? half of each?)

**When this rule was set vs prior state**:
- 2026-05-08 (Mike directive): main = "fully validated stable"; sprint branches stay deployed-but-pre-merge until real-hardware drill validates affected features.
- 2026-05-10 (Mike refinement, this rule): main = "fully functional working system" -- stronger than per-sprint validated; the WHOLE chain must be working before merge.
- V0.27.1 was merged to main 2026-05-09 under the prior rule (Path A). Grandfathered. V0.27.2 + V0.27.3 + ... accumulate on branches and won't merge until the V0.27 epoch closes "fully working."

**Cross-references**:
- `feedback_pm_patch_version_bug_fix_sprint_pattern.md` -- companion rule about V0.X.N patch chains
- `feedback_pm_ralph_branch_discipline.md` -- Ralph never commits to main; this rule extends to PM merges as well
- `.claude/commands/sprint-validated.md` -- needs review against this rule (per-sprint merge behavior may need to be retired or split into a chain-end variant)
