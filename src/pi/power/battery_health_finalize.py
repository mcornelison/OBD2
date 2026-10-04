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
# 2026-10-03    | Atlas (ARCH-065a)  | ARCH-065 T6 fix: row keyed by the loss time (not
#                                      newest closed row); open rows rated; span check.
################################################################################
"""Finalise the prior drain at boot -- cut step and window drain rate."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from src.common.time.helper import CANONICAL_ISO_FORMAT
from src.pi.power.battery_capacity import TEST_HOLD_S, WINDOW_S, WINDOW_SKIP_S
from src.pi.power.battery_health import DRAIN_TRIGGER_MONTHLY_TEST

logger = logging.getLogger(__name__)

__all__ = ['LOSS_ROW_AFTER_S', 'LOSS_ROW_BEFORE_S', 'MIN_WINDOW_FILL', 'finalizeLatestDrain', 'windowDrainRate']

#: The prior loss's drain row opens within this band around the loss's wall time
#: (the collector's clock may lead powerwatch's; its confirmation poll may lag).
LOSS_ROW_BEFORE_S: int = 5
LOSS_ROW_AFTER_S: int = 30

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
    conn: sqlite3.Connection,
    *,
    priorBootVcellBeforeCutV: float | None,
    priorBootLossAt: str | None,
) -> None:
    """Complete the cut step and (monthly test) window rate of THE prior loss's row.

    The row is found by the loss's wall time (``HomeStateAtLoss.lossIso``, landed
    as ``startup_log.prior_boot_loss_at``): the newest row whose start_timestamp
    lies in [loss - LOSS_ROW_BEFORE_S, loss + LOSS_ROW_AFTER_S], open or closed.
    At arm the prior loss's row may still be open (a hard cut, or the boot reaper
    has not run), so "newest closed row" could be an older drain -- and both
    fields are write-once, so a mis-stamp would be permanent.  No loss time, or
    no row in that band: nothing is written.

    Idempotent and write-once.  Commits the cut step at once, so a later failure
    cannot roll it back.

    Args:
        conn: Open connection with the Task 1 columns present.
        priorBootVcellBeforeCutV: powerwatch's last on-wall VCELL (volts), or None.
        priorBootLossAt: the prior loss's canonical UTC ISO second, or None.
    """
    if priorBootLossAt is None:
        logger.info("battery_health_finalize: no prior loss time recorded -- nothing to finalise")
        return
    loss = datetime.strptime(priorBootLossAt, CANONICAL_ISO_FORMAT).replace(tzinfo=UTC)
    lo = (loss - timedelta(seconds=LOSS_ROW_BEFORE_S)).strftime(CANONICAL_ISO_FORMAT)
    hi = (loss + timedelta(seconds=LOSS_ROW_AFTER_S)).strftime(CANONICAL_ISO_FORMAT)
    row = conn.execute(
        "SELECT drain_event_id, start_timestamp, start_vcell_v, drain_trigger, "
        "cut_step_mv, drain_rate_mv_s FROM battery_health_log "
        "WHERE start_timestamp >= ? AND start_timestamp <= ? "
        "ORDER BY drain_event_id DESC LIMIT 1",
        (lo, hi),
    ).fetchone()
    if row is None:
        logger.info("battery_health_log has no row for the loss at %s -- nothing to finalise",
                    priorBootLossAt)
        return
    drainId, startTs, startV, trigger, cutStep, rate = row
    if cutStep is None and priorBootVcellBeforeCutV is not None and startV is not None:
        conn.execute(
            "UPDATE battery_health_log SET cut_step_mv = ? WHERE drain_event_id = ?",
            (round(1000.0 * (priorBootVcellBeforeCutV - startV), 2), drainId),
        )
        conn.commit()
    if trigger != DRAIN_TRIGGER_MONTHLY_TEST or rate is not None:
        return
    cut = datetime.strptime(startTs, CANONICAL_ISO_FORMAT).replace(tzinfo=UTC)
    winLo = (cut + timedelta(seconds=WINDOW_SKIP_S)).strftime(CANONICAL_ISO_FORMAT)
    winHi = (cut + timedelta(seconds=TEST_HOLD_S)).strftime(CANONICAL_ISO_FORMAT)
    points = [
        (float(tsCapture), float(vcell))
        for tsCapture, vcell in conn.execute(
            "SELECT ts_capture, vcell_v FROM drain_vcell_trajectory "
            "WHERE ts_utc >= ? AND ts_utc <= ? AND vcell_v IS NOT NULL ORDER BY id",
            (winLo, winHi),
        )
    ]
    need = MIN_WINDOW_FILL * WINDOW_S
    if len(points) < need:
        return
    if max(t for t, _ in points) - min(t for t, _ in points) < need:
        return  # bunched samples do not cover the window
    slope = windowDrainRate(points)
    if slope is None:
        return
    conn.execute(
        "UPDATE battery_health_log SET drain_rate_mv_s = ?, window_start_s = ?, "
        "window_end_s = ? WHERE drain_event_id = ?",
        (round(slope, 5), WINDOW_SKIP_S, TEST_HOLD_S, drainId),
    )
    conn.commit()
