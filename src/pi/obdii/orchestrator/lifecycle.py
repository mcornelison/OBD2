################################################################################
# File Name: lifecycle.py
# Purpose/Description: Component initialization and shutdown lifecycle mixin
# Author: Ralph Agent
# Creation Date: 2026-04-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-14    | Ralph Agent  | Sweep 5 Task 2: extracted from orchestrator.py
#               |              | (init and shutdown order preserved per TD-003)
# 2026-04-20    | Ralph (Rex)  | US-207 TD-015: log hardware-import failures
#               |              | at INFO (not silent) + promote skip messages
#               |              | in _initializeHardwareManager from debug->info.
# ================================================================================
################################################################################

"""
Component lifecycle mixin for ApplicationOrchestrator.

Owns the 12-step initialization sequence and the 12-step reverse shutdown
sequence, plus the component-stop-with-timeout helper. Init order must match
TD-003 dependency chain.

This module is deliberately kept as a single file even though it exceeds the
300-line soft cap: each ``_initialize*`` method has a paired ``_shutdown*``
method, and the reverse-order shutdown depends on the ``COMPONENT_INIT_ORDER``
list at module scope. Splitting would scatter pair members across files,
making it harder to audit that every component has matching setup/teardown.
"""

import logging
import threading
from typing import Any

from .types import EXIT_CODE_FORCED, ComponentInitializationError, ShutdownState

# Unified logger name matches the original monolith module so existing tests
# that filter caplog by logger name continue to work unchanged.
logger = logging.getLogger("pi.obdii.orchestrator")

# Import hardware module functions with graceful fallback for non-Pi systems.
# TD-015: the ImportError was previously swallowed silently, masking a
# Pi-side failure where HARDWARE_AVAILABLE resolved False under main.py's
# import chain but True under direct-module load. Log the concrete
# exception at INFO so the skip reason is visible in journals.
try:
    from pi.hardware.hardware_manager import HardwareManager, createHardwareManagerFromConfig
    from pi.hardware.platform_utils import isRaspberryPi
    HARDWARE_AVAILABLE = True
except ImportError as _hardwareImportError:
    HARDWARE_AVAILABLE = False
    logger.info(
        "Hardware module import skipped: %s: %s",
        type(_hardwareImportError).__name__,
        _hardwareImportError,
    )

    def isRaspberryPi() -> bool:
        """Fallback function when hardware module not available."""
        return False

    HardwareManager = None  # type: ignore

    def createHardwareManagerFromConfig(config: Any) -> None:
        """Fallback function when hardware module not available."""
        return None


# ================================================================================
# Component Order Constants
# ================================================================================

# Dependency chain — do NOT reorder without reading TD-003
COMPONENT_INIT_ORDER = [
    "Database",
    "ProfileManager",
    "Connection",
    "VinDecoder",
    "DisplayManager",
    "HardwareManager",
    "StatisticsEngine",
    "DriveDetector",
    "AlertManager",
    "DataLogger",
    "ProfileSwitcher",
    "BackupManager",
]

# Shutdown is the reverse of init — components depending on others come down first
COMPONENT_SHUTDOWN_ORDER = list(reversed(COMPONENT_INIT_ORDER))


class LifecycleMixin:
    """
    Mixin providing component initialization and shutdown.

    Assumes the composing class has all the component reference attributes
    (_database, _connection, etc.) and the helper attributes
    (_config, _simulate, _shutdownState, _shutdownTimeout, _exitCode).

    The _initializeBackupManager and _shutdownBackupManager methods live in
    BackupCoordinatorMixin — this mixin calls them via method-resolution-order.
    """

    _config: dict[str, Any]
    _simulate: bool
    _database: Any | None
    _profileManager: Any | None
    _connection: Any | None
    _vinDecoder: Any | None
    _displayManager: Any | None
    _hardwareManager: Any | None
    _statisticsEngine: Any | None
    _driveDetector: Any | None
    _alertManager: Any | None
    _dataLogger: Any | None
    _profileSwitcher: Any | None
    _vehicleVin: str | None
    _shutdownState: ShutdownState
    _shutdownTimeout: float
    _exitCode: int

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
        self._initializeDtcLogger()
        self._initializeSummaryRecorder()
        self._initializeBackupManager()  # type: ignore[attr-defined]

    def _initializeDatabase(self) -> None:
        """Initialize the database component."""
        from ..database import createDatabaseFromConfig
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
            from pi.profile import createProfileManagerFromConfig
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
                from ..simulator.simulated_connection import createSimulatedConnectionFromConfig
                self._connection = createSimulatedConnectionFromConfig(
                    self._config, self._database
                )
            else:
                from ..obd_connection import createConnectionFromConfig
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
            from ..vehicle import createVinDecoderFromConfig
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
            from pi.display import createDisplayManagerFromConfig
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

    def _createHeadlessDisplayFallback(self) -> Any | None:
        """
        Create a headless display manager as fallback when hardware unavailable.

        Returns:
            Initialized headless DisplayManager or None if unavailable
        """
        try:
            from pi.display import createDisplayManagerFromConfig
            headlessConfig = dict(self._config)
            headlessConfig['pi'] = dict(self._config.get('pi', {}))
            headlessConfig['pi']['display'] = {
                **self._config.get('pi', {}).get('display', {}),
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
        # TD-015: promoted debug->info so skip reason is visible in normal
        # journal output (was hiding a Pi-side main.py import-chain bug).
        if not HARDWARE_AVAILABLE:
            logger.info("Hardware module not available, skipping HardwareManager")
            return

        # Check if running on Raspberry Pi
        if not isRaspberryPi():
            logger.info("Not running on Raspberry Pi, skipping HardwareManager")
            return

        # Check if hardware is enabled in config
        hardwareEnabled = self._config.get('hardware', {}).get('enabled', True)
        if not hardwareEnabled:
            logger.info("HardwareManager disabled by configuration")
            return

        logger.info("Starting hardwareManager...")
        try:
            batteryHealthRecorder = self._createBatteryHealthRecorder()
            self._hardwareManager = createHardwareManagerFromConfig(
                self._config,
                batteryHealthRecorder=batteryHealthRecorder,
            )
            self._wirePowerDownOrchestratorCallbacks()
            logger.info("HardwareManager initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize hardwareManager: {e}")
            self._hardwareManager = None

    def _createBatteryHealthRecorder(self) -> Any | None:
        """US-216: build a BatteryHealthRecorder when the DB is available.

        The recorder is consumed by the PowerDownOrchestrator inside
        HardwareManager; constructing it here keeps the DB dependency in
        lifecycle.py (where the database is already initialized) rather
        than forcing hardware_manager to know about ObdDatabase.
        """
        if self._database is None:
            logger.info(
                "BatteryHealthRecorder skipped: database not initialized"
            )
            return None
        try:
            from pi.power.battery_health import BatteryHealthRecorder
            return BatteryHealthRecorder(database=self._database)
        except Exception as e:
            logger.warning(
                "BatteryHealthRecorder init failed (orchestrator ladder "
                "will be disabled): %s", e,
            )
            return None

    def _wirePowerDownOrchestratorCallbacks(self) -> None:
        """US-216: attach runtime stage-behavior callbacks if the orchestrator
        is live.

        The orchestrator is constructed inside hardware_manager with no
        stage callbacks. Here we reach in and bind concrete behaviors that
        are safe from this layer: log the transition (+ forward to journald
        for the CIO drill), and on IMMINENT optionally close any active
        drive via the drive detector so drive_summary analytics flushes
        before poweroff. The heavier integrations (sync force-push, BT
        close, poll-tier stop, DB no_new_drives flag) are deferred to
        Sprint 17 per TD-034 so the systemd stop cascade still closes
        them cleanly on TRIGGER.
        """
        if self._hardwareManager is None:
            return
        orch = getattr(self._hardwareManager, 'powerDownOrchestrator', None)
        if orch is None:
            return

        def onWarning() -> None:
            logger.warning(
                "PowerDownOrchestrator WARNING stage fired -- "
                "battery_health_log row opened; operator action: review "
                "drain cause, no new drives will be started."
            )

        def onImminent() -> None:
            logger.warning(
                "PowerDownOrchestrator IMMINENT stage fired -- "
                "closing any active drive before TRIGGER."
            )
            try:
                if self._driveDetector is not None:
                    forceFn = getattr(self._driveDetector, 'forceKeyOff', None)
                    if callable(forceFn):
                        forceFn(reason='power_imminent')
            except Exception as e:  # noqa: BLE001
                logger.error("IMMINENT forceKeyOff failed: %s", e)

        def onAcRestore() -> None:
            logger.info(
                "PowerDownOrchestrator AC restored -- drain event closed "
                "as recovered; resuming normal operation."
            )

        # Reach in and bind. The orchestrator exposes these as attributes
        # on construction; updating them post-init is safe because tick()
        # only reads them through _invokeCallback.
        orch._onWarning = onWarning  # noqa: SLF001
        orch._onImminent = onImminent  # noqa: SLF001
        orch._onAcRestore = onAcRestore  # noqa: SLF001
        logger.info("PowerDownOrchestrator stage-behavior callbacks wired")

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
            from ..drive import createDriveDetectorFromConfig
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
            from pi.alert import createAlertManagerFromConfig
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
            from ..statistics_engine import createStatisticsEngineFromConfig
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
            from ..data import createRealtimeLoggerFromConfig
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
            from pi.profile import createProfileSwitcherFromConfig
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

    def _initializeDtcLogger(self) -> None:
        """Initialize DtcLogger + MIL rising-edge detector (US-204).

        Wired only when ``pi.dtc.enabled`` is true (default: true on the
        live-OBD path).  Replay / simulator paths can opt out via
        config.json so the orchestrator does not attempt Mode 03 against
        a synthesized connection.

        DtcLogger needs the database (always present at this point) but
        only references the connection at call-time, so a missing
        connection here is non-fatal -- the dispatcher in event_router
        rechecks before each call.
        """
        dtcConfig = self._config.get('pi', {}).get('dtc', {})
        if dtcConfig.get('enabled', True) is False:
            logger.info("DtcLogger disabled via pi.dtc.enabled=false")
            return
        if self._database is None:
            logger.info("DtcLogger skipped -- no database available")
            return
        try:
            from ..dtc_client import DtcClient
            from ..dtc_logger import DtcLogger
            from ..mil_edge import MilRisingEdgeDetector

            self._dtcLogger = DtcLogger(
                database=self._database,
                dtcClient=DtcClient(),
            )
            self._milEdgeDetector = MilRisingEdgeDetector()
            logger.info("DtcLogger + MIL edge detector started successfully")
        except Exception as e:  # noqa: BLE001 -- DTC capture must not fail boot
            logger.warning(
                "DtcLogger initialization skipped: %s (type=%s)",
                e, type(e).__name__,
            )
            self._dtcLogger = None
            self._milEdgeDetector = None

    def _initializeSummaryRecorder(self) -> None:
        """Initialize SummaryRecorder + wire into DriveDetector (US-206).

        Opt-out via ``pi.driveSummary.enabled=false``; the capture
        path is non-fatal (a missing recorder just skips
        drive_summary rows).  Requires the database (for the upsert)
        and wires the data logger as the reading-snapshot source so
        no new ECU polls are triggered.
        """
        summaryConfig = self._config.get('pi', {}).get('driveSummary', {})
        if summaryConfig.get('enabled', True) is False:
            logger.info("SummaryRecorder disabled via pi.driveSummary.enabled=false")
            return
        if self._database is None:
            logger.info("SummaryRecorder skipped -- no database available")
            return
        if self._driveDetector is None:
            logger.info("SummaryRecorder skipped -- no drive detector available")
            return
        try:
            from ..drive_summary import SummaryRecorder
            self._summaryRecorder = SummaryRecorder(database=self._database)
            self._driveDetector.setSummaryRecorder(self._summaryRecorder)
            if self._dataLogger is not None and hasattr(
                self._dataLogger, 'getLatestReadings'
            ):
                self._driveDetector.setReadingSnapshotSource(self._dataLogger)
            logger.info("SummaryRecorder wired to driveDetector (US-206)")
        except Exception as e:  # noqa: BLE001 -- summary capture must not fail boot
            logger.warning(
                "SummaryRecorder initialization skipped: %s (type=%s)",
                e, type(e).__name__,
            )
            self._summaryRecorder = None

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
        stopError: Exception | None = None

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
        self._shutdownBackupManager()  # type: ignore[attr-defined]
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


__all__ = [
    'LifecycleMixin',
    'COMPONENT_INIT_ORDER',
    'COMPONENT_SHUTDOWN_ORDER',
    'HARDWARE_AVAILABLE',
]
