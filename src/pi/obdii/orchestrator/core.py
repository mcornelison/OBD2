################################################################################
# File Name: core.py
# Purpose/Description: ApplicationOrchestrator class — the composed facade of
#                      all orchestrator mixins
# Author: Ralph Agent
# Creation Date: 2026-04-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-14    | Ralph Agent  | Sweep 5 Task 2: extracted from orchestrator.py
#               |              | as the composition root for all mixins
# 2026-04-23    | Ralph (Rex)  | US-226: add _syncClient attribute + interval-
#               |              | based sync trigger in runLoop.  Cadence
#               |              | driven by pi.sync.intervalSeconds; fires
#               |              | independently of drive_end (defensive
#               |              | design given US-229 drive_end bug).
# 2026-04-23    | Ralph (Rex)  | US-232 / TD-035: shared _shutdownEvent
#               |              | threading.Event plumbed into ObdConnection
#               |              | + ReconnectLoop so backoff sleeps wake
#               |              | within ~ms of SIGTERM.
# ================================================================================
################################################################################

"""
ApplicationOrchestrator for Eclipse OBD-II Performance Monitoring System.

This module contains the ApplicationOrchestrator class composed from the
LifecycleMixin, SignalHandlerMixin, HealthMonitorMixin, BackupCoordinatorMixin,
ConnectionRecoveryMixin, and EventRouterMixin. It owns construction, the
public start/stop/runLoop API, and status reporting.

Usage:
    from pi.obdii.orchestrator import ApplicationOrchestrator

    orchestrator = ApplicationOrchestrator(config=config, simulate=False)

    orchestrator.start()
    if orchestrator.isRunning():
        status = orchestrator.getStatus()
    orchestrator.stop()
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..database import ObdDatabase
from .backup_coordinator import BackupCoordinatorMixin
from .bt_resilience import BtResilienceMixin
from .connection_recovery import ConnectionRecoveryMixin
from .event_router import EventRouterMixin
from .health_monitor import HealthMonitorMixin
from .lifecycle import LifecycleMixin
from .signal_handler import SignalHandlerMixin
from .types import (
    DEFAULT_CONNECTION_CHECK_INTERVAL,
    DEFAULT_DATA_RATE_LOG_INTERVAL,
    DEFAULT_HEALTH_CHECK_INTERVAL,
    DEFAULT_MAX_RECONNECT_ATTEMPTS,
    DEFAULT_RECONNECT_DELAYS,
    DEFAULT_SHUTDOWN_TIMEOUT,
    EXIT_CODE_CLEAN,
    EXIT_CODE_FORCED,
    HealthCheckStats,
    OrchestratorError,
    ShutdownState,
)

# Unified logger name matches the original monolith module so existing tests
# that filter caplog by logger name continue to work unchanged.
logger = logging.getLogger("pi.obdii.orchestrator")


# ================================================================================
# ApplicationOrchestrator Class
# ================================================================================

class ApplicationOrchestrator(  # type: ignore[misc]
    LifecycleMixin,
    SignalHandlerMixin,
    HealthMonitorMixin,
    BackupCoordinatorMixin,
    ConnectionRecoveryMixin,
    BtResilienceMixin,
    EventRouterMixin,
):
    """
    Central orchestrator for the OBD-II monitoring application.

    Manages the lifecycle of all system components, handling initialization,
    startup, shutdown, and status reporting. Components are initialized in
    dependency order and shut down in reverse order.

    Initialization Order:
    1. database
    2. profileManager
    3. connection
    4. vinDecoder
    5. displayManager
    6. hardwareManager
    7. statisticsEngine
    8. driveDetector
    9. alertManager
    10. dataLogger
    11. profileSwitcher
    12. backupManager

    Shutdown Order (reverse of init):
    backupManager → profileSwitcher → dataLogger → alertManager → driveDetector
    → statisticsEngine → hardwareManager → displayManager → vinDecoder
    → connection → profileManager → database

    Example:
        config = loadObdConfig('config.json')
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        try:
            orchestrator.start()
            # Application runs...
        finally:
            orchestrator.stop()
    """

    # ================================================================================
    # Construction
    # ================================================================================

    def __init__(self, config: dict[str, Any], simulate: bool = False):
        """
        Initialize the application orchestrator.

        Args:
            config: Configuration dictionary with all component settings
            simulate: If True, use simulated OBD-II connection instead of real hardware
        """
        self._config = config
        self._simulate = simulate
        self._running = False

        # Component references - all start as None
        self._database: ObdDatabase | None = None
        self._connection: Any | None = None
        self._dataLogger: Any | None = None
        self._driveDetector: Any | None = None
        self._alertManager: Any | None = None
        self._displayManager: Any | None = None
        self._statisticsEngine: Any | None = None
        self._profileManager: Any | None = None
        self._profileSwitcher: Any | None = None
        self._vinDecoder: Any | None = None
        self._hardwareManager: Any | None = None
        self._backupManager: Any | None = None
        self._googleDriveUploader: Any | None = None
        # US-204: DTC logger + MIL rising-edge tracker.  Both stay None
        # when DTC capture is disabled in config (live-OBD path enables
        # by default; replay/simulator paths leave them off).
        self._dtcLogger: Any | None = None
        self._milEdgeDetector: Any | None = None
        # US-206: SummaryRecorder for drive-start metadata (ambient
        # IAT, starting battery, barometric).  Opt-out via
        # ``pi.driveSummary.enabled=false``.
        self._summaryRecorder: Any | None = None
        # US-226: SyncClient for the interval-based Pi->server sync
        # trigger in runLoop.  Opt-out via ``pi.sync.enabled=false``;
        # also stays None when the companion service itself is
        # disabled or misconfigured (API key missing).  The runLoop
        # trigger observes ``None`` as a no-op.
        self._syncClient: Any | None = None
        # Interval-sync cadence state (ticks whenever runLoop pass
        # observes intervalSeconds elapsed since the previous push).
        # None before runLoop starts so the very first interval lines
        # up with the first post-boot tick, not boot-instant.
        self._lastSyncAttemptTime: datetime | None = None
        syncConfig = config.get('pi', {}).get('sync', {})
        self._syncIntervalSeconds: float = float(
            syncConfig.get('intervalSeconds', 60)
        )
        self._syncTriggerOn: list[str] = list(
            syncConfig.get('triggerOn', ['interval'])
        )

        # Backup scheduling state
        self._backupScheduleTimer: threading.Timer | None = None
        self._lastScheduledBackupCheck: datetime | None = None

        # Shutdown state management
        self._shutdownState = ShutdownState.RUNNING
        self._shutdownTimeout = config.get('pi', {}).get('shutdown', {}).get(
            'componentTimeout', DEFAULT_SHUTDOWN_TIMEOUT
        )
        self._exitCode = EXIT_CODE_CLEAN
        self._originalSigintHandler: Callable[..., Any] | None = None
        self._originalSigtermHandler: Callable[..., Any] | None = None
        # US-232 / TD-035: shared shutdown event plumbed into the OBD
        # connection + ReconnectLoop so their backoff sleeps wake within
        # ~ms of SIGTERM arriving, instead of sleeping through the full
        # retryDelays cap (~60-90s) and forcing systemd to SIGKILL.
        # The signal handler mixin sets this alongside _shutdownState.
        self._shutdownEvent: threading.Event = threading.Event()

        # Main loop configuration
        self._healthCheckInterval = config.get('pi', {}).get('monitoring', {}).get(
            'healthCheckIntervalSeconds', DEFAULT_HEALTH_CHECK_INTERVAL
        )
        self._loopSleepInterval = 0.1  # 100ms between loop iterations

        # Data logging rate log interval (5 minutes default)
        self._dataRateLogInterval = config.get('pi', {}).get('monitoring', {}).get(
            'dataRateLogIntervalSeconds', DEFAULT_DATA_RATE_LOG_INTERVAL
        )
        self._lastDataRateLogTime: datetime | None = None
        self._lastDataRateLogCount: int = 0

        # Parameters to display on dashboard (extracted from realtimeData config)
        self._dashboardParameters: set[str] = self._extractDashboardParameters(config)

        # Statistics tracking for health checks
        self._startTime: datetime | None = None
        self._lastHealthCheckTime: datetime | None = None
        self._healthCheckStats = HealthCheckStats()
        self._lastDataRateCheckTime: datetime | None = None
        self._lastDataRateReadingCount: int = 0

        # Callback handlers for component events
        self._onDriveStart: Callable[[Any], None] | None = None
        self._onDriveEnd: Callable[[Any], None] | None = None
        self._onAlert: Callable[[Any], None] | None = None
        self._onAnalysisComplete: Callable[[Any], None] | None = None
        self._onConnectionLost: Callable[[], None] | None = None
        self._onConnectionRestored: Callable[[], None] | None = None

        # Connection recovery configuration
        bluetoothConfig = config.get('pi', {}).get('bluetooth', {})
        self._connectionCheckInterval = config.get('pi', {}).get('monitoring', {}).get(
            'connectionCheckIntervalSeconds', DEFAULT_CONNECTION_CHECK_INTERVAL
        )
        self._reconnectDelays = bluetoothConfig.get(
            'retryDelays', DEFAULT_RECONNECT_DELAYS
        )
        self._maxReconnectAttempts = bluetoothConfig.get(
            'maxRetries', DEFAULT_MAX_RECONNECT_ATTEMPTS
        )

        # Connection recovery state
        self._isReconnecting = False
        self._reconnectAttempt = 0
        self._lastConnectionCheckTime: datetime | None = None
        self._reconnectThread: threading.Thread | None = None
        self._dataLoggerPausedForReconnect = False
        self._alertsPausedForReconnect = False

        # Vehicle VIN from first connection decode
        self._vehicleVin: str | None = None

        # US-211 BT resilience: optional ReconnectLoop factory override.
        # Production leaves this None (mixin builds loop on demand via
        # live database + MAC + rfcomm device). Tests set it to a zero-
        # arg lambda returning a pre-built loop with injected probe +
        # sleep so handleCaptureError() runs deterministically.
        self._reconnectLoopFactory: Any | None = None

        # US-225 / TD-034: poll-tier pause state for the US-216
        # PowerDownOrchestrator IMMINENT-stage callback.  Separate
        # from _dataLoggerPausedForReconnect so a BT reconnect that
        # overlaps a drain event doesn't fight the power-down path
        # for the resume call.  AC-restore clears this flag and
        # restarts the logger; BT reconnect runs its own path.
        self._pollingPausedForPowerDown: bool = False

        logger.debug("ApplicationOrchestrator initialized")

    # ================================================================================
    # Properties for component access
    # ================================================================================

    @property
    def database(self) -> ObdDatabase | None:
        """Get the database instance."""
        return self._database

    @property
    def connection(self) -> Any | None:
        """Get the OBD connection instance."""
        return self._connection

    @property
    def dataLogger(self) -> Any | None:
        """Get the data logger instance."""
        return self._dataLogger

    @property
    def driveDetector(self) -> Any | None:
        """Get the drive detector instance."""
        return self._driveDetector

    @property
    def alertManager(self) -> Any | None:
        """Get the alert manager instance."""
        return self._alertManager

    @property
    def displayManager(self) -> Any | None:
        """Get the display manager instance."""
        return self._displayManager

    @property
    def statisticsEngine(self) -> Any | None:
        """Get the statistics engine instance."""
        return self._statisticsEngine

    @property
    def profileManager(self) -> Any | None:
        """Get the profile manager instance."""
        return self._profileManager

    @property
    def profileSwitcher(self) -> Any | None:
        """Get the profile switcher instance."""
        return self._profileSwitcher

    @property
    def vinDecoder(self) -> Any | None:
        """Get the VIN decoder instance."""
        return self._vinDecoder

    @property
    def hardwareManager(self) -> Any | None:
        """Get the hardware manager instance (Raspberry Pi only)."""
        return self._hardwareManager

    @property
    def backupManager(self) -> Any | None:
        """Get the backup manager instance."""
        return self._backupManager

    @property
    def syncClient(self) -> Any | None:
        """Get the Pi->server SyncClient instance (US-226).

        ``None`` when ``pi.sync.enabled=false``, when the companion
        service cannot be reached at boot (missing API key), or when
        SyncClient construction raised.  The interval trigger in
        runLoop observes None as a no-op.
        """
        return self._syncClient

    @property
    def shutdownEvent(self) -> threading.Event:
        """Get the shutdown event (US-232 / TD-035).

        Set by the signal-handler mixin when SIGTERM/SIGINT arrives;
        plumbed into :class:`ObdConnection` + :class:`ReconnectLoop` so
        their backoff sleeps wake within ~ms of the signal.
        """
        return self._shutdownEvent

    @property
    def exitCode(self) -> int:
        """Get the exit code for this orchestrator."""
        return self._exitCode

    @property
    def shutdownState(self) -> ShutdownState:
        """Get the current shutdown state."""
        return self._shutdownState

    # ================================================================================
    # State Methods
    # ================================================================================

    def isRunning(self) -> bool:
        """
        Check if the orchestrator is running.

        Returns:
            True if all components are running, False otherwise
        """
        return self._running

    def getStatus(self) -> dict[str, Any]:
        """
        Get the current status of all managed components.

        Returns:
            Dictionary containing:
            - running: bool indicating if orchestrator is running
            - components: dict mapping component names to their status
              ('initialized', 'not_initialized', or component-specific status)
            - hardware: hardware-specific status (if hardware manager available)
        """
        componentStatus = {
            'database': self._getComponentStatus(self._database),
            'connection': self._getComponentStatus(self._connection),
            'dataLogger': self._getComponentStatus(self._dataLogger),
            'driveDetector': self._getComponentStatus(self._driveDetector),
            'alertManager': self._getComponentStatus(self._alertManager),
            'displayManager': self._getComponentStatus(self._displayManager),
            'statisticsEngine': self._getComponentStatus(self._statisticsEngine),
            'profileManager': self._getComponentStatus(self._profileManager),
            'profileSwitcher': self._getComponentStatus(self._profileSwitcher),
            'vinDecoder': self._getComponentStatus(self._vinDecoder),
            'hardwareManager': self._getComponentStatus(self._hardwareManager),
            'backupManager': self._getComponentStatus(self._backupManager),
        }

        result: dict[str, Any] = {
            'running': self._running,
            'components': componentStatus,
        }

        # Add hardware-specific status if available
        if self._hardwareManager is not None:
            try:
                result['hardware'] = self._hardwareManager.getStatus()
            except Exception as e:
                logger.debug(f"Could not get hardware status: {e}")
                result['hardware'] = {'error': str(e)}

        # Add backup-specific status if available
        if self._backupManager is not None:
            try:
                result['backup'] = self._getBackupStatus()
            except Exception as e:
                logger.debug(f"Could not get backup status: {e}")
                result['backup'] = {'error': str(e)}

        return result

    def _getComponentStatus(self, component: Any | None) -> str:
        """
        Get the status string for a component.

        Args:
            component: Component instance or None

        Returns:
            'initialized' if component exists, 'not_initialized' otherwise
        """
        if component is None:
            return 'not_initialized'
        return 'initialized'

    def _extractDashboardParameters(self, config: dict[str, Any]) -> set[str]:
        """
        Extract parameter names that should be displayed on the dashboard.

        Parses the realtimeData.parameters list and returns names of parameters
        that have displayOnDashboard: true.

        Args:
            config: Configuration dictionary with realtimeData section

        Returns:
            Set of parameter names to display on dashboard
        """
        dashboardParams: set[str] = set()
        parameters = config.get('pi', {}).get('realtimeData', {}).get('parameters', [])

        for param in parameters:
            if isinstance(param, dict):
                if param.get('displayOnDashboard', False):
                    name = param.get('name', '')
                    if name:
                        dashboardParams.add(name)

        return dashboardParams

    # ================================================================================
    # Lifecycle Methods
    # ================================================================================

    def start(self) -> None:
        """
        Start the orchestrator and all managed components.

        Initializes and starts all components in dependency order.
        If any component fails to initialize, an OrchestratorError is raised
        and partial initialization is cleaned up.

        Startup can be aborted at any time with Ctrl+C (KeyboardInterrupt).
        Total startup time is logged at completion.

        Raises:
            OrchestratorError: If any component fails to initialize
            KeyboardInterrupt: If startup is aborted by user
        """
        logger.info("Starting ApplicationOrchestrator...")
        startTime = time.time()

        try:
            self._initializeAllComponents()
            self._running = True

            elapsedTime = time.time() - startTime
            logger.info(
                f"ApplicationOrchestrator started successfully | "
                f"startup_time={elapsedTime:.2f}s"
            )

        except KeyboardInterrupt:
            logger.warning("Startup aborted by user (Ctrl+C)")
            self._cleanupPartialInitialization()
            raise

        except Exception as e:
            logger.error(f"Failed to start orchestrator: {e}")
            self._cleanupPartialInitialization()
            raise OrchestratorError(f"Failed to start: {e}") from e

    def stop(self) -> int:
        """
        Stop the orchestrator and all managed components.

        Shuts down all components in reverse dependency order with configurable
        timeouts. Components that don't stop in time are force-stopped with a
        warning.

        Returns:
            Exit code: 0 for clean shutdown, non-zero for forced/error
        """
        if not self._running:
            logger.debug("Orchestrator not running, nothing to stop")
            return self._exitCode

        logger.info("Stopping ApplicationOrchestrator...")
        startTime = time.time()

        # Check for force exit state (double Ctrl+C)
        if self._shutdownState == ShutdownState.FORCE_EXIT:
            logger.warning("Force exit requested, skipping graceful shutdown")
            self._running = False
            self._exitCode = EXIT_CODE_FORCED
            return self._exitCode

        self._shutdownAllComponents()
        self._running = False

        elapsedTime = time.time() - startTime
        logger.info(
            f"ApplicationOrchestrator stopped | "
            f"shutdown_time={elapsedTime:.2f}s | "
            f"exit_code={self._exitCode}"
        )

        return self._exitCode

    # ================================================================================
    # Main Application Loop
    # ================================================================================

    def runLoop(self) -> None:
        """
        Run the main application loop until shutdown signal received.

        This loop:
        - Monitors shutdown state and exits when requested
        - Performs periodic health checks (configurable interval)
        - Handles component callbacks through event-driven architecture
        - Catches and logs unexpected exceptions without crashing
        - Maintains memory efficiency by not accumulating unbounded data

        Should be called after start() and before stop().
        """
        if not self._running:
            logger.warning("Cannot run loop - orchestrator not started")
            return

        logger.info(
            f"Entering main application loop | "
            f"health_check_interval={self._healthCheckInterval}s"
        )

        self._startTime = datetime.now()
        self._lastHealthCheckTime = datetime.now()
        self._lastDataRateCheckTime = datetime.now()
        self._lastDataRateReadingCount = 0
        self._lastDataRateLogTime = datetime.now()
        self._lastDataRateLogCount = 0

        # Setup component callbacks for event-driven processing
        self._setupComponentCallbacks()

        # Start data logger if available
        if self._dataLogger is not None and hasattr(self._dataLogger, 'start'):
            try:
                self._dataLogger.start()
                logger.info("Data logger started")
            except Exception as e:
                logger.error(f"Failed to start data logger: {e}")

        # Start drive detector if available
        if self._driveDetector is not None and hasattr(self._driveDetector, 'start'):
            try:
                self._driveDetector.start()
                logger.info("Drive detector started")
            except Exception as e:
                logger.error(f"Failed to start drive detector: {e}")

        # Start hardware manager if available (Raspberry Pi only)
        self._startHardwareManager()

        # Track connection state for lost/restored events
        lastConnectionState = self._checkConnectionStatus()

        try:
            while self._running and self._shutdownState == ShutdownState.RUNNING:
                try:
                    # Check for connection state changes
                    currentConnectionState = self._checkConnectionStatus()
                    if currentConnectionState != lastConnectionState:
                        if currentConnectionState:
                            self._handleConnectionRestored()
                        else:
                            self._handleConnectionLost()
                        lastConnectionState = currentConnectionState

                    # Perform health check if interval elapsed
                    now = datetime.now()
                    if self._lastHealthCheckTime is not None:
                        elapsed = (now - self._lastHealthCheckTime).total_seconds()
                        if elapsed >= self._healthCheckInterval:
                            self._performHealthCheck()
                            self._lastHealthCheckTime = now

                    # Log data logging rate every 5 minutes
                    if self._lastDataRateLogTime is not None:
                        elapsed = (now - self._lastDataRateLogTime).total_seconds()
                        if elapsed >= self._dataRateLogInterval:
                            self._logDataLoggingRate()
                            self._lastDataRateLogTime = now

                    # US-226: interval-based Pi->server sync trigger.
                    # Cheap to call every loop pass -- the method is its
                    # own cadence gate and short-circuits when not due.
                    self._maybeTriggerIntervalSync()

                    # Sleep briefly to avoid busy-waiting
                    # This allows shutdown signals to be processed promptly
                    time.sleep(self._loopSleepInterval)

                except Exception as e:
                    # Catch and log unexpected exceptions without crashing
                    logger.error(f"Error in main loop iteration: {e}", exc_info=True)
                    self._healthCheckStats.totalErrors += 1
                    # Continue running - don't let one error crash the loop
                    time.sleep(self._loopSleepInterval)

        except KeyboardInterrupt:
            logger.info("Main loop interrupted by user")

        finally:
            # Final health check on exit
            self._performHealthCheck()

            # Calculate total uptime
            if self._startTime is not None:
                uptime = (datetime.now() - self._startTime).total_seconds()
                logger.info(f"Main loop exited | uptime={uptime:.1f}s")

    # ================================================================================
    # US-226: Interval-based Pi->server sync trigger
    # ================================================================================

    def _maybeTriggerIntervalSync(self) -> bool:
        """Push pending deltas when ``pi.sync.intervalSeconds`` has elapsed.

        Called once per :meth:`runLoop` pass.  The check is cheap: a
        single ``datetime`` subtraction + a threshold compare.  The
        actual push is delegated to :meth:`SyncClient.pushAllDeltas`,
        which is itself cheap when there are no rows to push (the
        delta-query short-circuits on empty).

        **Invariant:** interval-based sync fires independently of
        drive_end detection.  A bugged drive-end detector (US-229
        scope) must NOT strand rows on the Pi -- every
        ``intervalSeconds`` the runLoop attempts a push regardless
        of whether a drive is active.

        **Exception isolation:** any failure (transport error,
        transient DB lock, bad config) is logged + swallowed so the
        runLoop never crashes on a sync hiccup.  The per-table
        ``status='failed'`` path in :meth:`SyncClient.pushDelta`
        preserves the high-water mark so the next tick resends.

        Returns:
            True when the tick actually invoked ``pushAllDeltas``;
            False when gated (disabled, not yet due, or no trigger
            configured).
        """
        # Fast-path guards -- every runLoop pass hits this method.
        if self._syncClient is None:
            return False
        if 'interval' not in self._syncTriggerOn:
            return False

        now = datetime.now()
        if self._lastSyncAttemptTime is not None:
            elapsed = (now - self._lastSyncAttemptTime).total_seconds()
            if elapsed < self._syncIntervalSeconds:
                return False

        self._lastSyncAttemptTime = now
        try:
            results = self._syncClient.pushAllDeltas()
        except Exception as e:  # noqa: BLE001 -- sync must never crash runLoop
            logger.error("Interval sync push crashed: %s", e, exc_info=True)
            return False

        rowsPushed = sum(
            int(getattr(r, 'rowsPushed', 0)) for r in results
            if getattr(r, 'status', None) is not None
            and str(r.status) in ('PushStatus.OK', 'ok')
        )
        failed = sum(
            1 for r in results
            if str(getattr(r, 'status', '')) in ('PushStatus.FAILED', 'failed')
        )
        if rowsPushed > 0 or failed > 0:
            logger.info(
                "Interval sync: rowsPushed=%d failedTables=%d",
                rowsPushed, failed,
            )
        else:
            logger.debug(
                "Interval sync tick: no pending deltas (elapsed=%.1fs)",
                (datetime.now() - now).total_seconds(),
            )
        return True

    def triggerDriveEndSync(self) -> bool:
        """Trigger a sync push on drive-end when configured (US-226).

        Callable hook for the drive-detector drive_end event.  When
        ``'drive_end'`` is in ``pi.sync.triggerOn``, fires an
        immediate push and resets the interval cadence so the next
        interval tick isn't immediately triggered by a drive that
        just ended.  Independent of the interval path -- either
        trigger or both may be configured.

        Returns:
            True when a push was attempted; False when gated.
        """
        if self._syncClient is None:
            return False
        if 'drive_end' not in self._syncTriggerOn:
            return False

        self._lastSyncAttemptTime = datetime.now()
        try:
            results = self._syncClient.pushAllDeltas()
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Drive-end sync push crashed: %s", e, exc_info=True,
            )
            return False

        rowsPushed = sum(
            int(getattr(r, 'rowsPushed', 0)) for r in results
            if str(getattr(r, 'status', '')) in ('PushStatus.OK', 'ok')
        )
        logger.info(
            "Drive-end sync: rowsPushed=%d", rowsPushed,
        )
        return True

    # ================================================================================
    # US-225 / TD-034: Poll-tier pause hooks (US-216 IMMINENT stage)
    # ================================================================================

    def pausePolling(self, reason: str = 'power_imminent') -> bool:
        """Halt OBD poll-tier dispatch without tearing down the connection.

        US-225 / TD-034: called by the US-216 PowerDownOrchestrator
        IMMINENT stage callback to stop new Mode 01 queries before
        ``systemctl poweroff`` fires.  The underlying
        :class:`RealtimeDataLogger.stop` waits for the in-flight
        poll cycle to finish before the thread exits -- no in-flight
        query is dropped (invariant).  The OBD connection remains
        open; :meth:`resumePolling` reattaches a fresh polling
        thread without reconnecting.

        Idempotent: a second call while already paused is a no-op.

        Args:
            reason: Short reason code used in the info log.  Defaults
                to ``'power_imminent'`` (US-216); other callers may
                pass ``'operator_manual'`` or similar.

        Returns:
            ``True`` when the pause actually took effect on this
            call (polling was running).  ``False`` when already
            paused or no data logger exists (safe no-op).
        """
        if self._dataLogger is None:
            logger.debug("pausePolling(%r): no data logger -- no-op", reason)
            return False
        if self._pollingPausedForPowerDown:
            logger.debug(
                "pausePolling(%r): already paused -- no-op", reason,
            )
            return False
        try:
            if hasattr(self._dataLogger, 'stop'):
                self._dataLogger.stop()
                self._pollingPausedForPowerDown = True
                logger.warning(
                    "pausePolling(%r): poll-tier dispatch halted "
                    "(connection stays attached)", reason,
                )
                return True
        except Exception as e:
            logger.error(
                "pausePolling(%r) failed: %s", reason, e,
            )
        return False

    def resumePolling(self, reason: str = 'power_restored') -> bool:
        """Resume OBD poll-tier dispatch after a :meth:`pausePolling`.

        US-225 / TD-034: called by the US-216 PowerDownOrchestrator
        AC-restore callback.  Starts a fresh polling thread; because
        the connection was never torn down, this does not drop any
        in-flight work (there is none -- the stop() handshake
        guarantees the previous thread exited cleanly).

        Idempotent: a call when not paused-by-power-down is a no-op
        to avoid stealing the BT-reconnect path's resume.

        Args:
            reason: Short reason code used in the info log.  Defaults
                to ``'power_restored'`` (US-216 AC-restore).

        Returns:
            ``True`` when polling actually resumed on this call.
            ``False`` when not in the paused-for-power-down state
            (safe no-op -- does not interfere with a concurrent
            BT-reconnect resume path).
        """
        if not self._pollingPausedForPowerDown:
            logger.debug(
                "resumePolling(%r): not paused for power-down -- no-op",
                reason,
            )
            return False
        if self._dataLogger is None:
            logger.debug(
                "resumePolling(%r): no data logger -- clearing flag",
                reason,
            )
            self._pollingPausedForPowerDown = False
            return False
        try:
            if hasattr(self._dataLogger, 'start'):
                self._dataLogger.start()
                self._pollingPausedForPowerDown = False
                logger.info(
                    "resumePolling(%r): poll-tier dispatch resumed", reason,
                )
                return True
        except Exception as e:
            logger.error(
                "resumePolling(%r) failed: %s", reason, e,
            )
        return False

    @property
    def pollingPausedForPowerDown(self) -> bool:
        """True when :meth:`pausePolling` has taken effect for power-down."""
        return self._pollingPausedForPowerDown


# ================================================================================
# Factory Functions
# ================================================================================

def createOrchestratorFromConfig(
    config: dict[str, Any],
    simulate: bool = False
) -> ApplicationOrchestrator:
    """
    Create an ApplicationOrchestrator from configuration.

    Args:
        config: Configuration dictionary
        simulate: If True, use simulated OBD-II connection

    Returns:
        Configured ApplicationOrchestrator instance

    Example:
        config = loadObdConfig('config.json')
        orchestrator = createOrchestratorFromConfig(config, simulate=True)
        orchestrator.start()
    """
    return ApplicationOrchestrator(config=config, simulate=simulate)


__all__ = [
    'ApplicationOrchestrator',
    'createOrchestratorFromConfig',
]
