################################################################################
# File Name: test_battery_health_verdict_reason.py
# Purpose/Description: US-632 -- the typed REASON on the battery-health verdict,
#   re-pinned for the ARCH-065 vocabulary.
#
#     "'we checked and cannot say' is distinguishable from 'nothing has checked
#      since May'.  Those are different facts and today they look identical."
#                                            -- US-632, NEGATIVE CASE
#
#   SIX causes, six typed reasons.  A RESOLVED verdict carries no reason.  And
#   the refusal that matters most: `lastHealthCheckTs` is never advanced to
#   "now" to make the card look fresh -- it is a MEASUREMENT date (F-9).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)        | Initial -- US-632 typed reason vocabulary.
# 2026-10-03    | Atlas (ARCH-065a)  | ARCH-065 T7: rewritten for the new six
#                                     (no_monthly_test / monthly_test_stale /
#                                     too_few_syncs replace no_qualifying_drains
#                                     / too_few_drains / health_data_stale).
#                                     The US-632 claims are unchanged.
# ================================================================================
################################################################################

"""US-632: every `unknown` battery-health verdict names its own cause."""

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from pi.power.battery_health_verdict import (
    REASON_CLOCK_UNREADABLE,
    REASON_LOG_UNREADABLE,
    REASON_MONTHLY_TEST_STALE,
    REASON_NO_DATABASE,
    REASON_NO_MONTHLY_TEST,
    REASON_TOO_FEW_SYNCS,
    STALE_TEST_DAYS,
    UNKNOWN_REASONS,
    VERDICT_UNKNOWN,
    readBatteryHealthVerdict,
)
from tests.pi.battery_verdict_fixture import VerdictDatabase, goodPack

_NOW = datetime(2026, 10, 28, 12, 0, 0)
_NOW_ISO = "2026-10-28T12:00:00Z"


def _read(db, nowIso: str = _NOW_ISO):
    return readBatteryHealthVerdict(database=db, nowIso=nowIso, smoothingSec=5.0)


class _BrokenDatabase:
    @contextmanager
    def connect(self):
        raise sqlite3.OperationalError("database is locked")
        yield  # pragma: no cover


def _stalePack():
    db = goodPack(_NOW, testDaysAgo=STALE_TEST_DAYS + 5)
    return db


def _thinPack():
    db = VerdictDatabase(_NOW)
    db.addTest(1)
    db.addJobs(2)
    return db


def test_resolvedVerdict_carriesNoReason():
    result = _read(goodPack(_NOW))
    assert result.verdict != VERDICT_UNKNOWN
    assert result.reason is None


def test_nothingHasEverChecked_isDistinguishableFromCheckedButStale():
    neverChecked = _read(VerdictDatabase(_NOW))
    checkedLongAgo = _read(_stalePack())
    assert neverChecked.verdict == checkedLongAgo.verdict == VERDICT_UNKNOWN
    assert neverChecked.reason == REASON_NO_MONTHLY_TEST
    assert checkedLongAgo.reason == REASON_MONTHLY_TEST_STALE


def test_lastHealthCheckTs_isNeverAdvancedToNow():
    db = _stalePack()
    result = _read(db)
    assert result.lastHealthCheckTs == db.iso(STALE_TEST_DAYS + 5)
    assert result.lastHealthCheckTs != _NOW_ISO


def test_noMonthlyTest_reportsNoDateRatherThanToday():
    result = _read(VerdictDatabase(_NOW))
    assert result.lastHealthCheckTs is None


def test_tooFewSyncs_isTooFewSyncs_andKeepsTheTestDate():
    db = _thinPack()
    result = _read(db)
    assert result.reason == REASON_TOO_FEW_SYNCS
    assert result.lastHealthCheckTs == db.iso(1)


def test_staleBeatsTooFewSyncs_whenBothWouldApply():
    """'The data on file has aged out' is the stronger statement."""
    db = VerdictDatabase(_NOW)
    db.addTest(STALE_TEST_DAYS + 5)
    db.addJobs(1)
    assert _read(db).reason == REASON_MONTHLY_TEST_STALE


def test_unparseableClock_isClockUnreadable():
    assert _read(goodPack(_NOW), nowIso="garbage").reason == REASON_CLOCK_UNREADABLE


def test_noDatabase_isNoDatabase():
    assert _read(None).reason == REASON_NO_DATABASE


def test_unreadableLog_isLogUnreadable():
    assert _read(_BrokenDatabase()).reason == REASON_LOG_UNREADABLE


def test_readableButEmptyLog_isNoMonthlyTest_notLogUnreadable():
    assert _read(VerdictDatabase(_NOW)).reason == REASON_NO_MONTHLY_TEST


def test_everyUnknownBranchCarriesAReasonFromTheVocabulary():
    for result in (
        _read(None),
        _read(_BrokenDatabase()),
        _read(goodPack(_NOW), nowIso="garbage"),
        _read(VerdictDatabase(_NOW)),
        _read(_stalePack()),
        _read(_thinPack()),
    ):
        assert result.verdict == VERDICT_UNKNOWN
        assert result.reason in UNKNOWN_REASONS


def test_theSixCausesAreSixDistinctReasons():
    reasons = {
        _read(None).reason,
        _read(_BrokenDatabase()).reason,
        _read(goodPack(_NOW), nowIso="garbage").reason,
        _read(VerdictDatabase(_NOW)).reason,
        _read(_stalePack()).reason,
        _read(_thinPack()).reason,
    }
    assert reasons == set(UNKNOWN_REASONS)
    assert len(UNKNOWN_REASONS) == 6


def test_reasonVocabularyIsSnakeCase_theProjectIdiom():
    for reason in UNKNOWN_REASONS:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", reason), reason
