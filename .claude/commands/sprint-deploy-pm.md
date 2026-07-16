---
name: sprint-deploy-pm
description: "Sprint-deploy ritual for Marcus (PM). Validates sprint complete; archives sprint.json + progress.txt with timestamp; bumps status fields; merges sprint to dev; bumps RELEASE_VERSION on dev; deploys Pi + server FROM dev. Does NOT merge to main -- /chain-validated does that at chain end. Per CIO 2026-05-23 directive #1 + spec 2026-05-28: main = fully validated stable; dev = integration branch. Run after Ralph finishes a sprint when CIO directs sprint-close + deploy. NEVER run mid-sprint while Ralph is working."
---

# Sprint Deploy (PM-driven, dev/main workflow per spec 2026-05-28)

End-of-sprint deployment ritual for Marcus (PM). **Replaces the prior sprint-branch-deploy pattern.** Per spec `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md`: main = fully validated stable (untouched between chain merges); `dev` = integration branch carrying the active V0.X.Y chain. Sprint branches merge into `dev` on code-complete; deploy + IRL validation target `dev`. `/chain-validated` merges `dev` → `main` at chain end.

**WHEN to run**: CIO explicitly directs sprint-deploy after Ralph finishes a sprint (all stories `passes:true`).

**WHEN NOT to run**: mid-sprint (Ralph still iterating); during a SEV-1 hotfix on `main` (uses separate hotfix path per spec §8.2); when sprint contract has unresolved blockers active.

**Critical workflow rules (spec 2026-05-28; US-471 CI-gate 2026-07-15)**:
- This command integrates sprint → `dev` via a **CI-green PR** (Phase 3.5, Option A) and deploys from `dev`. It does NOT merge to `main`.
- The sprint branch merges into `dev` **only when the migration-drift CI check is green for the exact HEAD SHA** (run-not-trust), or the PR touches no migration-relevant path (vacuous pass). Never a silent direct-merge fallback.
- After deploy, the sprint enters "awaiting validation" state on dev. CIO + drill runner exercise sprint.json `validation.bigDefinitionOfDone` IRL.
- `/sprint-validated` then stamps the sprint validation (no further merge).
- `/chain-validated` merges `dev` → `main` once the whole V0.X chain is whole-green.
- If a drill reveals a regression: a NEW patch sprint forks from `dev` → fix → re-run this command with V0.X.(Y+1) patch bump. Loop until validated.

---

## Phase 0 -- Pre-flight gates (HALT-EARLY)

```bash
git status --short                                   # working tree clean except known noise
git branch --show-current                            # MUST be the sprint/* branch (off dev)
git fetch origin dev                                 # refresh dev ref
test "$(git merge-base HEAD origin/dev)" = "$(git rev-parse origin/dev)" \
  || echo "WARN: sprint branched off stale dev tip"
python offices/pm/scripts/pm_status.py | head -25    # confirm stories all passes:true
python offices/pm/scripts/sprint_lint.py             # MUST be 0 errors
python offices/pm/scripts/repair_ralph_agents.py --check   # ralph_agents.json valid
```

**Stop conditions** -- abort + report to CIO if:
- Branch is `main` or `dev` (sprint-deploy runs FROM a `sprint/*` branch)
- Sprint branched off stale `dev` tip (merge-base ≠ current `dev` HEAD; ask CIO whether to rebase the sprint branch onto current dev or merge through with awareness)
- Any story has `passes: false` AND `status: pending` (sprint not actually done)
- `sprint_lint.py` shows errors (US-274 phantom-path / US-282 commit-vs-claim drift / missing `validation` block per Sprint 28+ requirement)
- `ralph_agents.json` is corrupt (run `repair_ralph_agents.py` first)

---

## Phase 1 -- Status field hygiene

```bash
python offices/pm/scripts/bump_passed_statuses.py
python offices/pm/scripts/sprint_lint.py    # re-verify 0 errors
```

---

## Phase 2 -- Archive sprint.json + progress.txt

```bash
python offices/pm/scripts/archive_sprint_artifacts.py
```

Stop condition: exit 2 means timestamp collision (re-run within 1 sec); abort + investigate.

---

## Phase 3 -- Update PM artifacts

### 3a -- `offices/pm/backlog.json`

Bump the active B-XXX phase entry to `awaiting-validation` (NEW status; was `in_progress` -> `complete` under prior workflow). Add `currentVersion` field tracking the version on disk.

```json
"engine-on-critical-path": {
  "status": "awaiting-validation",        // NEW status; bumps to "complete" only on /sprint-validated
  "sprint": "Sprint 27",
  "branch": "sprint/sprint27-engine-on-fixes",
  "createdDate": "2026-05-08",
  "currentVersion": "V0.27.0",            // bumps to V0.27.1+ on each deploy iteration
  "validatedAt": null,
  ...
}
```

### 3b -- `MEMORY.md`

Update Current State to "Sprint X DEPLOYED V0.X.Y -- AWAITING VALIDATION (real-hardware drill pending)".

### 3c -- `offices/pm/projectManager.md`

Last Updated header + Current Phase descriptor. Insert Session narrative.

---

## Phase 3.5 -- Integrate sprint branch into dev via a CI-green PR (US-471, Option A)

**Why a PR, not a direct merge (US-471 / BL-022):** the real-MariaDB migration-drift check (`migration-drift.yml`, US-470) only runs on `pull_request → dev`. A direct `git merge` bypasses it, so deploy-from-`dev` would see no CI signal -- the exact gap that let BL-019/020/021 reach the deploy attempt. Opening a PR runs the check pre-merge; gating the merge on green makes deploy-from-`dev` **CI-green by construction**. CI scope = **migration-touching changes only** (path-filtered; CIO 2026-07-15) -- a PR that touches no migration path legitimately does not trigger the job (handled as a vacuous pass below).

### 3.5a -- Commit + push the sprint branch

Stage all relevant files on the sprint branch BEFORE integrating, so the sprint-close commit body carries the PM artifacts (sprint-close exception to PM Rule 8 dev-only-domain):

```bash
git add -A -- offices/ src/ tests/ scripts/ deploy/ specs/
git reset HEAD -- offices/pm/.claude/ offices/ralph/.claude/ offices/tuner/.claude/   # drop drift
git commit -m "feat(sprint-N): <Sprint Name> SHIPPED N/N -- code-complete on sprint branch"
git push origin sprint/sprintN-<phase-name>
```

### 3.5b -- Open the PR into dev

```bash
SPRINT_BRANCH="sprint/sprintN-<phase-name>"
gh pr create --base dev --head "$SPRINT_BRANCH" \
  --title "Merge $SPRINT_BRANCH: <Sprint Name> code-complete N/N (V0.X.Y)" \
  --body "Sprint-deploy integration PR (US-471 CI-green gate). Migration-drift CI gates the merge."
PR=$(gh pr view "$SPRINT_BRANCH" --json number --jq .number)
```

### 3.5c -- CI-green gate (run-not-trust; US-469 principle)

Determine whether this sprint touched any **migration-relevant path** (the `migration-drift.yml` `paths:` filter). Only then is the check required:

```bash
HEAD_SHA=$(git rev-parse HEAD)
MIG_PATHS='^(src/server/migrations/|scripts/apply_server_migrations\.py|tests/server/_mariadb_chain_harness\.py|tests/server/test_migration_chain_real_mariadb\.py|requirements\.txt|requirements-server\.txt|requirements-dev\.txt|\.github/workflows/migration-drift\.yml)'
if git diff --name-only origin/dev...HEAD | grep -Eq "$MIG_PATHS"; then
  echo "Migration-relevant paths touched -> migration-drift CI is REQUIRED."
  gh pr checks "$PR" --watch --fail-fast          # blocks until checks settle; non-zero on failure
  # run-not-trust: assert a SUCCESS run exists for THIS exact SHA (never assume green)
  gh run list --workflow=migration-drift.yml --branch="$SPRINT_BRANCH" \
    --json headSha,conclusion \
    --jq 'map(select(.headSha=="'"$HEAD_SHA"'" and .conclusion=="success")) | length' \
    | grep -qx '0' && { echo "HALT: no SUCCESS migration-drift run for $HEAD_SHA"; exit 1; }
  echo "CI green for $HEAD_SHA."
else
  echo "No migration-relevant paths touched -> migration-drift job does not run (vacuous pass, no migration risk)."
fi
```

**Stop condition (HALT, do NOT merge/deploy):**
- `gh pr checks --watch` exits non-zero (a required check failed/errored) -> fix on the sprint branch, push, re-run 3.5c.
- The run-not-trust assertion finds **no SUCCESS run for the HEAD SHA** (check ran on a different SHA, or never ran when it should have) -> investigate; never merge on assumed-green.
- `gh` auth / PR creation fails -> **HALT and surface**; do NOT fall back to a silent direct `git merge` (that reintroduces the gap). The documented manual fallback is the **DSN-manual gate** (run the live layer on demand against a real MariaDB 11.x): `OBD2_MARIADB_TEST_DSN=mysql+pymysql://user:pass@host:3306/db pytest tests/server/test_migration_chain_real_mariadb.py -m integration`.

### 3.5d -- Merge the PR into dev

```bash
gh pr merge "$PR" --merge      # merge commit (preserves --no-ff semantics); keep the branch (short-lived; other agents may hold it locally)
git checkout dev && git pull origin dev              # bring the merge commit local; refresh base
```

**Stop condition**: `git pull` brings unexpected commits onto `dev` (parallel sprint / hotfix). Investigate before continuing.

**Note**: the PR merge commit IS the sprint-deploy record now. Do NOT merge to `main` here -- that's `/chain-validated`'s job at chain end.

---

## Phase 4 -- (RETIRED under dev/main workflow)

Phase 3.5 above absorbs the sprint-deploy commit semantics via the merge to `dev`. PM artifact commits (sprint.json, projectManager.md, MEMORY.md) ride on the sprint branch up to the merge.

---

## Phase 5 -- RELEASE_VERSION bump on dev

```bash
# Now on dev (Phase 3.5 left us here).
# Edit deploy/RELEASE_VERSION:
# - First sprint of a chain: V0.(X+1).0 (minor bump from main's last-validated version)
# - Patch sprint within current chain: V0.X.(Y+1) (patch bump from prior dev tip)

python offices/pm/scripts/verify_release_version.py    # validates SemVer + theme<=50 + description<=400
git add deploy/RELEASE_VERSION
git commit -m "chore(release): bump V0.X.Y -> V0.(X+1).0 (Sprint N on dev)"   # or V0.X.(Y+1) for patch
git push origin dev
```

Stop condition: `verify_release_version.py` exits 1 -> trim oversize field, re-run, then commit.

---

## Phase 6 -- Deploy Pi + server FROM dev

```bash
# Still on dev. Deploy scripts read HEAD of current branch.
bash deploy/deploy-pi.sh        # Pi pulls latest from origin/dev
bash deploy/deploy-server.sh
```

Server deploy is unattended via `/etc/sudoers.d/obd2-deploy` (Sprint 22 fix). Wait for both completions.

---

## Phase 7 -- Verify both targets running new version

```bash
ssh mcornelison@10.27.27.28 "cat /home/mcornelison/Projects/Eclipse-01/.deploy-version"
ssh mcornelison@chi-srv-01 "cat /mnt/projects/O/OBD2v2/.deploy-version && systemctl is-active obd-server.service"
```

Both should show new V0.X.Y + new gitHash (matching `git rev-parse dev`) + service active.

Stop condition: either target shows old version -> deploy hidden-bug pattern; investigate before reporting deployed.

---

## Phase 8 -- Final summary + AWAITING VALIDATION message

Print to CIO:

| Step | Result |
|---|---|
| Sprint validation | N/N SHIPPED (US-XXX through US-XXX) |
| sprint_lint | 0 errors |
| Archives written | sprint.archive.YYYY-MM-DD_HHMMSSZ.json + progress.archive |
| Sprint-deploy commit | `<short-hash>` (on sprint branch) |
| RELEASE_VERSION | V0.X.Y -> V0.(X+1).0 (or V0.X.(Y+1) hotfix) |
| Pi deploy | V0.X.Y active on chi-eclipse-01 |
| Server deploy | V0.X.Y active on chi-srv-01 (unattended) |
| **Status** | **DEPLOYED -- AWAITING VALIDATION** |

Plus the sprint's `validation.bigDefinitionOfDone` clauses, formatted as a checklist Mike will work through:

```
Validation pending (per sprint.json bigDefinitionOfDone):
  [ ] Drive 6 IRL: drive_start + realtime_data + drive_summary
  [ ] Sync IRL: chi-srv-01 receives drive data
  [ ] Reconnect IRL: 10s heartbeat + recover within 60s
  [ ] DTC IRL: Mode 03 + Mode 07 + dashboard footer
  [ ] Drain Test 11: STAGE_* rows + battery_health_log columns

Run /sprint-validated when all pass.
If drill reveals regression: fix on sprint branch -> bump V0.X.(Y+1) -> re-run /sprint-deploy-pm.
```

---

## Stop-condition flowchart

| Phase | Stop condition | Action |
|---|---|---|
| 0 | Branch is `main` or `dev` | Abort; sprint-deploy runs FROM a `sprint/*` branch off dev |
| 0 | Sprint branched off stale `dev` tip | Ask CIO whether to rebase onto dev or merge through |
| 0 | Any story `passes:false` + `status:pending` | Abort; sprint not done |
| 0 | `sprint_lint.py` errors | Fix per error; re-run |
| 0 | `--check-feedback` flags missing files | Run rescue-commit pattern; re-run Phase 0 |
| 0 | `ralph_agents.json` invalid | Run `repair_ralph_agents.py`; re-run Phase 0 |
| 2 | Archive timestamp collision | Abort; investigate accidental double-run |
| 3.5b | `gh` auth / PR creation fails | HALT + surface; do NOT silent direct-merge; DSN-manual gate is the fallback |
| 3.5c | Required migration-drift check failed/errored (`gh pr checks` non-zero) | Fix on sprint branch, push, re-run 3.5c |
| 3.5c | No SUCCESS migration-drift run for the HEAD SHA (run-not-trust) | Investigate; never merge on assumed-green |
| 3.5d | `git pull origin dev` brought unexpected commits to dev | Investigate; abort merge |
| 5 | RELEASE_VERSION cap violation | Trim before commit (TD-040 / TD-048 lessons) |
| 7 | Either target shows old version post-deploy | Sprint 22 hidden-bug pattern; investigate before declaring deployed |

---

## Why this exists (workflow change rationale)

Per Mike 2026-05-08: 27 sprints worth of features have been "shipped" via synthetic-test gates but never validated end-to-end IRL. The basic loop ("drive out, log data, return home, sync to server") hasn't been confirmed since Drive 5 (2026-04-29). Some features are NEVER validated in real life (reconnect path, DTC retrieval, self-update, auto-rollback).

Per CIO 2026-05-23 directive #1 + spec 2026-05-28: the V0.27 chain demonstrated that "sprint branches off main" let main carry deployed-but-not-yet-validated state for weeks, despite the 2026-05-08 directive that main = fully validated stable. The dev/main two-tier workflow makes main structurally untouchable mid-chain: `dev` is the integration branch + deploy target; main only receives the dev → main merge at chain end via `/chain-validated`. Main becomes the "validated stable" branch by construction; rollback is always to a known-good state.

## Related

- `/sprint-validated` -- runs after real-hardware drill passes; merges sprint branch to main + updates regression_manifest.
- `pm_regression_status.py` -- reports which features are STALE/NEVER-validated; suggests next drill triggers.
- `regression_manifest.json` -- the project's user-facing feature list with last_validated dates.
- `feedback_pm_semver_convention.md` -- patch-version-on-sprint-branch rule (V0.X.Y -> V0.X.(Y+1) until validated).
- `.github/workflows/migration-drift.yml` -- the real-MariaDB migration-drift CI job (US-470) that Phase 3.5c gates on; scope = migration-touching paths only (CIO 2026-07-15). Enablement + rationale: `offices/pm/decisions/2026-07-13-ci-green-deploy-gate-recommendation.md`.
