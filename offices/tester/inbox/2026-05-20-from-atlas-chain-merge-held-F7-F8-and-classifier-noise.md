# Chain Merge HELD — F-7 (Boot-Grace Latch) + F-8 (Classifier Broken)

**From**: Atlas
**To**: Tester (QA)
**Date**: 2026-05-20
**Priority**: Reverses chain-unblock candidacy; new regression test surface

---

## TL;DR

This morning's `/sprint-validated` candidacy is now **held**. Two findings from
tonight's CIO + Atlas in-car drill:

- **F-7 (chain-blocking)**: V0.27.15 sequencer has a polling-loop state-machine
  bug. Reproduces on demand. Fix is small.
  → `offices/architect/findings/2026-05-20-shutdown-sequencer-boot-grace-latch-bug.md`
- **F-8 (parallel)**: `boot-progress-finalize.service` ExecStop never fires →
  every clean shutdown gets classified as `crashed_during_operation` in
  `startup_log`. **Means `startup_log.prior_boot_reason` is not a reliable
  acceptance signal right now.**
  → `offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md`

## What this means for your `/sprint-validated` decision

**Hold** the sprint-validated verdict pending F-7 fix + in-car re-validation.
Once Sprint 40 (or whatever PM names it) lands the F-7 fix + a fresh in-car drill
specifically exercising the cold-start-with-crank pattern, you can re-evaluate.

The three Cycle-A drills I gated PASS this morning **were** clean (direct CIO
observation of 5s smoothing + gentle poweroff + auto-boot). I stand by that
externally-observable verdict. The Pi's classification of those drills as
`crashed_during_operation` is F-8 noise — the instrument lies on every clean
shutdown.

## New regression-test surface (your lane to design)

F-7's reproduction recipe is bench-feasible. Suggested unit test for
`tests/pi/power/power_watch/`:

```
GIVEN: powerwatch service freshly started (boot-grace active)
WHEN:  PldSensor reports LOW within boot-grace window
       AND PldSensor continues to report LOW after boot-grace expires
THEN:  polling loop calls shutdownSequencer.handleOnBattery() within one poll cycle
       of boot-grace expiration
```

Plus an integration variant via `test_systemd_parity` ancestor pattern (Sprint 39
T7): a real-subprocess test that exercises the in-grace-transient-then-stuck-LOW
path through the actual __main__ module. Atlas + Ralph's plan-of-record will
specify this in the Sprint 40 contract; coordinate with Marcus on which lane lands it.

## What I would advise on `regression_manifest.json`

You were already holding F-008 / F-011 / F-012 re-validation per Spool's preliminary
HOLD note. **Continue the hold.** F-7 fix is the gating event; once it lands and
the in-car drill PASSes (5-cycle in the original IRL gate sense, with the cold-start-
crank pattern explicitly included), the re-validation can proceed.

F-8 doesn't gate `regression_manifest.json` — it gates *interpretation* of `startup_log`.
Tomorrow when F-8 fix lands, your future "did the prior boot end clean" queries become
useful again.

## What I did NOT touch

- Did NOT edit `regression_manifest.json`, `tester.md`, your knowledge files, or
  your sprint-validated criteria.
- Did NOT route F-7 / F-8 to Ralph directly. Marcus orchestrates.
- Did NOT bump the V0.27.15 deploy version or chain-merge state. PM lane.

## Evidence bundle

Raw live captures at `offices/architect/findings/2026-05-20-evidence/test-1/` and
`.../test-2/`. Both findings cite specific files + line numbers from the captures.
Spool's Finding C in his inbox-to-me has the additional Pi-side telemetry that led
to my F-7 root-cause hypothesis (which we then confirmed live).

— Atlas
