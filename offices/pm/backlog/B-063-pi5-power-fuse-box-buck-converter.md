# B-063: Pi 5 power -- fuse-box buck converter (replaces stereo USB-C tap)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | **CRITICAL** -- blocks ALL V0.27.X IRL validation drills |
| Status       | Pending (CIO hardware task)  |
| Category     | hardware / infrastructure |
| Size         | (CIO hardware effort, not Ralph) |
| Related PRD  | None                   |
| Dependencies | None |
| Created      | 2026-05-10             |

## Description

Spool 2026-05-10 evening test surfaced this hardware blocker. Mike's clever wiring approach (tap into new stereo's USB-C output, key-switched 5V) is undersized for sustained Pi 5 operation. **All in-vehicle test drives produce compromised data until this is fixed.**

**Pi 5 power requirement**: 5V at 5A under load.

**Stereo USB-C provides**: ~2.4A or 3A (typical aftermarket head-unit USB-C output).

**Empirical evidence**: 2026-05-09 evening / 2026-05-10 early AM, three drives + four drains:

| Symptom | Evidence |
|---|---|
| Voltage instability during engine-on | Mike observed dashboard flickering between `power=car` and `power=battery` while driving |
| UPS battery never fully recharging | Drains 10/11/12 all started with `start_socs` 3.74-3.78V (vs full ~4.2V) -- battery has been micro-draining all day from flicker events |
| Drain opens DURING drive (mid-drive flicker) | `drain_event_id=12` opened 8 seconds INTO Drive 10 -- power flicker mid-drive, not key-off |
| Data capture degraded under brownout | Drive 9 produced 36 rows/min vs Drive 8's 459 rows/min (12x lower) -- Pi was likely brownout-throttling |

## Recommended Hardware Fix

**12V → 5V/5A buck converter** wired to a switched fuse-box circuit:

- **Suggested unit**: Pololu D24V50F5 (24V input range, 5V/5A output) -- Spool's recommendation. Or equivalent automotive-grade buck.
- **Wiring**: switched fuse-box circuit (key-switched 12V) → buck input; buck 5V output → Pi 5 USB-C in (or GPIO 5V if cleaner).
- **Why fuse-box not stereo**: native 12V capacity, dedicated fuse for safety, no contention with stereo's other USB consumers, supports full 5A draw.

## Acceptance Criteria

- [ ] Pi 5 powered via fuse-box buck converter (NOT stereo USB-C)
- [ ] Engine-on drive shows steady `power=car` for full duration (no flicker to `battery` mid-drive)
- [ ] UPS battery fully recharges to ~4.2V VCELL after engine-on cycle (no chronic drain)
- [ ] Drive captures sustained 400+ rows/min throughout drive (not 36 rows/min brownout-throttling)
- [ ] Drain test 11 (controlled drain on bench, AC power pulled) still fires V0.24.1 ladder cleanly through TRIGGER stage

## Validation Path

After hardware install:

1. Cold-start drive 10-15 min, observe dashboard `power=car` steady throughout, post-drive verify `realtime_data` shows >= 400 rows/min
2. Run I-019 repro protocol (Test A / Test B / Test C) -- this exercises the full DriveDetector + power-state interaction
3. Confirm UPS battery VCELL recovers to ~4.2V within reasonable time post-drive

## V0.27.X validation gate

**Sprint 28 / V0.27.2 IRL validation (Drive 8 + Drain Test 11) is gated on this hardware fix.** Per Spool 2026-05-10: "Don't burn a sprint cycle drilling against a flaky power source." V0.27.3 is also gated -- I-019 repro protocol explicitly requires stable power.

Until B-063 is complete, V0.27.2 stays in DEPLOYED-AWAITING-VALIDATION state. The bench-coupled bits (e.g., a swap-to-wall-power Drain Test 11 forensic capture) can proceed independently if Mike chooses, but in-vehicle drives cannot.

## Notes

**Pi power state evolution**:
- (Through 2026-05-08): bench wall power + UPS battery; Pi reachable any time
- (2026-05-09): Mike wired Pi to stereo USB-C key-switched output (this story's pre-state)
- (After this story): Pi on fuse-box buck converter key-switched output; ignition-coupled with proper 5A capacity

**Why critical priority**: silently corrupts every IRL drill we run. False-negative validation results from compromised power confound code regression analysis.

## Source

`offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-three-drives-tonight-power-blocker-drive-counter-clarification.md` (Hardware Blocker section)
