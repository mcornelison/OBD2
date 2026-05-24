# Finding C — In-Car Hard-Crash Pattern + Power-Topology Question
**Date**: 2026-05-20
**From**: Spool (Tuning SME)
**To**: Atlas (Senior Solutions Architect)
**Priority**: Safety-Critical (project-blocking; not engine-safety)
**cc**: Marcus, Tester, Ralph (CIO authorized this escalation)

---

## Context

CIO ran a deliberate IRL "graceful-shutdown" verification test this evening (2026-05-20). His stated timeline: key on at 17:05 CDT (Pi boots, OBD2 screen appears), engine on at 17:06, engine off at 17:07 with **key fully off** (confirmed when I asked), then he watched the Pi "power down gently" and "the UPS go dark a few seconds later."

I pulled both server (`obd2db` on chi-srv-01) and Pi-local (`obd.db` on chi-eclipse-01) telemetry for the test window. **The Pi instrument disagrees with the visual observation, and the pattern is consistent with — and broader than — Session 17's brownout finding from drives 17/18.**

This note is the consolidated evidence + an open topology question for you.

---

## Evidence

### 1. The "5:05 boot" was not a Pi boot

`journalctl --list-boots` tail (Pi-local; authoritative kernel boot record):

```
 -2  903be0ce... Wed 2026-05-20 14:28:53 CDT  Wed 2026-05-20 16:12:50 CDT
 -1  61580bb2... Wed 2026-05-20 16:12:50 CDT  Wed 2026-05-20 17:26:35 CDT
  0  9b53b90d... Wed 2026-05-20 17:24:26 CDT  (current)
```

The test boot (`61580bb2`) started at **16:12:50 CDT** — 53 min before CIO turned the key. The HDMI display lighting up at 17:05 (when 12 V acc came live) is what CIO saw; the Pi itself had been running for nearly an hour. NTP-jitter at next boot makes `9b53b90d` first-entry timestamp appear 2 min before `61580bb2` last entry — not a real overlap.

### 2. Drive 19 captured cleanly (engine telemetry side)

Server `connection_log` + `realtime_data`:

- `drive_start` 22:06:42 UTC = 17:06:42 CDT (drive_id=19)
- `drive_end` 22:07:58 UTC = 17:07:58 CDT
- 130 rows of full engine telemetry across the 76-sec idle. Clean K-line cadence.

OBD pipeline + DriveDetector + sync all behaved correctly for the brief engine-on window.

### 3. Pi `power_log` during the test — zero battery transitions

```
21:13:27Z  ac_power    ← heartbeat during boot 61580bb2
22:25:02Z  ac_power    ← heartbeat ~1 min before crash
```

**No `transition_to_battery`. No `battery_power`. No `STAGE_*` events.** The HAT never reported a transition to battery, so the V0.27.15 sequencer had no trigger to react to. **Same exact signature as Session 17 drives 17/18.**

### 4. Pi `startup_log` — new boot reports the test boot as crashed

```
boot_id               9b53b90dacae41169d0ba4089c4b5b0d
prior_boot_clean      0
prior_boot_last_stage RUNNING
prior_boot_reason     crashed_during_operation
recorded_at           2026-05-20T22:24:30Z
```

No `CLEAN_COMPLETE`, no graceful-shutdown marker in the prior boot's journal — abrupt cutoff at 17:26:35 CDT. Pi instrument classifies the observed "gentle power-down" as a **hard crash**.

### 5. `battery_health_log` — sequencer ladder never fired

No new drain row. Last entry is still #28 from 2026-05-16. Consistent with #3 — no battery transition seen, so no drain event opened.

### 6. The 19-min BATTERY_V trail at 12.5 V flat

Server `realtime_data` shows 495 rows of **only** `BATTERY_V` at flat **12.5 V** from 22:08:00 → 22:26:40 UTC (i.e., 5:08 → 5:26 CDT — 19 minutes after CIO's stated engine-off-with-key-off at 5:07).

This is the headline anomaly. CIO has confirmed key was fully off at 17:07. Either:

- (a) The OBD pipeline kept polling PID 0x42 and the 4G63 2G ECU stayed awake for 19 min after key-off (some DSM ECUs have a key-off-hold timer; 19 min is on the long end of plausible), and the Pi was running on UPS battery the whole time — **but power_log shows zero battery transitions, which contradicts this**.
- (b) The car's 12 V supply to the Pi's buck **did not actually drop at key-off** — buck input stayed live for 19 min, HAT had no reason to switch, ECU stayed awake on a still-live 12 V bus. **This is consistent with all observed evidence.** Implication: whatever 12 V circuit feeds the Pi is NOT key-switched the way we assumed.
- (c) Some hybrid (sticky relay, intermittent contact) — possible but harder to reconcile with 19 min of steady 12.5 V reading.

I cannot disambiguate from telemetry alone. **A multimeter at the buck input during a key-off would settle it in 5 sec.** This is the load-bearing topology question I'm bringing to you.

### 7. Twelve boots today — all `crashed_during_operation`

```
2026-05-20T04:59:42Z  54aefa5b...  TRIGGER_ROW_WRITTEN   wedged_before_poweroff
2026-05-20T05:37:57Z  4544655804...  RUNNING            crashed_during_operation
2026-05-20T05:43:12Z  12e5321d1c...  RUNNING            crashed_during_operation
2026-05-20T14:15:21Z  27a61b1ab3...  RUNNING            crashed_during_operation
2026-05-20T14:42:36Z  6813ff2bdd...  RUNNING            crashed_during_operation
2026-05-20T14:49:08Z  26bbad9e53...  RUNNING            crashed_during_operation
2026-05-20T18:24:24Z  a3a12bb38d...  RUNNING            crashed_during_operation  ← Session 17 drive 17
2026-05-20T18:30:29Z  e8f8cf22dd...  RUNNING            crashed_during_operation  ← between Session 17 drives
2026-05-20T19:13:04Z  fd0c5d289d...  RUNNING            crashed_during_operation  ← Session 17 drive 18
2026-05-20T19:28:57Z  903be0ce30...  RUNNING            crashed_during_operation  ← Session 17 accidental power-pull
2026-05-20T21:12:55Z  61580bb2db...  RUNNING            crashed_during_operation  ← test-boot ancestor
2026-05-20T22:24:30Z  9b53b90dac...  RUNNING            crashed_during_operation  ← today's test crash
```

This is not an isolated test event. The pattern was present across bench/idle/wall-power activity all day, including periods when no driving was happening. **The bench-Cycle-A clean signature you certified Sprint 39 against is not what the Pi actually experiences in real operation.**

### 8. Bonus — the `wedged_before_poweroff` one-off

The earliest boot of 2026-05-20 (recorded at 04:59:42Z = 2026-05-19 23:59:42 CDT) has:

```
prior_boot_last_stage  TRIGGER_ROW_WRITTEN
prior_boot_reason      wedged_before_poweroff
```

**The sequencer did fire once yesterday** — got as far as writing the TRIGGER row, then wedged before `systemctl poweroff` completed. Single occurrence, doesn't match today's pattern, but it's a distinct failure mode from `crashed_during_operation` and you should know about it.

---

## Recommendation

### What this does NOT change

- **V0.27.15 sequencer architectural correctness on bench** — your 3/3 (possibly 5/5) Cycle-A IRL findings stand. The sequencer works as designed when given the trigger surface it expects.
- **`POWER_OFF_ON_HALT=1` resolution of Finding B** — unaffected.
- **SSOT `PowerSourceProvider` + retired ladder lesson preserved in §10.6** — unaffected.
- **Engine-side data**: Drive 19 captured cleanly. No engine concern.

### What this DOES change

The V0.27.15 sequencer assumes the HAT will report a battery transition when external power is lost. **In-car, the HAT does not see its input drop** — at least not in any of the conditions exercised today (12 boots). Without that signal, the sequencer has no trigger and the Pi continues running on what appears to be live 12 V until *something else* eventually crashes it without warning.

This is a hardware/topology gap, not a sequencer gap. **Sequencer tuning will not close it.**

### Proposed sequencing

1. **CIO multimeter check** at the Pi's buck input during a key-off cycle (5 seconds of measurement). This single observation distinguishes (a)/(b)/(c) above and tells us whether the Pi is on always-on, switched, or some intermittent path.
2. **Pending #1, defer F-008/F-011/F-012 regression-manifest bump** beyond the preliminary HOLD I already filed with Tester. The fact that all 12 boots today were `crashed_during_operation` (including bench/idle periods) suggests the platform's "graceful shutdown" claim is currently unsupported by Pi-side evidence regardless of engine state. Need the topology answer before any regression-manifest update.
3. **Chain merge gate**: the chain-unblock candidate per current PM status was predicated on the IRL acceptance pass. That IRL acceptance was bench Cycle-A on wall power. **In-car the surface is different**, and today's data is the first hard evidence of that gap. Your call on whether this changes chain merge status.
4. **BL-018 empirical tuning still owed** to you when the rested-pack + chi-srv-01-reachable + SyncTask-real-work conditions land. Today did not produce a drain row. Unblocked by topology resolution, not by anything I'm holding.

### Why this is not just buck-reseat

CIO's working hypothesis from Session 17 was a loose 5 V buck (mechanical ghost). Today's data argues against that read: a loose buck would produce intermittent transitions visible in `power_log`, and we see **zero battery events** all day across 12 boots in varied physical contexts (bench wall power, in-car driving, in-car idle, manual power-cycle). The signature is too consistent for a mechanical intermittent — it looks more like the HAT's PG-pin signal is wired or sensed in a way that doesn't reflect the actual upstream-power state for the conditions the car produces.

This is the topology question I flagged to you 2026-05-15 (exact UPS HAT model/vendor + power-good pin + auto-on register) — still open per Marcus's last note. **The data is now telling us this is load-bearing, not a nice-to-know.**

---

## Sources

- **Pi `obd.db`** (`/home/mcornelison/Projects/Eclipse-01/data/obd.db`): `startup_log` (12 rows today), `power_log` (21 rows since 22:00Z 2026-05-20), `battery_health_log` (no new row since drain #28 on 2026-05-16).
- **Server `obd2db`** (chi-srv-01): `connection_log` (drive 19 start/end), `realtime_data` (130 rows for drive 19 + 495 rows BATTERY_V@12.5V NULL-drive trail), `sync_history` (clean syncs through 22:26:41Z then silence).
- **`journalctl --list-boots`** (Pi-local, authoritative): boots `903be0ce` / `61580bb2` / `9b53b90d` timestamps.
- **Session 17 context**: `offices/tuner/sessions.md` Session 17 brownout-finding-HELD block (same signature, 3 reboots, identical zero-battery-event pattern).

---

## What I am asking you for

1. **Acknowledge receipt + your read** on whether this changes chain merge status or stays orthogonal (your design call).
2. **Direction on whether you want me to file the topology question to CIO via Marcus directly**, or whether you'd prefer to route it (lane discipline — your call which orchestration path).
3. **Whether you want a Cycle-D bench variant designed** to simulate the in-car PG-pin behavior (force the HAT to think input is present while pulling actual power) — could pre-empirically test the topology hypothesis without waiting for CIO's next drive.

I'm on-demand for whatever direction this goes.

— Spool
