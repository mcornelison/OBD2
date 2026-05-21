# V0.27.16 Deployed — Awaiting Validation (Drill Pending)

**From**: Marcus (PM)
**To**: Spool
**Date**: 2026-05-21

---

## TL;DR

Sprint 40 / V0.27.16 deployed to Pi + server both on gitHash `5837239`. **5 stories shipped** (US-344..US-346 + US-348 + US-349); status: DEPLOYED — AWAITING VALIDATION. Atlas's smoothing bump (5→10s) rides this release and lands in BL-018 territory; the V0.27.7 false-pass cluster you cleared last sprint also gets redone with IRL acceptance discipline.

## What's in V0.27.16

- **US-344 — F-7 fix**: ShutdownSequencer boot-grace latch (Atlas's evening drill found it). `src/pi/power/power_watch/__main__.py` polling loop now does a level-based post-grace check so in-grace transients (engine crank, USB unplug) don't latch the sequencer blind. Smoothing path preserved.
- **US-345 — F-8 fix**: `boot-progress-finalize.service` ExecStop now actually fires during shutdown (`Conflicts=shutdown.target` added). Root cause of "Finding A / CLEAN_COMPLETE instrument honesty" since V0.27.13 — every "clean shutdown" was being recorded as `crashed_during_operation`. Post-fix: first reboot post-deploy should show `startup_log.prior_boot_clean=1 + last_stage=CLEAN_COMPLETE`.
- **US-346 — PM Rule 10 design-gate**: `specs/architecture.md` §10.6 amended to document both fixes (load-bearing power_watch + boot-progress instrument). Atlas reviewer-lane sign-off owed separately.
- **US-348 — V0.27.7 redo (drive_summary)**: server analytics writer now actually fires on Pi-sync drive_end (was: every drive 11-18 had `start_time/end_time/duration_seconds/row_count/is_real` all NULL). IRL round-trip acceptance per Tester I-040.
- **US-349 — V0.27.7 redo (drive_statistics)**: Pi-side writer at `src/pi/obdii/drive_statistics.py` (NEW) now actually fires on drive_end — was: zero rows ever in the table. Computes per-parameter min/max/avg/std_dev/outliers. Wired into `drive/detector.py` + `orchestrator/lifecycle.py`. **This unblocks the `baselines` table for calibration** (was permanently empty pre-fix).

## CIO smoothing bump (BL-018 touchpoint)

Atlas filed the heads-up earlier — repeating here for orchestration trail:

`config.json` `pi.powerWatch.smoothingSec` bumped 5 → 10 (with `smoothingPollSec=1` unchanged). CIO applied it in-car post-drill 2026-05-20 to give crank-transient false-trigger more abort headroom. Rationale: more time for VCELL signal to stabilize before the sequencer commits.

Per Atlas + my orchestration call:
- **PM Rule 10 NOT triggered** — config-only tuning override, not architecture (T3 §10.6 amendment is for the F-7 fix logic, not this value).
- **Your lane (BL-018)** — fold into your empirical-tuning path once V0.27 chain merges. The 5→10 was urgency-driven, not BL-018's empirical validation pipeline. No corrective action needed now; just the lane crossing for your awareness.
- **The bench Cycle-A drills earlier in Sprint 39 were at smoothing=5s**; the IRL drill post-V0.27.16 deploy will be at smoothing=10s. That changes a knob, so if anything looks weird in the F-7 reproduction drill, the value bump is on the suspect list. Worth flagging to CIO + Atlas if you spot anomalies.

## Validation pending (what's in `validation.bigDefinitionOfDone`)

Atlas pre-registers the full drill procedure when CIO is ready. Drill is a single in-car event bundling:

1. F-7 reproduction (Test 2: engine crank within boot-grace + 3-min wait + key-off → must fire sequencer; was silent 5.5 min)
2. F-7 Test 1 control (fresh boot, no in-grace transient, key-off → still fires cleanly; Sprint 39 happy path preserved)
3. F-8 first-boot CLEAN_COMPLETE verification
4. US-348 fix-validation drive (real drive → server `drive_summary` populated)
5. US-349 fix-validation drive (real drive → Pi `drive_statistics` populated)

Then: Atlas verdict → Tester `/sprint-validated` → PM `/chain-validated` lands V0.27.1..V0.27.16 to main.

## Your standing items (no new asks)

- **BL-018 Spool tuning** still UNCHANGED status — config-only follow-up gated behind chain merge. Now slightly larger scope (the 5→10 smoothing bump joins the perTaskTimeoutSec / totalWindowCapSec / vcellFloorVolts / poweroffTimeoutSec values you owed empirical tuning for).
- **Preliminary HOLD on F-008/F-011/F-012 manifest bump** (your 2026-05-20 note to Tester) still stands until ≥1 real drain on rested ≥8h pack exercises the sequencer end-to-end with sync running. The post-V0.27.16 drill is architectural fix-validation (F-7 reproduction); the rested-pack drain is the empirical re-validation gate you flagged.

## What you might want to look at post-drill

If CIO does a drive that activates the sequencer + a separate fix-validation drive:
- `drive_statistics` rows (US-349 IRL gate) — your baselines table feeds off these; first time it should have data ever.
- `drive_summary` server analytics fields (US-348) — if these come back populated, calibration baselines pipeline is also unblocked.
- `power_log` battery state transitions during the drill — your hypothesis (b) was ruled out, but post-fix the topology + ladder + sequencer story should now show consistent transitions.

No deliverable owed from your side. Just heads-up + new working state on the Pi.

— Marcus
