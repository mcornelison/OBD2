# B-054: Automated battery test on boot

| Field      | Value                                  |
|------------|----------------------------------------|
| Status     | Pending PRD grooming                   |
| Priority   | **P4 -- nice-to-have** (Mike 2026-05-08: "lets get everything else working first") |
| Filed By   | Marcus (PM), 2026-05-08 from Mike directive |
| Filed Date | 2026-05-08                             |
| Sprint     | Future candidate; not Sprint 28 (gated on Sprint 27 validation + post-mod baseline shelf) |

## Why

Mike 2026-05-08 idea: project should have a passive battery-health monitoring loop that exercises the full power-down + power-on cycle on a regular cadence (every N drives or every 2 weeks). Currently we only know UPS battery health when a real drain happens or when CIO triggers a manual drain test. An automated cadence would catch battery degradation early + provide trend data over time.

**Mike's exact framing**: "the system does it's normal detect low battery, does a graceful shutdown of the eclipse-tuner software, but then lets a small monitor watch the battery and then on boot we now have a automated battery test."

## Mechanics (proposed)

1. **Trigger**: configurable cadence (e.g. every 10th drive_end, OR every 2 weeks since last test, whichever comes first).
2. **Pre-test setup**: Pi continues normal operation through end of drive. After drive_end + sync completes + safe-to-discharge precondition, system enters "battery test" mode.
3. **Discharge phase**: kick off the staged shutdown ladder normally (PowerDownOrchestrator hits WARNING -> IMMINENT -> TRIGGER as VCELL declines under UPS battery load).
4. **Forensic recording**: a small monitor process watches battery state during the off-state -- could be:
   - Pi5 itself in low-power mode using systemd hooks (e.g., journal entries before halt + boot cooperative)
   - OR an external micro (overkill; keep simple)
   - OR just write a `battery_test_summary` row capturing pre/post VCELL / SOC / drain duration / dropout VCELL
5. **Post-test analysis on next boot**: read the `battery_test_summary` row + compare against historical baseline. If VCELL dropout knee or runtime trends 10%+ worse than baseline -> alert.
6. **Reporting**: Spool's tuning analysis shelf gets a battery-health view (statistical envelope tracked across all auto-tests).

## Open design questions (PRD grooming)

1. **Cadence trigger**: pure-time (every 14 days)? drive-count (every 10 drive_ends)? OR ("either" trigger fires)? What's the right interval for a hobbyist car?
2. **Safe-to-test preconditions**: must NOT auto-fire during a planned long trip. How does Pi know? Sync_history idle for X hours? Garage WiFi present? Mike's manual-disable flag?
3. **Off-state monitoring**: Pi can't watch its own off-state. Options:
   - Pre-shutdown VCELL stamping; post-boot diff
   - systemd-suspend hook variants
   - External micro (rejected as overkill)
4. **Failure/regression alert**: where? Spool inbox? Dashboard alert next boot? `connection_log` event_type=battery_health_warning row?
5. **Storage**: extend existing `battery_health_log` (Sprint 26 US-289 + US-294 territory) OR new `battery_test_summary` table?
6. **First-test-baseline**: how do we anchor "normal" for this car's UPS? Drain Test 11 + 12 + 13 averaged?

## Operator-action gates (action items, NOT sprint stories)

- CIO accepts the auto-test cadence on first activation (or directs a different trigger).
- CIO observes the first 1-2 auto-tests to confirm preconditions are working as expected.
- Spool reviews trend data after first 5+ auto-tests.

## Sprint sizing

- **Story A** (M) -- Cadence trigger + preconditions + safe-to-test gate
- **Story B** (M) -- Pre/post VCELL stamping + battery_test_summary writer (or battery_health_log extension)
- **Story C** (S) -- Boot-time analysis + alert path
- **Story D** (S) -- Spool's review-shelf integration

Whole feature: ~10 size points across 4 stories.

## Related

- B-043 (Pi auto-sync + conditional shutdown) -- foundation; this consumes the staged-shutdown ladder
- US-216 / US-252 / US-279 (the 9-drain saga ladder fix) -- this exercises that path on every cadence trigger
- US-289 (battery_health_log column rename Sprint 26) -- this consumes / extends that schema
- F-008 + F-011 + F-012 (regression manifest features) -- this auto-test validates them on every cycle (could become a passive validation source for those features)
- Spool's pre-mod baseline shelf (Mike 2026-05-06 P4 ask) -- complementary; baseline is engine-on, this is power-mgmt-on

## Why P4

Mike directly: "lets get everything else working first. that is a P4 a very nice to have." Translation: don't pull this into a sprint until:
1. Sprint 27 validates (Drive 6 + Drain 11 confirm core loop works)
2. Pre-mod baseline shelf is in place (3-5 drives across May/June)
3. Mods start landing (this would be most useful as a regression detector for mod-induced battery anomalies)

Estimated landing: Sprint 30+ as Mike's prep for ECMLink V3 install summer 2026 -- battery-health regressions during mod-tuning would be hard to debug without an automated baseline.
