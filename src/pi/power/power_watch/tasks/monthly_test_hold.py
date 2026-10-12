################################################################################
# File Name: monthly_test_hold.py
# Purpose/Description: ARCH-065 -- hold the Pi on battery TEST_HOLD_S after an
#                      at-home cut, once a month, and label the open drain row
#                      as a monthly test (specs/battery-health-design.md sec 6).
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | ARCH-065 T5: created. Timings from
#               |                    | battery_capacity (controller ruling 8).
# 2026-10-03    | Atlas (ARCH-065a)  | T5 fix 1: the mark is scoped to this loss, runs before AND
#               |                    | after the hold, and can never skip the hold.
# 2026-10-03    | Atlas (ARCH-065a)  | Ruling 19: gated on the HOME STATE at the loss
#               |                    | (home_detector.AT_HOME_STATE_NAMES), not a sync
#               |                    | outcome; lossIso + loss generation snapshotted
#               |                    | once per run, so a hold left running by a
#               |                    | cancelled loss never labels the next loss's row;
#               |                    | the mark selects through battery_health.lossRowBand;
#               |                    | CANONICAL_ISO_FORMAT replaces the local literal.
################################################################################
"""ARCH-065: hold the Pi on battery TEST_HOLD_S after an at-home cut, once a month.

The drain-rate window (WINDOW_SKIP_S..TEST_HOLD_S after the cut) is computed at
the next boot (battery_health_finalize). This task only keeps power up and
labels the row. Power returning early is the sequencer's cancel path; the
interrupted row's window is short, so finalize writes no rate and it is not
counted.

A "counted monthly test" is DEFINED as ``drain_rate_mv_s IS NOT NULL`` -- the
rate is written only by battery_health_finalize when the window is full, so the
row itself is the single owner of the fact (no second runtime threshold).
"""
from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from src.common.time.helper import CANONICAL_ISO_FORMAT
from src.pi.network.home_detector import AT_HOME_STATE_NAMES
from src.pi.power.battery_capacity import TEST_HOLD_S
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    DRAIN_TRIGGER_MONTHLY_TEST,
    lossRowBand,
)
from src.pi.power.power_watch.contract import OutcomeKind

logger = logging.getLogger(__name__)


class MonthlyTestHoldTask:
    """ShutdownTask: sleeps the Pi on battery until holdSec after the cut.

    Everything that identifies THE loss -- its home state, its wall time and its
    generation (``HomeStateAtLoss``) -- is read ONCE at the start of ``run()``.
    When power returns mid-hold the sequencer returns but this thread sleeps on;
    if it wakes during a LATER loss the generation has moved and it labels
    nothing (Ruling 19, I1).
    """

    name = "monthly_test_hold"

    def __init__(
        self, *, homeStateName: Callable[[], str], isDue: Callable[[], bool],
        markOpenDrain: Callable[[str], int], secondsSinceCut: Callable[[], float],
        holdSec: float = TEST_HOLD_S, sleepFn: Callable[[float], None] | None = None,
        lossIso: Callable[[], str | None] = lambda: None,
        lossGeneration: Callable[[], int] = lambda: 0,
    ) -> None:
        """Args:
        homeStateName: The home state NAME at the loss (``HomeStateAtLoss.stateName``);
            the hold runs only when it is in ``AT_HOME_STATE_NAMES``.
        isDue: True when this pack has no counted monthly test in the interval.
        markOpenDrain: Labels the open drain row of the loss at the given lossIso
            and returns the rows updated (``markOpenDrainMonthlyTest``).
        secondsSinceCut: Seconds since this loss was observed.
        holdSec: Hold until this long after the cut (the SSOT TEST_HOLD_S).
        sleepFn: The wait; ``time.sleep`` when None.
        lossIso: This loss's wall time; None before any loss (nothing is marked).
        lossGeneration: ``HomeStateAtLoss.lossGeneration`` -- moves on every loss.
        """
        self._homeStateName = homeStateName
        self._isDue = isDue
        self._markOpenDrain = markOpenDrain
        self._lossIso = lossIso
        self._lossGeneration = lossGeneration
        self._secondsSinceCut = secondsSinceCut
        self._holdSec = float(holdSec)
        self._sleep = sleepFn or time.sleep

    def run(self) -> OutcomeKind:
        """Never raises. OK whether or not it held."""
        try:
            generation = self._lossGeneration()
            lossIso = self._lossIso()
            state = self._homeStateName()
            if state not in AT_HOME_STATE_NAMES:
                logger.info("powerwatch monthly test: skipped (not at home: %s)", state)
                return OutcomeKind.OK
            if not self._isDue():
                logger.info("powerwatch monthly test: skipped (not due)")
                return OutcomeKind.OK
            marked = self._mark(lossIso, generation)
            remaining = self._holdSec - self._secondsSinceCut()
            logger.info("powerwatch monthly test: holding %.0fs more (to %.0fs after the cut)",
                        max(0.0, remaining), self._holdSec)
            if remaining > 0:
                self._sleep(remaining)
            # The collector opens the row on its own thread; it may only have
            # landed during the hold. Idempotent.
            marked += self._mark(lossIso, generation)
            if marked == 0 and self._isCurrent(generation):
                logger.warning(
                    "powerwatch monthly test: no open drain row labelled for the loss at %s",
                    lossIso,
                )
        except Exception as exc:  # noqa: BLE001 -- a broken test must never block the shutdown
            logger.error("powerwatch monthly test: hold failed (%s) -- continuing the shutdown", exc)
        return OutcomeKind.OK

    def _isCurrent(self, generation: int) -> bool:
        return self._lossGeneration() == generation

    def _mark(self, lossIso: str | None, generation: int) -> int:
        """One mark for THE loss snapshotted at run start; a failure never skips the hold."""
        if lossIso is None:
            return 0
        try:
            if not self._isCurrent(generation):
                logger.info("powerwatch monthly test: a later loss began -- the hold for the "
                            "loss at %s labels nothing", lossIso)
                return 0
            return int(self._markOpenDrain(lossIso) or 0)
        except Exception as exc:  # noqa: BLE001 -- the hold matters more than the label
            logger.error("powerwatch monthly test: labelling the drain row failed (%s)", exc)
            return 0


def isMonthlyTestDue(dbPath: str, *, cellEpoch: str, nowIso: str, intervalDays: int) -> bool:
    """True unless a COUNTED monthly test (drain_rate_mv_s IS NOT NULL) of this pack ran in intervalDays."""
    since = (datetime.strptime(nowIso, CANONICAL_ISO_FORMAT).replace(tzinfo=UTC)
             - timedelta(days=intervalDays)).strftime(CANONICAL_ISO_FORMAT)
    conn = sqlite3.connect(dbPath, timeout=1.0)
    try:
        row = conn.execute(
            f"SELECT 1 FROM {BATTERY_HEALTH_LOG_TABLE} WHERE drain_trigger = ? AND cell_epoch = ? "
            "AND drain_rate_mv_s IS NOT NULL AND start_timestamp >= ? LIMIT 1",
            (DRAIN_TRIGGER_MONTHLY_TEST, cellEpoch, since),
        ).fetchone()
    finally:
        conn.close()
    return row is None


def markOpenDrainMonthlyTest(dbPath: str, *, lossIso: str) -> int:
    """Label the newest OPEN drain row of THIS loss as a monthly test.

    Only an open row (``end_timestamp IS NULL``) whose start lies in
    ``battery_health.lossRowBand(lossIso)`` qualifies -- the same band the boot
    finaliser selects with -- so an older still-open row, or a later loss's
    row, is never mislabelled. Returns the rows updated.
    """
    lo, hi = lossRowBand(lossIso)
    conn = sqlite3.connect(dbPath, timeout=1.0)
    try:
        cur = conn.execute(
            f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET drain_trigger = ? WHERE drain_event_id = "
            f"(SELECT MAX(drain_event_id) FROM {BATTERY_HEALTH_LOG_TABLE} "
            "WHERE end_timestamp IS NULL AND start_timestamp >= ? AND start_timestamp <= ?)",
            (DRAIN_TRIGGER_MONTHLY_TEST, lo, hi),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
