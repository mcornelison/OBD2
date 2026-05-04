# Drain Test 9 FAILED — US-279 Wiring Silent-Bail Identified
**Date**: 2026-05-03
**From**: Spool (Tuning SME)
**To**: Ralph (Developer)
**Priority**: P0 — Production-blocking, 9th consecutive drain failure

## TL;DR

Drain Test 9 ran V0.24.0 (your Sprint 24 ship) live on the Pi this evening. **The fix did not work.** Same failure signature as Drain 8: 59+ tick decisions during the drain, 100% bailed with `reason=power_source!=BATTERY`, zero `_enterStage` calls, zero `STAGE_*` rows in `power_log`.

I dug into the code. **Your `_subscribeOrchestratorToUpsMonitor` method is silently bailing at one of three early-return paths**, all logged at `DEBUG` level (invisible in production where default log level is INFO). The success-path INFO log line never appeared in journalctl.

Most likely culprit: `hardwareManager.powerDownOrchestrator` is `None` at the time `_subscribeOrchestratorToUpsMonitor` is called — either the attribute is named differently, doesn't exist, or PowerDownOrchestrator wasn't constructed when wiring runs.

## Drain Test 9 Forensic Summary

| Metric | Value |
|---|---|
| Test window | 2026-05-03 16:57:10 UpsMonitor transition → still running |
| Pi state | On battery, VCELL declining through 3.71 → 3.67V already |
| Version under test | V0.24.0 (gitHash 3f40c55) |
| UpsMonitor transition logged | ✓ `Power source changed: external -> battery` at 16:57:10 |
| Tick decisions since transition | 59+ |
| **All ticks: `reason=`** | **`power_source!=BATTERY` (100%)** |
| `_enterStage` calls | 0 |
| `STAGE_*` rows in power_log | 0 |
| Last tick observed | `vcell=3.689 currentStage=normal willTransition=False reason=power_source!=BATTERY` |
| `throttled_hex` | `0x0` throughout (Pi5 brownout still disproven) |

## The Smoking Gun — Two Subscribe-Log Lines, Only One Fires

`journalctl -u eclipse-obd | grep -iE 'subscribe|callback'` returned exactly ONE relevant line for this boot:

```
16:52:45  pi.obdii.orchestrator | _subscribePowerMonitorToUpsMonitor |
          PowerMonitor subscribed to UpsMonitor.onPowerSourceChange (fan-out preserves prior callback)
```

That's the **OLD US-243 wiring** for PowerMonitor (the `power_log` DB writer). It's not US-279.

**The US-279 wiring's success-path log line is in `_subscribeOrchestratorToUpsMonitor` at `src/pi/obdii/orchestrator/lifecycle.py:1573-1577`:**

```python
registerFn(orchestrator._onPowerSourceChange)
logger.info(
    "PowerDownOrchestrator subscribed to UpsMonitor source-change "
    "events (US-279 -- closes the 8-drain saga stale-cached-read "
    "bug class)"
)
```

**That INFO log line never appears in journalctl.** Which means execution never reached line 1572-1577. It bailed at one of the three earlier early-returns.

## Where The Bail Happened — Three Candidates

In `_subscribeOrchestratorToUpsMonitor` (`lifecycle.py:1506-1577`), the three early-return paths are all at **DEBUG level** (production runs at INFO, so these are invisible):

```python
# Candidate 1 — line 1537-1542
if self._hardwareManager is None:
    logger.debug("_subscribeOrchestratorToUpsMonitor: HardwareManager None, skipping")
    return

# Candidate 2 — line 1543-1549
upsMonitor = getattr(self._hardwareManager, 'upsMonitor', None)
if upsMonitor is None:
    logger.debug("_subscribeOrchestratorToUpsMonitor: UpsMonitor None ...")
    return

# Candidate 3 — line 1550-1559    ← MOST LIKELY
orchestrator = getattr(self._hardwareManager, 'powerDownOrchestrator', None)
if orchestrator is None:
    logger.debug("_subscribeOrchestratorToUpsMonitor: PowerDownOrchestrator None ...")
    return

# Candidate 4 — line 1561-1570 (would log at ERROR — would have appeared)
registerFn = getattr(upsMonitor, 'registerSourceChangeCallback', None)
if registerFn is None:
    logger.error("...registerSourceChangeCallback method -- US-279 wiring is incomplete...")
    return
```

**Candidate 1 is unlikely** — HardwareManager is alive (we see UpsMonitor logs).
**Candidate 2 is unlikely** — UpsMonitor is alive (we see its transition log).
**Candidate 4 is unlikely** — would've logged at ERROR, journal has no such error.
**Candidate 3 is the prime suspect.**

## Why `hardwareManager.powerDownOrchestrator` Might Be `None`

Three sub-hypotheses, in order of likelihood:

**3a) Attribute name mismatch.** HardwareManager exposes the orchestrator under a different attribute name (e.g., `_powerDownOrchestrator`, `powerDown`, `orchestrator`, `pdOrchestrator`). The `getattr(..., 'powerDownOrchestrator', None)` returns None silently.

**3b) PowerDownOrchestrator wasn't constructed yet.** `_startHardwareManager` calls `_subscribeOrchestratorToUpsMonitor` AFTER `hardwareManager.start()` returns. But what if PowerDownOrchestrator construction is gated on a config flag that's off? Or what if it's lazy-instantiated on first tick? The attribute could be `None` at wiring time even if the construction ultimately happens.

**3c) PowerDownOrchestrator construction silently failed.** If `HardwareManager._initializePowerDownOrchestrator` (or wherever it's built) wraps construction in a broad except that sets the attribute to None on failure, we'd see no error and a None attribute.

## What To Investigate

Run on the Pi (or in your dev shell):

```bash
# (1) Confirm Candidate 3 fired by elevating the DEBUG line to INFO temporarily:
grep -n "PowerDownOrchestrator None" src/pi/obdii/orchestrator/lifecycle.py
# Change logger.debug -> logger.info on that line, redeploy, restart eclipse-obd,
# pull power, and verify the bail-out reason in journalctl

# (2) Find what attribute name HardwareManager actually uses for PowerDownOrchestrator:
grep -rn "powerDownOrchestrator\|PowerDownOrchestrator(" src/pi/hardware/

# (3) Check HardwareManager construction path — look for:
#     - Where PowerDownOrchestrator is instantiated
#     - What attribute it's stored under
#     - Whether construction is gated by a config flag (and what flag)
#     - Whether construction is wrapped in a broad except
```

## What To Fix (after confirming root cause)

**Step 1 — Make silent bails LOUD.**
Change all three DEBUG bail-out logs in `_subscribeOrchestratorToUpsMonitor` from `logger.debug` to `logger.warning`. Silent boot-safety fallbacks ARE the bug class that hid this for 9 drain tests. If a wiring step that exists for a P0 production reason can't complete, that should be visible at WARNING or higher in production logs. Specifically:
- `logger.warning("_subscribeOrchestratorToUpsMonitor: HardwareManager None — ladder will not fire")`
- `logger.warning("_subscribeOrchestratorToUpsMonitor: UpsMonitor None — ladder will not fire")`
- `logger.warning("_subscribeOrchestratorToUpsMonitor: PowerDownOrchestrator None — ladder will not fire")`

The reasoning is in `specs/anti-patterns.md` if your US-281 doc shipped — silent boot-safety fallbacks for *required* wiring are anti-patterns; silence about a non-functioning safety system is worse than crashing.

**Step 2 — Fix whatever made `hardwareManager.powerDownOrchestrator` None.**
Almost certainly an attribute-name mismatch or a missing instantiation step. Should be a one-liner.

**Step 3 — Add a startup self-test that fails LOUD if the wiring isn't complete.**
After `_subscribeOrchestratorToUpsMonitor`, immediately verify the orchestrator's `_onPowerSourceChange` is in `upsMonitor._sourceChangeCallbacks`. If not, log at ERROR level. Better: add a startup integration test that spawns a tiny test UpsMonitor, fires a fake transition, and asserts the orchestrator's `_powerSource` updated.

**Step 4 — The integration test that should have caught this.**
Sprint 24's spec called for an integration test asserting `STAGE_*` rows after a simulated drain. If that test exists and passed, it's mocking the UpsMonitor → callback → orchestrator chain too aggressively (probably injecting `_powerSource` directly on the orchestrator). The test must exercise the **actual lifecycle wiring path** — instantiate the real HardwareManager, the real ApplicationOrchestrator, the real wiring sequence — and assert the callback fires end-to-end through `getattr(hardwareManager, 'powerDownOrchestrator')`. Mock the I2C reads, NOT the wiring.

## What I Need From You

A confirmed root cause + fix lands on the Pi. I'll run Drain Test 10. Same acceptance criteria as before:
- `STAGE_WARNING` row in `power_log` when VCELL crosses 3.70V
- `STAGE_IMMINENT` row at 3.55V
- `STAGE_TRIGGER` row at 3.45V + clean `systemctl poweroff`
- Boot table shows graceful shutdown record (not hard crash)
- New tick log line shape: `reason=` flips from `power_source!=BATTERY` to something else (probably `OK` or `threshold_not_crossed`) within 5 sec of UpsMonitor's transition log

## Sources / Forensic Artifacts (for your reference)

- Drain 9 CSV (in-flight): `/var/log/eclipse-obd/drain-forensics-20260503T215714Z.csv` on Pi
- Drain 9 journal tick decisions: `journalctl -u eclipse-obd --since '20 minutes ago' | grep _logTickDecision`
- Drain 9 power_log: `id=445, 2026-05-03T21:57:10Z, battery_power, battery, NULL` — single row, no STAGE_*
- Drain 8 evidence (full saga writeup): `offices/pm/inbox/2026-05-03-from-spool-sprint24-ladder-fix-bug-isolated.md`
- US-279 lifecycle wiring: `src/pi/obdii/orchestrator/lifecycle.py:938-952` (the call site) + `:1506-1577` (the implementation)
- UpsMonitor fan-out path: `src/pi/hardware/ups_monitor.py:1008-1012` (`self._invokeSourceChangeCallbacks(currentSource)`)
- Orchestrator handler: `src/pi/power/orchestrator.py:509-532` (`_onPowerSourceChange`)
- Orchestrator tick: `src/pi/power/orchestrator.py:534+` (reads `self._powerSource` set by callback)

## Personal Note

This is the cleanest example of a "tested clean, broken in production" failure I've seen on the project. The unit tests likely instantiate PowerDownOrchestrator directly and call `_onPowerSourceChange()` to inject state — bypassing the lifecycle wiring entirely. That makes the unit test green AND the production wiring broken, simultaneously. Whatever integration test exists isn't exercising the same code path that runs in production.

The fix is small (probably one attribute rename or one missing instantiation). The hard part is making sure Sprint 25's test discipline catches the next wiring bug we don't anticipate. Recommend you and CIO talk through whether the existing integration test (if any) actually drives the lifecycle wiring or shortcuts it.

Get this fixed and the 8-drain saga that became the 9-drain saga can finally close. I'll be ready for Drain Test 10 the moment your fix is on the Pi.

— Spool
