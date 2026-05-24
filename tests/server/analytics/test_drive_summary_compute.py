################################################################################
# File Name: test_drive_summary_compute.py
# Purpose/Description: Tests for src/server/analytics/drive_summary_compute.py --
#                      US-350 / B-104 Step 1a server-side drive_summary compute
#                      from raw realtime_data + Pi event-log enrichment.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-350) | Initial -- B-104 Step 1a architectural shift.
#               |              | Server reads raw realtime_data + Pi event-log
#               |              | fields and computes drive_summary analytics on a
#               |              | server-side trigger that does NOT depend on a
#               |              | Pi-side drive-end signal.  Replaces the
#               |              | V0.27.7/V0.27.16 trigger-seam writer architecture
#               |              | that produced the recurring NULL-fields false-pass
#               |              | (US-326 / US-348 / I-040).
# ================================================================================
################################################################################

"""US-350 / B-104 Step 1a tests for ``compute_drive_summary``.

The compute path replaces the V0.27.7-V0.27.16 trigger-seam writer
architecture (``_tryAutoAnalysisTrigger`` -> ``enqueueAutoAnalysisForSync``
-> ``_ensureDriveSummary``) with a direct read of raw ``realtime_data``
rows for a given ``drive_id``.  Argus's RCA (2026-05-21): the Pi-side
drive-end signal does not fire when the drive is terminated by sequencer
poweroff, so the writer was never invoked for the just-completed drive.
Server compute path that reads raw realtime_data MIN/MAX/COUNT does not
depend on a marker event -- bug class structurally moot.

Test discipline (post-I-040 / Tester I-040 lesson)
--------------------------------------------------

* No mocks of the compute function's seams.  Tests use a real in-memory
  SQLite engine + the real ORM models + real INSERTs of synthetic
  ``realtime_data`` and ``drive_summary`` rows.
* The compute function is exercised against the populated DB and the
  drive_summary row's analytics fields are read back to assert the
  derived values.
* Idempotency is verified by running the compute twice and asserting
  data values match (``computed_at`` may update; the analytics columns
  must not drift).
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.drive_summary_compute import (  # noqa: E402
    compute_drive_summary,
)
from src.server.db.models import (  # noqa: E402
    Base,
    DriveSummary,
    RealtimeData,
)

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def engine():
    """Temp-file SQLite engine carrying the full server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _seedPiSyncedDriveSummary(
    session: Session,
    *,
    driveId: int,
    device: str = "chi-eclipse-01",
    dataSource: str | None = "real",
    ambientTemp: float | None = 19.0,
    startingBatteryV: float | None = 14.2,
    driveStartTimestamp: datetime | None = None,
) -> int:
    """Seed a Pi-sync drive_summary row with NULL analytics fields.

    Mirrors the production state Argus observed on drive 20 in the V0.27.16
    drill: event-log columns populated, computed analytics columns NULL.
    Returns the server-side ``drive_summary.id``.
    """
    row = DriveSummary(
        source_device=device,
        source_id=driveId,
        drive_id=driveId,
        drive_start_timestamp=driveStartTimestamp,
        ambient_temp_at_start_c=ambientTemp,
        starting_battery_v=startingBatteryV,
        data_source=dataSource if dataSource is not None else "real",
        # Analytics fields explicitly left NULL.
        start_time=None,
        end_time=None,
        duration_seconds=None,
        row_count=None,
        is_real=None,
    )
    session.add(row)
    session.commit()

    # SQLAlchemy applies ``server_default='real'`` when an ORM-level None
    # is passed on INSERT; force a NULL via a follow-up UPDATE so tests
    # of the NULL-preservation branch can drive the real production
    # state (Pi events shipped without data_source pre-US-195 BC).
    if dataSource is None:
        from sqlalchemy import update
        session.execute(
            update(DriveSummary)
            .where(DriveSummary.id == row.id)
            .values(data_source=None)
        )
        session.commit()

    return row.id


def _seedRealtimeRows(
    session: Session,
    *,
    driveId: int,
    device: str = "chi-eclipse-01",
    startTime: datetime,
    parameters: list[str],
    pollIntervalSeconds: float = 1.0,
    samplesPerParameter: int = 10,
    dataSource: str = "real",
) -> int:
    """Seed ``realtime_data`` rows for a drive.  Returns total row count."""
    total = 0
    sourceIdCursor = driveId * 100_000
    for i in range(samplesPerParameter):
        ts = startTime + timedelta(seconds=i * pollIntervalSeconds)
        for param in parameters:
            session.add(
                RealtimeData(
                    source_id=sourceIdCursor,
                    source_device=device,
                    timestamp=ts,
                    parameter_name=param,
                    value=float(100 + i),
                    drive_id=driveId,
                    data_source=dataSource,
                )
            )
            sourceIdCursor += 1
            total += 1
    session.commit()
    return total


# =========================================================================
# compute_drive_summary -- core compute
# =========================================================================


class TestComputeDriveSummaryCore:
    """compute_drive_summary populates analytics fields from raw realtime_data."""

    def test_compute_populatesAnalyticsFields_fromRealtimeData(self, engine):
        """Pre-fix: drive_summary.analytics fields stay NULL forever.

        Post-US-350: server-side compute reads realtime_data MIN/MAX/COUNT
        and writes the analytics fields directly.  No Pi-side drive-end
        trigger required.
        """
        driveId = 20
        startTime = datetime(2026, 5, 21, 17, 29, 21)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(
                session, driveId=driveId,
            )
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                parameters=["RPM", "SPEED", "MAP"],
                pollIntervalSeconds=1.0,
                samplesPerParameter=10,
            )

            returned = compute_drive_summary(session, driveId)
            session.commit()
            assert returned == summaryId

            row = session.get(DriveSummary, summaryId)
            assert row is not None
            assert row.start_time == startTime
            assert row.end_time == startTime + timedelta(seconds=9.0)
            assert row.duration_seconds == 9
            assert row.row_count == 30  # 3 params x 10 samples
            assert row.is_real == 1  # data_source='real' -> 1 per Atlas Q2

    def test_compute_preservesPiEventLogFields(self, engine):
        """ambient_temp / battery_v / data_source / drive_start_timestamp
        survive the compute pass unchanged."""
        driveId = 21
        startTime = datetime(2026, 5, 21, 18, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(
                session,
                driveId=driveId,
                ambientTemp=22.5,
                startingBatteryV=13.9,
                dataSource="real",
                driveStartTimestamp=startTime,
            )
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                parameters=["RPM"],
                samplesPerParameter=5,
            )
            compute_drive_summary(session, driveId)
            session.commit()

            row = session.get(DriveSummary, summaryId)
            assert row.ambient_temp_at_start_c == 22.5
            assert row.starting_battery_v == 13.9
            assert row.data_source == "real"
            assert row.drive_start_timestamp == startTime

    def test_compute_noRealtimeRows_returnsNone_doesNotWriteAnalytics(
        self, engine,
    ):
        """A drive with zero realtime_data rows leaves analytics NULL.

        The compute path is read-only over realtime_data; absence of rows
        is not a writer-fired-but-empty situation -- it's "nothing to
        compute yet."  Returns None.
        """
        driveId = 99
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            returned = compute_drive_summary(session, driveId)
            session.commit()

            assert returned is None
            row = session.get(DriveSummary, summaryId)
            assert row.start_time is None
            assert row.end_time is None
            assert row.row_count is None or row.row_count == 0

    def test_compute_missingDriveSummaryRow_returnsNone(self, engine):
        """No drive_summary row for drive_id -> WARN-log + return None.

        Backfill scenarios will always have a Pi-sync row present; an
        absent row is operationally unexpected but should be a non-fatal
        no-op (the on-demand CLI processes range members independently).
        """
        with Session(engine) as session:
            # Seed realtime_data but NO drive_summary row.
            _seedRealtimeRows(
                session,
                driveId=12345,
                startTime=datetime(2026, 5, 21, 19, 0, 0),
                parameters=["RPM"],
                samplesPerParameter=3,
            )
            returned = compute_drive_summary(session, 12345)
            session.commit()
            assert returned is None


# =========================================================================
# Idempotency
# =========================================================================


class TestIdempotent:
    """Re-running compute_drive_summary produces identical analytics values."""

    def test_idempotent(self, engine):
        driveId = 11
        startTime = datetime(2026, 5, 9, 12, 0, 0)
        with Session(engine) as session:
            _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                parameters=["RPM", "SPEED"],
                samplesPerParameter=20,
            )

            compute_drive_summary(session, driveId)
            session.commit()
            first = session.execute(
                select(
                    DriveSummary.start_time,
                    DriveSummary.end_time,
                    DriveSummary.duration_seconds,
                    DriveSummary.row_count,
                    DriveSummary.is_real,
                ).where(DriveSummary.source_id == driveId)
            ).one()

            compute_drive_summary(session, driveId)
            session.commit()
            second = session.execute(
                select(
                    DriveSummary.start_time,
                    DriveSummary.end_time,
                    DriveSummary.duration_seconds,
                    DriveSummary.row_count,
                    DriveSummary.is_real,
                ).where(DriveSummary.source_id == driveId)
            ).one()

            assert first == second


# =========================================================================
# is_real derivation (Atlas Q2)
# =========================================================================


class TestIsRealDerivation:
    """is_real follows Atlas Q2: 'real' -> 1, 'simulator' -> 0, NULL -> NULL.

    Critically: NULL data_source must NOT silently coerce to 0 (FALSE).
    That coercion is the exact failure mode the pre-fix code path
    exhibited (storing 0 even when the data wasn't confirmed real).
    """

    def test_isRealDerivation_real_returnsOne(self, engine):
        driveId = 31
        startTime = datetime(2026, 5, 21, 8, 0, 0)
        with Session(engine) as session:
            _seedPiSyncedDriveSummary(
                session, driveId=driveId, dataSource="real",
            )
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                parameters=["RPM"],
                samplesPerParameter=5,
            )
            compute_drive_summary(session, driveId)
            session.commit()

            row = session.execute(
                select(DriveSummary).where(DriveSummary.source_id == driveId)
            ).scalar_one()
            assert row.is_real == 1

    def test_isRealDerivation_simulator_returnsZero(self, engine):
        driveId = 32
        startTime = datetime(2026, 5, 21, 8, 0, 0)
        with Session(engine) as session:
            _seedPiSyncedDriveSummary(
                session, driveId=driveId, dataSource="simulator",
            )
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                parameters=["RPM"],
                samplesPerParameter=5,
            )
            compute_drive_summary(session, driveId)
            session.commit()

            row = session.execute(
                select(DriveSummary).where(DriveSummary.source_id == driveId)
            ).scalar_one()
            assert row.is_real == 0

    def test_isRealDerivation_nullDataSource_returnsNull_notSilentZero(
        self, engine,
    ):
        """The load-bearing assertion: NULL data_source MUST stay NULL.

        Pre-fix code paths silently coerced this to 0, masking
        "ungraded" drives as confirmed-not-real.  The new compute path
        preserves the NULL signal so Spool's grading queries can
        distinguish "tested + not real" from "untested".
        """
        driveId = 33
        startTime = datetime(2026, 5, 21, 8, 0, 0)
        with Session(engine) as session:
            _seedPiSyncedDriveSummary(
                session, driveId=driveId, dataSource=None,
            )
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                parameters=["RPM"],
                samplesPerParameter=5,
            )
            compute_drive_summary(session, driveId)
            session.commit()

            row = session.execute(
                select(DriveSummary).where(DriveSummary.source_id == driveId)
            ).scalar_one()
            assert row.is_real is None


# =========================================================================
# Gap-detection tripwire
# =========================================================================


class TestGapDetection:
    """Gaps in realtime_data timestamps >5 min produce WARN log, not failure.

    Per US-350 acceptance criterion 6: 'for each drive_id, realtime_data rows
    share contiguous timestamps; gaps >5 min logged at WARN-level (defensive,
    not failing the compute).'
    """

    def test_gapDetectionWarns_largeGap_logsWarning(self, engine, caplog):
        driveId = 41
        startTime = datetime(2026, 5, 21, 10, 0, 0)
        with Session(engine) as session:
            _seedPiSyncedDriveSummary(session, driveId=driveId)

            # Five samples one second apart, then a 10-minute gap, then 5 more.
            session.add(
                RealtimeData(
                    source_id=1,
                    source_device="chi-eclipse-01",
                    timestamp=startTime,
                    parameter_name="RPM",
                    value=1000.0,
                    drive_id=driveId,
                    data_source="real",
                )
            )
            session.add(
                RealtimeData(
                    source_id=2,
                    source_device="chi-eclipse-01",
                    timestamp=startTime + timedelta(seconds=1),
                    parameter_name="RPM",
                    value=1100.0,
                    drive_id=driveId,
                    data_source="real",
                )
            )
            # Gap: jump forward by 10 minutes.
            session.add(
                RealtimeData(
                    source_id=3,
                    source_device="chi-eclipse-01",
                    timestamp=startTime + timedelta(minutes=10, seconds=1),
                    parameter_name="RPM",
                    value=1200.0,
                    drive_id=driveId,
                    data_source="real",
                )
            )
            session.commit()

            with caplog.at_level(logging.WARNING):
                returned = compute_drive_summary(session, driveId)
                session.commit()

            assert returned is not None  # gap doesn't fail the compute
            row = session.get(DriveSummary, returned)
            assert row.row_count == 3
            warning_messages = [
                r.message for r in caplog.records
                if r.levelno >= logging.WARNING
            ]
            assert any(
                "gap" in m.lower() for m in warning_messages
            ), f"expected gap warning, got: {warning_messages}"

    def test_gapDetection_contiguousTimestamps_noWarning(self, engine, caplog):
        driveId = 42
        startTime = datetime(2026, 5, 21, 10, 0, 0)
        with Session(engine) as session:
            _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                parameters=["RPM"],
                pollIntervalSeconds=1.0,
                samplesPerParameter=20,
            )

            with caplog.at_level(logging.WARNING):
                compute_drive_summary(session, driveId)
                session.commit()

            gap_warnings = [
                r.message for r in caplog.records
                if r.levelno >= logging.WARNING and "gap" in r.message.lower()
            ]
            assert gap_warnings == []
