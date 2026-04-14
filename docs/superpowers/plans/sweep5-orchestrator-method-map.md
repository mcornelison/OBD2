# Sweep 5 Task 2 — Orchestrator Method Map

Internal scratch file tracking every symbol in `src/pi/obd/orchestrator.py` (2501 lines)
and its target module in the new package. Deleted in Task 6 cleanup.

## types.py

Pure data/type definitions — no behavior, no `self`.

- `ShutdownState` (Enum) — lifecycle state machine values (RUNNING / SHUTDOWN_REQUESTED / FORCE_EXIT)
- `HealthCheckStats` (dataclass) — runtime counters and uptime stats
- `OrchestratorError` (Exception) — base exception with component attribute
- `ComponentInitializationError` — init failure
- `ComponentStartError` — start failure
- `ComponentStopError` — stop failure
- `DEFAULT_SHUTDOWN_TIMEOUT` — 5.0s
- `DEFAULT_HEALTH_CHECK_INTERVAL` — 60.0s
- `DEFAULT_DATA_RATE_LOG_INTERVAL` — 300.0s
- `DEFAULT_CONNECTION_CHECK_INTERVAL` — 5.0s
- `DEFAULT_RECONNECT_DELAYS` — [1,2,4,8,16]
- `DEFAULT_MAX_RECONNECT_ATTEMPTS` — 5
- `EXIT_CODE_CLEAN` — 0
- `EXIT_CODE_FORCED` — 1
- `EXIT_CODE_ERROR` — 2

## signal_handler.py (SignalHandlerMixin)

- `registerSignalHandlers` — install SIGINT/SIGTERM handlers
- `restoreSignalHandlers` — revert to originals
- `_handleShutdownSignal` — first signal requests graceful, second forces exit

## health_monitor.py (HealthMonitorMixin)

- `_performHealthCheck` — compute stats, log HEALTH CHECK line
- `_collectComponentStats` — pull counters from dataLogger/driveDetector
- `_logDataLoggingRate` — 5-min interval rate log
- `getHealthCheckStats` — public getter
- `setHealthCheckInterval` — public setter with validation

## backup_coordinator.py (BackupCoordinatorMixin)

- `_initializeBackupManager` — read config, build BackupManager + uploader, kick off catchup + schedule
- `_performCatchupBackupCheck` — detect stale backup on startup
- `_performBackup` — run local backup + upload + cleanup
- `_scheduleNextBackup` — set up daily Timer
- `_runScheduledBackup` — timer callback, runs and reschedules
- `_shutdownBackupManager` — cancel timer, clear refs
- `_getBackupStatus` — build backup status dict (called by getStatus in core)

Note: `_initializeBackupManager` is also an init method (component order #12), but the
entire backup subsystem lives together for cohesion. Lifecycle list references this
method via `self._initializeBackupManager()`.

## connection_recovery.py (ConnectionRecoveryMixin)

- `_startReconnection` — kick off background reconnect thread
- `_reconnectionLoop` — main backoff loop running in thread
- `_attemptReconnection` — single reconnect try (reconnect() preferred, disconnect+connect fallback)
- `_handleReconnectionSuccess` — resume logging, update state
- `_handleReconnectionFailure` — mark disconnected after max retries
- `_pauseDataLogging` — stop data logger during reconnection
- `_resumeDataLogging` — restart data logger after reconnection
- `_checkConnectionStatus` — poll connection.isConnected()

## event_router.py (EventRouterMixin)

- `registerCallbacks` — public: register external event handlers
- `_setupComponentCallbacks` — wire internal handlers into all 5 components
- `_handleDriveStart` — drive start → display + external cb
- `_handleDriveEnd` — drive end → display + external cb
- `_handleAlert` — alert → display + hardware + external cb + stats
- `_handleAnalysisComplete` — analysis → display + external cb
- `_handleAnalysisError` — analysis error → log + stats
- `_handleReading` — reading → display + drive detector + alert manager
- `_handleLoggingError` — logging error → log + stats
- `_handleProfileChange` — profile switch → alert manager + data logger
- `_handleConnectionLost` — connection lost → display + hardware + external + start reconnect
- `_handleConnectionRestored` — connection up → display + hardware + external

## lifecycle.py (LifecycleMixin)

Module constants:
- `COMPONENT_INIT_ORDER` — ordered list of 12 component names
- `COMPONENT_SHUTDOWN_ORDER` — reversed copy

Init methods:
- `_initializeAllComponents` — calls all 12 init methods in order (plus VIN decode hook)
- `_initializeDatabase`
- `_initializeProfileManager`
- `_initializeConnection`
- `_performFirstConnectionVinDecode` — VIN decode hook between connection and display
- `_displayVehicleInfo` — helper for the VIN decode hook
- `_initializeVinDecoder`
- `_initializeDisplayManager`
- `_createHeadlessDisplayFallback`
- `_initializeHardwareManager`
- `_startHardwareManager` — deferred start from runLoop
- `_initializeStatisticsEngine`
- `_initializeDriveDetector`
- `_initializeAlertManager`
- `_initializeDataLogger`
- `_initializeProfileSwitcher`
- `_initializeBackupManager` — actually lives in backup_coordinator.py, shared via mixin inheritance

Shutdown methods:
- `_stopComponentWithTimeout` — generic shutdown helper with force-exit check
- `_shutdownAllComponents` — calls all shutdown methods in reverse order
- `_shutdownDataLogger`
- `_shutdownAlertManager`
- `_shutdownDriveDetector`
- `_shutdownStatisticsEngine`
- `_shutdownHardwareManager`
- `_shutdownDisplayManager`
- `_shutdownVinDecoder`
- `_shutdownConnection`
- `_shutdownProfileSwitcher`
- `_shutdownProfileManager`
- `_shutdownDatabase`
- `_shutdownBackupManager` — actually lives in backup_coordinator.py, shared via mixin inheritance
- `_cleanupPartialInitialization`

## core.py (ApplicationOrchestrator)

- `__init__` — instantiate state, read config sections, initialize callback refs
- `_extractDashboardParameters` — parse realtimeData config for display params (config helper, stays with __init__ state)
- Properties: `database`, `connection`, `dataLogger`, `driveDetector`, `alertManager`, `displayManager`, `statisticsEngine`, `profileManager`, `profileSwitcher`, `vinDecoder`, `hardwareManager`, `backupManager`, `exitCode`, `shutdownState`
- `isRunning`
- `getStatus` — build component status dict, delegate backup status to mixin helper
- `_getComponentStatus` — helper used by getStatus
- `start` — public lifecycle start
- `stop` — public lifecycle stop
- `runLoop` — main application loop

Factory:
- `createOrchestratorFromConfig` — module-level factory, re-exported via __init__

## __init__.py

Re-exports everything that was in `__all__`:
- `ApplicationOrchestrator`
- `HealthCheckStats`
- `ShutdownState`
- `OrchestratorError`, `ComponentInitializationError`, `ComponentStartError`, `ComponentStopError`
- `DEFAULT_SHUTDOWN_TIMEOUT`, `DEFAULT_HEALTH_CHECK_INTERVAL`, `DEFAULT_DATA_RATE_LOG_INTERVAL`,
  `DEFAULT_CONNECTION_CHECK_INTERVAL`, `DEFAULT_RECONNECT_DELAYS`, `DEFAULT_MAX_RECONNECT_ATTEMPTS`
- `EXIT_CODE_CLEAN`, `EXIT_CODE_FORCED`, `EXIT_CODE_ERROR`
- `createOrchestratorFromConfig`

Also re-export the module-level `HARDWARE_AVAILABLE` / `BACKUP_AVAILABLE` flags and
the try/except import of `HardwareManager`/`BackupManager` stays in lifecycle.py (where
the initialize methods that need them live) OR core.py module scope if we want them
visible at package-level for test patching. Tests don't patch them, so keep them
private to the module that uses them.

## Special cases / judgment calls

1. **`_initializeBackupManager` and `_shutdownBackupManager`**: These are "lifecycle"
   methods by strict category, but they live alongside the rest of the backup code
   in `backup_coordinator.py` for cohesion. Since `ApplicationOrchestrator` inherits
   from both `LifecycleMixin` and `BackupCoordinatorMixin`, `_initializeAllComponents`
   in lifecycle.py can still call `self._initializeBackupManager()` because MRO
   resolves it from the backup mixin.

2. **`_performFirstConnectionVinDecode` and `_displayVehicleInfo`**: These run during
   init (between `_initializeConnection` and `_initializeDisplayManager`), so they
   live in `lifecycle.py` with the other init methods.

3. **`_checkConnectionStatus`**: Used by both `runLoop` (detect state changes) and
   `_performHealthCheck` and `_handleConnectionLost`. Put it in `connection_recovery.py`
   because it's used by the recovery code and the loop just calls it; mixin lookup
   handles access from elsewhere.

4. **`_extractDashboardParameters`**: Called only from `__init__`. Stays in `core.py`.

5. **`_getComponentStatus`**: Called only from `getStatus`. Stays in `core.py`.

6. **`_getBackupStatus`**: Called from `getStatus` in core but lives in
   `backup_coordinator.py` for cohesion (accesses `_backupManager`, `_googleDriveUploader`).

7. **`HARDWARE_AVAILABLE` / `BACKUP_AVAILABLE` try/except imports**: Live in
   `lifecycle.py` module scope (used by the initialize methods) and `backup_coordinator.py`
   module scope (used by `_initializeBackupManager`). Each module has its own
   conditional import.

## Head count
Source file: 2501 lines
Method signatures (def) in original: TBD — will count before/after to confirm no
methods lost.
