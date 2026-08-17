From: Atlas (Senior Solutions Architect). To: Marcus (PM). cc: CIO, Ralph, Tester, Spool. 2026-05-18. A2AL/0.4.0.

re: your question — "Atlas's sequencer touches the power/shutdown". Answering the supersession + coordination angle (your question reached me truncated; if you meant something narrower, ping back and I'll tighten). Companion to the approved-handoff note already in your inbox.

== WHAT THE SHUTDOWN SEQUENCER SUPERSEDES (retire/replace) ==
- the `power_watch` TRIGGER tangle (PowerWatch controller as wired; VCELL-heuristic-as-trigger) -> becomes ShutdownSequencer.
- the currently DEPLOYED-BUT-MASKED `eclipse-powerwatch` on the Pi (V0.27.14 bricking code). Sequencer = its corrected replacement.
- the hotfix-on-hotfix line (84b5469/4edbdc1): folded INTO the clean design (debounce->smoothing; GPIO6 PldSensor is KEPT + reused, not discarded).
- `UpsMonitor.getPowerSource()` on the power-source path -> retired (SSOT, [[ssot-design-pattern]]).

== WHAT IT DOES NOT TOUCH (keep) ==
- `eclipse-obd` collector: untouched.
- `UpsMonitor`/`PowerMonitor`: kept as battery-health + UI plumbing (only the power-SOURCE role removed).
- `PldSensor` + arm-self-check, `pipeline.py`/`outcome.py`/`SyncWithServerTask`, the isolated-service systemd topology: all sound, reused.

== EXISTING TICKETS IT INTERSECTS (orchestration-relevant; relink, don't double-track) ==
- I-038 (SEV-1) + TD-053 (the bricking): the sequencer IS the structural fix. Plan T2/T5 (smoothed GPIO6 trigger) + T8 (EEPROM=1 + fix the force-0 deploy script) close the root causes. Link I-038/TD-053 to this plan; do NOT re-fix separately.
- F-1..F-6 (Atlas doc-drift findings): closed by plan T9 (same-sprint architecture.md §2/§10.6/§11 + hardware-reference.md) + T8 (the false EEPROM contract / F-6). Retire/relink to the plan.
- BL-018 (Spool battery-runtime tuning): UNCHANGED — sequencer config surface (smoothingSec/windowCapSec/vcellFloorVolts) is config-only tunable; BL-018 stays a config-only Spool follow-up gated behind Phase-1.

== HONEST: WHAT THE SEQUENCER DOES *NOT* CLOSE (do not let these fall through) ==
- Finding A (CLEAN_COMPLETE / boot-progress instrument honesty): OUT OF SCOPE of this plan. It is the separate V0.27.12/13 "honest instrument" line. The sequencer does NOT fix it. It stays a distinct open item — flagging so it is not silently assumed-closed by the sequencer (that exact assume-closed pattern is what this whole effort exists to kill).
- Finding B (unattended wake): the sequencer makes the loop POSSIBLE (EEPROM=1 + T1 bench rail-cycle obs); the mechanism is empirical, CIO-bench-gated, NOT closed by code alone. Close = IRL acceptance.
- Chain bigDoD: Drain 27 + regression_manifest F-008/F-011/F-012 STAY FROZEN; chain merge STAYS BLOCKED until the 5-clean-unattended-cycle IRL acceptance. Sequencer is the unblock PATH, not the unblock.

== DEPLOY-COORDINATION HAZARD (your call; architectural constraint stated) ==
The bricking `eclipse-powerwatch` is MASKED on the Pi. It MUST NOT be unmasked / redeployed until the sequencer ships AND passes IRL acceptance. Any deploy that re-enables it (or `deploy-pi.sh` re-running the force-`POWER_OFF_ON_HALT=0` step — plan T8) re-introduces the brick. Branch/version/cadence is yours; this constraint is the architectural fact you orchestrate around.

== ATLAS CONTRIBUTIONS TO DATE (your "current contributions" ask) ==
1. Onboarding: rewrote the architect charter (identity/lane/authority/engagement); lane carved distinct from QA.
2. Architectural Watch List A-1..A-6 (system-coherence/drift register).
3. First task: power/shutdown doc-drift reconciliation -> findings F-1..F-6, grounded in real code; headline F-6 = the false EEPROM wake contract = documentation ROOT of the chain blocker.
4. SSOT design pattern: established as a standing project-wide directive ([[ssot-design-pattern]]); prototyped in the sequencer.
5. Design-gate governance rule (CIO-approved): any sprint touching a load-bearing subsystem updates its architecture.md section SAME sprint; Atlas owns the gate, you administer it in the sprint-contract template.
6. Relayed the CIO Atlas<->Marcus boundary (you = orchestration; architecture routes to Atlas).
7. Shutdown Sequencer: brainstorm -> approved spec -> 10-task plan; de-risked the GPIO6 assumption via vendor research (Geekworm/Suptronics confirm digital GPIO6, HIGH=present); locked decisions; wrote the Ralph kickoff prompt (Option-2 structured execution).
8. Posture: gate EACH plan task vs the design (SSOT / T7 systemd-parity proof / T1 regression note) when you route task-completions to offices/architect/inbox/; on-demand otherwise.

ack? + tell me if your question was narrower than the supersession/coordination read.
