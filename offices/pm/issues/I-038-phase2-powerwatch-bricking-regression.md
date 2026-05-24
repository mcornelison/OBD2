# I-038 — Phase-2 eclipse-powerwatch self-bricking regression (SEV-1)

**Severity**: SEV-1 (shipped a bricking regression to real hardware)
**Status**: SUPERSEDED by the Shutdown Sequencer (Sprint 39 / V0.27.15, plan-driven, Atlas-approved 2026-05-18). The sequencer IS the structural fix — plan T2/T5 (smoothed GPIO6 SSOT trigger) + T8 (EEPROM=1 + deploy-script defect). Hotfix `84b5469`/`4edbdc1` folded INTO the clean design (debounce→smoothing; GPIO6 PldSensor kept+reused). **Do NOT re-fix separately.** Closes on IRL acceptance (5 clean unattended cycles). `eclipse-powerwatch` stays MASKED; NOT re-deployed.
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

## Resolution path (SUPERSEDES the Session-38 re-deploy gate)

The Session-38 "re-deploy hotfix + `systemctl unmask eclipse-powerwatch`" gate
is **RETIRED** (Atlas, CIO-approved 2026-05-18). The Shutdown Sequencer is the
corrected replacement, NOT a re-deploy of the old service.

- **DEPLOY HAZARD:** `eclipse-powerwatch` stays MASKED on the Pi and MUST NOT be
  unmasked/redeployed until the sequencer ships AND passes IRL acceptance. Any
  deploy re-enabling it — or `deploy-pi.sh`/`enforce-eeprom-power-off-on-halt.sh`
  re-running the force-`POWER_OFF_ON_HALT=0` step — RE-BRICKS the Pi.
  `POWER_OFF_ON_HALT=1` is CIO-locked (2026-05-18); plan **T8** corrects the
  deploy script.
- **Fix:** Sprint 39 / V0.27.15 plan **T2/T5** (smoothed GPIO6 SSOT trigger) +
  **T8**. The GPIO6 open question is resolved by Approach-1 (vendor-confirmed
  GPIO6 PLD digital SSOT, Geekworm/Suptronics) + plan **T1** read-only bench obs.
- **Close criteria:** 5 consecutive clean unattended shutdown→restore cycles
  (CIO IRL). Then Drain 27 (≥8h-rested) + chain bigDoD. Chain stays BLOCKED
  until then.

## Related

- TD-053 (test-validation gap that let this ship — stubbed `isOnBattery`)
- BL-018 (Spool empirical tuning — UNCHANGED; config-only, gated behind Phase-1)
- [[feedback-spec-invariant-validated-against-real-signal]]
- I-036 / I-037 (the prior shutdown/canary saga this Phase-2 work was meant to close)
- **Shutdown Sequencer (the structural fix)**: `docs/superpowers/specs/2026-05-18-pi-shutdown-sequencer-design.md` + `docs/superpowers/plans/2026-05-18-pi-shutdown-sequencer.md` (Sprint 39 / V0.27.15)
- Atlas coordination: `offices/pm/inbox/2026-05-18-from-atlas-sequencer-power-shutdown-coordination.md` (supersession map; do-not-double-track) + `...-shutdown-sequencer-approved-handoff.md`
