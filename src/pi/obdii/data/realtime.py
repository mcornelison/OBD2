################################################################################
# File Name: realtime.py
# Purpose/Description: RealtimeDataLogger class for continuous OBD-II data logging
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-007 (data module refactor)
# 2026-04-21    | Rex (US-212) | Accept optional dataSource kwarg; forwards
#                               to the inner ObdDataLogger so simulator
#                               callers stamp rows as 'physics_sim'.
# 2026-04-22    | Rex (US-221) | Wire US-211 handleCaptureError into the
#                               capture loop: captureErrorHandler +
#                               onFatalError injection points, wrapped
#                               ParameterReadError cause-unwrap, and
#                               ECU-silent cadence multiplier with
#                               restore-on-success.
# ================================================================================
################################################################################
"""
Continuous realtime OBD-II data logging.

Provides a background thread that polls configured parameters at a specified
interval and logs readings to the database.

Features:
- Configurable polling interval (default: 1000ms)
- Only logs parameters with logData=True
- Millisecond timestamp precision
- Graceful handling of unavailable parameters
- Profile-associated data logging
- Thread-safe start/stop control
- Comprehensive statistics tracking

Usage:
    from src.obd.data.realtime import RealtimeDataLogger

    config = loadObdConfig('obd_config.json')
    db = initializeDatabase(config)
    conn = createConnectionFromConfig(config, db)
    conn.connect()

    rtLogger = RealtimeDataLogger(config, conn, db)
    rtLogger.start()

    # ... let it run for a while ...

    rtLogger.stop()
    stats = rtLogger.getStats()
    print(f"Logged {stats.totalLogged} readings")
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..error_classification import CaptureErrorClass, classifyCaptureError
from .exceptions import DataLoggerError, ParameterNotSupportedError, ParameterReadError
from .logger import ObdDataLogger
from .types import LoggedReading, LoggingState, LoggingStats

logger = logging.getLogger(__name__)

#: Default multiplier applied to the polling interval when the classifier
#: reports :attr:`CaptureErrorClass.ECU_SILENT`. 5x is the conservative
#: default per US-221 ("Ralph picks conservative multiplier per Spool's
#: spec"): at a 100ms base cadence this slows to 500ms, enough to ease
#: the pressure on a silent ECU without sacrificing responsiveness when
#: the engine comes back. Exposed via the constructor for tests.
DEFAULT_ECU_SILENT_MULTIPLIER: int = 5


class RealtimeDataLogger:
    """
    Manages continuous realtime OBD-II data logging.

    Provides a background thread that polls configured parameters at a specified
    interval and logs readings to the database. Only parameters with logData=True
    in the configuration are logged.

    Features:
    - Configurable polling interval (default: 1000ms)
    - Only logs parameters with logData=True
    - Millisecond timestamp precision
    - Graceful handling of unavailable parameters
    - Profile-associated data logging
    - Thread-safe start/stop control
    - Comprehensive statistics tracking

    Attributes:
        config: Configuration dictionary with realtimeData settings
        connection: ObdConnection instance
        database: ObdDatabase instance for data storage
        state: Current logging state

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)
        conn.connect()

        rtLogger = RealtimeDataLogger(config, conn, db)
        rtLogger.start()

        # ... let it run for a while ...

        rtLogger.stop()
        stats = rtLogger.getStats()
        print(f"Logged {stats.totalLogged} readings")
    """

    def __init__(
        self,
        config: dict[str, Any],
        connection: Any,
        database: Any,
        profileId: str | None = None,
        dataSource: str | None = None,
        *,
        captureErrorHandler: Callable[[BaseException], CaptureErrorClass] | None = None,
        onFatalError: Callable[[BaseException], None] | None = None,
        ecuSilentMultiplier: int = DEFAULT_ECU_SILENT_MULTIPLIER,
    ):
        """
        Initialize the realtime data logger.

        Args:
            config: Configuration dictionary with 'realtimeData' and
                'profiles' sections.
            connection: ObdConnection instance for OBD-II communication.
            database: ObdDatabase instance for data storage.
            profileId: Optional profile ID (defaults to active profile
                from config).
            dataSource: Optional origin tag forwarded to the inner
                :class:`ObdDataLogger` (US-212).  When omitted the
                inner logger auto-derives from
                ``connection.isSimulated``.
            captureErrorHandler: US-221 injection point -- routes
                unexpected capture-boundary exceptions through the
                US-211 classifier (typically
                :meth:`BtResilienceMixin.handleCaptureError`).  ADAPTER
                flaps recover in-process, ECU_SILENT reduces cadence,
                FATAL re-raises so the loop can signal shutdown.  When
                ``None``, the legacy per-parameter error path runs
                (backward compatible).
            onFatalError: US-221 shutdown hook.  Invoked with the
                original exception when the handler reports (re-raises)
                FATAL.  Production wires this to the orchestrator's
                ``stop()`` so systemd ``Restart=always`` bounces the
                process; tests substitute a recorder.
            ecuSilentMultiplier: Multiplier applied to
                :attr:`_pollingIntervalMs` while the classifier has
                reported ECU_SILENT.  Cleared on the first successful
                query so the loop snaps back to normal cadence when
                the ECU wakes up.
        """
        self.config = config
        self.connection = connection
        self.database = database

        # Determine profile ID
        if profileId is not None:
            self.profileId = profileId
        else:
            profiles = config.get('pi', {}).get('profiles', {})
            self.profileId = profiles.get('activeProfile')  # None if not specified

        # Extract logging configuration
        self._pollingIntervalMs = self._getPollingInterval()
        self._parameters = self._getLoggedParameterNames()

        # Thread control
        self._state = LoggingState.STOPPED
        self._stopEvent = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Statistics
        self._stats = LoggingStats()
        self._cycleTimes: list[float] = []

        # Internal data logger for actual queries
        self._dataLogger = ObdDataLogger(
            connection, database,
            profileId=self.profileId, dataSource=dataSource,
        )

        # Callbacks
        self._onReading: Callable[[LoggedReading], None] | None = None
        self._onError: Callable[[str, Exception], None] | None = None
        self._onCycleComplete: Callable[[int], None] | None = None

        # US-221: capture-boundary error routing (see class docstring).
        self._captureErrorHandler = captureErrorHandler
        self._onFatalError = onFatalError
        self._ecuSilentMultiplier = max(1, int(ecuSilentMultiplier))
        self._ecuSilentMode = False

    @property
    def state(self) -> LoggingState:
        """Get current logging state."""
        return self._state

    @property
    def isRunning(self) -> bool:
        """Check if logger is currently running."""
        return self._state == LoggingState.RUNNING

    def _getPollingInterval(self) -> int:
        """
        Get the polling interval from configuration.

        Checks active profile first, then falls back to global setting.

        Returns:
            Polling interval in milliseconds
        """
        # Check active profile first
        profiles = self.config.get('pi', {}).get('profiles', {})
        activeProfileId = profiles.get('activeProfile', 'daily')
        availableProfiles = profiles.get('availableProfiles', [])

        for profile in availableProfiles:
            if profile.get('id') == activeProfileId:
                if 'pollingIntervalMs' in profile:
                    return profile['pollingIntervalMs']
                break

        # Fall back to global realtime setting
        return self.config.get('pi', {}).get('realtimeData', {}).get('pollingIntervalMs', 1000)

    def _getLoggedParameterNames(self) -> list[str]:
        """
        Get list of parameter names that should be logged.

        Only returns parameters with logData=True.

        Returns:
            List of parameter names to log
        """
        parameters = self.config.get('pi', {}).get('realtimeData', {}).get('parameters', [])
        loggedParams = []

        for param in parameters:
            if isinstance(param, dict):
                if param.get('logData', False):
                    name = param.get('name', '')
                    if name:
                        loggedParams.append(name)
            elif isinstance(param, str):
                # String parameters default to being logged
                loggedParams.append(param)

        return loggedParams

    def setPollingInterval(self, intervalMs: int) -> None:
        """
        Update the polling interval.

        Can be called while running - takes effect on next cycle.

        Args:
            intervalMs: New polling interval in milliseconds (minimum 100ms)

        Raises:
            ValueError: If interval is less than 100ms
        """
        if intervalMs < 100:
            raise ValueError("Polling interval must be at least 100ms")

        with self._lock:
            self._pollingIntervalMs = intervalMs
            logger.info(f"Polling interval updated to {intervalMs}ms")

    def registerCallbacks(
        self,
        onReading: Callable[[LoggedReading], None] | None = None,
        onError: Callable[[str, Exception], None] | None = None,
        onCycleComplete: Callable[[int], None] | None = None
    ) -> None:
        """
        Register callbacks for logging events.

        Args:
            onReading: Called for each successful reading
            onError: Called when a parameter read fails (paramName, exception)
            onCycleComplete: Called after each polling cycle (cycle number)
        """
        self._onReading = onReading
        self._onError = onError
        self._onCycleComplete = onCycleComplete

    def start(self) -> bool:
        """
        Start continuous realtime logging in a background thread.

        Returns:
            True if started successfully, False if already running or error

        Raises:
            DataLoggerError: If not connected to OBD-II
        """
        with self._lock:
            if self._state in (LoggingState.RUNNING, LoggingState.STARTING):
                logger.warning("Realtime logger already running")
                return False

            if not self.connection.isConnected():
                raise DataLoggerError(
                    "Cannot start realtime logging - not connected to OBD-II"
                )

            if not self._parameters:
                raise DataLoggerError(
                    "No parameters configured for logging. "
                    "Check realtimeData.parameters in config with logData=True"
                )

            self._state = LoggingState.STARTING
            self._stopEvent.clear()

            # Reset statistics
            self._stats = LoggingStats()
            self._stats.startTime = datetime.now()
            self._cycleTimes = []

            # Start background thread
            self._thread = threading.Thread(
                target=self._loggingLoop,
                name='RealtimeDataLogger',
                daemon=True
            )
            self._thread.start()

            logger.info(
                f"Realtime logging started | "
                f"parameters={len(self._parameters)} | "
                f"interval={self._pollingIntervalMs}ms | "
                f"profile={self.profileId}"
            )

            return True

    def stop(self, timeout: float = 5.0) -> bool:
        """
        Stop realtime logging gracefully.

        Args:
            timeout: Maximum time to wait for thread to stop in seconds

        Returns:
            True if stopped successfully, False if timeout
        """
        with self._lock:
            if self._state == LoggingState.STOPPED:
                return True

            self._state = LoggingState.STOPPING

        # Signal thread to stop
        self._stopEvent.set()

        # Wait for thread to finish
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

            if self._thread.is_alive():
                logger.warning("Realtime logging thread did not stop within timeout")
                return False

        with self._lock:
            self._state = LoggingState.STOPPED
            self._stats.endTime = datetime.now()

        logger.info(
            f"Realtime logging stopped | "
            f"cycles={self._stats.totalCycles} | "
            f"logged={self._stats.totalLogged} | "
            f"errors={self._stats.totalErrors}"
        )

        return True

    def _loggingLoop(self) -> None:
        """
        Main logging loop that runs in background thread.

        Polls parameters at configured interval, logs readings to database,
        and handles errors gracefully.
        """
        with self._lock:
            self._state = LoggingState.RUNNING

        while not self._stopEvent.is_set():
            cycleStartTime = time.perf_counter()

            try:
                self._pollCycle()
            except Exception as e:
                logger.error(f"Error in logging cycle: {e}")
                self._stats.totalErrors += 1

            # Calculate cycle duration
            cycleEndTime = time.perf_counter()
            cycleDurationMs = (cycleEndTime - cycleStartTime) * 1000
            self._cycleTimes.append(cycleDurationMs)
            self._stats.lastCycleTimeMs = cycleDurationMs

            # Update average (keep last 100 cycles for average)
            if len(self._cycleTimes) > 100:
                self._cycleTimes = self._cycleTimes[-100:]
            self._stats.averageCycleTimeMs = sum(self._cycleTimes) / len(self._cycleTimes)

            self._stats.totalCycles += 1

            # Callback for cycle complete
            if self._onCycleComplete:
                try:
                    self._onCycleComplete(self._stats.totalCycles)
                except Exception as e:
                    logger.warning(f"onCycleComplete callback error: {e}")

            # Calculate sleep time to maintain polling interval.  US-221:
            # the effective interval scales by _ecuSilentMultiplier while
            # the ECU is silent so the loop eases poll pressure.
            sleepTimeMs = self._getEffectivePollingIntervalMs() - cycleDurationMs
            if sleepTimeMs > 0:
                # Sleep in small intervals to allow for quick stop
                sleepTimeSec = sleepTimeMs / 1000.0
                sleepInterval = min(sleepTimeSec, 0.1)  # Check every 100ms max

                remaining = sleepTimeSec
                while remaining > 0 and not self._stopEvent.is_set():
                    time.sleep(min(remaining, sleepInterval))
                    remaining -= sleepInterval

    def _pollCycle(self) -> None:
        """
        Execute one polling cycle - read all configured parameters.

        Logs each parameter and handles errors per-parameter without
        stopping the entire cycle.  US-221: capture-boundary exceptions
        (BT drop, ECU silent, fatal) are routed through
        :attr:`_captureErrorHandler` so the collector recovers in-process
        instead of polling a dead connection until systemd bounces it.
        """
        for paramName in self._parameters:
            if self._stopEvent.is_set():
                break

            try:
                # Query the parameter - use high-precision timestamp
                timestamp = datetime.now()  # Includes microseconds

                reading = self._queryParameterSafe(paramName)

                if reading is not None:
                    # Override timestamp for millisecond precision
                    reading.timestamp = timestamp

                    # Log to database
                    self._logReadingSafe(reading)

                    # Update stats
                    self._stats.totalReadings += 1
                    self._stats.parametersLogged[paramName] = \
                        self._stats.parametersLogged.get(paramName, 0) + 1

                    # US-221: first successful query clears ECU-silent mode
                    # so cadence returns to normal as soon as the ECU wakes.
                    self._onSuccessfulQuery()

                    # Callback
                    if self._onReading:
                        try:
                            self._onReading(reading)
                        except Exception as e:
                            logger.warning(f"onReading callback error: {e}")

            except Exception as e:
                # US-221: prefer the capture-boundary classifier when wired.
                # On ADAPTER_UNREACHABLE / ECU_SILENT / FATAL the handler
                # owns the reaction; fall back to the per-parameter error
                # path only when no handler is injected (legacy tests +
                # callers that have not yet adopted the wiring).
                if self._routeCaptureError(paramName, e):
                    break  # Handler consumed; restart cycle next tick.
                self._handleParameterError(paramName, e)

    def _queryParameterSafe(self, parameterName: str) -> LoggedReading | None:
        """
        Query a parameter safely, catching and handling errors.

        Returns ``None`` for genuinely null responses (ECU didn't return
        a value for this PID but the connection is healthy).  When the
        underlying read raised a capture-boundary exception that
        :class:`ObdDataLogger.queryParameter` wrapped as
        :exc:`ParameterReadError` (``__cause__`` set), US-221 re-raises
        the cause so :meth:`_pollCycle` can route it through the
        classifier.  This keeps the public ``queryParameter`` contract
        unchanged while giving the realtime loop visibility into BT
        drops, ECU silences, and FATAL exceptions.

        Args:
            parameterName: Name of the parameter to query

        Returns:
            LoggedReading if successful, None if parameter unavailable
        """
        try:
            return self._dataLogger.queryParameter(parameterName)
        except ParameterNotSupportedError:
            # Parameter not supported by vehicle - log once and skip
            logger.debug(f"Parameter '{parameterName}' not supported - skipping")
            return None
        except ParameterReadError as e:
            cause = e.__cause__
            if cause is not None and self._isCaptureBoundaryCause(cause):
                raise cause from None
            # Null response - parameter may be temporarily unavailable
            logger.debug(f"Parameter '{parameterName}' returned null: {e}")
            return None

    def _isCaptureBoundaryCause(self, cause: BaseException) -> bool:
        """Return True when ``cause`` is US-221-routable.

        Delegates to the shared classifier: anything the classifier can
        bucket as ADAPTER_UNREACHABLE / ECU_SILENT / FATAL is something
        the realtime loop wants to see unwrapped.  That includes FATAL
        itself -- bubbling a FATAL cause up through the classifier
        ensures the re-raise path fires and systemd gets its restart
        signal rather than the exception being silently swallowed as a
        ``ParameterReadError``.
        """
        try:
            classifyCaptureError(cause)
        except Exception:  # noqa: BLE001 -- defensive
            return False
        return True

    def _routeCaptureError(self, paramName: str, exc: Exception) -> bool:
        """Route ``exc`` through the US-221 captureErrorHandler.

        Returns:
            True  -- handler was wired and consumed the exception
                     (ADAPTER_UNREACHABLE / ECU_SILENT succeeded, or
                     FATAL was signaled and the loop should stop).
                     Caller should break out of the current cycle.
            False -- no handler wired; caller should fall back to the
                     legacy per-parameter error path.
        """
        if self._captureErrorHandler is None:
            return False

        self._stats.totalErrors += 1
        self._stats.errorsByParameter[paramName] = (
            self._stats.errorsByParameter.get(paramName, 0) + 1
        )

        try:
            classification = self._captureErrorHandler(exc)
        except BaseException as fatal:  # noqa: BLE001 -- classifier re-raised
            logger.error(
                "FATAL capture-boundary exception -- signaling orchestrator shutdown",
                exc_info=fatal,
            )
            self._stopEvent.set()
            if self._onFatalError is not None:
                try:
                    self._onFatalError(fatal)
                except Exception as cbExc:  # noqa: BLE001 -- never crash the loop
                    logger.warning("onFatalError callback raised: %s", cbExc)
            return True

        if classification is CaptureErrorClass.ECU_SILENT:
            if not self._ecuSilentMode:
                logger.info(
                    "ECU silent -- reducing poll cadence %dx until ECU responds",
                    self._ecuSilentMultiplier,
                )
            self._ecuSilentMode = True
        elif classification is CaptureErrorClass.ADAPTER_UNREACHABLE:
            # Handler ran the reconnect loop synchronously; connection is
            # fresh.  Leave silent mode (if set) alone -- the next cycle's
            # first successful query will clear it naturally.
            logger.info("Adapter reconnected -- resuming capture loop")
        return True

    def _onSuccessfulQuery(self) -> None:
        """Clear ECU-silent mode (US-221) when a parameter read succeeds."""
        if self._ecuSilentMode:
            logger.info("ECU responded -- restoring normal poll cadence")
            self._ecuSilentMode = False

    def _getEffectivePollingIntervalMs(self) -> int:
        """Return the polling interval adjusted for ECU-silent mode.

        When :attr:`_ecuSilentMode` is set, multiplies the base interval
        by :attr:`_ecuSilentMultiplier` to ease pressure on the silent
        ECU.  Normal cadence resumes automatically on the first successful
        query (see :meth:`_onSuccessfulQuery`).
        """
        if self._ecuSilentMode:
            return self._pollingIntervalMs * self._ecuSilentMultiplier
        return self._pollingIntervalMs

    def _logReadingSafe(self, reading: LoggedReading) -> bool:
        """
        Log a reading safely, catching database errors.

        Args:
            reading: LoggedReading to store

        Returns:
            True if logged successfully
        """
        try:
            self._dataLogger.logReading(reading)
            self._stats.totalLogged += 1
            return True
        except Exception as e:
            logger.warning(f"Failed to log reading: {e}")
            self._stats.totalErrors += 1
            return False

    def _handleParameterError(self, paramName: str, error: Exception) -> None:
        """
        Handle an error reading a parameter.

        Args:
            paramName: Name of the parameter that failed
            error: The exception that occurred
        """
        self._stats.totalErrors += 1
        self._stats.errorsByParameter[paramName] = \
            self._stats.errorsByParameter.get(paramName, 0) + 1

        logger.debug(f"Error reading parameter '{paramName}': {error}")

        # Callback
        if self._onError:
            try:
                self._onError(paramName, error)
            except Exception as e:
                logger.warning(f"onError callback error: {e}")

    def getStats(self) -> LoggingStats:
        """
        Get current logging statistics.

        Returns:
            LoggingStats with current session statistics
        """
        return self._stats

    def getParameters(self) -> list[str]:
        """
        Get list of parameters being logged.

        Returns:
            List of parameter names
        """
        return list(self._parameters)

    def getPollingIntervalMs(self) -> int:
        """
        Get current polling interval.

        Returns:
            Polling interval in milliseconds
        """
        return self._pollingIntervalMs
