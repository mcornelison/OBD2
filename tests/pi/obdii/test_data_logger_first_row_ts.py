################################################################################
# File Name: test_data_logger_first_row_ts.py
# Purpose/Description: US-873 -- ObdDataLogger.firstRowTs is the canonical
#                      timestamp of the first realtime_data row this process
#                      committed: set once, never by a failed INSERT, never reset
#                      by a reconnect pause/resume.
# Author: Rex (US-873)
# Creation Date: 2026-10-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-13    | Rex (US-873) | Initial -- Atlas option A, tests (1)-(4).
# ================================================================================
################################################################################
"""ObdDataLogger.firstRowTs (US-873, Atlas option A).

capture-health's ``feeds.obd.firstSampleTs`` is "the event time of the first
realtime_data row written in this process". One ObdDataLogger writes every live
row for the whole process, so the writer already knows that value exactly; these
tests pin that it records it at the right moment and only then.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.data.exceptions import DataLoggerError
from src.pi.obdii.data.logger import ObdDataLogger
from src.pi.obdii.data.realtime import RealtimeDataLogger
from src.pi.obdii.data.types import LoggedReading
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.orchestrator.connection_recovery import ConnectionRecoveryMixin

_CONFIG: dict[str, Any] = {
    "pi": {
        "time": {"localZone": "America/Chicago"},
        "realtimeData": {"pollingIntervalMs": 50, "parameters": ["RPM"]},
    }
}


@pytest.fixture
def freshDb(tmp_path: Path) -> Generator[ObdDatabase, None, None]:
    db = ObdDatabase(str(tmp_path / "capture.db"), walMode=False)
    db.initialize()
    yield db


class _NullResponse:
    def is_null(self) -> bool:
        return True


class _Connection:
    """Connected, but every query comes back null -- the poll loop writes nothing."""

    isSimulated = False

    def isConnected(self) -> bool:
        return True

    def query(self, cmd: Any) -> _NullResponse:
        return _NullResponse()


def _reading(timestamp: datetime) -> LoggedReading:
    return LoggedReading(
        parameterName="RPM", value=800.0, timestamp=timestamp,
        unit="rpm", profileId=None,  # profile_id is a FK; no profile row here
    )


def _storedTimestamps(db: ObdDatabase) -> list[str]:
    with db.connect() as conn:
        rows = conn.execute("SELECT timestamp FROM realtime_data ORDER BY id").fetchall()
    return [row[0] for row in rows]


class _RaisingDatabase:
    """A database whose INSERT fails, as a locked or full disk would."""

    def connect(self) -> Any:
        class _Cursor:
            def execute(self, sql: str, params: tuple[Any, ...]) -> None:
                raise OSError("database is locked")

        class _Conn:
            def cursor(self) -> _Cursor:
                return _Cursor()

            def __enter__(self) -> _Conn:
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

        return _Conn()


class TestFirstRowTs:

    def test_newLogger_firstRowTsIsNone(self, freshDb) -> None:
        """
        Given: a logger that has written nothing
        When:  firstRowTs is read
        Then:  it is None -- never a placeholder time
        """
        assert ObdDataLogger(_Connection(), freshDb, config=_CONFIG).firstRowTs is None

    def test_firstWrite_setsFirstRowTsToTheRowsTimestamp(self, freshDb) -> None:
        """
        Given: a fresh logger
        When:  one reading is logged
        Then:  firstRowTs equals the timestamp READ BACK from that row
        """
        dataLogger = ObdDataLogger(_Connection(), freshDb, config=_CONFIG)

        dataLogger.logReading(_reading(datetime(2026, 10, 13, 7, 1, 5)))

        assert _storedTimestamps(freshDb) == [dataLogger.firstRowTs]
        assert dataLogger.firstRowTs is not None

    def test_secondWrite_leavesFirstRowTsUnchanged(self, freshDb) -> None:
        """
        Given: a logger that has written one row
        When:  a later reading is logged
        Then:  firstRowTs still names the FIRST row
        """
        dataLogger = ObdDataLogger(_Connection(), freshDb, config=_CONFIG)
        dataLogger.logReading(_reading(datetime(2026, 10, 13, 7, 1, 5)))
        dataLogger.logReading(_reading(datetime(2026, 10, 13, 7, 1, 6)))

        first, second = _storedTimestamps(freshDb)

        assert dataLogger.firstRowTs == first
        assert first != second

    def test_insertThatRaises_leavesFirstRowTsNone(self) -> None:
        """
        Given: a database whose INSERT raises
        When:  a reading is logged
        Then:  DataLoggerError is raised and firstRowTs stays None
        """
        dataLogger = ObdDataLogger(_Connection(), _RaisingDatabase(), config=_CONFIG)

        with pytest.raises(DataLoggerError):
            dataLogger.logReading(_reading(datetime(2026, 10, 13, 7, 1, 5)))

        assert dataLogger.firstRowTs is None

    def test_reconnectPauseResume_doesNotResetFirstRowTs(self, freshDb) -> None:
        """
        Given: the realtime logger wrote one row, then the reconnect path
               pauses and resumes it (connection_recovery)
        When:  firstRowTs is read afterwards
        Then:  the same writer instance still holds the first row's timestamp
        """
        realtime = RealtimeDataLogger(_CONFIG, _Connection(), freshDb)
        writer = realtime.dataLogger
        writer.logReading(_reading(datetime(2026, 10, 13, 7, 1, 5)))
        firstTs = writer.firstRowTs
        realtime.start()
        orch = SimpleNamespace(_dataLogger=realtime, _dataLoggerPausedForReconnect=False)

        try:
            ConnectionRecoveryMixin._pauseDataLogging(orch)
            assert orch._dataLoggerPausedForReconnect is True
            ConnectionRecoveryMixin._resumeDataLogging(orch)
            assert orch._dataLoggerPausedForReconnect is False
        finally:
            realtime.stop()

        assert realtime.dataLogger is writer
        assert writer.firstRowTs == firstTs == _storedTimestamps(freshDb)[0]
