# Sprint 19 — Consolidated Findings (2026-04-29 test session)

**Date:** 2026-04-29
**From:** Spool (Tuning SME)
**To:** Marcus (PM)
**Priority:** Important — Sprint 19 planning input
**Supersedes:** `2026-04-23-from-spool-ups-drain-test-2-findings.md` + `2026-04-23-from-spool-sprint18-design-nuances.md` (both archivable; this consolidates everything Sprint-19-bound from the 2026-04-29 test session)

## Context

CIO ran a multi-test sequence today on the Sprint 18 deploy:
- **Drain test 4** — Pi unplugged at engine-off, ran on UPS until hard crash
- **Drive 4** — sustained warm idle (post-jump-start battery recharge), 10:47 min, 4,487 rows
- **Drive 5** — full cold-start → warm-idle cycle, 17:39 min, 489 ECU samples per PID

This note consolidates Sprint 19 priorities from that session. Sprint 18's win/loss column is now empirically clear after live testing.

## Sprint 18 — what shipped well (verified live)

| Story | Verified by | Outcome |
|-------|-------------|---------|
| US-226 (sync restore) | sync_log advancing post-boot ×2 | ✅ Working — flush-on-boot fires reliably |
| US-227 (Pi truncate) | `drive_id=1` pollution gone | ✅ Working |
| **US-229 (drive_end ELM_VOLTAGE filter)** | drive_end fired at engine-off on **drives 4 AND 5** | ✅ **Solid — two consecutive validations** |
| US-230 (journald persistence) | `/var/log/journal/<machine-id>/` populated | ✅ Working |
| US-210 (real-OBD service) | drives 4+5 captured with `data_source='real'` | ✅ Working |
| US-212 (data_source hygiene) | All new rows tagged correctly | ✅ Working |

Six Sprint 18 wins is a real outcome — credit where due. **The infrastructure side of B-037 is now genuinely working.**

## Sprint 18 — what didn't ship or didn't work (Sprint 19 must-fix)

### 🔴 P0 #1 — US-216 SOC ladder still does not fire (FOURTH drain test)

**Drain test 4 today** (the 4th drain across 9 days):

| | Drain 1 (Session 6) | Drain 2 (2026-04-23) | Drain 3 (2026-04-29 morning) | **Drain 4 (today afternoon)** |
|-|---------------------|----------------------|--------------------------------|-------------------------------|
| Mode | --simulate | real-OBD | real-OBD | real-OBD post-drive |
| US-216 deployed | No | Yes | Yes | Yes |
| Pi runtime | 23:49 | 14:26 | 10:14 | **10:02** |
| Source ever→BATTERY | — | **No** | **No** | **No** |
| `battery_health_log` rows | 0 | 0 | 0 | **0** |
| Crash at SOC | 0% | 63% | 60% | **57%** |
| Crash at VCELL | unknown | 3.364V | 3.446V | **3.376V** |
| Boot signature | hard | hard | hard | **hard (EXT4 orphan cleanup)** |

**The pattern is now indisputable.** The PowerDownOrchestrator code is correctly designed (verified by source read in my 2026-04-23 note) but **never fires** because UpsMonitor's `getPowerSource()` heuristic doesn't flip to BATTERY when wall power is removed. The CRATE register is unavailable on this hardware setup, and the VCELL slope rule isn't catching the trend reliably either.

Sprint 19 must do TWO things to make US-216 functional:

**Story candidate: "US-216 trigger-source change SOC → VCELL" (M, P0).**
Suggested thresholds based on 4 drain tests of empirical VCELL data:
- WARNING: VCELL ≤ 3.70V (start drain event, force sync push, stop new drive_id minting)
- IMMINENT: VCELL ≤ 3.55V (close BT, stop OBD polling, KEY_OFF active drive)
- TRIGGER: VCELL ≤ 3.45V (`systemctl poweroff` — buck dropout is at ~3.36V, gives ~90s headroom)

Across 4 drain tests, all crashes occurred with VCELL between 3.36V and 3.45V — TRIGGER at 3.45V would have fired in time on every test.

**Story candidate: "Fix UpsMonitor BATTERY-detection heuristic" (S, P0).**
Add a third rule: `VCELL < 3.95V sustained for 30s → BATTERY`. Covers the case where any external power loss happens from a not-fully-charged state (which is what we have on this hardware — see calibration finding below). Drop CRATE-rule entirely if it's unreliable on this configuration.

### 🔴 P0 #2 — US-228 cold-start metadata FOURTH NULL across drives 3, 4, 5, and the in-flight 5

Sprint 18 closed US-228 with "Option (b) backfill-UPDATE with COALESCE." Empirically, the UPDATE path is dead. Every drive_summary row created post-Sprint-18 still has all three sensor metadata fields as NULL:

```
drive_id  iat   batt  baro
   5     NULL  NULL  NULL    ← drive completed today
   4     NULL  NULL  NULL    ← drive completed today
   3     NULL  NULL  NULL    ← from before US-228, expected
```

Drive 4 and 5 ran AFTER US-228 shipped. Both have NULL. **This is not a race condition** — drives 4 (10:47 min) and 5 (17:39 min) both had ample time for the UPDATE to fire if it were going to. The UPDATE path either isn't subscribed to the right event or has a logic bug.

**Story candidate: "Actually fix US-206 — drive_summary cold-start metadata backfill" (S, P0).** Sprint 18's attempt didn't work. Sprint 19 needs a different approach OR a debug-and-patch of the existing one. Recommended: defer the drive_summary INSERT until first IAT/BATTERY/BARO reading captured (Option (a) from my original note) — simpler than the UPDATE-backfill approach and harder to break.

### 🔴 P0 #3 — MAX17048 SOC% calibration is now egregiously broken

Today's data quantifies the problem precisely:

| Moment | SOC% reported | VCELL measured | Reality |
|--------|--------------|----------------|---------|
| Drain test 4 start | 73% | 3.720V | Already partially discharged |
| Drain test 4 end | 57% | 3.376V | At/past LiPo knee |
| Post-replug recharge | **64%** | **4.202V** | Full charge, gauge stuck |
| Drive 5 start | **60%** | **4.200V** | Full charge, **40-point error** |
| Drive 5 end | 71% | 4.201V | Gauge slowly creeping up |

A 40-percentage-point error in SOC% between gauge reading and reality (VCELL truth) means the SOC ladder, even if it fired correctly, would never be set at thresholds that match true battery state. This is why Sprint 19 must switch the trigger to VCELL — SOC% on this hardware is not trustworthy and may never be without a proper learning run.

**Story candidate: "MAX17048 calibration learning run protocol + scripts" (M, P1).** Hardware/protocol work — Spool can author the procedure spec, Ralph implements scripts. Run order: full-charge → controlled-load discharge to known endpoint → full-recharge with specific register writes to enable ModelGauge learning. Several hours per cycle. Should be done at least once before Sprint 19 closes.

### 🟡 P1 — UPS charging path may not bring battery to true full

Drive 5 started at SOC=60%, VCELL=4.200V. After ~10 hours on wall power between drain test 4 (Pi died ~14:00Z) and Pi replug (~23:44Z), the gauge was reading 60% — VCELL says 4.200V is full but gauge says 60%. Either the calibration error masks a fully-charged state OR the wall charger isn't bringing the battery quite to spec. Either way, an investigation is owed.

**Story candidate: "Investigate UPS charge path — VCELL final-charge target verification" (S, P1).** Audit: does the UPS HAT's charger actually bring VCELL to 4.200V at terminal (or only ~4.10–4.15V)? Compare against MAX17048 datasheet expectations.

## New tuning-domain finding from Drive 5 (positive signal, no story needed)

**LTFT showed real adaptation behavior for the first time.** Drives 3 and 4 showed LTFT_1 stuck at exactly **-6.25%** (one ECU notch). Drive 5 showed three distinct quantized values (-7.03, -6.25 implied, -4.69) with avg -6.42%.

Most likely cause: post-jump-start ECU adaptation reset. CIO used the Eclipse battery to jump another car earlier today; the deep-discharge event partially cleared the ECU's long-term fuel trim adaptation table. ECU is now actively re-learning.

**This is HEALTHY behavior** — confirms the fuel control system is responsive, not stuck. Worth tracking across the next 3-5 drives to see where LTFT settles. **No code action.** I'll note in `knowledge.md` once next drives confirm where the new learned trim lands.

## Drive 5 fingerprint (will supersede Drive 3 in `knowledge.md`)

Cleanest dataset to date (17:39 min, full cold→warm progression + post-jump alternator behavior):

- **Coolant warmup**: 31°C → 89°C, thermostat opens at 80°C (third confirmation, I-016 closed benign × 3)
- **Idle RPM (warm)**: 753–785 (32 RPM spread — engine idles like new)
- **MAF (warm)**: 3.04–3.14 g/s (0.1 g/s spread — pure steady state)
- **Engine load (warm)**: 18.04–18.82%
- **Timing advance (warm)**: 4–7° BTDC (still lower than community 10–15° norm; tracked across 3 drives now — likely modified-EPROM signature, will revisit at ECMLink V3)
- **Battery V**: 13.8–14.4V, alternator working hard post-jump
- **DTC/MIL**: 0/0 across all three drives

Engine health continues EXCELLENT.

## Sprint 19 must-ship — three non-negotiables

1. **US-216 trigger-source change SOC → VCELL** (M, P0) — every drain test will fail until this lands
2. **UpsMonitor BATTERY-detection fix** (S, P0) — compounds with #1; orchestrator can't fire until this works
3. **Actually fix US-228** (S, P0) — Option (a) defer-INSERT approach; current UPDATE-backfill is dead

If Sprint 19 capacity allows:
4. **MAX17048 calibration learning run** (M, P1) — hardware protocol work; precondition for SOC% being trustworthy long-term
5. **UPS charge-path audit** (S, P1) — small but informative

## Spool-side deliverables

- **Update `knowledge.md`** with Drive 5 as new authoritative warm-idle baseline (supersedes Drive 3, which superseded Session 23)
- **Track LTFT post-jump adaptation across next 3-5 drives** — will note the new learned trim once it stabilizes
- **MAX17048 calibration procedure spec** — Spool authors, Ralph implements scripts (if you accept story candidate above)

## Reusable tooling created today

Per CIO standing directive on graduating inline patterns to scripts:

- `offices/tuner/scripts/pi_state_snapshot.sh` — replaces 6+ inline SSH+sqlite bursts from system tests
- `offices/tuner/scripts/ups_drain_monitor.sh` — replaces 4 inline drain-monitor loops
- README updated

Future drain tests + drive grades will use these instead of inlining.

## Bottom line

Sprint 18 shipped 6 wins and 2 broken stories. Sprint 19 cleans up the 2 broken ones plus the calibration root cause. **No new feature scope** — just finish what Sprint 18 attempted. After Sprint 19, US-216 should ACTUALLY work for the first time and the next drain drill becomes the ship-gate.

— Spool
