---
name: sprint-deploy-pm
description: "Sprint-deploy ritual for Marcus (PM). Validates sprint complete; archives sprint.json + progress.txt with timestamp; bumps status fields; bumps RELEASE_VERSION; pushes branch; deploys Pi + server FROM SPRINT BRANCH. Does NOT merge to main -- that's /sprint-validated's job after real-hardware drill passes. Per Mike 2026-05-08 directive: main = fully validated stable. Run after Ralph finishes a sprint when CIO directs sprint-close + deploy. NEVER run mid-sprint while Ralph is working."
---

# Sprint Deploy (PM-driven, post-Mike-2026-05-08-workflow)

End-of-sprint deployment ritual for Marcus (PM). **Replaces the prior sprint-close-pm "merge-to-main + deploy" pattern.** Per Mike 2026-05-08 standing rule: main branch reflects "fully validated stable"; sprint branches stay deployed-but-pre-merge until real-hardware drill validates affected features (see `regression_manifest.json` + sprint.json `validation.bigDefinitionOfDone`).

**WHEN to run**: CIO explicitly directs sprint-deploy after Ralph finishes a sprint (all stories `passes:true`).

**WHEN NOT to run**: mid-sprint (Ralph still iterating); during a hotfix that doesn't follow the sprint-branch pattern; when sprint contract has unresolved blockers (BL-XXX active).

**Critical change from prior workflow**: this command DOES NOT merge to main. After deploy, the sprint enters "awaiting validation" state. Mike + Spool perform the real-hardware drill (Drive N, Drain Test N, etc.) defined in sprint.json `validation.bigDefinitionOfDone`. Then `/sprint-validated` performs the merge.

If the drill reveals a regression, fix on sprint branch + bump V0.X.Y -> V0.X.(Y+1) + re-run this command (phases 5-7 only) + retry validation. Loop until validated.

---

## Phase 0 -- Pre-flight gates (HALT-EARLY)

```bash
git status --short                                   # working tree clean except known noise
git branch --show-current                            # MUST be the sprint/* branch
python offices/pm/scripts/pm_status.py | head -25    # confirm stories all passes:true
python offices/pm/scripts/sprint_lint.py             # MUST be 0 errors
python offices/pm/scripts/repair_ralph_agents.py --check   # ralph_agents.json valid
```

**Stop conditions** -- abort + report to CIO if:
- Branch is `main` (sprint-deploy runs FROM sprint branch)
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

## Phase 4 -- Sprint-deploy commit + push branch

Stage all relevant files (sprint-close exception to PM Rule 8 dev-only-domain):

```bash
git add -A -- offices/ src/ tests/ scripts/ deploy/ specs/
git reset HEAD -- offices/pm/.claude/ offices/ralph/.claude/ offices/tuner/.claude/   # drop drift
git commit -m "feat(sprint-N): <Sprint Name> SHIPPED N/N -- DEPLOYED V0.X.Y AWAITING VALIDATION"
git push origin sprint/sprintN-<phase-name>
```

**Note**: do NOT merge to main here. That's `/sprint-validated`'s job.

---

## Phase 5 -- RELEASE_VERSION bump on sprint branch

```bash
# Edit deploy/RELEASE_VERSION:
# - First deploy of sprint: V0.(X+1).0 (minor bump from main's last-validated version)
# - Re-deploy after drill-revealed regression: V0.X.(Y+1) (patch bump)

python offices/pm/scripts/verify_release_version.py    # validates SemVer + theme<=50 + description<=400
git add deploy/RELEASE_VERSION
git commit -m "chore(release): bump V0.X.Y -> V0.(X+1).0 (Sprint N deploy)"   # or V0.X.(Y+1) for hotfix bump
git push origin sprint/sprintN-<phase-name>
```

Stop condition: `verify_release_version.py` exits 1 -> trim oversize field, re-run, then commit.

---

## Phase 6 -- Deploy Pi + server FROM SPRINT BRANCH

```bash
bash deploy/deploy-pi.sh        # Pi pulls latest from origin/sprint-branch (deploy script reads HEAD)
bash deploy/deploy-server.sh
```

Server deploy is unattended via `/etc/sudoers.d/obd2-deploy` (Sprint 22 fix). Wait for both completions.

---

## Phase 7 -- Verify both targets running new version

```bash
ssh mcornelison@10.27.27.28 "cat /home/mcornelison/Projects/Eclipse-01/.deploy-version"
ssh mcornelison@chi-srv-01 "cat /mnt/projects/O/OBD2v2/.deploy-version && systemctl is-active obd-server.service"
```

Both should show new V0.X.Y + new gitHash + service active.

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
| 0 | Branch is main | Abort; sprint-deploy runs FROM sprint branch |
| 0 | Any story `passes:false` + `status:pending` | Abort; sprint not done |
| 0 | `sprint_lint.py` errors | Fix per error; re-run |
| 0 | `--check-feedback` flags missing files | Run rescue-commit pattern; re-run Phase 0 |
| 0 | `ralph_agents.json` invalid | Run `repair_ralph_agents.py`; re-run Phase 0 |
| 2 | Archive timestamp collision | Abort; investigate accidental double-run |
| 5 | RELEASE_VERSION cap violation | Trim before commit (TD-040 / TD-048 lessons) |
| 7 | Either target shows old version post-deploy | Sprint 22 hidden-bug pattern; investigate before declaring deployed |

---

## Why this exists (workflow change rationale)

Per Mike 2026-05-08: 27 sprints worth of features have been "shipped" via synthetic-test gates but never validated end-to-end IRL. The basic loop ("drive out, log data, return home, sync to server") hasn't been confirmed since Drive 5 (2026-04-29). Some features are NEVER validated in real life (reconnect path, DTC retrieval, self-update, auto-rollback).

This workflow gates merge-to-main on the real-hardware drill that exercises the affected features per the sprint's `bigDefinitionOfDone`. Main becomes the "validated stable" branch; rollback is always to a known-good state.

## Related

- `/sprint-validated` -- runs after real-hardware drill passes; merges sprint branch to main + updates regression_manifest.
- `pm_regression_status.py` -- reports which features are STALE/NEVER-validated; suggests next drill triggers.
- `regression_manifest.json` -- the project's user-facing feature list with last_validated dates.
- `feedback_pm_semver_convention.md` -- patch-version-on-sprint-branch rule (V0.X.Y -> V0.X.(Y+1) until validated).
