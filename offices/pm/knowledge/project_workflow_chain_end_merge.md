---
name: project-workflow-chain-end-merge
description: Mike's 2026-05-08 + 2026-05-10 workflow directives. main = "fully validated stable"; sprint branches stay deployed-but-pre-merge; bug-fix chain (V0.X.1, V0.X.2, ...) merges to main TOGETHER via `/chain-validated` only after the whole chain validates IRL. Replaces prior per-sprint merge model.
metadata:
  type: project
---

# Workflow — chain-end-merge model

## Mike directive 2026-05-08 (morning)

Main branch = "fully validated stable." Sprint branches stay DEPLOYED-BUT-PRE-MERGE until real-hardware drill validates the affected features per `validation.bigDefinitionOfDone` in `sprint.json`. Patch versioning iterates on sprint branch (V0.X.0 → V0.X.1 → ... until validated). Then `/sprint-validated` merges to main as V0.X.N.

## Mike Q5 directive 2026-05-08 evening

Bug-fix sprints follow patch-version progression on the same minor-version epoch:
- Feature sprint = V0.X.0
- Subsequent bug-fix sprints = V0.X.1, V0.X.2, V0.X.3 ... until bugs clear
- Next FEATURE sprint then bumps minor (V0.(X+1).0)
- Bug attribution is irrelevant — the active bug-fix sprint owns whatever bugs are queued, regardless of which prior sprint introduced them.

See [[feedback-pm-patch-version-bug-fix-sprint-pattern]].

## Mike 2026-05-10 directive — chain-end-merge

Bug-fix chain (V0.X.1, V0.X.2, ...) accumulates on sprint branches; main only receives merge when WHOLE chain clean + system fully functional. Per-sprint merges retired. See [[feedback-pm-main-merges-at-chain-end-only]].

## Rituals (slash commands)

`/sprint-close-pm` **retired**; replaced by:

| Command | Purpose |
|---|---|
| **`/sprint-deploy-pm`** | Close + push branch + bump RELEASE on branch + deploy from branch. **NO merge to main.** |
| **`/sprint-validated`** | Runs after Mike confirms drill green; updates `regression_manifest.json` `lastValidated` for sprint's `validatesFeatures`; (per chain-end-merge rule, does NOT merge to main itself) |
| **`/chain-validated`** | Runs after the WHOLE bug-fix chain (V0.X.2 + V0.X.3 + ...) is validated IRL. Aggregates every sprint's validation block, bumps regression manifest, merges chain-tip branch to main, tags. |
| **`/closeout-pm`** | End-of-session ritual — triage inbox, audit sprint, update knowledge, commit PM-side changes, push to sprint branch. NEVER merges mid-sprint. |

## Artifacts that anchor the workflow

- `offices/pm/regression_manifest.json` — 14 user-facing features with `lastValidated` dates + categories + `staleThresholdDays`. Stdlib JSON (no PyYAML dep).
- `offices/pm/scripts/pm_regression_status.py` — queries the manifest; reports OK / STALE / NEVER per feature; suggests next drill triggers.
- `sprint.json` `validation` block — `bigDefinitionOfDone` (clauses) + `validationMethod` + `validatesFeatures` (FK to manifest) + `currentVersion` + `validatedAt`/`By`. **Required Sprint 28+** per `sprint_lint.lintSprintValidation`.

## Loop behavior

- If drill reveals regression: fix on sprint branch + bump V0.X.Y → V0.X.(Y+1) (patch) + re-run `/sprint-deploy-pm` + retry validation. Loop until validated.
- Sprint N+1 grooming does NOT begin until Sprint N is deployed (validation can be pending).

## Why this exists

Pre-2026-05-08: 27 sprints had "shipped" via synthetic-test gates but never validated end-to-end IRL. The basic loop ("drive out, log data, return home, sync to server") hadn't been confirmed since Drive 5 (2026-04-29). Some features were NEVER validated in real life (reconnect path, DTC retrieval, self-update, auto-rollback).

This workflow gates merge-to-main on the real-hardware drill that exercises affected features per the sprint's `bigDefinitionOfDone`. Main becomes "validated stable"; rollback is always to a known-good state.

## Cross-references

- [[project-v027-chain-status]] — current V0.27 chain status
- [[feedback-pm-semver-convention]] — SemVer rules
- [[feedback-sprint-branch-workflow]] — sprint-branch isolation
- [[feedback-ralph-no-git-commands]] — Ralph CAN commit, PM owns merges
