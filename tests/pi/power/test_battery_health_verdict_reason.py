################################################################################
# File Name: test_battery_health_verdict_reason.py
# Purpose/Description: US-632 -- the typed REASON on the battery-health verdict.
#   The live Pi renders health="unknown" with lastHealthCheckTs 2026-05-16, and
#   the punch list (4.2) read that as "the producer stopped running".  It did
#   not: the verdict is recomputed on EVERY card-emit tick inside
#   eclipse-obd.service.  What the card cannot say is WHY the verdict is
#   unknown, and that is the actual defect this file pins:
#
#     "'we checked and cannot say' is distinguishable from 'nothing has checked
#      since May'.  Those are different facts and today they look identical."
#                                            -- US-632, NEGATIVE CASE
#
#   SIX distinct operational causes currently collapse to the same bare string
#   `unknown`.  These tests pin each cause to its own typed reason, pin that a
#   RESOLVED verdict carries no reason at all, and pin the REFUSAL that matters
#   most: `lastHealthCheckTs` is never advanced to "now" to make the card look
#   fresh.  That timestamp is a MEASUREMENT date; moving it would fabricate a
#   health check that never happened and would defeat the F-9 stale-green guard,
#   which exists precisely so a stale verdict cannot pass for a live one.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-632 typed reason vocabulary.
# ================================================================================
################################################################################

"""US-632: every `unknown` battery-health verdict names its own cause."""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from pi.power.battery_health import SCHEMA_BATTERY_HEALTH_LOG
from pi.power.battery_health_verdict import (
    MEDIAN_SAMPLE_COUNT,
    REASON_CLOCK_UNREADABLE,
    REASON_HEALTH_DATA_STALE,
    REASON_LOG_UNREADABLE,
    REASON_NO_DATABASE,
    REASON_NO_QUALIFYING_DRAINS,
    REASON_TOO_FEW_DRAINS,
    STALE_HEALTH_CHECK_DAYS,
    TRAILING_WINDOW_DAYS,
    UNKNOWN_REASONS,
    VERDICT_DEGRADED,
    VERDICT_GOOD,
    VERDICT_REPLACE,
    VERDICT_UNKNOWN,
    computeBatteryHealthVerdict,
    readBatteryHealthVerdict,
)

_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)
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
    endVcellV: float | None = 3.45,
) -> dict:
    """One qualifying battery_health_log row unless a field is overridden.

    3.45 V is the top of the MEASURED 3.42-3.45 V cutoff range (Spool
    Session-27), i.e. a genuine run-to-shutdown that passes the depth gate.
    """
    return {
        "start_timestamp": _iso(daysAgo),
        "end_timestamp": _iso(daysAgo - 0.01) if closed else None,
        "runtime_seconds": runtimeSeconds,
        "load_class": loadClass,
        "end_vcell_v": endVcellV,
    }


def _verdict(rows, nowIso: str = _NOW_ISO):
    return computeBatteryHealthVerdict(rows=rows, nowIso=nowIso)


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


# ---------------------------------------------------------------------------
# A RESOLVED verdict carries no reason.
#
# The reason exists to explain an ABSENCE.  Attaching one to a real verdict
# would be the mirror of the defect: a card that prints a caveat beside a
# number it actually measured.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("runtimeSeconds", "expected"),
    [(700, VERDICT_GOOD), (500, VERDICT_DEGRADED), (300, VERDICT_REPLACE)],
)
def test_resolvedVerdict_carriesNoReason(runtimeSeconds, expected):
    """Given: three qualifying drains that land in a real band.
    When: the verdict is computed.
    Then: it resolves, and `reason` is None -- not an empty string, not 'ok'.
    """
    rows = [_row(daysAgo=d, runtimeSeconds=runtimeSeconds) for d in (1, 2, 3)]
    result = _verdict(rows)
    assert result.verdict == expected
    assert result.reason is None


# ---------------------------------------------------------------------------
# THE STORY'S CORE: the two facts that "look identical today".
# ---------------------------------------------------------------------------


def test_nothingHasEverChecked_isDistinguishableFromCheckedButStale():
    """Given: (a) a log with no qualifying drain, and (b) a log whose newest
        qualifying drain is older than the staleness horizon.
    When: both are computed.
    Then: both are `unknown` -- but they carry DIFFERENT reasons.

    This is US-632's NEGATIVE CASE stated as an assertion.  Before this story
    both cases produced the byte-identical payload `health="unknown"`, so the
    card could not tell "nothing has ever measured this pack" from "we
    measured it, in May, and refuse to call that current".
    """
    neverChecked = _verdict([])
    checkedLongAgo = _verdict(
        [
            _row(daysAgo=STALE_HEALTH_CHECK_DAYS + 1 + d)
            for d in range(MEDIAN_SAMPLE_COUNT)
        ]
    )

    assert neverChecked.verdict == VERDICT_UNKNOWN
    assert checkedLongAgo.verdict == VERDICT_UNKNOWN
    assert neverChecked.reason == REASON_NO_QUALIFYING_DRAINS
    assert checkedLongAgo.reason == REASON_HEALTH_DATA_STALE
    assert neverChecked.reason != checkedLongAgo.reason


def test_theLivePiState_resolvesToStale_notToNothingEverChecked():
    """Given: the EXACT state Atlas measured on the Pi 2026-08-31 -- the last
        qualifying drains are the 2026-05-16 cluster, 107 days back.
    When: the verdict is computed against that date.
    Then: the reason is `health_data_stale`.

    Grounding: punch list 4.2 records lastHealthCheckTs 2026-05-16T01:54:27Z,
    and Spool's US-504 note records 11 qualifying drains 2026-05-09 -> 05-16.
    So the log is NOT empty -- the pack WAS measured, and the honest statement
    is "that measurement is too old to stand", not "nothing ever ran".
    """
    nowIso = "2026-08-31T12:00:00Z"
    rows = [
        {
            "start_timestamp": ts,
            "end_timestamp": "2026-05-16T02:06:00Z",
            "runtime_seconds": 700,
            "load_class": "production",
            "end_vcell_v": 3.45,
        }
        for ts in (
            "2026-05-16T01:54:27Z",
            "2026-05-14T01:54:27Z",
            "2026-05-12T01:54:27Z",
        )
    ]
    result = computeBatteryHealthVerdict(rows=rows, nowIso=nowIso)

    assert result.verdict == VERDICT_UNKNOWN
    assert result.reason == REASON_HEALTH_DATA_STALE
    # And the measurement date SURVIVES -- it is the signal, not noise.
    assert result.lastHealthCheckTs == "2026-05-16T01:54:27Z"


# ---------------------------------------------------------------------------
# THE REFUSAL, pinned.
#
# US-632's validationCriteria ask for "lastHealthCheckTs is current".  It must
# NOT be satisfied by advancing the field: it is a MEASUREMENT date, and the
# F-9 stale-green guard renders it precisely so an old reading cannot pass for
# a live one.  A test is the only thing that stops a later reader from
# "fixing" this into a fabrication.
# ---------------------------------------------------------------------------


def test_lastHealthCheckTs_isNeverAdvancedToNow():
    """Given: a stale measurement and a current clock.
    When: the verdict is computed.
    Then: lastHealthCheckTs still reports the MEASUREMENT date, never `now`.
    """
    staleTs = _iso(STALE_HEALTH_CHECK_DAYS + 5)
    result = _verdict([_row(daysAgo=STALE_HEALTH_CHECK_DAYS + 5)])

    assert result.lastHealthCheckTs == staleTs
    assert result.lastHealthCheckTs != _NOW_ISO


def test_noQualifyingDrains_reportsNoDateRatherThanToday():
    """Given: nothing has ever been measured.
    When: the verdict is computed.
    Then: lastHealthCheckTs is None -- an absent date, never today's date
        standing in for a check that never ran.
    """
    result = _verdict([])
    assert result.lastHealthCheckTs is None


# ---------------------------------------------------------------------------
# One cause -> one reason, for every unknown branch there is.
# ---------------------------------------------------------------------------


def test_emptyLog_isNoQualifyingDrains():
    assert _verdict([]).reason == REASON_NO_QUALIFYING_DRAINS


def test_logOfOnlyNonQualifyingRows_isNoQualifyingDrains():
    """A log with rows in it, none of which measured a capacity drain, is the
    same FACT as an empty log: nothing has ever checked."""
    rows = [
        _row(daysAgo=1, closed=False),            # still open
        _row(daysAgo=2, loadClass="bench"),        # wrong load class
        _row(daysAgo=3, endVcellV=4.05),           # too shallow to measure
    ]
    result = _verdict(rows)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.reason == REASON_NO_QUALIFYING_DRAINS
    assert result.qualifyingCount == 0


@pytest.mark.parametrize("count", [1, MEDIAN_SAMPLE_COUNT - 1])
def test_tooFewDrainsInWindow_isTooFewDrains(count):
    """Below the median-of-3 minimum the verdict is unknown WITH the reason --
    a distinct fact from 'nothing has ever measured'."""
    rows = [_row(daysAgo=d + 1) for d in range(count)]
    result = _verdict(rows)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.reason == REASON_TOO_FEW_DRAINS
    assert result.qualifyingCount == count


def test_drainsPresentButOutsideTrailingWindow_isTooFewDrains():
    """Given: three qualifying drains, one recent and two beyond the 180-day
        trailing window.
    When: the verdict is computed.
    Then: too_few_drains -- the recent drain keeps it out of `stale`, and the
        old pair cannot vote.
    """
    rows = [
        _row(daysAgo=1),
        _row(daysAgo=TRAILING_WINDOW_DAYS + 10),
        _row(daysAgo=TRAILING_WINDOW_DAYS + 20),
    ]
    result = _verdict(rows)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.reason == REASON_TOO_FEW_DRAINS


def test_staleBeatsTooFew_whenBothWouldApply():
    """Given: a single drain, older than the staleness horizon -- both the
        staleness override and the sample-count floor would fire.
    When: the verdict is computed.
    Then: the reason is `health_data_stale`.

    Ordering is load-bearing and mirrors the code: staleness is checked FIRST
    so a stale reading can never paint a confident verdict of any colour.
    Reporting `too_few_drains` here would understate the problem -- it would
    imply that three more drains would fix it, when the real statement is that
    the data on file has aged out.
    """
    result = _verdict([_row(daysAgo=STALE_HEALTH_CHECK_DAYS + 5)])
    assert result.reason == REASON_HEALTH_DATA_STALE


def test_unparseableClock_isClockUnreadable():
    """A clock we cannot read cannot age-check the data -- and that is a
    DIFFERENT failure from having no data."""
    result = _verdict([_row(daysAgo=d) for d in (1, 2, 3)], nowIso="not-a-date")
    assert result.verdict == VERDICT_UNKNOWN
    assert result.reason == REASON_CLOCK_UNREADABLE


def test_noDatabase_isNoDatabase():
    """Bench / not-yet-built: there is no log to read, which is not the same
    as a log that is readable and empty."""
    result = readBatteryHealthVerdict(database=None, nowIso=_NOW_ISO)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.reason == REASON_NO_DATABASE


def test_unreadableLog_isLogUnreadable():
    """A locked / pre-migration / corrupt log is an INSTRUMENT failure and must
    not masquerade as 'this pack has never been measured'."""
    result = readBatteryHealthVerdict(database=_BrokenDatabase(), nowIso=_NOW_ISO)
    assert result.verdict == VERDICT_UNKNOWN
    assert result.reason == REASON_LOG_UNREADABLE


def test_readableButEmptyLog_isNoQualifyingDrains_notLogUnreadable():
    """The distinction that the shared `_UNKNOWN_NO_DATA` sentinel used to
    erase: a healthy empty table is not a broken table."""
    result = readBatteryHealthVerdict(database=_FakeDatabase([]), nowIso=_NOW_ISO)
    assert result.reason == REASON_NO_QUALIFYING_DRAINS
    assert result.reason != REASON_LOG_UNREADABLE


def test_readerResolvesARealVerdictWithNoReason():
    """End-to-end through the SQL gate, not just the pure function."""
    db = _FakeDatabase([_row(daysAgo=d) for d in (1, 2, 3)])
    result = readBatteryHealthVerdict(database=db, nowIso=_NOW_ISO)
    assert result.verdict == VERDICT_GOOD
    assert result.reason is None


# ---------------------------------------------------------------------------
# The vocabulary is CLOSED, and it is total.
#
# Without these two, a later branch could return `unknown` with reason None and
# silently reinstate the exact ambiguity this story exists to remove.
# ---------------------------------------------------------------------------


def test_everyUnknownBranchCarriesAReasonFromTheVocabulary():
    """Given: every distinct way the producer can reach `unknown`.
    When: each is exercised.
    Then: each yields a reason, and each reason is in UNKNOWN_REASONS.
    """
    cases = [
        _verdict([]),
        _verdict([_row(daysAgo=1)]),
        _verdict([_row(daysAgo=STALE_HEALTH_CHECK_DAYS + 5)]),
        _verdict([_row(daysAgo=d) for d in (1, 2, 3)], nowIso="not-a-date"),
        readBatteryHealthVerdict(database=None, nowIso=_NOW_ISO),
        readBatteryHealthVerdict(database=_BrokenDatabase(), nowIso=_NOW_ISO),
    ]
    for result in cases:
        assert result.verdict == VERDICT_UNKNOWN
        assert result.reason is not None
        assert result.reason in UNKNOWN_REASONS


def test_theSixCausesAreSixDistinctReasons():
    """No two causes may share a reason string -- collapsing any pair would
    recreate the defect on a smaller scale."""
    observed = {
        _verdict([]).reason,
        _verdict([_row(daysAgo=1)]).reason,
        _verdict([_row(daysAgo=STALE_HEALTH_CHECK_DAYS + 5)]).reason,
        _verdict([_row(daysAgo=d) for d in (1, 2, 3)], nowIso="x").reason,
        readBatteryHealthVerdict(database=None, nowIso=_NOW_ISO).reason,
        readBatteryHealthVerdict(
            database=_BrokenDatabase(), nowIso=_NOW_ISO
        ).reason,
    }
    assert len(observed) == 6
    assert observed == set(UNKNOWN_REASONS)


def test_reasonVocabularyIsSnakeCase_theProjectIdiom():
    """Follow the existing typed-absence idiom (reasons.altitude: 'no_source',
    gear_derivation's no_data/stale/ambiguous) rather than inventing a second
    one -- US-632 says so explicitly, and US-504's cross-module enum-identity
    bug is what that instruction is protecting against."""
    for reason in UNKNOWN_REASONS:
        assert reason == reason.lower()
        assert " " not in reason
        assert reason.replace("_", "").isalpha()
