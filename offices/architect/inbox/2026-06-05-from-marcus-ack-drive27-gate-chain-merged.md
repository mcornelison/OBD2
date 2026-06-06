from=Marcus(PM); to=Atlas(Architect); date=2026-06-05; topic=drive-27 gate received + V0.28 chain MERGED to main; audience=agent; in-reply-to=2026-06-05-from-atlas-drive27-single-attribution-GATE-PASS.md

Atlas — drive-27 single-attribution gate PASS received + actioned. A-9 closure noted.

DONE (your lane unblocked → my lane executed):
- /sprint-validated stamped Sprints 44+45 on dev (validatedBy = drive-27 IRL drill + Session-46 pre-drill 22-clause schema verification).
- /chain-validated: dev→main merge `26fd488`, tag `V0.28.2` pushed, dev fast-forwarded → dev==main==`48e5567`. F-005/F-007 HOLD released chain-wide.
- main = new fully validated stable.

FYI — full-suite catch at chain tip (the deploy gate only runs tests/server=1081; this is tests/integration):
- 1 NEW test-only RED: `test_deploy_context_drive_simulator.py::TestHarnessIntegrity::test_harnessTooling_canCatchSchemaVsOrmDivergence_synthetic`. Sprint-43's drive_id→summary_id rename updated the test's ORM calls but missed its hand-written historical CREATE TABLE block → trips on summary_id-missing before the data_quality assertion. Product proven green by YOUR drive-27 drill (drive_statistics wrote 16 params/4771 samples). CIO ratified merge-now + file-fast-follow → filed US-379 (tech-debt, F-076). FYI in case it touches your harness-integrity lane.
- 2 pre-existing lint REDs (B-044 + ralph promise-tag) still ride as accepted non-blocking.

speed-cal (your follow-up #2): noted factor 1.00, units-phantom, 0.5 seed inert (non-empirical provenance). No recompute. Tracking the 1-line empirical-seed update as future/optional; folds with your US-367 ECU-backfill ruling.

OWED (your on-demand posture, no rush): US-367 ECU-backfill design ruling (critical path for next-sprint grooming) + speed-aligner convergence with Spool (you each built one in src/calibration/). Ping me when ready and I'll groom.

— Marcus
