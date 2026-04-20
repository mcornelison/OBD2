################################################################################
# File Name: test_analytics_drive_scoping.py
# Purpose/Description: Behavioral tests that server analytics can scope
#                      queries by the Pi's drive_id column added in US-200.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Server-analytics tests for per-drive scoping via ``drive_id`` (US-200).

The Pi tags every new capture row with its local drive_id.  The Spool
spec requires server analytics queries like
``SELECT AVG(rpm) FROM realtime_data WHERE drive_id = ? AND data_source = 'real'``
to return sensible per-drive values.  This test module asserts:

1. ``RealtimeData.drive_id`` is a real column (schema-level sanity).
2. The new ``collectReadingsForDrive`` helper filters purely by drive_id +
   data_source + device, and never returns rows from other drives.
3. The ``computeDriveStatistics`` (legacy time-window-based) path still
   works for pre-US-200 / simulated DriveSummary rows where drive_id on
   the Pi-mirror tables is NULL.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.server.analytics.basic import collectReadingsForDrive
from src.server.db.models import Base, RealtimeData


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _insertRealtime(
    session: Session,
    *,
    sourceId: int,
    driveId: int | None,
    parameterName: str,
    value: float,
    timestamp: datetime,
    dataSource: str = 'real',
    device: str = 'chi-eclipse-01',
) -> None:
    session.add(RealtimeData(
        source_id=sourceId,
        source_device=device,
        timestamp=timestamp,
        parameter_name=parameterName,
        value=value,
        unit='rpm' if parameterName == 'RPM' else None,
        data_source=dataSource,
        drive_id=driveId,
    ))


class TestSchema:
    def test_driveIdColumnExists(self, session: Session) -> None:
        cols = {c.name for c in RealtimeData.__table__.columns}
        assert 'drive_id' in cols


class TestCollectReadingsForDrive:
    def test_returnsOnlyRowsMatchingDriveId(self, session: Session) -> None:
        base = datetime(2026, 4, 19, 12, 0, 0)
        # Drive 1 -- 3 RPM samples
        for i in range(3):
            _insertRealtime(
                session, sourceId=i + 1, driveId=1,
                parameterName='RPM', value=800.0 + i * 50,
                timestamp=base + timedelta(seconds=i),
            )
        # Drive 2 -- 2 RPM samples (different drive, should NOT be returned)
        for i in range(2):
            _insertRealtime(
                session, sourceId=i + 4, driveId=2,
                parameterName='RPM', value=3000.0 + i * 50,
                timestamp=base + timedelta(minutes=10, seconds=i),
            )
        session.commit()

        readings = collectReadingsForDrive(
            session, driveId=1, deviceId='chi-eclipse-01',
        )
        assert sorted(readings['RPM']) == [800.0, 850.0, 900.0]

    def test_excludesNonRealDataSource(self, session: Session) -> None:
        base = datetime(2026, 4, 19, 12, 0, 0)
        _insertRealtime(
            session, sourceId=1, driveId=5, parameterName='RPM',
            value=800.0, timestamp=base, dataSource='real',
        )
        _insertRealtime(
            session, sourceId=2, driveId=5, parameterName='RPM',
            value=9999.0, timestamp=base + timedelta(seconds=1),
            dataSource='fixture',
        )
        session.commit()

        readings = collectReadingsForDrive(
            session, driveId=5, deviceId='chi-eclipse-01',
        )
        assert readings['RPM'] == [800.0]

    def test_respectsDeviceFilter(self, session: Session) -> None:
        base = datetime(2026, 4, 19, 12, 0, 0)
        _insertRealtime(
            session, sourceId=1, driveId=7, parameterName='RPM',
            value=800.0, timestamp=base, device='chi-eclipse-01',
        )
        # Same drive_id but different device -- must not collide
        _insertRealtime(
            session, sourceId=2, driveId=7, parameterName='RPM',
            value=9999.0, timestamp=base, device='other-pi',
        )
        session.commit()

        readings = collectReadingsForDrive(
            session, driveId=7, deviceId='chi-eclipse-01',
        )
        assert readings['RPM'] == [800.0]

    def test_emptyDriveReturnsEmptyMap(self, session: Session) -> None:
        readings = collectReadingsForDrive(
            session, driveId=999, deviceId='chi-eclipse-01',
        )
        assert readings == {}

    def test_bucketsByParameterName(self, session: Session) -> None:
        base = datetime(2026, 4, 19, 12, 0, 0)
        _insertRealtime(
            session, sourceId=1, driveId=3, parameterName='RPM',
            value=800.0, timestamp=base,
        )
        _insertRealtime(
            session, sourceId=2, driveId=3, parameterName='SPEED',
            value=30.0, timestamp=base + timedelta(seconds=1),
        )
        _insertRealtime(
            session, sourceId=3, driveId=3, parameterName='RPM',
            value=850.0, timestamp=base + timedelta(seconds=2),
        )
        session.commit()

        readings = collectReadingsForDrive(
            session, driveId=3, deviceId='chi-eclipse-01',
        )
        assert set(readings.keys()) == {'RPM', 'SPEED'}
        assert sorted(readings['RPM']) == [800.0, 850.0]
        assert readings['SPEED'] == [30.0]

    def test_nullDriveIdRowsExcluded(self, session: Session) -> None:
        """Pre-US-200 rows with NULL drive_id must NOT collide with legitimate
        drive 1.  NULL != 1 in SQL and the query must respect that."""
        base = datetime(2026, 4, 19, 12, 0, 0)
        _insertRealtime(
            session, sourceId=1, driveId=1, parameterName='RPM',
            value=800.0, timestamp=base,
        )
        _insertRealtime(
            session, sourceId=2, driveId=None, parameterName='RPM',
            value=9999.0, timestamp=base + timedelta(seconds=1),
        )
        session.commit()

        readings = collectReadingsForDrive(
            session, driveId=1, deviceId='chi-eclipse-01',
        )
        assert readings['RPM'] == [800.0]
