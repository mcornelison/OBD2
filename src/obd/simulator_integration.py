################################################################################
# File Name: simulator_integration.py
# Purpose/Description: Integration module connecting simulator to existing OBD components
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-039
# ================================================================================
################################################################################

"""
Simulator integration module for the Eclipse OBD-II Performance Monitoring System.

Provides integration between the OBD-II simulator and existing system components:
- ObdDataLogger and RealtimeDataLogger for data acquisition
- AlertManager for threshold-based alerts
- DriveDetector for drive session detection
- StatisticsEngine for post-drive analysis
- DisplayManager for visual output

This module enables full-pipeline testing without actual vehicle hardware.

Usage:
    from obd.simulator_integration import (
        createIntegratedConnection,
        SimulatorIntegration,
        IntegrationConfig
    )

    # Create integrated connection based on config and --simulate flag
    conn = createIntegratedConnection(config, database, simulateFlag=True)

    # Or use the full integration manager
    integration = SimulatorIntegration(config, database)
    integration.initialize(simulateFlag=True)
    integration.start()

    # Later...
    integration.stop()
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .obd_config_loader import (
    getSimulatorConfig,
    isSimulatorEnabled,
)
from .obd_connection import (
    ObdConnection,
)
from .obd_connection import (
    createConnectionFromConfig as createRealConnection,
)
from .simulator import (
    DriveScenarioRunner,
    FailureInjector,
    FailureType,
    SensorSimulator,
    SimulatedObdConnection,
    createFailureInjectorFromConfig,
    loadProfile,
    loadScenario,
)

logger = logging.getLogger(__name__)


# ================================================================================
# Enums
# ================================================================================

class IntegrationState(Enum):
    """State of the simulator integration."""
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class IntegrationConfig:
    """
    Configuration for simulator integration.

    Attributes:
        enabled: Whether simulation is enabled
        profilePath: Path to vehicle profile JSON
        scenarioPath: Path to drive scenario JSON (optional)
        connectionDelaySeconds: Simulated connection delay
        updateIntervalMs: Simulator update interval
        autoStartScenario: Auto-start scenario on connection
        failureConfig: Failure injection configuration
    """
    enabled: bool = False
    profilePath: str = ""
    scenarioPath: str = ""
    connectionDelaySeconds: float = 2.0
    updateIntervalMs: int = 100
    autoStartScenario: bool = False
    failureConfig: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def fromConfig(
        cls,
        config: dict[str, Any],
        simulateFlag: bool = False
    ) -> "IntegrationConfig":
        """
        Create IntegrationConfig from application config.

        Args:
            config: Application configuration dictionary
            simulateFlag: True if --simulate CLI flag was passed

        Returns:
            IntegrationConfig instance
        """
        simConfig = getSimulatorConfig(config)

        return cls(
            enabled=isSimulatorEnabled(config, simulateFlag),
            profilePath=simConfig.get('profilePath', ''),
            scenarioPath=simConfig.get('scenarioPath', ''),
            connectionDelaySeconds=simConfig.get('connectionDelaySeconds', 2.0),
            updateIntervalMs=simConfig.get('updateIntervalMs', 100),
            autoStartScenario=simConfig.get('autoStartScenario', False),
            failureConfig=simConfig.get('failures', {}),
        )


@dataclass
class IntegrationStats:
    """
    Statistics for simulator integration.

    Attributes:
        startTime: When integration started
        connectionTime: When connected
        updateCount: Number of simulator updates
        readingsGenerated: Number of simulated readings
        alertsTriggered: Number of alerts triggered
        drivesDetected: Number of drives detected
        scenariosRun: Number of scenarios executed
    """
    startTime: datetime | None = None
    connectionTime: datetime | None = None
    updateCount: int = 0
    readingsGenerated: int = 0
    alertsTriggered: int = 0
    drivesDetected: int = 0
    scenariosRun: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'startTime': self.startTime.isoformat() if self.startTime else None,
            'connectionTime': self.connectionTime.isoformat() if self.connectionTime else None,
            'updateCount': self.updateCount,
            'readingsGenerated': self.readingsGenerated,
            'alertsTriggered': self.alertsTriggered,
            'drivesDetected': self.drivesDetected,
            'scenariosRun': self.scenariosRun,
        }


# ================================================================================
# Exceptions
# ================================================================================

class SimulatorIntegrationError(Exception):
    """Base exception for simulator integration errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SimulatorConfigurationError(SimulatorIntegrationError):
    """Error in simulator configuration."""
    pass


class SimulatorConnectionError(SimulatorIntegrationError):
    """Error connecting to simulator."""
    pass


# ================================================================================
# Factory Functions
# ================================================================================

def createIntegratedConnection(
    config: dict[str, Any],
    database: Any | None = None,
    simulateFlag: bool = False
) -> ObdConnection | SimulatedObdConnection:
    """
    Create an OBD connection based on configuration and simulation flag.

    This is the primary factory function for creating connections. When simulation
    mode is enabled (either via config or --simulate flag), returns a
    SimulatedObdConnection. Otherwise returns a real ObdConnection.

    Args:
        config: Application configuration dictionary
        database: Optional ObdDatabase instance for logging
        simulateFlag: True if --simulate CLI flag was passed

    Returns:
        ObdConnection or SimulatedObdConnection based on simulation mode

    Example:
        # In main.py
        conn = createIntegratedConnection(config, db, args.simulate)
        conn.connect()

        # Works the same regardless of connection type
        response = conn.obd.query("RPM")
        print(f"RPM: {response.value}")
    """
    # Check if simulation mode is enabled
    if isSimulatorEnabled(config, simulateFlag):
        logger.info("Creating SimulatedObdConnection (simulation mode enabled)")
        return _createSimulatedConnection(config, database)
    else:
        logger.info("Creating real ObdConnection")
        return createRealConnection(config, database)


def _createSimulatedConnection(
    config: dict[str, Any],
    database: Any | None = None
) -> SimulatedObdConnection:
    """
    Create a SimulatedObdConnection from configuration.

    Loads vehicle profile and configures the simulator based on config settings.

    Args:
        config: Application configuration dictionary
        database: Optional database instance (for compatibility)

    Returns:
        Configured SimulatedObdConnection instance
    """
    simConfig = getSimulatorConfig(config)

    # Load vehicle profile if specified
    profile = None
    profilePath = simConfig.get('profilePath', '')
    if profilePath:
        try:
            profile = loadProfile(profilePath)
            logger.info(f"Loaded vehicle profile: {profilePath}")
        except Exception as e:
            logger.warning(f"Failed to load vehicle profile '{profilePath}': {e}")
            logger.info("Using default vehicle profile")

    # Create connection with configuration
    connection = SimulatedObdConnection(
        profile=profile,
        connectionDelaySeconds=simConfig.get('connectionDelaySeconds', 2.0),
        config=config,
        database=database
    )

    return connection


# ================================================================================
# Simulator Integration Class
# ================================================================================

class SimulatorIntegration:
    """
    Manages integration between simulator and existing OBD system components.

    Provides a unified interface for:
    - Managing simulated OBD connections
    - Running drive scenarios
    - Injecting failures for testing
    - Coordinating with data loggers, alert managers, and drive detectors
    - Updating display with simulated data

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)

        integration = SimulatorIntegration(config, db)
        integration.initialize(simulateFlag=True)

        # Set up components
        integration.setDataLogger(dataLogger)
        integration.setAlertManager(alertManager)
        integration.setDriveDetector(driveDetector)
        integration.setDisplayManager(displayManager)

        # Start simulation
        integration.start()

        # Run a scenario
        integration.runScenario('city_driving')

        # Inject a failure
        integration.injectFailure(FailureType.SENSOR_FAILURE, sensors=['RPM'])

        # Stop
        integration.stop()
    """

    def __init__(
        self,
        config: dict[str, Any],
        database: Any | None = None
    ):
        """
        Initialize the simulator integration.

        Args:
            config: Application configuration dictionary
            database: Optional ObdDatabase instance
        """
        self._config = config
        self._database = database

        # Integration configuration
        self._integrationConfig: IntegrationConfig | None = None

        # Core components
        self._connection: SimulatedObdConnection | None = None
        self._scenarioRunner: DriveScenarioRunner | None = None
        self._failureInjector: FailureInjector | None = None

        # Connected OBD components
        self._dataLogger: Any | None = None
        self._realtimeLogger: Any | None = None
        self._alertManager: Any | None = None
        self._driveDetector: Any | None = None
        self._statisticsEngine: Any | None = None
        self._displayManager: Any | None = None

        # State tracking
        self._state = IntegrationState.IDLE
        self._stats = IntegrationStats()

        # Update thread
        self._updateThread: threading.Thread | None = None
        self._stopEvent = threading.Event()
        self._lock = threading.Lock()

        # Callbacks
        self._onReadingGenerated: Callable[[dict[str, float]], None] | None = None
        self._onAlertTriggered: Callable[[str, float], None] | None = None
        self._onDriveStateChange: Callable[[str, str], None] | None = None

    # ================================================================================
    # Initialization
    # ================================================================================

    def initialize(self, simulateFlag: bool = False) -> bool:
        """
        Initialize the simulator integration.

        Args:
            simulateFlag: True if --simulate CLI flag was passed

        Returns:
            True if initialization successful

        Raises:
            SimulatorConfigurationError: If configuration is invalid
        """
        with self._lock:
            if self._state != IntegrationState.IDLE:
                logger.warning(f"Cannot initialize in state: {self._state.value}")
                return False

            self._state = IntegrationState.INITIALIZING
            self._stats.startTime = datetime.now()

        try:
            # Load integration configuration
            self._integrationConfig = IntegrationConfig.fromConfig(
                self._config, simulateFlag
            )

            if not self._integrationConfig.enabled:
                logger.info("Simulator integration not enabled")
                self._state = IntegrationState.IDLE
                return False

            # Create simulated connection
            self._connection = _createSimulatedConnection(
                self._config, self._database
            )

            # Create failure injector
            failuresConfig = self._integrationConfig.failureConfig
            if failuresConfig:
                self._failureInjector = createFailureInjectorFromConfig(
                    {'failures': failuresConfig}
                )
                # Connect to simulator
                if self._connection and self._failureInjector:
                    self._connectFailureInjector()

            logger.info("Simulator integration initialized")
            with self._lock:
                self._state = IntegrationState.STOPPED

            return True

        except Exception as e:
            logger.error(f"Failed to initialize simulator integration: {e}")
            self._state = IntegrationState.ERROR
            raise SimulatorConfigurationError(
                f"Initialization failed: {e}",
                details={'error': str(e)}
            ) from e

    def _connectFailureInjector(self) -> None:
        """Connect failure injector to simulator."""
        if not self._failureInjector or not self._connection:
            return

        # The failure injector modifies sensor values
        # We need to intercept queries and apply failures
        originalQuery = self._connection.simulator.getValue

        def queryWithFailures(parameterName: str) -> float | None:
            """Query with failure injection applied."""
            # Check if this sensor should fail
            if self._failureInjector.shouldSensorFail(parameterName):
                logger.debug(f"Sensor failure injected: {parameterName}")
                return None

            # Get the original value
            value = originalQuery(parameterName)

            # Apply any value modifications (e.g., out of range)
            if value is not None:
                value = self._failureInjector.getModifiedValue(parameterName, value)

            return value

        # Monkey-patch the getValue method
        self._connection.simulator.getValue = queryWithFailures

    # ================================================================================
    # Component Registration
    # ================================================================================

    def setDataLogger(self, dataLogger: Any) -> None:
        """Set the ObdDataLogger instance."""
        self._dataLogger = dataLogger

    def setRealtimeLogger(self, realtimeLogger: Any) -> None:
        """Set the RealtimeDataLogger instance."""
        self._realtimeLogger = realtimeLogger

    def setAlertManager(self, alertManager: Any) -> None:
        """Set the AlertManager instance."""
        self._alertManager = alertManager

    def setDriveDetector(self, driveDetector: Any) -> None:
        """Set the DriveDetector instance."""
        self._driveDetector = driveDetector

    def setStatisticsEngine(self, statisticsEngine: Any) -> None:
        """Set the StatisticsEngine instance."""
        self._statisticsEngine = statisticsEngine

    def setDisplayManager(self, displayManager: Any) -> None:
        """Set the DisplayManager instance."""
        self._displayManager = displayManager

    def getConnection(self) -> SimulatedObdConnection | None:
        """Get the simulated connection."""
        return self._connection

    def getSimulator(self) -> SensorSimulator | None:
        """Get the underlying sensor simulator."""
        if self._connection:
            return self._connection.simulator
        return None

    def getFailureInjector(self) -> FailureInjector | None:
        """Get the failure injector."""
        return self._failureInjector

    # ================================================================================
    # Lifecycle
    # ================================================================================

    def start(self) -> bool:
        """
        Start the simulator integration.

        Connects to the simulated OBD-II and starts the update loop.

        Returns:
            True if started successfully
        """
        with self._lock:
            if self._state not in (IntegrationState.STOPPED, IntegrationState.IDLE):
                logger.warning(f"Cannot start in state: {self._state.value}")
                return False

            if not self._connection:
                logger.error("No simulated connection - call initialize() first")
                return False

            self._state = IntegrationState.RUNNING

        # Connect
        if not self._connection.isConnected():
            logger.info("Connecting to simulated OBD-II...")
            self._connection.connect()
            self._stats.connectionTime = datetime.now()

        # Start update thread
        self._stopEvent.clear()
        self._updateThread = threading.Thread(
            target=self._updateLoop,
            name='SimulatorIntegration',
            daemon=True
        )
        self._updateThread.start()

        logger.info("Simulator integration started")

        # Auto-start scenario if configured
        if (self._integrationConfig and
                self._integrationConfig.autoStartScenario and
                self._integrationConfig.scenarioPath):
            self.runScenarioFromPath(self._integrationConfig.scenarioPath)

        return True

    def stop(self, timeout: float = 5.0) -> bool:
        """
        Stop the simulator integration.

        Args:
            timeout: Maximum time to wait for threads to stop

        Returns:
            True if stopped successfully
        """
        with self._lock:
            if self._state == IntegrationState.STOPPED:
                return True

            self._state = IntegrationState.STOPPING

        # Stop update thread
        self._stopEvent.set()
        if self._updateThread and self._updateThread.is_alive():
            self._updateThread.join(timeout=timeout)

        # Stop scenario if running
        if self._scenarioRunner:
            self._scenarioRunner.stop()

        # Stop failure injector
        if self._failureInjector:
            self._failureInjector.clearAllFailures()

        # Disconnect
        if self._connection and self._connection.isConnected():
            self._connection.disconnect()

        with self._lock:
            self._state = IntegrationState.STOPPED

        logger.info("Simulator integration stopped")
        return True

    def pause(self) -> None:
        """Pause the simulation (keeps connection but stops updates)."""
        with self._lock:
            if self._state == IntegrationState.RUNNING:
                self._state = IntegrationState.PAUSED
                logger.info("Simulator integration paused")

    def resume(self) -> None:
        """Resume a paused simulation."""
        with self._lock:
            if self._state == IntegrationState.PAUSED:
                self._state = IntegrationState.RUNNING
                logger.info("Simulator integration resumed")

    def isRunning(self) -> bool:
        """Check if integration is running."""
        return self._state == IntegrationState.RUNNING

    def getState(self) -> IntegrationState:
        """Get current integration state."""
        return self._state

    # ================================================================================
    # Update Loop
    # ================================================================================

    def _updateLoop(self) -> None:
        """Main update loop for the simulator."""
        updateIntervalSec = (
            self._integrationConfig.updateIntervalMs / 1000.0
            if self._integrationConfig
            else 0.1
        )

        lastUpdateTime = time.perf_counter()

        while not self._stopEvent.is_set():
            if self._state != IntegrationState.RUNNING:
                time.sleep(0.1)
                continue

            currentTime = time.perf_counter()
            deltaSeconds = currentTime - lastUpdateTime
            lastUpdateTime = currentTime

            try:
                self._performUpdate(deltaSeconds)
            except Exception as e:
                logger.error(f"Error in simulator update: {e}")

            # Sleep for remaining interval time
            elapsed = time.perf_counter() - currentTime
            sleepTime = updateIntervalSec - elapsed
            if sleepTime > 0:
                # Sleep in small chunks for responsive stopping
                while sleepTime > 0 and not self._stopEvent.is_set():
                    time.sleep(min(sleepTime, 0.05))
                    sleepTime -= 0.05

    def _performUpdate(self, deltaSeconds: float) -> None:
        """
        Perform a single simulation update cycle.

        Args:
            deltaSeconds: Time since last update
        """
        if not self._connection:
            return

        # Update the simulator
        self._connection.update(deltaSeconds)
        self._stats.updateCount += 1

        # Get current sensor values
        values = self._getCurrentValues()

        # Feed values to connected components
        self._feedToComponents(values)

        # Trigger callback
        if self._onReadingGenerated and values:
            try:
                self._onReadingGenerated(values)
            except Exception as e:
                logger.warning(f"onReadingGenerated callback error: {e}")

    def _getCurrentValues(self) -> dict[str, float]:
        """
        Get current simulated sensor values.

        Returns:
            Dictionary of parameter names to values
        """
        if not self._connection:
            return {}

        simulator = self._connection.simulator
        values = {}

        # Key parameters for drive detection and alerts
        paramNames = [
            'RPM', 'SPEED', 'COOLANT_TEMP', 'THROTTLE_POS', 'ENGINE_LOAD',
            'MAF', 'INTAKE_TEMP', 'OIL_TEMP', 'INTAKE_PRESSURE',
            'CONTROL_MODULE_VOLTAGE', 'FUEL_LEVEL'
        ]

        for paramName in paramNames:
            value = simulator.getValue(paramName)
            if value is not None:
                values[paramName] = value

        return values

    def _feedToComponents(self, values: dict[str, float]) -> None:
        """
        Feed simulated values to connected components.

        Args:
            values: Dictionary of parameter names to values
        """
        # Feed to DriveDetector
        if self._driveDetector and 'RPM' in values:
            oldState = self._driveDetector.getDriveState()
            self._driveDetector.processValue('RPM', values['RPM'])
            if 'SPEED' in values:
                self._driveDetector.processValue('SPEED', values['SPEED'])

            newState = self._driveDetector.getDriveState()
            if oldState != newState:
                if self._onDriveStateChange:
                    try:
                        self._onDriveStateChange(oldState.value, newState.value)
                    except Exception as e:
                        logger.warning(f"onDriveStateChange callback error: {e}")

                if newState.value == 'running':
                    self._stats.drivesDetected += 1

        # Feed to AlertManager
        if self._alertManager:
            for paramName, value in values.items():
                alert = self._alertManager.checkValue(paramName, value)
                if alert:
                    self._stats.alertsTriggered += 1
                    if self._onAlertTriggered:
                        try:
                            self._onAlertTriggered(paramName, value)
                        except Exception as e:
                            logger.warning(f"onAlertTriggered callback error: {e}")

        # Update DisplayManager
        if self._displayManager:
            self._updateDisplay(values)

        self._stats.readingsGenerated += len(values)

    def _updateDisplay(self, values: dict[str, float]) -> None:
        """
        Update display with current simulated values.

        Args:
            values: Dictionary of parameter names to values
        """
        if not self._displayManager:
            return

        try:
            # Build status info
            statusDetails = {
                'rpm': values.get('RPM', 0),
                'coolantTemp': values.get('COOLANT_TEMP', 0),
                'speed': values.get('SPEED', 0),
                'throttle': values.get('THROTTLE_POS', 0),
            }

            # Check for SIM indicator in developer mode
            if hasattr(self._displayManager, 'showStatus'):
                # Add SIM indicator to status
                self._displayManager.showStatus(
                    "SIMULATION",
                    details=statusDetails
                )
        except Exception as e:
            logger.debug(f"Display update error: {e}")

    # ================================================================================
    # Scenario Management
    # ================================================================================

    def runScenario(self, scenarioName: str) -> bool:
        """
        Run a built-in drive scenario.

        Args:
            scenarioName: Name of built-in scenario (e.g., 'city_driving')

        Returns:
            True if scenario started
        """
        try:
            from .simulator import getBuiltInScenario
            scenario = getBuiltInScenario(scenarioName)
            return self._startScenario(scenario)
        except Exception as e:
            logger.error(f"Failed to load scenario '{scenarioName}': {e}")
            return False

    def runScenarioFromPath(self, scenarioPath: str) -> bool:
        """
        Run a scenario from a JSON file.

        Args:
            scenarioPath: Path to scenario JSON file

        Returns:
            True if scenario started
        """
        try:
            scenario = loadScenario(scenarioPath)
            return self._startScenario(scenario)
        except Exception as e:
            logger.error(f"Failed to load scenario from '{scenarioPath}': {e}")
            return False

    def _startScenario(self, scenario: Any) -> bool:
        """
        Start running a drive scenario.

        Args:
            scenario: DriveScenario object

        Returns:
            True if started successfully
        """
        if not self._connection:
            logger.error("Cannot run scenario - not initialized")
            return False

        # Stop existing scenario if running
        if self._scenarioRunner:
            self._scenarioRunner.stop()

        # Create runner
        self._scenarioRunner = DriveScenarioRunner(
            scenario=scenario,
            simulator=self._connection.simulator
        )

        # Register callbacks
        self._scenarioRunner.registerCallbacks(
            onPhaseStart=lambda phase: logger.info(f"Scenario phase: {phase.name}"),
            onScenarioComplete=lambda: self._onScenarioComplete()
        )

        # Start
        self._scenarioRunner.start()
        self._stats.scenariosRun += 1

        logger.info(f"Started scenario: {scenario.name}")
        return True

    def _onScenarioComplete(self) -> None:
        """Handle scenario completion."""
        logger.info("Scenario completed")

    def stopScenario(self) -> None:
        """Stop the current scenario if running."""
        if self._scenarioRunner:
            self._scenarioRunner.stop()
            logger.info("Scenario stopped")

    def isScenarioRunning(self) -> bool:
        """Check if a scenario is currently running."""
        if self._scenarioRunner:
            from .simulator import ScenarioState
            return self._scenarioRunner.getState() == ScenarioState.RUNNING
        return False

    # ================================================================================
    # Failure Injection
    # ================================================================================

    def injectFailure(
        self,
        failureType: FailureType,
        **config: Any
    ) -> bool:
        """
        Inject a failure into the simulation.

        Args:
            failureType: Type of failure to inject
            **config: Failure-specific configuration

        Returns:
            True if failure was injected
        """
        if not self._failureInjector:
            logger.warning("No failure injector configured")
            return False

        from .simulator import FailureConfig
        failureConfig = FailureConfig(**config)
        self._failureInjector.injectFailure(failureType, failureConfig)
        logger.info(f"Injected failure: {failureType.value}")
        return True

    def clearFailure(self, failureType: FailureType) -> bool:
        """
        Clear a specific failure.

        Args:
            failureType: Type of failure to clear

        Returns:
            True if failure was cleared
        """
        if not self._failureInjector:
            return False

        self._failureInjector.clearFailure(failureType)
        logger.info(f"Cleared failure: {failureType.value}")
        return True

    def clearAllFailures(self) -> None:
        """Clear all active failures."""
        if self._failureInjector:
            self._failureInjector.clearAllFailures()
            logger.info("Cleared all failures")

    def scheduleFailure(
        self,
        failureType: FailureType,
        startSeconds: float,
        durationSeconds: float,
        **config: Any
    ) -> bool:
        """
        Schedule a failure to occur after a delay.

        Args:
            failureType: Type of failure
            startSeconds: Seconds until failure starts
            durationSeconds: How long failure lasts
            **config: Failure-specific configuration

        Returns:
            True if scheduled successfully
        """
        if not self._failureInjector:
            return False

        from .simulator import FailureConfig
        failureConfig = FailureConfig(**config)
        self._failureInjector.scheduleFailure(
            failureType, failureConfig, startSeconds, durationSeconds
        )
        logger.info(
            f"Scheduled failure: {failureType.value} in {startSeconds}s "
            f"for {durationSeconds}s"
        )
        return True

    # ================================================================================
    # Callbacks
    # ================================================================================

    def registerCallbacks(
        self,
        onReadingGenerated: Callable[[dict[str, float]], None] | None = None,
        onAlertTriggered: Callable[[str, float], None] | None = None,
        onDriveStateChange: Callable[[str, str], None] | None = None
    ) -> None:
        """
        Register callbacks for integration events.

        Args:
            onReadingGenerated: Called each update cycle with current values
            onAlertTriggered: Called when an alert is triggered (paramName, value)
            onDriveStateChange: Called when drive state changes (oldState, newState)
        """
        self._onReadingGenerated = onReadingGenerated
        self._onAlertTriggered = onAlertTriggered
        self._onDriveStateChange = onDriveStateChange

    # ================================================================================
    # Statistics
    # ================================================================================

    def getStats(self) -> IntegrationStats:
        """Get integration statistics."""
        return IntegrationStats(
            startTime=self._stats.startTime,
            connectionTime=self._stats.connectionTime,
            updateCount=self._stats.updateCount,
            readingsGenerated=self._stats.readingsGenerated,
            alertsTriggered=self._stats.alertsTriggered,
            drivesDetected=self._stats.drivesDetected,
            scenariosRun=self._stats.scenariosRun,
        )

    def resetStats(self) -> None:
        """Reset statistics."""
        self._stats = IntegrationStats()


# ================================================================================
# Helper Functions
# ================================================================================



def isSimulationModeActive(config: dict[str, Any], simulateFlag: bool = False) -> bool:
    """
    Check if simulation mode should be active.

    Args:
        config: Configuration dictionary
        simulateFlag: True if --simulate CLI flag was passed

    Returns:
        True if simulation mode should be used
    """
    return isSimulatorEnabled(config, simulateFlag)


def createSimulatorIntegrationFromConfig(
    config: dict[str, Any],
    database: Any | None = None,
    simulateFlag: bool = False
) -> SimulatorIntegration | None:
    """
    Create and initialize a SimulatorIntegration from configuration.

    Returns None if simulation mode is not enabled.

    Args:
        config: Configuration dictionary
        database: Optional database instance
        simulateFlag: True if --simulate CLI flag was passed

    Returns:
        Initialized SimulatorIntegration or None
    """
    if not isSimulatorEnabled(config, simulateFlag):
        return None

    integration = SimulatorIntegration(config, database)
    integration.initialize(simulateFlag)
    return integration
