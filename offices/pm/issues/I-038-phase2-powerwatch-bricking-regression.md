# I-038 — Phase-2 eclipse-powerwatch self-bricking regression (SEV-1)

**Severity**: SEV-1 (shipped a bricking regression to real hardware)
**Status**: Hotfix committed + pushed (`84b5469`+`4edbdc1`+`3047673`), **NOT re-deployed** (gated)
**Filed**: 2026-05-18 (Session 38, Marcus/PM)
**Reported by**: CIO IRL test + Ralph RCA (`offices/pm/inbox/2026-05-18-from-ralph-SPRINT-FAIL-phase2-bricking-loop-and-hotfix.md`)
**Sprint verdict**: CIO — **Sprint 38 / Phase-2 = BIG FAIL**
**Affected version**: V0.27.14 @ `0125417` (deployed Pi + chi-srv-01 this session)

## Symptom (IRL, CIO, 2026-05-18)

V0.27.14 deployed; on the first IRL power on/off test the Pi entered a
self-bricking loop: reapply external power → Pi boots → OBD2 screen → ~10–15s
later `eclipse-powerwatch` runs the pre-shutdown sequence and powers the Pi OFF
**while external power is still ON**. Repeated 3×. Pi effectively
unreachable/unusable — worse than the pre-existing I-036/I-037 state (the Pi now
powers itself off shortly after every boot, on wall/car power).

## Root cause (Ralph, high-confidence)

The Phase-2 isolated-shutdown-service architecture is sound. The defect is the
**trigger**:

1. `UpsMonitor.getPowerSource()` is a VCELL-trend HEURISTIC, not a ground-truth
   "external power present" signal. Its slope rule (< −0.005 V/min) reports
   BATTERY on the normal VCELL sag a Pi draws at boot — even with external power
   physically connected — within ~2 poll ticks (~10s).
2. The controller acted on that **first unconfirmed BATTERY transition** (spec
   sec 6.2 "sustained on-battery, **debounced**" was under-implemented — the
   invariant was treated as implied by a dependency, not implemented + tested
   against the real signal's transient behavior).
3. Aggravator: the T4 "fail-safe" treated a FAILED VCELL read as floor →
   IMMEDIATE poweroff. I2C settles late at boot, so a transient boot read
   failure alone triggered an instant poweroff — the fail-safe defaulted to the
   catastrophic direction in the boot/external-power context.

## Recovery (no OS reinstall / no factory reset)

sshd comes up before powerwatch fires. CIO used a retry-loop that masks
`eclipse-powerwatch.service` the instant the Pi is reachable; once `OK_MASKED`
lands the next boot stays up. `eclipse-obd` (collector) untouched. Phase-1
EEPROM unattended-wake NOT implicated, remains valid.

## Hotfix (committed, pushed at Session-38 closeout, NOT re-deployed)

- `84b5469` — debounced sustained-confirmation gate (BATTERY must hold
  continuously across `confirmWindowSec`, re-sampled at `confirmPollSec`, before
  ANY pipeline/poweroff; a transient blip aborts with no poweroff) + boot-grace
  (`bootGraceSec`) + reversed uncertain-VCELL direction (a failed read never
  forces poweroff; floor is a backstop only on a SUCCESSFUL low read AFTER
  sustained battery is confirmed). New config (validated, Spool-tunable):
  `bootGraceSec=120` / `confirmWindowSec=20` / `confirmPollSec=5`. Regression
  tests added (transient-blip / failed-vcell).
- `4edbdc1` — trigger on the X1209 **GPIO6 PLD ground-truth** power-loss signal
  instead of the VCELL heuristic (the more fundamental fix).
- `3047673` — RCA/recovery handoff + **GPIO6 open question** (must be resolved
  before re-deploy).

## Re-deploy gate (before Phase-2 is anything but FAIL)

ALL of: (a) Ralph hotfix-verification complete (full not-slow pi suite +
runsheet "deploy-safe" line); (b) GPIO6 open question resolved; (c) CIO
direction → `/sprint-deploy-pm` Phases 4–7 (V0.27.14→V0.27.15) + `systemctl
unmask eclipse-powerwatch.service` + corrected runsheet precondition ("boot N×
on external power, Pi STAYS UP > bootGrace+confirmWindow ~3 min, no
self-poweroff" BEFORE on-battery cycles). Then Drain 27 (≥8h-rested) + chain
bigDoD.

## Related

- TD-053 (test-validation gap that let this ship — stubbed `isOnBattery`)
- BL-018 (Spool empirical tuning, now also covers the new debounce/grace bounds)
- [[feedback-spec-invariant-validated-against-real-signal]]
- I-036 / I-037 (the prior shutdown/canary saga this Phase-2 work was meant to close)
