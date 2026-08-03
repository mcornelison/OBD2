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
#   US-527: which rows COUNT is gated on DEPTH (``end_vcell_v <= 3.50`` V), not
#   duration -- the end voltage is what says the pack actually discharged to its
#   shutdown region.  The runtime still supplies the MEASUREMENT (and its bands);
#   it just no longer decides admission.
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
# 2026-08-03    | Ralph (Rex)  | US-527/TD-074 -- qualifying gate remapped from
#                               the RETIRED runtime_seconds>=600 duration gate
#                               to Spool's DEPTH gate (end_vcell_v <= 3.50 V
#                               AND runtime_seconds >= 60).  Bands UNCHANGED
#                               (Spool ruling c72677e) and now fully reachable.
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
    'QUALIFYING_MAX_END_VCELL_V',
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
# verdict-source.md (Spool, Tuning SME) for the bands + windows, and
# offices/ralph/inbox/2026-08-02-from-spool-us504-gate-ruling-and-us521-
# ratification.md (commit c72677e) for the DEPTH gate that replaced the retired
# duration gate.  Every number below is marked [EXACT] in one of those rulings
# and is load-bearing.

#: Only the real production drain measures the pack under its real load.
QUALIFYING_LOAD_CLASS: str = 'production'

#: [EXACT:3.50] The DEPTH gate (US-527).  Duration was only ever a PROXY for
#: "ran to cutoff"; end voltage answers that question directly where duration
#: cannot.  A pack reaching cutoff in 400 s is a genuine and alarming capacity
#: measurement that must vote; a key-cycle ending at 400 s with the pack at
#: 4.0 V measured nothing.  Only depth separates those two.
#:
#: 3.50 V is not a round number picked for tidiness -- it is the gap between two
#: measured values: the observed cutoff on this pack is 3.42-3.45 V (Spool
#: Session-27, 28 drains) and the MAX17048 "low" alert threshold in use is
#: 3.55 V.  So 3.50 sits ABOVE the observed cutoff with margin (a genuine
#: run-to-shutdown at 3.45 qualifies) and BELOW the low warning (a drain that
#: merely got low does not).
QUALIFYING_MAX_END_VCELL_V: float = 3.50

#: [EXACT:60] Sanity floor only -- it excludes absurd rows, it does NOT decide
#: whether the drain measured capacity (that is the depth gate above).
#:
#: This RETIRES the [EXACT:600] duration gate, which was Spool's own spec bug
#: (TD-074): 600 s sat ABOVE the 582 s good/degraded boundary, so every row that
#: survived the gate necessarily landed in the `good` band and `degraded` /
#: `replace` were unreachable -- the verdict failed toward REASSURANCE, the one
#: direction a health verdict must never fail.  The floor now sits below both
#: band boundaries, so the whole band range is reachable.
QUALIFYING_MIN_RUNTIME_S: int = 60

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
#:
#: UNCHANGED by the US-527 depth-gate remap -- Spool's ruling moves the GATE and
#: explicitly leaves the bands alone ("Bands UNCHANGED ... they're now fully
#: reachable across their whole range because duration no longer filters").
#: These stay RUNTIME bands; there is no such thing as a depth band here.
GOOD_MIN_RUNTIME_S: int = round(RUNTIME_BASELINE_S * GOOD_BASELINE_FRACTION)
DEGRADED_MIN_RUNTIME_S: int = round(
    RUNTIME_BASELINE_S * DEGRADED_BASELINE_FRACTION
)

# The canonical ISO-8601 UTC instant format every Pi writer stamps (TD-027).
_CANONICAL_ISO_FORMAT: str = '%Y-%m-%dT%H:%M:%SZ'

_QUALIFYING_ROW_SQL: str = (
    "SELECT start_timestamp, end_timestamp, runtime_seconds, load_class, "
    "       end_vcell_v "
    "FROM battery_health_log "
    "WHERE end_timestamp IS NOT NULL "
    "  AND load_class = ? "
    "  AND runtime_seconds IS NOT NULL "
    "  AND runtime_seconds >= ? "
    "  AND end_vcell_v IS NOT NULL "
    "  AND end_vcell_v <= ? "
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
            ``runtime_seconds`` / ``load_class`` / ``end_vcell_v`` keys, in any
            order.
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
                (
                    QUALIFYING_LOAD_CLASS,
                    QUALIFYING_MIN_RUNTIME_S,
                    QUALIFYING_MAX_END_VCELL_V,
                ),
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
            'end_vcell_v': row[4],
        }
        for row in fetched
    ]
    return computeBatteryHealthVerdict(rows=rows, nowIso=nowIso)


# ================================================================================
# Internal helpers
# ================================================================================


def verdictForMedianRuntime(medianRuntimeS: int) -> str:
    """Map a median drain runtime to its Spool band.

    RESOLVED (US-527 / TD-074).  This function previously carried an OPEN SPEC
    ISSUE: the qualifying gate was ``runtime_seconds >= 600`` while the degraded
    band topped out at 582 s and replace at 435 s -- both entirely BELOW the
    gate -- so every surviving row landed in ``good`` and a pack genuinely dying
    at 500 s was discarded as "partial drain" noise rather than reported as
    degraded.  Spool ruled it his own spec bug and gated on DEPTH instead
    (``offices/ralph/inbox/2026-08-02-from-spool-us504-gate-ruling-and-us521-
    ratification.md``, commit c72677e).

    The prediction made when the issue was filed held exactly: **only the gate
    constant moved.**  The bands here are byte-for-byte the ones Spool specified
    on 2026-08-01 and the whole range is now reachable, which is why they were
    kept in this separate public function rather than inlined into the gate.
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
    load class, missing/sub-floor runtime, a shallow or unknown end voltage, or
    an unparseable start timestamp.  A NULL required input is never silently
    defaulted; the row simply does not vote.

    The depth check makes an INTERRUPTED drain fail honestly.  US-526's boot
    reaper deliberately leaves ``runtime_seconds`` AND ``end_vcell_v`` NULL on a
    reaped orphan (nothing knew the voltage at power-off), so such a row is
    excluded twice over -- belt and braces on a value that feeds a health
    verdict.
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

    endVcell = row.get('end_vcell_v')
    if endVcell is None:
        return None
    try:
        endVcellV = float(endVcell)
    except (TypeError, ValueError):
        return None
    if endVcellV > QUALIFYING_MAX_END_VCELL_V:
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
