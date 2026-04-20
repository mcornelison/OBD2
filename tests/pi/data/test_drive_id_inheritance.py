################################################################################
# File Name: test_drive_id_inheritance.py
# Purpose/Description: Behavioral tests that writers persist the current
#                      drive_id into capture rows (US-200 / Spool Data v2 #2).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Writer-level integration tests for drive_id (US-200).

Spool spec: every row written while a drive is active must carry the
owning drive_id.  Writers consult
:func:`src.pi.obdii.drive_id.getCurrentDriveId` and stamp the result
into the INSERT.  Rows written with no active drive end up with NULL
drive_id (which is the correct signal -- pre-crank boot noise,
shutdown events, etc.).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest

from src.pi.obdii.data_source import DATA_SOURCE_DEFAULT
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_id import (
    clearCurrentDriveId,
    getCurrentDriveId,
    setCurrentDriveId,
)

# ================================================================================
# Fixture: isolated Pi DB + context reset
# ================================================================================

@pytest.fixture(autouse=True)
def resetDriveIdContext() -> Generator[None, None, None]:
    """Writers share a module-level current-drive context; isolate it."""
    clearCurrentDriveId()
    yield
    clearCurrentDriveId()


@pytest.fixture
def db(tmp_path) -> Generator[ObdDatabase, None, None]:
    dbPath = tmp_path / "obd.db"
    database = ObdDatabase(str(dbPath), walMode=False)
    database.initialize()
    # Seed the 'daily' profile so FK constraints on writers don't blow up
    with database.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO profiles (id, name) VALUES ('daily', 'Daily')"
        )
    yield database


# ================================================================================
# Current-drive context API
# ================================================================================

class TestDriveIdContext:
    def test_defaultsToNone(self) -> None:
        assert getCurrentDriveId() is None

    def test_setAndGetRoundTrip(self) -> None:
        setCurrentDriveId(42)
        assert getCurrentDriveId() == 42

    def test_clearResetsToNone(self) -> None:
        setCurrentDriveId(42)
        clearCurrentDriveId()
        assert getCurrentDriveId() is None

    def test_setNoneExplicitly(self) -> None:
        setCurrentDriveId(7)
        setCurrentDriveId(None)
        assert getCurrentDriveId() is None


# ================================================================================
# helpers.logReading tags realtime_data with current drive_id
# ================================================================================

class TestRealtimeDataWriter:
    def test_logReadingDuringDriveTagsDriveId(self, db: ObdDatabase) -> None:
        from src.pi.obdii.data.helpers import logReading
        from src.pi.obdii.data.types import LoggedReading

        setCurrentDriveId(5)
        reading = LoggedReading(
            parameterName='RPM', value=800.0, unit='rpm',
            timestamp=datetime(2026, 4, 19, 12, 0, 0),
            profileId='daily',
        )
        logReading(db, reading)

        with db.connect() as conn:
            row = conn.execute(
                "SELECT drive_id FROM realtime_data WHERE parameter_name='RPM'"
            ).fetchone()
            assert row[0] == 5

    def test_logReadingNoDriveLeavesDriveIdNull(self, db: ObdDatabase) -> None:
        from src.pi.obdii.data.helpers import logReading
        from src.pi.obdii.data.types import LoggedReading

        # No active drive -- context is None
        reading = LoggedReading(
            parameterName='RPM', value=800.0, unit='rpm',
            timestamp=datetime(2026, 4, 19, 12, 0, 0),
            profileId='daily',
        )
        logReading(db, reading)

        with db.connect() as conn:
            row = conn.execute(
                "SELECT drive_id FROM realtime_data WHERE parameter_name='RPM'"
            ).fetchone()
            assert row[0] is None

    def test_logReadingUsesDefaultDataSource(self, db: ObdDatabase) -> None:
        """Confirm US-195 default carries through alongside drive_id."""
        from src.pi.obdii.data.helpers import logReading
        from src.pi.obdii.data.types import LoggedReading

        setCurrentDriveId(1)
        reading = LoggedReading(
            parameterName='RPM', value=800.0, unit='rpm',
            timestamp=datetime(2026, 4, 19, 12, 0, 0),
            profileId='daily',
        )
        logReading(db, reading)

        with db.connect() as conn:
            row = conn.execute(
                "SELECT drive_id, data_source FROM realtime_data "
                "WHERE parameter_name='RPM'"
            ).fetchone()
            assert row[0] == 1
            assert row[1] == DATA_SOURCE_DEFAULT

    def test_driveIdChangesBetweenSequentialRows(
        self, db: ObdDatabase
    ) -> None:
        """Two drives in sequence -> rows carry different drive_ids."""
        from src.pi.obdii.data.helpers import logReading
        from src.pi.obdii.data.types import LoggedReading

        # Drive 1
        setCurrentDriveId(1)
        logReading(db, LoggedReading(
            parameterName='RPM', value=800.0, unit='rpm',
            timestamp=datetime(2026, 4, 19, 12, 0, 0),
            profileId='daily',
        ))
        # Drive ends
        setCurrentDriveId(None)
        # Drive 2
        setCurrentDriveId(2)
        logReading(db, LoggedReading(
            parameterName='RPM', value=850.0, unit='rpm',
            timestamp=datetime(2026, 4, 19, 13, 0, 0),
            profileId='daily',
        ))

        with db.connect() as conn:
            rows = conn.execute(
                "SELECT drive_id FROM realtime_data "
                "WHERE parameter_name='RPM' ORDER BY id"
            ).fetchall()
            assert [r[0] for r in rows] == [1, 2]


# ================================================================================
# statistics writer (analysis.engine)
# ================================================================================

class TestStatisticsWriter:
    @staticmethod
    def _makeResult(parameterName: str) -> AnalysisResult:  # noqa: F821
        from common.analysis.types import AnalysisResult, ParameterStatistics
        tsAware = datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC)
        ps = ParameterStatistics(
            parameterName=parameterName,
            profileId='daily',
            analysisDate=tsAware,
            maxValue=3500.0,
            minValue=700.0,
            avgValue=1800.0,
            modeValue=800.0,
            std1=200.0,
            std2=400.0,
            outlierMin=1000.0,
            outlierMax=2600.0,
            sampleCount=120,
        )
        return AnalysisResult(
            analysisDate=tsAware,
            profileId='daily',
            parameterStats={parameterName: ps},
            totalParameters=1,
            totalSamples=120,
            success=True,
        )

    def test_statisticsRowsCarryDriveId(self, db: ObdDatabase) -> None:
        """StatisticsEngine._storeStatistics stamps drive_id per row."""
        from src.pi.analysis.engine import StatisticsEngine

        setCurrentDriveId(9)
        engine = StatisticsEngine(db, {'pi': {}})
        engine._storeStatistics(self._makeResult('RPM'))

        with db.connect() as conn:
            row = conn.execute(
                "SELECT drive_id FROM statistics WHERE parameter_name='RPM'"
            ).fetchone()
            assert row[0] == 9

    def test_statisticsRowsNullWhenNoDrive(self, db: ObdDatabase) -> None:
        from src.pi.analysis.engine import StatisticsEngine

        engine = StatisticsEngine(db, {'pi': {}})
        engine._storeStatistics(self._makeResult('SPEED'))

        with db.connect() as conn:
            row = conn.execute(
                "SELECT drive_id FROM statistics WHERE parameter_name='SPEED'"
            ).fetchone()
            assert row[0] is None


# ================================================================================
# alert_log writer (alert.manager)
# ================================================================================

class TestAlertWriter:
    def test_alertRowsCarryDriveId(self, db: ObdDatabase) -> None:
        """AlertManager._logAlertToDatabase stamps current drive_id."""
        from src.pi.alert.manager import AlertManager
        from src.pi.alert.types import AlertEvent

        setCurrentDriveId(12)
        manager = AlertManager(database=db)
        event = AlertEvent(
            alertType='critical',
            parameterName='COOLANT_TEMP',
            value=115.0,
            threshold=110.0,
            profileId='daily',
        )
        manager._logAlertToDatabase(event)

        with db.connect() as conn:
            row = conn.execute(
                "SELECT drive_id FROM alert_log "
                "WHERE parameter_name='COOLANT_TEMP'"
            ).fetchone()
            assert row is not None
            assert row[0] == 12


# ================================================================================
# connection_log drive_event writer (drive.detector)
# ================================================================================

class TestDriveEventWriter:
    def test_driveEventRowsCarryDriveId(self, db: ObdDatabase) -> None:
        """_logDriveEvent stamps drive_id so connection_log drive_start/drive_end
        rows group with the realtime rows of the same drive."""
        from src.pi.obdii.drive.detector import DriveDetector

        detector = DriveDetector(
            config={'pi': {'profiles': {'activeProfile': 'daily'}}},
            statisticsEngine=None, database=db,
        )
        # Simulate the detector having just started a drive
        setCurrentDriveId(77)
        detector._logDriveEvent('drive_start', datetime(2026, 4, 19, 12, 0, 0))

        with db.connect() as conn:
            row = conn.execute(
                "SELECT drive_id FROM connection_log "
                "WHERE event_type='drive_start'"
            ).fetchone()
            assert row is not None
            assert row[0] == 77


class TestDriveDetectorLifecycle:
    def test_startDriveOpensIdFromCounter(self, db: ObdDatabase) -> None:
        """DriveDetector._startDrive mints a new id + publishes to context."""
        from src.pi.obdii.drive.detector import DriveDetector

        detector = DriveDetector(
            config={'pi': {'profiles': {'activeProfile': 'daily'}}},
            statisticsEngine=None, database=db,
        )
        assert getCurrentDriveId() is None
        detector._startDrive(datetime(2026, 4, 19, 12, 0, 0))
        assert getCurrentDriveId() == 1

    def test_endDriveClosesContext(self, db: ObdDatabase) -> None:
        from src.pi.obdii.drive.detector import DriveDetector

        detector = DriveDetector(
            config={'pi': {'profiles': {'activeProfile': 'daily'}}},
            statisticsEngine=None, database=db,
        )
        detector._startDrive(datetime(2026, 4, 19, 12, 0, 0))
        assert getCurrentDriveId() == 1
        detector._endDrive()
        assert getCurrentDriveId() is None

    def test_twoDrivesMintDistinctIds(self, db: ObdDatabase) -> None:
        from src.pi.obdii.drive.detector import DriveDetector

        detector = DriveDetector(
            config={'pi': {'profiles': {'activeProfile': 'daily'}}},
            statisticsEngine=None, database=db,
        )
        detector._startDrive(datetime(2026, 4, 19, 12, 0, 0))
        firstId = getCurrentDriveId()
        detector._endDrive()
        detector._startDrive(datetime(2026, 4, 19, 13, 0, 0))
        secondId = getCurrentDriveId()
        assert firstId == 1
        assert secondId == 2
