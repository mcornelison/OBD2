################################################################################
# File Name: drive_statistics_compute.py
# Purpose/Description: B-104 Step 1b server-side drive_statistics compute path.
#                      Reads raw realtime_data + computes per-parameter stats
#                      via the shared 2-sigma helper, classifies data_quality,
#                      and UPSERTs into drive_statistics keyed on the server-side
#                      drive_summary.id.  Replaces the V0.27.7-V0.27.16
#                      trigger-seam Pi-side writer architecture (US-328, US-349)
#                      whose drive-end signal never fired on sequencer-driven
#                      termination -- a 3-cycle false-pass class structurally
#                      moot once server reads raw realtime rows directly.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-351) | Initial -- B-104 Step 1b (server = analytics
#               |              | authority).  Sibling to US-350's
#               |              | drive_summary_compute; both invoked by the
#               |              | same systemd timer + on-demand CLI (Atlas Q1
#               |              | single-timer-fires-both-paths).  Spool FLAG-1
#               |              | honored: reuses computeBasicStats so the
#               |              | 2-sigma outlier math lives in one place and
#               |              | cannot drift to IQR / 3-sigma silently.
#               |              | Atlas Refinement A: generic invariants
#               |              | (min<=avg<=max, std_dev>=0, no NaN/inf,
#               |              | sample_count>=1) RAISE if violated.  Atlas
#               |              | Refinement B: data_quality classification
#               |              | (<10 below_threshold, 10-99 sparse, >=100 full).
# ================================================================================
################################################################################

"""B-104 Step 1b -- server-side ``drive_statistics`` compute from raw realtime_data.

Architectural principle (CIO 2026-05-21): Pi = telemetry emitter; server =
analytics authority.  Pi-side ``drive_statistics`` table retired entirely;
server is the sole writer.  The compute path is keyed on the Pi-local
``drive_id`` (matches ``realtime_data.drive_id`` and ``drive_summary.source_id``)
but persists rows keyed on the SERVER-side ``drive_summary.id`` per the
ForeignKey on :class:`src.server.db.models.DriveStatistic`.

Invocation triggers (same as :mod:`drive_summary_compute`):

1. Overnight batch (``deploy/server-analytics-batch.service`` + ``.timer``).
2. On-demand CLI (``python -m src.server.cli.recompute_drive_analytics``).

The compute function is read-only over ``realtime_data``, idempotent across
re-runs (re-running yields the same column values; ``computed_at`` advances
via ``onupdate=func.now()``), and never depends on a Pi-side drive-end
marker.  Argus's RCA (DriveDetector drive-end signal does not fire on
sequencer-driven termination) is structurally moot here -- the compute
reads raw rows directly.
"""

from __future__ import annotations

import logging
import math

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.server.analytics.helpers import computeBasicStats
from src.server.db.models import (
    DRIVE_STATISTICS_DATA_QUALITY_VALUES,
    DriveStatistic,
    DriveSummary,
    RealtimeData,
)

logger = logging.getLogger(__name__)


# ---- Constants --------------------------------------------------------------

# Atlas Refinement B: data_quality classification thresholds.
#
# ``below_threshold`` (< 10 samples) signals the aggregate is statistically
# meaningless -- the row is still written so downstream queries can
# distinguish "computed but unreliable" from "missing"; Spool's grading
# should treat it as untrustworthy.  ``sparse`` (10-99) is usable for trend
# direction but not for outlier bounds.  ``full`` (>= 100) is the
# steady-state polling cadence at ~1 Hz over ~100 seconds and is the
# baseline-quality bucket Spool reads.
DATA_QUALITY_BELOW_THRESHOLD = "below_threshold"
DATA_QUALITY_SPARSE = "sparse"
DATA_QUALITY_FULL = "full"

# Sanity-check at import time -- the model module owns the canonical enum.
assert set(DRIVE_STATISTICS_DATA_QUALITY_VALUES) == {
    DATA_QUALITY_BELOW_THRESHOLD,
    DATA_QUALITY_SPARSE,
    DATA_QUALITY_FULL,
}, (
    "data_quality classifiers diverged from the model enum -- update both "
    "together (src/server/db/models.py:DRIVE_STATISTICS_DATA_QUALITY_VALUES "
    "+ src/server/analytics/drive_statistics_compute.py constants)"
)

DATA_QUALITY_SPARSE_MIN = 10
DATA_QUALITY_FULL_MIN = 100


class InvariantViolation(ValueError):
    """Atlas Refinement A invariant tripped during compute.

    Raised when a per-parameter aggregate violates one of the generic
    invariants (min<=avg<=max, std_dev>=0, finite values, sample_count>=1).
    Callers in the CLI / batch path catch this per-drive so a single bad
    drive does not abort an entire backfill run.
    """


# ---- Public compute API -----------------------------------------------------


def compute_drive_statistics(session: Session, driveId: int) -> int:
    """Compute per-parameter ``drive_statistics`` rows from raw realtime_data.

    Reads every ``realtime_data`` row for the Pi-local ``driveId``, groups
    by ``parameter_name``, computes aggregates via
    :func:`src.server.analytics.helpers.computeBasicStats` (Spool FLAG-1
    SSOT pin), classifies ``data_quality`` per Atlas Refinement B, and
    UPSERTs one row per parameter into ``drive_statistics`` keyed on the
    server-side ``drive_summary.id``.

    Idempotency: prior rows for the drive are DELETEd before the new ones
    are INSERTed; ``computed_at`` carries ``onupdate=func.now()`` so an
    observable timestamp advances on re-run while the data columns stay
    stable.

    Args:
        session: Open sync SQLAlchemy session bound to the server DB.
        driveId: Pi-local drive_id (matches ``realtime_data.drive_id``
            and ``drive_summary.source_id`` / ``drive_summary.drive_id``).

    Returns:
        Number of ``drive_statistics`` rows written.  Returns ``0`` when
        the drive has no realtime_data OR when no ``drive_summary`` row
        exists for the drive_id (both non-fatal; logged at WARN).

    Raises:
        InvariantViolation: Atlas Refinement A invariant tripped on at
            least one parameter's aggregate.  The session is not flushed
            in that case; the caller is expected to rollback.
    """
    logger.info(
        "compute_drive_statistics | drive_id=%s | begin", driveId,
    )

    summary = session.execute(
        select(DriveSummary)
        .where(
            (DriveSummary.source_id == driveId)
            | (DriveSummary.drive_id == driveId)
        )
        .order_by(DriveSummary.id.asc())
    ).scalars().first()
    if summary is None:
        logger.warning(
            "compute_drive_statistics | drive_id=%s | no drive_summary row "
            "-- skipping (Pi-sync may not have landed yet)",
            driveId,
        )
        return 0
    summaryId = summary.id

    rows = session.execute(
        select(RealtimeData.parameter_name, RealtimeData.value)
        .where(RealtimeData.drive_id == driveId)
    ).all()
    if not rows:
        logger.warning(
            "compute_drive_statistics | drive_id=%s | summary_id=%s | "
            "zero realtime_data rows -- skipping",
            driveId, summaryId,
        )
        return 0

    valuesByParam: dict[str, list[float]] = {}
    for paramName, value in rows:
        valuesByParam.setdefault(paramName, []).append(float(value))

    # Pre-clear in a single statement so re-runs converge cleanly without
    # leaving stale parameter_name rows from prior raw-data shapes (e.g.,
    # a PID was dropped from the poll list).
    session.execute(
        delete(DriveStatistic).where(DriveStatistic.drive_id == summaryId)
    )

    written = 0
    for paramName in sorted(valuesByParam.keys()):
        stats = computeBasicStats(valuesByParam[paramName])
        if stats is None:
            # Empty group is impossible by construction (the parameter_name
            # would not appear in valuesByParam); defensive skip.
            continue
        _assertGenericInvariants(driveId, paramName, stats)
        dataQuality = _classifyDataQuality(stats.sample_count)
        session.add(
            DriveStatistic(
                drive_id=summaryId,
                parameter_name=paramName,
                min_value=stats.min_value,
                max_value=stats.max_value,
                avg_value=stats.avg_value,
                std_dev=stats.std_dev,
                outlier_min=stats.outlier_min,
                outlier_max=stats.outlier_max,
                sample_count=stats.sample_count,
                data_quality=dataQuality,
            )
        )
        written += 1

    session.flush()
    logger.info(
        "compute_drive_statistics | drive_id=%s | summary_id=%s | "
        "params=%d | total_samples=%d",
        driveId, summaryId, written,
        sum(len(v) for v in valuesByParam.values()),
    )
    return written


# ---- Helpers ----------------------------------------------------------------


def _classifyDataQuality(sampleCount: int) -> str:
    """Atlas Refinement B: classify per ``sample_count`` thresholds."""
    if sampleCount < DATA_QUALITY_SPARSE_MIN:
        return DATA_QUALITY_BELOW_THRESHOLD
    if sampleCount < DATA_QUALITY_FULL_MIN:
        return DATA_QUALITY_SPARSE
    return DATA_QUALITY_FULL


def _assertGenericInvariants(
    driveId: int, paramName: str, stats: object,
) -> None:
    """Atlas Refinement A: RAISE on min>avg, avg>max, std<0, NaN/inf, n<1.

    Per-PID envelopes are deferred to V0.28+ (Atlas Refinement A scope).
    These invariants apply to every PID identically.
    """
    minV = float(stats.min_value)
    maxV = float(stats.max_value)
    avgV = float(stats.avg_value)
    stdV = float(stats.std_dev) if stats.std_dev is not None else 0.0
    sampleCount = int(stats.sample_count)

    if sampleCount < 1:
        raise InvariantViolation(
            f"drive_id={driveId} param={paramName}: "
            f"sample_count={sampleCount} < 1"
        )
    if not (math.isfinite(minV) and math.isfinite(maxV)
            and math.isfinite(avgV) and math.isfinite(stdV)):
        raise InvariantViolation(
            f"drive_id={driveId} param={paramName}: "
            f"non-finite aggregate (min={minV} max={maxV} "
            f"avg={avgV} std={stdV})"
        )
    if stdV < 0:
        raise InvariantViolation(
            f"drive_id={driveId} param={paramName}: std_dev={stdV} < 0"
        )
    if not (minV <= avgV <= maxV):
        raise InvariantViolation(
            f"drive_id={driveId} param={paramName}: "
            f"min<=avg<=max violated (min={minV} avg={avgV} max={maxV})"
        )


__all__ = [
    "DATA_QUALITY_BELOW_THRESHOLD",
    "DATA_QUALITY_FULL",
    "DATA_QUALITY_SPARSE",
    "DATA_QUALITY_SPARSE_MIN",
    "DATA_QUALITY_FULL_MIN",
    "InvariantViolation",
    "compute_drive_statistics",
]
