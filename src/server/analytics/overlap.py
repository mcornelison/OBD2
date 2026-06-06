################################################################################
# File Name: overlap.py
# Purpose/Description: Server-side drive overlap detector.  US-362 / F-107.
#                      detect_overlapping_drives() returns the set of other
#                      drive_ids whose raw realtime_data time window intersects
#                      a given drive's window by any whole second -- the SSOT
#                      detector behind the V0.27.18 dual-attribution tripwire
#                      (data_quality='attribution_anomaly', US-363/364).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-362) | Initial -- F-107 server-side overlap detector.
#               |              | Pure query helper over raw realtime_data (B-104
#               |              | Step 1 raw-signal authority); no DB writes.
# ================================================================================
################################################################################

"""Server-side drive-window overlap detection over raw ``realtime_data``.

The V0.27.18 IRL drill (2026-05-22) surfaced a Pi-side DriveDetector defect
that minted two ``drive_id``s for one physical leg (drives 23 + 24), whose
raw ``realtime_data`` windows therefore intersect in wall-clock time.  This
module provides the single source-of-truth detector used by the server-side
tripwire (US-363 ``data_quality='attribution_anomaly'``) and the historical
backfill (US-364).

Function:
    * :func:`detect_overlapping_drives` -- given a ``drive_id``, return the
      sorted list of other ``drive_id``s whose ``[min(timestamp),
      max(timestamp)]`` window intersects the target's window.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.server.db.models import RealtimeData


def detect_overlapping_drives(session: Session, drive_id: int) -> list[int]:
    """Return drive_ids whose realtime_data window intersects ``drive_id``.

    Each drive's time window is derived as ``[min(timestamp),
    max(timestamp)]`` over its raw ``realtime_data`` rows -- the raw-signal
    authority per B-104 Step 1.  This helper deliberately reads
    ``realtime_data`` and NEVER the derived ``drive_summary`` rows, so it
    cannot inherit any attribution error already baked into a summary.

    **Overlap threshold = strict time-range intersection per second.**  Two
    windows overlap when they share at least one whole second: endpoints are
    floored to the second and compared inclusively, so a single shared second
    (e.g. one drive ending the same second another begins) counts as a match.
    The slack allowance is **ε=0 seconds by default** (no clock-jitter
    tolerance); any non-zero ε allowance requires empirical justification and
    is a separate Story (US-362 conditionalOutcome 3), not a parameter here.

    The helper is a pure query: it issues no ``INSERT``/``UPDATE``/``DELETE``
    and is therefore idempotent and safe to call repeatedly.

    Args:
        session: An active SQLAlchemy session bound to the server schema.
        drive_id: The Pi-local ``drive_id`` (``realtime_data.drive_id``)
            whose neighbours are being checked for overlap.

    Returns:
        A sorted ``list[int]`` of other ``drive_id``s that overlap the
        target by at least one second.  Returns ``[]`` when the target drive
        has no ``realtime_data`` rows (no window) or when nothing overlaps.
        The target ``drive_id`` itself is never included.
    """
    targetWindow = _driveTimeRange(session, drive_id)
    if targetWindow is None:
        return []
    targetStart, targetEnd = targetWindow

    # One grouped scan: min/max timestamp per other (non-NULL) drive_id.
    otherWindows = session.execute(
        select(
            RealtimeData.drive_id,
            func.min(RealtimeData.timestamp),
            func.max(RealtimeData.timestamp),
        )
        .where(RealtimeData.drive_id.isnot(None))
        .where(RealtimeData.drive_id != drive_id)
        .group_by(RealtimeData.drive_id)
    ).all()

    overlapping: list[int] = []
    for otherId, otherStart, otherEnd in otherWindows:
        if otherStart is None or otherEnd is None:
            continue
        if _rangesOverlapBySecond(targetStart, targetEnd, otherStart, otherEnd):
            overlapping.append(int(otherId))

    return sorted(overlapping)


def _driveTimeRange(
    session: Session, drive_id: int,
) -> tuple[datetime, datetime] | None:
    """Return ``(min_timestamp, max_timestamp)`` for a drive, or ``None``.

    ``None`` is returned when the drive has no ``realtime_data`` rows (the
    aggregate yields NULL/NULL), i.e. the drive has no time window to compare.
    """
    start, end = session.execute(
        select(
            func.min(RealtimeData.timestamp),
            func.max(RealtimeData.timestamp),
        ).where(RealtimeData.drive_id == drive_id)
    ).one()
    if start is None or end is None:
        return None
    return start, end


def _rangesOverlapBySecond(
    aStart: datetime, aEnd: datetime, bStart: datetime, bEnd: datetime,
) -> bool:
    """True when ``[aStart, aEnd]`` and ``[bStart, bEnd]`` share a second.

    Endpoints are floored to whole seconds before an inclusive interval
    comparison, so any single shared second counts as overlap (ε=0).
    """
    aStart, aEnd = _floorToSecond(aStart), _floorToSecond(aEnd)
    bStart, bEnd = _floorToSecond(bStart), _floorToSecond(bEnd)
    return aStart <= bEnd and bStart <= aEnd


def _floorToSecond(value: datetime) -> datetime:
    """Drop the sub-second component so per-second intersection is exact."""
    return value.replace(microsecond=0)


__all__ = ["detect_overlapping_drives"]
