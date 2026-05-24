# Finding C — Structural Answer (F-7) + Classifier-Noise Resolution (F-8)

**From**: Atlas
**To**: Spool (Tuning SME)
**Date**: 2026-05-20
**Priority**: Closes your Finding C topology question + de-fangs the "12 boots crashed" inflation

---

## TL;DR

Your Finding C was on the money. Fact-checked your 8 evidence items against Pi
SQLite + server obd2db — **zero substantive variances** (one minor refinement that
strengthened your case rather than weakened it). Then CIO + I did the in-car drill
you implicitly called for. **Two findings result:**

- **F-7** (chain-blocking, structural answer to your Finding C): the V0.27.15
  sequencer's polling loop has an edge-only state-machine defect; a power-loss
  event ignored during boot-grace latches `prevLost=True` and the sequencer goes
  silent permanently for that boot. Your hypothesis (b) (topology — buck stays
  hot) was correctly ruled out by CIO's just-now confirmation that key-off = buck-
  off (verified). Hypothesis adjusted to (b'): the HAT switched to battery
  silently at the crank transient, GPIO6 latched LOW, sequencer's polling logic
  missed all subsequent level-LOW state. Confirmed live in-car.
  → `offices/architect/findings/2026-05-20-shutdown-sequencer-boot-grace-latch-bug.md`
- **F-8** (parallel, instrument honesty): `boot-progress-finalize.service` ExecStop
  never fires during shutdown → every clean shutdown classified
  `crashed_during_operation` in `startup_log`. **This significantly de-fangs your
  "12 boots crashed today" headline** — many of those were clean sequencer
  shutdowns the broken instrument mislabeled. The bricking-loop alarm still
  stands (HAT battery did go dead — F-7 caused it), but the classification
  count itself is partly noise.
  → `offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md`

## The in-car drill (your Cycle-D bench variant offer was on the right track)

Two tests, both in-car under direct CIO observation:

- **Test 1** (control, fresh boot, no in-grace transient): clean sequencer fire at
  key-off, gentle 5s smoothing, poweroff, all dark. Mirrors your hypothesis about
  Bench Check A holding in-car when conditions align.
- **Test 2** (replicates this afternoon's failure pattern): boot, brief engine
  crank within boot-grace, wait 5 min. Journal logs the "ignoring" line; GPIO6
  stays LOW for 5.5 min while HAT drains (3.81V → 3.73V). VCELL trail visible
  via MAX17048 live sampling. Sequencer **silent** the entire time. This is the
  Finding C signature reproduced on demand.
- **Bonus phase**: engine started + idled briefly → HAT recovered, GPIO6 went
  HIGH, VCELL recovered to 4.20V (charging). CIO then accidentally cycled key
  fully off after engine-off → fresh HIGH→LOW edge → sequencer fired cleanly.
  **The HAT does recover under alternator load.** Bug bound is narrow:
  cold-start-crank-during-boot-grace + no alternator recovery before key-off.

## Refinement on your evidence (one of eight)

Item #6 (19-min BATTERY_V flat-12.5V trail): I refined "flat 12.5V" to "starts
12.7V, decays to 12.5V" (real-battery surface-charge fall-off signature). This
**strengthens** your case — a battery with no charging current behaves exactly
like that.

The rest of your evidence (boot lineage, drive 19 clean capture, zero battery
transitions, `wedged_before_poweroff` outlier, etc.) all verified verbatim.

## What this means for BL-018 + your monitoring

- **BL-018 (rested-pack + SyncTask-real-work + chi-srv-01-reachable conditions)**:
  unchanged — still gated behind chain merge. Sprint 40 (F-7 + F-8 fix) is the
  unblock. Then your tuning empiricals can proceed.
- **`startup_log` interpretation going forward**: until F-8 lands, treat
  `prior_boot_reason` as advisory-only. Real classification is the systemd
  journal's shutdown-target sequence. Post-F-8, the count becomes meaningful again.
- **The "12 boots crashed today" framing**: please update your read on this. Your
  observational evidence (BATTERY_V trail, power_log silent, startup_log says
  crashed) is still all real and correctly diagnosed. But the bricking-loop
  scope is *narrower than 12 events* — closer to the actual bricking incidents
  (afternoon's drives 17/18 + the manual power-pull). The morning Cycle-A
  drills were clean shutdowns the instrument misreported.

## What I did NOT touch

- Did NOT edit your sessions.md, knowledge files, drain procedure, tuning specs,
  or BL-018.
- Did NOT modify your Finding C note in my inbox. It stands.
- Did NOT route to Marcus or Ralph for you. PM lane.

## Atlas posture

On-demand. Filed PM + Tester inbox notes alongside this one. Marcus will spin
the F-7 + F-8 fix sprint; Atlas gates per-task; Tester gates regression. When
Tester's `/sprint-validated` clears the new sprint, BL-018 unblocks for you.

— Atlas
