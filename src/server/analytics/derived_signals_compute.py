################################################################################
# File Name: derived_signals_compute.py
# Purpose/Description: US-436 / F-106 server-side per-drive derived motion
#                      signals.  Integrates acceleration + estimated distance
#                      from the EXISTING SPEED realtime_data stream (no new
#                      PIDs) and UPSERTs one row per drive into
#                      drive_derived_signals, keyed on the server-side
#                      drive_summary.id.  Sibling to drive_summary_compute /
#                      drive_statistics_compute; invoked by the same on-demand
#                      CLI + nightly batch (Atlas Q1 single-timer-fires-all).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Rex (US-436) | Initial -- F-106 derived signals (acceleration
#               |              | + estimated distance) from speed+time.  Pure
#               |              | computeDerivedSignals + DB writer.  Guards the
#               |              | divide-by-zero (dt<=0) + time-gap (dt>threshold)
#               |              | cases the AC calls out.
# ================================================================================
################################################################################

"""US-436 / F-106 -- server-side per-drive derived motion signals.

Architectural principle (CIO 2026-05-21, B-104): Pi = telemetry emitter;
server = analytics authority.  This module reads the raw SPEED
``realtime_data`` rows for a Pi-local ``drive_id`` and derives two motion
signals the raw stream does not carry directly, WITHOUT any new PID:

* **estimated distance** -- the trapezoidal integral of speed over time.
  SPEED is stored in km/h, so distance comes out in kilometres.
* **acceleration** -- the per-segment finite difference of speed over time.
  km/h is converted to m/s (``/3.6``) before dividing by dt, so the peaks
  carry the physical m/s^2 unit.  The per-drive row stores the peak positive
  (hardest acceleration) and peak negative (hardest braking) values.

The pure core :func:`computeDerivedSignals` takes a plain
``(timestamp, speed_kmh)`` series and returns a :class:`DerivedSignals`
dataclass -- fully unit-testable off-Pi against canned series (the US-436
validationCriteria gate).  :func:`compute_drive_derived_signals` is the thin
DB adapter: it reads the ordered SPEED series for a drive, calls the pure
core, and UPSERTs the result.

Guards (AC "guard against divide-by-zero / time gaps"):

* ``dt <= 0`` -- duplicate or non-monotonic timestamps.  The segment is
  skipped entirely (never divided by); it accrues neither distance nor
  acceleration.
* ``dt > GAP_THRESHOLD_SECONDS`` -- a soak gap (engine-off transient, dropped
  heartbeat, Bluetooth reconnect).  The vehicle is NOT known to have travelled
  at the bracketing speed across the gap, so the segment is excluded from the
  distance integral and the acceleration scan, and is tallied in
  ``gap_skipped_count`` for observability.

Idempotency: the drive's prior ``drive_derived_signals`` row is DELETEd
before the new one is INSERTed; ``computed_at`` advances via
``onupdate=func.now()`` while data columns converge.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

# Reuse the drive_summary_compute soak-gap threshold as the SSOT for "a gap
# this wide is not continuous driving" -- keeping one constant so the two
# analytics paths cannot drift to different gap definitions silently.
from src.server.analytics.analytics_types import DerivedSignals
from src.server.analytics.drive_summary_compute import (
    GAP_DETECTION_THRESHOLD_SECONDS as GAP_THRESHOLD_SECONDS,
)
from src.server.db.models import (
    DriveDerivedSignal,
    DriveSummary,
    RealtimeData,
)

logger = logging.getLogger(__name__)


# ---- Constants --------------------------------------------------------------

# The realtime_data parameter_name carrying vehicle speed (OBD PID 0x0D,
# stored in km/h -- see src/pi/obdii/obd_parameters.py 'SPEED').
SPEED_PARAMETER_NAME: str = "SPEED"

# Unit labels persisted alongside the values (honest-instrument: a reader
# never has to guess the unit of a stored magnitude).
SPEED_UNIT: str = "km/h"
DISTANCE_UNIT: str = "km"
ACCELERATION_UNIT: str = "m/s^2"

# Unit-conversion constants (no magic numbers).
SECONDS_PER_HOUR: float = 3600.0
KMH_TO_MPS: float = 1.0 / 3.6


# ---- Pure compute -----------------------------------------------------------


def computeDerivedSignals(
    samples: Sequence[tuple[datetime, float]],
    *,
    gapThresholdSeconds: float = GAP_THRESHOLD_SECONDS,
) -> DerivedSignals | None:
    """Derive distance + acceleration peaks from a speed/time series.

    Pure function -- no DB, no I/O.  The input is a sequence of
    ``(timestamp, speed_kmh)`` samples (order-independent; sorted internally
    by timestamp).  Distance is the trapezoidal integral of speed over time
    (km); the acceleration peaks are the most positive / most negative
    per-segment finite differences in m/s^2.

    Args:
        samples: ``(timestamp, speed_kmh)`` readings for one drive.
        gapThresholdSeconds: segments whose dt exceeds this are excluded from
            both the distance integral and the acceleration scan (soak-gap
            guard).  Defaults to the shared drive-analytics gap threshold.

    Returns:
        A :class:`DerivedSignals`, or ``None`` when fewer than two samples are
        supplied (no segment can be formed).  When every segment is skipped
        (all dt<=0 or all gaps), distance is ``0.0`` and both peaks are
        ``None`` -- an honest "computed, nothing valid to integrate".
    """
    if len(samples) < 2:
        return None

    ordered = sorted(samples, key=lambda s: s[0])

    distanceKm = 0.0
    peakAccel: float | None = None
    peakDecel: float | None = None
    segmentCount = 0
    gapSkipped = 0

    for (t0, v0), (t1, v1) in zip(ordered, ordered[1:], strict=False):
        dtSeconds = (t1 - t0).total_seconds()

        # Divide-by-zero / non-monotonic guard: never divide by a non-positive
        # dt.  The segment contributes nothing.
        if dtSeconds <= 0.0:
            continue

        # Soak-gap guard: a gap wider than the threshold is not continuous
        # travel; exclude it from distance + acceleration and tally it.
        if dtSeconds > gapThresholdSeconds:
            gapSkipped += 1
            continue

        # Trapezoidal distance: mean speed over the segment * elapsed hours.
        distanceKm += (v0 + v1) / 2.0 * (dtSeconds / SECONDS_PER_HOUR)

        # Acceleration in m/s^2: convert the km/h delta to m/s, then / dt.
        accelMs2 = ((v1 - v0) * KMH_TO_MPS) / dtSeconds
        peakAccel = accelMs2 if peakAccel is None else max(peakAccel, accelMs2)
        peakDecel = accelMs2 if peakDecel is None else min(peakDecel, accelMs2)

        segmentCount += 1

    return DerivedSignals(
        estimated_distance_km=distanceKm,
        peak_acceleration_ms2=peakAccel,
        peak_deceleration_ms2=peakDecel,
        sample_count=len(ordered),
        segment_count=segmentCount,
        gap_skipped_count=gapSkipped,
        speed_unit=SPEED_UNIT,
        distance_unit=DISTANCE_UNIT,
        accel_unit=ACCELERATION_UNIT,
    )


# ---- DB adapter -------------------------------------------------------------


def compute_drive_derived_signals(session: Session, driveId: int) -> int | None:
    """Compute + persist the ``drive_derived_signals`` row for one drive.

    Reads the drive's SPEED ``realtime_data`` rows ordered by timestamp, runs
    :func:`computeDerivedSignals`, and UPSERTs a single row keyed on the
    server-side ``drive_summary.id`` (mirrors the DriveStatistic pattern).

    Args:
        session: Open sync SQLAlchemy session bound to the server DB.
        driveId: Pi-local drive_id (matches ``realtime_data.drive_id`` and
            ``drive_summary.source_id`` / ``drive_summary.drive_id``).

    Returns:
        The server-side ``drive_summary.id`` written, or ``None`` when:

        * no ``drive_summary`` row exists for the drive_id (Pi-sync not landed),
          OR
        * the drive has fewer than two SPEED samples (nothing to derive).

        Both are non-fatal and logged at WARN; the row is simply not written.
    """
    logger.info(
        "compute_drive_derived_signals | drive_id=%s | begin", driveId,
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
            "compute_drive_derived_signals | drive_id=%s | no drive_summary "
            "row -- skipping (Pi-sync may not have landed yet)",
            driveId,
        )
        return None
    summaryId = summary.id

    speedRows = session.execute(
        select(RealtimeData.timestamp, RealtimeData.value)
        .where(
            (RealtimeData.drive_id == driveId)
            & (RealtimeData.parameter_name == SPEED_PARAMETER_NAME)
        )
        .order_by(RealtimeData.timestamp.asc())
    ).all()

    samples = [(ts, float(value)) for ts, value in speedRows]
    signals = computeDerivedSignals(samples)
    if signals is None:
        logger.warning(
            "compute_drive_derived_signals | drive_id=%s | summary_id=%s | "
            "%d SPEED sample(s) (<2) -- nothing to derive, skipping",
            driveId, summaryId, len(samples),
        )
        return None

    # Pre-clear so re-runs replace rather than collide on the PK.
    session.execute(
        delete(DriveDerivedSignal).where(
            DriveDerivedSignal.summary_id == summaryId
        )
    )
    session.add(
        DriveDerivedSignal(
            summary_id=summaryId,
            estimated_distance_km=signals.estimated_distance_km,
            peak_acceleration_ms2=signals.peak_acceleration_ms2,
            peak_deceleration_ms2=signals.peak_deceleration_ms2,
            sample_count=signals.sample_count,
            segment_count=signals.segment_count,
            gap_skipped_count=signals.gap_skipped_count,
            speed_unit=signals.speed_unit,
            distance_unit=signals.distance_unit,
            accel_unit=signals.accel_unit,
        )
    )
    session.flush()

    logger.info(
        "compute_drive_derived_signals | drive_id=%s | summary_id=%s | "
        "distance_km=%.4f | peak_accel_ms2=%s | peak_decel_ms2=%s | "
        "samples=%d | segments=%d | gaps_skipped=%d",
        driveId, summaryId, signals.estimated_distance_km,
        signals.peak_acceleration_ms2, signals.peak_deceleration_ms2,
        signals.sample_count, signals.segment_count, signals.gap_skipped_count,
    )
    return summaryId


__all__ = [
    "ACCELERATION_UNIT",
    "DISTANCE_UNIT",
    "GAP_THRESHOLD_SECONDS",
    "KMH_TO_MPS",
    "SECONDS_PER_HOUR",
    "SPEED_PARAMETER_NAME",
    "SPEED_UNIT",
    "DerivedSignals",
    "computeDerivedSignals",
    "compute_drive_derived_signals",
]
