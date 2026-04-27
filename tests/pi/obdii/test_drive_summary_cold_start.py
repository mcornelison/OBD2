################################################################################
# File Name: test_drive_summary_cold_start.py
# Purpose/Description: Tests for SummaryRecorder cold-start backfill semantics
#                      (US-228 -- Drive 3 shipped NULL ambient/battery/baro
#                      because drive_start fires before first IAT/BATT/BARO
#                      arrives).  Covers the backfillFromSnapshot API that
#                      UPDATEs NULL fields without clobbering already-set
#                      values.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-228) | Initial -- backfill semantics unit tests.
# ================================================================================
################################################################################

"""Tests for :meth:`SummaryRecorder.backfillFromSnapshot` (US-228).

Scenario under test: ``drive_start`` fires before the first IAT /
BATTERY_V / BAROMETRIC_KPA reading is cached.  The INSERT at drive-
start writes NULLs; subsequent ticks need to UPDATE the row once the
readings arrive -- without clobbering already-captured non-NULL
values, and without re-enabling ambient capture on a warm restart.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_id import clearCurrentDriveId
from src.pi.obdii.drive_summary import (
    DRIVE_SUMMARY_TABLE,
    SummaryRecorder,
)
from src.pi.obdii.engine_state import EngineState


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "backfill.db"), walMode=False)
    db.initialize()
    yield db
    clearCurrentDriveId()


# ================================================================================
# Acceptance #1: bug reproduces with empty initial snapshot
# ================================================================================


class TestColdStartBugReproduces:
    """Acceptance #1 -- empty drive-start snapshot writes NULLs (Drive 3 case)."""

    def test_emptySnapshotAtDriveStartWritesAllNull(
        self, freshDb: ObdDatabase
    ) -> None:
        """Current captureDriveStart behaviour on Drive 3's empty snapshot."""
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=3,
            snapshot={},
            fromState=EngineState.UNKNOWN,
        )
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 3"
            ).fetchone()
        # Row exists (invariant: drive_summary row per drive_id),
        # but all three sensor columns are NULL (the bug).
        assert row is not None
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None


# ================================================================================
# backfillFromSnapshot: fills NULL columns
# ================================================================================


class TestBackfillFillsNullColumns:
    """backfillFromSnapshot populates NULL columns when readings arrive."""

    def test_backfillFillsAllThreeNullColumns(
        self, freshDb: ObdDatabase
    ) -> None:
        """After empty-snapshot INSERT, backfill with full snapshot fills all."""
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=3, snapshot={}, fromState=EngineState.UNKNOWN,
        )

        result = recorder.backfillFromSnapshot(
            driveId=3,
            snapshot={
                'INTAKE_TEMP': 19.0,
                'BATTERY_V': 13.4,
                'BAROMETRIC_KPA': 100.2,
            },
            fromState=EngineState.UNKNOWN,
        )

        assert result.filled == {'ambient', 'battery', 'baro'}
        assert result.complete is True
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 3"
            ).fetchone()
        assert row[0] == 19.0
        assert row[1] == 13.4
        assert row[2] == 100.2

    def test_backfillFillsOnlyWhatsAvailable(
        self, freshDb: ObdDatabase
    ) -> None:
        """Only columns with snapshot values (and still NULL in DB) get filled."""
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=4, snapshot={}, fromState=EngineState.UNKNOWN,
        )

        result = recorder.backfillFromSnapshot(
            driveId=4,
            snapshot={'BATTERY_V': 13.4},  # IAT + BARO still missing
            fromState=EngineState.UNKNOWN,
        )

        assert result.filled == {'battery'}
        assert result.complete is False  # ambient + baro still NULL
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 4"
            ).fetchone()
        assert row[0] is None
        assert row[1] == 13.4
        assert row[2] is None

    def test_backfillOnAlreadyFullRowIsNoOp(
        self, freshDb: ObdDatabase
    ) -> None:
        """All three columns already set -> backfill writes nothing + returns complete."""
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=5,
            snapshot={
                'INTAKE_TEMP': 18.0,
                'BATTERY_V': 12.5,
                'BAROMETRIC_KPA': 101.0,
            },
            fromState=EngineState.UNKNOWN,
        )

        result = recorder.backfillFromSnapshot(
            driveId=5,
            snapshot={
                'INTAKE_TEMP': 25.0,  # different value -- MUST NOT overwrite
                'BATTERY_V': 13.9,
                'BAROMETRIC_KPA': 99.0,
            },
            fromState=EngineState.UNKNOWN,
        )

        assert result.filled == set()
        assert result.complete is True
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 5"
            ).fetchone()
        # Original INSERT values preserved (invariant: never clobber non-NULL).
        assert row[0] == 18.0
        assert row[1] == 12.5
        assert row[2] == 101.0


# ================================================================================
# Warm restart: ambient stays NULL even if IAT arrives
# ================================================================================


class TestBackfillWarmRestartRule:
    """Invariant: warm-restart ambient stays NULL forever, regardless of IAT."""

    def test_warmRestartBackfillDoesNotFillAmbient(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=6, snapshot={}, fromState=EngineState.RUNNING,
        )

        result = recorder.backfillFromSnapshot(
            driveId=6,
            snapshot={
                'INTAKE_TEMP': 85.0,
                'BATTERY_V': 13.7,
                'BAROMETRIC_KPA': 100.4,
            },
            fromState=EngineState.RUNNING,
        )

        # ambient is NOT in filled because warm-restart rule -- but battery +
        # baro are.  complete=True because ambient is "not applicable" on
        # warm restart.
        assert 'ambient' not in result.filled
        assert 'battery' in result.filled
        assert 'baro' in result.filled
        assert result.complete is True
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 6"
            ).fetchone()
        assert row[0] is None  # ambient stays NULL
        assert row[1] == 13.7
        assert row[2] == 100.4


# ================================================================================
# Edge cases
# ================================================================================


class TestBackfillEdgeCases:
    """Missing rows, None snapshots, nonsense values."""

    def test_backfillOnMissingDriveIdReturnsNoOp(
        self, freshDb: ObdDatabase
    ) -> None:
        """backfill for a drive_id with no row yet is a no-op + complete=False."""
        recorder = SummaryRecorder(database=freshDb)
        result = recorder.backfillFromSnapshot(
            driveId=99,
            snapshot={'BATTERY_V': 12.5},
            fromState=EngineState.UNKNOWN,
        )
        assert result.filled == set()
        assert result.complete is False

    def test_backfillWithEmptySnapshotIsNoOp(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=10, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        result = recorder.backfillFromSnapshot(
            driveId=10, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        assert result.filled == set()
        assert result.complete is False

    def test_backfillWithNoneSnapshotIsNoOp(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=11, snapshot={}, fromState=EngineState.KEY_OFF,
        )
        result = recorder.backfillFromSnapshot(
            driveId=11, snapshot=None, fromState=EngineState.KEY_OFF,
        )
        assert result.filled == set()
        assert result.complete is False
