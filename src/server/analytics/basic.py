################################################################################
# File Name: basic.py
# Purpose/Description: Basic analytics engine — per-drive statistics and
#                      new-vs-historical comparison for the crawl phase.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-158 — basic
#               |              | analytics engine per spec §1.7
# ================================================================================
################################################################################

"""
Basic analytics engine.

Two entry points, both taking a sync :class:`sqlalchemy.orm.Session` and a
drive id:

* :func:`computeDriveStatistics` — read all ``realtime_data`` rows for the
  drive's time window and device, group by ``parameter_name``, compute
  min/max/avg/std/outlier bounds, and upsert into ``drive_statistics``.
* :func:`compareDriveToHistory` — compute historical aggregates across all
  *other* drives with stats for each parameter, compare the current drive's
  avg to the historical mean, and classify the deviation as NORMAL / WATCH
  / INVESTIGATE.

Both functions are idempotent: running ``computeDriveStatistics`` twice
replaces the previous rows for that drive; ``compareDriveToHistory`` is a
pure read and can be called any number of times.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from src.server.analytics.helpers import classifyDeviation, computeBasicStats
from src.server.analytics.types import DriveStatistics, ParameterComparison
from src.server.db.models import DriveStatistic, DriveSummary, RealtimeData

# ---- Per-drive statistics ----------------------------------------------------


def computeDriveStatistics(
    session: Session, driveId: int,
) -> list[DriveStatistics]:
    """
    Compute per-parameter statistics for ``driveId`` and persist them.

    Reads the drive's ``start_time``, ``end_time``, and ``device_id`` from
    ``drive_summary``, then pulls every ``realtime_data`` row whose timestamp
    falls inside that window and whose ``source_device`` matches. Rows are
    grouped by ``parameter_name`` and each group's series runs through
    :func:`computeBasicStats`. Any pre-existing ``drive_statistics`` rows for
    the drive are deleted before the new rows are inserted, making the
    operation idempotent.

    Args:
        session: Open SQLAlchemy session bound to the server database.
        driveId: PK of the ``drive_summary`` row to profile.

    Returns:
        A list of :class:`DriveStatistics`, one per distinct parameter.

    Raises:
        ValueError: If no ``drive_summary`` row exists for ``driveId``.
    """
    drive = session.get(DriveSummary, driveId)
    if drive is None:
        raise ValueError(f"no drive_summary row for drive_id={driveId}")

    valuesByParam = _collectReadings(session, drive)

    # Clear previous stats so re-running replaces rather than duplicates.
    session.execute(
        delete(DriveStatistic).where(DriveStatistic.drive_id == driveId)
    )

    results: list[DriveStatistics] = []
    for paramName in sorted(valuesByParam.keys()):
        stats = computeBasicStats(valuesByParam[paramName])
        if stats is None:
            continue

        row = DriveStatistic(
            drive_id=driveId,
            parameter_name=paramName,
            min_value=stats.min_value,
            max_value=stats.max_value,
            avg_value=stats.avg_value,
            std_dev=stats.std_dev,
            outlier_min=stats.outlier_min,
            outlier_max=stats.outlier_max,
            sample_count=stats.sample_count,
        )
        session.add(row)

        results.append(
            DriveStatistics(
                drive_id=driveId,
                parameter_name=paramName,
                min_value=stats.min_value,
                max_value=stats.max_value,
                avg_value=stats.avg_value,
                std_dev=stats.std_dev,
                outlier_min=stats.outlier_min,
                outlier_max=stats.outlier_max,
                sample_count=stats.sample_count,
            )
        )

    session.commit()
    return results


def _collectReadings(
    session: Session, drive: DriveSummary,
) -> dict[str, list[float]]:
    """Pull ``realtime_data`` rows for a drive and bucket by parameter name."""
    filters = [
        RealtimeData.source_device == drive.device_id,
        RealtimeData.timestamp >= drive.start_time,
    ]
    if drive.end_time is not None:
        filters.append(RealtimeData.timestamp <= drive.end_time)

    stmt = select(
        RealtimeData.parameter_name, RealtimeData.value,
    ).where(and_(*filters))

    buckets: dict[str, list[float]] = defaultdict(list)
    for name, value in session.execute(stmt).all():
        buckets[name].append(float(value))
    return buckets


# ---- Historical comparison ---------------------------------------------------


def compareDriveToHistory(
    session: Session, driveId: int,
) -> list[ParameterComparison]:
    """
    Compare the current drive's per-parameter stats to historical aggregates.

    Historical aggregates are computed from every ``drive_statistics`` row
    whose ``drive_id`` is **not** ``driveId`` (the current drive is excluded
    so its own values don't bias the baseline). For each parameter the
    current drive has stats for, we compute:

    * ``historical_mean_avg`` — mean of ``avg_value`` across prior drives.
    * ``historical_std_avg`` — sample std dev of ``avg_value`` across prior
      drives. Falls back to ``0.0`` when fewer than two historical samples
      exist, which keeps ``deviation_sigma`` at ``0.0`` and the status at
      ``NORMAL`` (there's no meaningful envelope yet).
    * ``deviation_sigma`` — ``(current_avg - historical_mean_avg) /
      historical_std_avg``.
    * ``status`` — :func:`helpers.classifyDeviation`.

    Args:
        session: Open SQLAlchemy session bound to the server database.
        driveId: PK of the drive to compare.

    Returns:
        One :class:`ParameterComparison` per parameter the current drive has
        stats for. Parameters with no historical data at all are reported
        with ``status=NORMAL`` and ``deviation_sigma=0.0``.
    """
    currentStats = session.execute(
        select(DriveStatistic).where(DriveStatistic.drive_id == driveId)
    ).scalars().all()

    if not currentStats:
        return []

    comparisons: list[ParameterComparison] = []
    for current in currentStats:
        historicalAvgs = [
            row.avg_value
            for row in session.execute(
                select(DriveStatistic).where(
                    and_(
                        DriveStatistic.parameter_name == current.parameter_name,
                        DriveStatistic.drive_id != driveId,
                    )
                )
            ).scalars().all()
            if row.avg_value is not None
        ]

        if not historicalAvgs:
            # No prior drives for this parameter — skip rather than emit a
            # zero-filled comparison that could mislead a reader.
            continue

        historicalMean = float(statistics.fmean(historicalAvgs))
        historicalStd = (
            float(statistics.stdev(historicalAvgs))
            if len(historicalAvgs) >= 2
            else 0.0
        )

        currentAvg = float(current.avg_value or 0.0)
        sigma = (
            (currentAvg - historicalMean) / historicalStd
            if historicalStd > 0.0
            else 0.0
        )

        comparisons.append(
            ParameterComparison(
                parameter_name=current.parameter_name,
                current_avg=currentAvg,
                current_max=float(current.max_value or 0.0),
                historical_mean_avg=historicalMean,
                historical_std_avg=historicalStd,
                deviation_sigma=sigma,
                status=classifyDeviation(sigma),
            )
        )

    return comparisons


# ---- Public API --------------------------------------------------------------

__all__ = [
    "compareDriveToHistory",
    "computeDriveStatistics",
]
