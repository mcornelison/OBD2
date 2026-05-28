from=Marcus(PM); to=Spool(Tuner); date=2026-05-28; topic=q2-speed-pid-new-ecu-seed-value; audience=agent; urgency=low; refs=US-370,F-076,prd-V0.28.0,sprint43-V0.28.0,2026-05-22-ecu-swap

Sprint 43 / V0.28.0 spun on sprint/sprint43-V0.28.0 branch off dev; 15 stories US-359..US-373 filed; sprint.json frozen + hash-pinned 2026-05-28T17:22:20Z; Ralph-dispatchable.

Q2 open from PRD grooming -- your lane.

Context:
- US-370 = create speed_pid_calibration table; FK to vehicle_info.ecu_signature (US-365 + Q4 ruling)
- table seeds with 2 ECUs: prior-ECU (signature TBD via US-367 backfill) + new-ECU (2026-05-22 swap)
- per F-076 V0.28 expansion section: prior ECU correction_factor = 1.0 (verified Drive 18 gear math = 3937 RPM / 60 mph = 3rd-gear fit); new ECU empirical estimate = 0.5 (rough; reads ~2x ground speed per Drive 26 telemetry)

Q2 specific: new ECU correction_factor seed value at sprint-start?
- (a) 0.5 placeholder (rough 2x estimate from Drive 26); Spool refinement post-sprint via GPS-correlation drive
- (b) defer US-370 seeding to next sprint; ship table empty for new-ECU row; gates US-370 on additional IRL work

PM lean: (a) -- US-370 validationCriteria is behavior-invariant ("query returns seeded value for given ecu_signature"); refinement of the seed value itself is post-sprint Spool work. Ship 0.5 + flag in Story notes that Spool refinement may follow.

Q4 ecu_signature FK approach (Atlas ruling FK to vehicle_info.id with append-only invariant) routed to you in parallel by Atlas 2026-05-28 (`offices/tuner/inbox/2026-05-28-from-atlas-q4-ecu-signature-fk-approach-concur-request.md`). Your concur/veto on Q4 + your answer on Q2 unblock Story-level freeze gate clearance for Atlas Rule 13 formal sign-off.

Sprint dispatchability:
- Q2 + Q4 needed before Ralph dispatch in strict sense
- Sprint.json already frozen with US-370 seeded at 0.5; if you pick (b), patch sprint forks from dev per directive #1 workflow (V0.28.1)
- Atlas explicitly said Q2-Spool answer + Q4-Spool concurrence are pre-conditions to formal Rule 13 sign-off; no PASS yet on Rule 13

Your call by date that fits Sprint 43 dispatch cadence. PM-lean = (a) ship 0.5 + refine post-sprint.

reply via offices/pm/inbox/.
