# Drill: Thermostat Warmup + Engine-Restart-With-Pi-Running
**Date**: 2026-04-20
**Operator**: CIO (Michael)
**Reviewer**: Spool (post-drill)
**Conditions**: Pi on wall power (not car accessory). Chicago ambient ~50-65°F spring.
**Duration**: ~22 minutes total
**Gates being tested**:
1. I-016 disposition — does coolant reach ≥180°F (82°C) at sustained idle?
2. EngineStateMachine — does drive_id increment correctly when Pi stays up across engine restart?
3. Pre-crank IAT validates US-206 ambient-proxy concept

---

## Before you walk to the car

- [ ] Confirm Pi is running: SSH works, `sudo systemctl status obd-collector` (or equivalent) shows active
- [ ] Check rfcomm binding: `ls /dev/rfcomm0` should exist
- [ ] Write down current wall-clock time (this is the `--since` slice boundary for my review)
- [ ] Write down approximate ambient air temp (phone weather, outdoor thermometer — F or C, either works)
- [ ] OBDLink LX adapter in hand
- [ ] Notepad, phone, or timer for phase transitions

---

## Phase A — Pre-crank observation (0-2 min)

1. Plug OBDLink LX into OBD port under dash
2. Confirm **solid blue LED** on adapter (connected to Pi, not discoverable)
3. Turn ignition key to **ON** (accessory position — DO NOT crank yet)
4. **Wait 60-90 seconds.** Engine off, ECU awake, Pi polling.

**Expected**:
- Pi queries succeed (ECU responds with key-on, no engine)
- RPM = 0, coolant = ambient-soaked, IAT ≈ ambient
- State machine stays in UNKNOWN (no RPM ≥250)

**What this proves**: pre-crank IAT ≈ ambient (US-206 validation without US-206 shipped yet)

---

## Phase B — Cold start + sustained idle (2-17 min) — THE MAIN SHOW

1. At ~90s mark: **crank the engine**, start normally
2. Let it idle. Timer starts now for the 15-minute requirement.
3. **DO NOT REV. DO NOT DRIVE. DO NOT TOUCH THE GAS.** Pure sustained idle.
4. Run **≥15 minutes continuously** (use timer; below 15 min is not conclusive for I-016)
5. **If anything feels wrong** — rough idle, check engine light, unusual smell, smoke, knocking — **abort immediately and text Spool**

**Expected state transitions** (what Pi will log):
```
UNKNOWN → CRANKING      (RPM crosses 250 during starter)
CRANKING → RUNNING      (RPM crosses 500 as engine catches)
drive_id = N minted
... holds RUNNING for 15+ minutes ...
```

**Success criteria**:
- Coolant climbs to ≥180°F (82°C) by end of 15 min → I-016 closes benign ✅
- Bonus: coolant reaches 190-200°F (full op temp) → thermostat + cooling fully healthy
- drive_id remains constant throughout (no fragmentation)

**Failure signal**:
- Coolant plateaus <180°F after 15 min → hardware escalation (I-016 becomes a cooling-system audit story)

---

## Phase C — First shutdown (17-18 min)

1. Turn ignition key **OFF**. Engine stops.
2. **LEAVE OBDLINK PLUGGED IN.** Do not unplug, do not disconnect.
3. Wait **60 seconds** (2x the 30s KEY_OFF debounce — no ambiguity)

**Expected**:
- RPM drops to 0, speed already 0
- After 30s of continuous RPM=0 AND speed=0 → RUNNING → KEY_OFF
- drive_id = N closed

---

## Phase D — Engine restart — THE EDGE CASE YOU ASKED ABOUT (18-22 min)

1. After the 60s of engine-off, turn key to **CRANK**, restart engine
2. Let it idle **3-5 minutes** (don't need long — we're testing the transition, not re-warming)
3. Then turn key **OFF** again

**Expected state transitions**:
```
KEY_OFF → CRANKING      (RPM crosses 250)
drive_id = N+1 minted   ← THE KEY RESULT
CRANKING → RUNNING
... hold 3-5 min ...
RUNNING → KEY_OFF       (after 30s of RPM=0)
drive_id = N+1 closed
```

**Success criteria**: two distinct drive_ids (N and N+1) from one continuous Pi uptime. N+1 > N (monotonic).

**Failure signals**:
- drive_id does NOT increment → state machine bug (KEY_OFF debounce didn't fire)
- drive_id increments mid-run during Phase B → state machine bug (false KEY_OFF during idle)

---

## Phase E — Clean shutdown (22+ min)

1. After engine off + ~60s KEY_OFF firing on Drive N+1
2. Unplug OBDLink
3. Text Spool:
   - Phase A start wall-clock time
   - Approximate ambient temp
   - Any anomalies noticed

---

## What Spool will do with the data

1. Run `offices/tuner/scripts/review_run.sh --since "<Phase A start>"` against Pi + server DBs
2. Grade:
   - Coolant trajectory + I-016 disposition (benign vs escalate)
   - Drive_id transitions (expect exactly 2 distinct, N and N+1)
   - Pre-crank IAT vs your reported ambient
   - Full cold-start → warmup engine health re-grade (way richer than Session 23's 23s slice)
3. Drop findings in `offices/tuner/sessions.md` + send any CRs via inboxes

---

## What this drill does NOT capture (known gaps, fine)

- No `drive_summary` row (US-206 pending) — pre-crank IAT lives in realtime_data only
- No `dtc_log` rows (US-204 pending) — if MIL lights up, capture codes manually via adapter software
- 352K pre-existing benchtest rows in DB (US-205 truncate pending) — Spool's review script filters by time window, no contamination

---

## Abort criteria (text Spool immediately + shut down)

- Check engine light illuminates mid-drill
- Unusual smoke, smell, sound
- Coolant temp exceeds 220°F at any point (danger threshold — very unlikely at idle but absolute hard stop)
- Any behavior that feels "off"

Safety first. Data second.

— Spool
