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
# 2026-08-03    | Ralph (Rex)  | US-527/TD-074 -- qualifying gate remapped from
#                               the retired runtime_seconds>=600 duration gate
#                               to Spool's DEPTH gate (end_vcell_v <= 3.50 V +
#                               60 s floor).  Bands UNCHANGED; degraded/replace
#                               now reachable through the real pipeline.
# ================================================================================
################################################################################

"""US-504 / US-527: the battery-health verdict producer (Spool [EXACT] spec)."""

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
    QUALIFYING_MAX_END_VCELL_V,
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
    endVcellV: float | None = 3.45,
) -> dict:
    """One battery_health_log row shaped as the reader hands it to the pure fn.

    ``endVcellV`` defaults to 3.45 V -- the top of the MEASURED 3.42-3.45 V
    cutoff range (Spool Session-27, 28 drains), i.e. a genuine run-to-shutdown
    that PASSES the depth gate.  A test that wants a non-qualifying row states
    its own shallower voltage rather than relying on the default.
    """
    start = _iso(daysAgo) if startTimestamp is None else startTimestamp
    return {
        "start_timestamp": start,
        "end_timestamp": _iso(daysAgo - 0.01) if closed else None,
        "runtime_seconds": runtimeSeconds,
        "load_class": loadClass,
        "end_vcell_v": endVcellV,
    }


def _verdict(rows, nowIso: str = _NOW_ISO):
    return computeBatteryHealthVerdict(rows=rows, nowIso=nowIso)


# ---------------------------------------------------------------------------
# The Spool [EXACT] constants (load-bearing -- flag Spool before any drift).
# ---------------------------------------------------------------------------


def test_constants_matchSpoolExactSpec():
    """[EXACT] 3.50 / 60 / 727 / 80 / 60 / 180 / 90.

    The depth gate (3.50 V + 60 s floor) is Spool's ruling of 2026-08-02
    (`offices/ralph/inbox/2026-08-02-from-spool-us504-gate-ruling-and-us521-
    ratification.md`, commit c72677e); everything else is the 2026-08-01 note
    and is UNCHANGED by the remap.
    """
    assert QUALIFYING_MAX_END_VCELL_V == 3.50
    assert QUALIFYING_MIN_RUNTIME_S == 60
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


def test_shallowDrain_doesNotQualify_evenWithALongRuntime():
    """DEPTH, not duration: a long drain that ended at 3.80 V never reached the
    shutdown region, so it measured nothing about capacity.

    This is the whole point of Spool's remap -- under the retired duration gate
    these three 700 s rows would have qualified and voted `good`.
    """
    rows = [_row(daysAgo=d, runtimeSeconds=700, endVcellV=3.80) for d in (1, 2, 3)]
    result = _verdict(rows)
    assert result.qualifyingCount == 0
    assert result.verdict == VERDICT_UNKNOWN


def test_endVcellAtExactDepthCut_qualifies():
    """The 3.50 V cut is inclusive, per Spool's `end_vcell_v <= [EXACT:3.50]`."""
    rows = [_row(daysAgo=d, endVcellV=3.50) for d in (1, 2, 3)]
    assert _verdict(rows).qualifyingCount == 3


def test_endVcellOneCentivoltAboveTheCut_doesNotQualify():
    """3.51 V is above the cut -- and below the 3.55 V MAX17048 'low' warning,
    so this is exactly the 'got low but did not run to shutdown' case the gate
    exists to reject."""
    rows = [_row(daysAgo=d, endVcellV=3.51) for d in (1, 2, 3)]
    assert _verdict(rows).qualifyingCount == 0


def test_measuredCutoffVoltages_qualify():
    """The measured cutoff on this pack is 3.42-3.45 V (Spool Session-27, 28
    drains).  3.50 V was chosen to sit ABOVE that range with margin, so a real
    run-to-shutdown must qualify -- if it did not, the gate would reject the
    only event it exists to accept."""
    for volts in (3.42, 3.45):
        rows = [_row(daysAgo=d, endVcellV=volts) for d in (1, 2, 3)]
        assert _verdict(rows).qualifyingCount == 3, volts


def test_nullEndVcell_doesNotQualify():
    """A reaped orphan / unreadable gauge leaves end_vcell_v NULL.  The depth of
    an interrupted drain is UNKNOWN and must never be treated as reached
    (US-526 honest-NA; the reaper deliberately leaves this NULL)."""
    rows = [_row(daysAgo=d, endVcellV=None) for d in (1, 2, 3)]
    result = _verdict(rows)
    assert result.qualifyingCount == 0
    assert result.verdict == VERDICT_UNKNOWN


def test_runtimeAtSanityFloor_qualifies():
    """The floor is inclusive (>= [EXACT:60]), per Spool's `runtime_seconds >= 60`."""
    rows = [_row(daysAgo=d, runtimeSeconds=60) for d in (1, 2, 3)]
    assert _verdict(rows).qualifyingCount == 3


def test_runtimeUnderSanityFloor_doesNotQualify():
    """< 60 s is an absurd row -- a pack cannot genuinely reach the shutdown
    region that fast, so depth alone must not admit it."""
    rows = [_row(daysAgo=d, runtimeSeconds=59) for d in (1, 2, 3)]
    assert _verdict(rows).qualifyingCount == 0


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


def test_qualifyingRuntimeFloorSitsBELOWBothBands():
    """US-527/TD-074 -- the REGRESSION GUARD for the retired 600 s gate.

    The Sprint-69 defect was a gate ABOVE the bands: `runtime_seconds >= 600`
    with `good` starting at 582 s meant every surviving row was necessarily
    `good`, so the verdict could not degrade -- it failed toward reassurance,
    the one direction a health verdict must never fail.

    Spool's remap fixes it by moving the GATE, not by re-tuning the bands: the
    60 s floor now sits below BOTH band boundaries, so the whole band range is
    reachable.  Asserting the ordering (rather than just the literal 60) is what
    makes this a guard: re-introducing any floor at or above 436 s silently
    re-breaks reachability, and this fails.
    """
    assert QUALIFYING_MIN_RUNTIME_S < DEGRADED_MIN_RUNTIME_S < GOOD_MIN_RUNTIME_S
    assert QUALIFYING_MIN_RUNTIME_S != 600  # the retired duration gate


def test_replaceBandRowStillQualifies_theEventTheOldGateDiscarded():
    """Spool's worked example: 'a pack dying at 500 s would have been discarded
    as partial-drain noise, which is precisely the event the verdict exists to
    catch.'  Under the depth gate that row qualifies AND reports degraded."""
    rows = [_row(daysAgo=d, runtimeSeconds=500) for d in (1, 2, 3)]
    result = _verdict(rows)
    assert result.qualifyingCount == 3
    assert result.verdict == VERDICT_DEGRADED


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
        # Spool's key-cycle example: ended at 4.00 V, so it measured nothing.
        _row(daysAgo=0.5, runtimeSeconds=120, endVcellV=4.00),
        _row(daysAgo=0.55, runtimeSeconds=30),   # under the 60s sanity floor
        _row(daysAgo=0.6, closed=False),         # never closed
        _row(daysAgo=0.7, loadClass="sim"),      # not a production load
        _row(daysAgo=0.8, endVcellV=None),       # reaped orphan -- depth unknown
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
                "(start_timestamp, end_timestamp, runtime_seconds, load_class, "
                " end_vcell_v) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    r["start_timestamp"], r["end_timestamp"],
                    r["runtime_seconds"], r["load_class"], r["end_vcell_v"],
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
            _row(daysAgo=0.5, runtimeSeconds=30),
            _row(daysAgo=0.6, closed=False),
            _row(daysAgo=1, runtimeSeconds=700),
            _row(daysAgo=2, runtimeSeconds=700),
            _row(daysAgo=3, runtimeSeconds=700),
        ]
    )
    result = readBatteryHealthVerdict(database=db, nowIso=_NOW_ISO)
    assert result.qualifyingCount == 3
    assert result.lastHealthCheckTs == _iso(1)


def test_readBatteryHealthVerdict_appliesTheDEPTHGateInSql(monkeypatch):
    """The SQL gate must exclude non-qualifying rows ITSELF.

    MUTATION-PROVED necessary.  The gate is applied TWICE -- once in SQL, once
    in the pure function -- so asserting only on the returned verdict cannot
    tell the two halves apart: neutralising the SQL depth predicate leaves the
    verdict, `qualifyingCount` and `lastHealthCheckTs` all correct, because the
    pure function silently covers for it.  I verified that: with
    `end_vcell_v <= ?` disabled in SQL, all 44 tests in this module still
    passed.

    So this test asserts at the READ BOUNDARY -- it captures exactly which rows
    SQL handed over.  That is the assertion the sibling
    `..._appliesTheGateInSql` above only claims in its docstring.
    """
    import pi.power.battery_health_verdict as verdictModule

    captured: list[dict] = []
    realCompute = verdictModule.computeBatteryHealthVerdict

    def _spy(*, rows, nowIso):
        materialised = list(rows)
        captured.extend(materialised)
        return realCompute(rows=materialised, nowIso=nowIso)

    monkeypatch.setattr(verdictModule, 'computeBatteryHealthVerdict', _spy)

    db = _FakeDatabase(
        [
            _row(daysAgo=0.4, runtimeSeconds=900, endVcellV=3.80),  # long+shallow
            _row(daysAgo=0.5, endVcellV=None),                # reaped orphan
            _row(daysAgo=0.6, runtimeSeconds=30),             # under the 60s floor
            _row(daysAgo=0.7, closed=False),                  # never closed
            _row(daysAgo=0.8, loadClass="sim"),               # not production
            _row(daysAgo=1, runtimeSeconds=700),
            _row(daysAgo=2, runtimeSeconds=700),
            _row(daysAgo=3, runtimeSeconds=700),
        ]
    )
    result = readBatteryHealthVerdict(database=db, nowIso=_NOW_ISO)

    # Only the three genuine run-to-cutoff drains crossed the read boundary.
    assert len(captured) == 3
    assert [r["start_timestamp"] for r in captured] == [_iso(1), _iso(2), _iso(3)]
    for row in captured:
        assert row["end_vcell_v"] is not None
        assert row["end_vcell_v"] <= QUALIFYING_MAX_END_VCELL_V
        assert row["runtime_seconds"] >= QUALIFYING_MIN_RUNTIME_S
        assert row["load_class"] == QUALIFYING_LOAD_CLASS
        assert row["end_timestamp"] is not None

    assert result.qualifyingCount == 3
    assert result.lastHealthCheckTs == _iso(1)


# ---------------------------------------------------------------------------
# US-527 AC4 -- degraded + replace reachable THROUGH THE REAL PIPELINE.
# Seeded depth-gated rows, read through readBatteryHealthVerdict (real SQL gate
# + real pure function), not through verdictForMedianRuntime() in isolation.
# The old gate made both of these verdicts impossible to reach this way.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "runtimeSeconds,expected",
    [
        (700, VERDICT_GOOD),      # healthy run-to-cutoff
        (500, VERDICT_DEGRADED),  # 436-582 band -- UNREACHABLE before US-527
        (300, VERDICT_REPLACE),   # < 436 band  -- UNREACHABLE before US-527
    ],
)
def test_everyBandIsReachableThroughTheRealPipeline(runtimeSeconds, expected):
    """Seed 3 depth-gated drains and read the verdict end-to-end."""
    db = _FakeDatabase(
        [
            _row(daysAgo=d, runtimeSeconds=runtimeSeconds, endVcellV=3.44)
            for d in (1, 2, 3)
        ]
    )
    result = readBatteryHealthVerdict(database=db, nowIso=_NOW_ISO)
    assert result.qualifyingCount == 3
    assert result.medianRuntimeS == runtimeSeconds
    assert result.verdict == expected


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
