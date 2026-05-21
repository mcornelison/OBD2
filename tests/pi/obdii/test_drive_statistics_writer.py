################################################################################
# File Name: test_drive_statistics_writer.py
# Purpose/Description: Sprint 40 / V0.27.16 US-349 (US-328-redo, I-040)
#                      regression test for the missing Pi-side drive_statistics
#                      writer.  V0.27.7 US-328 shipped the schema with NO
#                      writer wired (Option C "table only", explicit in
#                      database_schema.py:642).  Across drives 11-18 incl.
#                      fresh real drives 17+18 captured 2026-05-20, the Pi
#                      drive_statistics table holds zero rows ever.  This
#                      test file is the discriminator + acceptance gate for
#                      the new writer: RED pre-fix (no DriveStatisticsRecorder
#                      class exists), GREEN post-fix (per-parameter aggregates
#                      land on _endDrive).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-349) | Initial -- I-040 / US-328-redo writer regression
#               |              | test.  Two test classes mirror SummaryRecorder
#               |              | acceptance discipline: TestDriveStatisticsRecorder
#               |              | exercises the recorder in isolation against a
#               |              | live ObdDatabase populated with synthetic
#               |              | realtime_data; TestDriveDetectorEndDriveWiring
#               |              | exercises the _endDrive -> recorder call path
#               |              | (the seam US-328 V0.27.7 forgot to wire).
# ================================================================================
################################################################################

"""Pi-side ``drive_statistics`` writer regression tests (US-349 / I-040).

Why this exists
---------------

V0.27.7 US-328 shipped ``passes:true`` with a thin migration test (which still
lives at ``tests/pi/obdii/test_drive_statistics_pi_table_migration.py``) but
NO writer.  ``database_schema.py:642`` is explicit: ``Option C (hybrid) --
table only, no writer.``  Drives 11-18 (incl. fresh real drives 17+18 from
2026-05-20) all carry zero ``drive_statistics`` rows.

The acceptance discipline lesson (Tester I-040 +
``offices/tester/knowledge/feedback-tester-validate-deploy-fixes-irl-not-just-code.md``)
is that the synthetic test in V0.27.7 only asserted "table exists" -- it did
NOT exercise the writer-trigger seam (drive_end -> recorder.recordDriveStatistics
-> realtime_data aggregation -> drive_statistics INSERT).  This test file
closes that gap with two complementary surfaces:

1. **TestDriveStatisticsRecorder** -- the new ``DriveStatisticsRecorder``
   class in ``src.pi.obdii.drive_statistics``.  Aggregate math, idempotent
   replay, drive isolation, empty-drive no-op, n=1 edge case.
2. **TestDriveDetectorEndDriveWiring** -- the
   ``DriveDetector._endDrive`` -> ``recorder.recordDriveStatistics`` seam.
   The bug shape that produced I-040: V0.27.7 left this seam unwired so
   the recorder (if it had existed) would never fire.  These tests fail
   RED if the wiring is missing AND fail RED if the recorder import fails.

Discriminator
-------------

``TestDriveDetectorEndDriveWiring.test_endDrive_callsDriveStatisticsRecorder_
withClosingDriveId`` is the integration discriminator -- it asserts that a
detector with a recorder wired calls ``recordDriveStatistics(driveId)``
EXACTLY ONCE on the natural RPM-debounce-driven _endDrive path, with the
drive_id that was active at drive-end.  This is the discriminator the
V0.27.7 synthetic test should have had.

The IRL acceptance gate (CIO real drive -> Pi-side ``drive_statistics``
post-drive ``SELECT drive_id, COUNT(*) ... GROUP BY drive_id`` returns
>=1 row per parameter_name) lives downstream of US-347 in-car drill, mirrors
US-348 acceptance pattern, and is NOT in scope for this synthetic test file.
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pi.obdii.database import ObdDatabase

# The module under test ships with this story (US-349).  Pre-fix import
# fails with ModuleNotFoundError -- the entire test file errors out collection
# and produces the load-bearing RED signal.
from src.pi.obdii.drive_statistics import (  # noqa: E402
    DRIVE_STATISTICS_TABLE,
    DriveStatisticsRecorder,
    DriveStatisticsResult,
)

REALTIME_DATA_TABLE = "realtime_data"


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """A live ObdDatabase with the full schema (incl. drive_statistics + realtime_data).

    Mirrors the freshDb fixture in test_drive_statistics_pi_table_migration.py so
    the writer test runs against the same shape the migration test pins.
    """
    db = ObdDatabase(str(tmp_path / "test_drivestats_writer.db"), walMode=False)
    db.initialize()
    return db


def _seedRealtimeData(
    db: ObdDatabase,
    *,
    driveId: int,
    rows: list[tuple[str, float]],
) -> None:
    """Helper -- seed the realtime_data table for one drive.

    Each row is ``(parameter_name, value)``.  ``drive_id`` is stamped from
    ``driveId``.  ``profile_id`` is NULL to side-step the FK constraint
    against the (unpopulated) ``profiles`` table.  ``timestamp`` defaults
    to the schema's canonical ISO-8601 UTC.
    """
    with db.connect() as conn:
        for paramName, value in rows:
            conn.execute(
                f"INSERT INTO {REALTIME_DATA_TABLE} "
                "(parameter_name, value, profile_id, drive_id) "
                "VALUES (?, ?, NULL, ?)",
                (paramName, float(value), int(driveId)),
            )


def _readDriveStatistics(
    db: ObdDatabase, driveId: int,
) -> list[dict[str, Any]]:
    """Helper -- read drive_statistics rows for a drive_id, dict-shape."""
    with db.connect() as conn:
        cursor = conn.execute(
            f"SELECT drive_id, parameter_name, min_value, max_value, "
            f"avg_value, std_dev, outlier_min, outlier_max, sample_count "
            f"FROM {DRIVE_STATISTICS_TABLE} WHERE drive_id = ? "
            f"ORDER BY parameter_name",
            (int(driveId),),
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]


# ================================================================================
# TestDriveStatisticsRecorder -- the new writer in isolation
# ================================================================================


class TestDriveStatisticsRecorder:
    """The writer reads realtime_data + writes per-parameter aggregates."""

    def test_recordDriveStatistics_writesOneRowPerParameter_forDriveIdInRealtimeData(
        self, freshDb: ObdDatabase,
    ) -> None:
        """One drive_statistics row per distinct parameter_name in realtime_data."""
        _seedRealtimeData(freshDb, driveId=42, rows=[
            ("RPM", 800), ("RPM", 1500), ("RPM", 2400), ("RPM", 1800),
            ("SPEED", 0), ("SPEED", 25), ("SPEED", 60), ("SPEED", 45),
            ("COOLANT_TEMP", 85.0), ("COOLANT_TEMP", 86.5), ("COOLANT_TEMP", 87.0),
        ])
        recorder = DriveStatisticsRecorder(database=freshDb)

        result = recorder.recordDriveStatistics(42)

        rows = _readDriveStatistics(freshDb, driveId=42)
        params = {r["parameter_name"] for r in rows}
        assert params == {"RPM", "SPEED", "COOLANT_TEMP"}
        assert isinstance(result, DriveStatisticsResult)
        assert result.driveId == 42
        assert result.parametersWritten == frozenset({"RPM", "SPEED", "COOLANT_TEMP"})

    def test_recordDriveStatistics_computesCorrectAggregates_minMaxAvgSampleCount(
        self, freshDb: ObdDatabase,
    ) -> None:
        """min/max/avg/sample_count are arithmetically correct vs the raw values."""
        values = [800.0, 1500.0, 2400.0, 1800.0, 1000.0]
        _seedRealtimeData(
            freshDb, driveId=7,
            rows=[("RPM", v) for v in values],
        )
        recorder = DriveStatisticsRecorder(database=freshDb)

        recorder.recordDriveStatistics(7)

        rows = _readDriveStatistics(freshDb, driveId=7)
        assert len(rows) == 1
        row = rows[0]
        assert row["min_value"] == pytest.approx(min(values))
        assert row["max_value"] == pytest.approx(max(values))
        assert row["avg_value"] == pytest.approx(sum(values) / len(values))
        assert row["sample_count"] == len(values)

    def test_recordDriveStatistics_computesStdDev_andOutlierBoundsAtMeanPlusMinusTwoStd(
        self, freshDb: ObdDatabase,
    ) -> None:
        """std_dev = sample stdev; outlier_min/max = mean +/- 2 * std_dev."""
        values = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
        _seedRealtimeData(
            freshDb, driveId=99,
            rows=[("BATTERY_V", v) for v in values],
        )
        recorder = DriveStatisticsRecorder(database=freshDb)

        recorder.recordDriveStatistics(99)

        rows = _readDriveStatistics(freshDb, driveId=99)
        assert len(rows) == 1
        row = rows[0]
        expectedMean = sum(values) / len(values)
        expectedStd = statistics.stdev(values)
        assert row["std_dev"] == pytest.approx(expectedStd)
        assert row["outlier_min"] == pytest.approx(expectedMean - 2 * expectedStd)
        assert row["outlier_max"] == pytest.approx(expectedMean + 2 * expectedStd)

    def test_recordDriveStatistics_singleSample_stdDevAndOutliersAreNone(
        self, freshDb: ObdDatabase,
    ) -> None:
        """n=1 cannot compute sample stdev -- the row carries NULL std/outliers."""
        _seedRealtimeData(
            freshDb, driveId=11, rows=[("BAROMETRIC_KPA", 101.3)],
        )
        recorder = DriveStatisticsRecorder(database=freshDb)

        recorder.recordDriveStatistics(11)

        rows = _readDriveStatistics(freshDb, driveId=11)
        assert len(rows) == 1
        row = rows[0]
        assert row["min_value"] == pytest.approx(101.3)
        assert row["max_value"] == pytest.approx(101.3)
        assert row["avg_value"] == pytest.approx(101.3)
        assert row["sample_count"] == 1
        assert row["std_dev"] is None
        assert row["outlier_min"] is None
        assert row["outlier_max"] is None

    def test_recordDriveStatistics_isIdempotent_replayProducesSameRows(
        self, freshDb: ObdDatabase,
    ) -> None:
        """Running twice does not create duplicates -- existing rows are replaced."""
        _seedRealtimeData(freshDb, driveId=3, rows=[
            ("RPM", 1000), ("RPM", 2000),
            ("SPEED", 30), ("SPEED", 50),
        ])
        recorder = DriveStatisticsRecorder(database=freshDb)

        firstResult = recorder.recordDriveStatistics(3)
        secondResult = recorder.recordDriveStatistics(3)

        rows = _readDriveStatistics(freshDb, driveId=3)
        assert len(rows) == 2  # RPM + SPEED, NOT 4
        assert firstResult.parametersWritten == secondResult.parametersWritten

    def test_recordDriveStatistics_noRowsForDriveId_returnsEmptyResult_writesNothing(
        self, freshDb: ObdDatabase,
    ) -> None:
        """A drive with no realtime_data is a clean no-op (not an error)."""
        recorder = DriveStatisticsRecorder(database=freshDb)

        result = recorder.recordDriveStatistics(999)

        assert result.parametersWritten == frozenset()
        assert result.totalSamples == 0
        rows = _readDriveStatistics(freshDb, driveId=999)
        assert rows == []

    def test_recordDriveStatistics_onlyTargetsRequestedDriveId_ignoresOthers(
        self, freshDb: ObdDatabase,
    ) -> None:
        """Drive isolation -- writing drive 5 does not touch drive 6."""
        _seedRealtimeData(freshDb, driveId=5, rows=[("RPM", 1000), ("RPM", 2000)])
        _seedRealtimeData(freshDb, driveId=6, rows=[("RPM", 3000), ("RPM", 4000)])
        recorder = DriveStatisticsRecorder(database=freshDb)

        recorder.recordDriveStatistics(5)

        rowsForFive = _readDriveStatistics(freshDb, driveId=5)
        rowsForSix = _readDriveStatistics(freshDb, driveId=6)
        assert len(rowsForFive) == 1
        assert rowsForFive[0]["avg_value"] == pytest.approx(1500.0)
        # Drive 6's realtime_data exists but no drive_statistics row was written
        # for it (the recorder only wrote drive 5).
        assert rowsForSix == []

    def test_recordDriveStatistics_excludesNullDriveIdRowsFromAggregation(
        self, freshDb: ObdDatabase,
    ) -> None:
        """Untagged realtime_data (drive_id=NULL) does not pollute any drive."""
        # Drive 8: two real rows + (insert a NULL-drive_id row directly).
        # profile_id NULL throughout to side-step FK to profiles(id).
        with freshDb.connect() as conn:
            conn.execute(
                f"INSERT INTO {REALTIME_DATA_TABLE} "
                "(parameter_name, value, profile_id, drive_id) "
                "VALUES (?, ?, NULL, ?)",
                ("RPM", 1000.0, 8),
            )
            conn.execute(
                f"INSERT INTO {REALTIME_DATA_TABLE} "
                "(parameter_name, value, profile_id, drive_id) "
                "VALUES (?, ?, NULL, ?)",
                ("RPM", 2000.0, 8),
            )
            conn.execute(
                f"INSERT INTO {REALTIME_DATA_TABLE} "
                "(parameter_name, value, profile_id, drive_id) "
                "VALUES (?, ?, NULL, NULL)",
                ("RPM", 99999.0),
            )
        recorder = DriveStatisticsRecorder(database=freshDb)

        recorder.recordDriveStatistics(8)

        rows = _readDriveStatistics(freshDb, driveId=8)
        assert len(rows) == 1
        # The 99999 row (drive_id=NULL) MUST NOT pollute avg.
        assert rows[0]["avg_value"] == pytest.approx(1500.0)
        assert rows[0]["sample_count"] == 2

    def test_recordDriveStatistics_totalSamples_sumsAcrossParameters(
        self, freshDb: ObdDatabase,
    ) -> None:
        """The result's totalSamples is the sum of sample_count across rows."""
        _seedRealtimeData(freshDb, driveId=21, rows=[
            ("RPM", 800), ("RPM", 1500), ("RPM", 2400),
            ("SPEED", 0), ("SPEED", 25),
        ])
        recorder = DriveStatisticsRecorder(database=freshDb)

        result = recorder.recordDriveStatistics(21)

        assert result.totalSamples == 5

    def test_recordDriveStatistics_writerNeverComputesNaNForStdDev_pathologicalInputs(
        self, freshDb: ObdDatabase,
    ) -> None:
        """All-equal values produce std=0 (not NaN), outliers degenerate to mean."""
        _seedRealtimeData(freshDb, driveId=4, rows=[
            ("RPM", 1500.0), ("RPM", 1500.0), ("RPM", 1500.0),
        ])
        recorder = DriveStatisticsRecorder(database=freshDb)

        recorder.recordDriveStatistics(4)

        rows = _readDriveStatistics(freshDb, driveId=4)
        assert len(rows) == 1
        row = rows[0]
        # statistics.stdev of all-equal is 0.0 (not NaN, not error).
        assert row["std_dev"] == pytest.approx(0.0)
        assert math.isfinite(row["std_dev"])
        assert row["outlier_min"] == pytest.approx(1500.0)
        assert row["outlier_max"] == pytest.approx(1500.0)


# ================================================================================
# TestDriveDetectorEndDriveWiring -- the seam V0.27.7 forgot to wire
# ================================================================================


class TestDriveDetectorEndDriveWiring:
    """``DriveDetector._endDrive`` calls the recorder when wired (US-349 seam)."""

    def _buildDetector(
        self,
        *,
        statisticsEngine: Any | None = None,
        driveStatisticsRecorder: Any | None = None,
    ) -> Any:
        """Build a DriveDetector with the new optional kwarg.

        Pre-fix this raises TypeError (constructor doesn't accept the new
        kwarg).  Post-fix the kwarg is accepted as a 1st-class param.
        """
        from src.pi.obdii.drive.detector import DriveDetector
        config = {
            "pi": {
                "analysis": {
                    "driveStartRpmThreshold": 500,
                    "driveStartDurationSeconds": 0.0,
                    "driveEndRpmThreshold": 0,
                    "driveEndDurationSeconds": 0.0,
                    "triggerAfterDrive": False,
                    "driveSummaryBackfillSeconds": 0.0,
                },
                "profiles": {"activeProfile": "default"},
            }
        }
        return DriveDetector(
            config=config,
            statisticsEngine=statisticsEngine,
            database=None,
            driveStatisticsRecorder=driveStatisticsRecorder,
        )

    def test_driveDetector_acceptsDriveStatisticsRecorder_inConstructor(
        self,
    ) -> None:
        """The new kwarg is accepted at construction time (no TypeError)."""
        recorder = MagicMock()
        detector = self._buildDetector(driveStatisticsRecorder=recorder)

        # The detector exposes a setter -- mirror SummaryRecorder shape.
        assert hasattr(detector, "setDriveStatisticsRecorder")
        # And the constructor-provided recorder is stored.
        assert detector._driveStatisticsRecorder is recorder

    def test_driveDetector_acceptsRecorderViaSetter_late(self) -> None:
        """The setter wires a recorder constructed after detector init."""
        detector = self._buildDetector()
        assert detector._driveStatisticsRecorder is None

        recorder = MagicMock()
        detector.setDriveStatisticsRecorder(recorder)

        assert detector._driveStatisticsRecorder is recorder

    def test_endDrive_callsRecorder_withClosingDriveId_whenWired(self) -> None:
        """The discriminator: _endDrive -> recorder.recordDriveStatistics(driveId).

        Bug shape that produced I-040: V0.27.7 left this seam unwired.
        Post-fix, _endDrive invokes the recorder exactly once with the
        drive_id that was active at drive-end.
        """
        recorder = MagicMock()
        detector = self._buildDetector(driveStatisticsRecorder=recorder)
        detector.start()

        # Force a session active + a known drive_id so _endDrive can be called.
        # We mint a drive_id via the public drive_id helper so getCurrentDriveId
        # returns it (the recorder call uses getCurrentDriveId per the wiring).
        from src.pi.obdii.drive_id import setCurrentDriveId
        setCurrentDriveId(123)
        try:
            # Stage the detector into RUNNING with a session, then _endDrive.
            from datetime import datetime

            from src.pi.obdii.drive.types import DriveSession, DriveState
            detector._driveState = DriveState.RUNNING
            detector._currentSession = DriveSession(
                startTime=datetime.now(),
                profileId="default",
            )

            detector._endDrive()
        finally:
            setCurrentDriveId(None)

        recorder.recordDriveStatistics.assert_called_once_with(123)

    def test_endDrive_skipsRecorder_whenNotWired_noException(self) -> None:
        """No recorder -> _endDrive proceeds cleanly (legacy callsite invariant)."""
        detector = self._buildDetector()  # no recorder
        detector.start()
        from src.pi.obdii.drive_id import setCurrentDriveId
        setCurrentDriveId(456)
        try:
            from datetime import datetime

            from src.pi.obdii.drive.types import DriveSession, DriveState
            detector._driveState = DriveState.RUNNING
            detector._currentSession = DriveSession(
                startTime=datetime.now(),
                profileId="default",
            )

            # Must not raise.
            detector._endDrive()
        finally:
            setCurrentDriveId(None)

    def test_endDrive_swallowsRecorderException_drive_endStillProceeds(self) -> None:
        """Recorder failure must not block drive_end -- detector is the SSOT."""
        recorder = MagicMock()
        recorder.recordDriveStatistics.side_effect = RuntimeError("simulated DB error")
        detector = self._buildDetector(driveStatisticsRecorder=recorder)
        detector.start()
        from src.pi.obdii.drive_id import setCurrentDriveId
        setCurrentDriveId(789)
        try:
            from datetime import datetime

            from src.pi.obdii.drive.types import DriveSession, DriveState
            detector._driveState = DriveState.RUNNING
            detector._currentSession = DriveSession(
                startTime=datetime.now(),
                profileId="default",
            )

            # The exception is caught + logged -- _endDrive completes.
            detector._endDrive()
        finally:
            setCurrentDriveId(None)

        # Session was cleared (drive_end completed despite the exception).
        assert detector._currentSession is None
        recorder.recordDriveStatistics.assert_called_once()

    def test_endDrive_skipsRecorder_whenNoDriveIdInContext(self) -> None:
        """getCurrentDriveId() is None -> recorder NOT called (defensive)."""
        recorder = MagicMock()
        detector = self._buildDetector(driveStatisticsRecorder=recorder)
        detector.start()
        from src.pi.obdii.drive_id import setCurrentDriveId
        setCurrentDriveId(None)
        try:
            from datetime import datetime

            from src.pi.obdii.drive.types import DriveSession, DriveState
            detector._driveState = DriveState.RUNNING
            detector._currentSession = DriveSession(
                startTime=datetime.now(),
                profileId="default",
            )

            detector._endDrive()
        finally:
            setCurrentDriveId(None)

        recorder.recordDriveStatistics.assert_not_called()
