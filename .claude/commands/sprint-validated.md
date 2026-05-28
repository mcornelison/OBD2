---
name: sprint-validated
description: "Sprint-validated ritual for Marcus (PM) -- stamps per-sprint validation on dev + bumps regression_manifest. Does NOT merge to main -- /chain-validated does that at chain end per spec 2026-05-28. Per CIO 2026-05-23 directive #1: main = fully validated stable; dev = integration branch. Run when CIO confirms the per-sprint drill is green."
---

# Sprint Validated (PM-driven, dev/main workflow per spec 2026-05-28)

Per-sprint validation ritual for Marcus (PM). Companion to `/sprint-deploy-pm` (Phase 3.5 merged sprint → dev; deploy ran from dev). Per spec `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md`: validation drills target `dev`; this command stamps the per-sprint validation block + bumps `regression_manifest` for the sprint's `validatesFeatures`. **It does NOT merge to main.** `/chain-validated` does that at chain end (after every sprint in the V0.X chain has its own `/sprint-validated` stamp AND CIO confirms whole-chain green).

**WHEN to run**: after a real-hardware drill successfully exercises the sprint's `validation.bigDefinitionOfDone` clauses AND CIO confirms green light.

**WHEN NOT to run**: drill failed (a new patch sprint forks from `dev` → fix → re-run `/sprint-deploy-pm` with V0.X.(Y+1) patch bump → retry validation); drill not yet attempted; sprint not in DEPLOYED-AWAITING-VALIDATION state.

**Output of this command**: `dev`'s sprint.json carries `validation.validatedAt` stamp. `regression_manifest.json` bumps `lastValidated` for features the sprint validated. PM artifacts (backlog.json status, MEMORY.md, projectManager.md) reflect the per-sprint stamp. Sprint N+1 grooming can begin (PM judgement -- see spec §8.1).

---

## Phase 0 -- Pre-flight gates

```bash
git status --short                           # working tree clean
git branch --show-current                    # MUST be `dev` (sprint already merged + closed by /sprint-deploy-pm Phase 3.5)
                                             # If on sprint branch: `git checkout dev` first
                                             # If on main: abort -- sprint-validated runs from dev
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
- On `main` branch or any `sprint/*` branch (run from `dev`)
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

## Phase 5 -- Commit validation marker on dev

```bash
git add offices/ralph/sprint.json offices/pm/regression_manifest.json offices/pm/backlog.json offices/pm/projectManager.md
git commit -m "chore(validate): Sprint N validated by <drill> -- ready for chain merge"
git push origin dev
```

---

## Phase 6 -- (RETIRED under dev/main workflow)

Per spec 2026-05-28, the merge to `main` no longer happens at per-sprint validation. The chain merge runs once at chain end via `/chain-validated` after every sprint in the V0.X chain has its own `/sprint-validated` stamp AND CIO confirms whole-chain green. Sprint validation now only stamps the per-sprint records on `dev`.

---

## Phase 7 -- (RETIRED -- tagging moves to /chain-validated)

Tags are cut on `main` at chain merge (`/chain-validated` Phase 5), not per-sprint. The chain tag (V0.X.N) names the last validated patch version in the chain.

---

## Phase 8 -- Final summary

Print to CIO:

| Step | Result |
|---|---|
| Sprint X SHIPPED + VALIDATED on dev | N/N stories validated by <drill> |
| validatesFeatures bumped in manifest | F-XXX, F-YYY, ... (N features re-validated on dev) |
| Commit on dev | `<chore-validate-hash>` |
| dev tip | V0.X.Y |
| **Status** | **VALIDATED on dev -- awaiting chain close** |

Plus regression manifest status:

```bash
python offices/pm/scripts/pm_regression_status.py --stale
```

Show what's still STALE / NEVER-validated -> next sprint candidates.

**Next step**: when the full V0.X.Y chain is whole-green per CIO confirmation, run `/chain-validated` to merge `dev` → `main` + cut V0.X.N tag.

---

## Stop-condition flowchart

| Phase | Stop condition | Action |
|---|---|---|
| 0 | On main or any `sprint/*` branch | Abort; run from `dev` |
| 0 | sprint.json missing validation block | Migrate (Sprint 28+ requires it) |
| 0 | validatedAt already set | Double-run detection; abort |
| 0 | Working tree dirty | Commit/stash first |
| 1 | CIO has not confirmed drill green | Don't run; wait for CIO's go |

---

## Why this exists

Per Mike 2026-05-08: main = "fully validated stable." Sprint deployment + sprint validation are decoupled. Per CIO 2026-05-23 directive #1 + spec 2026-05-28: under dev/main two-tier workflow, this command no longer performs the merge to main. Instead it stamps the per-sprint validation on `dev` (which carries the active V0.X chain). The chain merge to main happens via `/chain-validated` once every sprint in the chain has its own stamp AND CIO confirms whole-chain green. The three-step gate (deploy → per-sprint validate → chain merge) prevents the Sprint 22 hidden-bug-pattern, the Sprint 25 sibling-bug pattern, and the never-validated-in-real-life class of features.

## Related

- `/sprint-deploy-pm` -- ships code to deploy targets; pre-cursor to this command.
- `pm_regression_status.py` -- reports which features are STALE/NEVER-validated.
- `regression_manifest.json` -- the project's user-facing feature list.
- `feedback_pm_semver_convention.md` -- patch-version-on-sprint-branch rule.
- `feedback_pm_python_for_deterministic_work.md` -- helper extraction rule (Phase 2 + Phase 3 candidates for next-pass extraction).
