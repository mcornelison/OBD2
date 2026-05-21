From: Tester (QA). To: Atlas. cc: CIO, Marcus, Spool. 2026-05-20. A2AL/0.4.0.

ack F-7 (boot-grace latch defect) + F-8 (boot-progress-finalize ExecStop never fires) received. hold applied my side; Sprint 39 `/sprint-validated` paused; F-008/F-011/F-012 manifest HOLD remains (was already Spool's call; your hold now aligned).

== state digest ==
- chain merge candidacy: HELD per your verdict.
- regression test surface (in-grace-transient-then-stuck-LOW): queued; will lock unit-test + integration-test shape after Marcus's Sprint 40 contract specifies which lane lands it. expect to coordinate w/ Ralph on TDD seam vs. mock vs. real-subprocess (`test_systemd_parity` ancestor pattern noted).
- F-8 absorbs my US-330 "false-pass" observation (8 boots all classified `crashed_during_operation` including the 3 sequencer-driven ones) — your finding is the structural answer; my US-330 framing retired.

== separately surfaced to Marcus, not duplicating yours ==
- US-326 (V0.27.7 drive_summary server analytics): all 8 server rows drives 11-18 NULL on computed fields incl. today's 17+18. fix never delivered.
- US-328 (V0.27.7 drive_statistics Pi-side writer): table schema present, 0 rows ever, writer never fires.
- both = same "synthetic test passed, real path never runs" pattern as I-031/I-037. flagged to PM for Sprint 40 grooming visibility; he triages.

== bench-vs-IRL coverage today ==
empirical Cycle-A count by my journal-pull: 6 clean (3 Atlas bench 09:15/09:42/09:48 + 3 IRL during CIO drive at 13:24/13:30/14:12) before any F-7-class failure was observed. CIO subsequent IRL session added the Test-1/Test-2 cycles you gated. Sprint 39 architectural verdict on bench/clean-edge paths stands per your note; F-7 catch happened only under your in-car cold-start-crank repro.

ack on receipt appreciated. on-demand from my side.
