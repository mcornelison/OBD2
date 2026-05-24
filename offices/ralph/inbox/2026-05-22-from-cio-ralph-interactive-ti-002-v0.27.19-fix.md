from=CIO; to=Rex(Dev); date=2026-05-23; topic=V0.27.19 interactive fix -- TI-002 chain_validate_aggregate.py double-count + chain-tip-validation-authoritative semantic; audience=agent; urgency=high

Rex -- one focused fix needed before /chain-validated can fire. This is a PM tooling script bug; small surface; interactive (not autonomous ralph.sh).

# Scope (expanded 2026-05-23 per CIO ratification of path B)

**Two fixes in one story (US-358)**:

1. **TI-002 dedupe**: `offices/pm/scripts/chain_validate_aggregate.py` double-counts sprints that have multiple archive snapshots in `offices/ralph/archive/sprint.archive.*.json` (e.g., Sprint 41 archived once at V0.27.17 deploy + again at V0.27.18 deploy + the live sprint.json -- all currentVersion=V0.27.18 → triple-counted).

2. **Chain-tip-validation-authoritative semantic**: per CIO chain-end-merge rule, the chain-tip sprint's `validatedAt` is authoritative for the whole chain. Today the aggregator marks every earlier patch (V0.27.2..V0.27.17) as `unvalidatedSprints` because none had `/sprint-validated` run individually (they were superseded by successive patches). Under `--strict`, this falsely blocks `/chain-validated`. **Fix**: aggregator should treat the highest-version sprint in the chain as the validation gate; if chain-tip is validated, chainStatus=READY regardless of earlier patches' validation state.

# Context

The script aggregates sprint.json validation blocks for /chain-validated pre-flight. It globs `offices/ralph/archive/sprint.archive.*.json` PLUS the current `offices/ralph/sprint.json`. Some sprints have multiple archives (e.g., Sprint 41 has `sprint.archive.2026-05-22_015122Z.json` AND `sprint.archive.2026-05-22_140602Z.json` from the V0.27.17 + V0.27.18 deploy cycle). Each archive that matches `currentVersion.startswith(chainPrefix)` joins the `inChain` list -- so the same sprint's `bigDefinitionOfDone` clauses and `validatesFeatures` get aggregated multiple times. `chainStatus` math + the human report are both affected.

Argus filed this 2026-05-11 at `offices/tester/gaps/2026-05-11-chain-validate-aggregate-double-count.md`. **READ THAT FILE FIRST** for her exact reproduction + expected output. Her gap entry is the authoritative bug description; my framing above is PM's guess at the failure shape.

# Branch + version

- Branch: spin **`sprint/sprint42-v0.27.19-ti-002`** from `sprint/sprint41-bugfixes-V0.27.17` tip (currently `fc6c15a` or later -- pull origin first to be safe).
- Version: V0.27.18 → **V0.27.19** patch bump.
- Sprint contract: minimal `sprint.json` with one story **US-358** (PM will provide the contract template). For this interactive session, focus on the fix + tests; PM handles sprint.json + RELEASE_VERSION bump + commits.

# Story scope (US-358)

- **Read**: `offices/tester/gaps/2026-05-11-chain-validate-aggregate-double-count.md` (Argus's gap entry; bug #1 description)
- **Read**: `offices/pm/scripts/chain_validate_aggregate.py` (the script to fix)
- **Fix #1 (dedupe)**: dedupe sprints by `currentVersion` (or by `sprintTitle` -- your call which is the right key) so each sprint is represented once in `aggregateChain`. The most-recent archive per `currentVersion` should win (the validatedAt + validatedBy in the latest snapshot are authoritative). Older snapshots of the same sprint discarded.
- **Fix #2 (chain-tip semantic)**: in `aggregateChain`, after dedup, identify the chain-tip sprint = the one with the highest `currentVersion` (lexicographic sort already gives this; pick `inChain[-1]`). Define `chainStatus = 'READY'` if chain-tip has non-null `validatedAt`, else `'INCOMPLETE'`. Earlier sprints in chain do NOT independently gate chainStatus. The rationale: chain-end-merge rule means the chain validates as a whole at the tip; earlier patches were superseded by successive ones and are not re-validated individually. Earlier-sprint `validatedAt=null` is normal under this workflow.
- **Optional refinement**: keep the existing `unvalidatedSprints` list in the output (informational; the human report should distinguish "chain-tip status" from "all sprints individually validated"). Add a note in the human report that earlier-sprint NULL is expected under chain-end-merge semantics. **Don't gate on it under --strict**.
- **Tests**: add `tests/pm/scripts/test_chain_validate_aggregate.py` (or wherever PM scripts have test cohabitation) covering:
  - Single archive per sprint, chain-tip validated → READY
  - Multiple archives for same sprint, chain-tip validated → READY (dedupe + tip semantic both exercised)
  - Single archive per sprint, chain-tip NOT validated → INCOMPLETE (tip-gate works)
  - Single archive per sprint, chain-tip validated but earlier sprint not validated → READY (NEW BEHAVIOR; the earlier-sprint NULL no longer blocks)
  - Mixed: 3 sprints, 2 with duplicate archives + 1 single, chain-tip validated → output shows 3 sprints (dedupe works) + READY (tip-gate)
  - Empty chain (no sprints match prefix) → INCOMPLETE
- **Run**: full test suite + lint (`make pre-commit` or equivalent); 0 errors required.
- **Commit**: single commit on `sprint/sprint42-v0.27.19-ti-002` branch with message:
  ```
  fix(pm-tooling): US-358 chain_validate_aggregate.py -- dedupe sprint archives + chain-tip-validation-authoritative semantic (TI-002 + chain-end-merge alignment)

  Closes Argus's 2026-05-11 gap report (TI-002 double-count). ALSO aligns
  aggregator semantics with CIO chain-end-merge rule: chain-tip sprint's
  validatedAt is authoritative for the whole chain; earlier patches'
  null validatedAt does not block --strict gate.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```

# What PM handles after you commit

- sprint.json US-358 scope + final feedback section
- RELEASE_VERSION V0.27.18 → V0.27.19 bump commit
- story_counter advance 358 → 359
- /chain-validated dispatch

# Out of scope

- No production code changes (Pi or server)
- No deploy needed (PM tooling only)
- No regression manifest changes
- No specs/architecture.md amendment (this is tooling, not a load-bearing subsystem)

# Why expanded scope (2026-05-23 addendum)

PM ran the aggregator pre-flight + discovered V0.27.2..V0.27.17 all show as `unvalidatedSprints` because /sprint-validated was never run individually for each patch (each was superseded by the next; only V0.27.18 has Argus's validation stamp). Three paths considered:
- (a) Retroactive /sprint-validated on every V0.27.X -- heavy + dishonest for sprints that FAILED IRL (V0.27.7/16/17)
- (b) Fix aggregator to honor chain-end-merge semantic (chain-tip is authoritative) -- PRAGMATIC + aligns with how chain has actually been validated
- (c) Add "supersededBy" field to each archived sprint.json -- schema change + audit trail of supersession

CIO ratified (b) 2026-05-23: "it is working good enough; let's not chase a ghost; let's get V0.27.19 in and validated then on to V0.28.X." This story is the (b) implementation.

# Side context (FYI, not load-bearing)

- V0.27.18 deployed clean 2026-05-22 morning; Argus IRL drill PASS 6/6 + Atlas independent re-verify; her /sprint-validated done (commit 153b43a)
- Drive 23/24 dual-attribution surfaced from your V0.27.18 drill data -- defect locus in your US-351 revert chain (DriveDetector/lifecycle); CIO-ratified disposition = V0.28.0 top priority (B-107 just filed), NOT this sprint
- CIO swapped ECUs mid-session post-drill PASS; new modified-EPROM ECU; drives 25+ on new ECU; SPEED PID reads 2x on new ECU (V0.28 grooming territory)
- TI-002 is the last blocker between V0.27.18 and /chain-validated merge of V0.27.1..V0.27.19 to main per Mike chain-end-merge rule

Ping me (CIO) when fix lands + tests green; PM handles the rest.

-- CIO
