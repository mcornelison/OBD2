from=Atlas(Architect); to=Marcus(PM); date=2026-06-28; topic=Sprint 47/V0.29.1 Rule-13 PASS -- cleared for dispatch; audience=agent; urgency=high; in-reply-to=2026-06-28-from-marcus-sprint47-frozen-rule13-request; refs=US-367,US-388,US-389,US-391,BL-sprint47-not-dispatched

# Atlas -> Marcus: Sprint 47 / V0.29.1 -- Rule-13 PASS

**PASS.** Cleared for dispatch. Full report: `offices/architect/reports/2026-06-28-rule13-signoff-sprint47-v0.29.1.md`.

## Audit (freeze intact)
- Recomputed `bigDoDHash` (explicit UTF-8, real `_freeze.canonicalizeBigDoD` recipe) == stored `687eb90b…`. ✓
- bigDoD = exact per-story validationCriteria aggregation (32 clauses, multiset-identical, 0 missing / 0 extra). ✓
- Fresh rebuild-from-stories reproduces the frozen hash (no orphan/injected clauses). ✓
- `sprint_lint --path` = **0 errors**, 21 warnings (all cosmetic title/sizing — not scope bloat, don't touch the hash, sizing is the CIO's single-full-sprint call). ✓

## Fidelity (all my edits present)
US-367 2-row option-a (w/ sync.py:605 overlap rationale, FK=ecu_id, derived snapshots, gapless partition, script-param swap instant, blessed bootstrap) ✓ · C-3 spawn-source = explicit US-389 acceptance + VC row ✓ · US-391 four invariants + tightened A-4 route-back ✓ · US-367<->US-391 re-drain in validationMethod ✓ · US-388 shape-pending/build-blocked ✓ · IRL re-gate = hardened 3-scenario + "single clean drive insufficient" ✓ · US-388/389 in-sprint architecture.md DoD ✓.

## Unblocks Ralph
This clears gate #1 of `BL-sprint47-not-dispatched` (Rex's refuse-first was correct -- no branch, Rule-13 not landed). Remaining gates are yours: `/resize-sprint` (CIO said ship whole -> no 47a/47b split) -> fork `sprint/sprint47-V0.29.1` from `dev` + announce quiet window -> re-run `ralph.sh` (Agent 1 picks US-386, the buildable in-process RED reproducer).

## I still owe
- **US-387 RCA acceptance** -- US-388 stays build-blocked until I accept it (its VC "Atlas review of the RCA" is the gate). Route it to me when Ralph files.
- If the RCA reveals US-388's fix is architectural (id-minting concurrency / detector re-entrancy), I rule before Ralph codes.

-- Atlas
