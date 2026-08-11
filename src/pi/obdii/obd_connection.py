################################################################################
# File Name: obd_connection.py
# Purpose/Description: Bluetooth OBD-II dongle connection management
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-003
# 2026-04-23    | Rex (US-232)  | TD-035 close: accept shutdownEvent; retry
#                |              | loop uses Event.wait() for backoff so
#                |              | SIGTERM wakes mid-sleep within ~ms.
# 2026-05-08    | Rex (V0.27.1) | Hotfix: connect() is now thread-safe.  Sprint
#                |              | 27 engine-on test #2 produced 0 realtime_data
#                |              | rows because the Sprint 25 leaked connect
#                |              | daemon and the Sprint 27 US-301 heartbeat-
#                |              | spawned daemons collided on /dev/rfcomm0
#                |              | ("multiple access on port?" pyserial errors).
#                |              | __init__ instantiates self._connectLock;
#                |              | connect() body runs under it; new
#                |              | isConnectInFlight() exposes the lock state to
#                |              | heartbeat callers so they can log
#                |              | already_in_flight and skip instead of
#                |              | stacking concurrent attempts.
# 2026-07-03    | Rex (US-441) | F-117/A-17 capture fix.  The V0.27.1 lock only
#                |              | guarded connect(); the realtime logger reads
#                |              | self.connection.obd.query() DIRECTLY, racing
#                |              | orphaned timeout daemons -> "device disconnected
#                |              | while reading" -> 0 rows.  Rename _connectLock ->
#                |              | _ioLock and make it the SINGLE serialization
#                |              | lock for EVERY .obd access: connect(), the new
#                |              | query() method, disconnect()'s close(), and the
#                |              | supported-PID probe.  Add a generation/epoch
#                |              | counter (bumped on each connect-success + each
#                |              | disconnect) so a superseded (timed-out, left-
#                |              | running) connect/query daemon is FENCED from
#                |              | touching a connection a newer owner now holds:
#                |              | connect(callerGeneration=) skips re-open,
#                |              | query(callerGeneration=) raises
#                |              | ObdConnectionSupersededError.  Callers with no
#                |              | generation (the live logger read path) are
#                |              | never fenced -- they always read the current
#                |              | connection.  TD-036 no-boot-hang preserved
#                |              | (the daemon+wall-clock pattern is untouched;
#                |              | only .obd access is serialized).
# 2026-07-03    | Rex (US-432) | BL-016 Option B capture fix.  A cold-boot-key-
#                |              | OFF connect runs the US-199 supported-PID probe
#                |              | with the engine off, so the dark ECU poisons
#                |              | python-obd's supported_commands cache for RPM --
#                |              | every later obd.query(RPM) returns null with NO
#                |              | wire traffic and the drive never starts.  Add an
#                |              | engine-confirmed latch (setEngineConfirmedForce-
#                |              | Mandatory, cleared on drive_end + disconnect) so
#                |              | query() force-reads the KNOWN-MANDATORY Mode-01
#                |              | PIDs (MANDATORY_MODE01_PIDS = RPM) past the stale
#                |              | cache.  SCOPED, never blanket (a blanket force
#                |              | re-exposes the 0x42/0x0B/0x15 garbage US-199
#                |              | skips).  Read-path only -- the DriveDetector
#                |              | RPM-sustained machine (US-388) is untouched.
# 2026-08-02    | Rex (US-512) | BL-025 P1 capture hardening.  An rfcomm bind is a
#                |              | KERNEL TABLE ENTRY that OUTLIVES the ACL link, and
#                |              | bindRfcomm is idempotent -- so after the dongle
#                |              | drops, every retry short-circuits on the surviving
#                |              | entry and re-opens the SAME DEAD tty, forever.
#                |              | Worse, the entry also outlives the PROCESS: a
#                |              | SIGKILLed predecessor leaves it bound, the new
#                |              | process has _boundRfcomm=False so its disconnect
#                |              | never releases it, and `systemctl restart` does not
#                |              | clear the fault.  Fix: resetTransport() (Spool's
#                |              | disconnect -> releaseRfcomm -> re-bind), used by
#                |              | reconnect(); plus a per-failed-attempt binding drop
#                |              | keyed on "the configured port is a MAC" (NOT on our
#                |              | own bookkeeping) so the US-338 heartbeat -- which
#                |              | calls connect() and never reconnect() -- re-binds
#                |              | each tick.  Also assures the bluez bond (trust) at
#                |              | connect time, the runtime half of the durable-bond
#                |              | story pair_obdlink.sh only ever wrote at pair time.
#                |              | Deliberately never touches the radio (rfkill /
#                |              | hciconfig / `power off`) -- that class of recovery
#                |              | is what got persisted as the 07-03 soft-block.
# ================================================================================
################################################################################

"""
Bluetooth OBD-II connection management module.

Provides:
- Bluetooth OBD-II dongle connectivity using python-OBD library
- Retry logic with configurable exponential backoff
- Connection status monitoring
- Connection attempt logging to database

Usage:
    from obd.obd_connection import ObdConnection

    # Create connection manager
    conn = ObdConnection(config, database)

    # Connect with retry
    if conn.connect():
        status = conn.getStatus()
        # Use conn.obd for OBD commands
        rpm = conn.obd.query(obd.commands.RPM)

    # Disconnect
    conn.disconnect()
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from . import bluetooth_helper, bond_self_heal

logger = logging.getLogger(__name__)


# OBD library import with fallback for environments where it's not available
try:
    import obd as obdlib
    OBD_AVAILABLE = True
except ImportError:
    obdlib = None  # type: ignore
    OBD_AVAILABLE = False
    logger.warning("python-OBD library not available - OBD functionality disabled")


# ================================================================================
# Constants
# ================================================================================

# Default retry delays in seconds (exponential backoff)
DEFAULT_RETRY_DELAYS = [1, 2, 4, 8, 16]

# Default connection timeout in seconds
DEFAULT_CONNECTION_TIMEOUT = 30

# Default rfcomm device index and channel for OBDLink LX.
# Channel 1 is the SPP channel confirmed via sdptool browse during Session 23.
DEFAULT_RFCOMM_DEVICE = 0
DEFAULT_RFCOMM_CHANNEL = 1

# Connection event types for logging
EVENT_TYPE_CONNECT_ATTEMPT = 'connect_attempt'
EVENT_TYPE_CONNECT_SUCCESS = 'connect_success'
EVENT_TYPE_CONNECT_FAILURE = 'connect_failure'
EVENT_TYPE_DISCONNECT = 'disconnect'
EVENT_TYPE_RECONNECT = 'reconnect'

# US-432 (BL-016, Option B): the set of KNOWN-MANDATORY Mode-01 PID command
# names that :meth:`ObdConnection.query` is allowed to force-read past
# python-obd's dark-ECU support cache while the engine-confirmed latch is set.
# RPM (PID 0x0C) is mandatory Mode-01 per SAE J1979 -- always supported by any
# OBD-II ECU with the engine running -- so forcing it corrects a false-negative
# (a stale engine-OFF probe result), NOT an unsupported PID.  Deliberately
# NARROW: a blanket force re-exposes the 0x42/0x0B/0x15 garbage the US-199 probe
# silent-skips.  Keyed by python-obd command name (obdlib.commands.RPM.name), or
# the bare parameter string when obdlib is unavailable.
MANDATORY_MODE01_PIDS: frozenset[str] = frozenset({'RPM'})


# ================================================================================
# Enums and Data Classes
# ================================================================================

class ConnectionState(Enum):
    """Connection state enumeration."""
    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    RECONNECTING = 'reconnecting'
    ERROR = 'error'


@dataclass
class ConnectionStatus:
    """
    Connection status information for monitoring.

    Attributes:
        state: Current connection state
        macAddress: Bluetooth MAC address of the dongle
        connected: Whether connection is active
        lastConnectTime: Timestamp of last successful connection
        lastErrorTime: Timestamp of last error
        lastError: Last error message
        retryCount: Number of retry attempts for current connection
        totalConnections: Total successful connections in session
        totalErrors: Total connection errors in session
    """
    state: ConnectionState = ConnectionState.DISCONNECTED
    macAddress: str | None = None
    connected: bool = False
    lastConnectTime: datetime | None = None
    lastErrorTime: datetime | None = None
    lastError: str | None = None
    retryCount: int = 0
    totalConnections: int = 0
    totalErrors: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert status to dictionary for logging/serialization."""
        return {
            'state': self.state.value,
            'macAddress': self.macAddress,
            'connected': self.connected,
            'lastConnectTime': self.lastConnectTime.isoformat() if self.lastConnectTime else None,
            'lastErrorTime': self.lastErrorTime.isoformat() if self.lastErrorTime else None,
            'lastError': self.lastError,
            'retryCount': self.retryCount,
            'totalConnections': self.totalConnections,
            'totalErrors': self.totalErrors
        }


# ================================================================================
# Custom Exceptions
# ================================================================================

class ObdConnectionError(Exception):
    """Base exception for OBD connection errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ObdConnectionTimeoutError(ObdConnectionError):
    """Timeout during OBD connection attempt."""
    pass


class ObdNotAvailableError(ObdConnectionError):
    """python-OBD library not available."""
    pass


class ObdConnectionFailedError(ObdConnectionError):
    """Connection to OBD dongle failed after all retries."""
    pass


class ObdConnectionSupersededError(ObdConnectionError):
    """A query/connect was fenced because a newer connection generation owns
    the port (US-441 epoch fence).

    Raised by :meth:`ObdConnection.query` when the caller passes a
    ``callerGeneration`` that no longer matches the wrapper's current
    generation -- i.e. the caller is a superseded (timed-out, left-running)
    daemon whose I/O must NOT touch the serial port a later owner established.
    """
    pass


# ================================================================================
# OBD Connection Class
# ================================================================================

class ObdConnection:
    """
    Manages Bluetooth OBD-II dongle connections.

    Provides connection management with exponential backoff retry logic,
    connection status monitoring, and database logging of connection events.

    Attributes:
        config: Configuration dictionary with bluetooth settings
        database: Optional ObdDatabase instance for logging
        obd: The underlying OBD connection object (when connected)

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)

        conn = ObdConnection(config, db)
        if conn.connect():
            response = conn.obd.query(obd.commands.RPM)
            print(f"RPM: {response.value}")
        conn.disconnect()
    """

    def __init__(
        self,
        config: dict[str, Any],
        database: Any | None = None,
        obdFactory: Callable[..., Any] | None = None,
        shutdownEvent: threading.Event | None = None,
    ):
        """
        Initialize OBD connection manager.

        Args:
            config: Configuration dictionary with 'bluetooth' section
            database: Optional ObdDatabase instance for logging connection events
            obdFactory: Optional factory for creating OBD connections (for testing)
            shutdownEvent: Optional :class:`threading.Event` used by the retry
                loop to abort early when SIGTERM/SIGINT arrives (US-232 /
                TD-035). When ``set()`` mid-backoff, ``connect()`` returns
                ``False`` within a few ms instead of sleeping the full
                ``retryDelays`` entry (worst case ~90s). Main-thread signal
                handlers installed by the orchestrator set the event.
        """
        self.config = config
        self.database = database
        self._obdFactory = obdFactory
        self.shutdownEvent = shutdownEvent

        # Extract bluetooth configuration
        btConfig = config.get('pi', {}).get('bluetooth', {})
        self.macAddress = btConfig.get('macAddress', '')
        self.retryDelays = btConfig.get('retryDelays', DEFAULT_RETRY_DELAYS)
        self.maxRetries = btConfig.get('maxRetries', len(self.retryDelays))
        self.connectionTimeout = btConfig.get('connectionTimeoutSeconds', DEFAULT_CONNECTION_TIMEOUT)
        self.rfcommDevice = btConfig.get('rfcommDevice', DEFAULT_RFCOMM_DEVICE)
        self.rfcommChannel = btConfig.get('rfcommChannel', DEFAULT_RFCOMM_CHANNEL)

        # Connection state
        self.obd: Any | None = None
        self._status = ConnectionStatus(macAddress=self.macAddress)
        # Set True once this instance performed the rfcomm bind, so
        # disconnect() knows whether to call releaseRfcomm. When the caller
        # configured a literal /dev/rfcommN path (BC), we never bind and
        # must not release.
        self._boundRfcomm: bool = False
        # US-441 (F-117/A-17): THE single serialization lock for every access
        # to the underlying python-obd connection (self.obd).  python-obd wraps
        # one serial port and is NOT thread-safe; two threads driving it at once
        # interleave the ELM327 frames -> "device disconnected while reading" ->
        # 0 rows.  V0.27.1 introduced this as _connectLock but only guarded
        # connect(); the realtime logger reads self.obd.query() DIRECTLY, so its
        # reads raced the orphaned connect/query daemons.  Renamed _ioLock and
        # now held around connect(), query(), disconnect()'s close(), and the
        # supported-PID probe so no two threads ever drive the port concurrently.
        # isConnectInFlight() exposes the lock state to heartbeat probers.
        self._ioLock = threading.Lock()
        # US-441 epoch fence: a monotonically increasing "connection generation".
        # Bumped on every successful connect and every disconnect, so a live
        # connection carries a stable generation between the two.  A bounded
        # timeout daemon captures the generation at spawn (via activeGeneration())
        # and passes it back to connect()/query(); if the generation has moved on
        # by the time the orphaned daemon finally acquires the lock, it is fenced
        # -- it must NOT touch a connection a newer owner now holds.  Guarded by
        # _ioLock.
        self._generation = 0
        # US-199: Supported-PID probe result cached at connection-open time.
        # None until connect() runs the probe. Consumers (ObdDataLogger) use
        # it to silent-skip unsupported PIDs before dispatching a K-line query.
        self.supportedPids: Any | None = None
        # US-432 (BL-016): engine-confirmed latch.  On a cold-boot-key-OFF
        # connect the US-199 probe runs with the engine off, so a dark ECU
        # answers "RPM unsupported" and python-obd caches that -- every later
        # obd.query(RPM) then returns null WITHOUT wire traffic and the drive
        # never starts.  When the orchestrator confirms engine-on (the
        # alternator-active BATTERY_V escalation edge) it sets this latch so
        # query() force-reads the known-mandatory Mode-01 PIDs (RPM) past the
        # stale cache.  Cleared on drive_end and on disconnect().  A plain
        # atomic bool (not guarded by _ioLock) so setting it from the runLoop
        # never blocks behind an in-flight bounded query; query() reads it while
        # already holding _ioLock, and the CPython bool read/write is atomic so
        # the worst case is one un-forced read on the tick the latch flips.
        self._forceMandatoryPids: bool = False

    def getStatus(self) -> ConnectionStatus:
        """
        Get current connection status.

        Returns:
            ConnectionStatus with current state information
        """
        # Update connected state from OBD object if available
        if self.obd is not None:
            self._status.connected = self._isConnected()
            if not self._status.connected and self._status.state != ConnectionState.ERROR:
                # Only reset to DISCONNECTED if not in ERROR state (preserve error state)
                self._status.state = ConnectionState.DISCONNECTED
        return self._status

    def isConnected(self) -> bool:
        """
        Check if OBD connection is active.

        Returns:
            True if connected, False otherwise
        """
        return self._isConnected()

    def isConnectInFlight(self) -> bool:
        """Return True when another thread is currently driving OBD I/O.

        V0.27.1 hotfix observability seam.  Heartbeat callers probe this
        before invoking ``connect()`` themselves so a tick that fires while
        the Sprint 25 leaked ``initial-obd-connect`` daemon is still working
        through its inner 6-attempt-with-backoff schedule logs
        ``outcome=already_in_flight`` and skips, rather than spawning a
        competing connect that collides on ``/dev/rfcomm0``.

        US-441: the probe now reflects the unified ``_ioLock`` -- True while
        ANY serialized OBD operation (connect OR query OR disconnect) is in
        flight, not just connect.  In PENDING state (the only time the
        heartbeat runs) the logger is not querying, so this remains an
        accurate "a connect is already happening" signal for the heartbeat.

        Cheap (no Bluetooth I/O) -- just inspects the local
        :class:`threading.Lock` state.  Always safe to call from any thread.

        Returns:
            True if any thread holds ``self._ioLock``, False otherwise.
        """
        return self._ioLock.locked()

    def _isConnected(self) -> bool:
        """Internal connection check."""
        if self.obd is None:
            return False
        try:
            # Check if OBD connection is active
            return self.obd.is_connected()
        except Exception:
            return False

    def activeGeneration(self) -> int:
        """Return the current connection generation (US-441 epoch fence).

        A bounded timeout daemon (the lifecycle ``_connectInThread`` /
        ``_queryInThread``) captures this at spawn and passes it back to
        :meth:`connect` / :meth:`query`.  If the generation has advanced by the
        time the (possibly orphaned) daemon acquires the lock, its operation is
        fenced.  Cheap (no serial I/O) -- takes ``_ioLock`` only to read the
        counter coherently.

        Returns:
            The current generation integer (starts at 0; +1 per connect-success
            and per disconnect).
        """
        with self._ioLock:
            return self._generation

    def setEngineConfirmedForceMandatory(self, enabled: bool = True) -> None:
        """Arm/clear the engine-confirmed force-mandatory-PID latch (US-432).

        When ``enabled`` is True, subsequent :meth:`query` calls for a
        known-mandatory Mode-01 PID (see :data:`MANDATORY_MODE01_PIDS` -- RPM)
        pass ``force=True`` to python-obd, bypassing the stale engine-OFF
        support cache that a cold-boot-key-OFF connect poisoned.  SCOPED: only
        the mandatory PIDs are forced; every other PID still honors the probe
        (no blanket un-mask -- BL-016 / Refusal Rule 3).

        Called by the orchestrator on the alternator-active escalation edge
        (engine-on confirmed) and cleared on ``drive_end``; :meth:`disconnect`
        also clears it so a fresh connection starts dark.

        Idempotent; logs at INFO only on an actual state change so the poll-rate
        RPM reads do not spam the journal.

        Args:
            enabled: True to force mandatory PIDs; False to return to the
                probe-honoring read path.
        """
        if self._forceMandatoryPids == enabled:
            return
        self._forceMandatoryPids = enabled
        logger.info(
            "Engine-confirmed force-mandatory latch %s -- mandatory Mode-01 "
            "PIDs %s force-read past the dark-ECU support cache "
            "(US-432 / BL-016)",
            'ARMED' if enabled else 'CLEARED',
            'WILL BE' if enabled else 'will NOT be',
        )

    def isForcingMandatoryPids(self) -> bool:
        """Return True when the engine-confirmed force latch is armed (US-432).

        Observability seam for tests + logging; cheap (a bool read, no I/O).
        """
        return self._forceMandatoryPids

    def connect(self, callerGeneration: int | None = None) -> bool:
        """
        Connect to OBD-II dongle with retry logic.

        Attempts to connect using exponential backoff retry delays.
        Logs all connection attempts to database if available.

        Thread safety (V0.27.1 / US-441):
            ``connect()`` runs under ``self._ioLock`` -- THE single lock that
            also guards :meth:`query` and :meth:`disconnect` -- so no two
            threads ever drive the serial port concurrently.  A second caller
            that invokes ``connect()`` while a first is mid-connect blocks on
            the lock; the US-301 heartbeat probes :meth:`isConnectInFlight`
            first and logs ``already_in_flight`` instead of blocking.

        Epoch fence (US-441):
            When ``callerGeneration`` is provided and no longer matches the
            wrapper's current generation, this attempt has been SUPERSEDED (a
            newer connection was established while this -- likely orphaned,
            timed-out -- daemon was blocked).  It refuses to re-open the port
            and returns the current connectedness instead.  Live callers
            (``reconnect()``, the heartbeat) pass no generation and always
            proceed.

        Args:
            callerGeneration: Optional generation token captured via
                :meth:`activeGeneration` before spawning a bounded connect
                daemon.  ``None`` (default) never fences.

        Returns:
            True if connection successful (or already connected on a fenced
            call), False otherwise.

        Raises:
            ObdNotAvailableError: If python-OBD library not available
        """
        return self._performConnect(callerGeneration)

    def query(self, command: Any, callerGeneration: int | None = None) -> Any:
        """Run a single OBD query under the serialization lock (US-441).

        THE serialized read path.  Every caller that would otherwise touch
        ``self.obd.query(...)`` directly -- the realtime logger, the lifecycle
        query daemon -- goes through here so its serial I/O cannot interleave
        with a connect, a disconnect, or another query on the one non-thread-
        safe python-obd connection.  Holding ``_ioLock`` for the whole query is
        what closes the F-117/A-17 "device disconnected while reading" race.

        Args:
            command: python-obd command name or command instance to query.
            callerGeneration: Optional generation token (see
                :meth:`activeGeneration`).  When provided and stale, the read is
                fenced -- an orphaned daemon must not read a connection a newer
                owner holds.  Live readers (the logger) pass ``None`` and are
                never fenced; they always read the current connection.

        Returns:
            The python-obd response object.

        Raises:
            ObdConnectionSupersededError: If ``callerGeneration`` is stale.
            ObdConnectionError: If there is no live OBD interface (obd is None).
        """
        with self._ioLock:
            if callerGeneration is not None and callerGeneration != self._generation:
                logger.warning(
                    "query() fenced -- caller generation %d superseded by "
                    "current %d; dropping orphaned read (US-441 epoch fence)",
                    callerGeneration,
                    self._generation,
                )
                raise ObdConnectionSupersededError(
                    "OBD query dropped: caller generation superseded by a "
                    "newer connection",
                    details={
                        'callerGeneration': callerGeneration,
                        'currentGeneration': self._generation,
                    },
                )
            if self.obd is None:
                raise ObdConnectionError(
                    "Cannot query: OBD interface is not connected (obd is None)"
                )
            # US-432 (BL-016): while the engine-confirmed latch is armed, force
            # known-mandatory Mode-01 PIDs (RPM) past python-obd's dark-ECU
            # support cache.  SCOPED to MANDATORY_MODE01_PIDS -- never blanket.
            if self._shouldForceMandatory(command):
                logger.debug(
                    "query() force-reading mandatory Mode-01 PID past the "
                    "dark-ECU support cache (US-432 engine-confirmed latch)"
                )
                return self.obd.query(command, force=True)
            return self.obd.query(command)

    def _shouldForceMandatory(self, command: Any) -> bool:
        """Return True when ``command`` must be force-read (US-432).

        True only when the engine-confirmed latch is armed AND ``command``
        resolves to a name in :data:`MANDATORY_MODE01_PIDS`.  Resolves the name
        from a python-obd command object (``.name``) or a bare string (the
        obdlib-absent fallback path in ``ObdDataLogger._getObdCommand``).

        Args:
            command: The python-obd command object or name being queried.

        Returns:
            True to pass ``force=True`` to the underlying query.
        """
        if not self._forceMandatoryPids:
            return False
        name = getattr(command, 'name', None)
        if name is None and isinstance(command, str):
            name = command
        return name in MANDATORY_MODE01_PIDS

    def _performConnect(self, callerGeneration: int | None = None) -> bool:
        """Internal connect implementation with PER-ATTEMPT serialization.

        Atlas A-17 fix (2026-07-27, "capture-dead-since-0703"): ``_ioLock`` is
        acquired PER ATTEMPT around only the discrete port work (resolve +
        ``obd.OBD(...)`` construction + probe) and RELEASED across the backoff
        sleep.  The US-441 regression held the lock for the WHOLE multi-attempt
        loop (backoff included), so a timed-out-but-still-running connect daemon
        monopolized the port lifecycle -- :meth:`disconnect` could never acquire
        the lock to free ``/dev/rfcommN``, and each retry re-opened the port over
        an unclosed partial handle -> "device disconnected or multiple access on
        port?" -> 0 rows for 24 days.

        Fix A: lock released across backoff (below) so ``disconnect()`` /
        ``query()`` can interleave.  Fix B: :meth:`_closePartialConnection`
        closes the partial ``obd`` on every failed attempt before the next open.

        The US-441 epoch fence is re-checked at the top of EACH attempt (under
        the lock) -- because the lock is now free across backoff, a newer
        connection may have won meanwhile, and a superseded daemon must fence
        rather than re-open the port.  Live callers (``callerGeneration=None``)
        are never fenced.
        """
        if not OBD_AVAILABLE and self._obdFactory is None:
            error = "python-OBD library not available"
            self._logConnectionEvent(EVENT_TYPE_CONNECT_FAILURE, success=False, errorMessage=error)
            raise ObdNotAvailableError(error)

        self._status.state = ConnectionState.CONNECTING
        self._status.retryCount = 0

        logger.info(f"Connecting to OBD-II dongle | mac={self.macAddress}")

        # Attempt connection with retries.  The lock is taken PER ATTEMPT (around
        # the port work only) and released across the backoff (fix A).
        for attempt in range(self.maxRetries + 1):
            # US-232 / TD-035: honor an already-set shutdown event before
            # even dispatching the next attempt. Covers the pre-set path
            # (SIGTERM arrived while we were preparing for the next retry).
            if self.shutdownEvent is not None and self.shutdownEvent.is_set():
                logger.info(
                    "Connect retry loop exiting -- shutdown signaled "
                    "before attempt %d",
                    attempt + 1,
                )
                self._status.state = ConnectionState.DISCONNECTED
                return False

            attemptFailed = False
            with self._ioLock:
                # US-441 epoch fence, re-checked each attempt: because the lock
                # is released across backoff, a newer connection may have won in
                # the meantime -- a superseded (orphaned) daemon must fence here
                # and NOT re-open the port a newer owner now holds.
                if callerGeneration is not None and callerGeneration != self._generation:
                    logger.warning(
                        "connect() fenced -- caller generation %d superseded by "
                        "current %d; a newer connection owns the port, not "
                        "re-opening (US-441 epoch fence)",
                        callerGeneration,
                        self._generation,
                    )
                    return self._isConnected()

                try:
                    self._logConnectionEvent(
                        EVENT_TYPE_CONNECT_ATTEMPT,
                        retryCount=attempt
                    )

                    # Resolve MAC -> /dev/rfcommN if needed. When the caller
                    # passed a literal device path (or left config empty) we
                    # pass it through unchanged for backwards compatibility.
                    serialPort = self._resolvePort()

                    # Create OBD connection
                    if self._obdFactory is not None:
                        self.obd = self._obdFactory(serialPort, self.connectionTimeout)
                    else:
                        self.obd = self._createObdConnection(serialPort)

                    # Check if connection was successful
                    if self._isConnected():
                        self._status.state = ConnectionState.CONNECTED
                        self._status.connected = True
                        self._status.lastConnectTime = datetime.now()
                        self._status.totalConnections += 1
                        self._status.retryCount = attempt

                        # US-441 epoch fence: a new live connection = a new
                        # generation.  Runs under the held _ioLock so the bump is
                        # atomic w.r.t. activeGeneration()/query().
                        self._generation += 1

                        # US-199: one-shot supported-PID probe so the realtime
                        # logger can silent-skip unsupported PIDs (0x42/0x0B/0x15
                        # candidates on 2G). Best-effort — probe failure never
                        # fails the connection itself.
                        self._runSupportedPidProbe()

                        self._logConnectionEvent(
                            EVENT_TYPE_CONNECT_SUCCESS,
                            success=True,
                            retryCount=attempt
                        )

                        logger.info(f"Connected to OBD-II dongle | mac={self.macAddress} | attempts={attempt + 1}")
                        return True
                    else:
                        # Connection object created but not connected
                        raise ObdConnectionError("OBD connection not active after creation")

                except Exception as e:
                    attemptFailed = True
                    self._status.lastError = str(e)
                    self._status.lastErrorTime = datetime.now()
                    self._status.totalErrors += 1

                    # Fix B: close the partially-opened obd (and the serial fd it
                    # opened on /dev/rfcommN) BEFORE the next attempt re-opens the
                    # same port -- otherwise pyserial rejects the second open with
                    # "device disconnected or multiple access on port?".  Runs
                    # under the held _ioLock.
                    self._closePartialConnection()

                    # US-512: and drop the rfcomm BINDING too, so the next
                    # attempt re-binds instead of taking bindRfcomm's
                    # already-bound short-circuit.  Closing the fd is not
                    # enough: the kernel bind entry survives the dead link, so
                    # without this the retry re-opens the identical dead tty --
                    # BL-025's stale-rfcomm-retry-forever.  This is the ONLY
                    # place the US-338 post-failure heartbeat gets a transport
                    # reset, because it drives connect() and never reconnect().
                    self._releaseRfcommBinding()

                    logger.warning(
                        f"Connection attempt {attempt + 1}/{self.maxRetries + 1} failed | "
                        f"mac={self.macAddress} | error={e}"
                    )

                    if attempt >= self.maxRetries:
                        # All retries exhausted
                        self._status.state = ConnectionState.ERROR
                        self._logConnectionEvent(
                            EVENT_TYPE_CONNECT_FAILURE,
                            success=False,
                            errorMessage=str(e),
                            retryCount=attempt
                        )
                        logger.error(
                            f"Failed to connect after {self.maxRetries + 1} attempts | "
                            f"mac={self.macAddress}"
                        )
            # --- _ioLock released here (fix A) ---

            # Backoff OUTSIDE the lock so disconnect()/query() can acquire it and
            # free the port while this (possibly orphaned) connect waits.
            if attemptFailed and attempt < self.maxRetries:
                # Get delay for this attempt (0 if empty, else clamp to last).
                if not self.retryDelays:
                    delay = 0
                else:
                    delayIndex = min(attempt, len(self.retryDelays) - 1)
                    delay = self.retryDelays[delayIndex]

                if delay > 0:
                    logger.info(f"Retrying in {delay}s...")
                    # US-232 / TD-035: use event.wait() when a shutdown event is
                    # plumbed in so a signal handler set() wakes us mid-backoff;
                    # else legacy time.sleep for callers that didn't opt in.
                    if self.shutdownEvent is not None:
                        if self.shutdownEvent.wait(timeout=delay):
                            logger.info(
                                "Connect retry loop exiting -- shutdown "
                                "signaled during backoff (attempt %d/%d)",
                                attempt + 1,
                                self.maxRetries + 1,
                            )
                            self._status.state = ConnectionState.DISCONNECTED
                            return False
                    else:
                        time.sleep(delay)
                self._status.retryCount = attempt + 1

        return False

    def _closePartialConnection(self) -> None:
        """Close a partially-opened ``obd`` after a FAILED connect attempt (B).

        A python-obd ``OBD()`` constructor that fails the ELM327 handshake can
        leave the serial fd on ``/dev/rfcommN`` open; the retry loop would then
        re-open the same port and pyserial rejects the second open with "device
        reports readiness to read but returned no data (device disconnected or
        multiple access on port?)".  Closing the partial handle before the next
        attempt (and before returning on final failure) prevents that
        self-inflicted collision -- the A-17 capture-dead-since-0703 regression.

        MUST be called with ``self._ioLock`` held (it touches ``self.obd``).
        Never raises -- cleanup must not mask the original connect error.
        """
        if self.obd is None:
            return
        try:
            self.obd.close()
        except Exception as e:  # noqa: BLE001 -- cleanup must never mask the real error
            logger.warning("Partial-connection close after failed attempt failed: %s", e)
        finally:
            self.obd = None

    def _runSupportedPidProbe(self) -> None:
        """Populate :attr:`supportedPids` from python-obd's auto-probed commands.

        Never raises — probe failures fall back to always-supported so the
        poll loop still dispatches every configured PID (null-response
        silent-skip remains the fallback safety net).
        """
        try:
            # Imported lazily to avoid coupling ObdConnection to pid_probe at
            # module import time (keeps the legacy import graph clean).
            from .pid_probe import SupportedPidSet, probeSupportedPids

            probed = probeSupportedPids(self)
            self.supportedPids = probed
            logger.info(
                "Supported-PID probe | discovered=%d | fallbackAllowAll=%s",
                len(probed),
                probed.fallbackAllowAll,
            )
        except Exception as exc:  # noqa: BLE001
            from .pid_probe import SupportedPidSet
            logger.warning("Supported-PID probe failed (%s) — falling back to always-supported", exc)
            self.supportedPids = SupportedPidSet.alwaysSupported()

    def _releaseRfcommBinding(self) -> bool:
        """Drop the rfcomm binding for a MAC-configured port (US-512).

        Keyed on "the configured port is a MAC", NOT on ``self._boundRfcomm``.
        That distinction is the whole fix for the restart-proof form of
        BL-025: a predecessor process that was SIGKILLed (or crashed) never
        ran :meth:`disconnect`, so its bind entry is still in the kernel table
        when we start.  We did not create it, so ``_boundRfcomm`` is False and
        a release keyed on our own bookkeeping skips -- then ``bindRfcomm``
        short-circuits on the inherited entry and we open the predecessor's
        dead tty.  Restarting the service does not clear that; only releasing
        an entry we did not make does.

        Path-style configuration (a literal ``/dev/rfcommN``) is exempt: we
        never bind it, and something else -- ``connect_obdlink.sh``, an
        operator -- owns it.

        MUST be called with ``self._ioLock`` held.  Never raises: this runs on
        recovery paths where an exception would surface as FATAL and bounce
        the service.

        Returns:
            True when a release was issued without error.
        """
        if not bluetooth_helper.isMacAddress(self.macAddress):
            return False
        try:
            bluetooth_helper.releaseRfcomm(device=self.rfcommDevice)
        except Exception as exc:  # noqa: BLE001 -- recovery cleanup never raises
            logger.warning(
                "rfcomm release during transport reset failed | device=%d | %s",
                self.rfcommDevice,
                exc,
            )
            return False
        finally:
            self._boundRfcomm = False
        return True

    def resetTransport(self) -> str | None:
        """Spool's transport reset: disconnect -> releaseRfcomm -> re-bind.

        The recovery primitive for a dropped BT link.  Re-opening
        ``obd.OBD()`` on the surviving ``/dev/rfcommN`` cannot work -- the
        binding is a kernel table entry that outlived the ACL link, so the
        device node is present and dead.  This tears the transport down to the
        binding and builds a genuinely new one, which is what the next
        :meth:`connect` (and the reconnect loop's reachability probe) needs in
        order to answer honestly.

        Deliberately leaves the transport BOUND rather than released.  The
        US-211 reconnect loop probes
        :func:`bluetooth_helper.isRfcommReachable`, which requires the binding
        to EXIST -- so a recovery path that only released would leave that
        probe permanently False and the loop waiting forever for a state its
        own teardown had made unreachable.

        Never raises, and never touches the radio (no rfkill / ``hciconfig
        down`` / ``bluetoothctl power off``): systemd-rfkill persists radio
        state across a reboot, which is how the 07-03 soft-block became sticky.

        Returns:
            The freshly-bound ``/dev/rfcommN`` path, or ``None`` when the port
            is path-style (someone else owns the bind) or the re-bind failed
            (no transport -- an honest answer the caller can act on).
        """
        self.disconnect()

        if not bluetooth_helper.isMacAddress(self.macAddress):
            logger.debug(
                "resetTransport: port %r is path-style -- not ours to re-bind",
                self.macAddress,
            )
            return None

        with self._ioLock:
            try:
                path = bluetooth_helper.resetRfcommBinding(
                    macAddress=self.macAddress,
                    device=self.rfcommDevice,
                    channel=self.rfcommChannel,
                )
            except Exception as exc:  # noqa: BLE001 -- recovery must not raise
                logger.warning(
                    "Transport reset could not re-bind rfcomm | mac=%s | %s",
                    self.macAddress,
                    exc,
                )
                self._boundRfcomm = False
                return None
            self._boundRfcomm = True

        logger.info(
            "Transport RESET complete | mac=%s port=%s -- next open gets a "
            "fresh binding, not the dead one (US-512 / BL-025)",
            self.macAddress,
            path,
        )
        return path

    def _assureDurableBond(self, macAddress: str) -> None:
        """Restore a lost ``Trusted`` flag before binding (US-512).

        ``scripts/pair_obdlink.sh`` writes Paired+Bonded+Trusted at pair time
        and verifies all three; nothing at runtime ever read them back.  A bond
        that loses ``Trusted`` still reports as paired, but bluez refuses the
        unattended reconnect -- so the symptom is a dead link whose only
        apparent remedy is a manual re-pair, which needs the dongle powered,
        i.e. the engine running.  Trust is a local bluez flag and IS repairable
        here; pairing is not, so an absent bond record is reported loudly with
        the actual remedy rather than papered over.

        US-545 (A-18): a bond bluez has actually DROPPED is no longer just a
        warning.  This runs on every connect -- so it is also the reconnect
        path -- and now delegates to the bounded self-heal.  It delegates
        rather than heals in-place because the heal must stop this very
        service first (never pair while the logger holds the port); see
        :mod:`~src.pi.obdii.bond_self_heal`.

        Best-effort by construction: never raises, and a failure here must
        never fail a connect attempt that would otherwise have worked.

        Args:
            macAddress: The configured dongle MAC.
        """
        try:
            state = bluetooth_helper.ensureTrusted(macAddress)
        except Exception as exc:  # noqa: BLE001 -- advisory check only
            logger.debug("Bond assurance skipped (%s)", exc)
            return

        if bluetooth_helper.isDurableBond(state):
            return

        # US-545: an unreadable bluez produces the SAME all-False state as a
        # genuinely cleared bond.  Classify against the adapter reading before
        # acting, or a slow-to-start bluetooth.service would have us stopping
        # capture and re-pairing the dongle in response to our own blindness.
        try:
            healer = bond_self_heal.BondSelfHealer(macAddress)
            verdict = bond_self_heal.classifyBond(
                state, adapterPresent=healer.readAdapterPowered() is not None
            )
        except Exception as exc:  # noqa: BLE001 -- advisory check only
            logger.debug("Bond verdict unavailable (%s)", exc)
            return

        if verdict is bond_self_heal.BondVerdict.UNKNOWN:
            logger.debug(
                "Bond for %s could not be classified (bluez unreadable) -- "
                "not requesting a self-heal off a blind reading",
                macAddress,
            )
            return

        logger.warning(
            "Bond for %s is NOT durable (known=%s paired=%s bonded=%s "
            "trusted=%s) -- bluez will not reconnect it unattended. Run "
            "scripts/pair_obdlink.sh %s with the dongle powered (engine "
            "on) and in pair mode.",
            macAddress,
            state.known,
            state.paired,
            state.bonded,
            state.trusted,
            macAddress,
        )

        try:
            bond_self_heal.requestBondSelfHeal(macAddress)
        except Exception as exc:  # noqa: BLE001 -- must never fail a connect
            logger.debug("Self-heal request failed (%s)", exc)

    def _resolvePort(self) -> str | None:
        """
        Resolve the configured port value to a serial device path.

        If ``self.macAddress`` looks like a Bluetooth MAC, idempotently bind
        it via rfcomm and return the resulting ``/dev/rfcommN`` path. If it
        already looks like a path (or is empty), return it unchanged.

        Returns:
            The serial port path ``obd.OBD(portstr=...)`` should open,
            or ``None`` when no port is configured at all.

        Raises:
            ObdConnectionError: On rfcomm bind failure; stderr is surfaced.
        """
        port = self.macAddress
        if not port:
            return None

        if not bluetooth_helper.isMacAddress(port):
            # Literal path (e.g. /dev/rfcomm0) — pass through unchanged.
            return port

        # US-512: assure the bluez bond before binding.  A binding over a
        # non-trusted bond binds fine and then refuses to carry traffic.
        self._assureDurableBond(port)

        try:
            resolved = bluetooth_helper.bindRfcomm(
                macAddress=port,
                device=self.rfcommDevice,
                channel=self.rfcommChannel,
            )
        except bluetooth_helper.BluetoothHelperError as exc:
            # Surface stderr + exact invocation into the warning log per invariant.
            logger.warning("rfcomm bind failed | %s", exc)
            raise ObdConnectionError(
                f"Failed to bind rfcomm for MAC {port}: {exc}",
                details={'macAddress': port, 'error': str(exc)},
            ) from exc

        self._boundRfcomm = True
        return resolved

    def _createObdConnection(self, serialPort: str | None = None) -> Any:
        """
        Create the underlying OBD connection.

        Args:
            serialPort: Pre-resolved serial device path (e.g. /dev/rfcomm0).
                        Caller is expected to have run :meth:`_resolvePort`.
                        When ``None`` we fall back to the configured port.

        Returns:
            obd.OBD connection object

        Raises:
            ObdConnectionError: If connection creation fails
        """
        if obdlib is None:
            raise ObdNotAvailableError("python-OBD library not available")

        portName = serialPort if serialPort is not None else (self.macAddress or None)

        try:
            # fast=False allows for more compatible but slower connection
            # timeout controls command timeout
            connection = obdlib.OBD(
                portstr=portName,
                fast=False,
                timeout=self.connectionTimeout
            )

            return connection

        except Exception as e:
            raise ObdConnectionError(
                f"Failed to create OBD connection: {e}",
                details={'macAddress': self.macAddress, 'portstr': portName, 'error': str(e)}
            ) from e

    def disconnect(self) -> None:
        """
        Disconnect from OBD-II dongle.

        Cleanly closes the OBD connection and logs the event.

        US-441: the close + generation bump run under ``self._ioLock`` so a
        disconnect never interleaves with an in-flight query, and any daemon
        holding the pre-disconnect generation is fenced from the next
        connection.  The DB event log is written outside the lock (different
        resource; no need to hold the serial lock for a SQLite write).
        """
        with self._ioLock:
            if self.obd is not None:
                try:
                    logger.info(f"Disconnecting from OBD-II dongle | mac={self.macAddress}")
                    self.obd.close()
                except Exception as e:
                    logger.warning(f"Error during disconnect: {e}")
                finally:
                    self.obd = None

            # US-441 epoch fence: tearing down the connection advances the
            # generation so a superseded connect/query daemon bound to the old
            # connection is fenced when it finally wakes.
            self._generation += 1

            # US-432 (BL-016): clear the engine-confirmed force latch on
            # teardown.  The next connect() re-runs the US-199 probe (dark ECU
            # again on a cold-boot connect), so a stale force must not carry
            # across connections -- the escalation re-arms it when engine-on is
            # re-confirmed.
            self._forceMandatoryPids = False

            # Release the rfcomm device we bound so the next connect() is
            # idempotent and the kernel slot is free for reuse. Path-style BC
            # (self._boundRfcomm is False) skips this — someone else owns the bind.
            if self._boundRfcomm:
                try:
                    bluetooth_helper.releaseRfcomm(device=self.rfcommDevice)
                except bluetooth_helper.BluetoothHelperError as exc:
                    logger.warning("rfcomm release during disconnect failed | %s", exc)
                finally:
                    self._boundRfcomm = False

        self._status.state = ConnectionState.DISCONNECTED
        self._status.connected = False

        self._logConnectionEvent(EVENT_TYPE_DISCONNECT)

    def reconnect(self) -> bool:
        """
        Reconnect to OBD-II dongle.

        US-512: resets the TRANSPORT first (disconnect -> releaseRfcomm ->
        re-bind) rather than just disconnecting.  ``disconnect()`` alone only
        releases a binding *this instance* created, so a binding inherited
        from a killed predecessor -- or left behind by a connect that failed
        before ``_boundRfcomm`` was set -- survives, ``bindRfcomm``
        short-circuits on it, and the "reconnect" re-opens the same dead tty.

        Returns:
            True if reconnection successful, False otherwise
        """
        logger.info("Attempting reconnection to OBD-II dongle")
        self._status.state = ConnectionState.RECONNECTING

        self._logConnectionEvent(EVENT_TYPE_RECONNECT)

        self.resetTransport()
        return self.connect()

    def _logConnectionEvent(
        self,
        eventType: str,
        success: bool = False,
        errorMessage: str | None = None,
        retryCount: int = 0
    ) -> None:
        """
        Log connection event to database.

        Args:
            eventType: Type of connection event
            success: Whether the event was successful
            errorMessage: Error message if failed
            retryCount: Number of retry attempts
        """
        if self.database is None:
            return

        # US-340b: skip repeated "still trying" rows for the same mac.
        # Shared module-level dedup so this writer + connection_logger.py
        # writer see the same "last logged event_type" state.
        from src.pi.data.connection_logger import shouldSuppressAsRepeat
        if shouldSuppressAsRepeat(self.macAddress, eventType):
            return

        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO connection_log
                    (event_type, mac_address, success, error_message, retry_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (eventType, self.macAddress, 1 if success else 0, errorMessage, retryCount)
                )
        except Exception as e:
            logger.warning(f"Failed to log connection event: {e}")


# ================================================================================
# Helper Functions
# ================================================================================

def createConnectionFromConfig(
    config: dict[str, Any],
    database: Any | None = None,
    simulateFlag: bool = False,
    shutdownEvent: threading.Event | None = None,
) -> Any:
    """
    Create an OBD connection instance from configuration.

    When simulation mode is enabled (via config or --simulate flag), returns
    a SimulatedObdConnection. Otherwise returns a real ObdConnection.

    Args:
        config: Configuration dictionary with 'bluetooth' section
        database: Optional ObdDatabase instance for logging
        simulateFlag: True if --simulate CLI flag was passed (overrides config)
        shutdownEvent: Optional :class:`threading.Event` plumbed into the real
            :class:`ObdConnection` so its retry-loop backoff is
            interruptible by a SIGTERM-set event (US-232 / TD-035). Ignored
            by the SimulatedObdConnection path (no retries to interrupt).

    Returns:
        ObdConnection or SimulatedObdConnection based on simulation mode

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)

        # Real connection
        conn = createConnectionFromConfig(config, db)

        # Simulated connection (via flag)
        simConn = createConnectionFromConfig(config, db, simulateFlag=True)
    """
    # Import here to avoid circular imports
    from .config import isSimulatorEnabled

    # Check if simulation mode is enabled
    if isSimulatorEnabled(config, simulateFlag):
        from .config import getSimulatorConfig
        from .simulator import (
            SimulatedObdConnection,
            loadProfile,
        )

        logger.info("Creating SimulatedObdConnection (simulation mode enabled)")

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

        return SimulatedObdConnection(
            profile=profile,
            connectionDelaySeconds=simConfig.get('connectionDelaySeconds', 2.0),
            config=config,
            database=database
        )

    # Return real connection
    logger.info("Creating real ObdConnection")
    return ObdConnection(config, database, shutdownEvent=shutdownEvent)


def isObdAvailable() -> bool:
    """
    Check if python-OBD library is available.

    Returns:
        True if library is installed and importable
    """
    return OBD_AVAILABLE
