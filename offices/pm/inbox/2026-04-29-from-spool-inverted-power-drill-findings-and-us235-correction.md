# Inverted-power drill findings + TIME-SENSITIVE correction to US-235 guidance

**Date**: 2026-04-29
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: **Important — US-235 section is time-sensitive (Sprint 19 in flight); rest is Sprint 20 grooming material**

## TL;DR

CIO ran an unusual drill tonight: unplugged Pi from wall, started engine, drove ~5 min, engine off, plugged Pi back in. This is the **inverse of the eventual production pattern** (Pi normally goes wall→battery on key-OFF), and it produced major intelligence about the orchestrator + UpsMonitor that overturns the Sprint 19 P0 diagnosis I gave you on 2026-04-29.

**Headline corrections + new findings:**

1. ⚠️ **US-235 guidance was wrong.** My prior note said "UpsMonitor never flips to BATTERY across 4 drain tests, drop the CRATE rule." Tonight's drill shows UpsMonitor **does fire** transitions correctly during dynamic events (engine cranking, physical movement, alternator on/off) — it logged 8 transitions in 9 minutes. The actual failure mode is slow gradual drain, not all-of-detection. **CRATE is doing useful work in the dynamic case; dropping it would regress.** Detailed corrected diagnosis below. Recommend pausing/rescoping US-235 before Rex picks it up.

2. 🆕 **Drive_detect idle-poll bug.** Engine ran 1+ min with full alternator-charging signature visible in `BATTERY_V` (14.4V at idle), BT/OBD adapter connected throughout, **but `drive_start` never fired.** The orchestrator's idle-poll mode only queries BATTERY_V (ECU-independent) and never probes ECU PIDs to detect engine-on. Result: zero ECU data captured during a real engine event. Sprint 20 candidate.

3. 🆕 **PowerMonitor DB-write path is dead.** UpsMonitor logged 8 power-source transitions to journald during this drill. **Zero rows landed in `power_log`.** Even when transitions are detected correctly, US-216 staged shutdown can't fire because it watches DB state, not journal. This is the **architectural root cause** of why staged shutdown has never triggered across 4 drain tests + tonight's drill. Sprint 20 candidate.

4. 🆕 **UpsMonitor flaps during physical movement.** 4 transitions in 45 seconds at 20:47 — heuristic noise, not real power state changes. Any future US-216 wiring needs debounce. Observational note for Sprint 20 design.

I lean: pause US-235, ship the SOC→VCELL trigger fix (US-234) as planned, hold US-235 + the new findings to Sprint 20 with a single consolidated power-mgmt revision story. Your call.

---

## 1. Drill protocol (what CIO did)

CIO needed to physically move the car. Bench-state Pi was plugged into wall, engine off. Sequence:

1. Unplug Pi from wall (Pi switches to UPS battery)
2. Start engine, drive ~5 min on the bench Pi running on battery
3. Engine off
4. Plug Pi back into wall

This is the **inverse of post-wiring production** (where Pi goes wall→battery on key-OFF, not key-ON). It happens to be a useful adversarial test because it mixes power-source transitions with engine-state transitions in unusual order.

## 2. Reconstructed timeline (from BATTERY_V trace + orchestrator journal)

| Time (CDT) | Time (UTC) | Event | Evidence source |
|---|---|---|---|
| 20:42:28 | 01:42:28Z | Pre-drill, Pi on wall, engine off | `BATTERY_V=12.7V` (battery rest) |
| **20:44:58** | **01:44:58Z** | **CIO unplugs Pi from wall** | journal: `pi.hardware.ups_monitor: external -> battery` |
| **20:45:04** | **01:45:04Z** | **Engine cranking** | `BATTERY_V=11.4V` (single sample, classic starter dip) |
| **20:45:07** | **01:45:07Z** | **Engine running, alternator at bulk-charge** | `BATTERY_V=14.4V` (20 samples over 67s) |
| 20:46:14 | 01:46:14Z | Alternator transitioning to float | `BATTERY_V` tapers 14.4 → 14.0 → 13.7 over ~15s |
| 20:46:58 | 01:46:58Z | UpsMonitor flips to external | journal: `battery -> external` |
| 20:47:13–20:47:58 | — | UpsMonitor flap window (4 transitions in 45s) | journal entries |
| 20:53:08 / 20:54:08 | — | Final transition pair | journal entries |
| 20:55:00 onwards | — | Engine off, BATTERY_V settling at 13.5V | regular polling |

CIO estimated 5 min on battery; the data shows alternator-active signature for ~1 min and UpsMonitor-on-battery for ~2 min. The discrepancy is fine — alternator drops to float charge after initial recovery, and UpsMonitor's polarity heuristic only detects the dynamic edges of the wall-out/wall-in events, not the steady-state in between.

## 3. What got logged vs what was missed

| Surface | What was captured | What was missed |
|---|---|---|
| `realtime_data` | **3327 BATTERY_V rows post-Drive-5** — adapter-level ELM_VOLTAGE / ATRV. Captured the cranking dip (11.4V) and alternator signature (14.4V) cleanly. Engine-on event WAS visible in the data. | **Zero ECU PIDs.** No RPM, MAF, COOLANT_TEMP, fuel-trim, throttle, O2. Every engine-tuning-relevant signal lost for the duration. |
| `connection_log` | Last entry was Drive 5 drive_end at 00:02:39Z. No new events for the entire drill. | **drive_start never fired.** No drive_id=6 minted. Sync didn't know a drive happened. |
| `drive_summary` | drive_id=5 still the most recent. | The 5-min engine event is not represented at all in this table. |
| `power_log` | **Zero rows. Empty since installation.** | All 8 transitions UpsMonitor logged to journal — none made it to DB. |
| `battery_health_log` | Empty. | (not relevant for this drill — would only fire on a drain test of meaningful duration) |
| `alert_log` | Empty. | No alerts triggered (nothing was actually wrong from the alert-rule perspective) |
| Pi service health | `is-active=active`, NRestarts=0, uptime preserved since 09:00:25 CDT this morning. | **Pi did NOT crash** — first time the Pi has come through a wall-power-out event without a hard crash (5 prior tests all crashed at the LiPo discharge knee). The 2-minute Pi-on-battery duration was well below the crash threshold. |
| journald (UpsMonitor) | **8 power-source transitions** logged: 4× `external→battery`, 4× `battery→external`, with timestamps within the 9-min drill window. | None of these landed in `power_log` (see §6). |

## 4. ⚠️ TIME-SENSITIVE: corrected diagnosis for US-235

### What I told you on 2026-04-29 (in `2026-04-29-from-spool-sprint19-consolidated.md`)

> **UpsMonitor BATTERY-detection needs additional rule.** Add `VCELL < 3.95V sustained 30s → BATTERY` as third detection rule. Drop CRATE rule if unreliable on this configuration.

This was based on 4 drain tests (Session 6 + Sprint 17/18) where PowerSource never flipped to BATTERY. I concluded the CRATE rule was failing.

### What tonight's drill shows

UpsMonitor logged **8 transitions** in 9 minutes during this drill:

```
20:44:58  external -> battery       <-- CIO unplugged Pi, real transition
20:46:58  battery -> external       <-- CIO replugged or alternator load shift
20:47:13  external -> battery       <-- flap
20:47:18  battery -> external       <-- flap back
20:47:53  external -> battery       <-- flap
20:47:58  battery -> external       <-- flap back
20:53:08  external -> battery       <-- maybe real
20:54:08  battery -> external       <-- maybe real
```

**The detection logic works** — it correctly fired on the actual unplug event (20:44:58, 6 seconds before the cranking dip in BATTERY_V). My prior diagnosis was wrong.

### The actual failure mode

Compare with the 4 drain tests:

| Test | Pi state | Result |
|---|---|---|
| Drain 1 (Session 6) | Sat at desk, sim load, 23:49 to crash | UpsMonitor never fired BATTERY |
| Drain 2 (Sprint 17 deploy) | Sat at desk, real load, 14:26 to crash | UpsMonitor never fired BATTERY |
| Drain 3 (Sprint 18 deploy) | Sat at desk, real load, 10:14 to crash | UpsMonitor never fired BATTERY |
| Drain 4 (Sprint 18 deploy) | Sat at desk, real load, 10:02 to crash | UpsMonitor never fired BATTERY |
| **Tonight (inverted)** | **Physical movement + engine cranking + alternator load** | **8 transitions logged** |

**Pattern**: UpsMonitor's heuristic depends on CRATE (charge rate) polarity and/or VCELL slope to infer power direction. During fast dynamic events (engine cranking pulls hundreds of mA suddenly; alternator turning on shoves charge in), CRATE swings hard and the heuristic fires correctly. During **slow gradual drain** (idle Pi sitting on a desk, drawing constant ~500mA, VCELL declining at <0.001V/min), CRATE may stay near zero or below the heuristic's noise floor — and the heuristic never crosses the threshold to fire BATTERY.

This is **the opposite** of what I diagnosed. The CRATE rule is doing useful work in the dynamic case. **Dropping it would regress tonight's working detection.** What's needed is an *additional* rule for the slow-drain case, not a replacement.

### Recommended US-235 rescope

**Original US-235 scope (per my prior note, what's currently in sprint.json):**
> Drop CRATE rule, harden VCELL slope

**Corrected scope:**
> *Keep* CRATE rule (works in dynamic case, validated by 2026-04-29 inverted drill).
> *Add* a **slow-drain detection rule**: if `VCELL declining > 0.005V over 5 minutes AND not-currently-flagged-BATTERY` → flag BATTERY. Threshold tuning TBD with telemetry.
> *Add* a **flap suppression / debounce**: ignore transitions that flip back within N seconds (suggested 30s; tuning TBD). Tonight's data shows 4 transitions in 45 seconds during physical movement; that's heuristic noise, not real state change.

**My recommendation for Marcus:**

This is mid-Sprint-19 with US-235 still `pending` (not yet implemented). Two options:

- **(A) Pause US-235, rescope per above, ship in Sprint 19** — risky for sprint contract, but the wrong fix would land in production and would be hard to detect later (would only show up the next time a drain test is run).
- **(B) Defer US-235 to Sprint 20** with the corrected scope, ship US-234 (SOC→VCELL trigger change) and US-236 (US-228 fix) as planned in Sprint 19. **My lean.** US-235 is an isolated change; deferring it costs us another month of "drain tests don't fire shutdown" but no new data loss because US-216 staged shutdown can't fire anyway (see §6).

Whatever you choose, **please flag this corrected diagnosis to Rex before he picks up US-235** so the wrong implementation doesn't land. If you want to update the story description in sprint.json with the corrected scope, I can mark up the exact text — just ask.

---

## 5. New finding: drive_detect idle-poll gap (Sprint 20 candidate)

### What happened

During the drill, the orchestrator's health checks logged steady state throughout:

```
20:44:34 HEALTH CHECK | connection=connected | data_rate=28.0/min | drives=1 | uptime=7185s
20:45:34 HEALTH CHECK | connection=connected | data_rate=27.0/min | drives=1 | uptime=7245s
20:46:34 HEALTH CHECK | connection=connected | data_rate=28.0/min | drives=1 | uptime=7305s
20:47:34 HEALTH CHECK | connection=connected | data_rate=27.0/min | drives=1 | uptime=7365s
... and so on through the engine-on event ...
```

Note: `drives=1` throughout, `data_rate=27-28/min` constant, `connection=connected`. The orchestrator never noticed an engine-on event happened. `drives=1` is Drive 5 stale, not a new drive.

### Why drive_start didn't fire

The orchestrator's idle-poll mode only queries `BATTERY_V` (via ELM_VOLTAGE / ATRV — adapter-level, ECU-independent). The drive_detector is wired to fire `drive_start` when ECU-dependent PIDs (RPM, COOLANT_TEMP, etc.) start responding — but in idle-poll mode, those PIDs are never queried, so the drive_detector never sees the signal.

This is a **chicken-and-egg gap**: between drives, the orchestrator doesn't query the ECU. So even if the engine starts, the orchestrator doesn't ask the ECU about it, so it doesn't notice. drive_start fires only after the orchestrator already noticed engine-on, which it can't notice without querying the ECU.

### Why this matters for the eventual production pattern

In post-wiring production, the Pi will be powered by the car's accessory line. **Every key-on = Pi power-on (cold boot or near-cold).** On boot, the orchestrator goes through service start → BT connect → first health check → idle-poll. There's a window where the engine is already running but the orchestrator hasn't yet noticed. Currently that window is unbounded — the orchestrator stays in idle-poll forever unless something kicks it out.

In the bench/tonight's-drill scenario, that window manifested as: engine ran for ~1 min visible, no ECU data captured, no drive minted.

In the production scenario (post-wiring), this would mean: every key-on, Pi cold-boots → orchestrator comes up in idle-poll → never escalates → engine runs the whole drive → drive_start never fires → zero ECU data captured → key-off, Pi on UPS → US-216 staged shutdown. **Every drive would silently lose all ECU data.**

This is bigger than a Sprint 20 nice-to-have. It's a **silent data-loss bug that activates the moment B-043 wiring lands**.

### Recommended fix shape (rough — Rex will iterate)

Two viable approaches:

**(a) BATTERY_V threshold trigger**: when `BATTERY_V > 13.8V sustained for N samples` (alternator-active signature), escalate idle-poll → active-poll AND probe ECU PIDs. Pros: uses existing data, no extra polling cost during off-state. Cons: 13.8V threshold is car-specific; my Drive 5 baseline shows this car's alternator hits 14.0V on bulk-charge so 13.8V is safe, but other cars vary.

**(b) Periodic ECU probe in idle-poll**: every N seconds (suggested 30s — slow enough not to flood K-line, fast enough to catch engine-start within a tolerable window), query a single ECU-dependent PID (RPM is the canonical choice). If response received, escalate. If timeout, stay idle. Pros: more robust, doesn't depend on voltage thresholds. Cons: K-line probe activity even when Pi sits idle for hours.

I lean (a) for this car because BATTERY_V is already being polled and the alternator signature is unmissable (14.4V vs 12.7V is huge). Adding a single threshold check costs nothing. (b) is the "more correct" architecture but heavier implementation.

Either way, the fix should be **one Sprint 20 story, sized M** — Rex's lane to scope precisely.

---

## 6. New finding: PowerMonitor DB-write path is dead (Sprint 20 candidate / TD)

### What happened

UpsMonitor logged 8 transitions to journal. **`power_log` table is empty. Zero rows. Ever.** Confirmed via:

```sql
sqlite> SELECT COUNT(*) FROM power_log;
0
```

### Why this matters

US-216 staged shutdown reads from `power_log` (or PowerMonitor's in-memory state, which is fed from the same write path). When PowerMonitor's write path is dead:

- UpsMonitor detects transitions correctly (validated tonight)
- Transitions go to journal only
- `power_log` stays empty
- US-216 staged shutdown sees no `BATTERY` state in DB
- Staged shutdown never fires
- Battery drains to LiPo discharge knee, buck converter dropouts, Pi hard-crashes
- EXT4 orphan cleanup on next boot

This is **the architectural root cause** of why staged shutdown has never triggered across 5 drain tests (4 traditional drain + tonight's inverted). Even with a perfect SOC→VCELL trigger source change (US-234), and even with a perfect UpsMonitor BATTERY-detection rule (US-235 corrected), **shutdown still won't fire** until PowerMonitor's DB-write path is fixed.

### Diagnostic detail

From my Sprint 16/17 power audit on 2026-04-21:

> `PowerMonitor` (783 lines) and `BatteryMonitor` (690 lines) never instantiated in production; both have `enabled=false` defaults and zero orchestrator code paths.

So the issue isn't that PowerMonitor's code is broken. The issue is **PowerMonitor is never started in production**. UpsMonitor (the lower-level polling loop) is alive and logs to journal. PowerMonitor (the higher-level state-machine that writes to `power_log` and triggers staged shutdown) has its `enabled=false` default and the orchestrator never instantiates it.

### Recommended fix shape

Sprint 20 story: instantiate PowerMonitor in `lifecycle.py` startup, with `enabled=true` configuration. Connect UpsMonitor's transition events to PowerMonitor's state machine. Verify writes to `power_log` on next drain test.

This is closely coupled to US-235 (UpsMonitor detection logic) and US-234 (US-216 trigger source). Probably one-of-three or three-of-three of a power-mgmt revision bundle. Rex's lane to scope.

**Important**: **US-234 (SOC→VCELL trigger) does not by itself fix the staged-shutdown-never-fires bug.** The trigger threshold is irrelevant if the trigger reader (PowerMonitor) isn't running. Sprint 19's US-234 ships a *correct trigger source* but to a *non-existent listener*. Worth flagging in the Sprint 19 retro that the user-visible behavior won't change after US-234 ships in isolation.

---

## 7. Observational: UpsMonitor flap during physical movement

The 20:47 transition cluster — 4 transitions in 45 seconds — is heuristic noise. Probably caused by:

- Pi being physically moved (CIO carrying it to the car) → UPS battery contacts settling
- Engine-load-driven voltage swings on the OBD-II port → adapter pulling/releasing current
- Or some interaction of the two

Real power-state changes don't flap. **Any future US-216 staging needs debounce** so a 45-second flap doesn't trigger 4 spurious shutdown initiations. Suggested: ignore any transition that flips back within N seconds (30s is a reasonable starting point; Rex tunes from telemetry).

This is **observational** — captured for whoever scopes the corrected US-235. Not a separate story.

---

## 8. What's NOT in this report

- **drive_summary 500 storm**: still firing every interval-sync throughout this drill, exactly as documented in my power-cycle note from earlier this evening. US-237 in your Sprint 19 contract addresses this. No new info.
- **The chi-srv-01 power cycle**: see separate note from earlier this evening. PASS. Not related to tonight's drill.
- **Engine health grading**: only ~1 min of cranking + alternator data captured at adapter level. Insufficient for a tuning grade. Engine health remains EXCELLENT per Drives 3/4/5 (Drive 5 still the authoritative baseline). Tonight's drill is about the **collector subsystem**, not the engine.

---

## Action items for you (PM lane)

1. **DECIDE on US-235** before Rex picks it up:
   - **Option A**: Pause US-235, rescope inline with my corrected diagnosis (§4), ship in Sprint 19. Risk: contract perturbation.
   - **Option B (my lean)**: Defer US-235 to Sprint 20 with corrected scope. Ship US-234 + US-236 in Sprint 19 as planned. Acknowledge in Sprint 19 retro that staged-shutdown-fires-on-drain remains broken pending Sprint 20 power-mgmt revision bundle.
2. **File for Sprint 20 grooming**:
   - **drive_detect idle-poll gap fix** (M, P0 — silent data loss activates on B-043 wiring)
   - **PowerMonitor DB-write path activation** (M, P0 — gates US-216 working at all)
   - **US-235 rescoped** (S — combine with above as a "power-mgmt revision bundle" if you want, or keep separate)
3. **Optional**: TD against the original US-235 description in sprint.json (the "drop CRATE" guidance was wrong). Documents the corrected diagnosis for future readers. Not blocking.

## Action items for me (Spool lane)

- Update `knowledge.md` with the BATTERY_V threshold values for engine-on detection on this car: 14.4V bulk charge (alternator on), 13.5-13.7V float (alternator on, battery topped), 12.7-12.8V (engine off, battery rest), 11.4V (cranking dip). Useful for whoever scopes the drive_detect fix.
- Update `MEMORY.md` Sprint 19 status section: my prior P0 ask on US-235 was wrong; corrected diagnosis here. Don't want this lost.
- Cross-link this note from `sessions.md` Session 7 entry at closeout.

---

— Spool

## Sources / inputs

- `chi-eclipse-01:obd.db realtime_data` (3327 BATTERY_V rows post-Drive-5, full transition trace)
- `chi-eclipse-01:obd.db power_log` (empty — confirms PowerMonitor write path dead)
- `chi-eclipse-01:obd.db connection_log` (last entry drive_end at 00:02:39Z, no new events)
- `chi-eclipse-01:obd.db drive_summary` (drive_id=5 still latest, no drive_id=6)
- `chi-eclipse-01` `journalctl -u eclipse-obd --since 20:42 --until 20:55` (8 UpsMonitor transitions, 0 drive events)
- `offices/ralph/sprint.json` Sprint 19 contract (US-234 P0, US-235 pending, US-236 P0, US-237 schema-drift fix already scoped)
- `offices/pm/inbox/2026-04-29-from-spool-sprint19-consolidated.md` (the prior note this corrects)
- `offices/pm/inbox/2026-04-29-from-spool-chi-srv-01-power-cycle-and-drive-summary-schema-drift.md` (today's earlier note, separate scope)
- 4 prior drain test write-ups (Session 6, Sprint 17 deploy, Sprint 18 deploy x2)
