################################################################################
# File Name: test_data_source_filter.py
# Purpose/Description: Tests for server-side data_source column + analytics
#                      filter + sync pipeline propagation (US-195, Spool CR #4).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-195 (CR #4)
# ================================================================================
################################################################################

"""Server-tier tests for ``data_source`` (US-195).

Three concerns:

1. **Schema** — every mirrored capture-table model carries the
   ``data_source`` column with default ``'real'``.
2. **Sync propagation** — ``runSyncUpsert`` persists ``data_source`` when
   present on a row and coerces missing/None to ``'real'`` so pre-US-195
   Pi rows arrive tagged correctly.
3. **Analytics filter** — ``basic._collectReadings`` ignores non-real
   rows so baselines do not get contaminated by replay / sim / fixture
   data.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics import basic  # noqa: E402
from src.server.api.sync import runSyncUpsert  # noqa: E402
from src.server.db.models import (  # noqa: E402
    Base,
    CalibrationSession,
    ConnectionLog,
    DriveSummary,
    Profile,
    RealtimeData,
    Statistic,
)

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def engine():
    """Sync SQLite engine with server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


# =========================================================================
# Schema: models have data_source column
# =========================================================================


@pytest.mark.parametrize('model', [
    RealtimeData, Statistic, ConnectionLog, CalibrationSession, Profile,
])
def test_mirrorModel_hasDataSourceColumn(model):
    """Every mirrored capture-table model declares data_source."""
    columnNames = {c.name for c in model.__table__.columns}
    assert 'data_source' in columnNames


def test_realtimeData_dataSourceDefaultIsReal(engine):
    """RealtimeData INSERT without data_source lands as 'real'."""
    with Session(engine) as session:
        row = RealtimeData(
            source_id=1,
            source_device='chi-eclipse-01',
            timestamp=datetime(2026, 4, 19, 12, 30, 0),
            parameter_name='RPM',
            value=800.0,
        )
        session.add(row)
        session.commit()

        fetched = session.execute(
            select(RealtimeData).where(RealtimeData.source_id == 1)
        ).scalar_one()
        assert fetched.data_source == 'real'


def test_driveSummary_hasDataSourceColumn(engine):
    """DriveSummary carries data_source for analytics-level tagging."""
    columnNames = {c.name for c in DriveSummary.__table__.columns}
    assert 'data_source' in columnNames


# =========================================================================
# Sync propagation
# =========================================================================


def _buildSyncTables(rows: list[dict]) -> dict:
    """Build the ``tables`` arg for runSyncUpsert around ``realtime_data``."""
    return {
        'realtime_data': {'lastSyncedId': 0, 'rows': rows},
    }


def test_sync_persistsExplicitDataSource(engine):
    """A row arriving with data_source='replay' is persisted as 'replay'."""
    rows = [{
        'id': 1,
        'timestamp': '2026-04-19T12:00:00',
        'parameter_name': 'RPM',
        'value': 800.0,
        'unit': 'rpm',
        'profile_id': 'daily',
        'data_source': 'replay',
    }]

    with Session(engine) as session:
        runSyncUpsert(
            session=session,
            deviceId='chi-eclipse-01',
            batchId='batch-1',
            tables=_buildSyncTables(rows),
            syncHistoryId=1,
        )
        session.commit()

        fetched = session.execute(
            select(RealtimeData).where(RealtimeData.source_id == 1)
        ).scalar_one()
        assert fetched.data_source == 'replay'


def test_sync_coercesMissingDataSourceToReal(engine):
    """Pre-US-195 Pi rows (no data_source key) land as 'real'."""
    rows = [{
        'id': 2,
        'timestamp': '2026-04-19T12:00:00',
        'parameter_name': 'RPM',
        'value': 800.0,
        'unit': 'rpm',
        'profile_id': 'daily',
        # No data_source key -- simulates pre-migration Pi.
    }]

    with Session(engine) as session:
        runSyncUpsert(
            session=session,
            deviceId='chi-eclipse-01',
            batchId='batch-2',
            tables=_buildSyncTables(rows),
            syncHistoryId=2,
        )
        session.commit()

        fetched = session.execute(
            select(RealtimeData).where(RealtimeData.source_id == 2)
        ).scalar_one()
        assert fetched.data_source == 'real'


def test_sync_coercesNoneDataSourceToReal(engine):
    """An explicit None data_source also coerces to 'real'."""
    rows = [{
        'id': 3,
        'timestamp': '2026-04-19T12:00:00',
        'parameter_name': 'RPM',
        'value': 800.0,
        'unit': 'rpm',
        'profile_id': 'daily',
        'data_source': None,
    }]

    with Session(engine) as session:
        runSyncUpsert(
            session=session,
            deviceId='chi-eclipse-01',
            batchId='batch-3',
            tables=_buildSyncTables(rows),
            syncHistoryId=3,
        )
        session.commit()

        fetched = session.execute(
            select(RealtimeData).where(RealtimeData.source_id == 3)
        ).scalar_one()
        assert fetched.data_source == 'real'


# =========================================================================
# Analytics filter
# =========================================================================


def _seedMixedDrive(session: Session) -> tuple[DriveSummary, list[float]]:
    """Seed one drive window with 3 real rows + 2 sim rows of RPM."""
    drive = DriveSummary(
        device_id='chi-eclipse-01',
        start_time=datetime(2026, 4, 19, 12, 0, 0),
        end_time=datetime(2026, 4, 19, 12, 30, 0),
        is_real=True,
    )
    session.add(drive)
    session.flush()

    realValues = [800.0, 810.0, 820.0]
    for i, v in enumerate(realValues, start=1):
        session.add(RealtimeData(
            source_id=i,
            source_device='chi-eclipse-01',
            timestamp=datetime(2026, 4, 19, 12, 5 + i, 0),
            parameter_name='RPM',
            value=v,
            data_source='real',
        ))
    for i, v in enumerate([8000.0, 9000.0], start=10):
        session.add(RealtimeData(
            source_id=i,
            source_device='chi-eclipse-01',
            timestamp=datetime(2026, 4, 19, 12, 10, 0),
            parameter_name='RPM',
            value=v,
            data_source='physics_sim',
        ))
    session.commit()
    return drive, realValues


def test_analytics_collectReadings_filtersToRealOnly(engine):
    """_collectReadings excludes physics_sim rows even in the drive window."""
    with Session(engine) as session:
        drive, realValues = _seedMixedDrive(session)
        buckets = basic._collectReadings(session, drive)

    rpmValues = sorted(buckets['RPM'])
    assert rpmValues == sorted(realValues)


def test_analytics_collectReadings_treatsNullAsReal(engine):
    """Pre-US-195 rows with NULL data_source still count as real (BC)."""
    with Session(engine) as session:
        drive = DriveSummary(
            device_id='chi-eclipse-01',
            start_time=datetime(2026, 4, 19, 12, 0, 0),
            end_time=datetime(2026, 4, 19, 12, 30, 0),
            is_real=True,
        )
        session.add(drive)
        session.flush()

        session.add(RealtimeData(
            source_id=1,
            source_device='chi-eclipse-01',
            timestamp=datetime(2026, 4, 19, 12, 10, 0),
            parameter_name='RPM',
            value=800.0,
            data_source=None,
        ))
        session.commit()

        buckets = basic._collectReadings(session, drive)

    assert buckets['RPM'] == [800.0]
