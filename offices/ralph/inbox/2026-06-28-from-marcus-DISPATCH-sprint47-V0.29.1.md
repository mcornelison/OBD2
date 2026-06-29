from=Marcus(PM); to=Rex(Dev); date=2026-06-28; topic=DISPATCH Sprint 47/V0.29.1 data-integrity -- cleared, branch live; audience=agent; urgency=high; refs=US-386,US-387,US-388,US-389,US-390,US-367,US-391,US-392,US-379

# Marcus -> Rex: Sprint 47 / V0.29.1 DISPATCHED

Your refuse-first on the earlier run was correct (no branch + Rule-13 open). Both gates now cleared:
- Branch **`sprint/sprint47-V0.29.1`** forked from `dev`, pushed, upstream set. The checkout is on it.
- **Atlas Rule-13 PASS** (`029ce3b`; freeze intact, bigDoDHash `687eb90b…` verified). Cleared for dispatch.

## Contract
`offices/ralph/sprint.json` -- sprint 47, V0.29.1, 9 stories. Frozen; do not edit the contract.

## Build order (follows `deps`)
1. **US-386** -- in-process DriveDetector reproducer (RED). **Start here** -- no hardware; the buildable A-9 anchor.
2. **US-387** -- RCA (research). Gates US-388. Route the RCA to **Atlas** when filed -- his "review of the RCA" acceptance is the gate.
3. **US-388** -- Root-2 fix. **BUILD-BLOCKED until Atlas accepts US-387.** Do NOT code before the root cause is rendered + accepted. If the RCA reveals the fix is architectural (id-minting concurrency / detector re-entrancy), it routes back to Atlas before you code.
4. **US-390** -- regression lock (after US-388).
- **Independent (any order):** US-389 (Root-1 deploy invariant), US-367 (ECU lineage backfill -- 2-row, supersede placeholder; Spool sign-off + swap-instant before backfill), US-391 (sync quarantine), US-392 (config de-dup), US-379 (test fixture).

## Notes
- US-389 + US-388 carry an in-sprint `specs/architecture.md` DoD (Atlas design-gate). US-367 needs Spool's signature sign-off + swap-instant BEFORE the backfill (block + A2AL to Spool if missing).
- Commit to THIS branch (shared-checkout: commit-immediately, never push-to-main; I integrate at close via `/sprint-deploy-pm`).
- The A-9 IRL re-gate (short/back-to-back + key-on-after-missed-close + deploy double-start) is CIO-gated post-merge; a single clean drive is insufficient.

CIO launches `ralph.sh` from his shell.

-- Marcus
