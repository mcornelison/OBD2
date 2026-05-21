# Chain Re-Blocked — Hold /sprint-validated for Sprint 39

**From**: Marcus (PM)
**To**: Tester
**Date**: 2026-05-20 (evening)

---

## TL;DR

The V0.27 chain-unblock-candidate verdict from this morning is reversed. Atlas + CIO live in-car drill this evening surfaced two structural findings. **Do NOT run `/sprint-validated` for Sprint 39 / V0.27.15.** Do NOT bump `regression_manifest.json` F-008/F-011/F-012. Wait for V0.27.16.

## What happened

- **F-7 (CRITICAL, chain-blocking)**: ShutdownSequencer state-machine bug in `src/pi/power/power_watch/__main__.py:301-322`. Boot-grace-ignored loss events latch the polling loop blind. Reproduced on demand in Atlas's Test 2 (engine crank within boot-grace + no alternator recovery before key-off → sequencer silent 5.5 min). Detail: `offices/architect/findings/2026-05-20-shutdown-sequencer-boot-grace-latch-bug.md` + `offices/pm/blockers/BL-019.md`.
- **F-8 (HIGH, parallel; not chain-blocking)**: `boot-progress-finalize.service` ExecStop never fires during shutdown (missing `Conflicts=shutdown.target`). Every clean shutdown classified `crashed_during_operation`. This is the root cause of what was tracked as "Finding A / CLEAN_COMPLETE instrument honesty" since V0.27.13. Detail: `offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md` + `offices/pm/issues/I-039-boot-progress-finalize-execstop-never-fires.md`.

## What this changes for Tester

- Sprint 39 / V0.27.15 IRL ACCEPTANCE PASS verdict (Atlas 3-of-3 Cycle-A) **stands on externally-observable facts** — the architectural fix Atlas signed off on remains validated for what it was scoped to validate.
- BUT chain-merge candidacy is HELD pending V0.27.16 fix + in-car re-validation (Sprint 40 / V0.27.16 spun on `sprint/sprint40-bugfixes-V0.27.16`).
- **Sprint 40 contract**: 4 stories US-344..US-347 (T1 F-7 fix + T2 F-8 fix + T3 architecture.md §10.6 amendment + T4 in-car re-validation drill). Atlas pre-registers per-task gates at Ralph dispatch.
- On Sprint 40 / V0.27.16 IRL re-validation pass (Atlas gates T4), you run `/sprint-validated` for Sprint 40 (V0.27.16). PM then runs `/chain-validated` for V0.27.1..V0.27.16.

## Spool's preliminary HOLD on F-008/F-011/F-012 still stands

Per Spool's 2026-05-20 ack to PM (closing the V0.27.x state-reconciliation loop): preliminary read = HOLD F-008/F-011/F-012 bump until ≥1 real drain on a rested ≥8h pack exercises the sequencer end-to-end with sync running. The Sprint 39 Cycle-A passes are architectural validation; the rested-pack drain is the empirical re-validation. Sprint 40 T4 is the architectural fix-validation for F-7 + F-8; the rested-pack drain is the additional empirical gate after T4 passes.

Net: on Sprint 40 IRL pass + rested-pack drain on V0.27.16, F-008/F-011/F-012 bump is on the table. Until then, freeze.

## What PM does next

- Monitors Sprint 40 progress
- Runs `/sprint-deploy-pm` after Ralph T1+T2 + Atlas gate-pass land (V0.27.16 to Pi + server, stacked on V0.27.15)
- On Atlas T4 pass + Tester `/sprint-validated` + (if Spool's rested-pack drain gate passes) → `/chain-validated` merges V0.27.1..V0.27.16

— Marcus
