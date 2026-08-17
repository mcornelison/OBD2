From: Ralph (Dev). To: Marcus (PM), cc CIO + Spool. 2026-05-18.
Priority: SEV-1 incident + sprint verdict. **CIO verdict: Sprint 38 / Phase-2 = BIG FAIL.**

PURPOSE: report (per CIO direct order) the Phase-2 power-watch field failure, the
root cause, the hotfix, and the corrected re-validation gate. This is logged as a
FAIL regardless of the hotfix — it shipped a bricking regression to real hardware.

=== WHAT HAPPENED (IRL, CIO, 2026-05-18) ===
V0.27.14 (Phase-2 power-watch) deployed to Pi + chi-srv-01. On the FIRST IRL
attempt the Pi entered a self-bricking loop:
- Remove external power -> Pi shuts down fast+smooth (sync status unconfirmed).
- UPS/HAT goes dark only after the CIO then removes power.
- Reapply power -> Pi boots -> OBD2 screen -> **~10-15s later eclipse-powerwatch
  runs the pre-shutdown sequence and powers the Pi OFF while external power is
  still ON.** Repeated 3x. Pi effectively unreachable / unusable.
This is worse than the pre-existing I-036/I-037 state: the Pi now powers itself
off shortly after every boot, on wall/car power.

=== ROOT CAUSE (Ralph, high-confidence; evidence capture pending recovery) ===
The Phase-2 architecture (isolated shutdown service) is sound. The defect is in
the trigger: I under-implemented the spec sec 6.2 requirement "sustained
on-battery, **debounced**".
- `UpsMonitor.getPowerSource()` is a VCELL-trend HEURISTIC, not a ground-truth
  "external power present" signal. Its slope rule (< -0.005 V/min) reports
  BATTERY on the normal VCELL sag a Pi draws at boot -- even with external
  power physically connected -- within ~2 poll ticks (~10s).
- The old controller acted on that FIRST unconfirmed BATTERY transition: ran
  the pipeline, re-checked (still latched BATTERY), powered off.
- Aggravator: my T4 "fail-safe" treated a FAILED VCELL read as floor ->
  IMMEDIATE poweroff. I2C settles late at boot, so a transient boot read
  failure alone triggered an instant poweroff. The fail-safe defaulted to the
  catastrophic direction in the boot/external-power context.
Net: powerwatch shut the Pi down ~10-15s after every boot.

=== RECOVERY (no OS reinstall / no factory reset) ===
sshd comes up before powerwatch fires. CIO given a retry-loop that masks the
service the instant the Pi is reachable; once `OK_MASKED` lands, the next boot
stays up. eclipse-obd (collector) untouched. Phase-1 EEPROM unattended-wake is
NOT implicated and remains valid.

=== HOTFIX (committed `84b5469`, sprint/sprint38-bugfixes-V0.27.12) ===
Root-cause fix, not a band-aid:
1. Debounced sustained-confirmation gate in the controller: a BATTERY signal
   must hold continuously across `confirmWindowSec` (re-sampled at
   `confirmPollSec`) before ANY pipeline/poweroff; a transient blip aborts
   with no poweroff.
2. Boot-grace: ignore BATTERY for `bootGraceSec` after service start.
3. Reversed the uncertain-VCELL direction: a failed read never forces
   poweroff; the floor is a backstop only on a SUCCESSFUL low read AFTER
   sustained battery is confirmed.
4. New config (validated, Spool-tunable): bootGraceSec=120, confirmWindowSec=20,
   confirmPollSec=5. Regression tests added (transient-blip / failed-vcell).
   power_watch suite 21 passed incl. the T8 real-invocation guard; ruff clean;
   validate_config exit 0. Full not-slow pi suite gate running at time of
   writing (result appended to the runsheet before any "deploy-safe" claim).

=== SPRINT VERDICT + WHAT THE PM SHOULD RECORD ===
- **Sprint 38 / Phase-2 IRL: FAIL.** Shipped a bricking regression to hardware
  on first real test. The hotfix does not erase the FAIL; it un-bricks and
  re-opens the gate.
- Process lesson filed in shared memory:
  [[feedback-inventory-first-before-first-dispatch]] (T9) and now this -- a
  spec invariant ("debounced") was treated as implied-by-a-dependency rather
  than implemented + tested against the real signal's transient behavior. The
  T8 real-invocation guard passed because it stubbed isOnBattery=True; it did
  NOT exercise a transient/boot-sag signal. Recommend a TD: "Phase-2 trigger
  must be validated against real UpsMonitor boot/transient behavior, not a
  stubbed predicate."
- Chain stays BLOCKED. V0.27 chain merge remains gated.

=== CORRECTED RE-VALIDATION GATE (before Phase-2 can be called anything but FAIL) ===
Re-deploy the hotfix; `systemctl unmask eclipse-powerwatch.service`; then the
IRL acceptance in `offices/ralph/phase2-deploy-and-acceptance-runsheet.md`
(updated): MUST now include an explicit **"boot N times on external power,
confirm the Pi STAYS UP > bootGrace + confirmWindow (~3 min) and does NOT
self-poweroff"** precondition BEFORE the on-battery cycles. Spool battery-runtime
tuning of the new debounce/grace bounds still owed (commit `d7849ce` family).
Drain 27 (>=8h-rested pack) and the chain bigDoD remain open.
