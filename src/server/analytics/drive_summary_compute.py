################################################################################
# File Name: drive_summary_compute.py
# Purpose/Description: B-104 Step 1a server-side drive_summary compute path.
#                      Reads raw realtime_data + Pi event-log fields and
#                      writes the drive_summary analytics columns directly.
#                      Replaces the V0.27.7-V0.27.16 trigger-seam writer
#                      architecture (US-326 / US-348) which depended on a
#                      Pi-side drive-end signal that did not fire on
#                      sequencer-driven termination.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-350) | Initial -- B-104 Step 1a (server = analytics
#               |              | authority).  Server-side compute path keyed on
#               |              | Pi-local drive_id.  Bug class structurally moot:
#               |              | start_time / end_time / row_count derived from
#               |              | realtime_data MIN/MAX/COUNT; no drive-end
#               |              | marker dependency.  Pi event-log fields
#               |              | (ambient_temp_at_start_c, starting_battery_v,
#               |              | data_source, drive_start_timestamp) are
#               |              | preserved -- is_real is derived from the
#               |              | Pi event-log data_source per Atlas Q2.
# ================================================================================
################################################################################

"""B-104 Step 1a -- server-side drive_summary compute from raw realtime_data.

Architectural principle (CIO 2026-05-21): Pi = telemetry emitter; server =
analytics authority.  Pi keeps drive boundary event logs for diagnostics;
server is the sole writer of derived analytics columns.

The compute function is invoked by two triggers, both server-side:

1. Overnight batch (``deploy/server-analytics-batch.service`` + ``.timer``):
   iterates over drives with NULL ``drive_summary`` analytics columns and
   recomputes each.
2. On-demand CLI (``python -m server.cli.recompute_drive_analytics``):
   recomputes a single drive, a range, or all stale drives.  First exercise
   of this path is the V0.27.17 backfill of drives 11-20 (US-352).

The function is read-only over ``realtime_data`` -- the canonical raw data
stream stays untouched.  It is idempotent: same raw data + same logic
produces the same output.  Re-running over an already-computed drive
updates ``computed_at`` (via the analytics columns themselves -- this
file does not own a separate timestamp column) but the data values
converge.

The Pi-side drive_summary writer module continues to write Pi event-log
fields (``drive_start_timestamp``, ``ambient_temp_at_start_c``,
``starting_battery_v``, ``data_source``); the server compute path
preserves those columns and ONLY writes the derived analytics columns
(``start_time``, ``end_time``, ``duration_seconds``, ``row_count``,
``is_real``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.server.analytics.overlap import detect_overlapping_drives
from src.server.db.models import (
    DATA_QUALITY_ATTRIBUTION_ANOMALY,
    DRIVE_SUMMARY_DATA_QUALITY_DEFAULT,
    DriveSummary,
    RealtimeData,
)

logger = logging.getLogger(__name__)


# ---- Constants --------------------------------------------------------------

# Per US-350 acceptance criterion 6: gaps >5 min in realtime_data timestamps
# log a WARN (defensive, not failing the compute).  5 min picks a soak
# window that's wider than any normal poll cadence (1-2 s) yet tighter
# than typical engine-off transients.
GAP_DETECTION_THRESHOLD_SECONDS: float = 300.0


# ---- Public compute API -----------------------------------------------------


def compute_drive_summary(session: Session, driveId: int) -> int | None:
    """Compute ``drive_summary`` analytics columns from raw realtime_data.

    Reads every ``realtime_data`` row for ``driveId`` (Pi-local drive_id,
    populated on the column by the US-200 sync path) and writes the
    derived analytics columns (``start_time``, ``end_time``,
    ``duration_seconds``, ``row_count``, ``is_real``) onto the existing
    Pi-sync ``drive_summary`` row matched by either ``source_id`` or
    ``drive_id``.

    Pi event-log columns (``drive_start_timestamp``,
    ``ambient_temp_at_start_c``, ``starting_battery_v``, ``data_source``,
    ``barometric_kpa_at_start``) are preserved -- ``is_real`` is derived
    from the Pi event-log ``data_source`` per Atlas Q2: ``'real'`` -> 1,
    ``'simulator'`` -> 0, NULL -> NULL (NULL must NOT silently coerce to
    0; that is the load-bearing distinction between "tested + not real"
    and "untested").

    Args:
        session: Open sync SQLAlchemy session bound to the server DB.
        driveId: Pi-local drive_id (matches ``realtime_data.drive_id``
            and ``drive_summary.source_id`` / ``drive_summary.drive_id``).

    Returns:
        The server-side ``drive_summary.id`` that was UPDATEd, or
        ``None`` when no ``realtime_data`` rows exist for the drive_id
        OR when no ``drive_summary`` row exists for the drive_id.  Both
        cases are non-fatal (logged at WARN); the caller decides whether
        a missing pre-condition is a real error in its context.
    """
    logger.info(
        "compute_drive_summary | drive_id=%s | begin", driveId,
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
            "compute_drive_summary | drive_id=%s | no drive_summary row -- "
            "skipping compute (Pi-sync may not have landed yet)",
            driveId,
        )
        return None

    realtimeFilter = (RealtimeData.drive_id == driveId)
    rowCount = int(session.execute(
        select(func.count()).select_from(RealtimeData).where(realtimeFilter),
    ).scalar_one())

    if rowCount == 0:
        logger.warning(
            "compute_drive_summary | drive_id=%s | zero realtime_data rows "
            "-- skipping compute (no canonical data to derive analytics from)",
            driveId,
        )
        return None

    startTime, endTime = session.execute(
        select(
            func.min(RealtimeData.timestamp),
            func.max(RealtimeData.timestamp),
        ).where(realtimeFilter),
    ).one()
    durationSeconds: int | None
    if startTime is not None and endTime is not None:
        durationSeconds = int((endTime - startTime).total_seconds())
    else:
        durationSeconds = None

    # Gap-detection tripwire (acceptance criterion 6).  Defensive log only --
    # never fails the compute.  Walks the ordered timestamp sequence once.
    _logTimestampGaps(session, realtimeFilter, driveId)

    # is_real derivation per Atlas Q2: read the Pi event-log data_source
    # already on the existing drive_summary row (server compute does NOT
    # majority-vote over realtime_data.data_source; the Pi event-log tag
    # is authoritative for the drive).
    isReal = _deriveIsReal(summary.data_source)

    # US-363: dual-attribution tripwire.  Flag the drive when its raw
    # realtime_data window overlaps another drive's window (the Drive 23/24
    # dual-emission pattern); detect_overlapping_drives (US-362) is the SSOT
    # detector over raw realtime_data.  Observability, not refusal: the row is
    # still written and fully readable, only its data_quality is stamped.
    overlappingDriveIds = detect_overlapping_drives(session, driveId)
    dataQuality = (
        DATA_QUALITY_ATTRIBUTION_ANOMALY if overlappingDriveIds
        else DRIVE_SUMMARY_DATA_QUALITY_DEFAULT
    )
    if overlappingDriveIds:
        logger.warning(
            "compute_drive_summary | drive_id=%s | ATTRIBUTION ANOMALY -- "
            "realtime_data window overlaps drive_id(s) %s; flagging row "
            "data_quality=%s",
            driveId, overlappingDriveIds, DATA_QUALITY_ATTRIBUTION_ANOMALY,
        )

    summary.start_time = startTime
    summary.end_time = endTime
    summary.duration_seconds = durationSeconds
    summary.row_count = rowCount
    summary.is_real = isReal
    summary.data_quality = dataQuality
    # US-372 (F-076): writer-path discipline -- never leave drive_id / source_id
    # divergent.  A legacy Pi-sync row arrives with source_id set and the
    # drive_id mirror NULL; heal both to the Pi-local driveId (== source_id for
    # any row this compute matched) so the chk_drive_id_source_id invariant holds.
    if summary.drive_id is None:
        summary.drive_id = driveId
    if summary.source_id is None:
        summary.source_id = driveId
    session.flush()

    logger.info(
        "compute_drive_summary | drive_id=%s | summary_id=%s | "
        "start=%s | end=%s | duration_s=%s | row_count=%s | is_real=%s | "
        "data_quality=%s",
        driveId,
        summary.id,
        startTime,
        endTime,
        durationSeconds,
        rowCount,
        isReal,
        dataQuality,
    )
    return summary.id


# ---- Helpers ---------------------------------------------------------------


def _deriveIsReal(dataSource: str | None) -> bool | None:
    """Derive ``is_real`` from the Pi event-log ``data_source`` per Atlas Q2.

    'real' -> True, 'simulator' -> False, anything else (including NULL,
    'replay', 'physics_sim', 'fixture') -> None.  NULL preservation is
    load-bearing: silently coercing NULL to 0 (FALSE) is the failure
    mode that masked "ungraded" drives as "tested + not real" in earlier
    revisions.
    """
    if dataSource is None:
        return None
    normalized = dataSource.strip().lower()
    if normalized == "real":
        return True
    if normalized == "simulator":
        return False
    return None


def _logTimestampGaps(
    session: Session,
    realtimeFilter,
    driveId: int,
) -> None:
    """Walk realtime_data timestamps in order; WARN on any gap >5 min.

    The compute path proceeds regardless -- this is observability, not
    a hard fail.  A gap is a flag for an operator/Spool to investigate
    (engine-off transient mid-drive, dropped Pi heartbeat, Bluetooth
    reconnect, etc.).
    """
    timestamps = session.execute(
        select(RealtimeData.timestamp)
        .where(realtimeFilter)
        .order_by(RealtimeData.timestamp.asc())
    ).scalars().all()

    if len(timestamps) < 2:
        return

    threshold = timedelta(seconds=GAP_DETECTION_THRESHOLD_SECONDS)
    previous: datetime = timestamps[0]
    for current in timestamps[1:]:
        delta = current - previous
        if delta > threshold:
            logger.warning(
                "compute_drive_summary | drive_id=%s | gap detected | "
                "prev=%s | curr=%s | delta_s=%.1f (threshold=%ss)",
                driveId,
                previous,
                current,
                delta.total_seconds(),
                GAP_DETECTION_THRESHOLD_SECONDS,
            )
        previous = current


__all__ = [
    "GAP_DETECTION_THRESHOLD_SECONDS",
    "compute_drive_summary",
]
