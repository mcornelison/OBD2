################################################################################
# File Name: test_drive_summary_integration.py
# Purpose/Description: Integration tests wiring DriveDetector._startDrive through
#                      to SummaryRecorder (US-206).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-206) | Initial.
# ================================================================================
################################################################################

"""Integration tests for the _startDrive -> SummaryRecorder path."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive_id import clearCurrentDriveId
from src.pi.obdii.drive_summary import DRIVE_SUMMARY_TABLE, SummaryRecorder


class _StubSnapshotSource:
    """Stand-in for :class:`ObdDataLogger` exposing getLatestReadings()."""

    def __init__(self, snapshot: dict[str, float]) -> None:
        self._snapshot = dict(snapshot)

    def getLatestReadings(self) -> dict[str, float]:
        return dict(self._snapshot)


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "integ.db"), walMode=False)
    db.initialize()
    yield db
    clearCurrentDriveId()


@pytest.fixture()
def detector(freshDb: ObdDatabase) -> DriveDetector:
    """Detector with fast thresholds so tests don't wait the full duration."""
    config = {
        'pi': {
            'analysis': {
                'driveStartRpmThreshold': 500.0,
                'driveStartDurationSeconds': 0.0,  # instant confirmation
                'driveEndRpmThreshold': 0.0,
                'driveEndDurationSeconds': 0.0,
                'triggerAfterDrive': False,  # skip analytics in tests
            },
            'profiles': {'activeProfile': 'daily'},
        },
    }
    det = DriveDetector(config, statisticsEngine=None, database=freshDb)
    det.start()
    return det


class TestStartDriveInvokesRecorder:
    """_startDrive reads snapshot + calls captureDriveStart."""

    def test_coldStartWritesRowWithAmbient(
        self, freshDb: ObdDatabase, detector: DriveDetector
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        snapshot = _StubSnapshotSource(
            {'INTAKE_TEMP': 20.0, 'BATTERY_V': 12.6, 'BAROMETRIC_KPA': 101.0}
        )
        detector.setSummaryRecorder(recorder)
        detector.setReadingSnapshotSource(snapshot)

        # Process an RPM spike to trigger _startDrive
        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)  # one extra tick past threshold

        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE}"
            ).fetchone()
        assert row is not None, "drive_summary row should be written"
        assert row[0] == 20.0
        assert row[1] == 12.6
        assert row[2] == 101.0

    def test_warmRestartAfterEndDriveNullsAmbient(
        self, freshDb: ObdDatabase, detector: DriveDetector
    ) -> None:
        """After a clean endDrive, lastEngineState=KEY_OFF -> cold-start; after
        a second drive starts mid-stream without endDrive, the recorder
        would see RUNNING and null ambient -- assert this transition.
        """
        recorder = SummaryRecorder(database=freshDb)
        snapshotCold = _StubSnapshotSource(
            {'INTAKE_TEMP': 18.0, 'BATTERY_V': 12.4}
        )
        snapshotWarm = _StubSnapshotSource(
            {'INTAKE_TEMP': 85.0, 'BATTERY_V': 13.7}
        )
        detector.setSummaryRecorder(recorder)
        detector.setReadingSnapshotSource(snapshotCold)

        # First drive: cold-start
        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        # End the first drive cleanly (RPM=0 for duration=0 triggers immediate
        # endDrive in our test config).
        detector.processValue('RPM', 0.0)
        detector.processValue('RPM', 0.0)
        detector.processValue('SPEED', 0.0)

        # Second drive with warm snapshot -- but detector._lastEngineState
        # should now be KEY_OFF (set in _endDrive), so technically ambient
        # WILL be captured again.  This asserts the KEY_OFF transition.
        detector.setReadingSnapshotSource(snapshotWarm)
        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        with freshDb.connect() as conn:
            rows = conn.execute(
                f"SELECT drive_id, ambient_temp_at_start_c "
                f"FROM {DRIVE_SUMMARY_TABLE} ORDER BY drive_id"
            ).fetchall()
        assert len(rows) == 2
        # First drive cold: ambient captured.
        assert rows[0][1] == 18.0
        # Second drive AFTER clean endDrive: still cold-start (KEY_OFF).
        assert rows[1][1] == 85.0

    def test_missingRecorderDoesNotAbortDrive(
        self, freshDb: ObdDatabase, detector: DriveDetector
    ) -> None:
        """No summaryRecorder set -> drive still starts; no drive_summary row."""
        snapshot = _StubSnapshotSource({'INTAKE_TEMP': 15.0})
        detector.setReadingSnapshotSource(snapshot)
        # recorder not set -- detector should silently skip

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        assert detector.isDriving()  # drive started successfully
        with freshDb.connect() as conn:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {DRIVE_SUMMARY_TABLE}"
            ).fetchone()[0]
        assert count == 0

    def test_recorderExceptionIsSwallowed(
        self, freshDb: ObdDatabase, detector: DriveDetector
    ) -> None:
        """Recorder errors don't crash the drive path."""
        class ExplodingRecorder:
            def captureDriveStart(self, **_kw: object) -> None:
                raise RuntimeError("simulated recorder failure")

        detector.setSummaryRecorder(ExplodingRecorder())
        detector.setReadingSnapshotSource(
            _StubSnapshotSource({'INTAKE_TEMP': 20.0})
        )

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        assert detector.isDriving()  # drive still ran
