# Chain Merge — BLOCKED on F-7 (Boot-Grace Latch Bug); F-8 Parallel

**From**: Atlas
**To**: Marcus (PM)
**Date**: 2026-05-20
**Priority**: Chain-blocker (F-7) + parallel issue (F-8)
**Tone**: Reversal of this morning's chain-unblock-candidate verdict, with clean evidence

---

## TL;DR

Live in-car drill with CIO this evening produced **two structural findings**, one of
which **reverses the chain-unblock-candidate verdict** I gave this morning.

- **F-7 (CRITICAL, chain-blocking)**: V0.27.15 ShutdownSequencer has a state-machine
  bug in `src/pi/power/power_watch/__main__.py:301-322`. Boot-grace-ignored loss
  events latch the polling loop blind. Reproduced on demand. Fix is small (~10 lines
  Python). See `offices/architect/findings/2026-05-20-shutdown-sequencer-boot-grace-latch-bug.md`.

- **F-8 (HIGH, parallel — not chain-blocking)**: `boot-progress-finalize.service`
  ExecStop never fires during shutdown (systemd unit dependency-graph defect →
  `Conflicts=shutdown.target` missing). Every clean shutdown gets classified as
  `crashed_during_operation`. Fix is one systemd-directive line. See
  `offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md`.

This morning's IRL Cycle-A PASS verdict (3-of-3 clean drills observed by CIO) remains
correct on the externally-observable facts — but the chain-merge candidacy is now
**held pending F-7 fix + in-car re-validation**.

## What changed since this morning's `2026-05-20-from-atlas-sprint39-IRL-passed-chain-unblock-candidate.md`

Spool's Finding C (filed to my inbox this evening) provided post-morning evidence I
hadn't seen: 12 boots today classified `crashed_during_operation`, a 19-min BATTERY_V
trail, zero `power_log` battery transitions. CIO fact-checked Spool's evidence with me
(zero substantive variances). CIO also provided fresh topology info (battery → relay
(NO, switched off 20A Wiper ESS-GLACE fuse tap) → 10A fuse → buck → Pi, and key-off =
buck-off verified just-now) which **ruled out** Spool's hypothesis (b) and pointed at
a software state-machine defect.

Live in-car drill (CIO + Atlas, two tests):
- **Test 1** (control, fresh boot, no in-grace transient): sequencer fires cleanly at
  key-off ✓
- **Test 2** (replicates this afternoon's failure pattern, brief engine crank during
  boot-grace): sequencer logs "ignoring" once, then is **silent for 5.5 min** while
  GPIO6 stays LOW and HAT drains ✗
- **Test 2 phase 2** (CIO accidentally cycled the key fully off after an engine idle):
  HAT had recovered under alternator (GPIO6 went HIGH); subsequent key-off produced a
  fresh HIGH→LOW edge → sequencer fires cleanly ✓

Bug bound: cold-start + in-grace transient + no alternator recovery before key-off.
Once HAT recovers external-power-detection (alternator running ~14V does the job),
sequencer works again.

## What you (PM) need to orchestrate

### Sprint 40 contract (proposal — CIO ratifies)

**Goal**: fix F-7 (chain-blocker) + F-8 (instrument-honesty parallel) + in-car
re-validation of the cold-start-crank-transient pattern. Then re-run `/sprint-deploy-pm`
+ `/sprint-validated` + `/chain-validated`.

**Suggested task spine** (Ralph executes; Atlas gates):
- T1: F-7 fix in `src/pi/power/power_watch/__main__.py` polling loop (level-based
  post-boot-grace check; preserve smoothing path). New unit test: in-grace transient
  followed by level-stuck-LOW post-grace must fire shutdown. Atlas-pre-registered
  criteria.
- T2: F-8 fix in `deploy/boot-progress-finalize.service` (add `Conflicts=shutdown.target`).
  Deploy. Verify on real Pi: clean shutdown → next boot's `startup_log` shows
  `prior_boot_clean=1, last_stage=CLEAN_COMPLETE`.
- T3 (Rule 10 design-gate DoD): same-sprint `specs/architecture.md` §10.6 update
  documenting (a) the boot-grace latch defect and its fix, (b) the level-based
  post-grace semantics, (c) the F-8 unit-file fix. Atlas sign-off required.
- T4: in-car re-validation drill — deliberately reproduce the Test 2 failure
  scenario (engine crank within boot-grace + 3-min wait + key off). Must fire
  sequencer. CIO observes; Atlas gates verdict.

**Bench check + drill cadence**: F-7 fix is bench-testable cleanly (USB-C unplug
within boot-grace produces the same pattern as in-car cranking). F-8 fix is also
bench-testable on first reboot. The in-car drill is the integration gate.

### Lane reminders
- **F-7 + F-8 fixes are load-bearing changes to power_watch and the deploy unit
  files** → both trigger **PM Rule 10 design-gate DoD** (same-sprint `specs/
  architecture.md` update). Atlas BLOCKs the sprint if §10.6 isn't updated in-sprint.
- **Versioning**: F-7 + F-8 land together → suggest V0.27.16. Same major.minor; bug-fix
  bump on a release that's already in the chain-merge candidacy queue.
- **Sprint 39 / V0.27.15 deploy stays in place** — V0.27.16 is a follow-on. The
  chain branches are stacked; V0.27.16 stacks on top of V0.27.15 per the chain-end-
  merge rule (Mike 2026-05-08 / 2026-05-10).

### Files to file under your lane
- Move F-7 → `offices/pm/blockers/BL-XXX-shutdown-sequencer-boot-grace-latch.md`
  (one-line summary pointing at Atlas finding; CIO is ratifier).
- File F-8 → `offices/pm/issues/I-XXX-startup-log-marker-broken.md` (issue, not
  blocker; lane is parallel to the chain merge path).

### What I did NOT touch (lane discipline)
- Did NOT edit `projectManager.md`, MEMORY.md, or any of your sprint/scheduling files.
- Did NOT route to Ralph directly (your lane to dispatch).
- Did NOT bump `regression_manifest.json` (Tester's lane to decide on F-008/F-011/F-012
  re-validation gating). Spool's Finding C preliminary HOLD with Tester stands.

## Evidence bundle

`offices/architect/findings/2026-05-20-evidence/test-1/` and `.../test-2/` contain the
raw live captures (journal, gpio6_raw at 2 Hz, power_log tail). Both findings cite
specific files + line numbers from the captures so the reasoning is reproducible.

## Atlas posture from here

On-demand. The findings are filed; the orchestration is yours. I gate task-completions
when you route them. F-7 + F-8 fix sprint, when you spin it, gets the same per-task
gate treatment as Sprint 39 did (criteria pre-registered, level-based gating, design
defects in my own plans I will own and ratify as Ralph catches them — see Sprint 39
§9 entries for the pattern).

— Atlas
