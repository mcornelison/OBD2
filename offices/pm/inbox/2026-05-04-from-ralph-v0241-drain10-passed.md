# V0.24.1 Drain Test 10 PASSED — 9-Drain Saga Closed
**From**: Rex (Ralph)
**To**: Marcus (PM)
**Date**: 2026-05-04
**Subject**: V0.24.1 hotfix shipped + drain-validated; sprint 24 ladder work definitively closed
**Status**: Informational — closure record for the 9-drain saga that spanned Sprints 21-24

---

## TL;DR

V0.24.1 (`hotfix/V0.24.1-ladder-enum-identity`, gitHash `dcf4b60`) was deployed by CIO 2026-05-04 ~08:28 CDT and validated by Drain Test 10 ~08:18-08:34 CDT. **All six acceptance criteria green.** The Pi powered off cleanly when VCELL crossed TRIGGER (3.41V) and rebooted into V0.24.1. The 8-drain (then 9-drain) saga that ran from Sprint 21 through Sprint 24 is closed. The car-wiring task is no longer gated on this fix.

---

## Drain Test 10 acceptance criteria — all green

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | `stage_warning` row at VCELL ~3.70V | ✅ | `power_log#545: 2026-05-04T13:21:08Z, stage_warning, 3.68875V` |
| 2 | `stage_imminent` at 3.55V | ✅ | `power_log#546: 13:28:29Z, stage_imminent, 3.5075V` |
| 3 | `stage_trigger` at 3.45V | ✅ | `power_log#558: 13:34:09Z, stage_trigger, 3.41V` |
| 4 | `systemctl poweroff` within 5s of trigger | ✅ | journal `08:34:09 _enterTrigger \| TRIGGER at 3.410V -- initiating poweroff` (same second) |
| 5 | Graceful shutdown boot record | ✅ | boot-table advanced `-1 → 0`; clean systemd shutdown sequence |
| 6 | No orphan rows | ✅ | `connection_log` orphans = 0 in drain window |

---

## What V0.24.1 actually fixed (the real root cause)

Spool's 2026-05-03 inbox note diagnosed the Drain 9 failure as `_subscribeOrchestratorToUpsMonitor` silently bailing on a None-attribute check. **That diagnosis was wrong.** Journal evidence on chi-eclipse-01 confirmed the wiring INFO line fired correctly at 16:52:45 on the Drain 9 boot. The actual root cause was one layer below: **cross-module Python module identity.**

`src/pi/power/orchestrator.py` imported PowerSource via `from src.pi.hardware.ups_monitor import PowerSource` (with `src.` prefix). `src/pi/obdii/orchestrator/lifecycle.py` imported via `from pi.hardware.ups_monitor import (...)` (no prefix). Production `main.py` adds BOTH `<repo>/` and `<repo>/src/` to `sys.path`; the two import forms resolve as DISTINCT module objects with DISTINCT enum classes. Verified live on Pi:

```
A.BATTERY == B.BATTERY:  False
```

The orchestrator's `_tickBody` compared `currentSource != _PS.BATTERY` where `_PS` came from `src.pi.X` while UpsMonitor's polling thread delivered `pi.X.PowerSource.BATTERY`. Equality always False; ladder bailed every tick across 9 drain tests. The misleading log message `reason=power_source!=BATTERY` actually fires for the UNKNOWN-or-unequal path; EXTERNAL comparison ALSO failed for the same reason.

Why this hid for 4 sprints: tests import via a single consistent path (usually `from src.pi.X`), so within tests only one module object exists and enum equality works. The bug requires BOTH paths loaded, which only happens in production. The display showed correct VCELL/SOC values because dashboard reads numerics directly with no inter-module enum comparison.

---

## V0.24.1 fix surface (six things shipped)

1. **Self-aliasing guard in `src/pi/hardware/ups_monitor.py`** — registers the module under BOTH `pi.hardware.ups_monitor` and `src.pi.hardware.ups_monitor` in `sys.modules` at first load. Subsequent imports under either name return the same module object, restoring enum identity across the boundary. This is the surgical kill of the bug class regardless of which prefix any consumer happens to use.

2. **`src/pi/power/orchestrator.py` imports normalized** to no-prefix paths (matches the polling-thread side). Belt-and-suspenders alongside (1).

3. **Boot-time canary** `_verifyOrchestratorCallbackWiring` in `lifecycle.py`: after `_subscribeOrchestratorToUpsMonitor`, fires a synthetic transition through the registered callback chain and ERROR-logs if `orchestrator._powerSource` does not equal `PowerSource.BATTERY`. **This canary fired PASSED on every restart during Drain 10** (verified across 3 boot events in the journal).

4. **Loud bails for required wiring** (per US-281 anti-pattern doc):
   - 4 silent-skip paths in `_initializePowerDownOrchestrator` upgraded DEBUG/INFO → WARNING with "ladder will not fire; graceful shutdown disarmed" messaging.
   - 3 silent-skip paths in `_subscribeOrchestratorToUpsMonitor` upgraded DEBUG → WARNING with same messaging.
   Production runs INFO; prior DEBUG bails were invisible in journalctl.

5. **`scripts/drain_log_simple.sh`** ships per Spool's request — independent baseline-truth bash logger talking directly to MAX17048 via i2cget + vcgencmd. ZERO shared code path with the production Python service. Cross-correlate against `scripts/drain_forensics.py` to validate the production logger.

6. **`tests/pi/regression/test_powersource_module_identity.py`** — 5 tests across 2 classes. Imports orchestrator via `src.pi.power.orchestrator` and PowerSource via `pi.hardware.ups_monitor`. Pre-fix MUST FAIL (3/3 ladder-firing tests bail with `state==NORMAL`); post-fix MUST PASS. Regression gate for any future re-introduction of the dual-import bug.

---

## Drain Test 10 timeline (interesting artifact)

- **08:18:46** wall power pulled, UpsMonitor logged `external -> battery`
- **08:21:08** ladder fired NORMAL → WARNING at VCELL 3.689V (right at threshold crossing)
- **08:28:25-08:28:33** `deploy-pi.sh` ran mid-drain (CIO redeployment / timer), idempotent service restart at 08:28:33
- **08:28:29** WARNING → IMMINENT at 3.508V (under original PID 44879)
- **08:28:33** systemd restarted eclipse-obd (deploy script triggered, NOT the ladder); new PID 47921
- **08:29:09 + 08:29:34** new instance correctly re-fired WARNING + IMMINENT under fall-through logic (state machine restarted but VCELL still below thresholds)
- **08:34:09** TRIGGER at 3.410V — `_enterTrigger | initiating poweroff` — `subprocess.run([systemctl, poweroff])` called
- **~08:34** Pi powered off cleanly
- **~08:35** Pi rebooted, V0.24.1 self-test PASSED on boot canary

The deploy-mid-drain was actually a useful stress test. It proved the orchestrator handles a service restart on battery correctly: the new PID came up, the wiring self-test PASSED, the ladder re-fired all three stages from NORMAL → TRIGGER without losing the safety invariant.

---

## Spec updates

Added to `specs/anti-patterns.md` under "Hardware/Import Anti-Patterns":
- New entry: **Cross-Module Module Identity (Dual sys.path Resolution)** documenting the Python footgun where a single source file loaded under two module names produces two distinct enum classes that never compare equal across the boundary. Includes the self-aliasing guard pattern as the surgical fix.

`specs/methodology.md` "Integration Tests for Runtime-Verifiable Bugs" subsection (Sprint 21 US-256) is now ratified by Drain 10 — the regression test in `tests/pi/regression/test_powersource_module_identity.py` is the canonical example of an integration test that exercises actual production import paths, not mocked-clean unit-test paths.

---

## Carryforward / housekeeping for you

1. **Hotfix branch on remote**: `hotfix/V0.24.1-ladder-enum-identity` is pushed but I did not merge to main. CIO did the merge + deploy himself. If you check git log on main, V0.24.1 should already be there as a fast-forward or merge commit.

2. **`.deploy-version` on the Pi reads V0.24.1 / gitHash dcf4b60** — confirms the hotfix is the live deployed code.

3. **Story-counter / sprint contract**: this hotfix had no US- number assigned. CIO authorized direct hotfix scope (waiving sprint contract per CIO 2026-05-03 directive). If you want a retroactive US- number for the audit trail, the work touched: `src/pi/hardware/ups_monitor.py` (self-alias), `src/pi/power/orchestrator.py` (no-prefix imports), `src/pi/obdii/orchestrator/lifecycle.py` (canary + loud bails), `src/pi/hardware/hardware_manager.py` (loud bails), `deploy/RELEASE_VERSION` (V0.24.1), `scripts/drain_log_simple.sh` (new), `tests/pi/regression/test_powersource_module_identity.py` (new), plus three Spool inbox notes archived. 437 pi tests + 10 common + 55 release-versioning + 18 drain-forensics deploy = 520 tests pass.

4. **Open carryforward items that are now CLOSED by Drain 10**:
   - Drain Test 7/8/9/10 needed (closed — Drain 10 passed)
   - 9-drain saga (closed)
   - The runtime-validation gate (`feedback_runtime_validation_required.md`) is upheld by the post-fix regression test plus the drain itself
   - B-043 PowerLossOrchestrator full lifecycle (effectively closed at the Pi-app layer; the only remaining gating work is the CIO hardware task to wire the Pi to ignition-switched line)

5. **Open carryforward items that are STILL OPEN**:
   - Drive 6 cold-start lifecycle empirical run (US-260 gate)
   - Phantom-path drift in sprint.json template-generator audit
   - B-041 Excel Export CLI grooming (3 open Qs)
   - B-046 Timing-baseline recalibration (still blocked on ECMLink V3 install)
   - Stale local sprint branches (CIO call on remote delete)

6. **Suggestion**: when you do the next sprint kickoff, the saga-closed status is worth noting in MEMORY.md "Current State" so future-you doesn't have to reconstruct the timeline. I've already updated my own auto-memory; you may want to mirror.

---

— Rex
