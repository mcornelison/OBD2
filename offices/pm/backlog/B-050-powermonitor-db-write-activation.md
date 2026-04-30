# B-050: PowerMonitor DB-write path activation — UpsMonitor → power_log → US-216

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High (P0 for Sprint 20) |
| Status       | Pending grooming       |
| Category     | architecture / pi-power-mgmt |
| Size         | M                      |
| Related PRD  | None (Sprint 20 candidate; couples with B-049, B-051) |
| Dependencies | None                   |
| Filed By     | Marcus from Spool inverted-power drill 2026-04-29 |
| Created      | 2026-04-29             |

## Description

**Architectural root cause** of why US-216 staged shutdown has never fired across 5 drain tests (Session 6, Sprint 17, Sprint 18 ×2, 2026-04-29 inverted drill).

UpsMonitor (lower-level MAX17048 polling loop) **is alive and detects power-source transitions correctly** — validated tonight by 8 transitions logged to journal during the inverted-power drill (`external→battery` and `battery→external` events with timestamps within the 9-min window).

PowerMonitor (the higher-level state-machine that writes to `power_log` and triggers staged shutdown) **is never instantiated in production**. From Spool's Sprint 16/17 power audit (2026-04-21):

> `PowerMonitor` (783 lines) and `BatteryMonitor` (690 lines) never instantiated in production; both have `enabled=false` defaults and zero orchestrator code paths.

**Result:** UpsMonitor → journal only. `power_log` table has been **empty since installation** (confirmed via `SELECT COUNT(*) FROM power_log = 0`). US-216 staged shutdown reads from `power_log` (or PowerMonitor's in-memory state, which is fed from the same write path). With PowerMonitor dead, US-216 sees no `BATTERY` state in DB → staged shutdown never fires → battery drains to LiPo discharge knee → buck dropout → Pi hard-crash → EXT4 orphan cleanup on boot.

**Important**: **US-234 (SOC→VCELL trigger source change, Sprint 19) does not by itself fix this.** US-234 ships a *correct trigger source* but to a *non-existent listener*. Until B-050 lands, the next drain test will look exactly like the 5 prior ones.

## Acceptance Criteria

- [ ] PowerMonitor instantiated in `lifecycle.py` startup with `enabled=true` configuration
- [ ] UpsMonitor's transition events connected to PowerMonitor's state machine (UpsMonitor → PowerMonitor → power_log writer)
- [ ] All UpsMonitor-detected transitions land in `power_log` with correct `event_type` (NORMAL→BATTERY, BATTERY→EXTERNAL, etc.) and timestamp
- [ ] US-216 PowerDownOrchestrator reads PowerMonitor state correctly when wired (post-US-234, post-B-051) — staged shutdown can fire
- [ ] Synthetic test: mock UpsMonitor.transitionDetected() event → assert PowerMonitor state machine transitions, asserts power_log INSERT fires with correct columns (per `feedback_runtime_validation_required.md` — mocks must operate at signal level)
- [ ] Live verification (post-sprint action item, NOT acceptance gate): a drain test that exercises the new path actually populates power_log

## Recommended Fix Shape (per Spool — Rex iterates)

1. Audit `src/pi/power/power_monitor.py` (783 lines) — what state machine it implements, what it writes
2. Audit `src/pi/lifecycle.py` startup — find where UpsMonitor is instantiated; add PowerMonitor instantiation alongside
3. Verify `enabled=false` default in config — flip to `enabled=true` in `config.json`'s `pi.power.power_monitor` section
4. Wire UpsMonitor transition callback → PowerMonitor.handleTransition()
5. Confirm `power_log` schema matches what PowerMonitor expects to write (US-217 / US-225 / TD-034 era; may need a migration)

## Validation Script Requirements

- **Input**: Pi boots, runs ≥1 minute, then a synthetic transition event is fired
- **Expected Output**: `power_log` row appears with correct columns within seconds
- **Database State**: `SELECT COUNT(*) FROM power_log` returns ≥1; latest row has correct event_type, timestamp
- **Test Program**: pytest with mocked UpsMonitor → PowerMonitor wiring; asserts INSERT statement composes correctly

## Related

- **US-216** (Power-Down Orchestrator) — gated on this; staged shutdown can't fire without power_log
- **US-217** (battery_health_log) — sister log table; wiring pattern reference
- **US-234** (Sprint 19 SOC→VCELL trigger) — correct trigger source but no listener until B-050 lands
- **B-049** (drive_detect idle-poll gap) — sister Sprint 20 candidate; possibly bundle
- **B-051** (UpsMonitor slow-drain + flap-debounce) — sister Sprint 20 candidate; possibly bundle
- **TD-031** (BatteryMonitor wrong-thresholds, Sprint 17 deleted) — analogous "code exists, never instantiated" pattern; B-050 fixes it for PowerMonitor side
- **TD-032** (tiered-battery defined, never called) — same architectural class
- **TD-033** (telemetry-logger UPS plumbing unaudited) — Spool's earlier flag in same area
- **Source note**: `offices/pm/inbox/2026-04-29-from-spool-inverted-power-drill-findings-and-us235-correction.md` Section 6

## Notes

- **5 drain tests, 0 power_log rows** — empirical evidence the listener was never wired
- **Worth flagging in Sprint 19 retro**: US-234 user-visible behavior won't change after ship in isolation; needs B-050 (and ideally B-051) to actually exercise staged shutdown
- **Sprint 20 P0 ranking**: probably ranks above B-049 because B-049 only matters post-B-043-wiring, while B-050 matters every drain test today
