################################################################################
# File Name: client.py
# Purpose/Description: HTTP sync client that pushes Pi delta rows to the
#                      Chi-Srv-01 companion service and advances the sync_log
#                      high-water mark on success ONLY.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-149
# 2026-04-19    | Rex (US-194) | TD-025 + TD-026 fix: route pushDelta through
#                               the PK_COLUMN registry; rename session_id
#                               -> id in payload rows for calibration_sessions
#                               so the existing server rule (key == 'id' ->
#                               source_id) applies unchanged.  Snapshot tables
#                               (profiles, vehicle_info) surface as SKIPPED.
# 2026-04-23    | Rex (US-225) | TD-034 close: forcePush() explicit-intent
#                               API + PushSummary aggregate for the US-216
#                               WARNING stage behavior (flush pending
#                               deltas before TRIGGER / poweroff).
# 2026-05-10    | Rex (US-315) | B-065 close: combined-cursor pushDelta for
#                               opt-in tables (battery_health_log,
#                               drive_summary, dtc_log).  Reads BOTH
#                               last_synced_id and last_synced_modified_at,
#                               passes them to getDeltaRows, advances both
#                               cursors after a successful push.  INSERT-only
#                               path for non-opt-in tables is unchanged.
# ================================================================================
################################################################################

"""
Pi -> server HTTP sync client.

:class:`SyncClient` is the Walk-phase link between the Pi's local SQLite and
the Chi-Srv-01 companion service.  It reads the sync_log (US-148), fetches
delta rows, POSTs them to ``{baseUrl}/api/v1/sync`` with an ``X-API-Key``
header, and advances the high-water mark on success.

Critical invariant
------------------
A failed push NEVER advances ``sync_log.last_synced_id``.  Failed pushes
record a ``status='failed'`` row with the ``last_batch_id`` and
``last_synced_at`` columns updated for diagnostics, but the id column
stays put so the next attempt re-sends the same rows.  Pi-side data is
unrecoverable without a restore if we lose it; when in doubt, do NOT
advance the mark.

Transport
---------
Uses stdlib :mod:`urllib.request` (no new dependencies on the Pi).  A
``POST /api/v1/sync`` looks like::

    POST /api/v1/sync HTTP/1.1
    Host: 10.27.27.10:8000
    Content-Type: application/json
    X-API-Key: <COMPANION_API_KEY>

    {
      "deviceId": "chi-eclipse-01",
      "batchId": "chi-eclipse-01-2026-04-18T14:30:00Z",
      "tables": {
        "realtime_data": {"lastSyncedId": 3965, "rows": [...]}
      }
    }

Retry classifier
----------------
* ``HTTPError`` with ``code >= 500`` -> retry (server fault, likely transient)
* ``HTTPError`` with ``code == 429`` -> retry (rate limit)
* ``HTTPError`` with ``400 <= code < 500`` (except 429) -> fail immediately
  (401/403 is a config bug, 404/422 is a client payload bug -- retrying
  would just hammer the server with the same broken request).
* ``URLError`` (DNS fail, connection refused, etc.) -> retry
* ``TimeoutError`` / ``socket.timeout`` -> retry

Backoff is per-attempt indexed from ``retryBackoffSeconds``; we use the
first ``retryMaxAttempts`` entries so the configured list can be longer
than needed without changing behavior.
"""

from __future__ import annotations

import json
import logging
import socket
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from src.common.config.secrets_loader import getSecret
from src.common.errors.handler import ConfigurationError
from src.pi.data import sync_log
from src.pi.obdii.drive_id import DRIVE_COUNTER_TABLE

__all__ = ["PushResult", "PushStatus", "PushSummary", "SyncClient"]

logger = logging.getLogger(__name__)


# ================================================================================
# Result types
# ================================================================================


class PushStatus(StrEnum):
    """Terminal status of a single push attempt."""

    OK = "ok"
    FAILED = "failed"
    DISABLED = "disabled"
    EMPTY = "empty"
    # US-194: snapshot/upsert tables (profiles, vehicle_info) are excluded
    # from the delta-sync path.  A call to pushDelta on them surfaces as
    # SKIPPED rather than FAILED -- this is deliberate behavior, not an
    # integrity problem.  A future upsert-sync story will introduce a
    # separate path for these tables.
    SKIPPED = "skipped"


@dataclass(slots=True)
class PushSummary:
    """Aggregate outcome of a :meth:`SyncClient.forcePush` call (US-225).

    Produced after iterating every in-scope table, giving the caller a
    compact view without forcing it to re-reduce the per-table list.
    The ``results`` list preserves the full per-table detail.

    Attributes:
        results: One :class:`PushResult` per in-scope table, in the
            same order :meth:`SyncClient.pushAllDeltas` returns them.
        rowsPushed: Sum of ``rowsPushed`` across OK results; excludes
            EMPTY / SKIPPED / DISABLED / FAILED results (which always
            report ``rowsPushed=0``).
        tablesOk: Count of OK (rows pushed).
        tablesEmpty: Count of EMPTY (nothing to push -- normal).
        tablesFailed: Count of FAILED (transport error, retries
            exhausted).
        tablesSkipped: Count of SKIPPED (snapshot tables, intentional).
        disabled: ``True`` when the first result came back DISABLED,
            meaning ``pi.companionService.enabled`` is false and no
            push was attempted.
        elapsed: Wall-clock seconds across the entire forcePush call,
            measured by the caller.
    """

    results: list[PushResult]
    rowsPushed: int
    tablesOk: int
    tablesEmpty: int
    tablesFailed: int
    tablesSkipped: int
    disabled: bool
    elapsed: float


@dataclass(slots=True)
class PushResult:
    """Outcome of one :meth:`SyncClient.pushDelta` call.

    Attributes:
        tableName: Source table the push was for.
        rowsPushed: Number of rows actually sent on the wire.  Zero for
            ``DISABLED`` (no network call made) and ``EMPTY`` (no rows to
            send); zero for ``FAILED`` when the failure happened before
            the POST body was built.
        batchId: Batch identifier sent in the payload; empty string when
            no push happened.
        elapsed: Wall-clock seconds spent inside :meth:`pushDelta`,
            including all retries.
        status: See :class:`PushStatus`.
        reason: Human-readable failure reason (empty on OK).
    """

    tableName: str
    rowsPushed: int
    batchId: str
    elapsed: float
    status: PushStatus
    reason: str = field(default="")


# ================================================================================
# Helpers
# ================================================================================


def _utcIsoTimestamp() -> str:
    """Return an ISO-8601 UTC timestamp with a trailing ``Z``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _makeBatchId(deviceId: str) -> str:
    """Build a batch identifier that is unique enough for human debugging."""
    return f"{deviceId}-{_utcIsoTimestamp()}"


def _isRetryableHttpStatus(code: int) -> bool:
    """Return True if a server-reported status code warrants another attempt."""
    return code == 429 or code >= 500


def _renamePkToId(
    rows: list[dict[str, Any]],
    pkColumn: str,
) -> list[dict[str, Any]]:
    """Return a new row list with ``pkColumn`` renamed to ``'id'`` (US-194).

    Used for tables whose Pi PK is not named ``id`` (calibration_sessions
    uses ``session_id``).  The server-side sync route expects ``id`` as the
    canonical Pi-native key (it maps ``row['id'] -> source_id``); keeping
    the original column name in the payload would leave the server with an
    unknown column AND no ``source_id``, triggering a NOT NULL violation.

    The rename is TOTAL (no dual-key row returned): SQLAlchemy's bulk
    upsert binds every key in the row, so an unknown column would cause
    the insert to fail.  Each row dict is rebuilt rather than mutated so
    callers that still hold the originals (e.g., for computing the new
    high-water mark) see unchanged data.
    """
    renamed: list[dict[str, Any]] = []
    for row in rows:
        newRow = {k: v for k, v in row.items() if k != pkColumn}
        newRow["id"] = row[pkColumn]
        renamed.append(newRow)
    return renamed


# Network-level exceptions that always warrant a retry.  ``socket.timeout`` is
# an alias for ``TimeoutError`` on Python 3.10+, listed explicitly so the
# classifier stays obvious on older interpreters in tests.
_RETRYABLE_NETWORK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    urllib.error.URLError,
    TimeoutError,
    socket.timeout,
)


def _readLocalDriveCounter(conn: sqlite3.Connection) -> int | None:
    """Return the local ``drive_counter.last_drive_id`` or None (US-314).

    Returns None when the table does not exist (pre-US-200 schema) so
    the caller can short-circuit cleanly without surfacing the bare
    sqlite3 error.  An empty singleton row is treated the same way --
    indistinguishable from "no drives yet" for sync purposes.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name = ?",
        (DRIVE_COUNTER_TABLE,),
    ).fetchone()
    if row is None:
        return None
    cursor = conn.execute(
        f"SELECT last_drive_id FROM {DRIVE_COUNTER_TABLE} WHERE id = 1"
    )
    record = cursor.fetchone()
    if record is None:
        return None
    return int(record[0])


# ================================================================================
# SyncClient
# ================================================================================


class SyncClient:
    """Push Pi delta rows to the companion server over HTTPS.

    One instance is reusable across many pushes.  It holds no open DB
    connections; each :meth:`pushDelta` call opens a fresh short-lived
    SQLite connection against ``pi.database.path``.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        dbPath: str | None = None,
        httpOpener: Any | None = None,
        sleep: Any | None = None,
    ) -> None:
        """Construct a SyncClient from a validated Pi config dict.

        Args:
            config: Full Pi config (the dict the validator returns).  Reads
                ``deviceId`` at the top level and ``pi.companionService`` +
                ``pi.database.path`` below.
            dbPath: Override for the Pi SQLite path.  Defaults to
                ``config['pi']['database']['path']``.
            httpOpener: Callable compatible with
                :func:`urllib.request.urlopen`; injected in tests to avoid
                real HTTP.  Defaults to ``urllib.request.urlopen``.
            sleep: Callable taking a float-seconds argument; injected in
                tests so backoff windows don't actually sleep.  Defaults to
                :func:`time.sleep`.

        Raises:
            ConfigurationError: If ``companionService.enabled`` is True but
                the configured API-key env var is unset.  (Construction is
                still allowed when ``enabled`` is False so disabled-path
                tests can round-trip without a real key in the env.)
        """
        self._config = config
        piConfig: dict[str, Any] = config.get("pi", {}) or {}
        self._companion: dict[str, Any] = piConfig.get("companionService", {}) or {}
        self._deviceId: str = str(config.get("deviceId") or "unknown-device")

        if dbPath is None:
            dbPath = piConfig.get("database", {}).get("path")
            if not dbPath:
                raise ConfigurationError(
                    "pi.database.path is required to construct SyncClient",
                    {"configKey": "pi.database.path"},
                )
        self._dbPath: str = dbPath

        self._httpOpener = httpOpener or urllib.request.urlopen
        self._sleep = sleep or time.sleep

        self._apiKey: str | None = None
        if self.isEnabled:
            self._apiKey = self._resolveApiKey()

    # ---- config surface ----------------------------------------------------

    @property
    def isEnabled(self) -> bool:
        """True when ``pi.companionService.enabled`` is truthy."""
        return bool(self._companion.get("enabled", False))

    @property
    def baseUrl(self) -> str:
        """Companion-service base URL, with any trailing slash stripped."""
        return str(self._companion.get("baseUrl", "")).rstrip("/")

    @property
    def deviceId(self) -> str:
        return self._deviceId

    @property
    def dbPath(self) -> str:
        return self._dbPath

    def _resolveApiKey(self) -> str:
        """Read the API key from the env var named in config, or raise."""
        envName = str(self._companion.get("apiKeyEnv") or "COMPANION_API_KEY")
        value = getSecret(envName)
        if not value:
            raise ConfigurationError(
                f"companion-service API key missing: set {envName} in the env",
                {"configKey": "pi.companionService.apiKeyEnv", "envVar": envName},
            )
        return value

    def _readTimeoutSeconds(self) -> float:
        return float(self._companion.get("syncTimeoutSeconds", 30))

    def _readBatchSize(self) -> int:
        return int(self._companion.get("batchSize", 500))

    def _readBackoffDelays(self) -> list[float]:
        """Return the backoff schedule truncated to ``retryMaxAttempts``.

        The configured list can be longer than strictly needed (the default
        is [1,2,4,8,16] even when retryMaxAttempts defaults to 3); we take
        only the first ``retryMaxAttempts`` entries so call-site logic and
        sleep accounting stays obvious.
        """
        schedule = self._companion.get("retryBackoffSeconds") or []
        maxAttempts = int(self._companion.get("retryMaxAttempts", 0))
        return [float(s) for s in schedule[:maxAttempts]]

    # ---- public API --------------------------------------------------------

    def pushDelta(self, tableName: str) -> PushResult:
        """Push one table's delta rows.  See module docstring for semantics.

        Args:
            tableName: Must be a member of
                :data:`src.pi.data.sync_log.IN_SCOPE_TABLES`.  Snapshot
                tables (see :data:`sync_log.SNAPSHOT_TABLES`) surface as
                :data:`PushStatus.SKIPPED` rather than being pushed --
                they do not fit the delta-by-PK model (US-194).

        Returns:
            A :class:`PushResult` describing the outcome.  A failed network
            push returns ``status=FAILED`` (not raised) so the caller /
            orchestrator stays alive.  ``ValueError`` is still raised for
            programmer errors like an unknown table name.

        Raises:
            ValueError: If ``tableName`` is not in IN_SCOPE_TABLES.
        """
        # Whitelist guard (delegates to sync_log; inherits US-148 semantics).
        sync_log._validateTable(tableName)  # noqa: SLF001 -- intentional reuse

        start = time.monotonic()

        # US-194: snapshot tables are explicitly excluded from the
        # delta-sync path.  Skip BEFORE touching DB / network so the call
        # is trivially cheap on every pass of pushAllDeltas().
        if tableName in sync_log.SNAPSHOT_TABLES:
            return PushResult(
                tableName=tableName,
                rowsPushed=0,
                batchId="",
                elapsed=time.monotonic() - start,
                status=PushStatus.SKIPPED,
                reason=(
                    f"{tableName} is a snapshot/upsert table; "
                    "delta-by-PK sync does not apply (US-194)"
                ),
            )

        if not self.isEnabled:
            return PushResult(
                tableName=tableName,
                rowsPushed=0,
                batchId="",
                elapsed=time.monotonic() - start,
                status=PushStatus.DISABLED,
            )

        # Canonical PK column for this delta-syncable table (US-194).
        pkColumn = sync_log.PK_COLUMN[tableName]
        supportsUpdateSync = tableName in sync_log.SYNC_UPDATE_TABLES_PK

        # US-319 (B-071): forensic INFO at push entry per table.  Stable
        # journalctl-grep token "FORENSIC sync_push_table_entry".
        # Discriminates US-315 / B-065 modified_at-cursor opt-in tables
        # (battery_health_log / drive_summary / dtc_log) from INSERT-
        # only tables on Drive 11+ sync sweeps.
        logger.info(
            "FORENSIC sync_push_table_entry | table=%s | pk_column=%s | "
            "supports_update_sync=%s",
            tableName, pkColumn, supportsUpdateSync,
        )

        with sqlite3.connect(self._dbPath) as conn:
            sync_log.initDb(conn)  # idempotent; makes the client robust to
            #                         a fresh DB being handed in by tests.
            # US-315: lazy idempotent migration -- ensures the modified_at
            # column + AFTER UPDATE trigger exist on opt-in tables before
            # the cursor query references them.  Pre-flight on a stale Pi
            # DB picks up the schema on first push.  No-op if already done.
            if supportsUpdateSync:
                sync_log.ensureSyncModifiedAtSchema(conn)
            lastId, _, _, _ = sync_log.getHighWaterMark(conn, tableName)
            lastModifiedAt: str | None = (
                sync_log.getModifiedHighWaterMark(conn, tableName)
                if supportsUpdateSync else None
            )
            # Pull the modified_at column on opt-in tables BEFORE
            # getDeltaRows strips it from the wire payload, so we can
            # compute the new high-water mark below.  For non-opt-in
            # tables this is None and the strip is a no-op.
            modifiedAtByPk: dict[int, str] = {}
            if supportsUpdateSync:
                modifiedAtByPk = self._collectModifiedAt(
                    conn, tableName, pkColumn, lastId, lastModifiedAt,
                )
            rows = sync_log.getDeltaRows(
                conn, tableName, lastId, self._readBatchSize(),
                lastModifiedAt=lastModifiedAt,
            )

            if not rows:
                return PushResult(
                    tableName=tableName,
                    rowsPushed=0,
                    batchId="",
                    elapsed=time.monotonic() - start,
                    status=PushStatus.EMPTY,
                )

            # US-194: For tables whose PK is not named ``id`` (currently
            # only calibration_sessions with session_id), rename the PK
            # column to ``id`` in each payload row so the server's existing
            # rule ``key == 'id' -> source_id`` applies without any
            # server-side protocol change.  The rename is TOTAL -- the
            # server rejects unknown columns, so leaving both names would
            # error on the SQLAlchemy insert.
            payloadRows = _renamePkToId(rows, pkColumn) if pkColumn != "id" else rows

            batchId = _makeBatchId(self._deviceId)
            try:
                self._postBatchWithRetry(tableName, batchId, payloadRows, lastId)
            except _PushFailure as failure:
                # On failure, record status='failed' + last_batch_id +
                # last_synced_at WITHOUT advancing last_synced_id.  We do
                # this by re-writing the existing mark through the UPSERT
                # with the same lastId it already held.
                sync_log.updateHighWaterMark(
                    conn, tableName, lastId, batchId, status="failed",
                )
                return PushResult(
                    tableName=tableName,
                    rowsPushed=0,
                    batchId=batchId,
                    elapsed=time.monotonic() - start,
                    status=PushStatus.FAILED,
                    reason=str(failure),
                )

            # New high-water mark comes from the source rows (pre-rename),
            # which still carry the authoritative PK under its real name.
            newHighWater = max(int(row[pkColumn]) for row in rows)
            # US-315: also advance the modified_at cursor for opt-in tables
            # so the next sync doesn't re-push the same row.  The advance
            # uses MAX(_sync_modified_at) of pushed rows; rows with NULL
            # _sync_modified_at (newly-INSERTed since US-315) don't move
            # the cursor.  Empty advance keeps the previous cursor (cursor
            # never rewinds).
            newModifiedAt: str | None = None
            if supportsUpdateSync and modifiedAtByPk:
                newModifiedAt = max(modifiedAtByPk.values())
                if lastModifiedAt is not None and newModifiedAt < lastModifiedAt:
                    newModifiedAt = lastModifiedAt
            sync_log.updateHighWaterMark(
                conn, tableName, newHighWater, batchId, status="ok",
                lastModifiedAt=newModifiedAt,
            )
            # US-319 (B-071): forensic INFO at cursor advance.  Stable
            # journalctl-grep token "FORENSIC sync_push_table_advance".
            # Confirms US-315 dual-cursor (id + modified_at) progression
            # so Drive 11+ sync sweeps can be reconciled against the
            # server-side UPSERT trail.
            logger.info(
                "FORENSIC sync_push_table_advance | table=%s | "
                "old_id=%s | new_id=%s | "
                "old_modified_at=%s | new_modified_at=%s | rows=%d",
                tableName, lastId, newHighWater,
                lastModifiedAt, newModifiedAt, len(rows),
            )
            return PushResult(
                tableName=tableName,
                rowsPushed=len(rows),
                batchId=batchId,
                elapsed=time.monotonic() - start,
                status=PushStatus.OK,
            )

    @staticmethod
    def _collectModifiedAt(
        conn: sqlite3.Connection,
        tableName: str,
        pkColumn: str,
        lastId: int,
        lastModifiedAt: str | None,
    ) -> dict[int, str]:
        """Return ``{pk -> _sync_modified_at}`` for rows the next push
        will fetch (US-315).

        Mirrors the WHERE clause in :func:`sync_log.getDeltaRows` but
        selects only the PK + modified_at columns -- cheap secondary
        query that lets :meth:`pushDelta` advance the modified_at cursor
        without re-scanning the full row payload.  Rows with NULL
        ``_sync_modified_at`` are omitted (their PK still moves the id
        cursor; they don't move the modified_at cursor).
        """
        modifiedFloor = lastModifiedAt or ''
        cursor = conn.execute(
            f"SELECT {pkColumn}, "  # noqa: S608 -- whitelisted identifiers
            f"       {sync_log.SYNC_MODIFIED_AT_COLUMN} "
            f"FROM {tableName} "
            f"WHERE ({pkColumn} > ? "
            f"       OR ({sync_log.SYNC_MODIFIED_AT_COLUMN} IS NOT NULL "
            f"           AND {sync_log.SYNC_MODIFIED_AT_COLUMN} > ?)) "
            f"  AND {sync_log.SYNC_MODIFIED_AT_COLUMN} IS NOT NULL "
            f"ORDER BY {pkColumn} ASC",
            (int(lastId), modifiedFloor),
        )
        return {int(pk): str(modAt) for pk, modAt in cursor.fetchall()}

    def pushAllDeltas(self) -> list[PushResult]:
        """Push every in-scope table in deterministic order.

        Snapshot tables return :data:`PushStatus.SKIPPED` -- they are still
        in the result set so operator output (``scripts/sync_now.py``) keeps
        visibility into all eight in-scope tables.

        Returns:
            One :class:`PushResult` per table in
            :data:`sync_log.IN_SCOPE_TABLES`, ordered by table name so
            operator-facing output is stable across runs.
        """
        results: list[PushResult] = []
        for tableName in sorted(sync_log.IN_SCOPE_TABLES):
            results.append(self.pushDelta(tableName))
        return results

    def forcePush(self) -> PushSummary:
        """Explicit-intent manual sync flush (US-225 / TD-034).

        Wraps :meth:`pushAllDeltas` with an explicit log line + an
        aggregate :class:`PushSummary`.  Semantics are identical to
        :meth:`pushAllDeltas` -- no normal-sync invariants are
        bypassed: the AUTH header, the per-table whitelist, the
        retry schedule, the failed-push HWM-preserve rule, and the
        snapshot-table skip all apply unchanged.  The value
        forcePush adds is readability at the call site and a single
        result object to reason about.

        Today there is no idle / rate-limit gate on pushDelta -- if
        a future gate is added, forcePush is the explicit bypass
        point.  The US-216 WARNING stage callback uses this to
        flush pending deltas before ``systemctl poweroff`` fires.

        US-314: also calls :meth:`pushDriveCounter` after the table
        sweep so the server-side singleton stays in lockstep with the
        Pi.  The counter result is appended to ``results`` so operator
        output shows the full picture; an EMPTY/FAILED/DISABLED counter
        push does not abort the table sweep (and vice versa).

        Returns:
            :class:`PushSummary` with per-table results and
            aggregate counts.  A companion service disabled by
            config returns ``disabled=True`` and zero counts
            (callers should treat that as a benign no-op rather
            than an error).
        """
        start = time.monotonic()
        logger.info(
            "forcePush: flushing pending deltas (explicit manual trigger)"
        )
        results = self.pushAllDeltas()
        results.append(self.pushDriveCounter())

        rowsPushed = 0
        tablesOk = 0
        tablesEmpty = 0
        tablesFailed = 0
        tablesSkipped = 0
        disabled = False
        for result in results:
            if result.status == PushStatus.OK:
                tablesOk += 1
                rowsPushed += result.rowsPushed
            elif result.status == PushStatus.EMPTY:
                tablesEmpty += 1
            elif result.status == PushStatus.FAILED:
                tablesFailed += 1
            elif result.status == PushStatus.SKIPPED:
                tablesSkipped += 1
            elif result.status == PushStatus.DISABLED:
                disabled = True

        elapsed = time.monotonic() - start
        logger.info(
            "forcePush complete: rows=%d ok=%d empty=%d failed=%d "
            "skipped=%d disabled=%s elapsed=%.2fs",
            rowsPushed, tablesOk, tablesEmpty, tablesFailed,
            tablesSkipped, disabled, elapsed,
        )
        return PushSummary(
            results=results,
            rowsPushed=rowsPushed,
            tablesOk=tablesOk,
            tablesEmpty=tablesEmpty,
            tablesFailed=tablesFailed,
            tablesSkipped=tablesSkipped,
            disabled=disabled,
            elapsed=elapsed,
        )

    def pushDriveCounter(self) -> PushResult:
        """Push the local ``drive_counter`` singleton to the server (US-314).

        ``drive_counter`` is a single-row state mirror, not a delta-by-PK
        capture table, so it rides on the sync request as a top-level
        ``driveCounter: {lastDriveId: N}`` field rather than being part
        of ``tables``.  The server's ``runDriveCounterUpsert`` writes
        it via a monotonic upsert (forward-only -- never rewinds).

        Status semantics mirror :meth:`pushDelta`:

        * :data:`PushStatus.DISABLED` -- companion service off in config.
        * :data:`PushStatus.EMPTY` -- counter table missing OR
          ``last_drive_id`` is 0 (no drives minted yet); no POST sent.
        * :data:`PushStatus.FAILED` -- transport error, retries
          exhausted; the singleton stays where it was on the server.
        * :data:`PushStatus.OK` -- value successfully delivered.

        Returns:
            :class:`PushResult` with ``tableName='drive_counter'``.
            ``rowsPushed`` is 1 on success, 0 otherwise.
        """
        start = time.monotonic()

        if not self.isEnabled:
            return PushResult(
                tableName=DRIVE_COUNTER_TABLE,
                rowsPushed=0,
                batchId="",
                elapsed=time.monotonic() - start,
                status=PushStatus.DISABLED,
            )

        with sqlite3.connect(self._dbPath) as conn:
            lastDriveId = _readLocalDriveCounter(conn)

        if lastDriveId is None or lastDriveId <= 0:
            return PushResult(
                tableName=DRIVE_COUNTER_TABLE,
                rowsPushed=0,
                batchId="",
                elapsed=time.monotonic() - start,
                status=PushStatus.EMPTY,
            )

        # US-319 (B-071): forensic INFO before drive_counter push.
        # Stable journalctl-grep token "FORENSIC sync_push_drive_counter".
        # Resolves V0.27.3 US-314 watch-item: drive_counter advance +
        # server UPSERT pairing visible in one journalctl trail on Drive 11+.
        logger.info(
            "FORENSIC sync_push_drive_counter | last_drive_id=%s",
            lastDriveId,
        )

        batchId = _makeBatchId(self._deviceId)
        try:
            self._postDriveCounterWithRetry(batchId, lastDriveId)
        except _PushFailure as failure:
            return PushResult(
                tableName=DRIVE_COUNTER_TABLE,
                rowsPushed=0,
                batchId=batchId,
                elapsed=time.monotonic() - start,
                status=PushStatus.FAILED,
                reason=str(failure),
            )

        return PushResult(
            tableName=DRIVE_COUNTER_TABLE,
            rowsPushed=1,
            batchId=batchId,
            elapsed=time.monotonic() - start,
            status=PushStatus.OK,
        )

    # ---- internals ---------------------------------------------------------

    def _postBatchWithRetry(
        self,
        tableName: str,
        batchId: str,
        rows: list[dict[str, Any]],
        lastSyncedId: int,
    ) -> None:
        """POST the batch; retry on transient failures; raise on final fail."""
        payload = {
            "deviceId": self._deviceId,
            "batchId": batchId,
            "tables": {
                tableName: {"lastSyncedId": lastSyncedId, "rows": rows},
            },
        }
        body = json.dumps(payload, default=str).encode("utf-8")
        url = f"{self.baseUrl}/api/v1/sync"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self._apiKey or "",
        }
        timeout = self._readTimeoutSeconds()
        delays = self._readBackoffDelays()

        # We attempt 1 + len(delays) times; first attempt has no prior
        # backoff, subsequent attempts sleep delays[attempt-1] before firing.
        totalAttempts = 1 + len(delays)
        lastReason: str = "no attempts executed"

        for attempt in range(totalAttempts):
            if attempt > 0:
                self._sleep(delays[attempt - 1])

            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with self._httpOpener(req, timeout=timeout) as response:
                    # Reading the body drains the socket cleanly; we don't
                    # care about the parsed content because 2xx is the
                    # success signal by itself.
                    _ = response.read()
                return
            except urllib.error.HTTPError as exc:
                code = getattr(exc, "code", 0) or 0
                lastReason = f"HTTP {code} {exc.reason}"
                if not _isRetryableHttpStatus(code):
                    logger.warning(
                        "sync push for %s -> %s rejected: %s (no retry)",
                        tableName, url, lastReason,
                    )
                    raise _PushFailure(lastReason) from exc
                logger.warning(
                    "sync push for %s -> %s attempt %d/%d failed: %s",
                    tableName, url, attempt + 1, totalAttempts, lastReason,
                )
            except _RETRYABLE_NETWORK_EXCEPTIONS as exc:
                lastReason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "sync push for %s -> %s attempt %d/%d network error: %s",
                    tableName, url, attempt + 1, totalAttempts, lastReason,
                )

        raise _PushFailure(lastReason)


    def _postDriveCounterWithRetry(
        self,
        batchId: str,
        lastDriveId: int,
    ) -> None:
        """POST the drive_counter snapshot; retry policy mirrors _postBatch.

        US-314: payload shape is the standard sync request with an empty
        ``tables`` map plus the new top-level ``driveCounter`` field.
        Reuses the same retry classifier so transient server-side
        errors don't lose the singleton update.
        """
        payload = {
            "deviceId": self._deviceId,
            "batchId": batchId,
            "tables": {},
            "driveCounter": {"lastDriveId": lastDriveId},
        }
        body = json.dumps(payload, default=str).encode("utf-8")
        url = f"{self.baseUrl}/api/v1/sync"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self._apiKey or "",
        }
        timeout = self._readTimeoutSeconds()
        delays = self._readBackoffDelays()
        totalAttempts = 1 + len(delays)
        lastReason = "no attempts executed"

        for attempt in range(totalAttempts):
            if attempt > 0:
                self._sleep(delays[attempt - 1])

            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with self._httpOpener(req, timeout=timeout) as response:
                    _ = response.read()
                return
            except urllib.error.HTTPError as exc:
                code = getattr(exc, "code", 0) or 0
                lastReason = f"HTTP {code} {exc.reason}"
                if not _isRetryableHttpStatus(code):
                    logger.warning(
                        "drive_counter sync -> %s rejected: %s (no retry)",
                        url, lastReason,
                    )
                    raise _PushFailure(lastReason) from exc
                logger.warning(
                    "drive_counter sync -> %s attempt %d/%d failed: %s",
                    url, attempt + 1, totalAttempts, lastReason,
                )
            except _RETRYABLE_NETWORK_EXCEPTIONS as exc:
                lastReason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "drive_counter sync -> %s attempt %d/%d network error: %s",
                    url, attempt + 1, totalAttempts, lastReason,
                )

        raise _PushFailure(lastReason)


# ================================================================================
# Internal failure marker
# ================================================================================


class _PushFailure(Exception):
    """Raised internally when all retries for a single table have been exhausted.

    Never propagates out of :meth:`SyncClient.pushDelta`; caught there and
    converted into ``PushResult(status=FAILED)``.
    """
