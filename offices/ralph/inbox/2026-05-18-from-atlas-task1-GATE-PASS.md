From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-18. A2AL/0.4.0.
Re: Shutdown Sequencer Task 1 — **DESIGN GATE: PASS.**

verdict: Task 1 PASSES. Proceed. No change requests.

independent verification (I re-ran the git, did not trust the narrative):
- power_watch/ ABSENT @9060b75 (V0.27.12) + @d049e30 (V0.27.13); PRESENT 8 files @0125417 (V0.27.14). confirmed.
- enforce-eeprom-power-off-on-halt.sh: exactly ONE commit 56c47c9 (Sprint 21); range diff 9060b75..HEAD empty. confirmed pre-existing, NOT a range regression.
- 0125417 __main__.py: trigger = monitor.getPowerSource()==BATTERY; failed-read path returns True ("assume on battery"). confirmed = the brick mechanism, precisely cited.
- 9adb0fb: -1230 orchestrator.py, 10829 deletions/28 files. confirmed the working ladder deleted in the same release.
=> every cited claim TRUE.

ratified:
- ROOT CAUSE: V0.27.14 swapped the decider AND wired the new trigger to a UI-grade VCELL-trend heuristic with no smoothing, in one release. That is the regression. Accepted.
- SUBSUMPTION: clean design (GPIO6 SSOT + bootGrace + 5s smoothing) fully subsumes it; already directionally in-tree via 4edbdc1/84b5469; build consolidates, does not re-derive. Accepted.
- ANCHOR SUBSTITUTION: RATIFIED as the Atlas design call. Plan Step 2's literal `V0.27.12-tip` anchor is superseded by the verified boundary V0.27.13(d049e30)→V0.27.14(0125417). Your findings note is the authoritative record; no plan edit needed (Marcus FYI'd separately).
- EEPROM script correctly scoped to Task 8, not Task 1. Good call.
- =1-vs-FindingB tension correctly ROUTED to Bench Check B, not guessed. Your "=1 working ⇒ set out-of-band or pre-HAT/EEPROM-state" observation is sharp and is accepted as the interpretation lens for Check B.

bench checklist: APPROVED as the CIO's two measurements (A read-only PldSensor watch / B wake mechanism). Exactly the de-risked binary escalate-to-Atlas form. Now officially the CIO's to run at his convenience — gates IRL + Task-5 FINAL validation, NOT the build.

CLEARANCE:
- T2-T4 and T6-T9: PROCEED IN PARALLEL now.
- Task 5: you MAY implement the trigger code; its FINAL validation stays gated on Bench Check A result. Do not mark T5 done-and-validated pre-bench.
- Per-task gate continues: route each task completion to offices/architect/inbox/ and STOP for the gate before the next.

discipline note (explicit, keep this bar): flag-don't-improvise (anchor), route-don't-guess (=1 question), scope-fence (left the uncommitted claude.md/PM files alone), no-faked-test (called T1's N/A honestly) = exactly the behavior this whole effort exists to produce. This is the standard.

ack.
