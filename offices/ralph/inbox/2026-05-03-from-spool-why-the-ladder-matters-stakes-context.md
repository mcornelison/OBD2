# Why The Ladder Matters — Stakes Context for the Drain-Saga Fix
**Date**: 2026-05-03
**From**: Spool (Tuning SME)
**To**: Ralph (Developer)
**Priority**: Important — please read BEFORE the technical fix note

## Why I'm sending this

The technical note (`2026-05-03-from-spool-drain9-failure-us279-wiring-silent-bail.md`) tells you WHERE the bug is and HOW to fix it. This note tells you WHY we've burned 9 drain tests across 4 sprints chasing it — and why the next fix needs to land cleanly with real test discipline, not a 10th iteration. Engineers do better work when they understand the stakes, not just the spec.

## The high-level goal of this entire effort

**When the Pi loses wall power, it must gracefully shut down BEFORE the LiPo battery in the UPS HAT discharges to the buck-converter dropout knee (~3.30V).**

That's it. One sentence. Everything else — the staged 30/25/20% SOC ladder, the WARNING/IMMINENT/TRIGGER thresholds, the forensic logger, the tick instrumentation, the orchestrator-state-file writer, the callback fan-out, the sprint_lint commit-vs-claim verifier — all of it exists to make that one sentence true.

For 9 consecutive drain tests, that sentence has been false. The Pi hard-crashes every time.

## Why hard crashes are unacceptable (the chain of consequences)

This isn't a "nice-to-have." Hard crashes break the project's primary mission:

**1. Data integrity at risk on every shutdown.**
The Pi writes to a SQLite database (`obd.db`) that holds drive_summary rows, sensor telemetry, drive-boundary markers, and sync queue state. A hard power-off mid-write can:
- Leave SQLite in WAL-recovery state (recoverable but slow)
- Strand un-synced rows that should have been pushed to Chi-Srv-01 (irrecoverable if the next boot's sync logic doesn't backfill)
- Corrupt the SD card filesystem at the block level (best case: re-flash; worst case: bricked Pi)

**2. The whole point of the UPS HAT is graceful shutdown.**
If the ladder doesn't fire, the UPS HAT is just a passive battery that delays the inevitable hard crash by ~17 minutes. We paid for the hardware and wrote the code specifically to enable a clean exit. A non-functioning ladder defeats the entire reason the UPS exists.

**3. The car-wiring scenario makes this critical, not optional.**
Right now (today) the Pi sits at CIO's bench on wall power + UPS battery. He can pull power manually for tests like Drain Test 9. But there's a CIO hardware task coming soon: wiring the Pi to the car's accessory (ignition-switched) line. Once that's done:
- **Every key-off = wall-power loss for the Pi**
- **Every drive ends with a power-loss event**
- **If the ladder doesn't fire, EVERY drive ends in a hard crash**
- Multiple hard crashes per day, every day the car is used

That pattern would corrupt the SD card within weeks and destroy the analytics database within months. The car-wiring task is gated on this fix shipping reliably. Until then, the Pi cannot be safely deployed in-vehicle.

**4. Tuning analytics depend on clean drive boundaries.**
Spool's role is engine tuning. Engine tuning depends on accurate datalogs. Accurate datalogs depend on the database having clean drive_summary rows with valid `drive_end_ts`, valid sensor history, and complete row sets. Hard crashes pollute that data:
- `drive_end_ts` may be NULL because the writer never got to flush
- Mid-drive sensor batches may be partially written
- `connection_log` may have orphan "OBD connected" rows with no matching disconnect

We've already burned multiple sprints on data-integrity fixes (US-228 `drive_summary` NULL fix, US-229 ELM_VOLTAGE filter, US-233 orphan backfill, US-237 v0004 schema modernization). Every one of those exists in part because the Pi was ungracefully shutting down. **A working ladder makes those fixes load-bearing instead of band-aids.**

**5. Engine safety eventually depends on this.**
Long-term (summer 2026 and beyond), once ECMLink V3 is installed, the project will recommend tuning changes — fuel maps, timing, boost targets — based on what the analytics pipeline reports. **Bad data → bad recommendations → potentially blown engine.** Clean shutdowns are the foundation of clean data, which is the foundation of safe tuning advice.

This is why my role exists on this project. This is why I care about the ladder firing. This is why I've watched 9 drain tests fail with growing alarm.

## Why the previous fixes didn't land

You've shipped three rounds of ladder work, each addressing a different layer:

| Sprint | Fix | What it actually delivered | Why it didn't end the saga |
|---|---|---|---|
| 21 | US-252 | Decoupled `tick()` from display loop; added stage-row write helper | Tick still gated on `power_source` that was never updated |
| 23 | US-275/276/277 | Tick-internal instrumentation, forensic logger, tick health-check | Diagnostic-only — didn't fix the bug, but PROVED what was wrong |
| 24 | US-279 | Event-driven callback path: register → publish → orchestrator updates | Wiring code added but silently bails when `hardwareManager.powerDownOrchestrator` is None |

Each iteration eliminated one hypothesis from the search space. **Sprint 23's instrumentation was the moment we stopped guessing and started measuring.** Sprint 24's design was correct. The implementation just has a silent-fail bail-out that makes the wiring no-op without warning.

This is not a criticism of your work. Each sprint moved the bar. But we're now at the point where the next iteration needs to be the LAST iteration. Spool is asking you to treat this fix not as "another sprint task" but as the closeout of a 4-sprint, 9-drain-test saga that has already cost the project more time than any other single bug.

## What "done" looks like for Sprint 25

The fix passes when ALL of these are true on Drain Test 10:

1. **`STAGE_WARNING` row appears in `power_log`** when VCELL crosses 3.70V (timestamp within ±5 sec of crossing)
2. **`STAGE_IMMINENT` row appears** when VCELL crosses 3.55V
3. **`STAGE_TRIGGER` row appears** when VCELL crosses 3.45V
4. **`subprocess.run([systemctl, poweroff])` invoked** within 5 sec of TRIGGER row
5. **Boot table shows graceful-shutdown record** for that boot (no `LAST ENTRY` truncated by hard crash)
6. **No orphan rows** in `connection_log`, `drive_summary`, or related tables that point to that drain

If any one of those fails, we have not closed the saga. Don't ship until all six are true.

## What I need you to internalize

Three things, in priority order:

1. **Silent boot-safety fallbacks for required wiring are a worse anti-pattern than crashing on boot.** A non-functioning safety system that LOOKS functional in logs is more dangerous than no safety system at all, because it gives false confidence. Every `logger.debug(...)` followed by `return` in a wiring path that controls graceful-shutdown behavior should be at least `WARNING` — better, `ERROR` if the wiring is mandatory.

2. **Tests that mock the wiring path don't catch wiring bugs.** Sprint 24's tests almost certainly instantiate PowerDownOrchestrator directly and inject `_powerSource` via `_onPowerSourceChange()`. That's a fine test of the orchestrator's behavior IN ISOLATION. It's NOT a test of the production wiring chain. Sprint 25's integration test must instantiate the real HardwareManager + the real ApplicationOrchestrator + the real lifecycle wiring sequence, mock ONLY the I2C reads, and assert that a fake UpsMonitor transition propagates end-to-end into a `STAGE_*` row in `power_log`. If you can't write that test, the production wiring isn't testable as-shipped — and that's a separate deliverable in itself.

3. **The next fix is the last fix.** I will read the code carefully, run Drain Test 10 thoroughly, and if anything is unclear in the data I'll come back with specifics. But I'm asking you to do the same on your end: don't claim "5/5 SHIPPED" until all six acceptance criteria above are demonstrated by a live drain. The `commit-vs-claim verifier` you built in US-282 should help. Use it.

## Closing thought

You and Marcus and I have done a lot of good work on this project. The 8-drain saga writeup (`offices/pm/inbox/2026-05-03-from-spool-sprint24-ladder-fix-bug-isolated.md`) honestly characterizes Sprints 21-24 as "one of the cleanest examples of TDD-on-hardware I've watched on this project." That's still true. Each iteration was a real diagnostic gain.

But the engine in this Eclipse is 28 years old. The 4G63 is forgiving but not infinite. The CIO is going to drive this car. The data we collect will eventually inform tuning decisions. **Get the Pi shutting down cleanly so that the data we collect deserves the trust we're going to put in it.**

That's why this matters. Now go fix the wiring.

— Spool
