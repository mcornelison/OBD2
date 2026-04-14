# src/pi/obd/orchestrator/ — Application Orchestrator Package

A 9-file mixin package composing a single `ApplicationOrchestrator` class.
Created in **Sweep 5** of the reorganization to resolve **TD-003** — the
original `orchestrator.py` had grown to 2501 lines before the split.

## Architecture — mixin composition

```python
class ApplicationOrchestrator(
    LifecycleMixin,
    SignalHandlerMixin,
    HealthMonitorMixin,
    BackupCoordinatorMixin,
    ConnectionRecoveryMixin,
    EventRouterMixin,
):
    ...
```

The core class lives in `core.py`. Each mixin owns one cohesive slice of
responsibility. All mixins use the literal `logging.getLogger("pi.obd.orchestrator")`
(not `__name__`) so `caplog` tests that filter by logger name keep working
regardless of which file the log call came from.

## Module map

| Module | Lines | Role |
|---|---:|---|
| `__init__.py` | 75 | Re-exports all 16 original `__all__` symbols — backward compat for existing `from src.pi.obd.orchestrator import X` callers. |
| `types.py` | 153 | Exceptions, `HealthCheckStats` dataclass, `DEFAULT_RECONNECT_DELAYS = [1, 2, 4, 8, 16]`. |
| `core.py` | 607 | `ApplicationOrchestrator` class itself — `__init__`, `runLoop`, `getStatus`, `createOrchestratorFromConfig` factory. The composition root. |
| `lifecycle.py` | 767 | `LifecycleMixin` — 12 `_initialize*` methods + 12 `_shutdown*` methods in dependency order, plus `COMPONENT_INIT_ORDER` / `COMPONENT_SHUTDOWN_ORDER` constants. Paired setup/teardown is the single-file contract. |
| `event_router.py` | 433 | `EventRouterMixin` — 5 callback chains (reading, drive, alert, analysis, profile). Each chain is short but the set of 5 is a natural unit. |
| `backup_coordinator.py` | 348 | `BackupCoordinatorMixin` — backup init, catchup, schedule, upload, cleanup. Cohesive backup lifecycle. |
| `connection_recovery.py` | 307 | `ConnectionRecoveryMixin` — reconnect with exponential backoff `[1, 2, 4, 8, 16]` seconds. Pause/resume. |
| `health_monitor.py` | 189 | `HealthMonitorMixin` — health checks, data rate tracking. |
| `signal_handler.py` | 112 | `SignalHandlerMixin` — SIGINT/SIGTERM handling, double-Ctrl+C pattern. |

Five of the modules exceed the 300-line soft cap. They're listed in the
`src/README.md` size-exemption block with rationale — splitting further would
scatter cohesive units (init/shutdown pairs, callback sets, recovery protocol)
across files and obscure the 12-component lifecycle contract.

## Backwards compatibility

Existing call sites that do
`from src.pi.obd.orchestrator import ApplicationOrchestrator` still work via
`__init__.py`. No consumer outside this package knows it's now a package
rather than a file.
