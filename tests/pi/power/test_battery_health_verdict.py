################################################################################
# File Name: test_battery_health_verdict.py
# Purpose/Description: ARCH-065 -- the battery-health verdict answers ONE
#   question (CIO 2026-10-02): after key-off at home, can the pack carry a full
#   sync AND a graceful shutdown?  T (time to the reserve floor) vs J (the
#   at-home job): good if T >= 1.2 J, degraded if J <= T < 1.2 J, replace if
#   T < J.  These tests pin the pure function at every boundary and the reader
#   against a real-DDL database.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03 (replaces the US-504 file of 2026-08-01)
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)        | Initial -- US-504 runtime-median verdict.
# 2026-10-03    | Atlas (ARCH-065a)  | ARCH-065 T7: REPLACED.  The US-504 file
#                                     pinned the retired qualifying rule
#                                     (production drains to <=3.50 V, median
#                                     runtime vs a 727 s baseline); no row has
#                                     reached it since 2026-05-18.
# ================================================================================
################################################################################

"""ARCH-065: the battery-health verdict = T vs J."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

import pytest

from src.common.config.validator import DEFAULTS
from src.pi.power import battery_health_verdict as verdictModule
from src.pi.power.battery_health_verdict import (
    GREEN_MARGIN,
    JOB_AVG_COUNT,
    MIN_JOBS,
    REASON_CLOCK_UNREADABLE,
    REASON_LOG_UNREADABLE,
    REASON_MONTHLY_TEST_STALE,
    REASON_NO_DATABASE,
    REASON_NO_MONTHLY_TEST,
    REASON_TOO_FEW_SYNCS,
    SHUTDOWN_ALLOWANCE_S,
    STALE_TEST_DAYS,
    UNKNOWN_REASONS,
    VERDICT_DEGRADED,
    VERDICT_GOOD,
    VERDICT_REPLACE,
    VERDICT_UNKNOWN,
    computeBatteryHealthVerdict,
    readBatteryHealthVerdict,
)
from src.pi.power.power_watch.contract import OutcomeKind
from tests.pi.battery_verdict_fixture import VerdictDatabase, goodPack

_NOW = "2026-10-28T12:00:00Z"
_NOW_DT = datetime(2026, 10, 28, 12, 0, 0)
_TEST = {"start_timestamp": "2026-10-27T17:00:00Z", "drain_rate_mv_s": -0.04, "end_vcell_v": 4.07,
         "window_end_s": 660}
_CAL = {"t_floor_s": 18000, "drain_rate_mv_s": -0.04}
_SMOOTHING_S = 5.0


def _v(test=_TEST, cal=_CAL, jobs=(100.0,) * 10):
    return computeBatteryHealthVerdict(test=test, calibration=cal, jobsS=list(jobs), nowIso=_NOW)


# ---------------------------------------------------------------------------
# The pure function -- every boundary.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("job,expected", [
    (18000 / 1.2, VERDICT_GOOD),          # T == 1.2 J  -> good (boundary inclusive)
    (18000 / 1.2 + 1, VERDICT_DEGRADED),  # just under 1.2 J
    (18000, VERDICT_DEGRADED),            # T == J -> degraded (inclusive)
    (18001, VERDICT_REPLACE),             # T < J
])
def test_thresholds_atTheirBoundaries(job, expected) -> None:
    assert _v(jobs=(job,) * 10).verdict == expected


def test_T_scalesTheCalibrationTimeByTheRateRatio() -> None:
    v = _v(test={**_TEST, "drain_rate_mv_s": -0.08})  # draining twice as fast
    assert v.timeToFloorS == 9000 and not v.provisional


def test_noCalibration_isProvisional_straightLineTo3_44_minusTheReserve() -> None:
    v = _v(cal=None)
    # 660 s + (4.07 - 3.44) V / 0.04 mV/s - 600 s reserve = 660 + 15750 - 600
    assert v.timeToFloorS == 15810 and v.provisional


def test_noTestForThisPack_isUnknown() -> None:
    v = _v(test=None)
    assert (v.verdict, v.reason) == (VERDICT_UNKNOWN, REASON_NO_MONTHLY_TEST)


def test_aTestOlderThan45Days_isStale() -> None:
    v = _v(test={**_TEST, "start_timestamp": "2026-09-12T00:00:00Z"})
    assert (v.verdict, v.reason) == (VERDICT_UNKNOWN, REASON_MONTHLY_TEST_STALE)


def test_fewerThanThreeJobs_isUnknown() -> None:
    assert _v(jobs=(100.0, 100.0)).reason == REASON_TOO_FEW_SYNCS


def test_J_isTheMeanOfTheNewestTen_andTheMaxIsPublished() -> None:
    v = _v(jobs=[100.0] * 10 + [9999.0])  # an 11th, older job is ignored
    assert v.jobAvgS == 100 and v.jobMaxS == 100


def test_theReasonVocabulary_isExactlySix() -> None:
    assert set(UNKNOWN_REASONS) == {"no_database", "log_unreadable", "clock_unreadable",
                                    "no_monthly_test", "monthly_test_stale", "too_few_syncs"}


def test_theConstants_areTheCiosNumbers() -> None:
    assert GREEN_MARGIN == 1.2
    assert STALE_TEST_DAYS == 45
    assert JOB_AVG_COUNT == 10
    assert MIN_JOBS == 3


def test_aTestAtExactly45Days_isNotYetStale() -> None:
    assert _v(test={**_TEST, "start_timestamp": "2026-09-13T12:00:00Z"}).verdict == VERDICT_GOOD


def test_exactlyThreeJobs_isEnough() -> None:
    assert _v(jobs=(100.0,) * 3).verdict == VERDICT_GOOD


def test_aResolvedVerdict_carriesNoReason_andTheTestDate() -> None:
    v = _v()
    assert v.reason is None
    assert v.lastHealthCheckTs == _TEST["start_timestamp"]


def test_staleAndTooFewSyncs_keepTheMeasurementDate() -> None:
    """F-9: the date of the last real check survives an unknown verdict."""
    stale = _v(test={**_TEST, "start_timestamp": "2026-09-12T00:00:00Z"})
    thin = _v(jobs=(100.0,))
    assert stale.lastHealthCheckTs == "2026-09-12T00:00:00Z"
    assert thin.lastHealthCheckTs == _TEST["start_timestamp"]
    for v in (stale, thin):
        assert v.timeToFloorS is None and v.jobAvgS is None


def test_aTestWithNoRate_isNotACountedTest() -> None:
    assert _v(test={**_TEST, "drain_rate_mv_s": None}).reason == REASON_NO_MONTHLY_TEST


def test_unparseableClock_isClockUnreadable_neverAConfidentVerdict() -> None:
    v = computeBatteryHealthVerdict(test=_TEST, calibration=_CAL, jobsS=[100.0] * 10,
                                    nowIso="not-a-time")
    assert (v.verdict, v.reason) == (VERDICT_UNKNOWN, REASON_CLOCK_UNREADABLE)


# ---------------------------------------------------------------------------
# The reader -- a real-DDL database.
# ---------------------------------------------------------------------------


def _read(db):
    return readBatteryHealthVerdict(database=db, nowIso=_NOW, smoothingSec=_SMOOTHING_S)


def test_reader_resolvesAGoodPack() -> None:
    v = _read(goodPack(_NOW_DT))
    assert v.verdict == VERDICT_GOOD
    assert v.timeToFloorS == 18000 and not v.provisional


def test_reader_J_isSmoothingPlusSyncPlusShutdownAllowance() -> None:
    """Ruling 10: the confirm-wait term is config smoothingSec, passed in."""
    db = goodPack(_NOW_DT)
    v = readBatteryHealthVerdict(database=db, nowIso=_NOW, smoothingSec=7.0)
    assert v.jobAvgS == round(7.0 + 100.0 + SHUTDOWN_ALLOWANCE_S)
    assert _read(db).jobAvgS == round(_SMOOTHING_S + 100.0 + SHUTDOWN_ALLOWANCE_S)


def test_reader_smoothingSec_isRequired() -> None:
    """No default that would hide a missing config value."""
    with pytest.raises(TypeError):
        readBatteryHealthVerdict(database=goodPack(_NOW_DT), nowIso=_NOW)  # type: ignore[call-arg]


def test_theValidatorDefault_isWhatTheEmitterFallsBackTo() -> None:
    assert DEFAULTS["pi.powerWatch.smoothingSec"] == 5


def test_reader_onlyDeliveredSyncsAreJobs() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addTest(1)
    db.addJobs(2)
    db.addJobs(5, outcome=OutcomeKind.AWAY.name)
    db.addJobs(5, outcome=OutcomeKind.STALLED.name)
    assert _read(db).reason == REASON_TOO_FEW_SYNCS


def test_reader_theJobOutcomeAndTriggers_areBound_notSqlLiterals() -> None:
    assert "DELIVERED" not in verdictModule._JOBS_SQL  # noqa: SLF001
    assert "monthly_test" not in verdictModule._TEST_SQL  # noqa: SLF001
    assert "calibration" not in verdictModule._CAL_SQL  # noqa: SLF001


def test_reader_noCalibration_isProvisional() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addTest(1)
    db.addJobs(10)
    v = _read(db)
    assert v.provisional and v.timeToFloorS == 15810


def test_reader_anUncountedTest_doesNotVote() -> None:
    """ONE definition of a counted test: drain_rate_mv_s IS NOT NULL."""
    db = VerdictDatabase(_NOW_DT)
    db.addTest(1, drainRateMvS=None)
    db.addJobs(10)
    assert _read(db).reason == REASON_NO_MONTHLY_TEST


def test_reader_usesTheNewestCountedTest() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addCalibration(30)
    db.addTest(20, drainRateMvS=-0.08)
    db.addTest(2)
    db.addTest(1, drainRateMvS=None)  # newer but uncounted
    db.addJobs(10)
    v = _read(db)
    assert v.timeToFloorS == 18000
    assert v.lastHealthCheckTs == db.iso(2)


def test_reader_aNewPack_neverInheritsTheOldPacksVerdict() -> None:
    """Review Focus #4: the newest row is a new pack with no counted test."""
    db = goodPack(_NOW_DT)
    db.addKeyoff(0.1, cellEpoch="new-pack")
    v = _read(db)
    assert (v.verdict, v.reason) == (VERDICT_UNKNOWN, REASON_NO_MONTHLY_TEST)


def test_reader_theCalibration_isPerPack() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addCalibration(30, cellEpoch="old-pack", tFloorS=99999)
    db.addTest(1)
    db.addJobs(10)
    assert _read(db).provisional


def test_reader_noPackYet_isNoMonthlyTest() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addKeyoff(1, cellEpoch=None)
    db.addJobs(10)
    assert _read(db).reason == REASON_NO_MONTHLY_TEST


def test_reader_emptyDatabase_isNoMonthlyTest() -> None:
    assert _read(VerdictDatabase(_NOW_DT)).reason == REASON_NO_MONTHLY_TEST


def test_reader_noDatabase_isNoDatabase() -> None:
    assert _read(None).reason == REASON_NO_DATABASE


class _BrokenDatabase:
    @contextmanager
    def connect(self):
        raise sqlite3.OperationalError("database is locked")
        yield  # pragma: no cover


def test_reader_unreadableLog_isLogUnreadable_notACrash() -> None:
    assert _read(_BrokenDatabase()).reason == REASON_LOG_UNREADABLE


def test_reader_preMigrationLog_isLogUnreadable() -> None:
    """A battery_health_log without the ARCH-065 columns cannot be read."""
    db = VerdictDatabase(_NOW_DT)
    db.conn.execute("DROP TABLE battery_health_log")
    db.conn.execute("CREATE TABLE battery_health_log (drain_event_id INTEGER PRIMARY KEY)")
    assert _read(db).reason == REASON_LOG_UNREADABLE


# ---------------------------------------------------------------------------
# The verdict is written onto the monthly-test row (server history), only
# when it changes -- the reader runs on every card emit.
# ---------------------------------------------------------------------------


def test_theResolvedVerdict_isWrittenOntoTheTestRow() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addCalibration(30)
    testId = db.addTest(1)
    db.addJobs(10)
    _read(db)
    assert db.storedVerdict(testId) == VERDICT_GOOD


def test_theVerdictWrite_happensOnlyWhenTheValueChanges() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addCalibration(30)
    testId = db.addTest(1)
    db.addJobs(10)
    _read(db)
    before = db.conn.total_changes
    _read(db)
    _read(db)
    assert db.conn.total_changes == before
    # A change of verdict IS written: ten newer 15000 s syncs -> J ~= 15009 s.
    db.addJobs(10, syncSeconds=15000)
    assert _read(db).verdict == VERDICT_DEGRADED
    assert db.storedVerdict(testId) == VERDICT_DEGRADED


def test_anUnknownVerdict_isNeverWrittenOntoTheRow() -> None:
    db = VerdictDatabase(_NOW_DT)
    testId = db.addTest(1)
    db.addJobs(1)
    assert _read(db).reason == REASON_TOO_FEW_SYNCS
    assert db.storedVerdict(testId) is None


def test_aFailedHistoryWrite_neverCostsTheVerdict() -> None:
    db = goodPack(_NOW_DT)
    db.conn.execute(
        "CREATE TRIGGER noWrites BEFORE UPDATE ON battery_health_log "
        "BEGIN SELECT RAISE(ABORT, 'read-only'); END"
    )
    assert _read(db).verdict == VERDICT_GOOD


# ---------------------------------------------------------------------------
# Fix round 1.  Ruling 16: a counted test whose provisional inputs are NULL is
# an unreadable LOG, never an exception out of the reader.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("override", [
    {"endVcellV": None},
    {"windowEndS": None},
])
def test_reader_aCountedTestWithANullProvisionalInput_isLogUnreadable_neverRaises(override) -> None:
    """Reproducer: a test reaped without a checkpoint keeps end_vcell_v NULL
    but the finaliser still rates it from the trajectory."""
    db = VerdictDatabase(_NOW_DT)
    db.addTest(1, **override)
    db.addJobs(10)
    v = _read(db)
    assert (v.verdict, v.reason) == (VERDICT_UNKNOWN, REASON_LOG_UNREADABLE)
    assert v.lastHealthCheckTs == db.iso(1)


def test_compute_aNonNumericProvisionalInput_isLogUnreadable() -> None:
    v = _v(cal=None, test={**_TEST, "end_vcell_v": "n/a"})
    assert (v.verdict, v.reason) == (VERDICT_UNKNOWN, REASON_LOG_UNREADABLE)
    assert v.lastHealthCheckTs == _TEST["start_timestamp"]


def test_reader_aNullEndVcell_isHarmless_whenTheCalibrationShapesT() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addCalibration(30)
    db.addTest(1, endVcellV=None, windowEndS=None)
    db.addJobs(10)
    assert _read(db).verdict == VERDICT_GOOD


def test_reader_anythingTheComputeRaises_isLogUnreadable(monkeypatch) -> None:
    def boom(**_kw):
        raise ValueError("unexpected")
    monkeypatch.setattr(verdictModule, "computeBatteryHealthVerdict", boom)
    assert _read(goodPack(_NOW_DT)).reason == REASON_LOG_UNREADABLE


# ---------------------------------------------------------------------------
# Ruling 13: a pack the reserve floor stopped at home failed its job -> replace.
# ---------------------------------------------------------------------------


def test_reader_aFloorEndedDrainNewerThanTheTest_isReplace() -> None:
    db = goodPack(_NOW_DT, testDaysAgo=5)
    db.addFloorEnded(1)
    v = _read(db)
    assert (v.verdict, v.reason) == (VERDICT_REPLACE, None)
    assert v.lastHealthCheckTs == db.iso(1)


def test_reader_aFloorEndedDrainOlderThanALaterCountedTest_theTestGoverns() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addCalibration(30)
    db.addFloorEnded(10)
    db.addTest(2)
    db.addJobs(10)
    assert _read(db).verdict == VERDICT_GOOD


def test_reader_aFloorEndedDrain_outranksStaleAndTooFewAndNoTest() -> None:
    for build in (
        lambda db: db.addTest(STALE_TEST_DAYS + 10),
        lambda db: (db.addTest(5), db.addJobs(1)),
        lambda db: None,
    ):
        db = VerdictDatabase(_NOW_DT)
        build(db)
        db.addFloorEnded(1)
        assert _read(db).verdict == VERDICT_REPLACE


def test_reader_anOldPacksFloorEndedDrain_isIgnored() -> None:
    db = VerdictDatabase(_NOW_DT)
    db.addFloorEnded(3, cellEpoch="old-pack")
    db.addCalibration(30)
    db.addTest(2)
    db.addJobs(10)
    assert _read(db).verdict == VERDICT_GOOD


def test_reader_aCountedTestsOwnReplaceHistory_isNotAFloorEndedDrain() -> None:
    """verdict=replace on a row WITH a rate is history, not a floor event."""
    db = VerdictDatabase(_NOW_DT)
    db.addCalibration(30)
    testId = db.addTest(1)
    db.conn.execute("UPDATE battery_health_log SET verdict = ? WHERE drain_event_id = ?",
                    (VERDICT_REPLACE, testId))
    db.addJobs(10)
    assert _read(db).verdict == VERDICT_GOOD


# ---------------------------------------------------------------------------
# Ruling 17: negative T is clamped; the history write cannot stall the reader.
# ---------------------------------------------------------------------------


def test_aNegativeT_isPublishedAsZero_andIsReplace() -> None:
    v = _v(cal=None, test={**_TEST, "end_vcell_v": 3.40, "window_end_s": 0})
    assert v.timeToFloorS == 0
    assert v.verdict == VERDICT_REPLACE


def test_aLockedDatabase_doesNotStallTheReader_andWarnsOnce(tmp_path, monkeypatch, caplog) -> None:
    import logging
    import time

    from src.pi.obdii.database import ObdDatabase

    monkeypatch.setattr(verdictModule, "_historyWriteWarned", False)
    obd = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    obd.initialize()
    src = goodPack(_NOW_DT)
    with obd.connect() as conn:
        for table in ("battery_health_log", "startup_log"):
            cols = [r[1] for r in src.conn.execute(f"PRAGMA table_info({table})")]
            for row in src.conn.execute(f"SELECT {', '.join(cols)} FROM {table}"):
                conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
                             f"({', '.join('?' * len(cols))})", tuple(row))
    holder = sqlite3.connect(str(tmp_path / "obd.db"), timeout=0)
    holder.execute("BEGIN IMMEDIATE")  # another writer holds the lock
    try:
        with caplog.at_level(logging.DEBUG, logger=verdictModule.__name__):
            started = time.monotonic()
            first = _read(obd)
            firstS = time.monotonic() - started
            second = _read(obd)
            secondS = time.monotonic() - started - firstS
    finally:
        holder.rollback()
        holder.close()
    assert first.verdict == second.verdict == VERDICT_GOOD
    # Each read's history write is bounded by the short busy timeout (~0.5 s).
    assert firstS < 1.2 and secondS < 1.2, (firstS, secondS)
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and "history write" in r.getMessage()]
    assert len(warnings) == 1
