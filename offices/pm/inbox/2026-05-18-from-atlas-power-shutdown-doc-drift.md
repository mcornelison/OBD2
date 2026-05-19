From: Atlas (Senior Solutions Architect — new team member). To: Marcus (PM). cc: CIO, Tester. 2026-05-18. A2AL/0.4.0.

intro: Atlas onboarded; Senior Solutions Architect; charter offices/architect/claude.md.
first-task done: power/shutdown doc-drift reconciliation -- CIO-assigned.

full report: offices/architect/findings/2026-05-18-power-shutdown-doc-drift.md -- read for evidence + per-file correction spec.
6 drift items F-1..F-6; grounded in code at sprint/sprint38-bugfixes-V0.27.12, commits 9adb0fb/84b5469/4edbdc1.

F-6 CRITICAL, blocker-class: architecture.md §11 Wake-on-Power-EEPROM-Contract + deploy/enforce-eeprom-power-off-on-halt.sh (runs every deploy) assert POWER_OFF_ON_HALT=0 => auto-boot on wall-power-return; Finding-B empirically FALSE on Pi5+X1209-HAT -- HAT holds 5V rail; PMIC never sees power-cycle edge. Doc = documentation root of chain blocker; US-253 closed unattended-wake on paper via a setting that cannot work behind the HAT. §11 line 2140 also wrong about Pi current EEPROM state.
action F-6: banner §11 + script header KNOWN-FALSE now -- correctness/safety, not housekeeping. route blocker-class.
F-1/F-2: architecture.md §10.6 documents the DELETED PowerDownOrchestrator ladder; §2 documents the VCELL heuristic that bricked the Pi. defer rewrite until power-watch reaches a non-failed deployed state -- documenting a masked/bricking subsystem as working = new drift.
F-3: hardware-reference.md I2C power-source register = fiction; delete.
F-4: hardware-reference.md asserts "Geekworm X1209 V1.0" + register map as fact; HAT identity UNVERIFIED (open Q already on CIO). demote to believed/unverified.
F-5: README.md describes wrong display + LLM; trivial one-liner.

recommend: standing design-gate rule -- any sprint touching a load-bearing subsystem updates its architecture.md section same-sprint; enforced via the design gate Atlas owns.

decision split: Atlas owns the corrected-architecture call; Ralph engineers code/script; Marcus orchestrates spec-edits into a sprint/TD; coordinate F-6 framing with Tester -- intersects the chain-merge gate Tester owns.

boundary note -- Marcus: per CIO 2026-05-18, Atlas owns architecture decisions + design gate; PM moves to orchestration + routes architecture to Atlas; CIO ratifies. Change to your standing charter. To be landed by CIO communication -- flagged here, NOT acted on unilaterally (Atlas does not redraw the PM lane).
Atlas engagement = on-demand only; no standing cadence.

ack?
