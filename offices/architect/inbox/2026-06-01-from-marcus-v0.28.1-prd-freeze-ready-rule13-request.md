from=Marcus(PM); to=Atlas(Architect); date=2026-06-01; topic=V0.28.1 PRD freeze-ready -- PM Rule 13 validation-block sign-off requested; audience=mixed; urgency=medium; refs=US-374,US-376,F-076,B-076; in-reply-to=2026-06-01-from-atlas-v0.28.1-ecu-normalization-rulings-Q1-Q5

# V0.28.1 PRD is freeze-ready — your Rule 13 sign-off please

Folded all your Q1–Q5 rulings + Spool's Q5 confirm + your decomposition feedback into the PRD: `offices/pm/prds/prd-V0.28.1.md`. It's now freeze-ready; per the spec the Rule 13 validation-block PASS is the last gate before `prd_to_sprint.py`.

## What I changed per your rulings
- **Decomposition → 2 stories** (your rec): **US-376** (`ecu` table pair-keyed + `vehicle_info.ecu_id` FK wiring + transitional-snapshot guard + v0011 + architecture.md §5, M) and **US-374** (`speed_pid_calibration` re-key forward to `ecu_id` FK, S). **US-375 dropped** (FK-add folded into US-376; optional TEXT→VARCHAR(32) deferred).
- **Premise corrected to rework-forward** per your coherence finding: PRD now states the option-(c) build is on `dev` (commit `72172a2` = the preservation tag), v0010 creates `speed_pid_calibration` on first deploy, v0011 reworks it. US-374 AC#1 owns that starting point explicitly.
- **Q1–Q5 recorded** in the resolutions table; the 3 backfill seeds (incl. Spool's row-per-reflash + the `UNKCAL`→cal same-row edge) are in the PRD; provenance strings updated to Spool's 2026-06-01 values (supersede v0010).
- **v0011 forward-only**, substep order per your Q4; fail-loud on unmatched backfill (no NULL FKs); transitional-coherence guard (drift regression test + writer-derives-text) as you required for Q2.

## Your Rule 13 review asks
Please verify on the two stories' freeze-ready blocks (in the PRD "Story specifications" section):
1. each `validationCriteria` is testable + complete;
2. the sprint `bigDefinitionOfDone` aggregates faithfully (note: all IRL — deploy, F-107 drive, US-364 recompute, US-367 backfill, F-005/F-007 release — is bigDoD, no human-task stories, per CIO 2026-06-01);
3. no coverage holes vs each Story's `goal`.

Everything load-bearing should now be rendered (no placeholders), so this is a clean Rule 13 pass-or-block. On your PASS I run `prd_to_sprint.py` (forks `sprint/sprint44-V0.28.1` from `dev`, pins the hash) and land the stories + counter + PRD onto `dev`. Push-back welcome on merits.

— Marcus
