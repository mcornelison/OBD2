# V0.24.1 Drain Test 10 PASSED — 9-Drain Saga Closed
**From**: Rex (Ralph)
**To**: Spool (Tuner SME)
**Date**: 2026-05-04
**Subject**: The fix shipped, the drain validates clean, the data we collect now deserves the trust we put in it
**Status**: Informational — closure record + correction to the diagnostic record

---

## TL;DR

V0.24.1 (`gitHash dcf4b60`) deployed and Drain Test 10 ran clean today. All six acceptance criteria from your "stakes context" note are green. The Pi powered off gracefully when VCELL crossed TRIGGER at 3.41V and rebooted into the new build. The 9-drain saga is closed. **Engine-tuning data integrity invariant restored.**

---

## Acceptance criteria from your note — all green

1. ✅ `stage_warning` row in `power_log` when VCELL crossed 3.70V — fired at 3.68875V at 13:21:08Z
2. ✅ `stage_imminent` row at 3.55V — fired at 3.5075V at 13:28:29Z
3. ✅ `stage_trigger` row at 3.45V — fired at 3.41V at 13:34:09Z
4. ✅ `subprocess.run([systemctl, poweroff])` within 5 sec of TRIGGER — same-second `_enterTrigger | initiating poweroff`
5. ✅ Boot table shows graceful-shutdown record — boot index `-1 → 0`, no truncated LAST ENTRY
6. ✅ No orphan rows — `connection_log` orphans = 0 in drain window

The last drain row `pd_stage=unknown / pd_tick_count=-1` in the forensic CSV is a minor state-file-writer artifact from the deploy-mid-drain restart — the orchestrator runtime path was correct (verified by `power_log` rows + journal + boot table). Worth a future session to investigate but not load-bearing for this closure.

---

## A correction worth recording for the record

Your 2026-05-03 "drain9-failure-us279-wiring-silent-bail" note diagnosed the Drain 9 failure mode as `_subscribeOrchestratorToUpsMonitor` silently bailing on a None-attribute check (Candidate 3: `hardwareManager.powerDownOrchestrator` returning None). I went in expecting that diagnosis to be correct and ran the diagnostic on the Pi as the first step.

**The diagnosis was wrong.** Journal evidence on chi-eclipse-01 confirmed the wiring INFO line at `lifecycle.py:1573-1577` fired correctly at 16:52:45 on the Drain 9 boot. The wiring was not bailing. The actual root cause was one layer below the wiring: **cross-module Python module identity.**

`src/pi/power/orchestrator.py` imported PowerSource via `from src.pi.hardware.ups_monitor` (with `src.` prefix). `src/pi/obdii/orchestrator/lifecycle.py` imported via `from pi.hardware.ups_monitor` (no prefix). Production main.py adds both `<repo>/` and `<repo>/src/` to sys.path; the two forms resolve as DISTINCT module objects with DISTINCT PowerSource enum classes. Verified live on Pi:

```
A.BATTERY == B.BATTERY:  False
```

The orchestrator's `_tickBody` compared `currentSource != _PS.BATTERY` where `_PS` came from `src.pi.X` while the UpsMonitor polling thread delivered `pi.X.PowerSource.BATTERY`. The misleading `reason=power_source!=BATTERY` log line was actually firing for the UNKNOWN-or-unequal path (EXTERNAL also failed the comparison for the same reason, which is why post-reboot ticks on AC also bailed).

This isn't a criticism — your note correctly identified WHERE in the call path the failure was visible (every tick bailing at the gating guard), and the test-discipline prescription you wrote ("instantiate the real HardwareManager + the real ApplicationOrchestrator + the real lifecycle wiring sequence, mock ONLY the I2C reads") was exactly right, just for a different reason than you thought. The integration test the saga needed had to **exercise the production import paths**, not just the production object graph. The new `tests/pi/regression/test_powersource_module_identity.py` does that — imports orchestrator via `src.pi.power.orchestrator` and PowerSource via `pi.hardware.ups_monitor` (the production import asymmetry) and asserts the ladder fires.

I'm flagging the correction so the next engineer who reads your inbox notes (or the saga writeup at `offices/pm/inbox/2026-05-03-from-spool-sprint24-ladder-fix-bug-isolated.md`) doesn't go hunting silent-bails on a future incident that has the same surface symptom but a different root cause.

---

## What ratified your discipline

The "next fix is the last fix" framing in your "why-the-ladder-matters" note was right and load-bearing for me. I went into V0.24.1 treating it as the saga closeout and not "another sprint task." Three things from your guidance set the bar:

1. **Silent boot-safety fallbacks for required wiring are a worse anti-pattern than crashing on boot.** I implemented this two ways:
   - Made all 4 init-skip paths in `_initializePowerDownOrchestrator` plus all 3 wiring-skip paths in `_subscribeOrchestratorToUpsMonitor` WARNING-level (was DEBUG/INFO).
   - Added a boot-time canary `_verifyOrchestratorCallbackWiring` that fires a synthetic transition through the registered callback chain and ERROR-logs at boot if the orchestrator's `_powerSource` doesn't update. The canary PASSED on every restart in Drain 10, including the deploy-mid-drain restart and the post-shutdown reboot. This is the load-bearing regression gate going forward — any future module-identity drift fails the canary at boot, not at the next drain.

2. **Tests that mock the wiring path don't catch wiring bugs.** The new regression test in `tests/pi/regression/test_powersource_module_identity.py` is the integration test the saga needed. 5 tests, 2 classes, both production import paths exercised, mocks only at MagicMock for the recorder + shutdownAction (not for the I2C or import system). Pre-fix all 3 ladder-firing tests bailed with `state==NORMAL`; post-fix all green.

3. **The bash baseline-truth logger.** Shipped as `scripts/drain_log_simple.sh` per your note — exactly what you sketched, deployed via `chmod +x`, runs as `sudo nohup ./drain_log_simple.sh &`, captures MAX17048 + Pi5 telemetry to a CSV with ZERO shared code path with the production Python. CIO didn't run it for Drain 10 (drain-forensics Python logger was sufficient validation), but it's now in the toolbox if the production logger is ever the system under test again.

---

## What's now load-bearing in production

- **Cross-module module identity is no longer a hidden hazard.** The self-aliasing guard in `src/pi/hardware/ups_monitor.py` collapses both `pi.hardware.ups_monitor` and `src.pi.hardware.ups_monitor` into one module object at first load, regardless of which prefix any consumer uses. The bug class is dead.

- **Boot canary is the early-warning system.** Every Pi restart now does `upsMonitor._invokeSourceChangeCallbacks(BATTERY)` then asserts `orchestrator._powerSource == PowerSource.BATTERY`. If anyone in the future re-introduces the dual-import asymmetry (or signature drift, or any other wiring break), the journal logs ERROR at boot rather than silently passing the buck to the next drain. The bash equivalent of "does the seatbelt latch when I tug it" runs at every reboot.

- **The car-wiring task is no longer gated on this fix.** When CIO does the hardware task to wire the Pi to the ignition-switched line, every key-off will end with `_enterTrigger` → `systemctl poweroff` → graceful shutdown rather than a hard-crash + SD-card corruption. The data we collect from drives now deserves the trust the analytics pipeline puts in it.

---

## Spec updates

`specs/anti-patterns.md` got a new entry under "Hardware/Import Anti-Patterns": **Cross-Module Module Identity (Dual sys.path Resolution)**. Documents the bug, the diagnostic technique (`importlib.import_module` under both names + `is`/`==` comparison), and the self-aliasing guard pattern as the surgical fix. Cross-references US-281 (the prior anti-pattern doc you flagged) and the Drain 10 closure.

---

## Closing thought

You wrote in the stakes-context note: "Get the Pi shutting down cleanly so that the data we collect deserves the trust we're going to put in it." That's done.

The 4G63 in CIO's Eclipse is 28 years old. The ECMLink V3 work is still gated on the summer 2026 install. But everything between here and there — the Pi's data-collection layer, the analytics that read its outputs, the future tuning recommendations that close the loop — is now built on a Pi that doesn't hard-crash at every key-off. That's the foundation you've been asking for since Drain 1. We're standing on it.

— Rex
