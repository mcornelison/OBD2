################################################################################
# File Name: battery_health_verdict.py
# Purpose/Description: The battery HEALTH verdict + last-health-check producer
#   for the Battery Health card.
#
#   ARCH-065 (CIO 2026-10-02) REPLACED the US-504 rule.  The verdict answers one
#   question: after key-off at home, can the pack carry a full sync AND a
#   graceful shutdown?
#     T = time from key-off to the reserve floor (from this pack's newest
#         counted monthly test, shaped by its calibration drain when one exists;
#         without one, a straight line to config drainFloorVolts -- provisional)
#     J = the at-home job: the mean of the newest JOB_AVG_COUNT DELIVERED
#         shutdown syncs, each = confirm wait (config smoothingSec) + sync +
#         graceful poweroff allowance
#     good if T >= 1.2 J; degraded if J <= T < 1.2 J; replace if T < J.
#   Design: specs/battery-health-design.md sec 3, 8, 15.
#
#   Honest-instrument, load-bearing: `unknown` is the DEFAULT, and every
#   unknown names its cause (US-632).  A verdict manufactured out of NULLs is
#   strictly worse than the placeholder it replaces (Spool, 2026-08-01).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-504 verdict + last-health-check.
# 2026-08-03    | Ralph (Rex)  | US-527/TD-074 -- qualifying gate remapped from
#                               the RETIRED runtime_seconds>=600 duration gate
#                               to Spool's DEPTH gate (end_vcell_v <= 3.50 V
#                               AND runtime_seconds >= 60).  Bands UNCHANGED
#                               (Spool ruling c72677e) and now fully reachable.
# 2026-09-24    | Rex (US-683) | Qualifying query + _parseRow key on the typed
#                               close_reason: an un-checkpointed reap is
#                               excluded by type.  No other eligibility change.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T7: REWRITTEN.  Verdict = T vs J
#                               (good/degraded/replace) from the current pack's
#                               counted monthly test (+ calibration) and the
#                               at-home DELIVERED syncs.  The qualifying-drain
#                               rule, its constants and its three reasons are
#                               retired.  The resolved verdict is written onto
#                               the monthly-test row when it changes.
# 2026-10-03    | Atlas (ARCH-065a) | T7 fix 1: a NULL/non-numeric provisional
#                               input is log_unreadable (Ruling 16) and the
#                               compute runs inside the reader's guard; a
#                               floor-ended at-home drain newer than the counted
#                               test is replace (Ruling 13); T clamped at 0; the
#                               history write is bounded and warns once (17).
# 2026-10-03    | Atlas (ARCH-065a) | Ruling 19: the current pack is the CONFIG's
#                               (resolveCellEpoch, passed in as cellEpoch; 'unknown'
#                               -> no_monthly_test), never the newest row's
#                               (_PACK_SQL dropped); the provisional T projects to
#                               config drainFloorVolts -- the ONE reserve floor --
#                               with no extra RESERVE_S (PROVISIONAL_CUTOFF_V
#                               removed); CANONICAL_ISO_FORMAT replaces _ISO.
# ================================================================================
################################################################################

"""Battery-health verdict producer (ARCH-065: T vs J).

The verdict vocabulary defined here is the SINGLE vocabulary for the battery
health field end-to-end: this module -> ``battery_health_emitter`` -> the
``battery-health`` state file -> ``carousel.js``.

Severity framing (Spool, load-bearing): this signal is INFORMATIONAL at every
state INCLUDING ``replace``.  It must never render in alarm red and never
compete with coolant or a DTC STOP-tier alert on a driving surface.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.common.config.validator import CELL_EPOCH_UNKNOWN
from src.common.time.helper import CANONICAL_ISO_FORMAT
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    DRAIN_TRIGGER_CALIBRATION,
    DRAIN_TRIGGER_MONTHLY_TEST,
)
from src.pi.power.power_watch.contract import OutcomeKind

logger = logging.getLogger(__name__)

__all__ = [
    'BatteryHealthVerdict',
    'GREEN_MARGIN',
    'JOB_AVG_COUNT',
    'MIN_JOBS',
    'REASON_CLOCK_UNREADABLE',
    'REASON_LOG_UNREADABLE',
    'REASON_MONTHLY_TEST_STALE',
    'REASON_NO_DATABASE',
    'REASON_NO_MONTHLY_TEST',
    'REASON_TOO_FEW_SYNCS',
    'RESERVE_S',
    'SHUTDOWN_ALLOWANCE_S',
    'STALE_TEST_DAYS',
    'UNKNOWN_REASONS',
    'VERDICT_DEGRADED',
    'VERDICT_GOOD',
    'VERDICT_REPLACE',
    'VERDICT_UNKNOWN',
    'VERDICT_VALUES',
    'computeBatteryHealthVerdict',
    'readBatteryHealthVerdict',
]


# ================================================================================
# Verdict vocabulary
# ================================================================================

VERDICT_GOOD: str = 'good'
VERDICT_DEGRADED: str = 'degraded'
VERDICT_REPLACE: str = 'replace'
VERDICT_UNKNOWN: str = 'unknown'

#: Every value the ``health`` field of the battery-health state file may carry.
VERDICT_VALUES: tuple[str, ...] = (
    VERDICT_GOOD, VERDICT_DEGRADED, VERDICT_REPLACE, VERDICT_UNKNOWN,
)

#: The verdicts that are a MEASUREMENT (written onto the monthly-test row).
_RESOLVED_VERDICTS: frozenset[str] = frozenset(
    (VERDICT_GOOD, VERDICT_DEGRADED, VERDICT_REPLACE)
)


# ================================================================================
# Unknown-reason vocabulary (US-632; ARCH-065 sec 8)
# ================================================================================
# `unknown` is one WORD covering six different operational facts; the reason
# says which.  snake_case machine words -- carousel.js maps them to text in
# BATTERY_HEALTH_REASON_TEXT, and a guard test holds that table equal to
# UNKNOWN_REASONS.

#: No database handle at all (bench, or wiring not yet built).
REASON_NO_DATABASE: str = 'no_database'

#: The log exists but could not be read -- locked, pre-migration, corrupt.  An
#: INSTRUMENT failure, never to masquerade as "never measured".
REASON_LOG_UNREADABLE: str = 'log_unreadable'

#: ``nowIso`` was unparseable, so nothing can be age-checked.
REASON_CLOCK_UNREADABLE: str = 'clock_unreadable'

#: No counted monthly test exists for the CURRENT pack (config pi.power.cellEpoch,
#: via resolveCellEpoch), or no pack is configured ('unknown').
#: A new pack never inherits the old pack's verdict.
REASON_NO_MONTHLY_TEST: str = 'no_monthly_test'

#: The current pack's newest counted test is older than STALE_TEST_DAYS.
REASON_MONTHLY_TEST_STALE: str = 'monthly_test_stale'

#: Fewer than MIN_JOBS at-home DELIVERED shutdown syncs to size J from.
REASON_TOO_FEW_SYNCS: str = 'too_few_syncs'

#: Every reason an ``unknown`` verdict may carry.  A resolved verdict carries
#: None -- the reason explains an ABSENCE.
UNKNOWN_REASONS: tuple[str, ...] = (
    REASON_NO_DATABASE,
    REASON_LOG_UNREADABLE,
    REASON_CLOCK_UNREADABLE,
    REASON_NO_MONTHLY_TEST,
    REASON_MONTHLY_TEST_STALE,
    REASON_TOO_FEW_SYNCS,
)


# ================================================================================
# ARCH-065 constants (design sec 8; CIO 2026-10-02).  The monthly-test window
# timings live in battery_capacity.py; the confirm wait is config
# pi.powerWatch.smoothingSec, passed in.  These are the verdict's own numbers.
# ================================================================================

#: good if T >= GREEN_MARGIN * J (CIO 2026-10-02).
GREEN_MARGIN: float = 1.2

#: A counted monthly test older than this is not health data.
STALE_TEST_DAYS: int = 45

#: J = the mean of this many newest DELIVERED at-home syncs.
JOB_AVG_COUNT: int = 10

#: Fewer DELIVERED syncs than this and J is not sized.
MIN_JOBS: int = 3

#: The graceful poweroff after the sync (measured ~4 s).
SHUTDOWN_ALLOWANCE_S: float = 4.0

#: The reserve left at the floor: 10 minutes (CIO 2026-10-02).  Coincides in
#: value with battery_capacity.WINDOW_S but is a DIFFERENT quantity.  Used by the
#: calibration tool to place floor_vcell_v; the provisional T does NOT subtract
#: it -- there the floor is config drainFloorVolts itself (sec 15.3).
RESERVE_S: int = 600

#: The verdict-history write waits at most this long for another writer's lock
#: (Ruling 17): the reader runs on the card tick and must never stall on it.
_HISTORY_WRITE_BUSY_TIMEOUT_MS: int = 500

#: The first failed history write is a WARNING; later ones are DEBUG, so a
#: persistent lock cannot flood the journal from the card tick.
_historyWriteWarned: bool = False


# ================================================================================
# SQL.  Every value is BOUND from its owner -- no trigger or outcome literal.
# ================================================================================

# The current pack is NOT read from the log: it is config pi.power.cellEpoch
# (resolveCellEpoch), passed in -- the same resolver the writers and
# isMonthlyTestDue use (Ruling 19).

#: The pack's newest COUNTED monthly test.  "Counted" has one definition
#: everywhere (isMonthlyTestDue, the boot finaliser): drain_rate_mv_s IS NOT NULL.
_TEST_SQL: str = (
    "SELECT drain_event_id, start_timestamp, drain_rate_mv_s, end_vcell_v, "
    "       window_end_s, verdict "
    f"FROM {BATTERY_HEALTH_LOG_TABLE} "
    "WHERE drain_trigger = ? AND cell_epoch = ? AND drain_rate_mv_s IS NOT NULL "
    "ORDER BY start_timestamp DESC, drain_event_id DESC LIMIT 1"
)

#: The pack's newest calibration drain.
_CAL_SQL: str = (
    "SELECT t_floor_s, drain_rate_mv_s "
    f"FROM {BATTERY_HEALTH_LOG_TABLE} "
    "WHERE drain_trigger = ? AND cell_epoch = ? AND t_floor_s IS NOT NULL "
    "ORDER BY start_timestamp DESC, drain_event_id DESC LIMIT 1"
)

#: The pack's newest drain the reserve floor ended AT HOME (Ruling 13): the
#: boot finaliser stamps verdict=replace on it.  ``drain_rate_mv_s IS NULL``
#: separates that event from a counted test's own verdict history.  Ordered by
#: start_timestamp, like _TEST_SQL, so the two are compared on one clock.
_FLOOR_SQL: str = (
    "SELECT start_timestamp "
    f"FROM {BATTERY_HEALTH_LOG_TABLE} "
    "WHERE cell_epoch = ? AND verdict = ? AND drain_rate_mv_s IS NULL "
    "ORDER BY start_timestamp DESC, drain_event_id DESC LIMIT 1"
)

#: The newest DELIVERED at-home shutdown syncs.  Ordered by rowid (insertion),
#: not recorded_at: a dead-RTC boot stamps a pre-NTP wall clock and would
#: mis-order (the prior_shutdown_summary precedent).
_JOBS_SQL: str = (
    "SELECT prior_boot_sync_started_at, prior_boot_sync_ended_at "
    "FROM startup_log "
    "WHERE prior_boot_sync_outcome = ? "
    "  AND prior_boot_sync_started_at IS NOT NULL "
    "  AND prior_boot_sync_ended_at IS NOT NULL "
    "ORDER BY rowid DESC LIMIT ?"
)

#: The history write -- only when the stored value differs (see the reader).
_WRITE_VERDICT_SQL: str = (
    f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET verdict = ? WHERE drain_event_id = ?"
)


# ================================================================================
# Result
# ================================================================================


@dataclass(frozen=True)
class BatteryHealthVerdict:
    """The computed battery-health facts the card consumes.

    Attributes:
        verdict: One of :data:`VERDICT_VALUES`.
        lastHealthCheckTs: The counted monthly test's ``start_timestamp``, or
            None when the pack has none.  Kept on the stale / too-few-syncs
            unknowns: that date is itself the signal (F-9).
        reason: One of :data:`UNKNOWN_REASONS` when ``unknown``; else None.
        timeToFloorS: T, seconds from key-off to the reserve floor.
        jobAvgS: J, the mean at-home job in seconds.
        jobMaxS: The longest of the jobs J was averaged over.
        provisional: True when T was projected in a straight line to config
            drainFloorVolts because the pack has no calibration drain yet.
    """

    verdict: str
    lastHealthCheckTs: str | None
    reason: str | None = None
    timeToFloorS: int | None = None
    jobAvgS: int | None = None
    jobMaxS: int | None = None
    provisional: bool = False


def _unknown(reason: str, lastTs: str | None = None) -> BatteryHealthVerdict:
    return BatteryHealthVerdict(verdict=VERDICT_UNKNOWN, lastHealthCheckTs=lastTs, reason=reason)


# ================================================================================
# Pure computation
# ================================================================================


def computeBatteryHealthVerdict(
    *,
    test: Mapping[str, Any] | None,
    calibration: Mapping[str, Any] | None,
    jobsS: list[float],
    nowIso: str,
    drainFloorVolts: float,
    floorEndedTs: str | None = None,
) -> BatteryHealthVerdict:
    """T vs J.  Pure: no clock, no database.

    Args:
        test: The current pack's newest counted monthly test
            (``start_timestamp``, ``drain_rate_mv_s`` (negative), ``end_vcell_v``,
            ``window_end_s``), or None.
        calibration: The pack's calibration (``t_floor_s``, ``drain_rate_mv_s``),
            or None -- T is then a provisional straight-line projection.
        jobsS: At-home job durations in seconds, NEWEST FIRST.
        nowIso: Canonical ISO-8601 UTC instant for the staleness check.
        drainFloorVolts: Config ``pi.powerWatch.drainFloorVolts`` -- the reserve
            floor the shutdown sequencer stops at (sec 15.3).  The provisional T
            projects to it.
        floorEndedTs: ``start_timestamp`` of the pack's newest drain that the
            reserve floor ended at home, or None.  Newer than the counted test
            -> ``replace``: the pack failed the very job the verdict judges, so
            it outranks stale / too-few-syncs / no-test (Ruling 13).
    """
    testTs = str(test.get('start_timestamp') or '') if test else ''
    if floorEndedTs and floorEndedTs > testTs:
        return BatteryHealthVerdict(verdict=VERDICT_REPLACE, lastHealthCheckTs=floorEndedTs)
    try:
        now = datetime.strptime(nowIso, CANONICAL_ISO_FORMAT)
    except (TypeError, ValueError):
        return _unknown(REASON_CLOCK_UNREADABLE)
    rate = test.get('drain_rate_mv_s') if test else None
    if rate is None or not float(rate) < 0:
        return _unknown(REASON_NO_MONTHLY_TEST)
    rate = float(rate)
    lastTs = str(test['start_timestamp'])  # type: ignore[index]
    try:
        testAt = datetime.strptime(lastTs, CANONICAL_ISO_FORMAT)
    except ValueError:
        # The stored test date does not parse: the LOG is at fault, not the clock.
        return _unknown(REASON_LOG_UNREADABLE)
    if now - testAt > timedelta(days=STALE_TEST_DAYS):
        return _unknown(REASON_MONTHLY_TEST_STALE, lastTs)
    jobs = list(jobsS[:JOB_AVG_COUNT])
    if len(jobs) < MIN_JOBS:
        return _unknown(REASON_TOO_FEW_SYNCS, lastTs)

    calRate = calibration.get('drain_rate_mv_s') if calibration else None
    if calibration and calibration.get('t_floor_s') and calRate is not None and float(calRate) < 0:
        # Shape from the calibration, scale from this month's rate.
        t = float(calibration['t_floor_s']) * (float(calRate) / rate)
        provisional = False
    else:
        # Straight line from the window's end VCELL to the reserve floor (config
        # drainFloorVolts, where the sequencer stops -- the reserve lies below
        # it, so nothing more is subtracted).  Over-projects near empty -- hence
        # the label.
        # A NULL or non-numeric input here is an unreadable LOG row (Ruling 16):
        # a test reaped without a checkpoint keeps end_vcell_v NULL yet can be
        # rated from its trajectory.
        try:
            t = (float(test['window_end_s'])  # type: ignore[index]
                 + 1000.0 * (float(test['end_vcell_v']) - float(drainFloorVolts))  # type: ignore[index]
                 / -rate)
        except (TypeError, ValueError):
            return _unknown(REASON_LOG_UNREADABLE, lastTs)
        provisional = True

    job = sum(jobs) / len(jobs)
    if t >= GREEN_MARGIN * job:
        verdict = VERDICT_GOOD
    elif t >= job:
        verdict = VERDICT_DEGRADED
    else:
        verdict = VERDICT_REPLACE
    return BatteryHealthVerdict(
        verdict=verdict, lastHealthCheckTs=lastTs, reason=None,
        # T < 0 (the pack is already past the floor) publishes as 0; the
        # verdict above is unaffected (Ruling 17).
        timeToFloorS=round(max(t, 0.0)), jobAvgS=round(job), jobMaxS=round(max(jobs)),
        provisional=provisional,
    )


# ================================================================================
# Database reader
# ================================================================================


def readBatteryHealthVerdict(
    *,
    database: Any | None,
    nowIso: str,
    smoothingSec: float,
    cellEpoch: str,
    drainFloorVolts: float,
) -> BatteryHealthVerdict:
    """Read the current pack's facts and compute the verdict.

    Best-effort by contract: an absent or unreadable log returns the honest
    unknown rather than raising into the card-emit loop.

    Args:
        database: An object exposing ``connect()`` as a context manager
            yielding a DB-API connection, or None (bench / not yet built).
        nowIso: Canonical ISO-8601 UTC instant for the staleness check.
        smoothingSec: Config ``pi.powerWatch.smoothingSec`` -- the confirm wait
            before the shutdown window opens, the first term of every job.
            Required: there is no default that could hide a missing value.
        cellEpoch: The CURRENT pack -- ``resolveCellEpoch(config)``, the one
            resolver the drain writers and ``isMonthlyTestDue`` also use.
            ``'unknown'`` (no pack configured) -> ``no_monthly_test``.  Required.
        drainFloorVolts: Config ``pi.powerWatch.drainFloorVolts`` -- the one
            reserve floor; the provisional T projects to it.  Required.
    """
    if database is None:
        return _unknown(REASON_NO_DATABASE)
    if not cellEpoch or cellEpoch == CELL_EPOCH_UNKNOWN:
        return _unknown(REASON_NO_MONTHLY_TEST)
    try:
        with database.connect() as conn:
            testRow = conn.execute(
                _TEST_SQL, (DRAIN_TRIGGER_MONTHLY_TEST, cellEpoch)
            ).fetchone()
            calRow = conn.execute(
                _CAL_SQL, (DRAIN_TRIGGER_CALIBRATION, cellEpoch)
            ).fetchone()
            jobRows = conn.execute(
                _JOBS_SQL, (OutcomeKind.DELIVERED.name, JOB_AVG_COUNT)
            ).fetchall()
            floorRow = conn.execute(
                _FLOOR_SQL, (cellEpoch, VERDICT_REPLACE)
            ).fetchone()
        result = _computeFromRows(testRow, calRow, jobRows, floorRow,
                                  nowIso=nowIso, smoothingSec=smoothingSec,
                                  drainFloorVolts=drainFloorVolts)
    except Exception as exc:  # noqa: BLE001 -- unreadable log -> honest unknown
        logger.debug("battery-health verdict read failed (%s) -- unknown", exc)
        return _unknown(REASON_LOG_UNREADABLE)

    # The history copy belongs to the TEST row: only a verdict the test
    # produced (not a floor-ended drain's replace) is written onto it.
    if (testRow is not None and result.verdict in _RESOLVED_VERDICTS
            and result.lastHealthCheckTs == testRow[1] and result.verdict != testRow[5]):
        _recordVerdict(database, drainEventId=testRow[0], verdict=result.verdict)
    return result


def _computeFromRows(
    testRow: Any, calRow: Any, jobRows: Any, floorRow: Any,
    *, nowIso: str, smoothingSec: float, drainFloorVolts: float,
) -> BatteryHealthVerdict:
    """Map the fetched rows and compute.  Runs inside the reader's guard."""
    test = None
    if testRow is not None:
        test = {
            'start_timestamp': testRow[1],
            'drain_rate_mv_s': testRow[2],
            'end_vcell_v': testRow[3],
            'window_end_s': testRow[4],
        }
    calibration = None
    if calRow is not None:
        calibration = {'t_floor_s': calRow[0], 'drain_rate_mv_s': calRow[1]}
    jobsS = [
        float(smoothingSec) + syncS + SHUTDOWN_ALLOWANCE_S
        for syncS in (_syncSeconds(row[0], row[1]) for row in jobRows)
        if syncS is not None
    ]
    return computeBatteryHealthVerdict(
        test=test, calibration=calibration, jobsS=jobsS, nowIso=nowIso,
        drainFloorVolts=drainFloorVolts, floorEndedTs=floorRow[0] if floorRow is not None else None,
    )


def _syncSeconds(startedAt: Any, endedAt: Any) -> float | None:
    """One sync's duration, or None for an unparseable or negative window.

    A row that does not parse does not vote -- it is never defaulted.  A
    negative duration is a wall-clock step mid-sync, not a measurement.
    """
    try:
        seconds = (datetime.strptime(str(endedAt), CANONICAL_ISO_FORMAT)
                   - datetime.strptime(str(startedAt), CANONICAL_ISO_FORMAT)).total_seconds()
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _recordVerdict(database: Any, *, drainEventId: int, verdict: str) -> None:
    """Write the verdict onto the monthly-test row (server history).

    Called ONLY when the computed verdict differs from the stored one: the
    reader runs on every card emit, and an unconditional UPDATE would make the
    card loop a continuous writer to the Pi's database (and re-mark the row
    for sync every tick).  A failure never costs the verdict -- the card's
    answer does not depend on the history copy.  The write waits at most
    _HISTORY_WRITE_BUSY_TIMEOUT_MS for a lock; the first failure is a WARNING,
    later ones DEBUG (Ruling 17).
    """
    global _historyWriteWarned
    try:
        with database.connect() as conn:
            conn.execute(f"PRAGMA busy_timeout = {_HISTORY_WRITE_BUSY_TIMEOUT_MS}")
            conn.execute(_WRITE_VERDICT_SQL, (verdict, drainEventId))
    except Exception as exc:  # noqa: BLE001 -- history copy only
        if not _historyWriteWarned:
            _historyWriteWarned = True
            logger.warning("battery-health verdict history write failed (%s) -- "
                           "the card verdict is unaffected; later failures log at DEBUG", exc)
        else:
            logger.debug("battery-health verdict history write failed (%s)", exc)
