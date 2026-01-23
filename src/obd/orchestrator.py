################################################################################
# File Name: orchestrator.py
# Purpose/Description: Central orchestrator for OBD-II application lifecycle
# Author: Ralph Agent
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-23    | Ralph Agent  | Initial implementation for US-OSC-001
# 2026-01-23    | Ralph Agent  | US-OSC-002: Add startup timing, Ctrl+C handling,
#               |              | connection retry with exponential backoff
# 2026-01-23    | Ralph Agent  | US-OSC-003: Add graceful shutdown with timeouts,
#               |              | signal handling, double Ctrl+C force exit
# 2026-01-23    | Ralph Agent  | US-OSC-005: Add main application loop with
#               |              | health checks, callbacks, exception handling
# 2026-01-23    | Ralph Agent  | US-OSC-006: Wire up realtime data logging with
#               |              | display updates, logging rate tracking
# 2026-01-23    | Ralph Agent  | US-OSC-007: Verified drive detection wiring -
#               |              | RPM/SPEED routing, callbacks, display updates
# 2026-01-23    | Ralph Agent  | US-OSC-008: Wire up alert system - fixed
#               |              | callback registration (onAlert vs registerCallback),
#               |              | enhanced alert logging with full details
# 2026-01-23    | Ralph Agent  | US-OSC-009: Wire up statistics engine - fixed
#               |              | init order (stats before drive), callback registration
#               |              | (registerCallbacks), added _handleAnalysisError
# ================================================================================
################################################################################

"""
Application Orchestrator for Eclipse OBD-II Performance Monitoring System.

This module provides the central ApplicationOrchestrator class that manages
the lifecycle of all system components. It handles:

- Component initialization in correct dependency order
- Component startup and shutdown coordination
- Application state management
- Error handling and logging during lifecycle events

Components managed:
- database: ObdDatabase for data persistence
- profileManager: ProfileManager for driving profile management
- connection: ObdConnection for OBD-II dongle communication
- vinDecoder: VinDecoder for vehicle identification
- displayManager: DisplayManager for user interface
- driveDetector: DriveDetector for drive session detection
- alertManager: AlertManager for threshold alerts
- statisticsEngine: StatisticsEngine for data analysis
- dataLogger: RealtimeDataLogger for continuous data logging

Usage:
    from obd.orchestrator import ApplicationOrchestrator

    # Create orchestrator
    orchestrator = ApplicationOrchestrator(config=config, simulate=False)

    # Start all components
    orchestrator.start()

    # Check status
    if orchestrator.isRunning():
        status = orchestrator.getStatus()
        print(f"Components: {status['components']}")

    # Stop all components
    orchestrator.stop()
"""

import logging
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from .database import createDatabaseFromConfig, ObdDatabase

logger = logging.getLogger(__name__)


# ================================================================================
# Enums
# ================================================================================

class ShutdownState(Enum):
    """States for shutdown handling."""
    RUNNING = "running"
    SHUTDOWN_REQUESTED = "shutdown_requested"
    FORCE_EXIT = "force_exit"


@dataclass
class HealthCheckStats:
    """Statistics for health check reporting."""

    connectionConnected: bool = False
    connectionStatus: str = "unknown"
    dataRatePerMinute: float = 0.0
    totalReadings: int = 0
    totalErrors: int = 0
    drivesDetected: int = 0
    alertsTriggered: int = 0
    lastHealthCheck: Optional[datetime] = None
    uptimeSeconds: float = 0.0

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            'connectionConnected': self.connectionConnected,
            'connectionStatus': self.connectionStatus,
            'dataRatePerMinute': round(self.dataRatePerMinute, 2),
            'totalReadings': self.totalReadings,
            'totalErrors': self.totalErrors,
            'drivesDetected': self.drivesDetected,
            'alertsTriggered': self.alertsTriggered,
            'lastHealthCheck': (
                self.lastHealthCheck.isoformat()
                if self.lastHealthCheck else None
            ),
            'uptimeSeconds': round(self.uptimeSeconds, 1),
        }


# ================================================================================
# Constants
# ================================================================================

# Default component shutdown timeout in seconds
DEFAULT_SHUTDOWN_TIMEOUT = 5.0

# Default health check interval in seconds
DEFAULT_HEALTH_CHECK_INTERVAL = 60.0

# Default data logging rate log interval in seconds (5 minutes)
DEFAULT_DATA_RATE_LOG_INTERVAL = 300.0

# Exit codes
EXIT_CODE_CLEAN = 0
EXIT_CODE_FORCED = 1
EXIT_CODE_ERROR = 2


# ================================================================================
# Exceptions
# ================================================================================

class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""

    def __init__(self, message: str, component: Optional[str] = None):
        """
        Initialize orchestrator error.

        Args:
            message: Error description
            component: Name of component that caused the error (optional)
        """
        super().__init__(message)
        self.component = component


class ComponentInitializationError(OrchestratorError):
    """Raised when a component fails to initialize."""
    pass


class ComponentStartError(OrchestratorError):
    """Raised when a component fails to start."""
    pass


class ComponentStopError(OrchestratorError):
    """Raised when a component fails to stop gracefully."""
    pass


# ================================================================================
# ApplicationOrchestrator Class
# ================================================================================

class ApplicationOrchestrator:
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
    6. driveDetector
    7. alertManager
    8. statisticsEngine
    9. dataLogger

    Shutdown Order (reverse):
    1. dataLogger
    2. alertManager
    3. driveDetector
    4. statisticsEngine
    5. displayManager
    6. connection
    7. database

    Example:
        config = loadObdConfig('config.json')
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)

        try:
            orchestrator.start()
            # Application runs...
        finally:
            orchestrator.stop()
    """

    def __init__(self, config: Dict[str, Any], simulate: bool = False):
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
        self._database: Optional[ObdDatabase] = None
        self._connection: Optional[Any] = None
        self._dataLogger: Optional[Any] = None
        self._driveDetector: Optional[Any] = None
        self._alertManager: Optional[Any] = None
        self._displayManager: Optional[Any] = None
        self._statisticsEngine: Optional[Any] = None
        self._profileManager: Optional[Any] = None
        self._vinDecoder: Optional[Any] = None

        # Shutdown state management
        self._shutdownState = ShutdownState.RUNNING
        self._shutdownTimeout = config.get('shutdown', {}).get(
            'componentTimeout', DEFAULT_SHUTDOWN_TIMEOUT
        )
        self._exitCode = EXIT_CODE_CLEAN
        self._originalSigintHandler: Optional[Callable[..., Any]] = None
        self._originalSigtermHandler: Optional[Callable[..., Any]] = None

        # Main loop configuration
        self._healthCheckInterval = config.get('monitoring', {}).get(
            'healthCheckIntervalSeconds', DEFAULT_HEALTH_CHECK_INTERVAL
        )
        self._loopSleepInterval = 0.1  # 100ms between loop iterations

        # Data logging rate log interval (5 minutes default)
        self._dataRateLogInterval = config.get('monitoring', {}).get(
            'dataRateLogIntervalSeconds', DEFAULT_DATA_RATE_LOG_INTERVAL
        )
        self._lastDataRateLogTime: Optional[datetime] = None
        self._lastDataRateLogCount: int = 0

        # Parameters to display on dashboard (extracted from realtimeData config)
        self._dashboardParameters: Set[str] = self._extractDashboardParameters(config)

        # Statistics tracking for health checks
        self._startTime: Optional[datetime] = None
        self._lastHealthCheckTime: Optional[datetime] = None
        self._healthCheckStats = HealthCheckStats()
        self._lastDataRateCheckTime: Optional[datetime] = None
        self._lastDataRateReadingCount: int = 0

        # Callback handlers for component events
        self._onDriveStart: Optional[Callable[[Any], None]] = None
        self._onDriveEnd: Optional[Callable[[Any], None]] = None
        self._onAlert: Optional[Callable[[Any], None]] = None
        self._onAnalysisComplete: Optional[Callable[[Any], None]] = None
        self._onConnectionLost: Optional[Callable[[], None]] = None
        self._onConnectionRestored: Optional[Callable[[], None]] = None

        logger.debug("ApplicationOrchestrator initialized")

    # ================================================================================
    # Properties for component access
    # ================================================================================

    @property
    def database(self) -> Optional[ObdDatabase]:
        """Get the database instance."""
        return self._database

    @property
    def connection(self) -> Optional[Any]:
        """Get the OBD connection instance."""
        return self._connection

    @property
    def dataLogger(self) -> Optional[Any]:
        """Get the data logger instance."""
        return self._dataLogger

    @property
    def driveDetector(self) -> Optional[Any]:
        """Get the drive detector instance."""
        return self._driveDetector

    @property
    def alertManager(self) -> Optional[Any]:
        """Get the alert manager instance."""
        return self._alertManager

    @property
    def displayManager(self) -> Optional[Any]:
        """Get the display manager instance."""
        return self._displayManager

    @property
    def statisticsEngine(self) -> Optional[Any]:
        """Get the statistics engine instance."""
        return self._statisticsEngine

    @property
    def profileManager(self) -> Optional[Any]:
        """Get the profile manager instance."""
        return self._profileManager

    @property
    def vinDecoder(self) -> Optional[Any]:
        """Get the VIN decoder instance."""
        return self._vinDecoder

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

    def getStatus(self) -> Dict[str, Any]:
        """
        Get the current status of all managed components.

        Returns:
            Dictionary containing:
            - running: bool indicating if orchestrator is running
            - components: dict mapping component names to their status
              ('initialized', 'not_initialized', or component-specific status)
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
            'vinDecoder': self._getComponentStatus(self._vinDecoder),
        }

        return {
            'running': self._running,
            'components': componentStatus,
        }

    def _getComponentStatus(self, component: Optional[Any]) -> str:
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

    def _extractDashboardParameters(self, config: Dict[str, Any]) -> Set[str]:
        """
        Extract parameter names that should be displayed on the dashboard.

        Parses the realtimeData.parameters list and returns names of parameters
        that have displayOnDashboard: true.

        Args:
            config: Configuration dictionary with realtimeData section

        Returns:
            Set of parameter names to display on dashboard
        """
        dashboardParams: Set[str] = set()
        parameters = config.get('realtimeData', {}).get('parameters', [])

        for param in parameters:
            if isinstance(param, dict):
                if param.get('displayOnDashboard', False):
                    name = param.get('name', '')
                    if name:
                        dashboardParams.add(name)

        return dashboardParams

    # ================================================================================
    # Signal Handling
    # ================================================================================

    def registerSignalHandlers(self) -> None:
        """
        Register signal handlers for graceful shutdown.

        Registers handlers for SIGINT (Ctrl+C) and SIGTERM (systemd stop).
        First signal initiates graceful shutdown, second signal forces immediate exit.
        """
        self._originalSigintHandler = signal.signal(
            signal.SIGINT, self._handleShutdownSignal
        )
        # SIGTERM is not available on Windows, only register if available
        if hasattr(signal, 'SIGTERM'):
            self._originalSigtermHandler = signal.signal(
                signal.SIGTERM, self._handleShutdownSignal
            )
        logger.debug("Signal handlers registered")

    def restoreSignalHandlers(self) -> None:
        """Restore the original signal handlers."""
        if self._originalSigintHandler is not None:
            signal.signal(signal.SIGINT, self._originalSigintHandler)
            self._originalSigintHandler = None
        if self._originalSigtermHandler is not None and hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, self._originalSigtermHandler)
            self._originalSigtermHandler = None
        logger.debug("Signal handlers restored")

    def _handleShutdownSignal(
        self, signum: int, frame: Optional[Any]
    ) -> None:
        """
        Handle shutdown signals (SIGINT/SIGTERM).

        First signal: Request graceful shutdown
        Second signal: Force immediate exit

        Args:
            signum: Signal number received
            frame: Stack frame (unused)
        """
        signalName = signal.Signals(signum).name if signum in [s.value for s in signal.Signals] else str(signum)

        if self._shutdownState == ShutdownState.SHUTDOWN_REQUESTED:
            # Second signal - force exit
            logger.warning(
                f"Received second signal ({signalName}), forcing immediate exit"
            )
            self._shutdownState = ShutdownState.FORCE_EXIT
            self._exitCode = EXIT_CODE_FORCED
            # Force immediate exit
            sys.exit(EXIT_CODE_FORCED)
        else:
            # First signal - request graceful shutdown
            logger.info(f"Received signal {signalName}, initiating shutdown")
            self._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

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

    def registerCallbacks(
        self,
        onDriveStart: Optional[Callable[[Any], None]] = None,
        onDriveEnd: Optional[Callable[[Any], None]] = None,
        onAlert: Optional[Callable[[Any], None]] = None,
        onAnalysisComplete: Optional[Callable[[Any], None]] = None,
        onConnectionLost: Optional[Callable[[], None]] = None,
        onConnectionRestored: Optional[Callable[[], None]] = None
    ) -> None:
        """
        Register callbacks for component events.

        Args:
            onDriveStart: Called when a drive session starts (DriveSession)
            onDriveEnd: Called when a drive session ends (DriveSession)
            onAlert: Called when an alert is triggered (AlertEvent)
            onAnalysisComplete: Called when statistics analysis completes
            onConnectionLost: Called when OBD connection is lost
            onConnectionRestored: Called when OBD connection is restored
        """
        self._onDriveStart = onDriveStart
        self._onDriveEnd = onDriveEnd
        self._onAlert = onAlert
        self._onAnalysisComplete = onAnalysisComplete
        self._onConnectionLost = onConnectionLost
        self._onConnectionRestored = onConnectionRestored

    def _setupComponentCallbacks(self) -> None:
        """
        Wire up callbacks between orchestrator and components.

        Called after all components are initialized to connect event handlers.
        """
        # Connect drive detector callbacks
        if self._driveDetector is not None:
            try:
                self._driveDetector.registerCallbacks(
                    onDriveStart=self._handleDriveStart,
                    onDriveEnd=self._handleDriveEnd
                )
                logger.debug("Drive detector callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register drive detector callbacks: {e}")

        # Connect alert manager callbacks
        # AlertManager uses onAlert() method to register single callback
        if self._alertManager is not None and hasattr(self._alertManager, 'onAlert'):
            try:
                self._alertManager.onAlert(self._handleAlert)
                logger.debug("Alert manager callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register alert manager callbacks: {e}")

        # Connect statistics engine callbacks
        # StatisticsEngine uses registerCallbacks() with onAnalysisComplete and onAnalysisError
        if self._statisticsEngine is not None and hasattr(self._statisticsEngine, 'registerCallbacks'):
            try:
                self._statisticsEngine.registerCallbacks(
                    onAnalysisComplete=self._handleAnalysisComplete,
                    onAnalysisError=self._handleAnalysisError
                )
                logger.debug("Statistics engine callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register statistics engine callbacks: {e}")

        # Connect realtime data logger callbacks
        if self._dataLogger is not None and hasattr(self._dataLogger, 'registerCallbacks'):
            try:
                self._dataLogger.registerCallbacks(
                    onReading=self._handleReading,
                    onError=self._handleLoggingError
                )
                logger.debug("Data logger callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register data logger callbacks: {e}")

    def _handleDriveStart(self, session: Any) -> None:
        """Handle drive start event from DriveDetector."""
        logger.info(f"Drive started | session_id={getattr(session, 'id', 'unknown')}")
        self._healthCheckStats.drivesDetected += 1

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showDriveStatus'):
            try:
                self._displayManager.showDriveStatus('driving')
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # Call external callback
        if self._onDriveStart is not None:
            try:
                self._onDriveStart(session)
            except Exception as e:
                logger.warning(f"onDriveStart callback error: {e}")

    def _handleDriveEnd(self, session: Any) -> None:
        """Handle drive end event from DriveDetector."""
        duration = getattr(session, 'duration', 0)
        logger.info(f"Drive ended | duration={duration:.1f}s")

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showDriveStatus'):
            try:
                self._displayManager.showDriveStatus('stopped')
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # Call external callback
        if self._onDriveEnd is not None:
            try:
                self._onDriveEnd(session)
            except Exception as e:
                logger.warning(f"onDriveEnd callback error: {e}")

    def _handleAlert(self, alertEvent: Any) -> None:
        """
        Handle alert event from AlertManager.

        The AlertManager has already logged the alert to the database
        at this point. This callback is responsible for:
        - Logging the alert at WARNING level
        - Updating the display with the alert
        - Calling any external callbacks
        - Updating statistics

        Args:
            alertEvent: AlertEvent object with alert details
        """
        alertType = getattr(alertEvent, 'alertType', 'unknown')
        paramName = getattr(alertEvent, 'parameterName', 'unknown')
        value = getattr(alertEvent, 'value', 'N/A')
        threshold = getattr(alertEvent, 'threshold', 'N/A')
        profileId = getattr(alertEvent, 'profileId', 'unknown')

        logger.warning(
            f"ALERT triggered | type={alertType} | param={paramName} | "
            f"value={value} | threshold={threshold} | profile={profileId}"
        )
        self._healthCheckStats.alertsTriggered += 1

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showAlert'):
            try:
                self._displayManager.showAlert(alertEvent)
            except Exception as e:
                logger.debug(f"Display alert failed: {e}")

        # Call external callback
        if self._onAlert is not None:
            try:
                self._onAlert(alertEvent)
            except Exception as e:
                logger.warning(f"onAlert callback error: {e}")

    def _handleAnalysisComplete(self, result: Any) -> None:
        """Handle analysis complete event from StatisticsEngine."""
        logger.info("Statistical analysis completed")

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showAnalysisResult'):
            try:
                self._displayManager.showAnalysisResult(result)
            except Exception as e:
                logger.debug(f"Display analysis result failed: {e}")

        # Call external callback
        if self._onAnalysisComplete is not None:
            try:
                self._onAnalysisComplete(result)
            except Exception as e:
                logger.warning(f"onAnalysisComplete callback error: {e}")

    def _handleAnalysisError(self, profileId: str, error: Exception) -> None:
        """
        Handle analysis error event from StatisticsEngine.

        Logs the error and continues operation - analysis failures
        should not crash the application.

        Args:
            profileId: Profile ID that was being analyzed
            error: The exception that occurred
        """
        logger.error(
            f"Analysis error | profile={profileId} | error={error}"
        )
        self._healthCheckStats.totalErrors += 1

    def _handleReading(self, reading: Any) -> None:
        """Handle reading event from RealtimeDataLogger."""
        self._healthCheckStats.totalReadings += 1

        paramName = getattr(reading, 'parameterName', None)
        value = getattr(reading, 'value', None)
        unit = getattr(reading, 'unit', None)

        # Update display if parameter is configured for dashboard
        if (
            self._displayManager is not None
            and paramName is not None
            and paramName in self._dashboardParameters
            and hasattr(self._displayManager, 'updateValue')
        ):
            try:
                self._displayManager.updateValue(paramName, value, unit)
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # Pass reading to drive detector for state machine processing
        if self._driveDetector is not None:
            try:
                if paramName is not None and value is not None:
                    self._driveDetector.processValue(paramName, value)
            except Exception as e:
                logger.debug(f"Drive detector process failed: {e}")

        # Pass reading to alert manager for threshold checking
        if self._alertManager is not None and hasattr(self._alertManager, 'checkValue'):
            try:
                if paramName is not None and value is not None:
                    self._alertManager.checkValue(paramName, value)
            except Exception as e:
                logger.debug(f"Alert check failed: {e}")

    def _handleLoggingError(self, paramName: str, error: Exception) -> None:
        """Handle logging error event from RealtimeDataLogger."""
        self._healthCheckStats.totalErrors += 1
        logger.debug(f"Data logging error | param={paramName} | error={error}")

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

    def _checkConnectionStatus(self) -> bool:
        """
        Check if OBD connection is currently connected.

        Returns:
            True if connected, False otherwise
        """
        if self._connection is None:
            return False

        try:
            if hasattr(self._connection, 'isConnected'):
                return self._connection.isConnected()
            return False
        except Exception:
            return False

    def _handleConnectionLost(self) -> None:
        """Handle connection lost event."""
        logger.warning("OBD connection lost")
        self._healthCheckStats.connectionStatus = "disconnected"
        self._healthCheckStats.connectionConnected = False

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showConnectionStatus'):
            try:
                self._displayManager.showConnectionStatus('Reconnecting...')
            except Exception as e:
                logger.debug(f"Display connection status failed: {e}")

        # Call external callback
        if self._onConnectionLost is not None:
            try:
                self._onConnectionLost()
            except Exception as e:
                logger.warning(f"onConnectionLost callback error: {e}")

    def _handleConnectionRestored(self) -> None:
        """Handle connection restored event."""
        logger.info("OBD connection restored")
        self._healthCheckStats.connectionStatus = "connected"
        self._healthCheckStats.connectionConnected = True

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showConnectionStatus'):
            try:
                self._displayManager.showConnectionStatus('Connected')
            except Exception as e:
                logger.debug(f"Display connection status failed: {e}")

        # Call external callback
        if self._onConnectionRestored is not None:
            try:
                self._onConnectionRestored()
            except Exception as e:
                logger.warning(f"onConnectionRestored callback error: {e}")

    def _performHealthCheck(self) -> None:
        """
        Perform periodic health check and log status.

        Logs:
        - Connection status
        - Data rate (readings per minute)
        - Error count
        - Uptime
        """
        now = datetime.now()

        # Calculate data rate (readings per minute)
        if self._lastDataRateCheckTime is not None:
            elapsedMinutes = (now - self._lastDataRateCheckTime).total_seconds() / 60.0
            if elapsedMinutes > 0:
                readingsDelta = (
                    self._healthCheckStats.totalReadings - self._lastDataRateReadingCount
                )
                self._healthCheckStats.dataRatePerMinute = readingsDelta / elapsedMinutes

        # Update tracking for next calculation
        self._lastDataRateCheckTime = now
        self._lastDataRateReadingCount = self._healthCheckStats.totalReadings

        # Update connection status
        self._healthCheckStats.connectionConnected = self._checkConnectionStatus()
        self._healthCheckStats.connectionStatus = (
            "connected" if self._healthCheckStats.connectionConnected else "disconnected"
        )

        # Calculate uptime
        if self._startTime is not None:
            self._healthCheckStats.uptimeSeconds = (now - self._startTime).total_seconds()

        self._healthCheckStats.lastHealthCheck = now

        # Get additional stats from components
        self._collectComponentStats()

        # Log health check
        logger.info(
            f"HEALTH CHECK | "
            f"connection={self._healthCheckStats.connectionStatus} | "
            f"data_rate={self._healthCheckStats.dataRatePerMinute:.1f}/min | "
            f"readings={self._healthCheckStats.totalReadings} | "
            f"errors={self._healthCheckStats.totalErrors} | "
            f"drives={self._healthCheckStats.drivesDetected} | "
            f"alerts={self._healthCheckStats.alertsTriggered} | "
            f"uptime={self._healthCheckStats.uptimeSeconds:.0f}s"
        )

    def _collectComponentStats(self) -> None:
        """Collect additional statistics from components for health check."""
        # Get data logger stats if available
        if self._dataLogger is not None and hasattr(self._dataLogger, 'getStats'):
            try:
                loggerStats = self._dataLogger.getStats()
                if hasattr(loggerStats, 'totalLogged'):
                    self._healthCheckStats.totalReadings = loggerStats.totalLogged
                if hasattr(loggerStats, 'totalErrors'):
                    self._healthCheckStats.totalErrors = loggerStats.totalErrors
            except Exception as e:
                logger.debug(f"Could not get data logger stats: {e}")

        # Get drive detector stats if available
        if self._driveDetector is not None and hasattr(self._driveDetector, 'getStats'):
            try:
                detectorStats = self._driveDetector.getStats()
                if hasattr(detectorStats, 'drivesDetected'):
                    self._healthCheckStats.drivesDetected = detectorStats.drivesDetected
            except Exception as e:
                logger.debug(f"Could not get drive detector stats: {e}")

    def _logDataLoggingRate(self) -> None:
        """
        Log the data logging rate (records per minute).

        Called every 5 minutes (configurable) to track logging performance.
        Logs the average records/minute since last log.
        """
        now = datetime.now()

        # Calculate records per minute since last log
        if self._lastDataRateLogTime is not None:
            elapsedMinutes = (now - self._lastDataRateLogTime).total_seconds() / 60.0
            if elapsedMinutes > 0:
                readingsDelta = (
                    self._healthCheckStats.totalReadings - self._lastDataRateLogCount
                )
                recordsPerMinute = readingsDelta / elapsedMinutes

                logger.info(
                    f"DATA LOGGING RATE | "
                    f"records/min={recordsPerMinute:.1f} | "
                    f"total_logged={self._healthCheckStats.totalReadings} | "
                    f"period_minutes={elapsedMinutes:.1f}"
                )

        # Update tracking for next calculation
        self._lastDataRateLogCount = self._healthCheckStats.totalReadings

    def getHealthCheckStats(self) -> HealthCheckStats:
        """
        Get current health check statistics.

        Returns:
            HealthCheckStats with current statistics
        """
        return self._healthCheckStats

    def setHealthCheckInterval(self, intervalSeconds: float) -> None:
        """
        Update the health check interval.

        Args:
            intervalSeconds: New interval in seconds (minimum 10 seconds)

        Raises:
            ValueError: If interval is less than 10 seconds
        """
        if intervalSeconds < 10:
            raise ValueError("Health check interval must be at least 10 seconds")

        self._healthCheckInterval = intervalSeconds
        logger.info(f"Health check interval updated to {intervalSeconds}s")

    # ================================================================================
    # Component Initialization
    # ================================================================================

    def _initializeAllComponents(self) -> None:
        """
        Initialize all components in dependency order.

        Order:
        1. database - needed by all other components
        2. profileManager - needed for profile-specific settings
        3. connection - OBD-II connectivity
        4. vinDecoder - vehicle identification
        5. displayManager - user interface
        6. statisticsEngine - data analysis (before driveDetector so it can
                              be passed to driveDetector for post-drive analysis)
        7. driveDetector - drive session detection (needs statisticsEngine)
        8. alertManager - threshold alerts
        9. dataLogger - continuous logging
        """
        self._initializeDatabase()
        self._initializeProfileManager()
        self._initializeConnection()
        self._initializeVinDecoder()
        self._initializeDisplayManager()
        self._initializeStatisticsEngine()
        self._initializeDriveDetector()
        self._initializeAlertManager()
        self._initializeDataLogger()

    def _initializeDatabase(self) -> None:
        """Initialize the database component."""
        logger.info("Starting database...")
        try:
            self._database = createDatabaseFromConfig(self._config)
            self._database.initialize()
            logger.info("Database started successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise ComponentInitializationError(
                f"Database initialization failed: {e}",
                component='database'
            ) from e

    def _initializeProfileManager(self) -> None:
        """Initialize the profile manager component."""
        logger.info("Starting profileManager...")
        try:
            from .profile_manager import createProfileManagerFromConfig
            self._profileManager = createProfileManagerFromConfig(
                self._config, self._database
            )
            logger.info("ProfileManager started successfully")
        except ImportError:
            logger.warning("ProfileManager not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize profileManager: {e}")
            raise ComponentInitializationError(
                f"ProfileManager initialization failed: {e}",
                component='profileManager'
            ) from e

    def _initializeConnection(self) -> None:
        """
        Initialize the OBD-II connection component.

        Uses exponential backoff retry logic from config['bluetooth']['retryDelays'].
        Connection retry delays default to [1, 2, 4, 8, 16] seconds if not configured.
        """
        logger.info("Starting connection...")
        try:
            if self._simulate:
                from .simulator.simulated_connection import (
                    createSimulatedConnectionFromConfig
                )
                self._connection = createSimulatedConnectionFromConfig(
                    self._config, self._database
                )
            else:
                from .obd_connection import createConnectionFromConfig
                self._connection = createConnectionFromConfig(
                    self._config, self._database
                )

            # Attempt to connect using the connection's built-in retry logic
            # The connection object already implements exponential backoff
            # from config['bluetooth']['retryDelays']
            if hasattr(self._connection, 'connect'):
                if not self._connection.connect():
                    raise ComponentInitializationError(
                        "OBD-II connection failed after all retry attempts",
                        component='connection'
                    )

            logger.info("Connection started successfully")
        except ImportError as e:
            logger.warning(f"Connection module not available: {e}")
        except ComponentInitializationError:
            # Re-raise ComponentInitializationError as-is
            raise
        except Exception as e:
            logger.error(f"Failed to initialize connection: {e}")
            raise ComponentInitializationError(
                f"Connection initialization failed: {e}",
                component='connection'
            ) from e

    def _initializeVinDecoder(self) -> None:
        """Initialize the VIN decoder component."""
        logger.info("Starting vinDecoder...")
        try:
            from .vin_decoder import createVinDecoderFromConfig
            self._vinDecoder = createVinDecoderFromConfig(
                self._config, self._database
            )
            logger.info("VinDecoder started successfully")
        except ImportError:
            logger.warning("VinDecoder not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize vinDecoder: {e}")
            raise ComponentInitializationError(
                f"VinDecoder initialization failed: {e}",
                component='vinDecoder'
            ) from e

    def _initializeDisplayManager(self) -> None:
        """Initialize the display manager component."""
        logger.info("Starting displayManager...")
        try:
            from .display_manager import createDisplayManagerFromConfig
            self._displayManager = createDisplayManagerFromConfig(self._config)
            logger.info("DisplayManager started successfully")
        except ImportError:
            logger.warning("DisplayManager not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize displayManager: {e}")
            raise ComponentInitializationError(
                f"DisplayManager initialization failed: {e}",
                component='displayManager'
            ) from e

    def _initializeDriveDetector(self) -> None:
        """Initialize the drive detector component."""
        logger.info("Starting driveDetector...")
        try:
            from .drive_detector import createDriveDetectorFromConfig
            self._driveDetector = createDriveDetectorFromConfig(
                self._config, self._statisticsEngine, self._database
            )
            logger.info("DriveDetector started successfully")
        except ImportError:
            logger.warning("DriveDetector not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize driveDetector: {e}")
            raise ComponentInitializationError(
                f"DriveDetector initialization failed: {e}",
                component='driveDetector'
            ) from e

    def _initializeAlertManager(self) -> None:
        """Initialize the alert manager component."""
        logger.info("Starting alertManager...")
        try:
            from .alert_manager import createAlertManagerFromConfig
            self._alertManager = createAlertManagerFromConfig(
                self._config, self._database, self._displayManager
            )
            logger.info("AlertManager started successfully")
        except ImportError:
            logger.warning("AlertManager not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize alertManager: {e}")
            raise ComponentInitializationError(
                f"AlertManager initialization failed: {e}",
                component='alertManager'
            ) from e

    def _initializeStatisticsEngine(self) -> None:
        """Initialize the statistics engine component."""
        logger.info("Starting statisticsEngine...")
        try:
            from .statistics_engine import createStatisticsEngineFromConfig
            self._statisticsEngine = createStatisticsEngineFromConfig(
                self._database, self._config
            )
            logger.info("StatisticsEngine started successfully")
        except ImportError:
            logger.warning("StatisticsEngine not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize statisticsEngine: {e}")
            raise ComponentInitializationError(
                f"StatisticsEngine initialization failed: {e}",
                component='statisticsEngine'
            ) from e

    def _initializeDataLogger(self) -> None:
        """Initialize the realtime data logger component."""
        logger.info("Starting dataLogger...")
        try:
            from .data_logger import createRealtimeLoggerFromConfig
            self._dataLogger = createRealtimeLoggerFromConfig(
                self._config, self._connection, self._database
            )
            logger.info("DataLogger started successfully")
        except ImportError:
            logger.warning("DataLogger not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize dataLogger: {e}")
            raise ComponentInitializationError(
                f"DataLogger initialization failed: {e}",
                component='dataLogger'
            ) from e

    # ================================================================================
    # Component Shutdown
    # ================================================================================

    def _stopComponentWithTimeout(
        self,
        component: Any,
        componentName: str,
        stopMethod: str = 'stop'
    ) -> bool:
        """
        Stop a component with timeout and force-stop if needed.

        Args:
            component: The component instance to stop
            componentName: Name of the component for logging
            stopMethod: Name of the stop method to call

        Returns:
            True if stopped cleanly, False if force-stopped or errored
        """
        if component is None:
            return True

        # Check for force exit before each component
        if self._shutdownState == ShutdownState.FORCE_EXIT:
            logger.warning(f"Force exit: skipping {componentName} shutdown")
            return False

        logger.info(f"Stopping {componentName}...")

        # Use a thread to implement timeout
        stopComplete = threading.Event()
        stopError: Optional[Exception] = None

        def doStop() -> None:
            nonlocal stopError
            try:
                if hasattr(component, stopMethod):
                    getattr(component, stopMethod)()
                elif stopMethod == 'stop' and hasattr(component, 'disconnect'):
                    # Fallback for connection components
                    component.disconnect()
            except Exception as e:
                stopError = e
            finally:
                stopComplete.set()

        stopThread = threading.Thread(target=doStop, daemon=True)
        stopThread.start()

        # Wait for stop with timeout
        cleanStop = stopComplete.wait(timeout=self._shutdownTimeout)

        if not cleanStop:
            logger.warning(
                f"{componentName} did not stop within {self._shutdownTimeout}s, "
                f"force-stopping"
            )
            self._exitCode = EXIT_CODE_FORCED
            return False
        elif stopError is not None:
            logger.warning(f"Error stopping {componentName}: {stopError}")
            return False
        else:
            logger.info(f"{componentName} stopped successfully")
            return True

    def _shutdownAllComponents(self) -> None:
        """
        Shutdown all components in reverse dependency order.

        Order (reverse of initialization):
        1. dataLogger
        2. alertManager
        3. driveDetector (before statisticsEngine - may still be triggering analysis)
        4. statisticsEngine
        5. displayManager
        6. vinDecoder
        7. connection
        8. profileManager
        9. database
        """
        self._shutdownDataLogger()
        self._shutdownAlertManager()
        self._shutdownDriveDetector()
        self._shutdownStatisticsEngine()
        self._shutdownDisplayManager()
        self._shutdownVinDecoder()
        self._shutdownConnection()
        self._shutdownProfileManager()
        self._shutdownDatabase()

    def _shutdownDataLogger(self) -> None:
        """Shutdown the data logger component."""
        self._stopComponentWithTimeout(self._dataLogger, 'dataLogger')
        self._dataLogger = None

    def _shutdownAlertManager(self) -> None:
        """Shutdown the alert manager component."""
        self._stopComponentWithTimeout(self._alertManager, 'alertManager')
        self._alertManager = None

    def _shutdownDriveDetector(self) -> None:
        """Shutdown the drive detector component."""
        self._stopComponentWithTimeout(self._driveDetector, 'driveDetector')
        self._driveDetector = None

    def _shutdownStatisticsEngine(self) -> None:
        """Shutdown the statistics engine component."""
        self._stopComponentWithTimeout(self._statisticsEngine, 'statisticsEngine')
        self._statisticsEngine = None

    def _shutdownDisplayManager(self) -> None:
        """Shutdown the display manager component."""
        self._stopComponentWithTimeout(self._displayManager, 'displayManager')
        self._displayManager = None

    def _shutdownVinDecoder(self) -> None:
        """Shutdown the VIN decoder component."""
        self._stopComponentWithTimeout(self._vinDecoder, 'vinDecoder')
        self._vinDecoder = None

    def _shutdownConnection(self) -> None:
        """Shutdown the OBD-II connection component."""
        # Connection uses disconnect() method, not stop()
        self._stopComponentWithTimeout(
            self._connection, 'connection', stopMethod='disconnect'
        )
        self._connection = None

    def _shutdownProfileManager(self) -> None:
        """Shutdown the profile manager component."""
        self._stopComponentWithTimeout(self._profileManager, 'profileManager')
        self._profileManager = None

    def _shutdownDatabase(self) -> None:
        """Shutdown the database component."""
        if self._database is not None:
            # Check for force exit
            if self._shutdownState == ShutdownState.FORCE_EXIT:
                logger.warning("Force exit: skipping database shutdown")
            else:
                logger.info("Stopping database...")
                # Database uses context managers, no explicit close needed
                # but we clear the reference
                logger.info("Database stopped successfully")
        self._database = None

    def _cleanupPartialInitialization(self) -> None:
        """
        Clean up any partially initialized components after a startup failure.

        Called when start() fails partway through initialization.
        """
        logger.info("Cleaning up partial initialization...")
        self._shutdownAllComponents()
        logger.info("Cleanup complete")


# ================================================================================
# Factory Functions
# ================================================================================

def createOrchestratorFromConfig(
    config: Dict[str, Any],
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
    # Classes
    'ApplicationOrchestrator',
    'HealthCheckStats',
    # Enums
    'ShutdownState',
    # Exceptions
    'OrchestratorError',
    'ComponentInitializationError',
    'ComponentStartError',
    'ComponentStopError',
    # Constants
    'DEFAULT_SHUTDOWN_TIMEOUT',
    'DEFAULT_HEALTH_CHECK_INTERVAL',
    'EXIT_CODE_CLEAN',
    'EXIT_CODE_FORCED',
    'EXIT_CODE_ERROR',
    # Factory functions
    'createOrchestratorFromConfig',
]
