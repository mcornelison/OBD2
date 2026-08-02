################################################################################
# File Name: battery_health_verdict.py
# Purpose/Description: US-504 -- the battery HEALTH verdict + last-health-check
#   producer for the consolidated Health card's Battery section (F-123).  The
#   card carried a HARDCODED health="unknown" / lastHealthCheckTs=None because
#   no producer existed; this module is that producer, built to Spool's [EXACT]
#   spec (offices/pm/inbox/2026-08-01-from-spool-us504-battery-health-verdict-
#   source.md).
#
#   Source = ``battery_health_log`` runtime-to-cutoff, NOT a live MAX17048 spot
#   read: health is capacity FADE over time and a spot voltage cannot see it.
#   Runtime under a known production load IS the capacity measurement.
#
#   Honest-instrument, load-bearing: `unknown` is the DEFAULT, not a failure
#   mode.  Fewer than 3 qualifying drains, any NULL required input, an
#   unreadable log, an unparseable clock, or health data older than 90 days all
#   resolve to `unknown`.  A verdict manufactured out of NULLs is strictly worse
#   than the placeholder it replaces (Spool, 2026-08-01).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-504 verdict + last-health-check.
# ================================================================================
################################################################################

"""Battery-health verdict producer (US-504 / Spool [EXACT] spec).

The verdict vocabulary defined here is the SINGLE vocabulary for the battery
health field end-to-end: this module -> ``battery_health_emitter`` -> the
``battery-health`` state file -> ``carousel.js``.  It replaces the earlier
green/attn/low display tiers, which were a second enum for the same fact (the
cross-module enum-identity class of bug that cost the 9-drain saga).

Severity framing (Spool, load-bearing): this signal is INFORMATIONAL at every
state INCLUDING ``replace``.  The UPS's job is carrying the Pi through power
loss to a clean shutdown -- that needs well under a minute and we measure ~12,
a 10x margin.  ``replace`` means the data-integrity margin has thinned, NOT that
anything on the car is at risk, so it must never render in alarm red and never
compete with coolant or a DTC STOP-tier alert on a driving surface.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    'BatteryHealthVerdict',
    'DEGRADED_BASELINE_FRACTION',
    'DEGRADED_MIN_RUNTIME_S',
    'GOOD_BASELINE_FRACTION',
    'GOOD_MIN_RUNTIME_S',
    'MEDIAN_SAMPLE_COUNT',
    'QUALIFYING_LOAD_CLASS',
    'QUALIFYING_MIN_RUNTIME_S',
    'RUNTIME_BASELINE_S',
    'STALE_HEALTH_CHECK_DAYS',
    'TRAILING_WINDOW_DAYS',
    'VERDICT_DEGRADED',
    'VERDICT_GOOD',
    'VERDICT_REPLACE',
    'VERDICT_UNKNOWN',
    'VERDICT_VALUES',
    'computeBatteryHealthVerdict',
    'readBatteryHealthVerdict',
    'verdictForMedianRuntime',
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


# ================================================================================
# Spool [EXACT] constants -- flag Spool before ANY drift
# ================================================================================
# groundingRef: offices/pm/inbox/2026-08-01-from-spool-us504-battery-health-
# verdict-source.md (Spool, Tuning SME).  Every number below is marked [EXACT]
# in that ruling and is load-bearing.

#: Only the real production drain measures the pack under its real load.
QUALIFYING_LOAD_CLASS: str = 'production'

#: [EXACT:600] Below this the pack never approached cutoff, so the run measured
#: nothing about capacity (key-cycles + aborts sit under 150 s).
QUALIFYING_MIN_RUNTIME_S: int = 600

#: [EXACT:727] Measured mean of the 11 qualifying drains 2026-05-09 -> 05-16
#: (range 617-831 s).  The reference point the bands are a fraction of.
RUNTIME_BASELINE_S: int = 727

#: [EXACT:80] 80%-of-rated-capacity is the standard end-of-useful-life
#: convention for lithium cells.
GOOD_BASELINE_FRACTION: float = 0.80

#: [EXACT:60] Below this Spool stops trusting the UPS margin at all.
DEGRADED_BASELINE_FRACTION: float = 0.60

#: [EXACT:180] Qualifying drains older than this do not count toward the
#: 3-sample minimum.
TRAILING_WINDOW_DAYS: int = 180

#: [EXACT:90] Health data older than this is not health data -- the verdict is
#: forced to unknown regardless of which way the numbers point.
STALE_HEALTH_CHECK_DAYS: int = 90

#: Median of the last 3, not the last 1: observed single-drain scatter is
#: 617-831 s (+/-15% around the mean), so one low reading would false-alarm.
MEDIAN_SAMPLE_COUNT: int = 3

#: Spool states the bands both as percentages and as seconds (>=582 / 436-582 /
#: <436).  Deriving the seconds from the percentages keeps ONE definition; the
#: test suite pins that the derivation reproduces his stated seconds exactly.
GOOD_MIN_RUNTIME_S: int = round(RUNTIME_BASELINE_S * GOOD_BASELINE_FRACTION)
DEGRADED_MIN_RUNTIME_S: int = round(
    RUNTIME_BASELINE_S * DEGRADED_BASELINE_FRACTION
)

# The canonical ISO-8601 UTC instant format every Pi writer stamps (TD-027).
_CANONICAL_ISO_FORMAT: str = '%Y-%m-%dT%H:%M:%SZ'

_QUALIFYING_ROW_SQL: str = (
    "SELECT start_timestamp, end_timestamp, runtime_seconds, load_class "
    "FROM battery_health_log "
    "WHERE end_timestamp IS NOT NULL "
    "  AND load_class = ? "
    "  AND runtime_seconds IS NOT NULL "
    "  AND runtime_seconds >= ? "
    "ORDER BY start_timestamp DESC"
)


# ================================================================================
# Result
# ================================================================================


@dataclass(frozen=True)
class BatteryHealthVerdict:
    """The computed battery-health facts the card consumes.

    Attributes:
        verdict: One of :data:`VERDICT_VALUES`.  ``unknown`` is the honest
            default -- never a fallback that hides a computation failure.
        lastHealthCheckTs: ``MAX(start_timestamp)`` over QUALIFYING rows, or
            None when no real health check has ever completed.  Reported even
            when the verdict is unknown: that date is itself the signal.
        qualifyingCount: How many rows passed the gate (all time).  Diagnostic
            only -- the card does not render it.
        medianRuntimeS: The median of the last :data:`MEDIAN_SAMPLE_COUNT`
            qualifying drains inside the trailing window, or None when the
            verdict is unknown.
    """

    verdict: str
    lastHealthCheckTs: str | None
    qualifyingCount: int
    medianRuntimeS: int | None


_UNKNOWN_NO_DATA = BatteryHealthVerdict(
    verdict=VERDICT_UNKNOWN,
    lastHealthCheckTs=None,
    qualifyingCount=0,
    medianRuntimeS=None,
)


# ================================================================================
# Pure computation
# ================================================================================


def computeBatteryHealthVerdict(
    *,
    rows: Iterable[Mapping[str, Any]],
    nowIso: str,
) -> BatteryHealthVerdict:
    """Compute the verdict + last-health-check from battery_health_log rows.

    Pure: no clock, no database.  ``rows`` may contain non-qualifying rows --
    the gate is applied here as well as in SQL so a caller that hands over an
    unfiltered table cannot smuggle a partial drain into the verdict.

    Args:
        rows: Mappings with ``start_timestamp`` / ``end_timestamp`` /
            ``runtime_seconds`` / ``load_class`` keys, in any order.
        nowIso: Canonical ISO-8601 UTC instant used for the trailing-window
            and staleness comparisons.  An unparseable value yields
            ``unknown`` -- a clock we cannot read cannot age-check the data.

    Returns:
        The :class:`BatteryHealthVerdict`.
    """
    qualifying = [
        parsed
        for parsed in (_parseRow(row) for row in rows)
        if parsed is not None
    ]
    if not qualifying:
        return _UNKNOWN_NO_DATA

    # Newest first.  Sorting here (not trusting the caller's order) is what
    # makes "the last 3 drains" mean the last 3 by CLOCK, not by row order.
    qualifying.sort(key=lambda item: item[0], reverse=True)
    lastCheckAt, _, lastCheckTs = qualifying[0]

    unknown = BatteryHealthVerdict(
        verdict=VERDICT_UNKNOWN,
        lastHealthCheckTs=lastCheckTs,
        qualifyingCount=len(qualifying),
        medianRuntimeS=None,
    )

    now = _parseIso(nowIso)
    if now is None:
        return unknown

    # Staleness override -- checked BEFORE the numbers so a stale reading can
    # never paint a confident verdict of any colour.
    if (now - lastCheckAt) > timedelta(days=STALE_HEALTH_CHECK_DAYS):
        return unknown

    windowStart = now - timedelta(days=TRAILING_WINDOW_DAYS)
    inWindow = [item for item in qualifying if item[0] >= windowStart]
    if len(inWindow) < MEDIAN_SAMPLE_COUNT:
        return unknown

    sample = sorted(item[1] for item in inWindow[:MEDIAN_SAMPLE_COUNT])
    median = sample[MEDIAN_SAMPLE_COUNT // 2]
    return BatteryHealthVerdict(
        verdict=verdictForMedianRuntime(median),
        lastHealthCheckTs=lastCheckTs,
        qualifyingCount=len(qualifying),
        medianRuntimeS=median,
    )


# ================================================================================
# Database reader
# ================================================================================


def readBatteryHealthVerdict(
    *,
    database: Any | None,
    nowIso: str,
) -> BatteryHealthVerdict:
    """Read the qualifying drain history and compute the verdict.

    Best-effort by contract: an absent or unreadable ``battery_health_log``
    (fresh Pi, pre-migration DB, locked file) returns the honest unknown rather
    than raising into the card-emit loop.

    Args:
        database: An object exposing ``connect()`` as a context manager
            yielding a DB-API connection, or None (bench / not yet built).
        nowIso: Canonical ISO-8601 UTC instant for the age comparisons.

    Returns:
        The :class:`BatteryHealthVerdict`; ``unknown`` on any read failure.
    """
    if database is None:
        return _UNKNOWN_NO_DATA
    try:
        with database.connect() as conn:
            fetched = conn.execute(
                _QUALIFYING_ROW_SQL,
                (QUALIFYING_LOAD_CLASS, QUALIFYING_MIN_RUNTIME_S),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 -- unreadable log -> honest unknown
        logger.debug("battery-health verdict read failed (%s) -- unknown", exc)
        return _UNKNOWN_NO_DATA

    rows = [
        {
            'start_timestamp': row[0],
            'end_timestamp': row[1],
            'runtime_seconds': row[2],
            'load_class': row[3],
        }
        for row in fetched
    ]
    return computeBatteryHealthVerdict(rows=rows, nowIso=nowIso)


# ================================================================================
# Internal helpers
# ================================================================================


def verdictForMedianRuntime(medianRuntimeS: int) -> str:
    """Map a median drain runtime to its Spool band.

    OPEN SPEC ISSUE (filed to Spool 2026-08-02, ``offices/tuner/inbox/
    2026-08-02-from-ralph-us504-gate-band-overlap-and-writer-gap.md``; NOT
    drifted here): the
    qualifying gate is ``runtime_seconds >= 600`` while the degraded band is
    436-582 s and replace is < 436 s -- both entirely BELOW the gate.  Every
    row that survives the gate therefore lands in the good band, so through the
    real pipeline ``degraded`` and ``replace`` are unreachable and a pack that
    genuinely dies at 500 s is filtered out as a "partial" drain rather than
    reported as degraded.  Both numbers are [EXACT] Spool values, so this
    module implements them verbatim; the bands live in this separate public
    function so the mapping stays fully exercised and the day Spool rules on
    the gate/band overlap, only the gate constant moves.
    """
    if medianRuntimeS >= GOOD_MIN_RUNTIME_S:
        return VERDICT_GOOD
    if medianRuntimeS >= DEGRADED_MIN_RUNTIME_S:
        return VERDICT_DEGRADED
    return VERDICT_REPLACE


def _parseRow(
    row: Mapping[str, Any],
) -> tuple[datetime, int, str] | None:
    """Return ``(startAt, runtimeSeconds, startTs)`` for a QUALIFYING row.

    None when the row fails the gate for any reason -- unclosed drain, wrong
    load class, missing/short runtime, or an unparseable start timestamp.  A
    NULL required input is never silently defaulted; the row simply does not
    vote.
    """
    if row.get('end_timestamp') is None:
        return None
    if row.get('load_class') != QUALIFYING_LOAD_CLASS:
        return None

    runtime = row.get('runtime_seconds')
    if runtime is None:
        return None
    try:
        runtimeSeconds = int(runtime)
    except (TypeError, ValueError):
        return None
    if runtimeSeconds < QUALIFYING_MIN_RUNTIME_S:
        return None

    startTs = row.get('start_timestamp')
    startAt = _parseIso(startTs)
    if startAt is None:
        return None
    return (startAt, runtimeSeconds, str(startTs))


def _parseIso(value: Any) -> datetime | None:
    """Parse a canonical ISO-8601 UTC instant to a naive-UTC datetime.

    Returns None for anything unparseable -- the callers treat that as a NULL
    required input rather than guessing a date.
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _CANONICAL_ISO_FORMAT)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    # Normalise to naive UTC so every comparison in this module is like-for-like.
    return (parsed - parsed.utcoffset()).replace(tzinfo=None)  # type: ignore[operator]
