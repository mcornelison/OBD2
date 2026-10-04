################################################################################
# File Name: battery_health_verdict.py
# Purpose/Description: The battery HEALTH verdict + last-health-check producer
#   for the Battery Health card.
#
#   ARCH-065 (CIO 2026-10-02) REPLACED the US-504 rule.  The verdict answers one
#   question: after key-off at home, can the pack carry a full sync AND a
#   graceful shutdown?
#     T = time from key-off to the reserve floor (from this pack's newest
#         counted monthly test, shaped by its calibration drain when one exists)
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
    'PROVISIONAL_CUTOFF_V',
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

#: No counted monthly test exists for the CURRENT pack (or no pack is known).
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
#: value with battery_capacity.WINDOW_S but is a DIFFERENT quantity.
RESERVE_S: int = 600

#: The 450 mAh pouch's measured dropout; the current pack's is unmeasured until
#: its calibration drain, which is why a T projected to it is ``provisional``.
PROVISIONAL_CUTOFF_V: float = 3.44

# The canonical ISO-8601 UTC instant format every Pi writer stamps (TD-027).
_ISO: str = '%Y-%m-%dT%H:%M:%SZ'


# ================================================================================
# SQL.  Every value is BOUND from its owner -- no trigger or outcome literal.
# ================================================================================

#: The current pack = the cell_epoch of the newest row that carries one.
_PACK_SQL: str = (
    f"SELECT cell_epoch FROM {BATTERY_HEALTH_LOG_TABLE} "
    "WHERE cell_epoch IS NOT NULL ORDER BY drain_event_id DESC LIMIT 1"
)

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
        provisional: True when T was projected to PROVISIONAL_CUTOFF_V because
            the pack has no calibration drain yet.
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
    """
    try:
        now = datetime.strptime(nowIso, _ISO)
    except (TypeError, ValueError):
        return _unknown(REASON_CLOCK_UNREADABLE)
    rate = test.get('drain_rate_mv_s') if test else None
    if rate is None or not float(rate) < 0:
        return _unknown(REASON_NO_MONTHLY_TEST)
    rate = float(rate)
    lastTs = str(test['start_timestamp'])  # type: ignore[index]
    try:
        testAt = datetime.strptime(lastTs, _ISO)
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
        # Straight line from the window's end VCELL to the provisional cutoff,
        # minus the reserve.  Over-projects near empty -- hence the label.
        t = (float(test['window_end_s'])  # type: ignore[index]
             + 1000.0 * (float(test['end_vcell_v']) - PROVISIONAL_CUTOFF_V) / -rate  # type: ignore[index]
             - RESERVE_S)
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
        timeToFloorS=round(t), jobAvgS=round(job), jobMaxS=round(max(jobs)),
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
    """
    if database is None:
        return _unknown(REASON_NO_DATABASE)
    try:
        with database.connect() as conn:
            pack = conn.execute(_PACK_SQL).fetchone()
            if pack is None:
                return _unknown(REASON_NO_MONTHLY_TEST)
            cellEpoch = pack[0]
            testRow = conn.execute(
                _TEST_SQL, (DRAIN_TRIGGER_MONTHLY_TEST, cellEpoch)
            ).fetchone()
            calRow = conn.execute(
                _CAL_SQL, (DRAIN_TRIGGER_CALIBRATION, cellEpoch)
            ).fetchone()
            jobRows = conn.execute(
                _JOBS_SQL, (OutcomeKind.DELIVERED.name, JOB_AVG_COUNT)
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 -- unreadable log -> honest unknown
        logger.debug("battery-health verdict read failed (%s) -- unknown", exc)
        return _unknown(REASON_LOG_UNREADABLE)

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
    result = computeBatteryHealthVerdict(
        test=test, calibration=calibration, jobsS=jobsS, nowIso=nowIso,
    )
    if testRow is not None and result.verdict in _RESOLVED_VERDICTS and result.verdict != testRow[5]:
        _recordVerdict(database, drainEventId=testRow[0], verdict=result.verdict)
    return result


def _syncSeconds(startedAt: Any, endedAt: Any) -> float | None:
    """One sync's duration, or None for an unparseable or negative window.

    A row that does not parse does not vote -- it is never defaulted.  A
    negative duration is a wall-clock step mid-sync, not a measurement.
    """
    try:
        seconds = (datetime.strptime(str(endedAt), _ISO)
                   - datetime.strptime(str(startedAt), _ISO)).total_seconds()
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _recordVerdict(database: Any, *, drainEventId: int, verdict: str) -> None:
    """Write the verdict onto the monthly-test row (server history).

    Called ONLY when the computed verdict differs from the stored one: the
    reader runs on every card emit, and an unconditional UPDATE would make the
    card loop a continuous writer to the Pi's database (and re-mark the row
    for sync every tick).  A failure is logged and never costs the verdict --
    the card's answer does not depend on the history copy.
    """
    try:
        with database.connect() as conn:
            conn.execute(_WRITE_VERDICT_SQL, (verdict, drainEventId))
    except Exception as exc:  # noqa: BLE001 -- history copy only
        logger.debug("battery-health verdict history write failed (%s)", exc)
