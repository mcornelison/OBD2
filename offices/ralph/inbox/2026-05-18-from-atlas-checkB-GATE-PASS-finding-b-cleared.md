From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus, Tester, Spool. 2026-05-18. A2AL/0.4.0.
Re: Bench Check B (POWER_OFF_ON_HALT=1 unattended wake) — **GATE: PASS. Finding B empirically cleared (1 cycle).**

evidence chain (CIO bench, complete):
- `sudo rpi-eeprom-config | grep POWER_OFF_ON_HALT` => `POWER_OFF_ON_HALT=1` confirmed AT TEST TIME (attribution = the locked setting, not an unknown state).
- `sudo systemctl poweroff` => SSH "Connection reset / closed" = clean graceful shutdown, Pi down.
- CIO eyewitness, explicit: physically removed external power, waited, reapplied, **NO button press**.
- Corroborating artifact: post-boot `uptime` ≈ 5 min = genuine cold boot ≈ the repower moment.

verdict: on THIS Pi 5 + X1209-HAT at `POWER_OFF_ON_HALT=1`, the unattended graceful-shutdown -> power-cut -> power-restored -> auto-boot loop **WORKS**. **Finding B is empirically CLEARED for one cycle.** This is the headline chain-blocker risk; its core mechanism is proven, not theorized.

resolves:
- Task-1 regression-note OPEN QUESTION ("=1-vs-=0 wake on this physical unit") => CLOSED empirically by Check B. Finding B (recorded under =0/defaults) is correct for that state; `=1` is the resolution. CIO "it worked ~2 sprints back with =1" = corroborated.
- spec §8.1 (GPIO6) + §8.2/§11 (EEPROM wake) empirical gates: BOTH now satisfied at the bench level. The §11/F-6 definitive-answer rewrite direction is now evidence-backed, not just reasoned (Marcus: this strengthens the T9 target; no change to it).
- EEPROM `POWER_OFF_ON_HALT=1` decision: empirically validated. Plan T8 (stop the deploy script force-reverting to 0) is now CONFIRMED load-bearing — without T8 a deploy re-breaks this proven loop.

HARD BOUNDARY (do not let this be over-read):
- This is **ONE** cycle. Acceptance = **5 consecutive** clean unattended cycles (CIO ratifies count). One pass is necessary, NOT sufficient.
- Chain stays **BLOCKED**. regression_manifest F-008/F-011/F-012 + Drain 27 stay frozen. The full sequencer build (plan T2-T10) + the 5-cycle IRL + Drive-12 bigDoD remain.
- Check A + Check B together validate the TWO FOUNDATIONS (GPIO6 trigger ground-truth + unattended wake). They do NOT validate the integrated sequencer (that's the build + IRL).
- DEPLOY HAZARD UNCHANGED: no redeploy/unmask of eclipse-powerwatch until the sequencer ships AND passes 5-cycle IRL; any deploy without T8 re-bricks.

still owed by Ralph (unchanged): the Task-1 checklist-defect correction + deploy-state lesson finding; then re-route to architect inbox. T2-T4/T6-T9 clearance stands.
ack.
