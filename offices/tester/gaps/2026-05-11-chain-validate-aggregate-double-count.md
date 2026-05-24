# Gap: `chain_validate_aggregate.py` double-counts the active sprint

**Date**: 2026-05-11
**Component**: `offices/pm/scripts/chain_validate_aggregate.py` (US-318, Sprint 31)
**For**: Developer (Ralph)
**Severity**: Low — transient-state bug; would mislead the `/chain-validated` pre-flight, not corrupt anything.

## Issue

`chain_validate_aggregate.py --chain V0.27` auto-discovers sprint files by globbing `offices/ralph/archive/sprint.archive.*.json` **and** the live `offices/ralph/sprint.json`, then filters by `validation.currentVersion.startswith(chainPrefix)`. When the live `sprint.json` has the same `currentVersion` as a file already in the archive — which is exactly the state right after `/sprint-deploy-pm` archives a sprint and before the next sprint is groomed — the same sprint is counted twice.

## Evidence

Earlier this session, with `sprint.json` still holding Sprint 31 (`currentVersion: V0.27.5`) and `sprint.archive.2026-05-11_120639Z.json` also being Sprint 31:

```
$ python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27
Sprints in chain: 5
  [PENDING] V0.27.2 ... Sprint 28 ...
  [PENDING] V0.27.3 ... Sprint 29 ...
  [PENDING] V0.27.4 ... Sprint 30 ...
  [PENDING] V0.27.5 ... Sprint 31 -- V0.27.5 Chain-merge prep ...
  [PENDING] V0.27.5 ... Sprint 31 -- V0.27.5 Chain-merge prep ...   <-- duplicate
...
unvalidatedSprints: V0.27.2, V0.27.3, V0.27.4, V0.27.5, V0.27.5     <-- duplicate
```

(It self-corrected once the PM groomed Sprint 32 into `sprint.json`, which masked it — but the bug is still there for the next time someone runs the script in the post-deploy / pre-groom window. Per the workflow, `/chain-validated` is *meant* to be run in roughly that window — "Sprint N+1 grooming does NOT begin until Sprint N is merged to main" — so the first real `/chain-validated` invocation is a likely place to hit it.)

## Expected behavior

Each distinct sprint counted once. If the live `sprint.json` is the same sprint as the newest matching archive, prefer one of them (the archive is the canonical post-deploy copy; or dedup by the `sprint` name string / by `(sprint, currentVersion)`).

## Actual behavior

The current sprint appears twice in `sprintsInChain`, `unvalidatedSprints`, and the printed report whenever its `currentVersion` matches an archived sprint's.

## Suggested fix (1 spot, ~3 lines)

In `aggregateChain` (or wherever the file list is assembled), dedup by sprint identity before iterating — e.g. build the list keyed on `d['sprint']` (or `(d['sprint'], d['validation']['currentVersion'])`), last-write-wins, and if you want the archive to win over the live file, sort archives after `sprint.json` in the merge order. Add a test case to `tests/pm_scripts/test_chain_validate_aggregate.py`: a synthetic chain where the live `sprint.json` duplicates the newest archive → assert `len(sprintsInChain)` is N, not N+1.
