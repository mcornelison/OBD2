################################################################################
# File Name: drive_statistics.py
# Purpose/Description: Pi-side per-drive per-parameter aggregate writer
#                      (US-349 / I-040 / US-328-redo, Sprint 40 / V0.27.16).
#                      The V0.27.7 US-328 ship landed the drive_statistics
#                      schema in src.pi.obdii.database_schema (Option C
#                      hybrid "table only, no writer") but left the writer
#                      unbuilt -- empirically confirmed 2026-05-20 across
#                      drives 11-18 incl. fresh real drives 17+18 (zero
#                      drive_statistics rows ever).  This module is the
#                      missing writer.  Reads realtime_data rows for the
#                      closing drive_id, groups by parameter_name, computes
#                      min/max/avg/std_dev/outlier_min/outlier_max/sample_count
#                      in Python, and INSERTs one row per parameter_name.
#                      Wired into DriveDetector._endDrive via the orchestrator
#                      lifecycle (mirrors the US-206 SummaryRecorder shape).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-349) | Initial -- I-040 / US-328-redo writer.  New
#               |              | sibling module per Sprint 40 story scope.
#               |              | DriveStatisticsRecorder mirrors SummaryRecorder
#               |              | constructor + DatabaseLike protocol pattern.
#               |              | Idempotent: re-running deletes existing rows
#               |              | for the drive_id before INSERTing fresh
#               |              | aggregates.  Edge: n<2 -> sample stdev N/A ->
#               |              | std_dev + outlier bounds are NULL.  n==N
#               |              | all-equal values -> stdev=0 (finite, not NaN).
# ================================================================================
################################################################################

"""Per-drive per-parameter aggregate writer (US-349 / I-040).

Why this exists
---------------

V0.27.7 US-328 shipped ``passes:true`` with ONLY the schema:
``src/pi/obdii/database_schema.py:642`` is explicit -- ``Option C (hybrid)
-- table only, no writer.``  The Tester I-040 evidence run 2026-05-20
confirmed empirically what the schema comment named: across drives 11-18
incl. fresh real drives 17+18, the Pi ``drive_statistics`` table holds zero
rows ever.  This module supplies the missing writer.

Where it runs
-------------

Pi tier only.  Called from
:meth:`src.pi.obdii.drive.detector.DriveDetector._endDrive` at drive-end,
AFTER the existing :meth:`_triggerAnalysis` call (which fires the legacy
``statistics`` table writer) and BEFORE :meth:`_closeDriveId` (which clears
the ``getCurrentDriveId()`` context).  The wiring lives in
:meth:`src.pi.obdii.orchestrator.lifecycle.LifecycleMixin
._initializeDriveStatisticsRecorder`, mirroring the
US-206 :meth:`_initializeSummaryRecorder` shape (DI via constructor + setter,
opt-out via ``pi.driveStatistics.enabled=false``, soft-failure init so a
recorder construction error never crashes boot).

What it writes
--------------

One row per distinct ``parameter_name`` present in the closing drive's
``realtime_data`` rows.  Columns populated:

* ``drive_id``        -- the closing drive_id (NOT NULL on the schema).
* ``parameter_name``  -- the OBD-II PID short name.
* ``min_value``       -- ``min(values)``.
* ``max_value``       -- ``max(values)``.
* ``avg_value``       -- ``sum(values) / n``.
* ``std_dev``         -- :func:`statistics.stdev` sample stdev.  NULL when ``n < 2``.
* ``outlier_min``     -- ``avg - 2 * std_dev``.  NULL when ``std_dev`` is NULL.
* ``outlier_max``     -- ``avg + 2 * std_dev``.  NULL when ``std_dev`` is NULL.
* ``sample_count``    -- ``n``.
* ``computed_at``     -- schema default (canonical ISO-8601 UTC).

Idempotency
-----------

Re-calling :meth:`DriveStatisticsRecorder.recordDriveStatistics` with the
same ``driveId`` first DELETEs existing rows for that drive_id, then
INSERTs the fresh aggregates.  This makes the writer safe to replay on
recovery paths (post-shutdown retry, manual operator re-trigger) without
needing UNIQUE constraints on the table (the schema mirrors the server
shape which has no per-(drive_id,parameter_name) UNIQUE either).

Scope discipline
----------------

* The Pi-side ``drive_statistics`` schema is doNotTouch -- this module
  ONLY writes against the existing schema.
* The server-side drive_statistics writer (``_ensureDriveStatistics`` in
  ``src/server/analytics/`` per US-324) is independent + unchanged.
* The Pi->server sync client is doNotTouch -- Pi-side stats are NOT yet
  synced server-side per the V0.27.7 Option C hybrid intent (B-075 for
  V0.28+ feature sprint, per the doNotTouch list).
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    'DRIVE_STATISTICS_TABLE',
    'DatabaseLike',
    'DriveStatisticsRecorder',
    'DriveStatisticsResult',
    'REALTIME_DATA_TABLE',
]

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================


DRIVE_STATISTICS_TABLE: str = 'drive_statistics'
REALTIME_DATA_TABLE: str = 'realtime_data'


# ================================================================================
# Database protocol (shared shape with SummaryRecorder; pinned here to keep
# drive_statistics independent of drive_summary.py at import time)
# ================================================================================


class DatabaseLike(Protocol):
    """Structural interface satisfied by :class:`ObdDatabase` + test doubles."""

    def connect(self) -> Any: ...  # context manager yielding sqlite3.Connection


# ================================================================================
# Result dataclass
# ================================================================================


@dataclass(frozen=True)
class DriveStatisticsResult:
    """Per-call outcome from :meth:`DriveStatisticsRecorder.recordDriveStatistics`.

    Attributes:
        driveId: The drive_id that was processed.
        parametersWritten: Set of ``parameter_name`` values for which a
            ``drive_statistics`` row was written.  Empty when no
            ``realtime_data`` rows exist for the drive_id (clean no-op
            -- not an error condition).
        totalSamples: Sum of ``sample_count`` across all written rows.
            Equal to the number of ``realtime_data`` rows aggregated.
    """

    driveId: int
    parametersWritten: frozenset[str]
    totalSamples: int


# ================================================================================
# Writer
# ================================================================================


class DriveStatisticsRecorder:
    """Persists per-parameter aggregates into ``drive_statistics`` at drive-end.

    Stateless aside from the injected database handle -- each
    :meth:`recordDriveStatistics` call opens its own connection via the
    protocol's ``connect()`` context manager.  Idempotent across replay.

    Designed to be called from
    :meth:`src.pi.obdii.drive.detector.DriveDetector._endDrive` with the
    closing drive_id (snapshot of ``getCurrentDriveId()`` BEFORE
    ``_closeDriveId`` clears the context).
    """

    def __init__(self, *, database: DatabaseLike) -> None:
        self._database = database

    def recordDriveStatistics(self, driveId: int) -> DriveStatisticsResult:
        """Aggregate ``realtime_data`` for ``driveId`` and write to ``drive_statistics``.

        Args:
            driveId: The Pi-local drive_id whose realtime_data should be
                aggregated.  Must be a valid integer that matches at
                least one ``realtime_data.drive_id`` row, or the call
                is a clean no-op (returns ``totalSamples=0``).

        Returns:
            :class:`DriveStatisticsResult` describing what was written.

        Raises:
            sqlite3.Error: If the underlying database is unavailable or
                the schema is corrupt.  Callers (the detector wiring)
                are expected to wrap this call in a try/except so a
                writer failure does not block drive_end.
        """
        with self._database.connect() as conn:
            rawRows = self._fetchRealtimeData(conn, driveId)

        if not rawRows:
            # Clean no-op: no realtime_data for this drive_id.  Do not
            # touch drive_statistics for unrelated drives.
            logger.info(
                "drive_statistics record: no realtime_data | drive_id=%s",
                driveId,
            )
            return DriveStatisticsResult(
                driveId=int(driveId),
                parametersWritten=frozenset(),
                totalSamples=0,
            )

        # Group values by parameter_name in Python so we can compute
        # sample stdev (SQLite has no native STDDEV).  A typical drive
        # produces ~600 readings per parameter at 1 Hz polling -- well
        # within memory.
        groups: dict[str, list[float]] = {}
        for paramName, value in rawRows:
            groups.setdefault(paramName, []).append(float(value))

        aggregates = [
            (paramName, _computeAggregates(values))
            for paramName, values in groups.items()
        ]

        totalSamples = sum(agg.sampleCount for _, agg in aggregates)

        # Single transaction: DELETE existing rows for idempotency, then
        # INSERT one row per parameter.  Keeps the write atomic so an
        # external reader never sees the deletion-without-insert window.
        with self._database.connect() as conn:
            conn.execute(
                f"DELETE FROM {DRIVE_STATISTICS_TABLE} WHERE drive_id = ?",
                (int(driveId),),
            )
            for paramName, agg in aggregates:
                conn.execute(
                    f"INSERT INTO {DRIVE_STATISTICS_TABLE} "
                    "(drive_id, parameter_name, min_value, max_value, "
                    " avg_value, std_dev, outlier_min, outlier_max, "
                    " sample_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        int(driveId),
                        paramName,
                        agg.minValue,
                        agg.maxValue,
                        agg.avgValue,
                        agg.stdDev,
                        agg.outlierMin,
                        agg.outlierMax,
                        agg.sampleCount,
                    ),
                )

        parametersWritten = frozenset(name for name, _ in aggregates)
        logger.info(
            "drive_statistics INSERT | drive_id=%s | params=%d | total_samples=%d",
            driveId, len(parametersWritten), totalSamples,
        )
        return DriveStatisticsResult(
            driveId=int(driveId),
            parametersWritten=parametersWritten,
            totalSamples=totalSamples,
        )

    @staticmethod
    def _fetchRealtimeData(
        conn: sqlite3.Connection, driveId: int,
    ) -> list[tuple[str, float]]:
        """Fetch (parameter_name, value) rows for one drive_id.

        ``realtime_data.value`` is ``REAL NOT NULL`` by schema, so a value
        is guaranteed non-NULL.  ``drive_id`` is ``NULL`` on pre-US-200
        rows / rows written while no drive is active; the ``=`` predicate
        naturally excludes them.
        """
        cursor = conn.execute(
            f"SELECT parameter_name, value FROM {REALTIME_DATA_TABLE} "
            f"WHERE drive_id = ?",
            (int(driveId),),
        )
        return [(row[0], float(row[1])) for row in cursor.fetchall()]


# ================================================================================
# Aggregate helper (pure -- no DB, no I/O)
# ================================================================================


@dataclass(frozen=True)
class _Aggregates:
    """Per-parameter aggregate bundle written into one drive_statistics row."""

    minValue: float
    maxValue: float
    avgValue: float
    stdDev: float | None
    outlierMin: float | None
    outlierMax: float | None
    sampleCount: int


def _computeAggregates(values: list[float]) -> _Aggregates:
    """Reduce a list of per-parameter values to the drive_statistics row shape.

    Pure function -- no DB, no I/O.  Edge cases:

    * ``n == 0`` is impossible by construction (the writer skips
      parameter_names with no rows), but a defensive guard returns a
      degenerate row that nevertheless satisfies NOT NULL constraints.
    * ``n == 1`` -> :func:`statistics.stdev` is undefined (needs >=2
      samples for sample stdev).  Returns ``stdDev=None`` and both
      outlier bounds ``None``.
    * ``n >= 2`` and all-equal values -> ``stdev`` is ``0.0`` (finite,
      not NaN); outliers degenerate to the mean.
    """
    n = len(values)
    if n == 0:
        return _Aggregates(
            minValue=0.0, maxValue=0.0, avgValue=0.0,
            stdDev=None, outlierMin=None, outlierMax=None,
            sampleCount=0,
        )
    minV = min(values)
    maxV = max(values)
    avgV = sum(values) / n
    if n < 2:
        return _Aggregates(
            minValue=minV, maxValue=maxV, avgValue=avgV,
            stdDev=None, outlierMin=None, outlierMax=None,
            sampleCount=n,
        )
    stdV = statistics.stdev(values)
    return _Aggregates(
        minValue=minV, maxValue=maxV, avgValue=avgV,
        stdDev=stdV,
        outlierMin=avgV - 2 * stdV,
        outlierMax=avgV + 2 * stdV,
        sampleCount=n,
    )
