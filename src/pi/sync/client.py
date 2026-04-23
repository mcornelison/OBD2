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

        with sqlite3.connect(self._dbPath) as conn:
            sync_log.initDb(conn)  # idempotent; makes the client robust to
            #                         a fresh DB being handed in by tests.
            lastId, _, _, _ = sync_log.getHighWaterMark(conn, tableName)
            rows = sync_log.getDeltaRows(
                conn, tableName, lastId, self._readBatchSize(),
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
            sync_log.updateHighWaterMark(
                conn, tableName, newHighWater, batchId, status="ok",
            )
            return PushResult(
                tableName=tableName,
                rowsPushed=len(rows),
                batchId=batchId,
                elapsed=time.monotonic() - start,
                status=PushStatus.OK,
            )

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


# ================================================================================
# Internal failure marker
# ================================================================================


class _PushFailure(Exception):
    """Raised internally when all retries for a single table have been exhausted.

    Never propagates out of :meth:`SyncClient.pushDelta`; caught there and
    converted into ``PushResult(status=FAILED)``.
    """
