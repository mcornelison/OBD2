# Three drives tonight (5/9 evening → 5/10 early AM) — drive-counter at 10, hardware blocker, two new bug priorities
**Date**: 2026-05-10
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important — drive-counter clarification + hardware blocker affecting all future drives until resolved + 2 bug priority bumps for Sprint 28

## TL;DR — drive_counter is at 10, NEXT drive is 11

You may be tracking next-drive as 8 — that's stale. Tonight Mike captured drives 8, 9, and 10. **High water mark on the Pi is now drive_id=10.** Server-side `drive_counter` table still says `last_drive_id=3` (way out of sync — separate cleanup item, not blocking).

| drive_id | Window | Duration | Captured | Notes |
|---:|---|---:|---|---|
| 8 | 5/9 23:21–23:39 | 18 min | **Clean** (8,268 rows @ 459 rows/min) | Cold-start city. First drive under car-coupled Pi power (key-switched USB-C from new stereo). |
| — | 5/9 23:40 → 5/10 00:16 | 37 min orphan window | **DriveDetector failed** | Mike did a 2–3 min around-the-block to back the car in. DriveDetector never assigned a drive_id. 1,078 rows of real driving + idle data are NULL-tagged. |
| 9 | 5/10 00:16–00:46 | 30 min | **Compromised** (1,095 rows @ 36 rows/min, 12× lower than Drive 8) | USB-C power was loose; Pi cycling between wall and battery; data capture degraded. Hardware artifact, not code regression. |
| 10 | 5/10 01:12–01:14 | 2:10 | Captured | Garage pull-in. Too short for tuning use. Drain id=12 opened 8 seconds AFTER drive_start — Pi on battery during drive. |

**Next drive captured by the Pi** = `drive_id=11`.

---

## Hardware Blocker — Stereo USB-C is undersized for Pi 5

Mike's wiring approach was clever: tap into the new stereo's USB-C output (key-switched 5V) instead of running a fuse-box jumper. **It doesn't work for sustained operation.** The stereo's USB-C is almost certainly 2.4A or 3A — Pi 5 needs 5A under load. Evidence:

1. Mike observed the dashboard flickering between `power=car` and `power=battery` while the engine was running — undeniable voltage instability.
2. Drains 10, 11, 12 all started with battery already partially depleted (start_socs 3.74–3.78V vs full ~4.2V). The UPS battery has been micro-draining all day from flicker events, never fully recharging.
3. Drain id=12 opened 8 seconds into Drive 10 — power flicker mid-drive, not a key-off event.
4. Drive 9's data capture degraded to 36 rows/min (vs 459 for Drive 8) — Pi was likely brownout-throttling under unstable power.

**Recommendation**: Mike will proceed with the fuse-box wiring solution. Suggested hardware: 12V→5V/5A buck converter (Pololu D24V50F5 or equivalent), wired to a switched fuse-box circuit. Until that ships, **all in-vehicle test drives will produce compromised data** — no point running Sprint 28 acceptance drills on the current power setup. **Sprint 28 IRL validation is gated on Mike completing the fuse-box wiring.**

I'd flag this in the regression manifest as "F-XX (vehicle-integrated power) NOT YET VALIDATED — pending hardware fix." Don't burn a sprint cycle drilling against a flaky power source.

---

## Bug Priority Updates for Sprint 28

### Bug A (NEW) — DriveDetector warm-restart-cranking gap

**P1 candidate, brand new.**

Mike's 3 tests tonight included a 2-3 min around-the-block between Drive 8 (key off after, waited 1 min) and Drive 9 (separate later trip). DriveDetector caught Drives 8 and 9 cleanly but **completely missed the middle test** — no drive_start, no drive_end, no drive_id. The 2-3 min of real driving data lives as 1,078 NULL-drive_id rows in the orphan window.

**Hypothesis**: DriveDetector has a debounce window or cooldown timer that swallows new-drive detection if a key-on happens within N minutes of the prior key-off. The 1-minute wait between Drive 8 end and Test 2 start was probably inside that window.

**Why P1**: With Pi-to-key wiring now live, the "park-1-min-drive-around-block" pattern is exactly the routine "stop at the gas station / drop something off / move the car" behavior the system should handle. Missing every short hop = systemic data loss going forward.

**Repro protocol** (Spool-recommended deterministic test for Ralph):
1. **Test A** — cold-start drive ~10–15 min. Should produce drive_id=N at 400+ rows/min.
2. **Test B** — within 2–5 min of A's key-off, key-on, drive 2–3 min, key-off. **THIS is the bug-isolation test.** Expected: drive_id=N+1. Bug-active: NULL-tagged orphan rows.
3. **Test C** — within 5–10 min of B's key-off, key-on, drive ~10–15 min. Should produce drive_id=N+2 at 400+ rows/min.

If A and C come out clean and B is missing, the bug is a debounce window. Sprint 28 fix is to lower or remove the debounce.

**Caveat**: this protocol is gated on the fuse-box power fix — running it on flaky USB-C power would confound DriveDetector behavior with power instability.

### Bug B (BUMP) — battery_health_log close-event-on-poweroff race: P3 → P2

Originally P3 ("data hygiene, not safety-critical, fires occasionally"). Tonight changes the math:

| Drain | Status | Cause |
|---:|---|---|
| 9 (5/9 morning) | unclosed | Drain 9 from earlier issue, already filed |
| 10 (5/10 00:00:57) | unclosed | USB-C flicker, opened pre-Drive-9 |
| 11 (5/10 00:46:12) | unclosed | Legitimate key-off after Drive 9 |
| 12 (5/10 01:12:28) | unclosed | USB-C flicker, opened during Drive 10 |

**4 out of 4 drains tonight are unclosed.** The bug fires on every key-off in the new car-coupled lifecycle, not on rare drains. Frequency went up an order of magnitude. P3 → P2 is justified.

The fix recommendation in yesterday's PM note (orchestrator pre-poweroff close-event flush with `os.fsync()` + `PRAGMA synchronous=FULL`, US-267 pattern) still stands.

---

## Drive_counter sync gap (background cleanup item)

`obd2db.drive_counter` table on the server says `last_drive_id=3`, but the Pi has minted up through 10 today. The mirror writer for that table either isn't running or isn't covered by sync. Not blocking — server can still ingest realtime_data + connection_log just fine — but it's a stale signal anyone querying drive_counter would trip over. Bottom of Sprint 28 P3 list at most.

---

## Recommended Sprint 28 priority stack (revised tonight)

| P | Story | Note |
|---|---|---|
| **P0 (NEW BLOCKER)** | Fuse-box wiring hardware fix | **Mike's task, not Ralph's** — but blocks IRL validation |
| **P1** | drive_summary writer regression (yesterday's Spec 3) | Still the analytics blocker |
| **P1** | DriveDetector warm-restart-cranking gap (Bug A above) | New tonight |
| **P1** | calibration.py fix (per Mike's note to you) | |
| **P2** | battery_health_log close-event flush (Bug B, bumped from P3) | |
| **P2** | mod_state enum (yesterday's Spec 1) | |
| **P3** | drive_annotations table (yesterday's Spec 2) | |
| **P3** | drive_counter server-side sync gap | |
| **P3** | Probe PID 0x2F (Fuel Tank Level Input) on 2G ECU + add to poll set if supported | NEW from CIO question this session |

---

## P3 addendum — probe PID 0x2F (Fuel Tank Level Input)

**CIO question this session**: "Isn't fuel level data in the ECU?"

Answer: **PID 0x2F is the standard SAE J1979 PID for fuel tank level input** (returns 0–100%). We have **never probed it on this 2G ECU** — it's not in our Tier 1 confirmed list, not in Tier 2 unconfirmed list, and Sprint 14 US-199 PID-probe didn't include it. **Oversight in our PID probe coverage.**

### Story scope (small)

- Pi-side: probe 0x2F support via the same mechanism US-199 used for other Tier 2 PIDs.
- If supported: add to the regular poll set; populate `drive_summary.fuel_level_at_start` automatically at drive_start.
- If unsupported: document under "What OBD-II CANNOT Tell Us" in `knowledge.md` and continue manual annotation.

### Why bother

Removes one field from Spool's manual drive interview going forward. Pairs with the weather-API feature (separate PM note 2026-05-09) — together they automate ambient_temp + weather + fuel_level capture so future drives only need manual entry for `driving_intent` + `route` + `anything_unusual`. **Major reduction in Spool/CIO interview load** for every future drive.

### Caveat (worth knowing for tuning interpretation)

2G DSM fuel-level senders are known to drift with age — float arms wear out, gauge readings can be inaccurate. Even if 0x2F returns a value, expect ±10-15% accuracy at best. For our use case (F / 3-4 / 1-2 / 1-4 / E granularity for tuning context), that's still useful. Don't trust it for precision fuel-economy calculations.

— Spool
