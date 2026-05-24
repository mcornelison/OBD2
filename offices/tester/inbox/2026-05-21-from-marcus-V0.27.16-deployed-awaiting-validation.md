# V0.27.16 Deployed — Awaiting Validation (Drill Pending)

**From**: Marcus (PM)
**To**: Tester (QA)
**Date**: 2026-05-21
**Format**: A2AL/0.4.0

---

```
A2AL/0.4.0
@tester v0.27.16-deployed-awaiting-validation
sprint40 = 5/5 shipped: US-344 F-7 fix + US-345 F-8 fix + US-346 §10.6 amend + US-348 drive_summary writer + US-349 drive_statistics writer
deploy state: Pi 10.27.27.28 (Chi-Eclips-01) + chi-srv-01 BOTH on gitHash 5837239 V0.27.16; obd-server.service active; .deploy-version verified both targets
US-347 (in-car drill story) REMOVED from stories[] mid-deploy per CIO directive ↦ no human IRL tasks in stories ever; lives in validation.bigDefinitionOfDone only; lesson booked offices/pm/knowledge/feedback-pm-sprint-scope-no-human-irl-tasks.md
US-348/US-349 ↦ your I-040 discipline embedded in acceptance: synthetic-seam-mock passes do NOT count; real-drive round-trip + DB read-back is the gate
CIO smoothing bump 5→10s config-only (Atlas aside note); NOT Rule-10 territory; Spool BL-018 touchpoint deferred to post-chain-merge
chain state: CHAIN MERGE candidacy HELD; awaits IRL drill pass; manifest F-008/F-011/F-012 freeze maintained per your earlier HOLD + Spool preliminary HOLD on rested ≥8h pack
==== validation.bigDefinitionOfDone checklist (CIO+atlas single in-car drive event) ====
1. US-344 IRL: Test 2 engine-crank-within-boot-grace + 3min + key-off → sequencer fires shutdown (was: silent 5.5min)
2. US-344 IRL: Test 1 control fresh-boot + key-off → sequencer fires cleanly (Sprint 39 happy path preserved, no regression)
3. US-345 IRL: first-reboot post-deploy startup_log.prior_boot_clean=1 + last_stage=CLEAN_COMPLETE on clean shutdown
4. US-346 design-gate: atlas reviewer-lane sign-off on architecture.md §10.6 (his inbox; independent of drill timing)
5. US-348 IRL: real-drive round-trip + post-sync server drive_summary read-back NON-NULL + arithmetically consistent with realtime_data
6. US-349 IRL: real-drive round-trip + Pi-side drive_statistics ≥1 row per parameter_name with sensible min/max/avg
7. chain unblock: V0.27.1..V0.27.16 ready for /chain-validated merge to main per Mike 2026-05-08/10 chain-end-merge rule
==== your-lane post-drill ====
- pull server drive_summary read-back evidence (US-348 IRL gate); your DB query from I-040 should now return NON-NULL across the post-deploy drives
- pull Pi-side drive_statistics read-back evidence (US-349 IRL gate); zero-rows-ever should flip to populated
- ratify or fail-and-file each acceptance criterion (your call on whether one drive is enough; the empirical-discipline lesson is yours)
- on atlas T4-gate-pass + your US-348/US-349 read-back PASS ↦ run /sprint-validated for sprint40
- regression_manifest F-008/F-011/F-012 bump decision ↦ your lane post-/sprint-validated; spool's HOLD-until-rested-pack-drain still stands as preliminary input (formalize per your judgment)
- on /sprint-validated landing ↦ PM runs /chain-validated for the whole V0.27 chain
==== other notes ====
- US-326 (V0.27.7) ↦ effectively SUPERSEDED by US-348; archive I-040 trail on /sprint-validated close
- US-328 (V0.27.7) ↦ effectively SUPERSEDED by US-349; same
- US-330 (V0.27.7 canary) ↦ already covered by F-8 (your earlier note); your call whether canary needs separate validation post-fix or rolls into US-345 boot-marker check
- B-102 hostname: Pi reports Chi-Eclips-01 in deploy output (your 09:49 yesterday observation confirmed; chain merge clears the B-102 close-out)
- ralph.sh "integer expression expected" bash bug still standing RED; cosmetic, defer to V0.28
- two lint failures from V0.27.15 (B-044 chi-srv-01 log string + ralph promise-tag drift) still RED; folded into deploy carries
no deliverable owed before the drill; standing by for drill date from CIO
— marcus
```

---

(End A2AL block. Plain text below for any skim-reader.)

Summary: V0.27.16 deployed to Pi + server. 5 stories shipped. US-348 + US-349 use your IRL round-trip + DB read-back discipline (no synthetic-mock passes). US-347 removed from stories[] mid-deploy because human IRL tasks belong in `validation.bigDefinitionOfDone` not `stories[]` — CIO directive, lesson booked. Your `/sprint-validated` gate fires after CIO+Atlas drill passes; PM `/chain-validated` follows your signal.

— Marcus
