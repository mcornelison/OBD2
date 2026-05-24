---
name: chain-validated
description: "Chain-validated ritual for Marcus (PM) -- runs AFTER the full V0.X chain (stacked sprint branches) has been validated IRL. Aggregates every sprint's validation block, bumps regression manifest for the chain-wide validatesFeatures union, merges the chain-tip sprint branch to main as the new fully validated stable, and tags. Per CIO 2026-05-10 chain-end-merge rule: main = fully functional working system. Companion to /sprint-deploy-pm + /sprint-validated. Run when CIO confirms the WHOLE chain (V0.X.2 + V0.X.3 + ...) is validated green."
---

# Chain Validated (PM-driven, post-CIO-2026-05-10-chain-end-merge-rule)

End-of-chain ritual for Marcus (PM). The third workflow command in the
deploy/validate/merge family:

| Command | What it does | When |
|---|---|---|
| `/sprint-deploy-pm` | Closes sprint, archives artifacts, pushes branch, deploys Pi + server FROM SPRINT BRANCH | After Ralph finishes a sprint |
| `/sprint-validated` | Marks one sprint validated; bumps manifest for that sprint's `validatesFeatures` | After drill validates that sprint's bigDoD clauses |
| `/chain-validated` | Merges the WHOLE chain (V0.X.2 + V0.X.3 + ... stacked sprint branches) to main + bumps manifest chain-wide + tags new stable | After every sprint in the chain has `/sprint-validated` run + CIO confirms whole chain green |

**WHEN to run**: every sprint in a V0.X chain has `validation.validatedAt`
populated (each had its own `/sprint-validated`) AND CIO explicitly confirms the
chain is "fully functional working" + ready to merge to main as the new stable.

**WHEN NOT to run**:
- Any sprint in the chain still has `validatedAt: null` (chain INCOMPLETE)
- Single-sprint epoch (use `/sprint-validated` instead; no chain to merge)
- Hardware blocker pending (e.g. B-063 fuse-box gating Drive 11+)
- Working tree dirty / branches not pushed to origin

**Output**: main carries the chain-tip work + new `chore(release):` commit
reflecting validated state; new V0.X.Y tag pushed; regression manifest bumped
chain-wide; intermediate sprint branches preserved (or archived per CIO call).

---

## Phase 0 -- Pre-flight gates

```bash
# Working tree clean (chain merge touches git history; no surprises)
git status --short

# Currently on the chain-tip branch (e.g. sprint/sprint31-...)
git branch --show-current

# All chain branches pushed to origin (no local-only commits)
git log --oneline @{u}..HEAD
```

**Stop conditions**:
- Not on the chain-tip sprint branch (e.g. on main)
- Working tree dirty
- Unpushed commits on chain branches (chain merge against origin only)
- Any chain branch missing from origin (run `git push origin <branch>` first)

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

## Phase 4 -- Merge chain to main

```bash
# Pull main; confirm base hasn't moved unexpectedly
git checkout main
git pull origin main
git log --oneline -5 main

# Merge chain tip to main (--no-ff preserves the chain-merge commit shape)
git merge --no-ff <chain-tip-branch> \
    -m "Merge V0.27 chain to main: V0.27.X -- new fully validated stable"
git push origin main
git log --oneline -3 main
```

**Stop condition**: `git pull` brings unexpected commits onto main -> CIO landed
a hotfix; investigate before completing the merge.

---

## Phase 5 -- Tag the new stable

```bash
git tag -a V0.27.X -m "V0.27 chain validated stable -- bug fixes complete"
git push origin V0.27.X
```

The tag is a rollback anchor + release-notes reference.

---

## Phase 6 -- Update PM artifacts on main

### 6a -- MEMORY.md

Update Current State to "V0.27 chain merged to main; new stable V0.27.X; next
chain V0.28 grooming begins".

### 6b -- projectManager.md

Last Updated header + Current Phase + Session entry noting the chain merge.

### 6c -- (Optional) Archive intermediate sprint branches

If CIO directs: delete origin sprint branches whose work landed on main via the
merge.  Default: preserve them as rollback references.

```bash
# Only if CIO directs
git push origin --delete sprint/sprint28-...
git push origin --delete sprint/sprint29-...
# etc.
```

Stage + commit + push the PM artifacts on main:

```bash
git add MEMORY.md offices/pm/projectManager.md offices/pm/regression_manifest.json
git commit -m "chore(chain-validated): V0.27 chain merged to main -- new stable V0.27.X"
git push origin main
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
| 0 | Not on chain-tip branch | Switch to chain-tip; re-run |
| 0 | Working tree dirty | Commit/stash; re-run |
| 0 | Unpushed commits on chain branches | `git push`; re-run |
| 1 | `chain_validate_aggregate.py` reports 0 sprints in chain | Wrong `--chain` prefix; abort |
| 2 | `--strict` exits 1 (INCOMPLETE) | Run `/sprint-validated` on missing sprint(s); re-run |
| 4 | `git pull` brings unexpected commits to main | Hotfix race; investigate |

---

## Why this exists (workflow rationale)

Per CIO 2026-05-10 chain-end-merge rule: main = "fully functional working
system".  When a feature sprint plus its bug-fix follow-ups (V0.X.0, V0.X.1,
V0.X.2, ...) stack on consecutive sprint branches, each branch tip is
DEPLOYED-AWAITING-VALIDATION; merge-to-main is gated on the WHOLE chain
proving green via real-hardware drill.

The previous workflow (`/sprint-validated` does the merge) was per-sprint; the
chain-end-merge rule moved merge to the chain boundary so main never carries a
partially validated chain.  `/sprint-validated` still bumps the per-sprint
manifest entries + marks each sprint validated; `/chain-validated` consummates
the chain merge once every sprint in the chain has its sprint-validated stamp.

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
