---
name: chain-validated
description: "Chain-validated ritual for Marcus (PM) -- merges dev -> main once the V0.X chain is whole-green IRL. Aggregates per-sprint validation evidence, merges dev to main as new fully validated stable, tags V0.X.N, fast-forwards dev to match main for the next chain. Per spec 2026-05-28 (dev/main workflow): main = fully validated stable; dev = integration branch carrying the active V0.X.Y chain. Companion to /sprint-deploy-pm + /sprint-validated. Run when CIO confirms the WHOLE chain is validated green."
---

# Chain Validated (PM-driven, dev/main workflow per spec 2026-05-28)

End-of-chain ritual for Marcus (PM). The third workflow command in the
deploy/validate/merge family:

| Command | What it does | When |
|---|---|---|
| `/sprint-deploy-pm` | Closes sprint, archives artifacts, pushes branch, deploys Pi + server FROM SPRINT BRANCH | After Ralph finishes a sprint |
| `/sprint-validated` | Marks one sprint validated; bumps manifest for that sprint's `validatesFeatures` | After drill validates that sprint's bigDoD clauses |
| `/chain-validated` | Merges the WHOLE chain (V0.X.2 + V0.X.3 + ... stacked sprint branches) to main + bumps manifest chain-wide + tags new stable | After every sprint in the chain has `/sprint-validated` run + CIO confirms whole chain green |

**WHEN to run**: every sprint in a V0.X chain has `validation.validatedAt`
populated on `dev` (each had its own `/sprint-validated`) AND CIO explicitly
confirms the chain is "fully functional working" + ready to merge to main.

**WHEN NOT to run**:
- Any sprint in the chain still has `validatedAt: null` (chain INCOMPLETE)
- Hardware blocker pending (e.g. B-063 fuse-box gating Drive 11+)
- Working tree dirty / `dev` not pushed to origin
- Not on `dev` branch (this command runs from `dev`)

**Output**: `main` receives the dev → main merge (`--no-ff`); new V0.X.N tag
pushed; `dev` fast-forwards to match `main` so the next V0.(X+1).0 chain starts
from a clean dev = main state. Regression manifest already carries per-sprint
bumps (done by `/sprint-validated` runs on dev); chain-wide bump runs as a
safety net for any HELD bumps released at chain time. Intermediate sprint
branches preserved on origin (or archived per CIO call).

---

## Phase 0 -- Pre-flight gates

```bash
# Working tree clean (chain merge touches git history; no surprises)
git status --short

# MUST be on dev
git branch --show-current

# dev pushed to origin (no local-only commits)
git log --oneline @{u}..HEAD
```

**Stop conditions**:
- Not on `dev`
- Working tree dirty
- Unpushed commits on `dev` (chain merge against origin only -- `git push origin dev` first)

```bash
# Confirm the chain-end-merge rule is the right ritual for this state
python offices/pm/scripts/pm_regression_status.py --stale
```

If many features still STALE / NEVER -- chain probably isn't ready;
investigate before continuing.

---

## Phase 1 -- Aggregate chain status

Enumerate the chain (auto-discover: archived sprint.json + current sprint.json
filtered by `validation.currentVersion` prefix). Print sprints in chain + per-sprint
validation state + aggregated validatesFeatures + chain-wide bigDoD checklist.

```bash
# Replace V0.27 with the chain epoch being merged
python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27
```

**Stop conditions**:
- Sprints in chain = 0 -> wrong --chain prefix; abort
- chainStatus = INCOMPLETE -> at least one sprint lacks `validatedAt`;
  run `/sprint-validated` on that sprint first

---

## Phase 2 -- Confirm chain-tip "fully functional working"

CIO confirms each aggregated bigDoD clause was observed (Mike's 2026-05-08 rule:
evidence is helpful but not required; Mike looks for proof himself).

If running in a Claude session: take CIO's prior "merge chain to main" message
as the green light. If running interactively: prompt for confirmation.

```bash
# Strict gate -- exit 1 if any sprint lacks validatedAt
python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27 --strict
```

**Stop conditions**: strict exit 1 -> abort; sprint(s) still need
`/sprint-validated`.

Optional verification (kick off full fast suite on chain tip):

```bash
pytest tests/ -m "not slow" -q
```

---

## Phase 3 -- Update regression manifest chain-wide

For the aggregated validatesFeatures union, bump lastValidated to today + stamp
validatedBy with the chain-merge label.

```bash
# Capture aggregated feature IDs from Phase 1's JSON output
python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27 --json \
    > /tmp/chain-agg.json
python -c "import json; print(' '.join(json.load(open('/tmp/chain-agg.json'))['aggregateValidatesFeatures']))"
# Example output: F-005 F-007

# Bump those features chain-wide
python offices/pm/scripts/chain_validate_manifest_bump.py \
    --features F-005 F-007 \
    --label "by chain merge V0.27.5" \
    --date $(date -u +%Y-%m-%d)
```

Verify the manifest now shows all chain-touched features OK:

```bash
python offices/pm/scripts/pm_regression_status.py
```

---

## Phase 4 -- Merge dev to main

```bash
# Pull main; confirm base hasn't moved unexpectedly
git checkout main
git pull origin main
git log --oneline -5 main

# Merge dev to main (--no-ff preserves the chain-merge commit shape)
git merge --no-ff dev \
    -m "Merge V0.X chain to main: V0.X.N -- new fully validated stable"
git push origin main
git log --oneline -3 main
```

**Stop condition**: `git pull` brings unexpected commits onto main -> CIO ran a
SEV-1 hotfix on main (per spec §8.2); investigate before completing the merge
(dev may also need to absorb the hotfix before this merge).

---

## Phase 5 -- Tag the new stable

```bash
git tag -a V0.X.N -m "V0.X chain validated stable -- whole chain green"
git push origin V0.X.N
```

The tag is a rollback anchor + release-notes reference. V0.X.N = the chain-tip
patch version (last patch sprint validated on dev).

---

## Phase 6 -- Update PM artifacts on main

### 6a -- MEMORY.md

Update Current State to "V0.27 chain merged to main; new stable V0.27.X; next
chain V0.28 grooming begins".

### 6b -- projectManager.md

Last Updated header + Current Phase + Session entry noting the chain merge.

### 6c -- (Optional) Archive intermediate sprint branches

If CIO directs: delete origin sprint branches whose work landed on dev (and
therefore via the chain merge, on main).  Default: preserve them as rollback
references.

```bash
# Only if CIO directs
git push origin --delete sprint/sprint28-...
git push origin --delete sprint/sprint29-...
# etc.
```

Stage + commit + push the PM artifacts on main:

```bash
git add MEMORY.md offices/pm/projectManager.md offices/pm/regression_manifest.json
git commit -m "chore(chain-validated): V0.X chain merged to main -- new stable V0.X.N"
git push origin main
```

---

## Phase 6.5 -- Fast-forward dev to match main (NEW per spec 2026-05-28)

After main carries the chain-merge + tag, sync `dev` to match `main` so the next
V0.(X+1).0 sprint starts from a clean dev = main state.

```bash
git checkout dev
git merge --ff-only main
git push origin dev
```

**Stop condition**: `--ff-only` fails (dev has commits main doesn't have).
Should NEVER happen at this phase -- if it does, a sprint branched and merged
to dev *after* the chain merge started; investigate before continuing.

Verify dev = main:

```bash
git rev-parse dev
git rev-parse main      # MUST match
```

---

## Phase 7 -- Final summary

Print to CIO:

| Step | Result |
|---|---|
| Chain V0.27 aggregate | N sprints in chain (V0.27.2 ... V0.27.X) |
| chainStatus | READY |
| Manifest bumped | F-XXX, F-YYY, ... (N features re-validated chain-wide) |
| Merge to main | `<merge-hash>` |
| Tag pushed | V0.27.X |
| **Status** | **CHAIN MERGED to main = new fully validated stable** |

Plus regression manifest snapshot:

```bash
python offices/pm/scripts/pm_regression_status.py
```

Show what's still STALE / NEVER-validated for the next chain.

---

## Stop-condition flowchart

| Phase | Stop condition | Action |
|---|---|---|
| 0 | Not on `dev` | `git checkout dev`; re-run |
| 0 | Working tree dirty | Commit/stash; re-run |
| 0 | Unpushed commits on `dev` | `git push origin dev`; re-run |
| 1 | `chain_validate_aggregate.py` reports 0 sprints in chain | Wrong `--chain` prefix; abort |
| 2 | `--strict` exits 1 (INCOMPLETE) | Run `/sprint-validated` on missing sprint(s); re-run |
| 4 | `git pull` brings unexpected commits to main | SEV-1 hotfix on main; investigate (dev may need to absorb hotfix first) |
| 6.5 | `git merge --ff-only main` fails | Sprint branched + merged to dev after chain merge started; investigate before continuing |

---

## Why this exists (workflow rationale)

Per CIO 2026-05-10 chain-end-merge rule + CIO 2026-05-23 directive #1 + spec
2026-05-28: main = "fully functional working system" -- structurally untouched
between chain merges. `dev` is the integration branch carrying the active V0.X
chain (V0.X.0 minor sprint + V0.X.1..V0.X.N patch sprints stacked).

The chain pattern (stacked patch sprints) is preserved; only the merge target
moves -- from "chain-tip sprint branch" (prior workflow) to `dev` (this
workflow). `/sprint-validated` stamps each sprint's validation on dev + bumps
the regression manifest. `/chain-validated` consummates the chain merge once
every sprint in the chain has its stamp AND CIO confirms whole-chain green.

After this command runs, Phase 6.5 fast-forwards `dev` to `main` so the next
V0.(X+1).0 chain branches from a clean dev = main base.

---

## Related

- `/sprint-deploy-pm` -- ships code to deploy targets from sprint branch
- `/sprint-validated` -- per-sprint manifest bump + sprint validation stamp
  (NO merge under chain-end-merge rule)
- `chain_validate_aggregate.py` -- Phases 1 + 2 (enumerate + status)
- `chain_validate_manifest_bump.py` -- Phase 3 (manifest bump chain-wide)
- `pm_regression_status.py` -- pre + post status report
- `regression_manifest.json` -- the project's user-facing feature list
- B-067 backlog item (`offices/pm/backlog/B-067-chain-validated-slash-command.md`)
- CIO 2026-05-10 chain-end-merge rule
  (`feedback_pm_main_merges_at_chain_end_only.md`)
