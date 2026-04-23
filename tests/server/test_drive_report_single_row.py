################################################################################
# File Name: test_drive_report_single_row.py
# Purpose/Description: US-214 -- verify that post-reconciliation the drive
#                      report surfaces one row per drive (not two, as the
#                      US-206 dual-writer pattern produced pre-US-214).
# Author: Rex (Ralph)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-214) | Initial single-row-per-drive report tests.
# ================================================================================
################################################################################

"""Post-reconciliation reports must surface one row per drive.

Before US-214 the all-drives summary table would double-count every drive
(the US-206 dual-writer left an analytics-only row and a Pi-sync-only row
for the same drive).  After US-214 the reconciled row carries both halves
so the table shows one row per drive with analytics + metadata populated.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import Base, DriveSummary  # noqa: E402
from src.server.reports.drive_report import buildAllDrivesReport  # noqa: E402
from src.server.services.analysis import _ensureDriveSummary  # noqa: E402


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def _insertPiSyncRow(
    session: Session, *, driveId: int, driveStartTs: datetime,
) -> int:
    row = DriveSummary(
        source_device="chi-eclipse-01",
        source_id=driveId,
        drive_id=driveId,
        drive_start_timestamp=driveStartTs,
        ambient_temp_at_start_c=20.0,
        starting_battery_v=12.5,
        barometric_kpa_at_start=99.1,
        data_source="real",
    )
    session.add(row)
    session.flush()
    return row.id


class TestReportSingleRowPerDrive:
    """Two drives, full Pi-first + analytics flow → report shows 2 rows."""

    def test_allDrivesReport_oneRowPerDrive(self, session):
        driveOneStart = datetime(2026, 4, 21, 10, 0, 0)
        driveOneEnd = datetime(2026, 4, 21, 10, 15, 0)
        driveTwoStart = datetime(2026, 4, 21, 14, 0, 0)
        driveTwoEnd = datetime(2026, 4, 21, 14, 20, 0)

        _insertPiSyncRow(session, driveId=1, driveStartTs=driveOneStart)
        _insertPiSyncRow(session, driveId=2, driveStartTs=driveTwoStart)
        session.commit()

        _ensureDriveSummary(
            session, "chi-eclipse-01", driveOneStart, driveOneEnd, driveId=1,
        )
        _ensureDriveSummary(
            session, "chi-eclipse-01", driveTwoStart, driveTwoEnd, driveId=2,
        )
        session.commit()

        report = buildAllDrivesReport(session)

        # The report header + borders consume a few lines; count the data rows
        # by looking for the 2026-04-21 prefix.
        dataLines = [line for line in report.splitlines() if "2026-04-21" in line]
        assert len(dataLines) == 2

    def test_piFirstThenAnalytics_singleRowHasAllFields(self, session):
        """Analytics UPDATE populates all fields on the existing Pi-sync row."""
        driveStart = datetime(2026, 4, 21, 10, 0, 0)
        driveEnd = datetime(2026, 4, 21, 10, 15, 0)

        piRowId = _insertPiSyncRow(session, driveId=1, driveStartTs=driveStart)
        session.commit()

        analyticsRowId = _ensureDriveSummary(
            session, "chi-eclipse-01", driveStart, driveEnd, driveId=1,
        )
        session.commit()

        # Same physical row -- analytics updated Pi-sync row in place.
        assert analyticsRowId == piRowId
        row = session.get(DriveSummary, piRowId)
        assert row.device_id == "chi-eclipse-01"
        assert row.start_time == driveStart
        assert row.end_time == driveEnd
        assert row.ambient_temp_at_start_c == 20.0
