# B-067: /chain-validated slash command (V0.27 chain merge to main ritual)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High (P1) -- gates the V0.27 chain merge to main |
| Status       | Pending (V0.27.5+ candidate; build before chain merge) |
| Category     | workflow / pm-tooling  |
| Size         | S-M (PM-side slash command + supporting Python script) |
| Related PRD  | None                   |
| Dependencies | V0.27.X chain ready to merge (i.e., all bugs cleared + B-066 drill green) |
| Created      | 2026-05-10             |

## Description

Per CIO 2026-05-10 chain-end-merge rule: when the V0.27 chain (V0.27.1 + V0.27.2 + V0.27.3 + V0.27.4 + V0.27.X) is fully functional working, it merges to main as the new stable. **Currently, this ritual doesn't have a slash command.** `/sprint-validated` (post-2026-05-10 retired per-sprint merge behavior) bumps the regression manifest + marks individual sprints validated, but does NOT merge.

**Manual merge ritual is error-prone**: 5+ sprint branches to consolidate, RELEASE_VERSION to bump, manifest entries to bump, deploy/.../version stamps to align, regression-status reports to verify. Without a slash command, each chain merge is a one-off.

**B-067 = build the slash command** so the eventual V0.27 chain merge (and future chain merges in V0.28.X / V0.29.X / etc.) is repeatable + safer.

## Acceptance Criteria

- [ ] `.claude/commands/chain-validated.md` slash command file created
- [ ] Phases documented (proposed below)
- [ ] At least one supporting Python script in `offices/pm/scripts/` for the deterministic operations (manifest bumping, RELEASE_VERSION calculation, branch enumeration)
- [ ] Pre-flight gates that catch common-failure-modes (incomplete chain validation, uncommitted state, divergent branches)
- [ ] Smoke-tested against a synthetic chain (e.g., a no-op test branch chain that exercises the merge logic without actually merging)

## Proposed Phases (subject to PM grooming refinement)

```
Phase 0 -- Pre-flight gates
  - All sprint branches in chain are pushed to origin
  - Each sprint has validation block with validatedAt populated
  - Regression manifest shows no STALE features (or fewer than threshold)
  - main is at the chain BASE (last-validated-stable)
  - Working tree clean
  - User explicitly confirms "merge V0.27 chain to main as new stable"

Phase 1 -- Aggregate chain status
  - Enumerate sprint branches in chain: sprint/sprint28-V0.27.2 + sprint/sprint29-V0.27.3 + ...
  - Aggregate validatesFeatures across all chain sprints
  - Print chain-wide bigDoD checklist for CIO confirmation

Phase 2 -- Confirm chain-tip = "fully functional working"
  - Run pm_regression_status.py --json; assert no NEVER-validated features in chain scope
  - Run sprint_lint.py against latest sprint.json (validation block populated)
  - Optional: kick off full fast suite on chain-tip; assert GREEN

Phase 3 -- Update manifest (chain-wide)
  - For each feature in any chain sprint's validatesFeatures: bump lastValidated to chain-merge date
  - Mark "by chain merge V0.27.X" in validatedBy
  - Commit on chain-tip branch

Phase 4 -- Merge chain to main
  - git checkout main
  - git pull origin main (verify base hasn't moved)
  - git merge --no-ff <chain-tip-branch> -m "Merge V0.27 chain: V0.27.X -- new fully validated stable"
  - git push origin main

Phase 5 -- Tag the new stable
  - git tag -a V0.27.X -m "V0.27 chain validated stable -- bug fixes complete"
  - git push origin V0.27.X

Phase 6 -- Update PM artifacts on main
  - MEMORY.md current state -> "V0.27 chain merged to main; new stable V0.27.X"
  - projectManager.md -> session entry
  - Archive intermediate sprint branches (optional; CIO call)

Phase 7 -- Final summary
  - Print chain-merge result to CIO
  - List features bumped + sprint branches consolidated + new main tag
  - Suggest next steps (V0.28.0 feature sprint planning, etc.)
```

## Validation Script Requirements

- **Input**: V0.27 chain in DEPLOYED-AWAITING-VALIDATION state with all sprint validations green + B-066 drill complete
- **Expected Output**: main bumped to V0.27.X; chain branches preserved (or archived per CIO call); regression manifest reflects chain validation
- **Database State**: N/A (workflow / git state only)
- **Test Program**: smoke against synthetic test branch chain that exercises merge logic without affecting real branches

## Why This Story Matters Now

V0.27 chain has at least 3 sprint branches by V0.27.4 (sprint28 + sprint29 + sprint30). B-066 drill adds maybe one more (V0.27.5). When CIO directs chain merge, manual git ritual = 6+ commands + 5+ file edits + risk of divergence between merge state + manifest state.

A slash command:
- Makes the chain-merge ritual repeatable (V0.28 chain in the future; V0.29 chain after)
- Catches pre-flight failure modes BEFORE git history is touched
- Keeps PM artifacts (manifest + MEMORY + projectManager) in lockstep with git state

## Notes

**Naming alternative**: `/release-stable` or `/chain-merge-to-main`. `/chain-validated` reads cleanly + parallels `/sprint-validated` + `/sprint-deploy-pm` family.

**Sprint timing**: file as V0.27.5+ candidate. Build BEFORE V0.27 chain merges to main. Likely ships alongside B-066 drill in the same V0.27.5 sprint -- the drill validates the chain content; the slash command consummates the merge.

**One-time-vs-reusable trade-off**: V0.27 chain is the FIRST chain merge under the new workflow. Building a slash command for a one-time event is potentially over-engineering. BUT: V0.28 chain will follow, V0.29 chain after. Repeatability + safety justify the build.

**Cross-reference Sprint 27 close session note** (2026-05-09 V0.27.1 validate session): "Per Mike 2026-05-08: 27 sprints worth of features have been 'shipped' via synthetic-test gates but never validated end-to-end IRL. Chain-end-merge gates merge on real-hardware drill." -- B-067 is the slash command that consummates that gate.

## Source

- CIO 2026-05-10 chain-end-merge rule (`feedback_pm_main_merges_at_chain_end_only.md`)
- V0.27 chain branch state (sprint28-V0.27.2 + sprint29-V0.27.3 + sprint30-V0.27.4 + V0.27.5 anticipated)
- CIO 2026-05-10 V0.27.4 grooming session question "any gaps you have + want to research?" -> Marcus surfaced this
