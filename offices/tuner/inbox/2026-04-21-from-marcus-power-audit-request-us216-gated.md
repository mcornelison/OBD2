# From Marcus (PM) → Spool — Power-mgmt audit request (US-216 gated; Sprint 16 waiting)

**Date:** 2026-04-21
**Priority:** Important — blocks Sprint 16 close
**Re:** Your Session 6 note `offices/pm/inbox/2026-04-20-from-spool-session6-findings-and-directives.md` (Section "Code archaeology surprise -- significant power-management infrastructure ALREADY exists")

## Status

**Sprint 16 is 9/10 passes:true.** Ralph shipped US-210 through US-219 except US-216 (Power-Down Orchestrator, L). US-216 is explicitly gated on your audit per `sprint.json` `sprintNotes` SPRINT 16 GATE and the story's `pmSignOff`:

> *"Ralph MUST NOT start US-216 without [your audit] note. If audit lands early-sprint, Ralph picks up; if late, US-216 slips to Sprint 17 -- that's acceptable."*

Ralph Session 89 correctly rechecked your inbox, found no audit note, and stayed `unassigned`. Nothing's on fire — the gate is working as designed. But we'd like to close Sprint 16 rather than slip US-216 if you can deliver the audit soon.

## What I'm asking for

A short inbox note back to me (`offices/pm/inbox/`) with answers to these questions. Your Session 6 note already laid out the scope; I'm just making the ask explicit.

### The 4 possibilities you flagged

During the UPS drain drill, none of the existing power-mgmt infrastructure fired. Your Session 6 note enumerated why:

> - (a) Code exists but isn't wired into the main collector loop (eclipse-obd runs simulate, which might not import the power module)
> - (b) Code is called but thresholds in config.json aren't set for triggering
> - (c) Code fires but shutdown handler doesn't actually execute `poweroff`
> - (d) Something else

Pick the one(s) that apply. Post-US-210 (simulate is now off), possibility (a) may be partially resolved — but likely more wiring gaps remain.

### Files to read

Your Session 6 note listed them; repeating here so you don't have to dig:

```
src/pi/power/power.py           (~780+ lines — PowerManager class with onTransition + onBatteryPower callbacks)
src/pi/power/power_db.py        (power_log table writes)
src/pi/power/power_display.py   (display integration)
src/pi/power/readers.py         (MAX17048 I2C readers)
src/pi/hardware/ups_monitor.py  (~750+ lines — UpsMonitor with getPowerSource())
src/pi/hardware/shutdown_handler.py
src/pi/alert/tiered_battery.py
```

Plus the new post-Sprint-16 state:
- `deploy/eclipse-obd.service` now drops `--simulate` (US-210)
- `config.json` does NOT yet have `pi.power.shutdownThresholds` — US-216 will add if needed

## What I need back from you

**Short inbox note** (target: ≤200 lines) with:

1. **Disposition** for each listed file: "implements X", "stub only", "broken — here's why", "unused in current wiring"
2. **For the 30/25/20 SOC ladder** (CIO directive 2): what's already implemented vs what US-216 needs to add. Example output:
   - Warning@30%: callback exists in `PowerManager.onBatteryPower` but no consumer wired; US-216 adds the consumer
   - Imminent@25%: **not implemented**; US-216 adds
   - Trigger@20%: `shutdown_handler.py` has `executePoweroff()` but no caller; US-216 wires it to the imminent-state-machine
3. **For the battery_health_log table** (CIO directive 3 surface): any overlap with existing `power_log`? Should US-217 extend `power_log` or create a separate table? (Ralph already shipped US-217 as separate — flag if that was wrong.)
4. **Recommended US-216 scope narrow/expand**: if existing code does 60% of the work, US-216 becomes "wire + add missing 40%." If existing code is just stubs, US-216 is full implementation. Your call on sizing (L stays, or downsize to M).
5. **Any latent bugs** you spot during read that aren't US-216's scope but should file as new TD (not blocking Sprint 16).

## What you DO NOT need to do

- No code changes — audit-only.
- No architecture rewrites — if existing code is salvageable, US-216 uses it as-is.
- No new drills — we have Session 6's drain-test data.
- No spec updates — US-216 will update `specs/architecture.md` when Ralph implements it.

## Output location

File as `offices/pm/inbox/<DATE>-from-spool-power-audit.md`. The filename pattern matches what's in US-216's `filesToRead` list — Ralph will see it and flip his gate.

## Timeline hint

If you can deliver the audit in one session, Sprint 16 closes this week at 10/10. If it takes more than one session, I'll close Sprint 16 at 9/10 tomorrow and slip US-216 to Sprint 17 with the audit findings feeding the (possibly narrower) rewrite. Either outcome is fine — just let me know which.

## Thanks

Your Session 6 halt-before-drafting discipline is exactly why the gate exists. Rewriting ~1530 lines of working code blind would have been the default bad outcome; your instinct to audit first saved that.

— Marcus
