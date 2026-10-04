################################################################################
# File Name: battery_health_finalize.py
# Purpose/Description: ARCH-065 -- at boot, finish the prior drain's capacity
#                      fields (specs/battery-health-design.md sec 6, 9, 15.4).
#                      cut_step_mv = powerwatch's last on-wall VCELL minus the
#                      drain row's start_vcell_v.  drain_rate_mv_s = least-squares
#                      slope of VCELL over the window, for a COUNTED monthly test
#                      only (runtime >= TEST_HOLD_S and the window >= 80 % filled).
#                      The window is timed from the drain row's start_timestamp
#                      (the cut); the trajectory begins ~smoothingSec later, at
#                      the confirmation read.  Write-once: a field already set is
#                      never overwritten.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | ARCH-065 T6: created.  Timings imported from
#                                      battery_capacity (SSOT), trigger enum from
#                                      battery_health.
################################################################################
"""Finalise the prior drain at boot -- cut step and window drain rate."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from src.common.time.helper import CANONICAL_ISO_FORMAT
from src.pi.power.battery_capacity import TEST_HOLD_S, WINDOW_S, WINDOW_SKIP_S
from src.pi.power.battery_health import DRAIN_TRIGGER_MONTHLY_TEST

__all__ = ['MIN_WINDOW_FILL', 'finalizeLatestDrain', 'windowDrainRate']

#: Fraction of WINDOW_S the window must hold in samples (1 Hz) for the rate to count.
MIN_WINDOW_FILL: float = 0.8


def windowDrainRate(points: list[tuple[float, float]]) -> float | None:
    """Least-squares slope of (seconds, volts), in mV/s; None for < 2 distinct times."""
    n = len(points)
    if n < 2:
        return None
    meanT = sum(t for t, _ in points) / n
    meanV = sum(v for _, v in points) / n
    den = sum((t - meanT) ** 2 for t, _ in points)
    if den == 0:
        return None
    return 1000.0 * sum((t - meanT) * (v - meanV) for t, v in points) / den


def finalizeLatestDrain(
    conn: sqlite3.Connection, *, priorBootVcellBeforeCutV: float | None,
) -> None:
    """Complete the newest closed drain row's cut step and (monthly test) window rate.

    Idempotent and write-once.  The caller owns commit.  A monthly test shorter
    than TEST_HOLD_S (interrupted) or with a sparse window gets no rate.

    Args:
        conn: Open connection with the Task 1 columns present.
        priorBootVcellBeforeCutV: powerwatch's last on-wall VCELL (volts), or None.
    """
    row = conn.execute(
        "SELECT drain_event_id, start_timestamp, runtime_seconds, start_vcell_v, drain_trigger, "
        "cut_step_mv, drain_rate_mv_s FROM battery_health_log "
        "WHERE end_timestamp IS NOT NULL ORDER BY drain_event_id DESC LIMIT 1",
    ).fetchone()
    if row is None:
        return
    drainId, startTs, runtime, startV, trigger, cutStep, rate = row
    if cutStep is None and priorBootVcellBeforeCutV is not None and startV is not None:
        conn.execute(
            "UPDATE battery_health_log SET cut_step_mv = ? WHERE drain_event_id = ?",
            (round(1000.0 * (priorBootVcellBeforeCutV - startV), 2), drainId),
        )
    if (
        trigger != DRAIN_TRIGGER_MONTHLY_TEST
        or rate is not None
        or runtime is None
        or runtime < TEST_HOLD_S
    ):
        return
    cut = datetime.strptime(startTs, CANONICAL_ISO_FORMAT).replace(tzinfo=UTC)
    lo = (cut + timedelta(seconds=WINDOW_SKIP_S)).strftime(CANONICAL_ISO_FORMAT)
    hi = (cut + timedelta(seconds=TEST_HOLD_S)).strftime(CANONICAL_ISO_FORMAT)
    points = [
        (float(tsCapture), float(vcell))
        for tsCapture, vcell in conn.execute(
            "SELECT ts_capture, vcell_v FROM drain_vcell_trajectory "
            "WHERE ts_utc >= ? AND ts_utc <= ? AND vcell_v IS NOT NULL ORDER BY id",
            (lo, hi),
        )
    ]
    if len(points) < MIN_WINDOW_FILL * WINDOW_S:
        return
    slope = windowDrainRate(points)
    if slope is None:
        return
    conn.execute(
        "UPDATE battery_health_log SET drain_rate_mv_s = ?, window_start_s = ?, "
        "window_end_s = ? WHERE drain_event_id = ?",
        (round(slope, 5), WINDOW_SKIP_S, TEST_HOLD_S, drainId),
    )
