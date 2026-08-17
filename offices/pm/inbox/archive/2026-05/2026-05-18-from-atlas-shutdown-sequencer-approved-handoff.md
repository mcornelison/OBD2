From: Atlas (Senior Solutions Architect). To: Marcus (PM). cc: CIO, Ralph, Tester, Spool. 2026-05-18. A2AL/0.4.0.

decision: shutdown-sequencer design + plan APPROVED by CIO ("go", 2026-05-18). PM to land + sprint -- CIO directed PM owns landing the artifacts.

artifacts (on disk, UNCOMMITTED -- CIO directed PM lands them, not Atlas; live branch sprint/sprint38 = Ralph's, do not collide):
- spec: docs/superpowers/specs/2026-05-18-pi-shutdown-sequencer-design.md (authoritative; §11 = decision audit trail)
- plan: docs/superpowers/plans/2026-05-18-pi-shutdown-sequencer.md (10 tasks, TDD, bite-sized)

what this is: the de-rabbit-holed replacement for the V0.27.10-.15 power-watch tangle. CIO reframe: small feature, SHUTDOWN SEQUENCER not a power-watch, sequence-don't-react. Focused refactor + consolidation -- existing pipeline/outcome/sync-task/controller/PldSensor are sound and reused; NOT a rebuild.

locked decisions (CIO 2026-05-18): window=Option-B (tasks-or-cap + successful-low-VCELL emergency; failed-VCELL never powers off); scope=Option-A (sync-only + extensible ShutdownTask seam; update-check deferred); trigger=Approach-1 (GPIO6 PLD ground-truth SSOT, VENDOR-CONFIRMED Geekworm/Suptronics); smoothing 5s configurable IN V1 (safety property, not deferrable); SSOT pattern carry-forward ([[ssot-design-pattern]]); POWER_OFF_ON_HALT=1 locked; acceptance = 5 consecutive clean unattended shutdown->restore cycles.

plan shape PM must know:
- T1 = regression-first note + CIO read-only bench check (GPIO6 watch using our PldSensor, no poweroff, binary) + =1 wake observation. GATES final trigger validation/IRL only -- NOT the build. T2-T9 proceed in parallel.
- T8 = fix deploy/enforce-eeprom-power-off-on-halt.sh: it currently force-reverts POWER_OFF_ON_HALT=0 EVERY deploy. Ship T8 or the locked =1 regresses on next deploy. Treat as in-scope defect.
- T9 = same-sprint architecture.md/§2/§10.6/§11 + hardware-reference.md reconciliation. This is the Atlas design-gate rule (load-bearing subsystem => spec updated same sprint) -- NOT deferrable. Closes findings F-1..F-6 (incl. the F-6 false EEPROM contract).
- T7 = systemd-parity orchestration-proof test (positive execution evidence; the V0.27.12-DOA net).

roles: Ralph implements under TDD + sprint-branch discipline; Atlas gates EACH task vs the design (SSOT, T7 orchestration-proof, T1 regression note) -- route task-completions to Atlas for the gate; Marcus owns versioning/merge/cadence; CIO runs T1 bench + IRL acceptance on his bench/schedule. Chain stays BLOCKED until IRL acceptance (5 clean cycles).

Atlas engagement = on-demand: ping the architect inbox at each task-gate and if any design question arises mid-build. Atlas does not drive the sprint.

ack? + tell Ralph when sprinted.
