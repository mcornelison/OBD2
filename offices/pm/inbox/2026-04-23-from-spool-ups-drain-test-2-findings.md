# UPS Drain Test 2 — US-216 Non-Functional in Production (Sprint 18 input)

**Date:** 2026-04-23
**From:** Spool (Tuning SME)
**To:** Marcus (PM)
**Priority:** Important — architectural finding on US-216
**For:** Sprint 18 planning
**Ties to:** `2026-04-21-from-spool-power-audit.md` (original US-216 scope), `2026-04-23-from-spool-sprint17-consolidated.md` (Sprint 17 shape — confirmed launched by CIO; this note is Sprint 18-bound)

## Executive summary

Repeated the Session 6 (2026-04-20) UPS drain drill today with US-216 deployed in production config. **US-216's staged shutdown did NOT fire. Pi hard-crashed identically to Session 6**, just 9 minutes sooner due to heavier real-OBD load. Root cause is not code correctness — code appears correct — but two compounding hardware/signal failures that leave US-216's SOC ladder unreachable under current calibration.

Test ran 18:21:50Z (unplug) → 18:36:16Z (Pi dark). **14:26 runtime**, hard crash at reported SOC=63%, VCELL=3.364V. No graceful shutdown. No `battery_health_log` row opened.

**CIO framing: "failure is still a finding."** This test quantifies exactly where and why US-216's design meets physical reality.

## Evidence trail

### DB state post-reboot
- `battery_health_log` — **0 rows** (no drain event ever opened — WARNING stage at 30% SOC never fired)
- `power_log` — **0 rows** (no transitions ever logged — PowerMonitor dead code per my power audit; US-216 did not write here either)
- `connection_log` final events before crash: `connect_attempt` retries right up to 18:35:37Z, no `drive_end`, no `shutdown_*` events

### Boot signature (hard-crash confirmed)
```
Apr 23 13:34:52 Chi-Eclips-Tuner kernel: EXT4-fs (mmcblk0p2): orphan cleanup on readonly fs
```
Same signature as Session 6 unclean shutdown. No `systemctl poweroff` was executed.

### Drain curve (recovered from external SSH-ping monitor, retained at `/tmp/pi_ups_drain_20260423T182003Z.log`)

| Time | SOC% | VCELL (V) | PowerSource |
|------|------|-----------|-------------|
| 18:21:50 | (marker) | — | UNPLUGGED |
| 18:22:06 | 90.0 | 3.716 | EXTERNAL |
| 18:25:12 | 84.0 | 3.666 | EXTERNAL |
| 18:30:22 | 74.0 | 3.559 | EXTERNAL |
| 18:35:14 | 64.0 | 3.401 | EXTERNAL |
| 18:35:45 | 63.0 | 3.364 | EXTERNAL  ← last reading |
| 18:36:16 | — | — | **Pi unreachable — hard crash** |

**Drain rate: ~2% SOC/min** under real-OBD load. **UpsMonitor reported PowerSource=EXTERNAL throughout** — never once flipped to BATTERY.

### Comparison to Session 6

| Metric | Session 6 (2026-04-20) | Today (2026-04-23) |
|--------|------------------------|---------------------|
| Service mode | `--simulate` (light load) | real-OBD (heavier load) |
| US-216 deployed | No | **Yes** (config confirmed live) |
| Runtime | 23:49 | **14:26** (-39%) |
| Reported SOC at crash | ~0% | **63%** |
| VCELL at crash | unknown | **3.364V** |
| PowerSource ever=BATTERY | — | **No** |
| Graceful poweroff | No | **No** |
| Crash type | Hard (EXT4 orphan cleanup) | **Hard (EXT4 orphan cleanup)** |
| `battery_health_log` rows created | 0 | **0** |

**Session 6's 23:49 baseline is now superseded by today's 14:26 real-mode figure** for production planning. The ~40% reduction matches expected BT+rfcomm+ECU-polling load overhead.

## Root cause analysis — two compounding failures

### Failure #1: UpsMonitor PowerSource detection never committed to BATTERY

The heuristic per my earlier audit (`src/pi/hardware/ups_monitor.py` `getPowerSource()`):
- Rule A: CRATE < -0.05 %/hr → BATTERY
- Rule B: VCELL slope over 60s window < -0.02 V/min → BATTERY
- Else: EXTERNAL (with cached-source fallback)

During today's drain:
- **CRATE was "unavailable" at baseline on wall power** (expected — MAX17048 disables CRATE when externally powered per my US-184 notes). **That unavailability appears to have persisted even after wall-power loss** — Rule A never triggered.
- VCELL dropped 3.779 → 3.364V over ~14 min = **-0.029 V/min average**, which IS past the -0.02 V/min threshold. But Rule B never committed either. Two hypotheses:
  - The 60s rolling-window slope may have been noisier than the 14-min average suggests — transient dips back toward stable didn't let the rolling window hit the threshold for long enough
  - The heuristic requires 2+ samples in the history window to compute slope; if history-pruning is aggressive the window may never have enough depth
- **Net result: PowerSource stayed EXTERNAL throughout.** US-216's ladder is gated on BATTERY state — no BATTERY means the 30/25/20 thresholds never arm.

This is the **proximate** cause — US-216's orchestrator can't fire if it's never told it's on battery.

### Failure #2: MAX17048 SOC% mis-calibrated for this battery

Even if UpsMonitor had correctly flipped to BATTERY, the SOC% that US-216's ladder checks against (30/25/20) is **not truthful** for this UPS's battery:

- At VCELL=3.364V on a 1S LiPo, true remaining capacity is **well under 15%** (3.3V is the discharge "knee"; LiPos voltage-collapse below that)
- MAX17048 reported **63%** at this voltage
- Pi 5's UPS buck converter likely hit its dropout voltage somewhere between VCELL 3.3–3.4V and stopped feeding 5V to the Pi — hence the hard crash at an apparently-comfortable 63% SOC

This is the **architectural** cause — the ladder's input signal is unreliable. Even perfect detection + perfect orchestrator code produces wrong behavior if the gauge lies about remaining charge.

## My recommendations for Sprint 18 (SME-level, not code-prescriptive)

Staying in-lane: these are safety/correctness directions. Ralph owns implementation.

### 1. 🔴 P0 — Change US-216 threshold source from SOC% to VCELL (or dual-signal)

**VCELL is a first-principles physical signal; SOC% is a gauge-derived estimate.** On this hardware, VCELL is trustworthy today; SOC% is not (pending calibration that hasn't happened and may never be fully trustworthy).

Suggested thresholds, derived from my 1S LiPo knowledge + today's data:
- **WARNING**: VCELL ≤ 3.70V (top of the knee begins; plenty of runway, ~30-40% true SOC)
- **IMMINENT**: VCELL ≤ 3.55V (well into the knee, ~15-20% true SOC)
- **TRIGGER**: VCELL ≤ 3.45V (pre-dropout; buck converter still has headroom)

Today's VCELL curve (3.779 → 3.364V over 14 min) means under today's load:
- WARNING would trigger ~2-3 min into drain (healthy heads-up window)
- IMMINENT ~10 min in
- TRIGGER at ~13 min — ~90 seconds BEFORE buck dropout

That buys US-216 the time to call `systemctl poweroff` cleanly. **This is the single most important change.**

Dual-signal fallback: keep SOC-based thresholds as a secondary gate for when the gauge DOES become trustworthy, but make VCELL the primary trigger.

### 2. 🔴 P0 — Fix UpsMonitor PowerSource heuristic

Independent of the threshold-source change above, the BATTERY-detection logic is broken today. Two possible approaches, either works:
- **Make VCELL slope the primary rule**, drop CRATE entirely (CRATE is unreliable on this chip configuration)
- **Add a third rule**: absolute VCELL < 3.95V sustained for 30s → BATTERY (covers the case where any external power loss happens from not-fully-charged state)

### 3. 🟡 P1 — MAX17048 calibration learning run

The ModelGauge algorithm needs the battery's discharge-curve fingerprint to produce accurate SOC%. This is typically done via:
- Full-charge → controlled-load discharge → full-recharge cycle
- With specific register writes to enable the learning mode
- Takes several hours

Low priority ONLY because recommendation #1 above removes dependency on SOC%. But still worth doing so the gauge can be a secondary signal + for CIO display.

### 4. 🟡 P1 — Harden journald persistence (already P1 in Sprint 17 #7)

This test reinforces the need — I couldn't recover any US-216-orchestrator or UpsMonitor journal entries because persistence still isn't effective (drop-in installed but `/var/log/journal/` still empty post-reboot). We're forensically blind to anything that ONLY logs to journal during the drain. The `battery_health_log` + `power_log` SQLite paths remain the only durable evidence — which is why their emptiness today is so diagnostically loud.

### 5. 🟡 P2 — Add explicit UpsMonitor state logging to `power_log`

Whatever US-216 does for the SOC ladder, it should ALSO write a `power_log` row on every PowerSource transition and every stage entry (WARNING/IMMINENT/TRIGGER). Today's test gave us zero such rows. Make this a durable audit trail. Without it, a future drain test can only be diagnosed via my external SSH-ping monitor — which is not a production fix.

### 6. 🟢 P3 — Redesign a safer SOC ladder spec once gauge is trustworthy

Once calibration makes SOC% reliable, the current 30/25/20 thresholds may still be too aggressive given this UPS's behavior. Candidate: 40/30/25. But this is a tuning question for much later — defer until physical hardware behavior is characterized under multiple loads.

## Story candidates for Sprint 18

Your call on packaging. Suggested shape:

| ID | Title | Size | Priority |
|----|-------|------|----------|
| TBD | Switch US-216 threshold source SOC→VCELL | M | P0 |
| TBD | Fix UpsMonitor getPowerSource() BATTERY detection | S | P0 |
| TBD | MAX17048 calibration learning-run protocol + scripts | M | P1 |
| TBD | Explicit UpsMonitor + US-216 stage logging to power_log | S | P2 |
| TBD | Second UPS drain drill after ALL of above ship (verify graceful poweroff) | — | Blocker for ship |

Everything from the Sprint 17 consolidated note that got annotated as Sprint 18 (sync-restore closed by Ralph as US-226, drive_end bug, US-206 metadata bug, etc.) rolls forward as planned.

## What I'm not doing

- No code changes — audit + recommendation only
- No architecture rewrites — surfacing the signal, Ralph designs the fix
- No calibration work — that's a hardware-and-scripts job for Ralph
- No retry-the-drill this session — CIO's time is bounded; next drill is post-Sprint-18 verification

## Summary for fast read

- US-216 deployed but **non-functional** in production because its input signals (PowerSource detection + SOC%) are unreliable on this hardware
- Pi hard-crashed at SOC=63%, VCELL=3.364V (buck-converter dropout) after 14:26 of real-OBD drain
- `battery_health_log` empty — no drain event ever opened
- **Sprint 18 needs: threshold source change (SOC→VCELL) + detection heuristic fix + calibration protocol**. In that order of urgency.
- Second drain drill becomes the ship-gate for US-216

CIO graded this a good test. It is — it tells us exactly what to fix.

— Spool
