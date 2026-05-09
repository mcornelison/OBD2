---
name: sprint-validated
description: "Sprint-validated ritual for Marcus (PM) -- runs AFTER real-hardware drill passes the sprint's bigDefinitionOfDone. Merges sprint branch to main + bumps regression_manifest.json features that were re-validated. Per Mike 2026-05-08 directive: main = fully validated stable. Run when CIO confirms drill green."
---

# Sprint Validated (PM-driven, post-Mike-2026-05-08-workflow)

End-of-validation ritual for Marcus (PM). Companion to `/sprint-deploy-pm`. Per Mike 2026-05-08 standing rule: sprint branches deployed-but-pre-merge until real-hardware drill passes; this command performs the merge.

**WHEN to run**: after a real-hardware drill (Drive N, Drain Test N, etc.) successfully exercises the sprint's `validation.bigDefinitionOfDone` clauses AND CIO confirms green light.

**WHEN NOT to run**: drill failed (fix on sprint branch + bump V0.X.(Y+1) + re-deploy + re-attempt validation); drill not yet attempted; sprint not in DEPLOYED-AWAITING-VALIDATION state.

**Output of this command**: main branch carries sprint work + new `chore(release):` commit reflecting validated state. Regression manifest bumps `lastValidated` for features the sprint validated. Sprint N+1 grooming can begin.

---

## Phase 0 -- Pre-flight gates

```bash
git status --short                           # working tree clean
git branch --show-current                    # SHOULD be the sprint branch (currently deployed-awaiting-validation)
                                             # If on main: abort -- sprint-validated runs FROM sprint branch
python -c "
import json
d = json.load(open('offices/ralph/sprint.json', encoding='utf-8'))
v = d.get('validation', {})
if not v:
    raise SystemExit('ERROR: sprint.json has no validation block (Sprint 27+ required field)')
if v.get('validatedAt'):
    raise SystemExit(f'ERROR: sprint already marked validated at {v[\"validatedAt\"]}; double-run?')
print(f'Sprint awaiting validation as of currentVersion={v.get(\"currentVersion\")}')
print(f'bigDefinitionOfDone clauses: {len(v.get(\"bigDefinitionOfDone\", []))}')
print(f'validatesFeatures: {v.get(\"validatesFeatures\", [])}')
"
```

**Stop conditions**:
- On `main` branch (run from sprint branch)
- sprint.json `validation` block missing (sprint pre-2026-05-08-workflow; needs migration)
- sprint.json `validation.validatedAt` already set (double-run detection)
- Working tree dirty (commit / stash drift first)

---

## Phase 1 -- Confirm validation evidence

Print the sprint's `bigDefinitionOfDone` clauses. **CIO confirms each was observed** (Mike's 2026-05-08 rule: evidence is helpful but not required; Mike looks for proof himself).

If running interactively, prompt for confirmation. If running via slash command in Claude session, take CIO's prior message as the green light.

```bash
python -c "
import json
v = json.load(open('offices/ralph/sprint.json', encoding='utf-8'))['validation']
print('=== bigDefinitionOfDone (Mike confirmed observed?) ===')
for i, clause in enumerate(v['bigDefinitionOfDone'], 1):
    print(f'  [{i}] {clause}')
"
```

**Optional**: query journalctl / DB tables for evidence the validation events fired (e.g., new drive_summary row, new STAGE_* power_log rows, new connection_log auto_update_applied event). If automation can prove the clauses, log the evidence to validation field.

---

## Phase 2 -- Update sprint.json validation block

```python
# Mark validated:
import json
from datetime import datetime, timezone
p = 'offices/ralph/sprint.json'
d = json.load(open(p, encoding='utf-8'))
d['validation']['validatedAt'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
d['validation']['validatedBy'] = "Mike (CIO confirmed) + drill: <Drive N / Drain Test N>"
with open(p, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
    f.write('\n')
```

---

## Phase 3 -- Update regression_manifest.json

For each feature in sprint's `validation.validatesFeatures`, bump `lastValidated` + `validatedBy`:

```python
import json
from datetime import date

sprintP = 'offices/ralph/sprint.json'
manifestP = 'offices/pm/regression_manifest.json'

sprintData = json.load(open(sprintP, encoding='utf-8'))
manifest = json.load(open(manifestP, encoding='utf-8'))

today = date.today().isoformat()
validatedFeatures = sprintData['validation']['validatesFeatures']
validationLabel = sprintData['validation']['validatedBy']  # e.g. "Drive 6 + Drain Test 11"
sprintNum = int(sprintData['sprint'].split('--')[0].strip().split()[-1])  # extract "27" from "Sprint 27 -- ..."

bumped = []
for feat in manifest['features']:
    if feat['id'] in validatedFeatures:
        feat['lastValidated'] = today
        feat['validatedBy'] = validationLabel
        bumped.append(feat['id'])

manifest['lastUpdated'] = today
manifest['lastUpdatedBy'] = f"Marcus (PM, Sprint {sprintNum} validated)"

with open(manifestP, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write('\n')

print(f'Bumped lastValidated for {len(bumped)} features: {bumped}')
```

---

## Phase 4 -- Update PM artifacts

### 4a -- backlog.json B-XXX phase: `awaiting-validation` -> `complete`

```python
# Find the active phase under the sprint's backlogItem reference
# Bump status: awaiting-validation -> complete
# Set validatedAt date
```

### 4b -- MEMORY.md

Update Current State: "Sprint X SHIPPED + VALIDATED + MERGED to main; V0.X.Y on main; <validatedBy>".

### 4c -- projectManager.md

Last Updated header + Current Phase: "Sprint X validated by <drill>; merged to main; ready for Sprint X+1 grooming."

---

## Phase 5 -- Commit validation marker on sprint branch

```bash
git add offices/ralph/sprint.json offices/pm/regression_manifest.json offices/pm/backlog.json offices/pm/projectManager.md
git commit -m "chore(validate): Sprint N validated by <drill> -- ready to merge"
git push origin sprint/sprintN-<phase-name>
```

---

## Phase 6 -- Merge sprint branch to main

```bash
git checkout main
git pull origin main          # confirm main at expected base
git merge --no-ff sprint/sprintN-<phase-name> -m "Merge sprint/sprintN-<phase-name>: Sprint N VALIDATED V0.X.Y -- merged to main as fully validated stable"
git push origin main
git log --oneline -3 main     # confirm merge landed
```

**Stop condition**: if `git pull` fast-forwards beyond expected base, the world has moved (CIO landed a hotfix on main). Investigate before merge.

---

## Phase 7 -- Optional: tag git history

```bash
git tag -a v0.X.Y -m "Sprint N validated stable -- <drill summary>"
git push origin v0.X.Y
```

Useful for rollback reference + release-notes generation.

---

## Phase 8 -- Final summary

Print to CIO:

| Step | Result |
|---|---|
| Sprint X SHIPPED + VALIDATED | N/N stories validated by <drill> |
| validatesFeatures bumped in manifest | F-XXX, F-YYY, ... (N features re-validated) |
| Merge to main | `<merge-hash>` |
| RELEASE_VERSION on main | V0.X.Y |
| Tag pushed | v0.X.Y (optional) |
| **Status** | **VALIDATED + MERGED to main = stable** |

Plus regression manifest status:

```bash
python offices/pm/scripts/pm_regression_status.py --stale
```

Show what's still STALE / NEVER-validated -> next sprint candidates.

---

## Stop-condition flowchart

| Phase | Stop condition | Action |
|---|---|---|
| 0 | On main branch | Abort; run from sprint branch |
| 0 | sprint.json missing validation block | Migrate (Sprint 28+ requires it) |
| 0 | validatedAt already set | Double-run detection; abort |
| 0 | Working tree dirty | Commit/stash first |
| 1 | CIO has not confirmed drill green | Don't run; wait for Mike's go |
| 6 | git pull fast-forwards beyond base | CIO landed hotfix; investigate |

---

## Why this exists

Per Mike 2026-05-08: main = "fully validated stable." Sprint deployment + sprint validation are now decoupled. `/sprint-deploy-pm` ships code to deploy targets; `/sprint-validated` certifies the code works in real life and merges. The two-step gate prevents the Sprint 22 hidden-bug-pattern, the Sprint 25 sibling-bug pattern, and the never-validated-in-real-life class of features (F-009 through F-014 currently).

## Related

- `/sprint-deploy-pm` -- ships code to deploy targets; pre-cursor to this command.
- `pm_regression_status.py` -- reports which features are STALE/NEVER-validated.
- `regression_manifest.json` -- the project's user-facing feature list.
- `feedback_pm_semver_convention.md` -- patch-version-on-sprint-branch rule.
- `feedback_pm_python_for_deterministic_work.md` -- helper extraction rule (Phase 2 + Phase 3 candidates for next-pass extraction).
