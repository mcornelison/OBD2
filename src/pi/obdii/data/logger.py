################################################################################
# File Name: logger.py
# Purpose/Description: ObdDataLogger class for OBD-II data logging operations
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-007 (data module refactor)
# 2026-04-19    | Rex (US-203) | TD-027 sweep: realtime_data INSERT routes the
#                               timestamp through utcIsoNow so rows are
#                               canonical ISO-8601 UTC.  In-memory reading.time
#                               keeps its original datetime value for stats.
# 2026-04-19    | Rex (US-199) | Spool Data v2 Story 1: queryParameter now
#                               consults PARAMETER_DECODERS for new
#                               parameter_names (FUEL_SYSTEM_STATUS, MIL_ON,
#                               DTC_COUNT, RUNTIME_SEC, BAROMETRIC_KPA,
#                               BATTERY_V, O2_BANK1_SENSOR2_V). Supported-PID
#                               probe (via connection.supportedPids) gates
#                               Mode 01 queries; adapter commands bypass the
#                               probe. LoggedReading.unit stores the
#                               enum textLabel when the decoder emits one.
# 2026-04-21    | Rex (US-212) | Accept explicit dataSource in __init__,
#                               auto-derive from connection.isSimulated
#                               when not passed, and persist the tag in
#                               realtime_data INSERTs instead of relying
#                               on the schema DEFAULT.  Closes the
#                               simulator-tags-as-real hygiene bug.
# ================================================================================
################################################################################
"""
OBD-II data logger class for parameter querying and storage.

Provides:
- Parameter querying via OBD-II connection
- Data logging to SQLite database with timestamps
- Statistics tracking for logged readings

Usage:
    from src.obd.data.logger import ObdDataLogger
    from src.obd.data.types import LoggedReading

    # Create logger with connection and database
    logger = ObdDataLogger(obdConnection, database, profileId='daily')

    # Query and log a parameter
    reading = logger.queryAndLogParameter('RPM')
    print(f"RPM: {reading.value} {reading.unit}")
"""

import logging
import threading
from datetime import datetime
from typing import Any

from common.time.helper import utcIsoNow
from pi.obdii.decoders import PARAMETER_DECODERS, DecodedReading, ParameterDecoderEntry

from ..data_source import DATA_SOURCE_DEFAULT, DATA_SOURCE_VALUES
from ..drive_id import getCurrentDriveId
from .exceptions import DataLoggerError, ParameterNotSupportedError, ParameterReadError
from .types import LoggedReading

logger = logging.getLogger(__name__)


# OBD library import with fallback for environments where it's not available
try:
    import obd as obdlib
    OBD_AVAILABLE = True
except ImportError:
    obdlib = None  # type: ignore
    OBD_AVAILABLE = False


def _resolveDataSource(
    connection: Any,
    explicit: str | None,
) -> str:
    """Return the data_source tag rows from ``connection`` should carry.

    Explicit caller overrides win.  Otherwise, a connection that
    self-identifies as simulated (``isSimulated=True``) yields
    ``'physics_sim'``; every other shape -- including real OBD,
    mocks without the attribute, and None -- falls back to
    :data:`DATA_SOURCE_DEFAULT`.
    """
    if explicit is not None:
        if explicit not in DATA_SOURCE_VALUES:
            raise ValueError(
                f"invalid data_source {explicit!r}; "
                f"must be one of {DATA_SOURCE_VALUES}"
            )
        return explicit
    if getattr(connection, "isSimulated", False):
        return "physics_sim"
    return DATA_SOURCE_DEFAULT


class ObdDataLogger:
    """
    Manages OBD-II data logging operations.

    Provides parameter querying, database storage, and statistics tracking
    for OBD-II data acquisition.

    Attributes:
        connection: ObdConnection instance for communicating with the dongle
        database: ObdDatabase instance for data storage
        profileId: Optional profile ID for data grouping

    Example:
        # Setup
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = ObdConnection(config, db)
        conn.connect()

        # Create logger and log data
        logger = ObdDataLogger(conn, db, profileId='daily')
        reading = logger.queryAndLogParameter('RPM')
        print(f"Logged RPM: {reading.value}")

        # Check stats
        stats = logger.getStats()
        print(f"Total readings: {stats['totalReadings']}")
    """

    def __init__(
        self,
        connection: Any,
        database: Any,
        profileId: str | None = None,
        dataSource: str | None = None,
    ):
        """
        Initialize the data logger.

        Args:
            connection: ObdConnection instance for OBD-II communication.
            database: ObdDatabase instance for data storage.
            profileId: Optional profile ID for associating logged data.
            dataSource: Tag stamped on every row written by this logger.
                Must be one of :data:`DATA_SOURCE_VALUES`.  When omitted
                (the default), the tag is derived from the connection
                shape: ``'physics_sim'`` when
                ``getattr(connection, 'isSimulated', False)`` is true,
                otherwise :data:`DATA_SOURCE_DEFAULT` (``'real'``).
                US-212: this override is the call-site fix for the
                simulator-feeds-live-writer hygiene bug.

        Raises:
            ValueError: If ``dataSource`` is not in
                :data:`DATA_SOURCE_VALUES`.
        """
        self.connection = connection
        self.database = database
        self.profileId = profileId
        self.dataSource = _resolveDataSource(connection, dataSource)

        # Statistics tracking
        self._totalReadings = 0
        self._totalLogged = 0
        self._lastReadingTime: datetime | None = None
        self._readErrors = 0

        # US-206: most-recent-per-parameter cache for drive-start
        # metadata capture (SummaryRecorder reads this on _startDrive).
        # Populated on every successful queryParameter -- no new polls.
        # Lock covers read + write so a late polling thread can't hand
        # the recorder a torn dict.
        self._latestReadings: dict[str, float] = {}
        self._latestReadingsLock = threading.Lock()

    def queryParameter(self, parameterName: str) -> LoggedReading:
        """
        Query a single parameter from the OBD-II interface.

        For Spool Data v2 parameter_names (see PARAMETER_DECODERS registry)
        this routes through the v2 decoder path: python-obd command name
        differs from the Pi-facing parameter_name, and the decoder
        normalizes multi-field or enum-style responses into a single
        :class:`LoggedReading`.

        Args:
            parameterName: Name of the OBD-II parameter (e.g., 'RPM',
                'FUEL_SYSTEM_STATUS', 'BATTERY_V')

        Returns:
            LoggedReading with the parameter value (and enum textLabel in
            :attr:`LoggedReading.unit` for enum-style parameters like
            FUEL_SYSTEM_STATUS / MIL_ON).

        Raises:
            DataLoggerError: If not connected to OBD-II
            ParameterReadError: If parameter cannot be read
            ParameterNotSupportedError: If parameter is not supported (probe
                result shows the PID is not in the ECU's Mode 01 bitmap)
        """
        if not self.connection.isConnected():
            raise DataLoggerError(
                "Not connected to OBD-II",
                details={'parameter': parameterName}
            )

        decoderEntry = PARAMETER_DECODERS.get(parameterName)
        if decoderEntry is not None:
            self._assertPidSupported(decoderEntry)
            return self._queryViaDecoder(parameterName, decoderEntry)

        try:
            # Get the OBD command for this parameter
            cmd = self._getObdCommand(parameterName)

            # Query the parameter - cmd may be the command object or the name
            response = self.connection.obd.query(cmd)

            # Check if response is valid
            if response.is_null():
                self._readErrors += 1
                raise ParameterReadError(
                    f"Parameter '{parameterName}' returned null response",
                    details={'parameter': parameterName}
                )

            # Extract value and unit
            value = self._extractValue(response)
            unit = self._extractUnit(response)

            # Create reading
            timestamp = datetime.now()
            reading = LoggedReading(
                parameterName=parameterName,
                value=value,
                unit=unit,
                timestamp=timestamp,
                profileId=self.profileId
            )

            # Update stats
            self._totalReadings += 1
            self._lastReadingTime = timestamp
            self._recordLatest(parameterName, value)

            logger.debug(
                f"Read parameter | name={parameterName} | value={value} | unit={unit}"
            )

            return reading

        except (ParameterReadError, ParameterNotSupportedError):
            raise
        except Exception as e:
            self._readErrors += 1
            raise ParameterReadError(
                f"Failed to read parameter '{parameterName}': {e}",
                details={'parameter': parameterName, 'error': str(e)}
            ) from e

    def _assertPidSupported(self, entry: ParameterDecoderEntry) -> None:
        """Raise ParameterNotSupportedError when the probe says the PID is unsupported.

        Adapter-level commands (entry.pidCode is None) always proceed.
        When the connection has no supportedPids cache (tests, legacy
        ObdConnection instances), treat as 'supported' and let null-response
        handling provide silent-skip semantics.
        """
        if entry.pidCode is None:
            return
        supportedPids = getattr(self.connection, "supportedPids", None)
        if supportedPids is None:
            return
        if not supportedPids.isSupported(entry.pidCode):
            raise ParameterNotSupportedError(
                f"Parameter '{entry.parameterName}' (PID {entry.pidCode}) "
                "not in Mode 01 support bitmap for this ECU",
                details={'parameter': entry.parameterName, 'pid': entry.pidCode},
            )

    def _queryViaDecoder(
        self, parameterName: str, entry: ParameterDecoderEntry
    ) -> LoggedReading:
        """Run a Spool v2 decoder and wrap its output as a LoggedReading."""
        try:
            cmd = self._getObdCommand(entry.obdCommand)
            response = self.connection.obd.query(cmd)

            if response is None or (hasattr(response, "is_null") and response.is_null()):
                self._readErrors += 1
                raise ParameterReadError(
                    f"Parameter '{parameterName}' returned null response",
                    details={'parameter': parameterName, 'pid': entry.pidCode},
                )

            decoded: DecodedReading = entry.decoder(response)
            timestamp = datetime.now()
            unit = decoded.textLabel if decoded.textLabel is not None else decoded.unit
            reading = LoggedReading(
                parameterName=parameterName,
                value=decoded.valueNumeric,
                unit=unit,
                timestamp=timestamp,
                profileId=self.profileId,
            )

            self._totalReadings += 1
            self._lastReadingTime = timestamp
            self._recordLatest(parameterName, decoded.valueNumeric)
            logger.debug(
                "Read v2 parameter | name=%s | pid=%s | value=%s | unit=%s",
                parameterName, entry.pidCode, decoded.valueNumeric, unit,
            )
            return reading
        except (ParameterReadError, ParameterNotSupportedError):
            raise
        except Exception as e:
            self._readErrors += 1
            raise ParameterReadError(
                f"Failed to read parameter '{parameterName}' via v2 decoder: {e}",
                details={'parameter': parameterName, 'pid': entry.pidCode, 'error': str(e)},
            ) from e

    def logReading(self, reading: LoggedReading) -> bool:
        """
        Log a reading to the database.

        Args:
            reading: LoggedReading to store

        Returns:
            True if logged successfully

        Raises:
            DataLoggerError: If database operation fails
        """
        try:
            # Use profile from reading or fall back to logger's profile
            profileId = reading.profileId or self.profileId

            with self.database.connect() as conn:
                cursor = conn.cursor()
                # TD-027 / US-203: canonical ISO-8601 UTC via the shared helper.
                # reading.timestamp may be naive local-time (upstream creates
                # it via naive datetime.now() in realtime.py:399 and in
                # queryParameter above); capture rows must be UTC canonical.
                # US-200: stamp the active drive_id (or NULL if no drive).
                # US-212: pass self.dataSource explicitly so simulator runs
                # land as 'physics_sim' instead of inheriting the live-path
                # DEFAULT 'real'.
                cursor.execute(
                    """
                    INSERT INTO realtime_data
                    (timestamp, parameter_name, value, unit, profile_id,
                     drive_id, data_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utcIsoNow(),
                        reading.parameterName,
                        reading.value,
                        reading.unit,
                        profileId,
                        getCurrentDriveId(),
                        self.dataSource,
                    )
                )

            self._totalLogged += 1

            logger.debug(
                f"Logged reading | parameter={reading.parameterName} | "
                f"value={reading.value} | profile={profileId}"
            )

            return True

        except Exception as e:
            raise DataLoggerError(
                f"Failed to log reading: {e}",
                details={'reading': reading.toDict(), 'error': str(e)}
            ) from e

    def queryAndLogParameter(self, parameterName: str) -> LoggedReading:
        """
        Query a parameter and immediately log it to the database.

        Convenience method that combines queryParameter and logReading.

        Args:
            parameterName: Name of the OBD-II parameter

        Returns:
            LoggedReading with the logged data

        Raises:
            DataLoggerError: If query or logging fails
        """
        reading = self.queryParameter(parameterName)
        self.logReading(reading)
        return reading

    def getStats(self) -> dict[str, Any]:
        """
        Get statistics about logged data.

        Returns:
            Dictionary with stats:
            - totalReadings: Number of parameter reads
            - totalLogged: Number of readings logged to database
            - lastReadingTime: Timestamp of last reading
            - readErrors: Number of read errors encountered
        """
        return {
            'totalReadings': self._totalReadings,
            'totalLogged': self._totalLogged,
            'lastReadingTime': (
                self._lastReadingTime.isoformat()
                if self._lastReadingTime else None
            ),
            'readErrors': self._readErrors
        }

    def _getObdCommand(self, parameterName: str) -> Any:
        """
        Get the OBD command object for a parameter name.

        Args:
            parameterName: Name of the parameter (e.g., 'RPM')

        Returns:
            OBD command object or parameter name string for mocked connections

        Raises:
            ParameterNotSupportedError: If parameter is not recognized
        """
        # Try to get command from python-OBD library if available
        if obdlib is not None and hasattr(obdlib, 'commands'):
            cmd = getattr(obdlib.commands, parameterName, None)
            if cmd is not None:
                return cmd

        # For mocked connections or when OBD library doesn't have the command,
        # return the parameter name string. The mock's query() method will
        # handle it appropriately.
        return parameterName

    def _extractValue(self, response: Any) -> float:
        """
        Extract numeric value from OBD response.

        Handles both pint Quantity objects and plain values.

        Args:
            response: OBD response object

        Returns:
            Numeric value as float
        """
        value = response.value

        # Handle pint Quantity objects (have magnitude attribute)
        if hasattr(value, 'magnitude'):
            return float(value.magnitude)

        # Handle plain numeric values
        return float(value)

    def _extractUnit(self, response: Any) -> str | None:
        """
        Extract unit string from OBD response.

        Args:
            response: OBD response object

        Returns:
            Unit string or None
        """
        if hasattr(response, 'unit') and response.unit is not None:
            return str(response.unit)
        return None

    # ================================================================================
    # US-206: latest-reading snapshot (for drive_summary capture on _startDrive)
    # ================================================================================

    def _recordLatest(self, parameterName: str, value: float) -> None:
        """Publish ``value`` as the most-recent reading for ``parameterName``.

        Called at the tail of every successful query path (legacy +
        v2 decoder).  Kept private; :meth:`getLatestReadings` is the
        public read side.
        """
        with self._latestReadingsLock:
            self._latestReadings[parameterName] = float(value)

    def getLatestReadings(self) -> dict[str, float]:
        """Return a shallow copy of the most-recent reading per parameter.

        Read-only snapshot -- the copy semantics are what make this
        safe for :class:`~src.pi.obdii.drive_summary.SummaryRecorder`
        to consume on another thread without holding the logger's
        internal lock during its DB write.  US-206 Invariant #1:
        consuming this snapshot MUST NOT trigger any new Mode 01
        polls -- this method is pure read.

        Returns:
            ``{parameter_name: latest_numeric_value, ...}``.  Empty
            dict when no parameters have been queried yet (e.g., the
            collector cold-started between boot and first tick).
        """
        with self._latestReadingsLock:
            return dict(self._latestReadings)
