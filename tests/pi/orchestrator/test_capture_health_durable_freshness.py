################################################################################
# File Name: test_capture_health_durable_freshness.py
# Purpose/Description: US-727 -- a restart must stop erasing how long capture has
#     actually been dead. `lastRowWrittenSecondsAgo` is a time.monotonic() marker
#     on the logger INSTANCE, None until THIS process writes its first row, so a
#     Pi dead since yesterday read identically to one that booted forty seconds
#     ago: both reported never_written. The acquisition now falls back to the
#     DURABLE record (MAX(realtime_data.timestamp)) when the in-process marker is
#     absent -- and keeps three DISTINCT typed absences, none of them a number.
# Author: Rex (US-727)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-22    | Rex (US-727)   | Initial -- durable fallback, the three
#               |                | absences, and the signature fence.
# ================================================================================
################################################################################
"""US-727: capture-health reads the durable record when the process marker is gone."""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pi.obdii.capture_health import (
    DEFAULT_STALL_SECONDS,
    REASON_LOGGER_ABSENT,
    REASON_NEVER_WRITTEN,
    REASON_UNREADABLE,
    STATE_STALLED,
    buildCaptureHealthState,
)
from pi.obdii.orchestrator.health_monitor import HealthMonitorMixin

# The measured live case: the Pi's newest realtime_data row was 253,333 s old
# (2026-09-22, read from the car). 26.5 h is the story's stated fixture.
_MEASURED_AGE_S = 26.5 * 3600

_SCHEMA = "CREATE TABLE realtime_data (id INTEGER PRIMARY KEY, timestamp TEXT)"


class _Db:
    """An ObdDatabase-shaped handle over a real SQLite file."""

    def __init__(self, path: Path, *, rows: list[str] | None = None, broken: bool = False):
        self.dbPath = str(path)
        self._broken = broken
        with sqlite3.connect(self.dbPath) as conn:
            conn.execute(_SCHEMA)
            for ts in rows or []:
                conn.execute("INSERT INTO realtime_data (timestamp) VALUES (?)", (ts,))

    @contextmanager
    def connect(self):
        if self._broken:
            raise sqlite3.OperationalError("database is locked")
        conn = sqlite3.connect(self.dbPath)
        try:
            yield conn
        finally:
            conn.close()


class _Logger:
    """A RealtimeDataLogger stand-in: the marker is None until THIS process
    writes a row, which is the whole defect."""

    def __init__(self, lastRowWrittenSecondsAgo=None):
        self.lastRowWrittenSecondsAgo = lastRowWrittenSecondsAgo


class _Monitor(HealthMonitorMixin):
    def __init__(self, *, dataLogger=None, database=None):
        self._dataLogger = dataLogger
        self._database = database


def _isoAgo(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _isoAhead(seconds: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------- the durable fallback


def test_restartAfterADeadDay_reportsTheRealAgeFromTheDatabase(tmp_path: Path) -> None:
    """
    Given: a logger whose in-process marker is None (a fresh restart) and a
        database whose newest row is 26.5 h old
    When: the freshness is read
    Then: the REAL age, with no reason -- on dev this same input returns
        (None, 'never_written') and the alert loses the only number it had
    """
    monitor = _Monitor(
        dataLogger=_Logger(None),
        database=_Db(tmp_path / "a.db", rows=[_isoAgo(_MEASURED_AGE_S)]),
    )

    value, reason = monitor._readDataLoggerRowFreshness()

    assert reason is None
    assert value == pytest.approx(_MEASURED_AGE_S, rel=0.01)


def test_theStateBuiltFromThatReadingIsStalled_withTheAgeCarried(tmp_path: Path) -> None:
    """
    Given: the same restart-after-a-dead-day shape, on external power
    When: the capture-health state is built
    Then: stalled, with the age in lastRowSecondsAgo. Dev reports
        reason='never_written' and lastRowSecondsAgo=None for this input
    """
    monitor = _Monitor(
        dataLogger=_Logger(None),
        database=_Db(tmp_path / "b.db", rows=[_isoAgo(_MEASURED_AGE_S)]),
    )
    value, reason = monitor._readDataLoggerRowFreshness()

    state = buildCaptureHealthState(
        lastRowSecondsAgo=value,
        freshnessReason=reason,
        powerSource="external",
        stallSeconds=DEFAULT_STALL_SECONDS,
        nowIso="2026-09-22T15:00:00Z",
    )

    assert state["state"] == STATE_STALLED
    assert state["reason"] == STATE_STALLED
    assert state["lastRowSecondsAgo"] == pytest.approx(_MEASURED_AGE_S, rel=0.01)


def test_aLiveInProcessMarkerStillWins(tmp_path: Path) -> None:
    """The durable read is a FALLBACK: a process that has written a row reports
    its own marker, unchanged, and never touches the database."""
    monitor = _Monitor(
        dataLogger=_Logger(12.5),
        database=_Db(tmp_path / "c.db", rows=[_isoAgo(_MEASURED_AGE_S)]),
    )

    assert monitor._readDataLoggerRowFreshness() == (12.5, None)


# ------------------------------------------------- the three typed absences


def test_emptyCaptureTable_isStillNeverWritten(tmp_path: Path) -> None:
    """The honest answer for a genuinely empty table survives: a Pi that has
    truly never captured still says so."""
    monitor = _Monitor(dataLogger=_Logger(None), database=_Db(tmp_path / "d.db"))

    assert monitor._readDataLoggerRowFreshness() == (None, REASON_NEVER_WRITTEN)


def test_noDatabase_isUnreadable_notNeverWritten(tmp_path: Path) -> None:
    """An instrument we cannot consult is not a measurement of capture."""
    monitor = _Monitor(dataLogger=_Logger(None), database=None)

    assert monitor._readDataLoggerRowFreshness() == (None, REASON_UNREADABLE)


def test_aRaisingDatabase_isUnreadable(tmp_path: Path) -> None:
    """A locked or mid-migration DB degrades to unreadable, never to a stall."""
    monitor = _Monitor(
        dataLogger=_Logger(None), database=_Db(tmp_path / "e.db", broken=True),
    )

    assert monitor._readDataLoggerRowFreshness() == (None, REASON_UNREADABLE)


def test_aFutureRow_isUnreadable_andTheAgeIsNeverClampedToZero(tmp_path: Path) -> None:
    """
    Given: the newest row stamped an hour in the FUTURE -- the dead-RTC case,
        where the Pi boots at 1970 and steps forward when NTP lands
    When: the freshness is read
    Then: unreadable. A negative age is a broken clock, and clamping it to 0
        would report "captured just now" on the strength of a bad timestamp
    """
    monitor = _Monitor(
        dataLogger=_Logger(None),
        database=_Db(tmp_path / "f.db", rows=[_isoAhead(3600)]),
    )

    assert monitor._readDataLoggerRowFreshness() == (None, REASON_UNREADABLE)


def test_noLoggerAtAll_isStillLoggerAbsent(tmp_path: Path) -> None:
    """The bench shape is unchanged, and it never reaches the database."""
    monitor = _Monitor(
        dataLogger=None, database=_Db(tmp_path / "g.db", rows=[_isoAgo(60)]),
    )

    assert monitor._readDataLoggerRowFreshness() == (None, REASON_LOGGER_ABSENT)


def test_theThreeAbsencesStayDistinct(tmp_path: Path) -> None:
    """Never-captured, no-logger and cannot-read are three different facts, and
    the alert is only correct for the first."""
    assert len({REASON_NEVER_WRITTEN, REASON_LOGGER_ABSENT, REASON_UNREADABLE}) == 3


# ----------------------------------------------------------- the layer fence


def test_theDeciderSignatureIsUnchanged() -> None:
    """
    Given: buildCaptureHealthState
    When: its parameters are read
    Then: exactly the pinned set. The durable read belongs in the ACQUISITION
        layer; needing a new argument here would mean the read is in the wrong
        place (and this signature is what keeps transport-derived facts out)
    """
    params = list(inspect.signature(buildCaptureHealthState).parameters)

    assert params == [
        "lastRowSecondsAgo",
        "freshnessReason",
        "powerSource",
        "stallSeconds",
        "nowIso",
    ]


def test_theDurableReadIsNotInThePureDecider() -> None:
    """capture_health stays pure: no SQL, no database handle, no clock of the
    database's."""
    source = Path(
        inspect.getsourcefile(buildCaptureHealthState)  # type: ignore[arg-type]
    ).read_text(encoding="utf-8")

    for forbidden in ("realtime_data", "julianday", "connect(", "sqlite"):
        assert forbidden not in source, forbidden
