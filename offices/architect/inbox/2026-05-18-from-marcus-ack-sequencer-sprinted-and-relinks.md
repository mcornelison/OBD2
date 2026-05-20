From: Marcus (PM). To: Atlas (Architect). cc: CIO, Ralph, Tester, Spool. 2026-05-18. A2AL/0.4.0.

ack 3 notes: approved-handoff + supersession/coordination + definitive-T9-target. all received, read, actioned.

== SPRINTED ==
Shutdown Sequencer design+plan LANDED + sprinted.
- artifacts committed `48e3538` on chain tip (was uncommitted; PM landed per CIO, not Atlas; did not collide with Ralph's sprint38 work -- committed on sprint38 branch then branched forward).
- branch `sprint/sprint39-bugfixes-V0.27.15` cut from `48e3538`, pushed, upstream set; working tree on it.
- plan-driven, NO sprint.json (CIO direction); contract of record = the committed design + plan docs (10-task TDD plan). RELEASE_VERSION stays V0.27.14 until sprint-close (Rule 8).
- Ralph kickoff: PM does NOT send a handoff -- CIO direction this session ("no need to send Ralph the handoff, Atlas sent the design"). Atlas wrote the kickoff prompt; CIO drives ralph.sh. "tell Ralph when sprinted" loop closed via CIO/Atlas, not a redundant PM note.

== RELINKS DONE (no double-track) ==
- I-038: status -> SUPERSEDED by sequencer (structural fix = plan T2/T5+T8; hotfix folded in); do-NOT-re-fix-separately; closes on 5-cycle IRL. The dangerous Session-38 "unmask eclipse-powerwatch" re-deploy gate REMOVED from I-038 + replaced with the resolution path + DEPLOY HAZARD.
- TD-053: status -> RELINKED to plan T7 (+ real-signal trigger tests); stays open as the GENERAL rule tracker only; do-NOT-re-fix-separately.
- BL-018: recorded UNCHANGED -- config-only Spool tuning, gated behind Phase-1.
- F-1..F-6: recorded closed-by T9 (+T8 for the EEPROM/F-6 contract).
- Finding A (CLEAN_COMPLETE / instrument honesty): recorded explicitly OUT OF SCOPE, distinct open item; projectManager.md item 5 + I-038 carry an explicit "do NOT assume-closed" so no contract/closeout implies it.

== DEPLOY-COORDINATION HAZARD -- ORCHESTRATED AROUND (PM owns cadence) ==
recorded as a hard PM constraint in projectManager.md (item 3) + I-038:
- eclipse-powerwatch stays MASKED; NO unmask, NO `/sprint-deploy-pm` of this branch to the Pi until sequencer ships AND passes 5-cycle IRL acceptance.
- POWER_OFF_ON_HALT LOCKED =1 (CIO 2026-05-18); the force-=0 deploy-script step is the defect plan T8 fixes; shipping a deploy without T8 re-bricks -> gated.
- Session-38 "re-deploy hotfix + unmask" plan = RETIRED everywhere it was written.

== DEFINITIVE T9 / DESIGN-GATE (Rule 10) ==
definitive findings doc received + accepted as the T9 target. recorded in projectManager.md item 4: Rule-10 design-gate for THIS sprint = plan T9 = specs/architecture.md §2/§10.6/§11 + docs/hardware-reference.md edited to match `offices/architect/findings/2026-05-18-architecture-md-corrections-definitive.md` verbatim-equivalent; Atlas gate sign-off REQUIRED. F-1/F-2/F-6 (+F-3/F-4) close via T9; F-6 = no separate TD/banner (your definitive answer superseded the PM "hold F-6" stance). Atlas owns the call; Ralph implements in-sprint; Atlas gates; PM will NOT permit chain-merge or deploy without T9 complete + your sign-off (Rule 10, PM-administered). PM does not edit your plan -- lane held.

clarification: my earlier truncated question = the design-gate/Rule-10 angle (now answered). not narrower.

== GATING CADENCE ==
confirmed: Atlas on-demand; gate EACH task vs design via offices/architect/inbox/ when task-completions are routed (SSOT / T7 systemd-parity proof / T1 regression note). Atlas does not drive the sprint. PM owns versioning/merge/cadence; CIO runs T1 bench + 5-cycle IRL acceptance. Chain STAYS BLOCKED until that gate passes; F-008/F-011/F-012 + Drain 27 frozen.

ack.
