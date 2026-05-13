################################################################################
# File Name: test_drive_statistics_writer_post_us326.py
# Purpose/Description: Sprint 33 US-328 / I-028 / BL-015 Option C regression test
#                      -- the server-side Approach-1 drive_statistics writer
#                      (_writeDriveAnalytics -> _ensureDriveStatistics ->
#                      computeDriveStatistics) must produce per-parameter
#                      drive_statistics rows for a Pi-synced drive.  Pre-US-326
#                      this path silently produced ZERO rows: _writeDriveAnalytics
#                      calls _ensureDriveSummary first, which (pre-fix) looked the
#                      existing Pi-sync row up by the never-populated drive_id
#                      mirror column, missed, took the INSERT branch, and tripped
#                      UNIQUE(source_device, source_id) -> IntegrityError -> the
#                      whole transaction rolled back before _ensureDriveStatistics
#                      ever ran (exactly the "0 drive_statistics rows for Drive 11"
#                      symptom Spool observed).  US-326's lookup fix lets the
#                      transaction commit, so the Approach-1 writer now produces
#                      the rows -- which is why V0.27.7 ships the Pi-side table as
#                      a thin idempotent CREATE TABLE IF NOT EXISTS only (Option C)
#                      rather than reversing to a Pi-side writer (B-075 / V0.28).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Rex (US-328) | Initial -- BL-015 Option C server-side e2e lock-in.
# ================================================================================
################################################################################

"""Server-side Approach-1 ``drive_statistics`` writer e2e test (US-328 / I-028).

Why this exists
---------------

BL-015 / I-028 pre-flight established that ``drive_statistics`` is computed
server-side (Approach 1): ``enqueueAutoAnalysisForSync`` -> ``_writeDriveAnalytics``
-> ``_ensureDriveSummary`` then ``_ensureDriveStatistics`` -> ``computeDriveStatistics``,
which reads the synced ``realtime_data`` rows in the drive's window and upserts
one ``drive_statistics`` row per distinct ``parameter_name``.  Spool's "0 rows
for Drive 11" symptom was a *downstream* consequence of the I-026 bug US-326
fixed this sprint: ``_ensureDriveSummary`` raised ``IntegrityError`` on the
duplicate-key INSERT, the auto-analysis transaction rolled back, and
``_ensureDriveStatistics`` never committed (or never even ran).

This test exercises the realistic shape -- a Pi-synced ``drive_summary`` row
(``source_id`` set, ``drive_id`` mirror NULL) plus synced ``realtime_data`` --
then runs ``_writeDriveAnalytics`` and asserts the ``drive_statistics`` rows
land.  It is RED against pre-US-326 code (``IntegrityError`` in
``_ensureDriveSummary`` -> no ``drive_statistics`` rows) and GREEN with the
US-326 lookup fix in place.

It also documents the Option-C decision: the *Pi-side* ``drive_statistics``
table US-328 ships stays EMPTY -- the rows are produced *here*, server-side,
from synced ``realtime_data``.  See
:mod:`tests.pi.obdii.test_drive_statistics_pi_table_migration` for the Pi-side
half.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.server.api.sync import runSyncUpsert
from src.server.db.models import Base, DriveStatistic, DriveSummary
from src.server.services.analysis import _writeDriveAnalytics

# ================================================================================
# Fixtures / builders
# ================================================================================

_DEVICE = "chi-eclipse-01"
_DRIVE_ID = 11
_DRIVE_START = datetime(2026, 5, 12, 1, 0, 0)
_STEP_SECONDS = 3
# Three canonical PIDs interleaved -- one realtime_data row each per tick.
_PARAMS = ("RPM", "COOLANT_TEMP", "SPEED")
_TICKS = 40
_SAMPLES_PER_PARAM = _TICKS
_DRIVE_END = _DRIVE_START + timedelta(seconds=(_TICKS - 1) * _STEP_SECONDS)


def _newServerEngine():
    """In-memory SQLite engine with the modern ORM-driven server schema."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _valueFor(param: str, tick: int) -> float:
    """A deterministic, parameter-specific value series so the aggregates differ."""
    if param == "RPM":
        return 2000.0 + 25.0 * tick
    if param == "COOLANT_TEMP":
        return 70.0 + 0.5 * tick
    return 30.0 + float(tick)  # SPEED


def _piRealtimeRows(driveId: int) -> list[dict]:
    """Pi-shape realtime_data rows: one row per (param, tick), contiguous window."""
    rows: list[dict] = []
    rowId = 0
    for tick in range(_TICKS):
        ts = _DRIVE_START + timedelta(seconds=tick * _STEP_SECONDS)
        for param in _PARAMS:
            rowId += 1
            rows.append(
                {
                    "id": rowId,
                    "timestamp": ts.isoformat(),
                    "parameter_name": param,
                    "value": _valueFor(param, tick),
                    "unit": "",
                    "profile_id": "daily",
                    "drive_id": driveId,
                    "data_source": "real",
                }
            )
    return rows


def _piDriveSummaryRow(driveId: int) -> dict:
    """Pi-shape drive_summary sync row (6-col Pi schema) -- the wire shape.

    ``_renamePkToId`` renames the Pi PK ``drive_id`` -> ``id`` before
    transmission and ``runSyncUpsert`` maps ``id`` -> ``source_id``, so the row
    arrives server-side as ``source_id=driveId`` with the ``drive_id`` mirror
    column NULL -- the exact state that broke ``_ensureDriveSummary``'s lookup
    pre-US-326.
    """
    return {
        "id": driveId,
        "drive_start_timestamp": _DRIVE_START.isoformat() + "Z",
        "ambient_temp_at_start_c": 18.0,
        "starting_battery_v": 14.5,
        "barometric_kpa_at_start": 100.0,
        "data_source": "real",
    }


def _seedPiSync(session: Session, *, syncHistoryId: int = 1) -> None:
    """Run the real sync upsert with realtime_data + the Pi drive_summary row."""
    runSyncUpsert(
        session,
        deviceId=_DEVICE,
        batchId=f"batch-{syncHistoryId}",
        tables={
            "realtime_data": {"rows": _piRealtimeRows(_DRIVE_ID)},
            "drive_summary": {"rows": [_piDriveSummaryRow(_DRIVE_ID)]},
        },
        syncHistoryId=syncHistoryId,
    )


def _runDriveAnalyticsWriter(session: Session) -> list[int]:
    """Invoke the writer the way ``enqueueAutoAnalysisForSync`` does at drive_end."""
    return _writeDriveAnalytics(
        session, _DEVICE, [(_DRIVE_START, _DRIVE_END, _DRIVE_ID)],
    )


def _driveStatisticRows(session: Session) -> list[DriveStatistic]:
    return list(
        session.execute(
            select(DriveStatistic).order_by(DriveStatistic.parameter_name)
        ).scalars().all()
    )


# ================================================================================
# 1) Approach-1 writer produces drive_statistics rows for a Pi-synced drive
# ================================================================================


class TestApproach1WriterProducesDriveStatistics:
    """Post-US-326, ``_writeDriveAnalytics`` lands per-parameter drive_statistics."""

    def test_piSyncedDrive_thenWriteDriveAnalytics_producesPerParameterRows(self) -> None:
        engine = _newServerEngine()
        with Session(engine) as session:
            _seedPiSync(session)
            session.commit()

        # Pre-condition: Pi-sync drive_summary row exists, drive_id mirror NULL,
        # and no drive_statistics rows yet -- the observed Drive 11 state.
        with Session(engine) as session:
            summaries = list(session.execute(select(DriveSummary)).scalars().all())
            assert len(summaries) == 1
            assert summaries[0].source_id == _DRIVE_ID
            assert summaries[0].drive_id is None
            assert _driveStatisticRows(session) == []

        # Run the auto-analysis writer step (RED pre-US-326: IntegrityError in
        # _ensureDriveSummary rolls this back before _ensureDriveStatistics).
        with Session(engine) as session:
            summaryIds = _runDriveAnalyticsWriter(session)
            session.commit()

        assert len(summaryIds) == 1
        serverDriveId = summaryIds[0]

        with Session(engine) as session:
            stats = _driveStatisticRows(session)
            # One row per distinct parameter_name.
            assert {s.parameter_name for s in stats} == set(_PARAMS)
            assert len(stats) == len(_PARAMS)
            for s in stats:
                # drive_statistics.drive_id keys the SERVER drive_summary.id
                # (matches proposeCalibration's join), NOT the Pi-local drive_id.
                assert s.drive_id == serverDriveId
                assert s.sample_count == _SAMPLES_PER_PARAM
                assert s.min_value is not None
                assert s.max_value is not None
                assert s.avg_value is not None
                assert s.min_value <= s.avg_value <= s.max_value

            byName = {s.parameter_name: s for s in stats}
            # Spot-check one series so the aggregates aren't all coincidentally equal.
            rpm = byName["RPM"]
            assert rpm.min_value == pytest.approx(_valueFor("RPM", 0))
            assert rpm.max_value == pytest.approx(_valueFor("RPM", _TICKS - 1))

        # The drive_summary row was reconciled in place (US-326), not duplicated.
        with Session(engine) as session:
            summaries = list(session.execute(select(DriveSummary)).scalars().all())
            assert len(summaries) == 1
            assert summaries[0].id == serverDriveId
            assert summaries[0].drive_id == _DRIVE_ID
            assert summaries[0].start_time == _DRIVE_START

    def test_writeDriveAnalytics_isIdempotentOnReRun(self) -> None:
        """Re-running converges: still one drive_statistics row per parameter."""
        engine = _newServerEngine()
        with Session(engine) as session:
            _seedPiSync(session)
            session.commit()

        with Session(engine) as session:
            firstIds = _runDriveAnalyticsWriter(session)
            session.commit()
        with Session(engine) as session:
            secondIds = _runDriveAnalyticsWriter(session)
            session.commit()

        assert firstIds == secondIds
        with Session(engine) as session:
            stats = _driveStatisticRows(session)
            assert {s.parameter_name for s in stats} == set(_PARAMS)
            assert len(stats) == len(_PARAMS)
            assert all(s.drive_id == firstIds[0] for s in stats)
            assert all(s.sample_count == _SAMPLES_PER_PARAM for s in stats)


# ================================================================================
# 2) Option-C documentation: the Pi-side table stays empty; the server computes
# ================================================================================


class TestOptionCContract:
    """The rows live server-side -- the Pi-side ``drive_statistics`` table is empty."""

    def test_serverIsTheProducer_noPiSideWriterInvolved(self) -> None:
        """No Pi-computed rows are synced; the server computes from realtime_data.

        ``_seedPiSync`` pushes ``realtime_data`` + ``drive_summary`` only -- it
        never pushes ``drive_statistics`` rows (there is no Pi-side writer in
        Option C).  The server-side rows appear purely because
        ``_writeDriveAnalytics`` computed them.
        """
        engine = _newServerEngine()
        with Session(engine) as session:
            _seedPiSync(session)
            session.commit()
            # Nothing computed yet -- the Pi sent no drive_statistics rows.
            assert _driveStatisticRows(session) == []

        with Session(engine) as session:
            _runDriveAnalyticsWriter(session)
            session.commit()

        with Session(engine) as session:
            assert len(_driveStatisticRows(session)) == len(_PARAMS)
