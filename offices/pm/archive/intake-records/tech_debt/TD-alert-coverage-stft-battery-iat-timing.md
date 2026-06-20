# TD: Alert coverage gap — STFT / battery voltage / IAT / timing advance

**Filed**: 2026-04-13
**Filed by**: Ralph (during Sweep 2a Task 2 investigation)
**Severity**: Medium — safety-relevant parameters not firing user alerts

## Finding

The tiered alert evaluation modules for STFT, battery voltage, IAT, and timing advance are fully
implemented and well-tested, but none of them are wired to any runtime call site. Their results
never reach the user (display, log, audio, AlertManager, drive summary, or recommendations).

By contrast, RPM and coolant temp DO fire: `primary_screen.py` calls `evaluateRPM` and
`evaluateCoolantTemp` directly for display color, and AlertManager fires legacy threshold checks
for `rpmRedline` and `coolantTempCritical` on every polled value.

## Evidence

- `evaluateSTFT` (`src/alert/tiered_thresholds.py:319`): no call site in `src/` outside its
  own definition. Exported from `src/alert/__init__.py:155` but never imported by any runtime module.

- `evaluateBatteryVoltage` (`src/alert/tiered_thresholds.py:443`): no call site in `src/`
  outside its own definition. Exported but never imported by any runtime module.

- `IATSensorTracker` (`src/alert/iat_thresholds.py:142`): wraps `evaluateIAT()` with
  sensor-failure detection logic. Well-designed. Never instantiated in any runtime path.
  Only instantiated in `tests/test_iat_thresholds.py`.

- `TimingRetardTracker` (`src/alert/timing_thresholds.py:113`): baseline-learning, knock-pattern-
  detecting evaluator for timing advance. Never instantiated in any runtime path. Only instantiated
  in `tests/test_timing_thresholds.py`.

- `fuel_detail.py` (`src/display/screens/fuel_detail.py:235`): defines its own `_evaluateFuelTrim()`
  with hardcoded thresholds, bypassing the config-driven `evaluateSTFT()` entirely.

## Impact

The following safety-relevant conditions do not fire any user-visible alert today:

- **STFT out of range**: short-term fuel trim excursions indicating running rich or lean are silently
  ignored. On a forced-induction engine, sustained STFT deviation can indicate injector issues or
  boost leaks.
- **Battery voltage out of range**: charging system problems (dead alternator, failing battery) are
  silently ignored. Voltage below ~12.0V or above ~15.0V is never flagged to the driver.
- **IAT danger**: high intake air temperature (>160°F) degrading charge density and knock threshold
  is never flagged. The IAT sensor-failure detection (consecutive -40°F readings) also never fires.
- **Timing advance retard**: knock-induced timing retard — the ECU's primary knock protection signal —
  is never flagged. The pattern detection (repeated retard at same RPM/load band) also never fires.

## Suggested remediation

Two approaches, not mutually exclusive:

1. **Wire STFT and battery voltage through AlertManager** (simpler path). After Sweep 2a rewires
   AlertManager to consume `tieredThresholds`, add a second evaluation layer: after the standard
   `checkValue()` call in `orchestrator._handleOBDReading()`, also invoke `evaluateSTFT()` and
   `evaluateBatteryVoltage()` and convert `TieredThresholdResult` to `AlertEvent`. This avoids
   redesigning AlertManager's interface.

2. **Wire IAT via `IATSensorTracker` and timing via `TimingRetardTracker`** (requires orchestrator
   state). These evaluators are stateful — they must persist across polling cycles. The orchestrator
   (or a new `TieredAlertCoordinator` helper) needs to own tracker instances, initialize them with
   loaded thresholds at startup, and call `.evaluate()` per poll. Timing advance also requires RPM
   and load alongside the value, which `orchestrator._handleOBDReading()` does not currently provide
   as a batch — may need `checkValues()` refactoring or a new multi-param evaluation callback.

3. **Wire `fuel_detail.py` to use `evaluateSTFT()`** to eliminate the hardcoded thresholds and
   align display coloring with the config-driven evaluation.

Priority order: battery voltage and STFT are the lowest-effort wins (stateless evaluators, same
`checkValue(paramName, value)` signature pattern). IAT and timing require stateful plumbing.

## Related

- Sweep 2a audit notes: `docs/superpowers/plans/sweep2-audit-notes.md`
- Sweep 2a plan: `docs/superpowers/plans/2026-04-13-reorg-sweep2a-rewire.md`
- PM inbox note: `offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md`
- Tiered thresholds modules: `src/alert/tiered_thresholds.py`, `src/alert/iat_thresholds.py`,
  `src/alert/timing_thresholds.py`
