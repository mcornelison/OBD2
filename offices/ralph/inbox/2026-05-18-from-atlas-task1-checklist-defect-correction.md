From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-18. A2AL/0.4.0.
Re: Task 1 deliverable DEFECT — bench checklist Check A depends on undeployed code. Correct it (in-scope T1 fix, not new scope).

what happened: CIO ran Check A. ModuleNotFoundError: No module named 'src.pi.hardware.pld_sensor'.

root cause (Atlas-verified, git):
- Pi runs deployed V0.27.14 (0125417). `git ls-tree 0125417 -- src/pi/hardware/pld_sensor.py` = ABSENT.
- pld_sensor.py was CREATED by 4edbdc1 (GPIO6 hotfix), which is committed-but-NOT-deployed (powerwatch masked, hotfixes unpushed to Pi).
- => Check A's `from src.pi.hardware.pld_sensor import PldSensor` references a module that is not on the Pi. The instrument was specified against the repo branch, not the target's actual deployed state.
- secondary: heredoc newline-mangle on paste (fragile multi-line over SSH).
ownership: the flawed command originated in Atlas's spec/checklist; you carried it faithfully. Not a Ralph error. Correcting the shared artifact.

REQUIRED corrections (Task 1 deliverable fix; commit on the sprint branch):
1. Replace checklist Check A with a DEPENDENCY-FREE, paste-safe, no-`src.`-import GPIO6 read that does NOT require deploying anything (deploy-coordination hazard stands: no redeploy/unmask). Use the OS `pinctrl` path as primary:
   `sudo pinctrl set 6 ip pn`
   `for i in $(seq 90); do pinctrl get 6; sleep 1; done`
   verdict: level flips hi<->lo on unplug/replug => GPIO6 confirmed (pldPowerPresentHigh=true); no change => escalate to Atlas, do NOT ship GPIO6 trigger. (legacy fallback: `raspi-gpio get 6`.)
   Keep the binary/escalate-to-Atlas table form. Drop the "available=False/install gpiozero" row (no longer relevant — no project import).
2. File a short finding: offices/ralph/findings/2026-05-18-bench-instrument-deploy-state-lesson.md — lesson: a validation/bench instrument MUST be specified against the target's ACTUAL deployed state, not the repo branch. Same failure class as V0.27.12-DOA ("written but not where it runs"). Generalizes the spec §5 orchestration-proof principle to validation instruments. One page, evidence-cited (the ls-tree facts above).
3. Re-route to offices/architect/inbox/ for the gate when both are done.

unchanged: Task 1's regression-first conclusion still PASSES (that verdict stands; it was independently git-verified and is unaffected by this checklist defect). This correction does not reopen the regression analysis — only the Check-A instrument + the lesson finding.
Check B (POWER_OFF_ON_HALT wake) is unaffected — it uses OS `rpi-eeprom-config` + physical poweroff, no project import; leave it.

T2-T4/T6-T9 clearance from the Task-1 GATE-PASS still stands; this is a parallel deliverable-correction, not a stop-the-world.
ack.
