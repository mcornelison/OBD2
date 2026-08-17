# Drain Test 5 — US-216 staged shutdown STILL doesn't fire (5/5 hard crashes); plus wake-on-power verification ask

**Date**: 2026-05-01
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: **P0 for Sprint 21 — staged shutdown remains architecturally broken despite Sprint 19/20 fixes**

## TL;DR

Drain Test 5 ran today post-Sprint-20 deploy. Outcome: **HARD CRASH** at the LiPo discharge knee, EXT4 orphan cleanup confirmed on next boot. **5 drain tests, 5 hard crashes.**

Mixed result, though. Sprint 19/20 fixed the **detection and logging** of the wall-out event — UpsMonitor flipped to BATTERY correctly, PowerMonitor wrote 3 transition rows to `power_log`, the dashboard display flipped to "Battery" mode (visible to CIO for the first time across 5 tests). The **actual safety feature** — the staged-shutdown stages that fire WARNING / IMMINENT / TRIGGER as VCELL declines — never engaged. Even though VCELL crossed all three US-234 thresholds (3.70V, 3.55V, 3.45V) over a 14-min drain, **zero stage transitions were written to `power_log` and zero shutdown events appeared in journald**.

The Pi has shipped Sprint 19's US-234 (SOC→VCELL trigger source change) and Sprint 20's US-243 (PowerMonitor activation), but the part of US-216 that **monitors VCELL during BATTERY state and fires graceful shutdown** is still not engaging in production.

CIO follow-up question raised a separate Sprint 21 verification item: **does Pi auto-wake on wall-power return after a graceful shutdown?** Critical for the post-B-043 wiring use case. Detailed below.

Two Sprint 21 candidates outlined at the end.

---

## 1. Drain Test 5 timeline

| Marker | Time (UTC) | Time (local) | Evidence |
|---|---|---|---|
| Pre-drain baseline | 12:54:41Z | 07:54:41 CDT | VCELL=4.139V, SOC=94%, EXTERNAL |
| Display flip to "Battery" (visual) | ~12:56:30Z | ~07:56:30 CDT | CIO photo |
| **CIO unplugged Pi** | **12:56:39Z** | **07:56:39 CDT** | journal: `pi.hardware.ups_monitor: external -> battery`; `pi.power.power: ac_power -> battery` |
| (my marker, ~52s late) | 12:57:31Z | 07:57:31 CDT | drain monitor manual mark |
| Crossed WARNING (3.70V) | ~12:58:00Z | ~07:58:00 CDT | drain monitor: 3.674V; **no WARNING event in journal** |
| Crossed IMMINENT (3.55V) | ~13:05:30Z | ~08:05:30 CDT | drain monitor: 3.549V; **no IMMINENT event in journal** |
| Crossed TRIGGER (3.45V) | ~13:10:30Z | ~08:10:30 CDT | drain monitor: 3.439V; **no TRIGGER event in journal** |
| Last successful read | 13:11:14Z | 08:11:14 CDT | VCELL=3.416V (well below trigger), SOC=63 |
| **Pi went silent** | **~13:11:25Z** | **~08:11:25 CDT** | drain monitor: ssh-unreachable. ~10s after crossing trigger — too fast for a real `systemctl poweroff` |
| Pi rebooted (CIO replug) | 13:18:47Z | 08:18:47 CDT | replugged after diagnostic prep |
| Boot 0 first journal entry | 13:08:07 CDT-tagged | (clock not yet NTP'd) | EXT4 orphan cleanup confirmed |

**Total runtime on battery: ~14:35** — consistent with prior drains (drain 1 / 23:49 sim load; drain 2 / 14:26 real; drain 3 / 10:14 real; drain 4 / 10:02 real). All 5 hit the same buck-dropout knee.

## 2. Smoking gun — hard crash confirmed

```
May 01 08:08:07 Chi-Eclips-Tuner kernel: EXT4-fs (mmcblk0p2): orphan cleanup on readonly fs
May 01 08:08:07 Chi-Eclips-Tuner kernel: EXT4-fs (mmcblk0p2): mounted filesystem ... ro with ordered data mode
May 01 08:08:07 Chi-Eclips-Tuner systemd-journald[345]: File /var/log/journal/.../system.journal corrupted or uncleanly shut down, renaming and replacing
```

Same signature as drains 1-4. Filesystem fsck'd clean on next boot, no data corruption. But the journal was actively being written when power vanished — definitive evidence the OS did not gracefully halt.

## 3. The mixed result — what's working vs what's broken

| Component | Status | Evidence |
|---|---|---|
| **US-243 PowerMonitor instantiation** | ✅ WORKING | journal at deploy startup: `_initializePowerMonitor: PowerMonitor initialized (US-243 power_log write path active)`, `_subscribePowerMonitorToUpsMonitor: PowerMonitor subscribed to UpsMonitor.onPowerSourceChange (fan-out preserves prior callback)` |
| **US-243 PowerMonitor → power_log on transitions** | ✅ WORKING | 3 new rows captured at 12:56:39Z: `power_saving_enabled` / `transition_to_battery` / `battery_power`. Plus 3 prior rows from earlier flip drill (4 ↔ AC). 6 rows total in power_log, all from real events. |
| **UpsMonitor BATTERY detection** | ✅ WORKING | journal: `external -> battery` correctly fired on wall-out |
| **Display flipped to "Battery" mode** | ✅ WORKING | CIO photo confirms; first visible BATTERY indication across 5 drain tests |
| **US-216 WARNING stage (VCELL ≤ 3.70V)** | ❌ **NEVER FIRED** | VCELL crossed at ~12:58:00Z. Zero WARNING events in journal. Zero rows written to power_log for the WARNING transition. |
| **US-216 IMMINENT stage (VCELL ≤ 3.55V)** | ❌ **NEVER FIRED** | crossed at ~13:05:30Z. Same — no event. |
| **US-216 TRIGGER stage (VCELL ≤ 3.45V) → systemctl poweroff** | ❌ **NEVER FIRED** | crossed at ~13:10:30Z. Pi went silent ~10s later — too fast for real `systemctl poweroff` (typical 5-15s, with shutdown events streaming to journal the whole way). |
| **MAX17048 SOC% calibration** | ❌ **STILL BROKEN** | At drain start: VCELL=4.139V (~95% real charge) reported as SOC=94% (close). At drain end: VCELL=3.416V (~3-5% real charge) reported as SOC=63% (off by ~58 points). The drift is non-linear and gets worse near depletion — exactly when accurate SOC matters most. **This validates the Sprint 19 US-234 SOC→VCELL trigger source change** (correct call; SOC% is unusable as ladder-trigger source on this hardware). |

## 4. Architectural diagnosis

```
Wall power removed
  │
  ▼
UpsMonitor ──✅──> PowerMonitor.onPowerSourceChange callback
                        │
                        ├──✅──> writes 3 rows to power_log (transition + state)
                        │       (transition_to_battery, power_saving_enabled, battery_power)
                        │
                        ├──✅──> updates display state machine ("Battery" indicator)
                        │
                        └──❌──> ??? VCELL-decline monitor never starts
                                       │
                                       ▼
                            VCELL drops 4.14 → 3.42 over 14 min
                                       │
                                       ▼
                            ❌ no WARNING fired at 3.70V
                            ❌ no IMMINENT fired at 3.55V  
                            ❌ no TRIGGER fired at 3.45V
                                       │
                                       ▼
                            Buck dropout at ~3.36V → hard crash
                                       │
                                       ▼
                            EXT4 orphan cleanup on next boot
```

**The transition path works.** The **decline-monitoring path** (the part that watches VCELL after BATTERY state is entered, and fires staged shutdown when thresholds are crossed) **never engages**.

I don't know exactly where the gap is in the code. Likely candidates Rex can investigate:

- **Hypothesis A**: the staged-shutdown logic from US-216 was written but never wired to the new PowerMonitor callback chain that US-243 introduced. So PowerMonitor knows we're on battery but doesn't poll VCELL or compare to thresholds.
- **Hypothesis B**: VCELL polling is happening (the drain monitor proves MAX17048 is being read) but the threshold-comparison logic lives in a different module that isn't subscribed to the polling loop.
- **Hypothesis C**: the thresholds are being checked but the action ladder (`systemctl poweroff` at TRIGGER) calls into a path that itself is dead (similar to the pre-US-243 `power_log` write path situation).

Drain 5's empty staged-shutdown trace can't distinguish A/B/C — needs code audit.

## 5. Sprint 21 P0 candidate — the actual fix

**Story sketch (Rex sizes precisely):**

> **US-XXX (P0): US-216 staged shutdown DOES NOT FIRE during real drain — wire VCELL-decline monitor to PowerMonitor stage transitions**
>
> **Symptom**: Across 5 drain tests (Sessions 6, Sprint 17 deploy, Sprint 18 deploy x2, today's post-Sprint-20), the Pi has hard-crashed at the LiPo discharge knee (~3.36V). PowerMonitor correctly detects wall-out and writes transition rows to `power_log`, but the staged-shutdown stages (WARNING/IMMINENT/TRIGGER per US-234 thresholds) never fire — no rows in `power_log` for the stages, no `systemctl poweroff` event in journal, EXT4 orphan-cleanup smoking gun on every boot.
>
> **Acceptance criteria**:
> 1. Drain Test 6 captures rows in `power_log` for `WARNING` (VCELL ≤ 3.70V), `IMMINENT` (VCELL ≤ 3.55V), and `TRIGGER` (VCELL ≤ 3.45V) stage transitions
> 2. Drain Test 6 produces a clean `systemctl poweroff` event in journald between TRIGGER firing and Pi going silent
> 3. Drain Test 6 boot trail shows **no EXT4 orphan cleanup** (the smoking-gun-of-hard-crash) and **no journal corruption**
> 4. The `last reboot` output on next boot shows a clean shutdown record, not a `crash` record
> 5. Tests in `tests/pi/power/` cover the VCELL-decline → stage-transition → action-ladder path via mocking

> **Drill protocol** (CIO + Spool, post-deploy validation):
> - CIO unplugs Pi from wall
> - Spool's `ups_drain_monitor.sh --cadence 10` watches VCELL/SOC every 10s
> - Spool's parallel journal-tail captures stage events as they fire
> - Wait for `systemctl poweroff` event in journal (expected ~14 min post-unplug given prior trace data)
> - Verify Pi goes silent within 5-15s of TRIGGER stage firing (graceful shutdown latency, not buck-dropout latency)
> - CIO replugs, Spool checks boot trail for clean-shutdown indicators
>
> **Sources/preconditions**:
> - This note + drain test 5 trace at `offices/tuner/drills/2026-05-01-drain-test-5-post-sprint20.log`
> - Sprint 19 US-234 (SOC→VCELL trigger source change) — already shipped
> - Sprint 20 US-243 (PowerMonitor → power_log activation) — already shipped, validated transition rows
> - Pi `power_log` table — schema is barebones (id, timestamp, event_type, power_source, on_ac_power); may need extension to capture VCELL at time of stage transition for forensics
>
> **Sizing**: M (probably). Could be S if Hypothesis A is correct (the wiring exists but a callback isn't subscribed). Could be L if Hypothesis C is correct (whole action ladder needs reimplementation).

## 6. Sprint 21 secondary candidate — wake-on-power verification

**CIO's follow-up question after seeing the drain test result:**

> Once US-216 finally fires graceful `systemctl poweroff`, does the Pi automatically wake up when wall power returns? Or does it need a button press?

This matters because in the post-B-043-wiring production scenario:
1. Key-OFF → Pi loses wall power (accessory-line cuts)
2. Pi runs on UPS battery for some time
3. US-216 fires staged shutdown → `systemctl poweroff`
4. Pi sits in halt state on UPS battery (could be hours, days)
5. Key-ON → wall power returns
6. **Pi MUST auto-boot** — there's no operator at the car to press a button

**Quick analysis I did from CIO conversation today:**

Pi 5 bootloader config controls this via `POWER_OFF_ON_HALT`:

| Setting | Behavior |
|---|---|
| `POWER_OFF_ON_HALT=0` (default; **chi-eclipse-01 currently has this**) | `systemctl poweroff` halts SoC; PMIC stays alive watching power state. External power transition triggers boot. **Auto-wakes.** ✅ |
| `POWER_OFF_ON_HALT=1` (deep sleep) | After `systemctl poweroff`, board needs physical button OR full power-cycle (loss + return) to boot. **Does NOT auto-wake on power return alone.** ❌ |

Confirmed via `sudo rpi-eeprom-config` on chi-eclipse-01: the setting is not present (which means it uses the default = 0). That's the **right** config for our use case.

**But this hasn't been tested end-to-end** because all 5 drain tests crashed before getting to the graceful-poweroff state. We've never had a clean halt → power return → boot cycle to verify.

**Story sketch:**

> **US-YYY (P0 in Sprint 21, paired with the US-216 fix story): wake-on-power verification post-graceful-shutdown**
>
> **Acceptance criteria**:
> 1. Drill protocol (executable independently of US-216 fix, before/after either way):
>    - `ssh chi-eclipse-01 sudo systemctl poweroff`
>    - Wait 30s for clean halt
>    - CIO unplugs Pi from wall
>    - Wait 30s
>    - CIO plugs Pi back into wall
>    - **Acceptance**: Pi auto-boots without operator pressing the power button. Verifiable by Spool's continuous ping monitor logging UP transition within ~75s.
> 2. If drill #1 fails: `sudo rpi-eeprom-config --edit` to verify/enforce `POWER_OFF_ON_HALT=0`. Document config in `deploy/` (deploy-pi.sh should set/verify this). Re-run drill.
> 3. **Coupled drill** (after US-216 fix lands): drain test → graceful shutdown → wall-return → auto-boot. End-to-end production loop validated in one drill.
>
> **Sizing**: S. The drill is mechanical. The risk is config drift between deploys (an `eeprom-config` setting can be modified out-of-band without anyone noticing) — argues for the deploy script verifying the setting on every deploy.
>
> **Note for Rex**: This story is testable independently of the US-216 fix. Could land first as confidence-building.

## 7. Other observations from drain test 5

- **MAX17048 ModelGauge SOC% drift was severe** at low VCELL: reported 63% at 3.416V (real LiPo curve places that closer to 3-5%). The chip's "learn" period after a discharge cycle is ~minutes; post-recharge to 4.20V it reported 64% (should be ~95-100%). The chip's calibration is genuinely broken on this hardware. **Sprint 19 US-234's SOC→VCELL trigger source change was the right call** — this drain test reaffirms it.
- **Drain monitor's `EXTERNAL` PowerSource string was stale** — it kept showing `EXTERNAL` even during the drain. That's a bug in `offices/tuner/scripts/ups_drain_monitor.sh` (probably reads from a config file, not live state). My script, my fix to make later. Not blocking anything.
- **Display dashboard size** is on the radar (CIO commented it occupies only a small fraction of HDMI canvas during this drill). Captured in an earlier exchange — Sprint 21+ design grooming candidate, separate from this note.

## 8. Action items for you (PM lane)

1. **File the US-216 fix story for Sprint 21** (P0). The story sketch in §5 above is ready to drop into Rex's pickup queue. Coordinate with him on which Hypothesis (A/B/C) needs investigating first — that determines sizing.
2. **File the wake-on-power drill story for Sprint 21** (P0, paired with #1). The story sketch in §6 above. The drill is mechanical (5 minutes plus boot wait).
3. **Optional**: file a TD against the existing US-216 implementation noting that "transition logging fired correctly but stage transitions never engaged" — useful retro material for the upcoming fix. Could also be a closing note in the existing US-216 story if it's still open.

## 9. Action items for me (Spool lane)

- Update `MEMORY.md`: drain test count is now 5/5 hard crashes (was 4/4 in my prior consolidated note). Update Sprint 19 P0 ladder to reflect that US-243 transition-logging is now confirmed working but US-216 stages still don't fire.
- Add Drain 5 to drain-test history in `knowledge.md` (drain durations: 23:49 / 14:26 / 10:14 / 10:02 / 14:35 — pattern: 10-15 min on battery before knee).
- Capture the dashboard sizing design note as a Sprint 21+ design grooming candidate (separate inbox note when I close out today's session).

---

— Spool

## Sources / inputs

- `offices/tuner/drills/2026-05-01-drain-test-5-post-sprint20.log` (143 lines, 14:35 of trace, 10s cadence)
- chi-eclipse-01 journal boot 0: EXT4 orphan cleanup + journal corruption (smoking gun)
- chi-eclipse-01 journal boot -1: full pre-shutdown trace (no staged-shutdown events)
- chi-eclipse-01 `obd.db power_log` (6 rows total: 3 from earlier flip drill + 3 from this drain — all transition-only, no stages)
- chi-eclipse-01 `sudo rpi-eeprom-config` (POWER_OFF_ON_HALT not set → defaults to 0, auto-wake on power return)
- 4 prior drain test write-ups (Session 6 / Sprint 17 deploy / Sprint 18 deploys x2)
- `offices/pm/inbox/2026-04-29-from-spool-sprint19-consolidated.md` (the Sprint 19 P0 ladder this note updates)
- `offices/pm/inbox/2026-04-29-from-spool-inverted-power-drill-findings-and-us235-correction.md` (the corrected UpsMonitor diagnosis — still valid; this note adds new failure mode info)
