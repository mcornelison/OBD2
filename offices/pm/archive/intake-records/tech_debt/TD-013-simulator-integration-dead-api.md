# TD-013 — Simulator integration helper calls non-existent DriveScenarioRunner API

**Filed:** 2026-04-17 (Session 34, Rex / Ralph agent, during US-177)
**Severity:** Low — dead code path, not currently reachable from `main.py --simulate`
**Triggering story:** US-177 (Pi Crawl — Simulator validation on ARM)

## Summary

`src/pi/obd/integration_operations.py` has two call sites that invoke methods
on `DriveScenarioRunner` that do not exist on the class. Neither path is
exercised by the simulator validation done in US-177 (it goes straight
through `main.py --simulate` which does not load scenarios), so they were not
fixed in-story per scope discipline. Filing for PM to decide whether to
groom into a cleanup story or leave until someone wires the simulator
integration into the orchestrator for real.

## Specifics

### 1. `registerCallbacks(...)` — method does not exist

`src/pi/obd/integration_operations.py:167-170` — inside `createScenarioRunner()`:

```python
runner.registerCallbacks(
    onPhaseStart=lambda phase: logger.info(f"Scenario phase: {phase.name}"),
    onScenarioComplete=onScenarioComplete,
)
```

But `DriveScenarioRunner` (`src/pi/obd/simulator/scenario_runner.py`) exposes
callbacks as **attributes**, not via a `registerCallbacks(...)` method:

```python
# scenario_runner.py lines 107-110
self.onPhaseStart: Callable[[DrivePhase], None] | None = None
self.onPhaseEnd: Callable[[DrivePhase], None] | None = None
self.onScenarioComplete: Callable[[], None] | None = None
self.onLoopComplete: Callable[[int], None] | None = None
```

Calling `runner.registerCallbacks(...)` raises `AttributeError`.

### 2. `getState()` — method does not exist

`src/pi/obd/integration_operations.py:188` — inside `isScenarioRunnerActive()`:

```python
return runner.getState() == ScenarioState.RUNNING
```

`DriveScenarioRunner` exposes `state` as an **attribute**, not a getter:

```python
# scenario_runner.py line 94
self.state = ScenarioState.IDLE
```

Calling `runner.getState()` raises `AttributeError`.

## Why this didn't block US-177

`integration_operations.py` is imported by
`src/pi/obd/simulator_integration.py`, which is the "wire scenarios into the
orchestrator" helper. `main.py --simulate` does **not** load scenarios — it
spins up the orchestrator with a plain `SimulatedObdConnection` (which
internally creates an idle `SensorSimulator`). Drive detection sees the
~800 rpm idle and that's enough to trigger `drive_start` for existing e2e
tests. No one is currently calling `createScenarioRunner(...)` or
`isScenarioRunnerActive(...)` from a live code path.

The US-177 regression test (`tests/pi/simulator/test_scenario_arm.py`) bypasses
`integration_operations.py` entirely — it constructs `DriveScenarioRunner`
directly and uses the attribute form for callbacks, which is the shape the
class actually supports.

## Suggested fix

Either:

**Option A — bring integration_operations.py into line with the class shape
(smallest change, 2 edits):**

```python
# integration_operations.py ~167 — replace registerCallbacks(...) with
runner.onPhaseStart = lambda phase: logger.info(f"Scenario phase: {phase.name}")
runner.onScenarioComplete = onScenarioComplete

# integration_operations.py:188 — replace runner.getState() with
return runner.state == ScenarioState.RUNNING
```

**Option B — add the missing methods to DriveScenarioRunner (more work but
keeps the integration_operations.py helper readable):**

```python
# scenario_runner.py
def registerCallbacks(self, **callbacks) -> None:
    for name, fn in callbacks.items():
        if hasattr(self, name):
            setattr(self, name, fn)

def getState(self) -> ScenarioState:
    return self.state
```

Option A is simpler and preserves the established "callbacks are attributes"
idiom.

## Scope

- No functional change to anything `main.py --simulate` executes today.
- Gets `simulator_integration.py` back into a runnable state if/when a future
  story wires scenarios into the orchestrator for real (e.g., to drive a
  CIO demo or a deterministic canary drive).
- ~3 line edit, regression-safe.

## Related

- US-177 completion note (Sprint 10) — how the discovery was made.
- `src/pi/obd/simulator_integration.py` — consumer of `integration_operations.py`.
