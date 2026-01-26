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
# 2026-01-23    | Ralph Agent  | US-OSC-010: Wire up display manager - initialize
#               |              | display driver, show welcome screen on startup,
#               |              | show shutdown message on stop, fallback to headless
# 2026-01-23    | Ralph Agent  | US-OSC-011: Wire up profile system - add
#               |              | ProfileSwitcher init/shutdown, _handleProfileChange
#               |              | callback for alert manager thresholds and polling
# 2026-01-23    | Ralph Agent  | US-OSC-012: Implement connection recovery - add
#               |              | automatic reconnection with exponential backoff,
#               |              | pause/resume data logging during reconnection
# 2026-01-23    | Ralph Agent  | US-OSC-013: Implement first-connection VIN decode -
#               |              | query VIN from vehicle, cache check, NHTSA API decode,
#               |              | display vehicle info on startup
# 2026-01-26    | Ralph Agent  | US-RPI-013: Integrate HardwareManager - add init,
#               |              | start/stop lifecycle, status reporting, OBD callbacks
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
- hardwareManager: HardwareManager for Raspberry Pi hardware (UPS, GPIO, etc.)
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
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from .database import createDatabaseFromConfig, ObdDatabase

# Import hardware module functions with graceful fallback for non-Pi systems
try:
    from hardware.platform_utils import isRaspberryPi
    from hardware.hardware_manager import (
        HardwareManager,
        createHardwareManagerFromConfig
    )
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

    def isRaspberryPi() -> bool:
        """Fallback function when hardware module not available."""
        return False

    HardwareManager = None  # type: ignore

    def createHardwareManagerFromConfig(config: Any) -> None:
        """Fallback function when hardware module not available."""
        return None

# Import backup module with graceful fallback for optional dependency
try:
    from backup import (
        BackupManager,
        BackupConfig,
        BackupStatus,
        GoogleDriveUploader,
    )
    BACKUP_AVAILABLE = True
except ImportError:
    BACKUP_AVAILABLE = False
    BackupManager = None  # type: ignore
    BackupConfig = None  # type: ignore
    BackupStatus = None  # type: ignore
    GoogleDriveUploader = None  # type: ignore

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

# Connection recovery constants
DEFAULT_CONNECTION_CHECK_INTERVAL = 5.0  # Check connection every 5 seconds
DEFAULT_RECONNECT_DELAYS = [1, 2, 4, 8, 16]  # Exponential backoff delays in seconds
DEFAULT_MAX_RECONNECT_ATTEMPTS = 5  # Maximum reconnection attempts

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
        self._profileSwitcher: Optional[Any] = None
        self._vinDecoder: Optional[Any] = None
        self._hardwareManager: Optional[Any] = None
        self._backupManager: Optional[Any] = None
        self._googleDriveUploader: Optional[Any] = None

        # Backup scheduling state
        self._backupScheduleTimer: Optional[threading.Timer] = None
        self._lastScheduledBackupCheck: Optional[datetime] = None

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

        # Connection recovery configuration
        bluetoothConfig = config.get('bluetooth', {})
        self._connectionCheckInterval = config.get('monitoring', {}).get(
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
        self._lastConnectionCheckTime: Optional[datetime] = None
        self._reconnectThread: Optional[threading.Thread] = None
        self._dataLoggerPausedForReconnect = False

        # Vehicle VIN from first connection decode
        self._vehicleVin: Optional[str] = None

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
    def profileSwitcher(self) -> Optional[Any]:
        """Get the profile switcher instance."""
        return self._profileSwitcher

    @property
    def vinDecoder(self) -> Optional[Any]:
        """Get the VIN decoder instance."""
        return self._vinDecoder

    @property
    def hardwareManager(self) -> Optional[Any]:
        """Get the hardware manager instance (Raspberry Pi only)."""
        return self._hardwareManager

    @property
    def backupManager(self) -> Optional[Any]:
        """Get the backup manager instance."""
        return self._backupManager

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

        result: Dict[str, Any] = {
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

    def _getBackupStatus(self) -> Dict[str, Any]:
        """
        Get detailed backup status information.

        Returns:
            Dictionary with backup status details including:
            - enabled: Whether backup is enabled
            - status: Current backup status (pending, in_progress, completed, failed)
            - lastBackupTime: ISO timestamp of last backup
            - daysSinceLastBackup: Days since last backup (None if never)
            - backupCount: Total number of backups stored
            - uploaderAvailable: Whether Google Drive upload is available
            - nextScheduledBackup: Estimated time of next scheduled backup
        """
        if self._backupManager is None:
            return {'enabled': False}

        status: Dict[str, Any] = {
            'enabled': self._backupManager.isEnabled(),
            'status': self._backupManager.getStatus().value,
            'lastBackupTime': None,
            'daysSinceLastBackup': self._backupManager.getDaysSinceLastBackup(),
            'backupCount': self._backupManager.getBackupCount(),
            'uploaderAvailable': False,
        }

        # Get last backup time
        lastBackupTime = self._backupManager.getLastBackupTime()
        if lastBackupTime is not None:
            status['lastBackupTime'] = lastBackupTime.isoformat()

        # Check uploader availability
        if self._googleDriveUploader is not None:
            try:
                status['uploaderAvailable'] = self._googleDriveUploader.isAvailable()
            except Exception:
                status['uploaderAvailable'] = False

        return status

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

        # Connect profile switcher callbacks
        # ProfileSwitcher uses onProfileChange() to register profile change callback
        if self._profileSwitcher is not None and hasattr(self._profileSwitcher, 'onProfileChange'):
            try:
                self._profileSwitcher.onProfileChange(self._handleProfileChange)
                logger.debug("Profile switcher callbacks registered")
            except Exception as e:
                logger.warning(f"Could not register profile switcher callbacks: {e}")

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

        # Update hardware manager display (Pi status display) with alert count
        if self._hardwareManager is not None:
            try:
                self._hardwareManager.updateErrorCount(
                    errors=self._healthCheckStats.alertsTriggered
                )
            except Exception as e:
                logger.debug(f"Hardware display error count update failed: {e}")

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

    def _handleProfileChange(
        self, oldProfileId: Optional[str], newProfileId: str
    ) -> None:
        """
        Handle profile change event from ProfileSwitcher.

        Updates alert manager thresholds and data logger polling interval
        to match the new profile's settings.

        Args:
            oldProfileId: Previous profile ID (or None if first profile)
            newProfileId: New active profile ID
        """
        logger.info(f"Profile changed from {oldProfileId} to {newProfileId}")

        # Get the new profile from profile manager
        newProfile = None
        if self._profileManager is not None:
            try:
                newProfile = self._profileManager.getProfile(newProfileId)
            except Exception as e:
                logger.warning(f"Could not get profile {newProfileId}: {e}")

        # Update alert manager with new profile's thresholds
        if self._alertManager is not None and newProfile is not None:
            try:
                thresholds = getattr(newProfile, 'alertThresholds', {})
                if hasattr(self._alertManager, 'setProfileThresholds'):
                    self._alertManager.setProfileThresholds(newProfileId, thresholds)
                if hasattr(self._alertManager, 'setActiveProfile'):
                    self._alertManager.setActiveProfile(newProfileId)
                logger.debug(
                    f"Alert manager updated with {len(thresholds)} thresholds "
                    f"for profile {newProfileId}"
                )
            except Exception as e:
                logger.warning(f"Could not update alert manager thresholds: {e}")

        # Update data logger polling interval
        if self._dataLogger is not None and newProfile is not None:
            try:
                pollingInterval = getattr(newProfile, 'pollingIntervalMs', None)
                if pollingInterval and hasattr(self._dataLogger, 'setPollingInterval'):
                    self._dataLogger.setPollingInterval(pollingInterval)
                    logger.debug(
                        f"Data logger polling interval updated to {pollingInterval}ms"
                    )
            except Exception as e:
                logger.warning(f"Could not update data logger polling interval: {e}")

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
        """
        Handle connection lost event.

        Called when the OBD connection is detected as lost. Updates state,
        notifies display, calls external callbacks, and initiates automatic
        reconnection with exponential backoff.
        """
        logger.warning("OBD connection lost")
        self._healthCheckStats.connectionStatus = "reconnecting"
        self._healthCheckStats.connectionConnected = False

        # Update display if available
        if self._displayManager is not None and hasattr(self._displayManager, 'showConnectionStatus'):
            try:
                self._displayManager.showConnectionStatus('Reconnecting...')
            except Exception as e:
                logger.debug(f"Display connection status failed: {e}")

        # Update hardware manager display (Pi status display) if available
        if self._hardwareManager is not None:
            try:
                self._hardwareManager.updateObdStatus('reconnecting')
            except Exception as e:
                logger.debug(f"Hardware display OBD status update failed: {e}")

        # Call external callback
        if self._onConnectionLost is not None:
            try:
                self._onConnectionLost()
            except Exception as e:
                logger.warning(f"onConnectionLost callback error: {e}")

        # Start automatic reconnection
        self._startReconnection()

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

        # Update hardware manager display (Pi status display) if available
        if self._hardwareManager is not None:
            try:
                self._hardwareManager.updateObdStatus('connected')
            except Exception as e:
                logger.debug(f"Hardware display OBD status update failed: {e}")

        # Call external callback
        if self._onConnectionRestored is not None:
            try:
                self._onConnectionRestored()
            except Exception as e:
                logger.warning(f"onConnectionRestored callback error: {e}")

    # ================================================================================
    # Connection Recovery
    # ================================================================================

    def _startReconnection(self) -> None:
        """
        Start the reconnection process in a background thread.

        Called when connection loss is detected. Initiates automatic reconnection
        with exponential backoff delays.
        """
        if self._isReconnecting:
            logger.debug("Reconnection already in progress")
            return

        if self._connection is None:
            logger.warning("Cannot reconnect - no connection object available")
            return

        self._isReconnecting = True
        self._reconnectAttempt = 0

        # Pause data logging during reconnection
        self._pauseDataLogging()

        # Start reconnection in background thread
        self._reconnectThread = threading.Thread(
            target=self._reconnectionLoop,
            daemon=True,
            name="connection-recovery"
        )
        self._reconnectThread.start()
        logger.info("Connection recovery started")

    def _reconnectionLoop(self) -> None:
        """
        Reconnection loop with exponential backoff.

        Attempts to reconnect to the OBD-II dongle using the configured
        retry delays. Runs in a background thread.
        """
        while (
            self._isReconnecting
            and self._reconnectAttempt < self._maxReconnectAttempts
            and self._shutdownState == ShutdownState.RUNNING
        ):
            self._reconnectAttempt += 1

            # Get delay for this attempt
            if self._reconnectDelays:
                delayIndex = min(
                    self._reconnectAttempt - 1,
                    len(self._reconnectDelays) - 1
                )
                delay = self._reconnectDelays[delayIndex]
            else:
                delay = 0

            logger.info(
                f"Reconnection attempt {self._reconnectAttempt}/{self._maxReconnectAttempts} "
                f"in {delay}s..."
            )

            # Wait before attempting reconnection
            if delay > 0:
                # Use small sleep increments to allow for shutdown during wait
                for _ in range(int(delay * 10)):
                    if (
                        self._shutdownState != ShutdownState.RUNNING
                        or not self._isReconnecting
                    ):
                        logger.debug("Reconnection cancelled during backoff wait")
                        return
                    time.sleep(0.1)

            # Attempt reconnection
            try:
                if self._attemptReconnection():
                    self._handleReconnectionSuccess()
                    return
            except Exception as e:
                logger.warning(f"Reconnection attempt failed: {e}")

        # Max retries exceeded
        if self._reconnectAttempt >= self._maxReconnectAttempts:
            self._handleReconnectionFailure()

    def _attemptReconnection(self) -> bool:
        """
        Attempt a single reconnection to the OBD-II dongle.

        Returns:
            True if reconnection successful, False otherwise
        """
        if self._connection is None:
            return False

        try:
            # Check if connection has reconnect method (preferred)
            if hasattr(self._connection, 'reconnect'):
                return self._connection.reconnect()

            # Fall back to disconnect + connect pattern
            if hasattr(self._connection, 'disconnect'):
                self._connection.disconnect()

            if hasattr(self._connection, 'connect'):
                return self._connection.connect()

            return False

        except Exception as e:
            logger.debug(f"Reconnection attempt error: {e}")
            return False

    def _handleReconnectionSuccess(self) -> None:
        """
        Handle successful reconnection.

        Resumes data logging and updates connection state.
        """
        logger.info(
            f"Connection recovered successfully after "
            f"{self._reconnectAttempt} attempt(s)"
        )

        self._isReconnecting = False
        self._reconnectAttempt = 0

        # Update connection status
        self._healthCheckStats.connectionStatus = "connected"
        self._healthCheckStats.connectionConnected = True

        # Resume data logging
        self._resumeDataLogging()

        # Update display
        if self._displayManager is not None:
            try:
                if hasattr(self._displayManager, 'showConnectionStatus'):
                    self._displayManager.showConnectionStatus('Connected')
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # Call external callback
        if self._onConnectionRestored is not None:
            try:
                self._onConnectionRestored()
            except Exception as e:
                logger.warning(f"onConnectionRestored callback error: {e}")

    def _handleReconnectionFailure(self) -> None:
        """
        Handle reconnection failure after max retries exceeded.

        Logs the error but allows the system to continue running.
        Data logging remains paused since connection is unavailable.
        """
        logger.error(
            f"Connection recovery failed after {self._maxReconnectAttempts} attempts. "
            f"System will continue running without OBD connection."
        )

        self._isReconnecting = False

        # Update connection status
        self._healthCheckStats.connectionStatus = "disconnected"
        self._healthCheckStats.connectionConnected = False
        self._healthCheckStats.totalErrors += 1

        # Update display to show disconnected state
        if self._displayManager is not None:
            try:
                if hasattr(self._displayManager, 'showConnectionStatus'):
                    self._displayManager.showConnectionStatus('Disconnected')
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

        # Note: Data logging remains paused since connection is unavailable
        # The system continues running so user can monitor other aspects
        # or manually intervene

    def _pauseDataLogging(self) -> None:
        """
        Pause data logging during reconnection.

        Stops the data logger polling to prevent errors while connection
        is unavailable.
        """
        if self._dataLogger is None or self._dataLoggerPausedForReconnect:
            return

        try:
            if hasattr(self._dataLogger, 'stop'):
                self._dataLogger.stop()
                self._dataLoggerPausedForReconnect = True
                logger.info("Data logging paused during reconnection")
        except Exception as e:
            logger.warning(f"Failed to pause data logging: {e}")

    def _resumeDataLogging(self) -> None:
        """
        Resume data logging after successful reconnection.

        Restarts the data logger if it was paused for reconnection.
        """
        if self._dataLogger is None or not self._dataLoggerPausedForReconnect:
            return

        try:
            if hasattr(self._dataLogger, 'start'):
                self._dataLogger.start()
                self._dataLoggerPausedForReconnect = False
                logger.info("Data logging resumed after reconnection")
        except Exception as e:
            logger.warning(f"Failed to resume data logging: {e}")

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
        6. hardwareManager - Pi hardware (after display, so display fallback is available)
        7. statisticsEngine - data analysis (before driveDetector so it can
                              be passed to driveDetector for post-drive analysis)
        8. driveDetector - drive session detection (needs statisticsEngine)
        9. alertManager - threshold alerts
        10. dataLogger - continuous logging
        11. profileSwitcher - profile switching (after driveDetector for drive-aware switching)
        12. backupManager - backup system (last, non-critical to core operation)
        """
        self._initializeDatabase()
        self._initializeProfileManager()
        self._initializeConnection()
        self._initializeVinDecoder()
        # Perform VIN decode on first connection (requires both connection and vinDecoder)
        self._performFirstConnectionVinDecode()
        self._initializeDisplayManager()
        self._initializeHardwareManager()
        self._initializeStatisticsEngine()
        self._initializeDriveDetector()
        self._initializeAlertManager()
        self._initializeDataLogger()
        self._initializeProfileSwitcher()
        self._initializeBackupManager()

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

            # Perform first-connection VIN decode after successful connection
            # This is deferred until after VIN decoder is initialized (called from start())

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

    def _performFirstConnectionVinDecode(self) -> None:
        """
        Perform VIN decode on first successful connection.

        This method is called after the connection is established and VIN decoder
        is initialized. It:
        1. Queries VIN from vehicle
        2. Checks if VIN is already cached in database
        3. If not cached, calls NHTSA API to decode VIN
        4. Stores decoded info in database
        5. Displays vehicle info on startup

        API timeouts are handled gracefully - the application continues without
        the decoded vehicle info if the API is unavailable.
        """
        # Check preconditions
        if self._connection is None:
            logger.debug("VIN decode skipped: no connection available")
            return

        if self._vinDecoder is None:
            logger.debug("VIN decode skipped: no VIN decoder configured")
            return

        # Query VIN from vehicle
        try:
            if not hasattr(self._connection, 'obd') or self._connection.obd is None:
                logger.debug("VIN decode skipped: connection has no OBD interface")
                return

            vinResponse = self._connection.obd.query("VIN")

            # Check for null response
            if vinResponse is None or vinResponse.is_null():
                logger.debug("VIN decode skipped: vehicle returned null VIN response")
                return

            vin = vinResponse.value
            if not vin:
                logger.debug("VIN decode skipped: VIN value is empty")
                return

            logger.debug(f"VIN queried from vehicle: {vin}")

        except Exception as e:
            logger.warning(f"Failed to query VIN from vehicle: {e}")
            return

        # Check if VIN is already cached
        try:
            if self._vinDecoder.isVinCached(vin):
                logger.debug(f"VIN {vin} found in cache, using cached data")
                decodeResult = self._vinDecoder.getDecodedVin(vin)
            else:
                # VIN not cached, decode via NHTSA API
                logger.info(f"Decoding VIN via NHTSA API: {vin}")
                decodeResult = self._vinDecoder.decodeVin(vin)

        except Exception as e:
            logger.warning(f"VIN decode failed: {e}")
            return

        # Store VIN in orchestrator for reference
        self._vehicleVin = vin

        # Process decode result
        if decodeResult is not None and decodeResult.success:
            vehicleSummary = decodeResult.getVehicleSummary()
            logger.info(f"Connected to {vehicleSummary}")

            # Display vehicle info
            self._displayVehicleInfo(decodeResult)
        else:
            errorMsg = getattr(decodeResult, 'errorMessage', 'Unknown error') if decodeResult else 'No result'
            logger.warning(f"VIN decode unsuccessful: {errorMsg}")

    def _displayVehicleInfo(self, decodeResult: Any) -> None:
        """
        Display decoded vehicle info on the display manager.

        Falls back to showConnectionStatus if showVehicleInfo is not available.

        Args:
            decodeResult: VinDecodeResult with vehicle information
        """
        if self._displayManager is None:
            return

        vehicleSummary = decodeResult.getVehicleSummary()

        try:
            # Try showVehicleInfo first
            if hasattr(self._displayManager, 'showVehicleInfo'):
                self._displayManager.showVehicleInfo(vehicleSummary)
            # Fall back to showConnectionStatus
            elif hasattr(self._displayManager, 'showConnectionStatus'):
                self._displayManager.showConnectionStatus(f"Connected to {vehicleSummary}")
        except Exception as e:
            logger.debug(f"Display vehicle info failed: {e}")

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
        """
        Initialize the display manager component.

        Display mode is selected from config['display']['mode']:
        - headless: No display output, logging only
        - minimal: Adafruit 1.3" 240x240 TFT display
        - developer: Full-featured console display

        If display hardware is unavailable, gracefully falls back to headless mode.
        The display is initialized and shows a welcome screen on startup.
        """
        logger.info("Starting displayManager...")
        try:
            from .display_manager import createDisplayManagerFromConfig
            self._displayManager = createDisplayManagerFromConfig(self._config)

            # Initialize the display driver
            if not self._displayManager.initialize():
                logger.warning(
                    "Display initialization failed, falling back to headless mode"
                )
                # Fall back to headless if display hardware unavailable
                self._displayManager = self._createHeadlessDisplayFallback()

            # Show welcome screen on startup
            if self._displayManager is not None:
                displayMode = getattr(self._displayManager, 'mode', None)
                modeValue = displayMode.value if displayMode else 'unknown'
                self._displayManager.showWelcomeScreen(
                    appName="Eclipse OBD-II Monitor",
                    version="1.0.0"
                )
                logger.info(f"DisplayManager started successfully | mode={modeValue}")
            else:
                logger.info("DisplayManager started successfully")

        except ImportError:
            logger.warning("DisplayManager not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize displayManager: {e}")
            raise ComponentInitializationError(
                f"DisplayManager initialization failed: {e}",
                component='displayManager'
            ) from e

    def _createHeadlessDisplayFallback(self) -> Optional[Any]:
        """
        Create a headless display manager as fallback when hardware unavailable.

        Returns:
            Initialized headless DisplayManager or None if unavailable
        """
        try:
            from .display_manager import createDisplayManagerFromConfig
            headlessConfig = dict(self._config)
            headlessConfig['display'] = {
                **self._config.get('display', {}),
                'mode': 'headless'
            }
            fallbackDisplay = createDisplayManagerFromConfig(headlessConfig)
            if fallbackDisplay.initialize():
                logger.info("Fallback to headless display mode successful")
                return fallbackDisplay
            return None
        except Exception as e:
            logger.warning(f"Could not create headless fallback: {e}")
            return None

    def _initializeHardwareManager(self) -> None:
        """
        Initialize the hardware manager component (Raspberry Pi only).

        Only initializes on Raspberry Pi systems when hardware.enabled is True.
        On non-Pi systems, logs debug message and skips initialization.
        """
        # Check if hardware module is available
        if not HARDWARE_AVAILABLE:
            logger.debug("Hardware module not available, skipping HardwareManager")
            return

        # Check if running on Raspberry Pi
        if not isRaspberryPi():
            logger.debug("Not running on Raspberry Pi, skipping HardwareManager")
            return

        # Check if hardware is enabled in config
        hardwareEnabled = self._config.get('hardware', {}).get('enabled', True)
        if not hardwareEnabled:
            logger.info("HardwareManager disabled by configuration")
            return

        logger.info("Starting hardwareManager...")
        try:
            self._hardwareManager = createHardwareManagerFromConfig(self._config)
            logger.info("HardwareManager initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize hardwareManager: {e}")
            self._hardwareManager = None

    def _startHardwareManager(self) -> None:
        """
        Start the hardware manager.

        Should be called during runLoop startup to begin hardware monitoring.
        """
        if self._hardwareManager is None:
            return

        try:
            self._hardwareManager.start()
            logger.info("HardwareManager started")
        except Exception as e:
            logger.warning(f"Failed to start hardwareManager: {e}")

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

    def _initializeProfileSwitcher(self) -> None:
        """
        Initialize the profile switcher component.

        Creates a ProfileSwitcher wired to profileManager, driveDetector,
        displayManager, and database for drive-aware profile switching.
        """
        logger.info("Starting profileSwitcher...")
        try:
            from .profile_manager import createProfileSwitcherFromConfig
            self._profileSwitcher = createProfileSwitcherFromConfig(
                self._config,
                profileManager=self._profileManager,
                driveDetector=self._driveDetector,
                displayManager=self._displayManager,
                database=self._database
            )
            logger.info("ProfileSwitcher started successfully")
        except ImportError:
            logger.warning("ProfileSwitcher not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize profileSwitcher: {e}")
            raise ComponentInitializationError(
                f"ProfileSwitcher initialization failed: {e}",
                component='profileSwitcher'
            ) from e

    def _initializeBackupManager(self) -> None:
        """
        Initialize the backup manager component if enabled.

        Only initializes if backup.enabled is true in config and the
        backup module is available. Also performs catch-up backup check
        on startup and schedules daily backups.
        """
        if not BACKUP_AVAILABLE:
            logger.debug("Backup module not available, skipping")
            return

        # Check if backup is enabled in config
        backupConfig = self._config.get('backup', {})
        if not backupConfig.get('enabled', False):
            logger.debug("Backup is disabled in config, skipping initialization")
            return

        logger.info("Starting backupManager...")
        try:
            # Create BackupConfig from config dict
            config = BackupConfig.fromDict(backupConfig)

            # Determine data directory - use database path if available
            dataDir = 'data'
            dbConfig = self._config.get('database', {})
            if 'path' in dbConfig:
                import os
                dataDir = os.path.dirname(dbConfig['path']) or 'data'

            # Create backup manager
            self._backupManager = BackupManager(config=config, dataDir=dataDir)

            # Create Google Drive uploader if provider is google_drive
            if config.provider == 'google_drive':
                self._googleDriveUploader = GoogleDriveUploader()
                if self._googleDriveUploader.isAvailable():
                    logger.info("Google Drive uploader available")
                else:
                    logger.warning(
                        "Google Drive uploader not available "
                        "(rclone not installed or not configured)"
                    )

            logger.info("BackupManager started successfully")

            # Perform catch-up backup check on startup
            self._performCatchupBackupCheck()

            # Schedule daily backups at configured time
            self._scheduleNextBackup()

        except Exception as e:
            logger.error(f"Failed to initialize backupManager: {e}")
            # Backup failure is non-critical - log warning but don't raise
            logger.warning("Backup system unavailable, continuing without backup")
            self._backupManager = None
            self._googleDriveUploader = None

    def _performCatchupBackupCheck(self) -> None:
        """
        Check if a catch-up backup should be run on startup.

        A catch-up backup is needed if more than catchupDays have passed
        since the last backup (or if no backup has ever been performed).
        """
        if self._backupManager is None:
            return

        if not self._backupManager.isEnabled():
            return

        try:
            if self._backupManager.shouldRunCatchupBackup():
                daysSinceBackup = self._backupManager.getDaysSinceLastBackup()
                if daysSinceBackup is None:
                    logger.info("No previous backup found, running catch-up backup")
                else:
                    logger.info(
                        f"Running catch-up backup: {daysSinceBackup} days since last backup"
                    )

                # Perform the catch-up backup
                self._performBackup()
            else:
                logger.debug("No catch-up backup needed")
        except Exception as e:
            logger.warning(f"Catch-up backup check failed: {e}")

    def _performBackup(self) -> bool:
        """
        Perform a backup operation, including optional upload to Google Drive.

        Returns:
            True if backup (and optional upload) succeeded, False otherwise
        """
        if self._backupManager is None:
            return False

        try:
            # Perform local backup
            result = self._backupManager.performBackup()

            if not result.success:
                logger.error(f"Backup failed: {result.error}")
                return False

            logger.info(
                f"Backup completed: {result.backupPath} "
                f"({result.size / 1024:.1f} KB)"
            )

            # Upload to Google Drive if available
            if (
                self._googleDriveUploader is not None
                and self._googleDriveUploader.isAvailable()
            ):
                try:
                    config = self._backupManager.getConfig()
                    remotePath = f"{config.folderPath}/{result.backupPath.split('/')[-1]}"
                    uploadResult = self._googleDriveUploader.upload(
                        result.backupPath,
                        remotePath
                    )
                    if uploadResult.success:
                        logger.info(f"Backup uploaded to Google Drive: {remotePath}")
                    else:
                        logger.warning(
                            f"Google Drive upload failed: {uploadResult.error}"
                        )
                except Exception as e:
                    logger.warning(f"Google Drive upload error: {e}")

            # Clean up old backups
            self._backupManager.cleanupOldBackups()

            return True

        except Exception as e:
            logger.error(f"Backup operation failed: {e}")
            return False

    def _scheduleNextBackup(self) -> None:
        """
        Schedule the next daily backup at the configured time.

        Parses scheduleTime (HH:MM format) and schedules a timer
        to run the backup at that time tomorrow (or today if not yet passed).
        """
        if self._backupManager is None:
            return

        if not self._backupManager.isEnabled():
            return

        try:
            config = self._backupManager.getConfig()
            scheduleTime = config.scheduleTime  # e.g., "03:00"

            # Parse schedule time
            hour, minute = map(int, scheduleTime.split(':'))

            # Calculate next backup time
            now = datetime.now()
            scheduleDate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If the time has passed today, schedule for tomorrow
            if scheduleDate <= now:
                scheduleDate = scheduleDate + timedelta(days=1)

            # Calculate seconds until next backup
            secondsUntilBackup = (scheduleDate - now).total_seconds()

            # Cancel existing timer if any
            if self._backupScheduleTimer is not None:
                self._backupScheduleTimer.cancel()

            # Create new timer
            self._backupScheduleTimer = threading.Timer(
                secondsUntilBackup,
                self._runScheduledBackup
            )
            self._backupScheduleTimer.daemon = True
            self._backupScheduleTimer.start()

            logger.info(
                f"Next backup scheduled at {scheduleDate.strftime('%Y-%m-%d %H:%M')}"
            )

        except ValueError as e:
            logger.error(f"Invalid backup schedule time format: {e}")
        except Exception as e:
            logger.warning(f"Failed to schedule backup: {e}")

    def _runScheduledBackup(self) -> None:
        """
        Run a scheduled backup and reschedule the next one.

        Called by the backup schedule timer. Performs the backup,
        then schedules the next backup for tomorrow.
        """
        if not self._running:
            return

        logger.info("Running scheduled daily backup")

        try:
            self._performBackup()
        except Exception as e:
            logger.error(f"Scheduled backup failed: {e}")
        finally:
            # Schedule next backup for tomorrow
            self._scheduleNextBackup()

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
        1. backupManager (first, was initialized last)
        2. profileSwitcher (before driveDetector uses it)
        3. dataLogger
        4. alertManager
        5. driveDetector (before statisticsEngine - may still be triggering analysis)
        6. statisticsEngine
        7. hardwareManager (before displayManager - may be using display)
        8. displayManager
        9. vinDecoder
        10. connection
        11. profileManager
        12. database
        """
        self._shutdownBackupManager()
        self._shutdownProfileSwitcher()
        self._shutdownDataLogger()
        self._shutdownAlertManager()
        self._shutdownDriveDetector()
        self._shutdownStatisticsEngine()
        self._shutdownHardwareManager()
        self._shutdownDisplayManager()
        self._shutdownVinDecoder()
        self._shutdownConnection()
        self._shutdownProfileManager()
        self._shutdownDatabase()

    def _shutdownBackupManager(self) -> None:
        """
        Shutdown the backup manager component.

        Cancels any pending backup schedule timer and clears references.
        """
        # Cancel scheduled backup timer
        if self._backupScheduleTimer is not None:
            try:
                self._backupScheduleTimer.cancel()
                logger.debug("Cancelled scheduled backup timer")
            except Exception as e:
                logger.debug(f"Error cancelling backup timer: {e}")
            finally:
                self._backupScheduleTimer = None

        # Clear backup manager and uploader references
        if self._backupManager is not None:
            logger.info("Stopping backupManager...")
            logger.info("BackupManager stopped successfully")
            self._backupManager = None

        self._googleDriveUploader = None

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

    def _shutdownHardwareManager(self) -> None:
        """
        Shutdown the hardware manager component.

        Stops hardware monitoring and releases all Pi-specific resources.
        """
        if self._hardwareManager is None:
            return

        logger.info("Stopping hardwareManager...")
        try:
            self._hardwareManager.stop()
            logger.info("HardwareManager stopped successfully")
        except Exception as e:
            logger.warning(f"Error stopping hardwareManager: {e}")
        finally:
            self._hardwareManager = None

    def _shutdownDisplayManager(self) -> None:
        """
        Shutdown the display manager component.

        Shows 'Shutting down...' message on display before stopping.
        """
        # Show shutdown message on display before stopping
        if self._displayManager is not None:
            try:
                if hasattr(self._displayManager, 'showShutdownMessage'):
                    self._displayManager.showShutdownMessage()
            except Exception as e:
                logger.debug(f"Display shutdown message failed: {e}")

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

    def _shutdownProfileSwitcher(self) -> None:
        """Shutdown the profile switcher component."""
        self._stopComponentWithTimeout(self._profileSwitcher, 'profileSwitcher')
        self._profileSwitcher = None

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
    'DEFAULT_DATA_RATE_LOG_INTERVAL',
    'DEFAULT_CONNECTION_CHECK_INTERVAL',
    'DEFAULT_RECONNECT_DELAYS',
    'DEFAULT_MAX_RECONNECT_ATTEMPTS',
    'EXIT_CODE_CLEAN',
    'EXIT_CODE_FORCED',
    'EXIT_CODE_ERROR',
    # Factory functions
    'createOrchestratorFromConfig',
]
