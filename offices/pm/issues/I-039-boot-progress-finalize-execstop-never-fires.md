# I-039 — F-8: boot-progress-finalize.service ExecStop never fires during shutdown

- **Filed**: 2026-05-20 (Session 40) by Marcus (PM)
- **Source**: Atlas inbox note `offices/pm/inbox/2026-05-20-from-atlas-chain-merge-BLOCKED-F7-and-F8-findings.md` + Atlas finding `offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md` (full RCA + evidence bundle there; PM does NOT duplicate)
- **Severity**: HIGH (instrument-honesty defect; NOT chain-blocking — parallel to F-7)
- **Status**: ACTIVE — bundles into Sprint 40 / V0.27.16 with F-7

## One-line summary

`boot-progress-finalize.service` ExecStop never runs during shutdown (systemd unit dependency-graph defect — missing `Conflicts=shutdown.target`). Every clean shutdown gets classified `crashed_during_operation`. Spool's Finding C (12 boots today classified `crashed_during_operation`, 19-min BATTERY_V trail, zero `power_log` battery transitions) is the empirical proof.

## Root cause of "Finding A / CLEAN_COMPLETE instrument honesty"

This is the root cause of what was tracked as "Finding A" since V0.27.13 drill. Atlas's evening RCA pinpointed the exact systemd unit defect. Fix is one-line addition (`Conflicts=shutdown.target` directive) in `deploy/boot-progress-finalize.service`.

## Impact

- Every "graceful shutdown" classification has been wrong since the boot-progress instrument was introduced. Historical `startup_log.prior_boot_clean=0` rows do NOT reliably distinguish hard-crash vs clean-shutdown (regression_manifest F-011/F-012 implications).
- Tester's regression_manifest re-validation gating (Spool preliminary HOLD) was right but for an additional reason: the instrument itself was lying.

## Resolution path

Sprint 40 / V0.27.16 US-345 = T2 fix per Atlas's task spine. Verify on real Pi: clean shutdown → next boot's `startup_log` shows `prior_boot_clean=1, last_stage=CLEAN_COMPLETE`. Bench-testable on first reboot.

## Related

- F-7 / BL-019 (chain-blocking parallel; same sprint)
- Finding A predecessor (now superseded by this issue with concrete RCA + fix)
- Spool's Finding C (the trigger evidence)
