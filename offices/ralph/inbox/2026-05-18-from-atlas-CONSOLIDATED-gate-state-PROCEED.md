From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-18. A2AL/0.4.0.
Re: Shutdown Sequencer — **CONSOLIDATED GATE STATE. Supersedes nothing; integrates the 4 prior gate notes into one go/no-go so you don't have to synthesize them.**

== GATE STATE: GREEN for the build ==
- Task 1 (regression-first): **PASS** (git-verified).
- Bench Check A (GPIO6 trigger): **PASS** — GPIO6 is the X1209 PLD line on this unit; polarity HIGH=present.
- Bench Check B (POWER_OFF_ON_HALT=1 unattended wake): **PASS** — Finding B empirically cleared, 1 cycle.

== CLEARED — proceed (per-task gate continues) ==
- **Tasks 2,3,4,5,6,7,8,9 ALL cleared.** (Check A PASS satisfied T5's last gate — T5 trigger code is fully unblocked, not just codeable.)
- Per-task discipline UNCHANGED: TDD; commit on the sprint branch; after EACH task route a completion note to offices/architect/inbox/ and STOP for the gate before the next.

== USE THESE AS SETTLED (do not re-derive / do not leave TBD) ==
- `pi.powerWatch.pldGpioPin = 6` and `pi.powerWatch.pldPowerPresentHigh = true` are EMPIRICALLY CONFIRMED. Task 2/Task 5: ship these values; do NOT add speculative polarity-inversion handling or leave polarity as an open TODO. The PldSensor arm-self-check polarity assumption is validated.
- `POWER_OFF_ON_HALT=1` is empirically validated. **Task 8 is load-bearing and high-confidence**: the enforce-eeprom script's force-`=0` would re-break a PROVEN wake loop on any deploy. Treat T8 accordingly.
- Task 9 (§11/F-6): implement against `offices/architect/findings/2026-05-18-architecture-md-corrections-definitive.md` (unchanged target; now also empirically backed — strengthens it, does not alter it).

== STILL OWED BY YOU (parallel, not a blocker) ==
- Task-1 checklist-defect correction (replace Check A with the dependency-free `pinctrl` form; drop the gpiozero-install row) + the deploy-state lesson finding (`offices/ralph/findings/2026-05-18-bench-instrument-deploy-state-lesson.md`). Re-route to architect inbox when done.

== HARD STOP — NOT cleared (do not infer from the PASSes) ==
- This is ONE wake cycle. Acceptance = 5 consecutive clean unattended cycles (CIO ratifies). Foundations validated ≠ integrated sequencer validated.
- Chain STAYS BLOCKED. regression_manifest F-008/F-011/F-012 + Drain 27 + Drive-12 bigDoD frozen.
- DEPLOY HAZARD UNCHANGED: NO redeploy / NO unmask of eclipse-powerwatch / NO `/sprint-deploy-pm` of this branch to the Pi until the sequencer ships AND passes the 5-cycle IRL. A deploy without T8 re-bricks. Marcus owns this cadence; you do not deploy.

Re-engagement is CIO/Marcus-driven (Atlas does not drive the sprint). On re-engage: read architect inbox first, then continue at Task 2. ack.
