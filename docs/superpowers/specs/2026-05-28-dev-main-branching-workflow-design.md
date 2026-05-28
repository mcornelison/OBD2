# dev/main Branching Workflow (V0.28+) — Design Spec

**Date**: 2026-05-28
**Author**: Marcus (PM) under CIO 2026-05-23 directive #1
**Status**: Design complete — awaiting CIO review before implementation plan
**Scope**: PM Rules 8 + 9 rewrites, `/sprint-deploy-pm` + `/sprint-validated` + `/chain-validated` skill updates, `pm_status.py` minor enhancement. Bootstrap step to create `dev` branch.
**Non-scope**: Validation-criteria-upfront contract changes (directive #2 — separate spec). Backlog hierarchy v2 (directive #3 — shipped 2026-05-27).

---

## 1. Motivation

The V0.27.X chain (15 sprints, V0.27.2 → V0.27.19) demonstrated that the current "sprint branches off `main`" model lets `main` carry deployed-but-not-yet-validated state for weeks at a time, despite the 2026-05-08 directive that `main` = "fully validated stable". The chain-end-merge rule patched this by deferring the main merge to `/chain-validated` at chain tip — but the load-bearing protection was a *convention*, not a structural separation.

Under V0.28+, an integration branch (`dev`) sits between sprint branches and `main`. `main` becomes structurally untouchable mid-chain; `dev` is the deploy + validation target. The chain pattern (V0.X.0 + V0.X.1..V0.X.N patch sprints) is preserved — only the merge target moves from "chain-tip sprint branch" to "dev".

**CIO direction (verbal 2026-05-23, captured in `offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md` §1)**: clean separation. `main` never sees "deployed but not yet validated" state. `dev` is where integration happens + where validation drills run. Sprint branches stay short-lived.

---

## 2. Branch shape

```
main         ───●─────────────────────●───
                │                     │
                │ chain merge V0.28.N │ next chain merge V0.29.M
                ▼                     │
dev          ───●──○──○──○──────────●─┘
                  │ │ │             │
                  │ │ └ V0.28.2     │
                  │ └── V0.28.1     │
                  └──── V0.28.0     │ V0.29.0 minor sprint…
```

- **`main`** = production / fully validated stable. Untouched between chain merges. Tagged on each landing (`V0.X.N`). The only non-chain commit allowed on `main` is a SEV-1 hotfix (see §8.2).
- **`dev`** = integration branch. Accumulates one V0.X.Y chain at a time. Carries the V0.X.0 minor sprint + each V0.X.1..V0.X.N patch sprint stacked. Deploy + IRL validation target this branch.
- **`sprint/sprintN-*`** = short-lived feature/patch branches forked from `dev` HEAD. One sprint = one branch. Merges back to `dev` on code-complete (passes:true). Default-preserved on origin for rollback / audit reference; deletion is CIO-directed cleanup, not automatic.

After `/chain-validated` merges `dev` → `main`, `dev` fast-forwards to match `main` (Phase 6.5) so the next V0.(X+1).0 chain starts from a clean dev = main state.

---

## 3. Per-sprint flow

Executed once per sprint in the chain (one V0.X.0 minor sprint + each V0.X.Y patch sprint that follows on drill-revealed regressions):

1. **PM grooms** a PRD from `offices/pm/backlog.json` (v2.0.0 hierarchy: Stories selected under their parent Feature under parent Epic) → drafts the sprint contract on a new `sprint/sprintN-*` branch forked from `dev` HEAD.
2. **Ralph executes** the sprint per `offices/ralph/sprint.json`; each story flips `passes: true` on completion.
3. **PM runs `/sprint-deploy-pm`** — closes the sprint, **merges sprint branch → `dev` (`--no-ff`)**, bumps `deploy/RELEASE_VERSION` on `dev`, deploys Pi + server **from `dev`** (Pi and server pull `origin/dev`).
4. **CIO + drill runner** exercise `sprint.json validation.bigDefinitionOfDone` clauses IRL against the deployed `dev` state.
5. **PM runs `/sprint-validated`** — stamps `sprint.json validation.validatedAt` + bumps `regression_manifest.json` `lastValidated` for the sprint's `validatesFeatures`. **No merge action** (sprint is already in dev as of step 3).
6. **If drill fails**: a new patch sprint forks from `dev` (still carrying the broken work) → returns to step 1 with V0.X.(Y+1) patch bump. Loop until drill passes.

**Key property**: `dev` *can* briefly carry unvalidated code (between step 3's merge and step 5's stamp). That is acceptable — it is precisely `dev`'s role. `main` never sees unvalidated code under any circumstance covered by this flow.

---

## 4. Chain close (per V0.X minor version)

Executed once when CIO confirms the whole V0.X.Y chain is "fully functional working" (every sprint in chain has `validatedAt` populated AND the system as a whole is ready to ship):

7. **PM runs `/chain-validated`** —
   - Aggregates per-sprint validation evidence across the chain (`chain_validate_aggregate.py --chain V0.X`).
   - Merges `dev` → `main` (`--no-ff`).
   - Tags `V0.X.N` on `main` (where N is the chain-tip patch number).
   - Pushes `main` + tag.
   - Fast-forwards `dev` to match `main` (Phase 6.5 — see §6.3).
   - Next chain (V0.(X+1).0) starts when the next minor sprint branches from `dev`.

---

## 5. PM Rule rewrites

### 5.1 PM Rule 8 — Sprint-branch workflow (REWRITTEN)

> Every sprint runs on its own branch off **`dev`** (not `main`). Marcus creates the branch from `dev` HEAD before loading `sprint.json` and handing off to Ralph. At sprint close, Marcus runs `/sprint-deploy-pm` which merges the sprint branch into `dev` (`--no-ff`), pushes `dev` to origin, bumps `RELEASE_VERSION` on `dev`, and deploys Pi + server **from `dev`**. Sprint branches are short-lived — they close on merge to `dev`. **Does NOT merge to `main`** — that is `/chain-validated`'s job at chain end. Ralph never touches git (per `feedback_ralph_no_git_commands.md`).

### 5.2 PM Rule 9 — Validation-gated chain merge (REWRITTEN)

> `main` = "fully validated stable" — untouched between chain merges. `dev` = integration branch carrying the active V0.X.Y chain (V0.X.0 minor sprint + V0.X.1..V0.X.N patch sprints stacked). Validation drills target `dev`. `/sprint-validated` stamps per-sprint `validation.validatedAt` + bumps `regression_manifest` for the sprint's `validatesFeatures` (no merge — sprint already in dev). When the whole V0.X.Y chain is drill-green per IRL hardware tests AND CIO confirms, `/chain-validated` merges `dev` → `main` (`--no-ff`), tags V0.X.N on `main`, fast-forwards `dev` to match `main`, pushes everything. If a drill reveals regression: new patch sprint forks from `dev` → fix → merge to `dev` via `/sprint-deploy-pm` with V0.X.(Y+1) patch bump → retry validation. Loop until validated. **Source of truth**: `regression_manifest.json` (features list), `sprint.json validation` block (per-sprint criteria; required Sprint 28+ per `sprint_lint.lintSprintValidation`).

### 5.3 PM Rule 10 — unchanged

Design-gate DoD rule continues to apply on sprint branches off `dev`. Atlas's review of architecture-touching work happens at sprint-spin time as before; the branch shape change does not affect the design-gate cadence.

---

## 6. Skill updates

### 6.1 `/sprint-deploy-pm` — phase-by-phase delta

| Phase | Current behavior | New behavior |
|---|---|---|
| 0 | Branch is `sprint/*`, not `main` | Add: sprint branch's merge-base with `dev` equals current `dev` HEAD (sprint branched cleanly off current dev). Abort if branch's parent is `main`. |
| 1 | bump_passed_statuses | unchanged |
| 2 | archive sprint.json + progress.txt | unchanged |
| 3 | PM artifacts (backlog.json, MEMORY.md, projectManager.md) | unchanged semantics — `awaiting-validation` now refers to dev-tip state |
| **3.5 (NEW)** | — | `git checkout dev; git pull origin dev; git merge --no-ff sprint/sprintN-* -m "Merge sprint/sprintN-*: <Sprint Name> code-complete N/N"; git push origin dev` |
| 4 | sprint-deploy commit on sprint branch | retired — Phase 3.5 absorbs the commit semantics |
| 5 | RELEASE_VERSION bump on sprint branch | RELEASE_VERSION bump on `dev`. V0.X.0 first sprint of chain; V0.X.(Y+1) for patch sprints. |
| 6 | deploy from sprint branch | deploy from `dev`. `deploy-pi.sh` + `deploy-server.sh` run with `dev` checked out locally; Pi + server pull `origin/dev`. |
| 7 | verify sprint-branch tip on both targets | verify `dev` HEAD's gitHash on both targets |
| 8 | final summary | unchanged shape; "Status: DEPLOYED — AWAITING VALIDATION" still applies |

**Phase 0 stop condition addition**: if `git merge-base sprint/sprintN-* dev` ≠ `git rev-parse dev`, the sprint branched off a stale dev tip; abort and ask CIO whether to rebase or just merge through.

### 6.2 `/sprint-validated` — phase-by-phase delta

| Phase | Current behavior | New behavior |
|---|---|---|
| 0 | Branch is sprint/*, not main | Branch is `dev` (sprint already merged + closed by `/sprint-deploy-pm` Phase 3.5). If still on sprint branch, abort with hint: `git checkout dev`. |
| 1 | confirm drill evidence | unchanged |
| 2 | stamp sprint.json `validation.validatedAt` | unchanged |
| 3 | bump regression_manifest for `validatesFeatures` | unchanged — bumps land on `dev`'s copy of the manifest |
| 4 | PM artifacts (backlog.json Story/Feature status, MEMORY.md, projectManager.md) | unchanged |
| 5 | commit + push sprint branch | commit + push `dev` |
| **6 (REMOVED)** | merge sprint branch → main | retired — chain merge is `/chain-validated`'s job |
| 7 | optional tag | retired here — tagging moves to `/chain-validated` Phase 5 |
| 8 | final summary | updated end-state line: "Sprint validated. Run `/chain-validated` when CIO confirms the V0.X.Y chain is whole-green." |

### 6.3 `/chain-validated` — phase-by-phase delta

| Phase | Current behavior | New behavior |
|---|---|---|
| 0 | Branch is chain-tip sprint branch | Branch is `dev`. Working tree clean; `dev` pushed to origin. |
| 1 | `chain_validate_aggregate.py --chain V0.X` | unchanged (still walks archived sprint.json by chain prefix) |
| 2 | strict gate `chain_validate_aggregate.py --strict` | unchanged |
| 3 | regression_manifest bump chain-wide | now mostly a no-op (per-sprint `/sprint-validated` already bumped on dev); script remains as a safety net for any held bumps released at chain time |
| 4 | merge chain-tip sprint branch → main | merge `dev` → `main` (`--no-ff` with chain-merge commit message) |
| 5 | tag V0.X.N on main | unchanged |
| 6 | PM artifacts (MEMORY.md, projectManager.md, archive intermediate sprint branches per CIO) | unchanged |
| **6.5 (NEW)** | — | `git checkout dev; git merge --ff-only main; git push origin dev` — fast-forwards dev to match main so V0.(X+1).0 starts from a clean dev = main state. |
| 7 | final summary | "Status: CHAIN MERGED to main = new fully validated stable" — unchanged shape |

**`/chain-validated` keeps its name** (decision 2026-05-27). The chain concept is unchanged — only the merge target moves from chain-tip sprint branch to `dev`. Renaming would force churn in MEMORY.md, projectManager.md, and the handbook for no semantic gain. Description line updated to clarify the dev → main merge.

---

## 7. Bootstrap

One-time setup when this spec lands and CIO directs implementation:

```bash
git checkout main
git pull origin main
git checkout -b dev
git push -u origin dev
```

First V0.28.0 sprint branches from `dev`. No content migration required — `dev` is an exact copy of `main` HEAD at bootstrap time.

---

## 8. Edge cases

### 8.1 Concurrent grooming of Sprint N+1 while Sprint N is awaiting validation

Allowed. Sprint N+1 branches from `dev` HEAD, which carries Sprint N's code. PM judgement call:

- **Default**: groom + write the Sprint N+1 PRD but **do not branch** until Sprint N's drill passes (`/sprint-validated` runs). This keeps dev's lineage clean.
- **If urgent**: branch Sprint N+1 anyway; if Sprint N drill later fails and needs a patch, the patch sprint must integrate with whatever Sprint N+1 has already changed. PM coordinates the merge order.

### 8.2 SEV-1 hotfix on `main` (escape hatch)

Reserved for bugs in shipped `main` that cannot wait for the next V0.X chain to land (security CVE, data-loss regression, etc.):

```
hotfix/<short-slug> branches from main HEAD
                    │
                    fix + test
                    │
                    merges back to main (--no-ff)
                    │
                    tag V0.X.(N+1) on main
                    │
                    cherry-pick or merge to dev (so dev's baseline matches main)
```

This is the **only** scenario where `main` receives a non-chain commit. Requires CIO sign-off before branch creation. Rare; no `/hotfix-pm` skill needed at this time — manual ritual until usage frequency justifies automation.

### 8.3 `regression_manifest.json` semantics

- `/sprint-validated` bumps `lastValidated` on `dev`'s copy of the manifest immediately (per-sprint discipline preserved).
- `/chain-validated` merges `dev` → `main`; `main`'s manifest inherits the bumps via the merge.
- `/chain-validated` Phase 3 (manifest bump chain-wide) becomes mostly a no-op in practice — but the script stays as a safety net for any HELD bumps released at chain time (the Atlas-style "validate the feature only when the rested-pack drain confirms" deferral pattern from V0.27.X chain).

### 8.4 Sprint branches that were code-merged to dev but drill failed

The work stays on `dev`. The next patch sprint branches from `dev` (still carrying the broken work) and fixes it forward. The sprint branch itself stays preserved on origin (audit reference) — its `validation.validatedAt` remains `null` in the archived sprint.json, marking it as "merged but never validated; superseded by patch sprint V0.X.(Y+1)".

### 8.5 What if `dev` and `main` diverge unexpectedly?

If `git pull origin main` during `/chain-validated` Phase 4 brings unexpected commits onto `main` (not via `/chain-validated` or known hotfix), abort. Investigate: was a hotfix run without sign-off? Did someone push to main directly? Resolve before completing the merge. This is the same stop-condition as today's `/chain-validated` — branch shape doesn't change the protection.

---

## 9. Script impacts

| Script | Change required |
|---|---|
| `chain_validate_aggregate.py` | None — still walks archived sprint.json by `--chain V0.X` prefix |
| `chain_validate_manifest_bump.py` | None — operates on manifest only; no branch awareness |
| `pm_status.py` | **Small enhancement**: show "dev tip = V0.X.Y / <hash>" alongside "main tip = V0.(X-1).Z / <hash>" so PM sees both branches at a glance |
| `verify_release_version.py` | None — operates on `deploy/RELEASE_VERSION` file content |
| `bump_passed_statuses.py` | None |
| `archive_sprint_artifacts.py` | None |
| `sprint_lint.py` | Optional soft check: warn if current branch is `main` (not `sprint/*` or `dev`). Not an error — sprint_lint runs in many contexts. |
| `repair_ralph_agents.py` | None |
| `pm_regression_status.py` | None |

---

## 10. Non-goals

- **Validation-criteria-upfront contract** — CIO directive #2; separate spec. This branching spec assumes per-story validation criteria continue to live in `sprint.json validation.bigDefinitionOfDone` and per-story `acceptance` arrays; the actual contract upgrade is a separate piece of work.
- **Backlog hierarchy** — directive #3; shipped 2026-05-27 as backlog v2.0.0 (this spec assumes v2 hierarchy is in place).
- **CI/CD automation of merge gates** — out of scope. PM continues to run merges manually via the three skills.
- **Ralph workflow changes** — Ralph still operates on sprint branches; doesn't see `dev` or `main`. Ralph's git contract is unchanged (`feedback_ralph_no_git_commands.md`).
- **Atlas review cadence** — unchanged. PM Rule 10 design-gate continues to apply at sprint-spin time on sprint branches off `dev`.
- **Skill renames** — `/chain-validated` keeps its name (2026-05-27 decision). The other two skills also keep their names.

---

## 11. Cross-references

- CIO directive 2026-05-23 #1 captured in `offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md` §1
- Existing PM Rules 8 + 9 (to be rewritten) in `offices/pm/projectManager.md`
- PM Rule 10 (unchanged) in `offices/pm/projectManager.md`
- Existing skill files:
  - `.claude/commands/sprint-deploy-pm.md`
  - `.claude/commands/sprint-validated.md`
  - `.claude/commands/chain-validated.md`
- Companion scripts in `offices/pm/scripts/`
- Mike 2026-05-08 chain-end-merge rule (preserved; this spec implements the original intent more structurally) — `offices/pm/knowledge/feedback_pm_main_merges_at_chain_end_only.md`
- Atlas design-gate (PM Rule 10) — `offices/architect/knowledge/atlas-charter-and-authority.md`
- Backlog v2 spec (directive #3, shipped) — `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md`
- Validation-criteria-upfront spec (directive #2, next) — *to be written; landing as `docs/superpowers/specs/YYYY-MM-DD-validation-criteria-upfront-design.md`*

---

## 12. Open questions deferred to implementation plan

- Whether `pm_status.py` "show both branches" enhancement lands in the same PR as the rule rewrites + skill updates, or as a small follow-up. PM lean: same PR; small surface area.
- Whether `sprint_lint.py` soft branch-check warning lands in the same PR. PM lean: defer; not load-bearing.
- Exact test coverage for `/sprint-deploy-pm` Phase 3.5's new merge step (the script is the slash command body; no Python coverage to add — tested via dry-run on the V0.28.0 sprint 1 actual execution).
