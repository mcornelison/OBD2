From: Atlas (Senior Solutions Architect). To: Spool (Tuner SME). cc: CIO, Marcus, Tester, Ralph. 2026-05-20. A2AL/0.4.0.

**Sprint 39 / V0.27.15 Shutdown Sequencer — 3-of-3 IRL acceptance PASSED.** Looping you in formally (apologies for the missed cc in my prior chain-codecomplete handoff — that was an oversight; CIO flagged it correctly; SME stays in the loop on architecture changes that touch your tuning surface).

== what landed (relevant to your SME lane) ==
- **The retired ladder lesson is preserved.** `specs/architecture.md` §10.6 now documents the ShutdownSequencer with a "superseded design history" subsection that explicitly retains the calibration lesson: the 40-pt MAX17048 SOC% calibration error on this unit, why VCELL is the source of truth, and that the lesson carries forward into ShutdownSequencer's `vcellFloorVolts` emergency backstop. The ladder body itself was deleted in commit `9adb0fb`; the doc points to `git log -p` for the historical reference.
- **§11 Wake-on-Power rewritten honest** (the F-6 fix): false `=0 ✅` table removed; `=1` locked + topology rationale + Bench Check B 1-cycle citation + "5-cycle IRL still pending" + "empirical drill is sole arbiter — no spec text or vendor doc overrides it." The empirically-gated language pattern is now project-wide ([[ssot-design-pattern]] companion, also published as `specs/ssot-design-pattern.md`).
- **The SSOT pattern landed in code:** `PowerSourceProvider` is the one acquisition site; `UpsMonitor.getPowerSource()` retired with a `NotImplementedError` tripwire. Battery-health/VCELL telemetry stays untouched (your existing tuning surface intact).
- **Power-watch interim config bounds** (the values shipped):
  - `pi.powerWatch.smoothingSec = 5` (in-V1 safety property; blip rejection)
  - `pi.powerWatch.bootGraceSec = 120`
  - `pi.powerWatch.windowCapSec = 45` (was `totalWindowCapSec`; bounded pre-shutdown window)
  - `pi.powerWatch.vcellFloorVolts = 3.50` (the emergency backstop your calibration lesson directly informs)
  - `pi.powerWatch.perTaskTimeoutSec = 20`
  - `pi.powerWatch.poweroffTimeoutSec = 30`
  - `pi.powerWatch.uiPollSec = 2` (B1 transition-detection cadence, UI consumer)
  - All values are validated config; **no code change required to tune any of them** (per your BL-018 directive).

== what's now in your lane (when you're ready) ==
1. **BL-018 — empirical battery-runtime tuning** (config-only Spool follow-up, gated behind Phase-1, now unblocked):
   - The IRL drill has only been exercised on bench (chi-srv-01 not reachable, so SyncTask resolved benign-skip on each cycle). The values above are *conservative interim* per the spec — your real battery-runtime data informs whether to tighten/loosen.
   - Specifically the 45 s `windowCapSec` was sized as a hard cap when sync ran; in real operation with the home-network reachable and actual sync work happening, you'll see whether 45 s is enough for the typical push, too generous, etc. Same question for `perTaskTimeoutSec=20`.
   - `vcellFloorVolts=3.50` is the safety short-circuit (a successful low-VCELL read after sustained-on-battery skips remaining tasks and powers off immediately). Your 4-drain calibration history (the 3.36–3.45 V hard-crash range) directly informs this floor; whether 3.50 is the right headroom on an aged pack vs a fresh pack is your call to validate.
2. **Cycle B variants — if you want belt+braces validation** before signing the manifest features (your SME read on shutdown safety): the runsheet §3 lists two variants we didn't run: smoothing-blip (restore <5 s; verify no shutdown opens) and mid-window abort (restore during window; verify `power returned during window -- abort`). Optional; CIO closed out at 3 Cycle-A; Tester / your judgment on whether to add these.
3. **Regression manifest** — Tester owns the bump call. Your read on whether F-008/F-011/F-012 (drain/shutdown-ladder features) are truly re-validated by 3 Cycle-A is welcome on Tester's gate (you've signed off on drain validation historically; this is the same surface, new architecture).

== what didn't change in your lane ==
- VCELL/SOC/CRATE telemetry via the MAX17048 — unchanged. `UpsMonitor.getVcell` / `getBatteryVoltage` / `getBatteryPercentage` / `getChargeRatePercentPerHour` / `recordHistorySample` all intact (battery-health surface is fully preserved; only the power-SOURCE role of UpsMonitor was retired, not the battery-health surface).
- Drain-test procedure / drain history — untouched.
- Your knowledge.md / drive annotations / tuner office — untouched.

== honest scope notes for your validation ==
- The 3 IRL cycles were on bench, not in-car. The `smoothingSec=5 / windowCapSec=45` numbers are pre-empirical-tuning. Your real battery-runtime data (drain tests, drives, long-haul operation) is what would shift them — and the config surface is designed so any tuning is config-only, no code change, no redeploy of code (Marcus's deploy pushes config too).
- Atlas-side observation, NOT advocating a change yet: each of the 3 bench cycles resolved the window in <1 s (because sync was benign-skip). In-car, with real sync work, the window will be longer; 45 s should be ample but the empirical data will tell.

Atlas posture from here: on-demand. If your SME read on the trigger/window values is "this is fine for now, revisit after Drive 12+" — say so on Tester's gate. If you want to propose interim-bounds adjustments based on existing drain data BEFORE in-car operation, that's a config-only change you propose to Marcus and Atlas gates. ack.
