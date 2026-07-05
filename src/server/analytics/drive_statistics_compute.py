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
# 2026-07-04    | Rex (US-450) | F-104 spine: re-key the persisted stat from the
#               |              | bare drive_summary.id onto the US-448 canonical
#               |              | drives.drive_id (resolve_canonical_drive_id,
#               |              | natural-key lookup; subsume fallback to
#               |              | drive_summary.id == drives.drive_id per v0018).
#               |              | Add the F-116 foreign-vehicle guard: a drive
#               |              | stamped foreign_vehicle / non-'real' data_source
#               |              | is excluded from the authoritative table (mirrors
#               |              | compare_drives.driveExclusionReason).
# ================================================================================
################################################################################

"""B-104 Step 1b -- server-side ``drive_statistics`` compute from raw realtime_data.

Architectural principle (CIO 2026-05-21): Pi = telemetry emitter; server =
analytics authority.  Pi-side ``drive_statistics`` table retired entirely;
server is the sole writer.  The compute path is keyed on the Pi-local
``drive_id`` (matches ``realtime_data.drive_id`` and ``drive_summary.source_id``)
but persists rows keyed on the **canonical** ``drives.drive_id`` (US-450 / F-104).

US-450 re-key: the persisted stat's key is now resolved through the US-448
canonical drive-identity SSOT (:func:`src.server.analytics.drive_identity.
resolve_canonical_drive_id`, a natural-key lookup into ``drives``) rather than
the bare ``drive_summary.id``.  Because ``drives.drive_id`` SUBSUMES
``drive_summary.id`` (the v0018 explicit-id migration), the resolved value is
numerically identical to the old key for every existing drive, so the current
``DriveStatistic.summary_id -> drive_summary.id`` foreign key stays valid; US-451
formally re-points the FK constraint at ``drives.drive_id`` (same values).  When
no canonical row exists yet (unmappable legacy with a NULL natural key, or a
drive whose ``drives`` row has not been minted), the compute falls back to
``drive_summary.id`` -- which is exactly the value the subsume preserves, so the
key is honest either way.  This story only re-keys; it does NOT mint ``drives``
rows (the harness minting gap is a US-449 follow-up, flagged for the F-104 spine).

F-116 foreign guard (US-450): ``drive_statistics`` is the authoritative per-drive
analytics table, so a drive captured from a non-Eclipse vehicle (drive 33, the
Ford Explorer) or otherwise non-``'real'`` data is EXCLUDED -- no stats row is
written and any prior rows for the drive are cleared.  The exclusion predicate
mirrors :func:`src.server.cli.compare_drives.driveExclusionReason` (the F-116
SSOT) so the two never disagree on what "foreign" means.

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

from src.server.analytics.drive_identity import resolve_canonical_drive_id
from src.server.analytics.helpers import computeBasicStats
from src.server.analytics.overlap import detect_overlapping_drives
from src.server.db.models import (
    DATA_QUALITY_ATTRIBUTION_ANOMALY,
    DATA_QUALITY_FOREIGN_VEHICLE,
    DATA_SOURCE_DEFAULT,
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

# US-363 / F-107: not a sample-count bucket -- the dual-attribution tripwire
# value, applied as an override when the drive's realtime_data window overlaps
# another drive's (detect_overlapping_drives, US-362).  Aliased from the model
# SSOT so the classifier-vs-enum guard below stays meaningful.
DATA_QUALITY_ANOMALY = DATA_QUALITY_ATTRIBUTION_ANOMALY

# US-424 / F-116: drive-level foreign-vehicle marker.  Also not a sample-count
# bucket -- applied by the re-tag SQL / server backstop tripwire when a drive
# was captured from a non-Eclipse vehicle (drive 33, the Explorer).  Aliased
# from the model SSOT for the classifier-vs-enum guard.
DATA_QUALITY_FOREIGN = DATA_QUALITY_FOREIGN_VEHICLE

# Sanity-check at import time -- the model module owns the canonical enum.
assert set(DRIVE_STATISTICS_DATA_QUALITY_VALUES) == {
    DATA_QUALITY_BELOW_THRESHOLD,
    DATA_QUALITY_SPARSE,
    DATA_QUALITY_FULL,
    DATA_QUALITY_ANOMALY,
    DATA_QUALITY_FOREIGN,
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
    US-448 canonical ``drives.drive_id`` (US-450 re-key; resolved via
    :func:`src.server.analytics.drive_identity.resolve_canonical_drive_id`
    with a subsume fallback to ``drive_summary.id`` -- see the module
    docstring).

    F-116 foreign guard (US-450): a drive stamped ``data_quality=
    'foreign_vehicle'`` or carrying a non-'real' ``data_source`` (drive 33,
    the Ford Explorer) is EXCLUDED -- prior rows are cleared and ``0`` is
    returned, so no foreign data enters the authoritative table.

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
        the drive has no realtime_data, when no ``drive_summary`` row
        exists for the drive_id, OR when the drive is excluded by the
        F-116 foreign guard (all non-fatal; logged).

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

    # US-450 / F-104: resolve the CANONICAL drives.drive_id (US-448) and key
    # the persisted stat on it.  For every existing drive the natural-key
    # lookup returns drives.drive_id == drive_summary.id (v0018 subsume), so the
    # value is unchanged; the fallback covers a drive whose canonical row has
    # not been minted yet (or an unmappable-legacy NULL natural key), where the
    # subsumed identity is exactly drive_summary.id.
    canonicalDriveId = resolve_canonical_drive_id(
        session, summary.source_device, driveId,
    )
    if canonicalDriveId is None:
        canonicalDriveId = summaryId

    # US-450 / F-116: foreign-vehicle guard.  drive_statistics is the
    # authoritative per-drive analytics table -- a drive captured from a
    # non-Eclipse vehicle (drive 33) or otherwise non-'real' data must never
    # contaminate real-data baselines.  Exclude it: clear any prior rows and
    # return 0.  Idempotent (a re-run finds nothing to clear and returns 0).
    if _isForeignDrive(summary):
        session.execute(
            delete(DriveStatistic).where(
                DriveStatistic.summary_id == canonicalDriveId
            )
        )
        session.flush()
        logger.info(
            "compute_drive_statistics | drive_id=%s | drive_id_canonical=%s | "
            "EXCLUDED (F-116: data_quality=%s data_source=%s) -- no "
            "authoritative stats written",
            driveId, canonicalDriveId,
            summary.data_quality, summary.data_source,
        )
        return 0

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

    # US-363: the V0.27.18 dual-attribution tripwire.  If this drive's raw
    # realtime_data window overlaps another drive's (detect_overlapping_drives,
    # US-362), every per-parameter row is flagged 'attribution_anomaly',
    # overriding the sample-count classification -- the whole drive's
    # attribution is suspect, not a single parameter.  Observability, not
    # refusal: the rows are still written and fully readable downstream.
    overlappingDriveIds = detect_overlapping_drives(session, driveId)
    isAttributionAnomaly = bool(overlappingDriveIds)
    if isAttributionAnomaly:
        logger.warning(
            "compute_drive_statistics | drive_id=%s | summary_id=%s | "
            "ATTRIBUTION ANOMALY -- realtime_data window overlaps drive_id(s) "
            "%s; flagging all rows data_quality=%s",
            driveId, summaryId, overlappingDriveIds,
            DATA_QUALITY_ANOMALY,
        )

    valuesByParam: dict[str, list[float]] = {}
    for paramName, value in rows:
        valuesByParam.setdefault(paramName, []).append(float(value))

    # Pre-clear in a single statement so re-runs converge cleanly without
    # leaving stale parameter_name rows from prior raw-data shapes (e.g.,
    # a PID was dropped from the poll list).  Keyed on the canonical drive_id.
    session.execute(
        delete(DriveStatistic).where(
            DriveStatistic.summary_id == canonicalDriveId
        )
    )

    written = 0
    for paramName in sorted(valuesByParam.keys()):
        stats = computeBasicStats(valuesByParam[paramName])
        if stats is None:
            # Empty group is impossible by construction (the parameter_name
            # would not appear in valuesByParam); defensive skip.
            continue
        _assertGenericInvariants(driveId, paramName, stats)
        dataQuality = (
            DATA_QUALITY_ANOMALY if isAttributionAnomaly
            else _classifyDataQuality(stats.sample_count)
        )
        session.add(
            DriveStatistic(
                summary_id=canonicalDriveId,
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
        "drive_id_canonical=%s | params=%d | total_samples=%d",
        driveId, summaryId, canonicalDriveId, written,
        sum(len(v) for v in valuesByParam.values()),
    )
    return written


# ---- Helpers ----------------------------------------------------------------


def _isForeignDrive(summary: DriveSummary) -> bool:
    """F-116 foreign / non-'real' exclusion predicate for drive_statistics.

    Mirrors :func:`src.server.cli.compare_drives.driveExclusionReason` (the
    established F-116 exclusion SSOT) so ``drive_statistics`` and the
    cross-drive comparison never disagree on what "foreign" means -- the two
    predicates are pinned equal by a mirror-consistency test (A-4 anti-drift).

    A drive is excluded when it is stamped ``data_quality='foreign_vehicle'``
    OR carries a non-NULL ``data_source`` other than ``'real'``.  A NULL
    ``data_source`` is pre-US-195 history and treated as real (never excluded),
    matching the ``src/server/analytics/basic.py`` real-data filter.
    """
    if summary.data_quality == DATA_QUALITY_FOREIGN_VEHICLE:
        return True
    dataSource = summary.data_source
    return dataSource is not None and dataSource != DATA_SOURCE_DEFAULT


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
    "DATA_QUALITY_ANOMALY",
    "DATA_QUALITY_FOREIGN",
    "DATA_QUALITY_BELOW_THRESHOLD",
    "DATA_QUALITY_FULL",
    "DATA_QUALITY_SPARSE",
    "DATA_QUALITY_SPARSE_MIN",
    "DATA_QUALITY_FULL_MIN",
    "InvariantViolation",
    "compute_drive_statistics",
]
