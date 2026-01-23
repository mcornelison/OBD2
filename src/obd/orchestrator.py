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
import time
from typing import Any, Dict, Optional

from .database import createDatabaseFromConfig, ObdDatabase

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Default component shutdown timeout in seconds
DEFAULT_SHUTDOWN_TIMEOUT = 5.0


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

    def stop(self) -> None:
        """
        Stop the orchestrator and all managed components.

        Shuts down all components in reverse dependency order.
        Errors during shutdown are logged but do not stop the shutdown process.
        """
        if not self._running:
            logger.debug("Orchestrator not running, nothing to stop")
            return

        logger.info("Stopping ApplicationOrchestrator...")

        self._shutdownAllComponents()
        self._running = False

        logger.info("ApplicationOrchestrator stopped")

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
        6. driveDetector - drive session detection
        7. alertManager - threshold alerts
        8. statisticsEngine - data analysis
        9. dataLogger - continuous logging
        """
        self._initializeDatabase()
        self._initializeProfileManager()
        self._initializeConnection()
        self._initializeVinDecoder()
        self._initializeDisplayManager()
        self._initializeDriveDetector()
        self._initializeAlertManager()
        self._initializeStatisticsEngine()
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

    def _shutdownAllComponents(self) -> None:
        """
        Shutdown all components in reverse dependency order.

        Order:
        1. dataLogger
        2. alertManager
        3. driveDetector
        4. statisticsEngine
        5. displayManager
        6. connection
        7. database
        """
        self._shutdownDataLogger()
        self._shutdownAlertManager()
        self._shutdownDriveDetector()
        self._shutdownStatisticsEngine()
        self._shutdownDisplayManager()
        self._shutdownConnection()
        self._shutdownDatabase()

    def _shutdownDataLogger(self) -> None:
        """Shutdown the data logger component."""
        if self._dataLogger is not None:
            logger.info("Stopping dataLogger...")
            try:
                if hasattr(self._dataLogger, 'stop'):
                    self._dataLogger.stop()
                logger.info("DataLogger stopped successfully")
            except Exception as e:
                logger.warning(f"Error stopping dataLogger: {e}")
            finally:
                self._dataLogger = None

    def _shutdownAlertManager(self) -> None:
        """Shutdown the alert manager component."""
        if self._alertManager is not None:
            logger.info("Stopping alertManager...")
            try:
                if hasattr(self._alertManager, 'stop'):
                    self._alertManager.stop()
                logger.info("AlertManager stopped successfully")
            except Exception as e:
                logger.warning(f"Error stopping alertManager: {e}")
            finally:
                self._alertManager = None

    def _shutdownDriveDetector(self) -> None:
        """Shutdown the drive detector component."""
        if self._driveDetector is not None:
            logger.info("Stopping driveDetector...")
            try:
                if hasattr(self._driveDetector, 'stop'):
                    self._driveDetector.stop()
                logger.info("DriveDetector stopped successfully")
            except Exception as e:
                logger.warning(f"Error stopping driveDetector: {e}")
            finally:
                self._driveDetector = None

    def _shutdownStatisticsEngine(self) -> None:
        """Shutdown the statistics engine component."""
        if self._statisticsEngine is not None:
            logger.info("Stopping statisticsEngine...")
            try:
                if hasattr(self._statisticsEngine, 'stop'):
                    self._statisticsEngine.stop()
                logger.info("StatisticsEngine stopped successfully")
            except Exception as e:
                logger.warning(f"Error stopping statisticsEngine: {e}")
            finally:
                self._statisticsEngine = None

    def _shutdownDisplayManager(self) -> None:
        """Shutdown the display manager component."""
        if self._displayManager is not None:
            logger.info("Stopping displayManager...")
            try:
                if hasattr(self._displayManager, 'stop'):
                    self._displayManager.stop()
                logger.info("DisplayManager stopped successfully")
            except Exception as e:
                logger.warning(f"Error stopping displayManager: {e}")
            finally:
                self._displayManager = None

    def _shutdownConnection(self) -> None:
        """Shutdown the OBD-II connection component."""
        if self._connection is not None:
            logger.info("Stopping connection...")
            try:
                if hasattr(self._connection, 'disconnect'):
                    self._connection.disconnect()
                elif hasattr(self._connection, 'stop'):
                    self._connection.stop()
                logger.info("Connection stopped successfully")
            except Exception as e:
                logger.warning(f"Error stopping connection: {e}")
            finally:
                self._connection = None

    def _shutdownDatabase(self) -> None:
        """Shutdown the database component."""
        if self._database is not None:
            logger.info("Stopping database...")
            try:
                # Database uses context managers, no explicit close needed
                # but we clear the reference
                logger.info("Database stopped successfully")
            except Exception as e:
                logger.warning(f"Error stopping database: {e}")
            finally:
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
    # Exceptions
    'OrchestratorError',
    'ComponentInitializationError',
    'ComponentStartError',
    'ComponentStopError',
    # Factory functions
    'createOrchestratorFromConfig',
]
