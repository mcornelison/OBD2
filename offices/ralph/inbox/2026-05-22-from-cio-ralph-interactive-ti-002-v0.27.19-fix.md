from=CIO; to=Rex(Dev); date=2026-05-22; topic=V0.27.19 interactive fix -- TI-002 chain_validate_aggregate.py double-count; audience=agent; urgency=high

Rex -- one focused fix needed before /chain-validated can fire. This is a PM tooling script bug; small surface; interactive (not autonomous ralph.sh).

# Scope

**TI-002 fix**: `offices/pm/scripts/chain_validate_aggregate.py` double-counts sprints that have multiple archive snapshots in `offices/ralph/archive/sprint.archive.*.json`.

# Context

The script aggregates sprint.json validation blocks for /chain-validated pre-flight. It globs `offices/ralph/archive/sprint.archive.*.json` PLUS the current `offices/ralph/sprint.json`. Some sprints have multiple archives (e.g., Sprint 41 has `sprint.archive.2026-05-22_015122Z.json` AND `sprint.archive.2026-05-22_140602Z.json` from the V0.27.17 + V0.27.18 deploy cycle). Each archive that matches `currentVersion.startswith(chainPrefix)` joins the `inChain` list -- so the same sprint's `bigDefinitionOfDone` clauses and `validatesFeatures` get aggregated multiple times. `chainStatus` math + the human report are both affected.

Argus filed this 2026-05-11 at `offices/tester/gaps/2026-05-11-chain-validate-aggregate-double-count.md`. **READ THAT FILE FIRST** for her exact reproduction + expected output. Her gap entry is the authoritative bug description; my framing above is PM's guess at the failure shape.

# Branch + version

- Branch: spin **`sprint/sprint42-v0.27.19-ti-002`** from `sprint/sprint41-bugfixes-V0.27.17` tip (currently `fc6c15a` or later -- pull origin first to be safe).
- Version: V0.27.18 → **V0.27.19** patch bump.
- Sprint contract: minimal `sprint.json` with one story **US-358** (PM will provide the contract template). For this interactive session, focus on the fix + tests; PM handles sprint.json + RELEASE_VERSION bump + commits.

# Story scope (US-358)

- **Read**: `offices/tester/gaps/2026-05-11-chain-validate-aggregate-double-count.md` (Argus's gap entry; bug description)
- **Read**: `offices/pm/scripts/chain_validate_aggregate.py` (the script to fix)
- **Fix**: dedupe sprints by `currentVersion` (or by `sprintTitle` -- your call which is the right key) so each sprint is represented once in `aggregateChain`. The most-recent archive per `currentVersion` should win (the validatedAt + validatedBy in the latest snapshot are authoritative). Older snapshots of the same sprint discarded.
- **Tests**: add `tests/pm/scripts/test_chain_validate_aggregate.py` (or wherever PM scripts have test cohabitation) covering:
  - Single archive per sprint: no change in output (regression gate for existing behavior)
  - Multiple archives for same sprint: only the latest archive's data shows in `inChain` + `aggregateBigDoD` + `aggregateValidatesFeatures`
  - Mixed: 3 sprints, 2 have duplicate archives + 1 has single -- output shows 3 sprints, not 5
  - `chainStatus` calculation is correct under dedupe
- **Run**: full test suite + lint (`make pre-commit` or equivalent); 0 errors required.
- **Commit**: single commit on `sprint/sprint42-v0.27.19-ti-002` branch with message:
  ```
  fix(pm-tooling): US-358 dedupe sprint archives in chain_validate_aggregate.py (TI-002)

  Closes Argus's 2026-05-11 gap report. Multiple sprint.archive.*.json files
  with same currentVersion no longer double-count in chain aggregation.

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

# Side context (FYI, not load-bearing)

- V0.27.18 deployed clean 2026-05-22 morning; Argus IRL drill PASS 6/6 + Atlas independent re-verify; her /sprint-validated done (commit 153b43a)
- Drive 23/24 dual-attribution surfaced from your V0.27.18 drill data -- defect locus in your US-351 revert chain (DriveDetector/lifecycle); CIO-ratified disposition = V0.28.0 top priority (B-107 just filed), NOT this sprint
- CIO swapped ECUs mid-session post-drill PASS; new modified-EPROM ECU; drives 25+ on new ECU; SPEED PID reads 2x on new ECU (V0.28 grooming territory)
- TI-002 is the last blocker between V0.27.18 and /chain-validated merge of V0.27.1..V0.27.19 to main per Mike chain-end-merge rule

Ping me (CIO) when fix lands + tests green; PM handles the rest.

-- CIO
