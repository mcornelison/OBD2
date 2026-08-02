################################################################################
# File Name: test_battery_health_verdict.py
# Purpose/Description: US-504 tests for the battery HEALTH verdict + last-
#   health-check producer (Spool [EXACT] spec, inbox note 2026-08-01). The card
#   previously carried a HARDCODED health="unknown" / lastHealthCheckTs=None
#   because no producer existed. These tests pin the qualifying-row gate (a
#   partial or aborted drain measured NOTHING about capacity and must not
#   qualify -- nor bump the last-health-check date), median-of-3 (single-drain
#   scatter is +/-15%, so last-1 would false-alarm), the 80/60% baseline bands,
#   the trailing-180-day sample window, the 90-day staleness override (stale
#   health data is not health data), and the honest-unknown default on every
#   NULL / missing / unreadable input -- a verdict manufactured out of NULLs is
#   strictly worse than the placeholder it replaces.
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

"""US-504: the battery-health verdict producer (Spool [EXACT] spec)."""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from pi.power.battery_health import (
    SCHEMA_BATTERY_HEALTH_LOG,
)
from pi.power.battery_health_verdict import (
    DEGRADED_BASELINE_FRACTION,
    DEGRADED_MIN_RUNTIME_S,
    GOOD_BASELINE_FRACTION,
    GOOD_MIN_RUNTIME_S,
    MEDIAN_SAMPLE_COUNT,
    QUALIFYING_LOAD_CLASS,
    QUALIFYING_MIN_RUNTIME_S,
    RUNTIME_BASELINE_S,
    STALE_HEALTH_CHECK_DAYS,
    TRAILING_WINDOW_DAYS,
    VERDICT_DEGRADED,
    VERDICT_GOOD,
    VERDICT_REPLACE,
    VERDICT_UNKNOWN,
    computeBatteryHealthVerdict,
    readBatteryHealthVerdict,
    verdictForMedianRuntime,
)

_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
_NOW_ISO = "2026-08-01T12:00:00Z"


def _iso(daysAgo: float) -> str:
    """Canonical ISO-8601 UTC instant `daysAgo` days before the fixed now."""
    return (_NOW - timedelta(days=daysAgo)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(
    *,
    daysAgo: float,
    runtimeSeconds: int | None = 700,
    loadClass: str = "production",
    closed: bool = True,
    startTimestamp: str | None = None,
) -> dict:
    """One battery_health_log row shaped as the reader hands it to the pure fn."""
    start = _iso(daysAgo) if startTimestamp is None else startTimestamp
    return {
        "start_timestamp": start,
        "end_timestamp": _iso(daysAgo - 0.01) if closed else None,
        "runtime_seconds": runtimeSeconds,
        "load_class": loadClass,
    }


def _verdict(rows, nowIso: str = _NOW_ISO):
    return computeBatteryHealthVerdict(rows=rows, nowIso=nowIso)


# ---------------------------------------------------------------------------
# The Spool [EXACT] constants (load-bearing -- flag Spool before any drift).
# ---------------------------------------------------------------------------


def test_constants_matchSpoolExactSpec():
    """[EXACT] 600 / 727 / 80 / 60 / 180 / 90 -- Spool inbox note 2026-08-01."""
    assert QUALIFYING_MIN_RUNTIME_S == 600
    assert RUNTIME_BASELINE_S == 727
    assert GOOD_BASELINE_FRACTION == 0.80
    assert DEGRADED_BASELINE_FRACTION == 0.60
    assert TRAILING_WINDOW_DAYS == 180
    assert STALE_HEALTH_CHECK_DAYS == 90
    assert QUALIFYING_LOAD_CLASS == "production"
    assert MEDIAN_SAMPLE_COUNT == 3


def test_derivedBands_matchSpoolStatedSeconds():
    """Spool states the bands BOTH as percentages and as seconds (>=582s /
    436-582s / <436s). Deriving from the percentage must reproduce his
    seconds exactly, or the two halves of the [EXACT] spec have drifted."""
    assert GOOD_MIN_RUNTIME_S == 582
    assert DEGRADED_MIN_RUNTIME_S == 436


# ---------------------------------------------------------------------------
# Qualifying-row gate: a partial/aborted drain measured NOTHING about capacity.
# ---------------------------------------------------------------------------


def test_openDrain_doesNotQualify():
    """end_timestamp NULL = the drain never closed -- no runtime-to-cutoff."""
    rows = [_row(daysAgo=d, closed=False) for d in (1, 2, 3)]
    result = _verdict(rows)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.qualifyingCount == 0


def test_nonProductionLoadClass_doesNotQualify():
    """'test' / 'sim' drains are not the production load the baseline measures."""
    rows = [_row(daysAgo=1, loadClass="test"), _row(daysAgo=2, loadClass="sim")]
    rows.append(_row(daysAgo=3))
    result = _verdict(rows)
    assert result.qualifyingCount == 1
    assert result.verdict == VERDICT_UNKNOWN


def test_shortRuntime_doesNotQualify():
    """< [EXACT:600]s -- the pack never approached cutoff (key-cycle/abort)."""
    rows = [_row(daysAgo=d, runtimeSeconds=599) for d in (1, 2, 3)]
    assert _verdict(rows).qualifyingCount == 0


def test_runtimeAtExactCut_qualifies():
    """The 600s cut is inclusive (>= 600), per Spool's `runtime_seconds >= 600`."""
    rows = [_row(daysAgo=d, runtimeSeconds=600) for d in (1, 2, 3)]
    assert _verdict(rows).qualifyingCount == 3


def test_nullRuntime_doesNotQualify():
    """A NULL required input can never be treated as a measurement."""
    rows = [_row(daysAgo=d, runtimeSeconds=None) for d in (1, 2, 3)]
    result = _verdict(rows)
    assert result.qualifyingCount == 0
    assert result.verdict == VERDICT_UNKNOWN


def test_unparseableStartTimestamp_doesNotQualify():
    """A corrupt timestamp is a NULL required input -- never silently dated."""
    rows = [_row(daysAgo=d, startTimestamp="not-a-timestamp") for d in (1, 2, 3)]
    assert _verdict(rows).qualifyingCount == 0


# ---------------------------------------------------------------------------
# Honest unknown: fewer than 3 qualifying drains in the trailing window.
# ---------------------------------------------------------------------------


def test_noRows_isUnknownNotGood():
    result = _verdict([])
    assert result.verdict == VERDICT_UNKNOWN
    assert result.lastHealthCheckTs is None
    assert result.medianRuntimeS is None


def test_twoQualifyingDrains_isUnknown():
    """< 3 qualifying = the default unknown; two drains cannot outvote scatter."""
    rows = [_row(daysAgo=1), _row(daysAgo=2)]
    assert _verdict(rows).verdict == VERDICT_UNKNOWN


def test_thirdDrainOutsideTrailingWindow_isUnknown():
    """The 3-drain count is over the trailing [EXACT:180] days only."""
    rows = [_row(daysAgo=1), _row(daysAgo=2), _row(daysAgo=181)]
    result = _verdict(rows)
    assert result.qualifyingCount == 3
    assert result.verdict == VERDICT_UNKNOWN


def test_thirdDrainAtWindowEdge_counts():
    """180 days exactly is INSIDE the trailing window (the cut is >= now-180d)."""
    rows = [_row(daysAgo=1), _row(daysAgo=2), _row(daysAgo=180)]
    assert _verdict(rows).verdict == VERDICT_GOOD


# ---------------------------------------------------------------------------
# median-of-3, not last-1 (observed single-drain scatter is +/-15%).
# ---------------------------------------------------------------------------


def test_medianOfThree_notLastOne():
    """One low reading must NOT decide the verdict: the newest drain is a 617s
    low outlier, the median of the newest three is 727s."""
    rows = [
        _row(daysAgo=1, runtimeSeconds=617),
        _row(daysAgo=2, runtimeSeconds=727),
        _row(daysAgo=3, runtimeSeconds=831),
    ]
    result = _verdict(rows)
    assert result.medianRuntimeS == 727
    assert result.verdict == VERDICT_GOOD


def test_medianUsesTheNewestThree_notTheWholeHistory():
    """Only the last 3 qualifying drains vote; older ones are history."""
    rows = [
        _row(daysAgo=1, runtimeSeconds=620),
        _row(daysAgo=2, runtimeSeconds=620),
        _row(daysAgo=3, runtimeSeconds=620),
        _row(daysAgo=40, runtimeSeconds=830),
        _row(daysAgo=41, runtimeSeconds=830),
    ]
    assert _verdict(rows).medianRuntimeS == 620


def test_rowOrderIndependent_newestWinsByTimestampNotListOrder():
    """The reader's row order must not decide which drains vote."""
    rows = [
        _row(daysAgo=41, runtimeSeconds=830),
        _row(daysAgo=1, runtimeSeconds=620),
        _row(daysAgo=3, runtimeSeconds=620),
        _row(daysAgo=2, runtimeSeconds=620),
    ]
    assert _verdict(rows).medianRuntimeS == 620


# ---------------------------------------------------------------------------
# Verdict bands vs the [EXACT:727]s baseline.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "median,expected",
    [
        (831, VERDICT_GOOD),      # top of the measured baseline range
        (582, VERDICT_GOOD),      # exactly 80% of 727 -- inclusive
        (581, VERDICT_DEGRADED),  # one second under the good band
        (436, VERDICT_DEGRADED),  # exactly 60% -- Spool's degraded floor
        (435, VERDICT_REPLACE),   # one second under -> replace
        (0, VERDICT_REPLACE),
    ],
)
def test_verdictBands(median, expected):
    assert verdictForMedianRuntime(median) == expected


def test_degradedAndReplaceBandsSitBelowTheQualifyingGate():
    """FLAGGED TO SPOOL 2026-08-01 -- an open [EXACT]-spec interaction, pinned
    here so it stays visible instead of being silently "fixed" by drift.

    The qualifying gate is `runtime_seconds >= 600` but the degraded band tops
    out at 582s and replace at 435s -- both entirely BELOW the gate. So every
    row that survives the gate lands in the good band, and through the real
    pipeline `degraded` / `replace` are unreachable: a pack that genuinely
    dies at 500s is filtered out as a "partial" drain rather than reported as
    degraded. Both numbers are Spool [EXACT] values, so US-504 implements them
    verbatim and does NOT pick a side.
    """
    assert QUALIFYING_MIN_RUNTIME_S > GOOD_MIN_RUNTIME_S > DEGRADED_MIN_RUNTIME_S
    rows = [_row(daysAgo=d, runtimeSeconds=QUALIFYING_MIN_RUNTIME_S) for d in (1, 2, 3)]
    assert _verdict(rows).verdict == VERDICT_GOOD


# ---------------------------------------------------------------------------
# last-health-check: qualifying rows only.
# ---------------------------------------------------------------------------


def test_lastHealthCheck_isMaxStartTimestampOfQualifyingRows():
    rows = [_row(daysAgo=1), _row(daysAgo=9), _row(daysAgo=5)]
    assert _verdict(rows).lastHealthCheckTs == _iso(1)


def test_partialDrainDoesNotBumpLastHealthCheck():
    """A partial/aborted drain is NOT a health check -- otherwise the card
    claims a recent check that measured nothing."""
    rows = [
        _row(daysAgo=0.5, runtimeSeconds=120),   # key-cycle, under the 600s cut
        _row(daysAgo=0.6, closed=False),         # never closed
        _row(daysAgo=0.7, loadClass="sim"),      # not a production load
        _row(daysAgo=4),
        _row(daysAgo=5),
        _row(daysAgo=6),
    ]
    result = _verdict(rows)
    assert result.lastHealthCheckTs == _iso(4)
    assert result.verdict == VERDICT_GOOD


def test_lastHealthCheckSurvivesTheUnknownVerdict():
    """Even when the verdict is unknown the card still shows WHEN the last
    real check was -- that date is the honest signal."""
    rows = [_row(daysAgo=200), _row(daysAgo=201)]
    result = _verdict(rows)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.lastHealthCheckTs == _iso(200)


# ---------------------------------------------------------------------------
# The 90-day staleness override -- stale health data is not health data.
# ---------------------------------------------------------------------------


def test_staleHealthCheck_forcesUnknownDespiteGoodNumbers():
    """3 qualifying drains, all comfortably good, but the newest is 91 days
    old -> the verdict is forced to unknown regardless of the numbers."""
    rows = [_row(daysAgo=d, runtimeSeconds=800) for d in (91, 92, 93)]
    result = _verdict(rows)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.lastHealthCheckTs == _iso(91)


def test_healthCheckAtNinetyDays_isNotYetStale():
    """The override fires when the check is OLDER than [EXACT:90] days."""
    rows = [_row(daysAgo=d, runtimeSeconds=800) for d in (90, 91, 92)]
    assert _verdict(rows).verdict == VERDICT_GOOD


def test_staleOverrideBeatsAFullTrailingWindow():
    """Five healthy qualifying drains inside the 180-day window still resolve
    to unknown when the newest is over 90 days old -- the sample-count gate
    and the staleness gate are AND-ed, not alternatives."""
    rows = [_row(daysAgo=d, runtimeSeconds=800) for d in (95, 96, 97, 98, 99)]
    result = _verdict(rows)
    assert result.qualifyingCount == 5
    assert result.verdict == VERDICT_UNKNOWN


def test_unparseableNow_isUnknownNeverAConfidentVerdict():
    """A clock we cannot read cannot age-check the data -> unknown."""
    rows = [_row(daysAgo=d) for d in (1, 2, 3)]
    assert _verdict(rows, nowIso="garbage").verdict == VERDICT_UNKNOWN


# ---------------------------------------------------------------------------
# The database reader.
# ---------------------------------------------------------------------------


class _FakeDatabase:
    """An in-memory battery_health_log shaped exactly like the Pi's."""

    def __init__(self, rows=()):
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        for r in rows:
            self._conn.execute(
                "INSERT INTO battery_health_log "
                "(start_timestamp, end_timestamp, runtime_seconds, load_class) "
                "VALUES (?, ?, ?, ?)",
                (
                    r["start_timestamp"], r["end_timestamp"],
                    r["runtime_seconds"], r["load_class"],
                ),
            )
        self._conn.commit()

    @contextmanager
    def connect(self):
        yield self._conn


class _BrokenDatabase:
    @contextmanager
    def connect(self):
        raise sqlite3.OperationalError("no such table: battery_health_log")
        yield  # pragma: no cover -- unreachable, keeps this a generator


def test_readBatteryHealthVerdict_readsRealRows():
    db = _FakeDatabase([_row(daysAgo=d, runtimeSeconds=700) for d in (1, 2, 3)])
    result = readBatteryHealthVerdict(database=db, nowIso=_NOW_ISO)
    assert result.verdict == VERDICT_GOOD
    assert result.lastHealthCheckTs == _iso(1)


def test_readBatteryHealthVerdict_appliesTheGateInSql():
    """The non-qualifying rows must not reach the pure function at all."""
    db = _FakeDatabase(
        [
            _row(daysAgo=0.5, runtimeSeconds=120),
            _row(daysAgo=0.6, closed=False),
            _row(daysAgo=1, runtimeSeconds=700),
            _row(daysAgo=2, runtimeSeconds=700),
            _row(daysAgo=3, runtimeSeconds=700),
        ]
    )
    result = readBatteryHealthVerdict(database=db, nowIso=_NOW_ISO)
    assert result.qualifyingCount == 3
    assert result.lastHealthCheckTs == _iso(1)


def test_readBatteryHealthVerdict_emptyTableIsUnknown():
    result = readBatteryHealthVerdict(database=_FakeDatabase(), nowIso=_NOW_ISO)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.lastHealthCheckTs is None


def test_readBatteryHealthVerdict_databaseErrorIsUnknownNotACrash():
    """An unreadable log degrades to unknown -- it never raises into the emit
    loop and never invents a verdict."""
    result = readBatteryHealthVerdict(database=_BrokenDatabase(), nowIso=_NOW_ISO)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.lastHealthCheckTs is None


def test_readBatteryHealthVerdict_noDatabaseIsUnknown():
    result = readBatteryHealthVerdict(database=None, nowIso=_NOW_ISO)
    assert result.verdict == VERDICT_UNKNOWN
