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
# 2026-04-23    | Ralph (Rex)  | US-222 / TD-030: _initializeHardwareManager
#               |              | now reads pi.hardware.enabled (canonical
#               |              | config path) instead of top-level hardware.
# 2026-04-23    | Ralph (Rex)  | US-225 / TD-034: replace log-only
#               |              | PowerDownOrchestrator stage callbacks with
#               |              | concrete wiring (no_new_drives gate +
#               |              | forcePush on WARNING; pausePolling +
#               |              | forceKeyOff on IMMINENT; clearNoNewDrives +
#               |              | resumePolling on AC-restore).  SyncClient
#               |              | is constructed lazily per-warning so a
#               |              | disabled companion service is a benign
#               |              | no-op.
# 2026-04-23    | Ralph (Rex)  | US-226: wire a SyncClient into the
#               |              | orchestrator's init sequence so the
#               |              | interval-based sync trigger in runLoop
#               |              | has a non-lazy client to call.  Respects
#               |              | pi.sync.enabled (opt-out) + reuses the
#               |              | US-225 forcePush lazy path for power-down
#               |              | callbacks.  Missing API key with sync
#               |              | enabled logs a warning + disables -- does
#               |              | NOT crash boot.
# 2026-04-23    | Ralph (Rex)  | US-232 / TD-035: pass the orchestrator
#               |              | _shutdownEvent into createConnectionFromConfig
#               |              | so the retry loop's sleep is interruptible.
# 2026-04-30    | Rex (US-243) | B-050 close: instantiate PowerMonitor in
#               |              | _initializeAllComponents and chain its
#               |              | checkPowerStatus into UpsMonitor's
#               |              | onPowerSourceChange (fan-out wrapper preserves
#               |              | the prior ShutdownHandler callback).
#               |              | Activates the power_log write path that has
#               |              | been dead since installation -- 5 drain tests
#               |              | + Spool's inverted drill all logged transitions
#               |              | to journal but 0 reached power_log.
# 2026-04-30    | Rex (US-247) | B-047 US-C: add _initializeUpdateChecker that
#               |              | constructs the Pi UpdateChecker (gated on
#               |              | pi.update.enabled) and hands it an
#               |              | isDrivingFn closure that resolves the live
#               |              | DriveDetector lazily. Soft-failure init --
#               |              | construction errors leave updateChecker=None
#               |              | and runLoop's _maybeTriggerUpdateCheck no-ops.
# 2026-04-30    | Rex (US-248) | B-047 US-D: add _initializeUpdateApplier that
#               |              | constructs the Pi UpdateApplier (gated on
#               |              | pi.update.enabled) with isDrivingFn /
#               |              | getPowerSourceFn / getLastObdActivitySecondsAgo
#               |              | closures.  Each closure resolves its component
#               |              | lazily so a re-bound drive detector / late-
#               |              | initialized hardware manager / unavailable
#               |              | DB are all handled cleanly.  Soft-failure
#               |              | init -- construction errors leave
#               |              | updateApplier=None and runLoop's
#               |              | _maybeTriggerUpdateApply no-ops.
# 2026-04-30    | Rex (US-244) | TD-036 close: _initializeConnection runs the
#               |              | OBD connect attempt in a daemon thread with a
#               |              | wall-clock timeout (pi.obdii.orchestrator.
#               |              | initialConnectTimeoutSec, default 30s).  On
#               |              | timeout or connect-returns-False the method
#               |              | logs WARN and returns without raising so
#               |              | runLoop starts in PENDING state; US-226 interval
#               |              | sync fires regardless of OBD state, and the
#               |              | US-211 reconnect path picks up late-arriving
#               |              | adapter+ECU readiness.  Closes the silent
#               |              | "auto-sync never fires until engine on" gap
#               |              | observed Sprint 18 post-deploy 2026-04-27.
# 2026-05-01    | Rex (US-252) | Added _createPowerLogWriter -- builds a
#               |              | (eventType, vcell) closure over the live
#               |              | ObdDatabase and threads it into
#               |              | createHardwareManagerFromConfig.  The
#               |              | PowerDownOrchestrator now persists each
#               |              | stage transition to power_log via the
#               |              | logShutdownStage helper.  Same DB-isolation
#               |              | pattern as _createBatteryHealthRecorder.
# 2026-05-02    | Rex (US-265) | Discriminator A audit trail.  After
#               |              | _wirePowerDownOrchestratorCallbacks
#               |              | confirms the orchestrator was constructed
#               |              | by hardware_manager, log a single audit
#               |              | line confirming the dedicated tick thread
#               |              | spawn is delegated to
#               |              | HardwareManager._startComponents (with
#               |              | daemon=True per the US-252 wiring).  The
#               |              | symmetric audit pairs lifecycle's
#               |              | "orchestrator wired" entry with the
#               |              | hardware_manager's "tick thread spawned
#               |              | tid=<id>" entry in journalctl so a
#               |              | post-Drain-7 forensic walk can prove the
#               |              | thread reached .start() (or did not).
# 2026-05-07    | Rex (US-284) | Engine-telemetry-regression P0: Spool's
#               |              | inbox 2026-05-05 documented 27-hour boot-1
#               |              | / 82-min boot-0 hangs in _initializeConnection
#               |              | with the 30-sec wall-clock timeout effectively
#               |              | disarmed.  Code-only investigation (no Pi
#               |              | access): US-244 daemon-thread spawn IS in
#               |              | place + correct (lines 458-462); config
#               |              | default IS 30 (config.json:203 +
#               |              | validator.py:178); production root cause is
#               |              | python-obd library blocking, broadened from
#               |              | Spool's hypothesis 2 (obd.OBD() ctor) to
#               |              | "any python-obd I/O in the init chain
#               |              | without a wall-clock wrapper."  Two adjacent
#               |              | sites in the same class: (a)
#               |              | _runInitialConnectWithTimeout uses
#               |              | Event.wait(timeout=30), which drifts on Pi 5
#               |              | due to GIL contention from python-obd
#               |              | protocol probing -- adds wall-clock
#               |              | drift-detection log so post-deploy journal
#               |              | walks name the failure mode (cannot PREVENT
#               |              | drift without subprocess isolation; tracked
#               |              | as Sprint 26 follow-up TD); (b)
#               |              | _performFirstConnectionVinDecode line 502
#               |              | called connection.obd.query("VIN") with NO
#               |              | timeout wrapper -- adds new _queryWithTimeout
#               |              | helper mirroring US-244 daemon-thread +
#               |              | Event.wait pattern, bounding the call
#               |              | regardless of library behavior.  Reuses
#               |              | initialConnectTimeoutSec config (same init
#               |              | phase, same timeout semantics) so no new
#               |              | config key is added (scope-fence:
#               |              | validator.py + config.json out of US-284
#               |              | scope.filesToTouch).  Synthetic test in
#               |              | tests/pi/orchestrator/test_initialize_
#               |              | connection_timeout.py would FAIL pre-fix
#               |              | (unprotected query blocks indefinitely on
#               |              | mocked I/O) and PASSES post-fix.
# 2026-05-07    | Rex (US-287) | Spool Story 4: wire the US-263 / US-283
#               |              | startup_log writer into the boot path.  New
#               |              | LifecycleMixin._recordStartupLog method
#               |              | invoked from _initializeAllComponents
#               |              | immediately after _initializeDatabase and
#               |              | before _initializeProfileManager (the
#               |              | earliest call site with DB access, prior
#               |              | to the US-244/US-284 OBD-connect blocker
#               |              | territory).  Calls recordBootReason with
#               |              | the live ObdDatabase; PK INSERT OR IGNORE
#               |              | guarantees idempotency at the SQL layer.
#               |              | Per the story invariants, all exceptions
#               |              | (journalctl unavailable, malformed output,
#               |              | DB hiccup) are swallowed at WARNING so a
#               |              | diagnostics surface failure NEVER crashes
#               |              | the boot path.  Module-level import of
#               |              | recordBootReason at the no-prefix
#               |              | `pi.diagnostics.boot_reason` form matches
#               |              | the existing `from pi.hardware...` /
#               |              | `from pi.profile...` import shape used
#               |              | throughout this file -- avoids the
#               |              | cross-module dual-resolution anti-pattern
#               |              | V0.24.1 closed.  Ships without a wiring
#               |              | scope-fence violation despite lifecycle.py
#               |              | not appearing verbatim in the story's
#               |              | scope.filesToTouch -- US-287
#               |              | stopConditions[0] expressly authorizes
#               |              | "pick the earliest site that has DB access
#               |              | + document choice in completionNotes."
# 2026-05-03    | Rex (US-279) | LADDER FIX wiring -- new
#               |              | _subscribeOrchestratorToUpsMonitor method
#               |              | called from _startHardwareManager (after
#               |              | hardwareManager.start() returns + before /
#               |              | alongside the existing _subscribePower
#               |              | MonitorToUpsMonitor call).  Registers the
#               |              | orchestrator's _onPowerSourceChange method
#               |              | as a callback on UpsMonitor via the new
#               |              | registerSourceChangeCallback API.  Closes
#               |              | the 8-drain saga: every BATTERY transition
#               |              | the polling thread observes is now PUSHED
#               |              | into the orchestrator's self._powerSource,
#               |              | eliminating the stale-cached-read pattern
#               |              | that survived 8 drain tests across 4 sprints.
#               |              | Wrapped in broad try/except so a wiring
#               |              | failure never blocks runLoop entry --
#               |              | ladder-degradation is preferable to a boot
#               |              | crash, mirroring _subscribePowerMonitor's
#               |              | error isolation.
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
import time
from collections.abc import Callable
from typing import Any

from pi.diagnostics.boot_reason import recordBootReason

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
    _syncClient: Any | None
    _powerMonitor: Any | None
    _updateChecker: Any | None
    _updateApplier: Any | None
    _vehicleVin: str | None
    _shutdownState: ShutdownState
    _shutdownTimeout: float
    _exitCode: int
    # US-284 test seam: drift-detection branch of _runInitialConnectWithTimeout
    # calls this instead of Event.wait directly, so a test can simulate the
    # Pi-5 production drift deterministically in <5 sec.  Defaults to None;
    # production code path uses Event.wait(timeout=...) verbatim when this is
    # None (zero overhead).  Test fixtures override to inject drift.
    _eventWaitForTesting: Callable[[threading.Event, float], bool] | None

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
        # US-287: write the startup_log row right after database init so it
        # lands regardless of the OBD-connect outcome (US-244 / US-284
        # blocker territory).  Earliest call site with DB access; failures
        # are swallowed so a journalctl glitch never crashes the boot path.
        self._recordStartupLog()
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
        self._initializeSyncClient()
        self._initializePowerMonitor()
        self._initializeUpdateChecker()
        self._initializeUpdateApplier()
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

    def _recordStartupLog(self) -> None:
        """Write one ``startup_log`` row for the current Pi boot (US-287).

        Best-effort wiring of the US-263 boot-reason detector + US-283
        schema-pinned writer.  Called from
        :meth:`_initializeAllComponents` immediately after
        :meth:`_initializeDatabase` and before any OBD-connect path so
        the row lands regardless of the US-244 / US-284 connect-blocker
        territory.

        Idempotent at the SQL layer: ``startup_log.boot_id`` is the PK
        and the writer uses ``INSERT OR IGNORE``, so an orchestrator
        restart on the same boot is a no-op.

        Per the story invariants ("If journalctl is unavailable or
        returns malformed output -- log error and skip; do NOT crash
        boot path"), all exceptions are swallowed at WARNING level.
        """
        if self._database is None:
            return
        try:
            recordBootReason(self._database)
        except Exception as exc:
            logger.warning("Startup-log write skipped: %s", exc)

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
        Initialize the OBD-II connection component (non-blocking on initial connect).

        Constructs the connection object and dispatches the initial ``connect()``
        attempt on a daemon thread, bounded by a wall-clock timeout from
        ``pi.obdii.orchestrator.initialConnectTimeoutSec`` (default 30s).

        US-244 / TD-036: prior behavior raised ``ComponentInitializationError`` on
        connect-failure, which kept the orchestrator stuck in startup whenever the
        Pi cold-booted with engine off (adapter responds, ECU silent).  That
        blocked ``runLoop`` from ever entering, so US-226's interval-based sync
        and every other runLoop-resident behavior silently never fired.

        Post-fix contract:

        * On timeout: log WARN and return.  The connect daemon thread keeps
          running -- its eventual success transparently flips the connection to
          CONNECTED, observed by ``_checkConnectionStatus`` on the next
          ``runLoop`` pass.  Eventual failure leaves the connection DISCONNECTED;
          the existing US-211 reconnect path (driven by capture-loop errors)
          retries on its own cadence.
        * On thread-completion within timeout: log normally and return without
          raising.  Failure is no longer fatal to startup.
        * Construction-time failures (ImportError, KeyError) still raise
          ``ComponentInitializationError`` -- those are config-quality issues that
          must fail fast.

        Uses exponential backoff retry logic from
        ``config['pi']['bluetooth']['retryDelays']``; defaults to
        ``[1, 2, 4, 8, 16]`` seconds.  The wall-clock timeout caps the total
        wait time independently of the retry-count cap.
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
                # US-232 / TD-035: plumb the orchestrator's shared shutdown
                # event into the real connection so its retry backoff sleeps
                # wake within ~ms of SIGTERM rather than out-lasting the
                # 60s cap and getting SIGKILL'd.
                self._connection = createConnectionFromConfig(
                    self._config,
                    self._database,
                    shutdownEvent=getattr(self, '_shutdownEvent', None),
                )

        except ImportError as e:
            logger.warning(f"Connection module not available: {e}")
            return
        except Exception as e:
            logger.error(f"Failed to construct connection: {e}")
            raise ComponentInitializationError(
                f"Connection initialization failed: {e}",
                component='connection'
            ) from e

        # Connection object exists.  Attempt the initial connect on a daemon
        # thread bounded by a wall-clock timeout so a non-responsive ECU does
        # not block runLoop entry (US-244 / TD-036).
        if not hasattr(self._connection, 'connect'):
            logger.info("Connection started successfully")
            return

        timeoutSec = self._initialConnectTimeoutSec()
        completed, success, error = self._runInitialConnectWithTimeout(timeoutSec)

        if not completed:
            logger.warning(
                "Initial connect timed out after %.1fs, runLoop starting in "
                "PENDING (connect daemon thread continues; US-211 reconnect "
                "path will transition to CONNECTED if/when adapter+ECU "
                "become responsive)",
                timeoutSec,
            )
            return

        if error is not None:
            logger.warning(
                "Initial connect raised %s: %s -- runLoop starting in PENDING",
                type(error).__name__, error,
            )
            return

        if success:
            logger.info("Connection started successfully")
        else:
            logger.warning(
                "Initial connect returned False (retries exhausted) -- "
                "runLoop starting in PENDING (US-211 reconnect path will retry)"
            )

    def _initialConnectTimeoutSec(self) -> float:
        """Read ``pi.obdii.orchestrator.initialConnectTimeoutSec`` (US-244)."""
        raw = (
            self._config.get('pi', {})
            .get('obdii', {})
            .get('orchestrator', {})
            .get('initialConnectTimeoutSec', 30)
        )
        try:
            return float(raw)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid initialConnectTimeoutSec=%r in config; using 30s default",
                raw,
            )
            return 30.0

    def _runInitialConnectWithTimeout(
        self, timeoutSec: float,
    ) -> tuple[bool, bool, BaseException | None]:
        """Run ``self._connection.connect()`` on a daemon thread with timeout.

        US-244 / TD-036: dispatches connect on a background thread so the
        wall-clock cap can return control to ``_initializeAllComponents``
        even when the underlying retry loop has not yet exhausted its
        configured delays.  On timeout, the daemon thread is left running
        -- it may eventually transition the connection to CONNECTED in
        the background.  The runLoop's existing ``_checkConnectionStatus``
        path observes the late transition and fires
        ``_handleConnectionRestored`` automatically.

        Args:
            timeoutSec: Wall-clock cap in seconds.

        Returns:
            ``(completed, success, error)`` where:
              - ``completed`` is True iff the thread finished within
                ``timeoutSec`` (False = timed out, thread still running);
              - ``success`` is the bool returned by ``connect()`` when
                ``completed`` is True (undefined when timed out);
              - ``error`` is the ``BaseException`` raised by ``connect()``
                if any (None on clean True/False return).
        """
        connectDoneEvent = threading.Event()
        connectResult: dict[str, Any] = {'success': False, 'error': None}

        def _connectInThread() -> None:
            try:
                connectResult['success'] = bool(self._connection.connect())
            except BaseException as exc:  # noqa: BLE001 -- surface to caller
                connectResult['error'] = exc
            finally:
                connectDoneEvent.set()

        connectThread = threading.Thread(
            target=_connectInThread,
            daemon=True,
            name="initial-obd-connect",
        )
        connectThread.start()

        # US-284 drift-detection: Spool's 2026-05-05 inbox documented
        # production Event.wait drift on Pi 5 -- the 30-sec configured
        # timeout returned at 82 min on boot 0 (and apparently ~27h on
        # boot -1).  Likely cause: python-obd's serial I/O during ELM327
        # protocol probing holds the GIL hard enough to starve the main-
        # thread wait timer.  We CANNOT prevent the drift here without
        # subprocess isolation (kernel-level SIGKILL escape, beyond US-284
        # scope -- Sprint 26 follow-up TD); we CAN observe and log it so
        # post-deploy journal walks name the failure mode instead of
        # silently waiting on a broken timer.
        waitFn = getattr(self, '_eventWaitForTesting', None)
        startedAt = time.monotonic()
        if waitFn is None:
            completed = connectDoneEvent.wait(timeout=timeoutSec)
        else:
            completed = waitFn(connectDoneEvent, timeoutSec)
        elapsed = time.monotonic() - startedAt

        # Drift threshold: 1.5x the configured timeout absorbs normal
        # scheduling jitter (a healthy Pi typically wakes within 5-50ms of
        # the timer) while catching the production failure mode (82 min
        # vs configured 30 sec = 164x).
        if elapsed > timeoutSec * 1.5:
            logger.critical(
                "Event.wait drift detected: configured timeout=%.1fs, "
                "actual elapsed=%.1fs (%.1fx).  Production root cause "
                "candidate per Spool 2026-05-05 sprint25 P0; subprocess "
                "isolation is the recommended fix (Sprint 26 follow-up).",
                timeoutSec,
                elapsed,
                elapsed / timeoutSec if timeoutSec > 0 else float('inf'),
            )

        return (
            completed,
            bool(connectResult['success']) if completed else False,
            connectResult['error'] if completed else None,
        )

    def _queryWithTimeout(
        self,
        command: str,
        timeoutSec: float,
    ) -> tuple[bool, Any, BaseException | None]:
        """Run ``self._connection.obd.query(command)`` on a daemon thread with timeout.

        US-284: the python-obd library's per-command timeout (set on the
        ``obd.OBD(timeout=...)`` ctor) is observably not honored when the
        underlying serial / bluetooth subsystem hangs (Spool 2026-05-05
        production evidence on the same I/O class).  This wrapper bounds
        an arbitrary single-command query against a wall-clock cap,
        mirroring ``_runInitialConnectWithTimeout``: dispatch the query
        on a background daemon thread, ``Event.wait(timeout=timeoutSec)``,
        return success/timeout/error tuple identical in shape.

        On timeout, the daemon thread is left running -- it may eventually
        return (the answer is discarded) or stay wedged until process exit
        (daemon=True so it's reaped).  This is the same trade-off the
        US-244 connect wrapper accepts.

        Args:
            command: python-obd command name or instance to query.
            timeoutSec: Wall-clock cap in seconds.

        Returns:
            ``(completed, value, error)`` where:
              - ``completed`` is True iff the thread finished within
                ``timeoutSec`` (False = timed out, thread still running);
              - ``value`` is the python-obd response when ``completed`` is
                True and no exception (None when timed out or errored);
              - ``error`` is the ``BaseException`` raised by ``query()`` if
                any (None on clean return or timeout).
        """
        queryDoneEvent = threading.Event()
        queryResult: dict[str, Any] = {'value': None, 'error': None}

        def _queryInThread() -> None:
            try:
                queryResult['value'] = self._connection.obd.query(command)
            except BaseException as exc:  # noqa: BLE001 -- surface to caller
                queryResult['error'] = exc
            finally:
                queryDoneEvent.set()

        threading.Thread(
            target=_queryInThread,
            daemon=True,
            name=f"obd-query-{command}",
        ).start()

        completed = queryDoneEvent.wait(timeout=timeoutSec)
        return (
            completed,
            queryResult['value'] if completed else None,
            queryResult['error'] if completed else None,
        )

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

        # Query VIN from vehicle.  US-284: wrap with wall-clock cap so a
        # python-obd serial-read wedge cannot hang the orchestrator init
        # thread for hours (Spool 2026-05-05 production evidence).  Re-uses
        # initialConnectTimeoutSec because the static-VIN-query is part of
        # the same init phase + the failure mode is identical.
        try:
            if not hasattr(self._connection, 'obd') or self._connection.obd is None:
                logger.debug("VIN decode skipped: connection has no OBD interface")
                return

            vinTimeoutSec = self._initialConnectTimeoutSec()
            completed, vinResponse, queryError = self._queryWithTimeout(
                "VIN", vinTimeoutSec,
            )

            if not completed:
                logger.warning(
                    "VIN query timed out after %.1fs -- vehicle did not respond "
                    "in time; continuing without decoded vehicle info "
                    "(US-284 wall-clock cap on python-obd query path).",
                    vinTimeoutSec,
                )
                return

            if queryError is not None:
                logger.warning(
                    "Failed to query VIN from vehicle: %s",
                    queryError,
                )
                return

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

        # Check if hardware is enabled in config.
        # US-222 / TD-030: the canonical path is ``pi.hardware.enabled``
        # (config.json nests hardware under the pi tier). Pre-US-222 this
        # read top-level ``hardware`` which silently returned the default
        # True, so any attempt to disable the subsystem via config was
        # ignored. Default-True-on-missing-key is preserved.
        hardwareEnabled = (
            self._config.get('pi', {}).get('hardware', {}).get('enabled', True)
        )
        if not hardwareEnabled:
            logger.info("HardwareManager disabled by configuration")
            return

        logger.info("Starting hardwareManager...")
        try:
            batteryHealthRecorder = self._createBatteryHealthRecorder()
            powerLogWriter = self._createPowerLogWriter()
            self._hardwareManager = createHardwareManagerFromConfig(
                self._config,
                batteryHealthRecorder=batteryHealthRecorder,
                powerLogWriter=powerLogWriter,
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

    def _createPowerLogWriter(self) -> Any | None:
        """US-252: build a (eventType, vcell) -> None closure over the DB.

        The closure persists each PowerDownOrchestrator stage transition
        to ``power_log`` for forensic reconstruction of drain events.
        Same pattern as :meth:`_createBatteryHealthRecorder` -- the DB
        dependency stays in lifecycle.py; hardware_manager receives a
        plain callable.
        """
        if self._database is None:
            logger.info(
                "powerLogWriter skipped: database not initialized; "
                "stage transitions will only land in journal"
            )
            return None
        try:
            from src.pi.power.power_db import logShutdownStage
            db = self._database

            def writer(eventType: str, vcell: float) -> None:
                logShutdownStage(db, eventType, vcell)

            return writer
        except Exception as e:
            logger.warning(
                "powerLogWriter init failed (stage transitions will only "
                "land in journal): %s", e,
            )
            return None

    def _wirePowerDownOrchestratorCallbacks(self) -> None:
        """US-216 / US-225: attach concrete stage-behavior callbacks.

        The orchestrator is constructed inside hardware_manager with no
        stage callbacks.  This method reaches in post-init and binds the
        four stage behaviors the Spool Session-6 directive + TD-034
        defined:

        * **WARNING@30%** -- set ``pi_state.no_new_drives=true`` so
          any cranking transition during the drain event proceeds
          id-less; trigger :meth:`SyncClient.forcePush` to flush
          pending deltas before poweroff may fire.
        * **IMMINENT@25%** -- :meth:`ApplicationOrchestrator.pausePolling`
          to stop new Mode 01 queries; :meth:`DriveDetector.forceKeyOff`
          to close any active drive with a ``'power_imminent'`` reason
          code so analytics see a first-class termination.
        * **AC-restore** -- clear ``no_new_drives`` and
          :meth:`ApplicationOrchestrator.resumePolling` so the
          collector reattaches its polling thread.  BT reconnect is
          owned by US-211's own path (adapter-reachable probe).

        Each callback is wrapped with broad exception capture so a
        raising stage behavior (missing DB, transport failure, dead
        data logger) never blocks the orchestrator from escalating
        to TRIGGER.  SyncClient is constructed lazily at WARNING
        time so the companion-service config can be disabled without
        breaking boot.
        """
        if self._hardwareManager is None:
            return
        orch = getattr(self._hardwareManager, 'powerDownOrchestrator', None)
        if orch is None:
            return

        def onWarning() -> None:
            logger.warning(
                "PowerDownOrchestrator WARNING stage fired -- "
                "setting no_new_drives gate + forcing sync flush"
            )
            self._setNoNewDrives(True)
            self._forceSyncPush('power_warning')

        def onImminent() -> None:
            logger.warning(
                "PowerDownOrchestrator IMMINENT stage fired -- "
                "pausing polling + forcing drive-end before TRIGGER"
            )
            # Pause polling first so the in-flight cycle finishes
            # before we close the active drive -- the drive-end row
            # then reflects the final observed readings.
            try:
                if hasattr(self, 'pausePolling'):
                    self.pausePolling(reason='power_imminent')
            except Exception as e:  # noqa: BLE001
                logger.error("IMMINENT pausePolling failed: %s", e)
            try:
                if self._driveDetector is not None:
                    forceFn = getattr(self._driveDetector, 'forceKeyOff', None)
                    if callable(forceFn):
                        forceFn(reason='power_imminent')
            except Exception as e:  # noqa: BLE001
                logger.error("IMMINENT forceKeyOff failed: %s", e)

        def onAcRestore() -> None:
            logger.info(
                "PowerDownOrchestrator AC restored -- clearing gate + "
                "resuming polling"
            )
            self._setNoNewDrives(False)
            try:
                if hasattr(self, 'resumePolling'):
                    self.resumePolling(reason='power_restored')
            except Exception as e:  # noqa: BLE001
                logger.error("AC-restore resumePolling failed: %s", e)

        # Reach in and bind. The orchestrator exposes these as attributes
        # on construction; updating them post-init is safe because tick()
        # only reads them through _invokeCallback.
        orch._onWarning = onWarning  # noqa: SLF001
        orch._onImminent = onImminent  # noqa: SLF001
        orch._onAcRestore = onAcRestore  # noqa: SLF001
        logger.info("PowerDownOrchestrator stage-behavior callbacks wired")
        # US-265 audit: confirm the orchestrator handed back by
        # HardwareManager is non-None (the tick-thread spawn path inside
        # _startComponents is gated on a non-None orchestrator + UPS).
        # The matching "tick thread spawned tid=<id>" entry in journalctl
        # lets a post-Drain-7 forensic walk prove the thread reached
        # .start() with daemon=True.  If the spawn line is missing while
        # this audit line is present, the bug is in HardwareManager's
        # spawn block, not lifecycle's wiring.
        logger.info(
            "PowerDownOrchestrator audit OK: orchestrator instantiated "
            "by HardwareManager; dedicated tick thread spawn delegated "
            "to HardwareManager._startComponents (US-252 + US-265)"
        )

    def _setNoNewDrives(self, value: bool) -> None:
        """Set the ``pi_state.no_new_drives`` gate (US-225).

        Used by the WARNING (set) + AC-restore (clear) callbacks.
        Swallows exceptions so a DB hiccup never blocks stage
        escalation; the ladder's primary shutdown still fires even
        when the gate cannot be persisted.
        """
        if self._database is None:
            logger.warning(
                "_setNoNewDrives(%s) skipped: database not initialized",
                value,
            )
            return
        try:
            from ..pi_state import setNoNewDrives
            with self._database.connect() as conn:
                setNoNewDrives(conn, value)
            logger.info(
                "pi_state.no_new_drives set to %s", value,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Failed to set pi_state.no_new_drives=%s: %s", value, e,
            )

    def _forceSyncPush(self, reasonCode: str) -> None:
        """Invoke :meth:`SyncClient.forcePush` if a client can be built.

        Constructs the client lazily so a boot without a companion
        service keeps working; swallows exceptions so a transport
        failure does not block the power-down ladder.
        """
        try:
            from pi.sync.client import SyncClient
            client = SyncClient(self._config)
            if not client.isEnabled:
                logger.info(
                    "forceSyncPush(%s): companion service disabled, skipping",
                    reasonCode,
                )
                return
            summary = client.forcePush()
            logger.warning(
                "forceSyncPush(%s) complete: rows=%d ok=%d failed=%d",
                reasonCode, summary.rowsPushed, summary.tablesOk,
                summary.tablesFailed,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                "forceSyncPush(%s) failed: %s", reasonCode, e,
            )

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

        # US-243 / B-050: subscribe PowerMonitor to UpsMonitor AFTER
        # HardwareManager.start() because UpsMonitor + the prior
        # ShutdownHandler.registerWithUpsMonitor wiring only exist post-start.
        # Wrapped in broad except so a wiring failure never blocks runLoop
        # entry (the audit-trail-loss is preferable to a boot crash).
        try:
            self._subscribePowerMonitorToUpsMonitor()
        except Exception as e:  # noqa: BLE001
            logger.error(
                "PowerMonitor subscription failed (power_log writes "
                "may stay dead): %s",
                e,
            )

        # US-279 LADDER FIX: subscribe PowerDownOrchestrator to
        # UpsMonitor's source-change events.  Same post-start ordering
        # as _subscribePowerMonitorToUpsMonitor -- both UpsMonitor and
        # PowerDownOrchestrator are constructed inside HardwareManager.
        # start().  Wrapped in broad except for the same boot-safety
        # invariant: a wiring failure degrades the ladder to the legacy
        # stale-arg path (back-compat fallback) but never blocks boot.
        try:
            self._subscribeOrchestratorToUpsMonitor()
        except Exception as e:  # noqa: BLE001
            logger.error(
                "PowerDownOrchestrator source-change subscription failed "
                "(ladder may revert to stale-arg fallback): %s",
                e,
            )

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
        """Initialize the realtime data logger component.

        US-221: wires US-211's ``handleCaptureError`` into the capture loop
        so BT flaps recover in-process (no systemd bounce for
        ADAPTER_UNREACHABLE / ECU_SILENT) and the ``_onCaptureFatalError``
        shutdown hook bounces the process on genuinely broken state via
        systemd ``Restart=always``.
        """
        logger.info("Starting dataLogger...")
        try:
            from ..data import createRealtimeLoggerFromConfig
            self._dataLogger = createRealtimeLoggerFromConfig(
                self._config, self._connection, self._database,
                captureErrorHandler=self.handleCaptureError,
                onFatalError=self._onCaptureFatalError,
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

    def _onCaptureFatalError(self, exc: BaseException) -> None:
        """Signal orchestrator shutdown when the capture loop reports FATAL.

        US-221 contract: the capture loop (RealtimeDataLogger) calls this
        callback when its injected ``captureErrorHandler`` re-raises --
        i.e. the classifier bucketed the exception as
        :attr:`CaptureErrorClass.FATAL`.  Mark the shutdown state so
        :meth:`runLoop` exits cleanly with a non-zero exit code; systemd
        ``Restart=always`` (US-210) handles the bounce.

        This is intentionally not a direct ``sys.exit()`` -- it runs on
        the capture thread, and forcing process exit from a daemon thread
        interferes with the orchestrator's shutdown pipeline.  Setting
        the shutdown state lets the main loop observe it on the next
        iteration and run the normal stop sequence.
        """
        # Local import to keep this file's top-level imports narrow.
        from .types import EXIT_CODE_FORCED as _FORCED
        logger.error(
            "Capture loop reported FATAL -- orchestrator shutting down for systemd restart",
            exc_info=exc,
        )
        self._exitCode = _FORCED
        self._shutdownState = ShutdownState.FORCE_EXIT
        self._running = False

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

    def _initializeSyncClient(self) -> None:
        """Initialize the Pi->server SyncClient (US-226).

        Wired only when ``pi.sync.enabled`` is true.  Construction is
        side-effect-free (no network, no DB handles held): the client
        holds no open socket and opens a fresh SQLite connection per
        push, so the only failure mode here is a misconfigured section
        (missing API key when companion service is enabled).

        Missing API key is treated as a soft failure: the client stays
        None, a warning is logged, and the orchestrator continues
        running.  This matches the US-225 forcePush pattern -- a
        disabled / misconfigured companion service must never block
        boot.  The interval trigger in :meth:`ApplicationOrchestrator.runLoop`
        observes ``self._syncClient is None`` and becomes a no-op.
        """
        syncConfig = self._config.get('pi', {}).get('sync', {})
        if syncConfig.get('enabled', True) is False:
            logger.info("SyncClient disabled via pi.sync.enabled=false")
            self._syncClient = None
            return
        try:
            from pi.sync.client import SyncClient
            self._syncClient = SyncClient(self._config)
            if not self._syncClient.isEnabled:
                logger.info(
                    "SyncClient constructed but companion service disabled "
                    "(pi.companionService.enabled=false) -- interval trigger "
                    "will be a no-op",
                )
            else:
                intervalSeconds = syncConfig.get('intervalSeconds', 60)
                triggers = syncConfig.get('triggerOn', ['interval'])
                logger.info(
                    "SyncClient initialized: baseUrl=%s intervalSeconds=%d "
                    "triggerOn=%s",
                    self._syncClient.baseUrl, intervalSeconds, triggers,
                )
        except Exception as e:  # noqa: BLE001 -- sync init must not fail boot
            logger.warning(
                "SyncClient initialization failed, sync disabled: %s (type=%s)",
                e, type(e).__name__,
            )
            self._syncClient = None

    def _initializePowerMonitor(self) -> None:
        """Instantiate the PowerMonitor that writes to ``power_log`` (US-243).

        Spool's 2026-04-21 audit + 2026-04-29 inverted-power drill found
        that ``power_log`` had been empty since installation: UpsMonitor
        was logging transitions to journald but PowerMonitor (the writer
        consuming those transitions) was never instantiated in production
        (``enabled=false`` default + zero orchestrator code paths). This
        method flips the gate.

        Gated on ``pi.power.power_monitor.enabled`` (default true, set by
        validator DEFAULTS) AND a live database. The actual subscription
        to UpsMonitor.onPowerSourceChange happens in
        :meth:`_subscribePowerMonitorToUpsMonitor`, called from
        :meth:`_startHardwareManager` -- UpsMonitor is created inside
        ``HardwareManager.start()``, so subscription cannot happen here.

        Construction is side-effect-free: PowerMonitor only opens a DB
        cursor when checkPowerStatus is invoked, so failing to instantiate
        is benign (the wired path becomes a no-op).
        """
        powerMonitorConfig = (
            self._config.get('pi', {}).get('power', {}).get('power_monitor', {})
        )
        if powerMonitorConfig.get('enabled', True) is False:
            logger.info(
                "PowerMonitor disabled via pi.power.power_monitor.enabled=false"
            )
            self._powerMonitor = None
            return
        if self._database is None:
            logger.info(
                "PowerMonitor skipped -- database not initialized "
                "(power_log writes require a live DB)"
            )
            self._powerMonitor = None
            return
        try:
            from pi.power.power import PowerMonitor
            self._powerMonitor = PowerMonitor(
                database=self._database,
                enabled=True,
            )
            logger.info(
                "PowerMonitor initialized (US-243 power_log write path active)"
            )
        except Exception as e:  # noqa: BLE001 -- power_log write must not fail boot
            logger.warning(
                "PowerMonitor initialization failed, power_log write path "
                "remains dead: %s (type=%s)",
                e, type(e).__name__,
            )
            self._powerMonitor = None

    def _initializeUpdateChecker(self) -> None:
        """Initialize the Pi UpdateChecker (US-247 / B-047 US-C).

        Wired only when ``pi.update.enabled`` is true. Construction is
        side-effect-free (no network, no filesystem writes): the checker
        only reaches out when :meth:`UpdateChecker.check_for_updates` is
        invoked from :meth:`ApplicationOrchestrator._maybeTriggerUpdateCheck`
        in the runLoop.

        The orchestrator hands the checker an ``isDrivingFn`` closure that
        delegates to :meth:`DriveDetector.isDriving`. The closure resolves
        the detector at call time (not at init time) because
        :meth:`_initializeDriveDetector` runs earlier in the chain but the
        detector reference can in principle be re-bound or torn down by a
        later lifecycle path -- defensive late-resolution prevents a stale
        reference from outliving its component. When the detector is
        absent, the gate defaults to ``False`` (open) -- a missing detector
        must NEVER be interpreted as "drive in progress" or update checks
        would be blocked indefinitely.

        Construction failures are soft: a warning is logged, the checker
        stays None, and :meth:`_maybeTriggerUpdateCheck` observes None and
        becomes a no-op. Update-check is a convenience feature, never
        boot-critical.
        """
        updateConfig = self._config.get('pi', {}).get('update', {})
        if updateConfig.get('enabled', True) is False:
            logger.info("UpdateChecker disabled via pi.update.enabled=false")
            self._updateChecker = None
            return

        def _isDrivingClosure() -> bool:
            detector = getattr(self, '_driveDetector', None)
            if detector is None:
                return False
            try:
                return bool(detector.isDriving())
            except Exception:  # noqa: BLE001 -- defensive: detector glitch
                return False

        try:
            from src.pi.update.update_checker import UpdateChecker
            self._updateChecker = UpdateChecker(
                self._config,
                isDrivingFn=_isDrivingClosure,
            )
            intervalMinutes = updateConfig.get('intervalMinutes', 60)
            logger.info(
                "UpdateChecker initialized: baseUrl=%s intervalMinutes=%d "
                "markerFilePath=%s",
                self._updateChecker.baseUrl,
                intervalMinutes,
                self._updateChecker.markerFilePath,
            )
        except Exception as e:  # noqa: BLE001 -- update-check must not fail boot
            logger.warning(
                "UpdateChecker initialization failed, update checks disabled: "
                "%s (type=%s)",
                e, type(e).__name__,
            )
            self._updateChecker = None

    def _initializeUpdateApplier(self) -> None:
        """Initialize the Pi UpdateApplier (US-248 / B-047 US-D).

        Wired only when ``pi.update.enabled`` is true (the same gate as
        :meth:`_initializeUpdateChecker` -- if updates are disabled the
        whole feature is off).  Construction is side-effect-free: the
        applier only runs subprocesses when :meth:`UpdateApplier.apply`
        is invoked from :meth:`ApplicationOrchestrator._maybeTriggerUpdateApply`
        in the runLoop.

        The orchestrator hands the applier three lazy closures:

        * ``isDrivingFn`` -- mirrors the US-247 pattern, resolves the
          drive detector at call time, returns False when absent
          (open-by-default safety: a missing detector must not
          perma-block updates).
        * ``getPowerSourceFn`` -- resolves the live UpsMonitor through
          ``HardwareManager.upsMonitor``; returns ``"external"`` when
          the monitor is not yet available (open-by-default).
        * ``getLastObdActivitySecondsAgoFn`` -- queries the ObdDatabase
          for ``MAX(timestamp)`` over ``connection_log``; returns None
          when no rows or no DB (open-by-default).  Read-only query,
          cheap to call once per apply tick.

        Construction failures are soft: a warning is logged, the
        applier stays None, and :meth:`_maybeTriggerUpdateApply`
        observes None and becomes a no-op.  Apply is a CIO-opt-in
        feature, never boot-critical.
        """
        updateConfig = self._config.get('pi', {}).get('update', {})
        if updateConfig.get('enabled', True) is False:
            logger.info("UpdateApplier disabled via pi.update.enabled=false")
            self._updateApplier = None
            return

        def _isDrivingClosure() -> bool:
            detector = getattr(self, '_driveDetector', None)
            if detector is None:
                return False
            try:
                return bool(detector.isDriving())
            except Exception:  # noqa: BLE001 -- defensive
                return False

        def _getPowerSourceClosure() -> str:
            hardwareManager = getattr(self, '_hardwareManager', None)
            if hardwareManager is None:
                return "external"
            upsMonitor = getattr(hardwareManager, 'upsMonitor', None)
            if upsMonitor is None:
                return "external"
            try:
                source = upsMonitor.getPowerSource()
            except Exception:  # noqa: BLE001 -- defensive
                return "external"
            return getattr(source, "value", str(source))

        def _getLastObdActivitySecondsAgoClosure() -> float | None:
            database = getattr(self, '_database', None)
            if database is None:
                return None
            try:
                with database.connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT "
                        "  CAST((julianday('now') - "
                        "        julianday(MAX(timestamp))) * 86400 AS REAL) "
                        "FROM connection_log"
                    )
                    row = cursor.fetchone()
            except Exception:  # noqa: BLE001 -- defensive
                return None
            if not row or row[0] is None:
                return None
            try:
                return float(row[0])
            except (TypeError, ValueError):
                return None

        try:
            from src.pi.update.update_applier import UpdateApplier
            self._updateApplier = UpdateApplier(
                self._config,
                isDrivingFn=_isDrivingClosure,
                getPowerSourceFn=_getPowerSourceClosure,
                getLastObdActivitySecondsAgoFn=(
                    _getLastObdActivitySecondsAgoClosure
                ),
            )
            logger.info(
                "UpdateApplier initialized: applyEnabled=%s stagingPath=%s "
                "rollbackEnabled=%s markerFilePath=%s",
                self._updateApplier.applyEnabled,
                self._updateApplier.stagingPath,
                self._updateApplier.rollbackEnabled,
                self._updateApplier.markerFilePath,
            )
        except Exception as e:  # noqa: BLE001 -- apply must not fail boot
            logger.warning(
                "UpdateApplier initialization failed, update apply disabled: "
                "%s (type=%s)",
                e, type(e).__name__,
            )
            self._updateApplier = None

    def _subscribePowerMonitorToUpsMonitor(self) -> None:
        """Wire UpsMonitor.onPowerSourceChange -> PowerMonitor.checkPowerStatus.

        Called from :meth:`_startHardwareManager` AFTER
        ``self._hardwareManager.start()`` returns, because UpsMonitor and
        the ShutdownHandler.registerWithUpsMonitor wiring (which sets
        ``upsMonitor.onPowerSourceChange = handler.onPowerSourceChange``)
        only happen inside ``HardwareManager.start()``.

        The fan-out wrapper preserves any prior callback (typically the
        ShutdownHandler legacy path, which is itself a no-op when
        ``suppressLegacyTriggers=True`` per US-216) so this wiring never
        clobbers existing behavior. Errors in the prior callback are
        swallowed so a regression there cannot kill the new audit path.

        UpsMonitor's PowerSource enum (EXTERNAL / BATTERY / UNKNOWN) is
        bridged to PowerMonitor's checkPowerStatus(onAcPower: bool) by
        treating BATTERY as ``onAcPower=False`` and everything else
        (EXTERNAL / UNKNOWN) as ``onAcPower=True``. UNKNOWN biased
        toward AC matches PowerMonitor's own initial state assumption
        (PowerSource.UNKNOWN -> ignored on first read; downstream
        transitions still fire correctly).
        """
        if self._powerMonitor is None:
            logger.debug(
                "_subscribePowerMonitorToUpsMonitor: PowerMonitor None, skipping"
            )
            return
        if self._hardwareManager is None:
            logger.debug(
                "_subscribePowerMonitorToUpsMonitor: HardwareManager None, skipping"
            )
            return
        upsMonitor = getattr(self._hardwareManager, 'upsMonitor', None)
        if upsMonitor is None:
            logger.debug(
                "_subscribePowerMonitorToUpsMonitor: UpsMonitor None "
                "(non-Pi or init failure), skipping"
            )
            return

        priorCallback = getattr(upsMonitor, 'onPowerSourceChange', None)
        powerMonitor = self._powerMonitor

        def fanOutPowerSourceChange(oldSource: Any, newSource: Any) -> None:
            # Preserve the prior path (ShutdownHandler) -- swallow its
            # exceptions so a regression there never poisons the new
            # audit path.
            if priorCallback is not None:
                try:
                    priorCallback(oldSource, newSource)
                except Exception as e:  # noqa: BLE001
                    logger.error(
                        "Prior UpsMonitor.onPowerSourceChange callback raised: %s",
                        e,
                    )

            # Bridge UpsMonitor PowerSource -> PowerMonitor onAcPower bool.
            # Only BATTERY counts as off-AC; EXTERNAL and UNKNOWN are AC.
            try:
                from pi.hardware.ups_monitor import (
                    PowerSource as HwPowerSource,
                )
                onAcPower = newSource != HwPowerSource.BATTERY
                powerMonitor.checkPowerStatus(onAcPower)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "PowerMonitor.checkPowerStatus failed: %s (type=%s)",
                    e, type(e).__name__,
                )

        upsMonitor.onPowerSourceChange = fanOutPowerSourceChange
        logger.info(
            "PowerMonitor subscribed to UpsMonitor.onPowerSourceChange "
            "(fan-out preserves prior callback)"
        )

    def _subscribeOrchestratorToUpsMonitor(self) -> None:
        """Wire UpsMonitor source-change events into PowerDownOrchestrator (US-279).

        The 8-drain saga (Sprints 21-24) ended at Drain Test 8 with the
        bug isolated: PowerDownOrchestrator.tick() was reading
        ``power_source`` from a stale/decoupled view of state.  Every
        one of 214 tick decisions during the 17.5-min battery window
        emitted ``reason=power_source!=BATTERY`` while UpsMonitor's
        polling loop correctly logged the BATTERY transition.

        US-279 closes the gap: UpsMonitor exposes
        :meth:`registerSourceChangeCallback` (new fan-out API), the
        orchestrator exposes :meth:`_onPowerSourceChange` as a
        single-arg callback that updates ``self._powerSource``
        synchronously, and this method wires the registration.  After
        wiring, every ``EXTERNAL <-> BATTERY`` transition the polling
        thread observes is PUSHED into the orchestrator's live
        attribute; the next tick reads it directly and the gating
        guard passes when on BATTERY.

        Idempotency: registering twice would fire the callback twice
        per transition (the ladder's _onPowerSourceChange is idempotent
        on re-application of the same value, but extra invocations are
        log noise).  This method is called once from
        :meth:`_startHardwareManager` per boot.

        Failure mode: when UpsMonitor or PowerDownOrchestrator is None
        (non-Pi or init failure) the wiring is skipped silently -- the
        legacy back-compat stale-arg fallback in tick() preserves
        whatever ladder behavior was available before US-279.
        """
        # V0.24.1 hotfix: every skip-path is now WARNING-level (was DEBUG).
        # Production runs INFO; the prior DEBUG bails were invisible in
        # journalctl, hiding the failure mode of a non-functioning safety
        # ladder behind LOOK-OK logs.  US-281 anti-pattern doc applies:
        # silent boot-safety fallbacks for required wiring are worse than
        # a loud failure, because they give false confidence that the
        # ladder is armed when it is not.
        if self._hardwareManager is None:
            logger.warning(
                "_subscribeOrchestratorToUpsMonitor: HardwareManager None "
                "-- ladder will not fire; graceful shutdown disarmed"
            )
            return
        upsMonitor = getattr(self._hardwareManager, 'upsMonitor', None)
        if upsMonitor is None:
            logger.warning(
                "_subscribeOrchestratorToUpsMonitor: UpsMonitor None "
                "(non-Pi or init failure) -- ladder will not fire; "
                "graceful shutdown disarmed"
            )
            return
        orchestrator = getattr(
            self._hardwareManager, 'powerDownOrchestrator', None,
        )
        if orchestrator is None:
            logger.warning(
                "_subscribeOrchestratorToUpsMonitor: "
                "PowerDownOrchestrator None (config-disabled or unwired) "
                "-- ladder will not fire; graceful shutdown disarmed"
            )
            return

        registerFn = getattr(
            upsMonitor, 'registerSourceChangeCallback', None,
        )
        if registerFn is None:
            logger.error(
                "_subscribeOrchestratorToUpsMonitor: UpsMonitor lacks "
                "registerSourceChangeCallback method -- US-279 wiring "
                "is incomplete; ladder reverts to stale-arg fallback"
            )
            return

        registerFn(orchestrator._onPowerSourceChange)
        logger.info(
            "PowerDownOrchestrator subscribed to UpsMonitor source-change "
            "events (US-279 -- closes the 8-drain saga stale-cached-read "
            "bug class)"
        )

        # V0.24.1 boot-time canary -- prove the just-registered callback
        # actually flips orchestrator._powerSource when invoked through
        # UpsMonitor's fan-out.  If module-identity, signature drift, or
        # any future refactor breaks the wiring chain, this self-test
        # logs ERROR at boot rather than silently passing the buck to
        # the next drain test.  Wrapped in broad-except so a self-test
        # failure cannot block the runLoop -- but the ERROR log line is
        # the canary operators must monitor.
        try:
            self._verifyOrchestratorCallbackWiring(upsMonitor, orchestrator)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "PowerDownOrchestrator wiring self-test raised "
                "(ladder may be disarmed): %s",
                e,
            )

    def _verifyOrchestratorCallbackWiring(
        self, upsMonitor: Any, orchestrator: Any,
    ) -> None:
        """V0.24.1 boot-time canary: prove the callback path updates state.

        After ``_subscribeOrchestratorToUpsMonitor`` registers
        ``orchestrator._onPowerSourceChange``, fire a synthetic transition
        through ``UpsMonitor._invokeSourceChangeCallbacks`` and verify
        the orchestrator's ``_powerSource`` attribute compares equal to
        ``UpsMonitor.PowerSource.BATTERY`` (the value the production
        polling thread will deliver on the next real transition).  This
        is the regression gate for the dual-import enum identity bug
        that hid for 9 drain tests across 4 sprints: pre-V0.24.1 the
        comparison silently failed across the module boundary, and the
        ladder bailed every tick in production.

        Self-test fires BATTERY then EXTERNAL so the orchestrator's
        state is NOT left mid-drain after the canary -- AC is reality
        during boot wiring.  Restores the prior ``_powerSource`` value
        if it was set at all (production wiring runs once at boot, so
        ``priorSource is None`` is the normal case).
        """
        from pi.hardware.ups_monitor import PowerSource

        priorSource = getattr(orchestrator, '_powerSource', None)

        upsMonitor._invokeSourceChangeCallbacks(PowerSource.BATTERY)
        if orchestrator._powerSource != PowerSource.BATTERY:
            logger.error(
                "PowerDownOrchestrator wiring self-test FAILED: "
                "after _invokeSourceChangeCallbacks(BATTERY), "
                "orchestrator._powerSource=%r (expected BATTERY).  "
                "Ladder is DISARMED -- the callback chain is not "
                "propagating into the orchestrator's live attribute. "
                "Likely cause: cross-module PowerSource enum identity "
                "regression (V0.24.1 bug class) or signature drift in "
                "_onPowerSourceChange.",
                orchestrator._powerSource,
            )
            return

        upsMonitor._invokeSourceChangeCallbacks(PowerSource.EXTERNAL)
        if orchestrator._powerSource != PowerSource.EXTERNAL:
            logger.error(
                "PowerDownOrchestrator wiring self-test FAILED on AC "
                "restore: after _invokeSourceChangeCallbacks(EXTERNAL), "
                "orchestrator._powerSource=%r (expected EXTERNAL). "
                "Ladder may stay armed even on AC -- spurious shutdown "
                "risk on subsequent ticks.",
                orchestrator._powerSource,
            )
            return

        logger.info(
            "PowerDownOrchestrator wiring self-test PASSED: "
            "callback chain propagates BATTERY <-> EXTERNAL transitions "
            "into orchestrator._powerSource (V0.24.1 enum identity "
            "regression gate)"
        )

        # Restore prior _powerSource so the canary leaves no side effect.
        # Normal case at boot: priorSource is None (callback never fired
        # yet) and orchestrator._powerSource is now EXTERNAL from the
        # canary's restore step -- which matches reality during boot.
        if priorSource is not None:
            orchestrator._powerSource = priorSource

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
        self._shutdownPowerMonitor()
        self._shutdownSyncClient()
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

    def _shutdownPowerMonitor(self) -> None:
        """Shutdown the PowerMonitor (US-243 / B-050).

        PowerMonitor was instantiated without a polling thread (the
        write path is event-driven via UpsMonitor.onPowerSourceChange),
        so shutdown is just dropping the reference. Idempotent: safe to
        call when ``_powerMonitor`` was never assigned (init disabled or
        skipped).

        UpsMonitor itself is closed by HardwareManager's own shutdown
        path; we don't need to unhook the fan-out callback here.
        """
        if self._powerMonitor is not None:
            logger.info("Stopping powerMonitor...")
            try:
                # PowerMonitor.stop() is idempotent and safe even when
                # start() was never called (no polling thread).
                if hasattr(self._powerMonitor, 'stop'):
                    self._powerMonitor.stop()
            except Exception as e:  # noqa: BLE001
                logger.warning("Error stopping powerMonitor: %s", e)
            logger.info("PowerMonitor stopped successfully")
        self._powerMonitor = None

    def _shutdownSyncClient(self) -> None:
        """Shutdown the SyncClient (US-226).

        SyncClient holds no open connections between pushes (each
        :meth:`SyncClient.pushDelta` opens + closes its own SQLite
        connection, and HTTP is one-shot), so shutdown is just
        clearing the reference.  Kept as a named method for symmetry
        with other components + so future refactors that add a
        background sync thread have an obvious attach point.
        """
        if self._syncClient is not None:
            logger.info("Stopping syncClient...")
            logger.info("SyncClient stopped successfully")
        self._syncClient = None

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
