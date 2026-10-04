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

from src.pi.power.battery_capacity import TEST_HOLD_S
from src.pi.power.battery_health import BATTERY_HEALTH_LOG_TABLE, DRAIN_TRIGGER_MONTHLY_TEST
from src.pi.power.power_watch.contract import OutcomeKind

logger = logging.getLogger(__name__)

#: Sync outcomes that prove the car was at home.
AT_HOME_OUTCOMES: frozenset[OutcomeKind] = frozenset({
    OutcomeKind.DELIVERED, OutcomeKind.STALLED, OutcomeKind.AT_HOME_SERVER_DOWN,
    OutcomeKind.PROBE_MISCONFIGURED,
})
_ISO = "%Y-%m-%dT%H:%M:%SZ"


class MonthlyTestHoldTask:
    """ShutdownTask: sleeps the Pi on battery until holdSec after the cut."""

    name = "monthly_test_hold"

    def __init__(
        self, *, lastSyncOutcome: Callable[[], OutcomeKind | None], isDue: Callable[[], bool],
        markOpenDrain: Callable[[], int], secondsSinceCut: Callable[[], float],
        holdSec: float = TEST_HOLD_S, sleepFn: Callable[[float], None] | None = None,
        lossIso: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._lastSyncOutcome = lastSyncOutcome
        self._isDue = isDue
        self._markOpenDrain = markOpenDrain
        self._lossIso = lossIso
        self._secondsSinceCut = secondsSinceCut
        self._holdSec = float(holdSec)
        self._sleep = sleepFn or time.sleep

    def run(self) -> OutcomeKind:
        """Never raises. OK whether or not it held."""
        try:
            outcome = self._lastSyncOutcome()
            if outcome not in AT_HOME_OUTCOMES:
                logger.info("powerwatch monthly test: skipped (not at home: %s)", outcome)
                return OutcomeKind.OK
            if not self._isDue():
                logger.info("powerwatch monthly test: skipped (not due)")
                return OutcomeKind.OK
            marked = self._mark()
            remaining = self._holdSec - self._secondsSinceCut()
            logger.info("powerwatch monthly test: holding %.0fs more (to %.0fs after the cut)",
                        max(0.0, remaining), self._holdSec)
            if remaining > 0:
                self._sleep(remaining)
            # The collector opens the row on its own thread; it may only have
            # landed during the hold. Idempotent.
            marked += self._mark()
            if marked == 0:
                logger.warning(
                    "powerwatch monthly test: no open drain row labelled for the loss at %s",
                    self._lossIso(),
                )
        except Exception as exc:  # noqa: BLE001 -- a broken test must never block the shutdown
            logger.error("powerwatch monthly test: hold failed (%s) -- continuing the shutdown", exc)
        return OutcomeKind.OK


    def _mark(self) -> int:
        """One mark attempt; a failure is logged and never skips the hold."""
        try:
            return int(self._markOpenDrain() or 0)
        except Exception as exc:  # noqa: BLE001 -- the hold matters more than the label
            logger.error("powerwatch monthly test: labelling the drain row failed (%s)", exc)
            return 0


#: The collector opens the row on its own poll; allow its clock to lead ours.
_ROW_OPEN_SLACK_S = 5


def isMonthlyTestDue(dbPath: str, *, cellEpoch: str, nowIso: str, intervalDays: int) -> bool:
    """True unless a COUNTED monthly test (drain_rate_mv_s IS NOT NULL) of this pack ran in intervalDays."""
    since = (datetime.strptime(nowIso, _ISO).replace(tzinfo=UTC)
             - timedelta(days=intervalDays)).strftime(_ISO)
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

    Only a row opened at or after ``lossIso`` minus a small slack qualifies, so
    an older still-open row is never mislabelled. Returns the rows updated.
    """
    floorIso = (datetime.strptime(lossIso, _ISO).replace(tzinfo=UTC)
                - timedelta(seconds=_ROW_OPEN_SLACK_S)).strftime(_ISO)
    conn = sqlite3.connect(dbPath, timeout=1.0)
    try:
        cur = conn.execute(
            f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET drain_trigger = ? WHERE drain_event_id = "
            f"(SELECT MAX(drain_event_id) FROM {BATTERY_HEALTH_LOG_TABLE} "
            "WHERE end_timestamp IS NULL AND start_timestamp >= ?)",
            (DRAIN_TRIGGER_MONTHLY_TEST, floorIso),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
