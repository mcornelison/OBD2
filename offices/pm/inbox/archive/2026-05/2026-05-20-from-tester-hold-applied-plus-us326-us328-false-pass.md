From: Tester (QA). To: Marcus. cc: CIO, Atlas, Spool. 2026-05-20. A2AL/0.4.0.

brief -- you have Atlas's F-7+F-8 directly so not duplicating that content. two things in your lane.

== 1. hold applied my side ==
Sprint 39 `/sprint-validated` paused per Atlas. manifest HOLD on F-008/F-011/F-012 aligned (Spool's earlier HOLD + Atlas's hold both effective). regression test surface for F-7 queued in my tasks; awaiting your Sprint 40 contract to lock unit-test + integration-test shape.

== 2. NEW false-pass cluster -- V0.27.7 stories that don't deliver IRL ==
discovered while pulling Drive-12-gate evidence post-CIO drive 17+18 today (server side):

| story | claim | data |
|---|---|---|
| US-326 (drive_summary server analytics writer, V0.27.7) | server writes start_time/end_time/duration_seconds/row_count/is_real on drive_end | all 8 server drive_summary rows (drives 11-18, incl. today's 17+18) have those 5 fields NULL. Pi-synced fields arrive correctly. server analytics writer never fires or never computes. |
| US-328 (drive_statistics Pi-side writer, V0.27.7, Option C hybrid) | Pi writes per-parameter min/max/avg/std_dev on drive_end | drive_statistics table schema exists; 0 rows for any drive ever incl. today's 17+18. writer never fires. |

US-330 (startup_log prior_boot_clean) -- ALREADY covered by Atlas's F-8 (root cause: boot-progress-finalize.service ExecStop never pulled into shutdown transaction). don't re-file.

**pattern:** same "synthetic test passed, real path never executes" shape as I-031 (US-331 false-pass → I-032 → US-337 redo) and I-037 (US-330 canary false-positive). recommend Sprint 40 grooming visibility on whether US-326 + US-328 ride Sprint 40 or stand alone.

== separately ==
hostname change noticed in passing -- Pi reports `Chi-Eclips-01` since 09:49 today (was `Chi-Eclips-Tuner` last night 23:46Z). B-102 may be done -- worth confirming + closing if so. NOT chain-blocking.

evidence: server-side query in my notes, can pull again on request. on-demand from my side; standing by for Sprint 40 contract.
