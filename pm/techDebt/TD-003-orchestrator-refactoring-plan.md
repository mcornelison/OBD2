# Tech Debt: Orchestrator Refactoring Plan

**Reported by**: Rex (Agent 1)
**Date**: 2026-01-29
**Priority**: High
**Type**: Refactoring

---

## Summary

Deep-dive analysis of `src/obd/orchestrator.py` (2,500 lines) identified a concrete 7-module split plan. This is the single largest file in the codebase and the #1 tech debt item. `tests/test_orchestrator.py` (7,516 lines) would need a parallel split.

## Current State

- **1 god class**: ApplicationOrchestrator with 70+ methods, 40+ instance variables
- **12 component dependencies**: Database, ProfileManager, Connection, VinDecoder, DisplayManager, HardwareManager, StatisticsEngine, DriveDetector, AlertManager, DataLogger, ProfileSwitcher, BackupManager
- **12 responsibility areas**: lifecycle, signals, main loop, event routing, connection recovery, health monitoring, status reporting, display updates, VIN decoding, backup management, hardware integration, config extraction

## Proposed Split

```
src/obd/orchestrator/
├── __init__.py                # Re-export ApplicationOrchestrator
├── types.py                   # ShutdownState, HealthCheckStats, exceptions (~100 lines)
├── core.py                    # Main class, __init__, runLoop, getStatus, properties (~750 lines)
├── lifecycle.py               # 12 _initialize*() + 13 _shutdown*() methods (~400 lines)
├── connection_recovery.py     # Reconnect with backoff, pause/resume (~350 lines)
├── event_router.py            # Callback registration, all _handle*() methods (~400 lines)
├── backup_coordinator.py      # Init, catchup, scheduling, upload, cleanup (~300 lines)
├── health_monitor.py          # Health checks, stats, data rate tracking (~200 lines)
└── signal_handler.py          # SIGINT/SIGTERM, double-Ctrl+C pattern (~100 lines)
```

## Key Architectural Details to Preserve

### Component Init Order (dependency chain)
```
Database -> ProfileManager -> Connection -> VinDecoder -> DisplayManager ->
HardwareManager -> StatisticsEngine -> DriveDetector -> AlertManager ->
DataLogger -> ProfileSwitcher -> BackupManager
```

### Shutdown Order (reverse of init)
```
BackupManager -> DataLogger -> AlertManager -> DriveDetector -> StatisticsEngine ->
HardwareManager -> DisplayManager -> VinDecoder -> Connection -> ProfileSwitcher ->
ProfileManager -> Database
```

### Data Flow (callback chains)
- Reading: DataLogger -> Orchestrator -> DisplayManager + DriveDetector + AlertManager
- Drive: DriveDetector -> Orchestrator -> DisplayManager + external callback
- Alert: AlertManager -> Orchestrator -> DisplayManager + HardwareManager + external
- Analysis: StatisticsEngine -> Orchestrator -> DisplayManager + external
- Profile: ProfileSwitcher -> Orchestrator -> AlertManager + DataLogger

## Good Patterns to Keep
- Graceful fallbacks (HARDWARE_AVAILABLE, BACKUP_AVAILABLE flags)
- Dependency-ordered init, reverse-order shutdown
- Timeout-based shutdown with force-exit
- Exponential backoff for reconnection
- Double-Ctrl+C (graceful then force)
- Non-critical errors logged as warnings, don't crash

## Risks
- Test file (7,516 lines) must be split in parallel
- Backward compatibility via __init__.py re-exports
- Component wiring touches all modules -- integration testing critical
- Threading coordination (reconnect thread, backup timer) needs careful extraction

---

*Submitted by Rex via pm/techDebt/ per established protocol.*
